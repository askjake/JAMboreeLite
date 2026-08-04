"""Automatic SGS PIN pairing using the live aBot/JAMboree video frame.

The OCR voting pipeline is ported from the running aBotTesty ``montjac`` code,
while credential handling is hardened: issued secrets go to the OS keyring and
are never logged or returned by API responses.  Joey aliases are resolved to
their host Hopper before pairing.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .core.credentials import CredentialManager
from .sgs_lib import get_local_iface_mac, sgs_get_receiver_id

log = logging.getLogger(__name__)
SGS_PORTS: Tuple[int, ...] = (8080, 80)
HTTP_TIMEOUT_S = 8.0
PIN_MIN_DIGITS = 4
PIN_MAX_DIGITS = 8
PIN_PREFERRED_DIGITS = 6
PIN_READ_TIMEOUT_S = 45.0
PIN_READ_INTERVAL_S = 1.5
PIN_STABLE_READS = 2
MAX_PIN_ATTEMPTS = 3
VERIFY_SETTLE_S = 2.0
SCREEN_CHANGE_THRESHOLD = 1.5
PAIR_SCREEN_KEYWORDS: Tuple[str, ...] = (
    "pair", "pairing", "code", "pin", "authorize", "authorise",
    "remote access", "device", "connect",
)

_get_frame: Optional[Callable[[], Any]] = None
_store: Any = None
_ctl: Any = None
_CFG: Dict[str, Any] = {}
_lock = threading.RLock()
_state: Dict[str, Any] = {
    "phase": "idle",
    "active": False,
    "last_result": {},
    "history": [],
    "alias": None,
}


def set_dependencies(
    *,
    get_frame: Optional[Callable[[], Any]] = None,
    store: Any = None,
    ctl: Any = None,
    CFG: Optional[Dict[str, Any]] = None,
) -> None:
    global _get_frame, _store, _ctl, _CFG
    if get_frame is not None:
        _get_frame = get_frame
    if store is not None:
        _store = store
    if ctl is not None:
        _ctl = ctl
    if CFG is not None:
        _CFG = CFG
    log.info(
        "SGS autopair dependencies registered (frame=%s ctl=%s store=%s)",
        _get_frame is not None, _ctl is not None, _store is not None,
    )


def _set_phase(phase: str, **detail: Any) -> None:
    with _lock:
        _state["phase"] = phase
        if detail:
            _state.setdefault("detail", {}).update(detail)
        _state["history"] = (_state.get("history") or [])[-40:] + [
            {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "phase": phase, **detail}
        ]
    # PIN values and credentials are deliberately never included in detail.
    log.info("SGS autopair phase=%s %s", phase, " ".join(f"{k}={v}" for k, v in detail.items()))


def get_status() -> Dict[str, Any]:
    with _lock:
        return {
            "phase": _state.get("phase"),
            "active": bool(_state.get("active")),
            "alias": _state.get("alias"),
            "detail": dict(_state.get("detail") or {}),
            "last_result": dict(_state.get("last_result") or {}),
            "history": list(_state.get("history") or [])[-15:],
        }


def _entry(alias: str) -> Dict[str, Any]:
    return dict(_store.get(alias) or {}) if _store is not None else {}


def _resolve_pair_target(alias: str) -> tuple[str, Dict[str, Any]]:
    requested = str(alias).strip()
    entry = _entry(requested)
    if not entry:
        raise ValueError(f"alias {requested!r} not found")
    if str(entry.get("role", "hopper")).lower() == "joey" or entry.get("master_stb"):
        host_alias = str(entry.get("host") or entry.get("master_stb") or "").strip()
        host = _entry(host_alias)
        if not host:
            raise ValueError(f"Joey {requested!r} has invalid host Hopper {host_alias!r}")
        return host_alias, host
    return requested, entry


def _receiver_id() -> str:
    return sgs_get_receiver_id()


def _local_mac() -> str:
    return get_local_iface_mac()


def credentials_status(alias: str) -> Dict[str, Any]:
    pair_alias, entry = _resolve_pair_target(alias)
    status = CredentialManager.status(pair_alias, _store.document() if _store else None)
    stored_rid = entry.get("pair_rid")
    current_rid = _receiver_id()
    return {
        "requested_alias": str(alias),
        "pair_alias": pair_alias,
        "paired": bool(status["stored"]),
        "secure_backend": status.get("backend"),
        "username_present": status.get("username_present"),
        "password_present": status.get("password_present"),
        "paired_ts": entry.get("paired_ts"),
        "pair_rid": stored_rid,
        "current_rid": current_rid,
        "rid_matches": (stored_rid == current_rid) if stored_rid else None,
        "stale_rid": bool(stored_rid and stored_rid != current_rid),
    }


def _pair_envelope(stb_id: str, command: str, **extra: Any) -> Dict[str, Any]:
    payload = {
        "command": command,
        "receiver": _receiver_id(),
        "stb": stb_id,
        "app": "JAMboreeLite",
        "name": "JAMboreeLite",
        "type": "web",
        "id": "S9",
        "mac": _local_mac(),
    }
    payload.update(extra)
    return payload


def _safe_response(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if key not in {"name", "passwd", "password", "login", "pin", "text"}
    }


def _post_noauth(ip: str, payload: Dict[str, Any], port_hint: Any = None) -> Dict[str, Any]:
    import requests

    ports: List[int] = []
    try:
        if port_hint:
            ports.append(int(port_hint))
    except Exception:
        pass
    ports += [port for port in SGS_PORTS if port not in ports]
    last: Dict[str, Any] = {"result": -1, "error": "no_endpoint_tried"}
    for port in ports:
        url = f"http://{ip}:{port}/sgs_noauth"
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=HTTP_TIMEOUT_S,
                headers={"Content-Type": "application/json"},
            )
        except Exception as exc:
            last = {"result": -1, "error": "transport", "detail": str(exc), "url": url}
            continue
        try:
            data = response.json()
            if isinstance(data, dict):
                data.setdefault("_url", url)
                data.setdefault("_http_status", response.status_code)
                if data.get("result") == 1:
                    return data
                last = data
                continue
        except Exception:
            pass
        last = {
            "result": -13 if response.status_code in (401, 403) else -3,
            "error": "auth_required_or_opt_in_disabled"
            if response.status_code in (401, 403)
            else "json_parse_failed",
            "http_status": response.status_code,
            "url": url,
        }
    return last
_DIGIT_FIXUPS = {
    "O": "0", "o": "0", "D": "0", "Q": "0",
    "I": "1", "l": "1", "|": "1", "i": "1", "!": "1",
    "Z": "2", "z": "2",
    "A": "4",
    "S": "5", "s": "5",
    "G": "6", "b": "6",
    "T": "7",
    "B": "8",
    "g": "9", "q": "9",
}

# "Pairing code is 123456", "Enter code: 1234", "PIN 123456"
_LABELLED_PIN_RE = re.compile(
    r"(?:pair(?:ing)?[\s_-]*(?:code|pin)?|code|pin|passcode)"
    r"[\s:=.\-]{0,14}"
    r"([0-9OoDIl|SsBGgbqZzAT]{%d,%d})" % (PIN_MIN_DIGITS, PIN_MAX_DIGITS),
    re.I,
)
_BARE_DIGITS_RE = re.compile(r"(?<![0-9])([0-9]{%d,%d})(?![0-9])"
                             % (PIN_MIN_DIGITS, PIN_MAX_DIGITS))


def _normalise_digits(raw: str) -> str:
    """Map OCR look-alikes to digits and strip everything else."""
    fixed = "".join(_DIGIT_FIXUPS.get(ch, ch) for ch in (raw or ""))
    return re.sub(r"[^0-9]", "", fixed)


def _ocr(img, psm: int = 6, digits_only: bool = False, strict: bool = False) -> str:
    try:
        import pytesseract
    except Exception:
        return ""
    cfg = f"--oem 3 --psm {psm} -c user_defined_dpi=300"
    if digits_only:
        # strict: digits only, so the classifier must choose the nearest digit.
        # loose:  also allow look-alike letters, repaired by _normalise_digits().
        cfg += (" -c tessedit_char_whitelist=0123456789" if strict
                else " -c tessedit_char_whitelist=0123456789OoDdIl|SsBGgbqZzAT")
    try:
        return pytesseract.image_to_string(img, config=cfg) or ""
    except Exception as exc:
        log.debug("sgs_autopair: OCR error: %s", exc)
        return ""


# Tesseract cost scales with pixel count, and a 0.5x0.4 crop of a 1080p frame
# upscaled 2.6x is already 2496 px wide.  Cap it: beyond ~1800 px the OCR gets
# slower without getting better on TV-sized glyphs.
MAX_OCR_WIDTH: int = 1800


def has_text_like_content(img) -> bool:
    """Cheap gate: does this crop plausibly contain rendered glyphs?

    Running the full pass matrix over an empty region is what made a single poll
    take ~40 s on a banner-style pairing screen: the centred-modal crop held
    nothing but capture noise, and tesseract spends a long time hunting for text
    in noise before giving up.

    A first version of this gate only counted connected components and passed
    pure noise as "text-like", so it never actually skipped anything.  Two
    signals are needed:

      * **class separation** -- real text is bimodal, so the mean of the pixels
        above Otsu's threshold sits far from the mean of those below it.  Sensor
        noise on a flat panel is unimodal and separates by only a few levels.
      * **glyph-shaped, baseline-aligned blobs** -- at least a few components of
        plausible size that share a horizontal band, which digits in a PIN do and
        scattered noise speckle does not.
    """
    try:
        import cv2
        import numpy as np

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        h, w = gray.shape[:2]
        if h < 16 or w < 16:
            return False

        thr, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        hi = gray[gray >= thr]
        lo = gray[gray < thr]
        if hi.size == 0 or lo.size == 0:
            return False
        separation = float(hi.mean()) - float(lo.mean())
        if separation < 28.0:
            # Unimodal: flat panel, gradient or pure noise. No text here.
            return False

        # Glyph-shaped components, on any polarity, roughly sharing a baseline.
        for polarity in (th, cv2.bitwise_not(th)):
            n, _lbl, stats, cent = cv2.connectedComponentsWithStats(polarity, 8)
            boxes = []
            for i in range(1, n):
                cw = int(stats[i, cv2.CC_STAT_WIDTH])
                ch = int(stats[i, cv2.CC_STAT_HEIGHT])
                area = int(stats[i, cv2.CC_STAT_AREA])
                if not (0.03 * h <= ch <= 0.80 * h):
                    continue
                if not (0.004 * w <= cw <= 0.45 * w):
                    continue
                if area < 0.25 * cw * ch * 0.35:      # too sparse to be a glyph
                    continue
                boxes.append((float(cent[i][1]), ch))
            if len(boxes) < 2:
                continue
            # Baseline alignment: several blobs whose centres fall in one band.
            boxes.sort()
            for idx, (cy, ch) in enumerate(boxes):
                band = max(6.0, 0.6 * ch)
                same_line = sum(1 for cy2, _ in boxes if abs(cy2 - cy) <= band)
                if same_line >= 2:
                    return True
        return False
    except Exception:
        return True      # never skip a region because the gate itself failed


def _variants(img, scale: float):
    """Yield ``(name, image)`` preprocessing variants for one crop.

    A single threshold pass is not good enough: on a real TV capture the PIN can
    be light-on-dark or dark-on-light, and Otsu picks the wrong polarity often
    enough that individual digits flip (3<->5, 8<->6).  Running several variants
    and voting is what makes the reader reliable, and it costs a few hundred ms
    once per pairing attempt.
    """
    out = []
    try:
        import cv2
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        # Clamp the effective scale so the OCR image never exceeds MAX_OCR_WIDTH.
        if gray.shape[1] > 0:
            scale = min(float(scale), MAX_OCR_WIDTH / float(gray.shape[1]))
            scale = max(scale, 1.0)
        up = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        out.append(("gray", up))
        _, otsu = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        out.append(("otsu", otsu))
        out.append(("otsu_inv", cv2.bitwise_not(otsu)))
        # Fixed high threshold: isolates bright dialog text from a dark panel.
        _, bright = cv2.threshold(up, 165, 255, cv2.THRESH_BINARY)
        out.append(("bright_inv", cv2.bitwise_not(bright)))
        # Mild blur before Otsu smooths compression noise on the capture.
        _, blurred = cv2.threshold(
            cv2.GaussianBlur(up, (3, 3), 0), 0, 255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        out.append(("blur_otsu_inv", cv2.bitwise_not(blurred)))
        # Adaptive threshold copes with a gradient/backlit dialog panel where a
        # single global cutoff loses either the top or the bottom of the digits.
        try:
            adap = cv2.adaptiveThreshold(
                up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 31, 5,
            )
            out.append(("adaptive_inv", cv2.bitwise_not(adap)))
        except Exception:
            pass
        # Closing repairs hairline breaks in anti-aliased strokes, which is the
        # single most common cause of a digit being read as a letter.
        try:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            closed = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel)
            out.append(("closed_inv", cv2.bitwise_not(closed)))
        except Exception:
            pass
    except Exception:
        out.append(("raw", img))
    return out


def _prep(img, scale: float = 2.6):
    """Single best-effort preprocessing pass (kept for pairing_screen_visible)."""
    try:
        import cv2
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        up = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        _, th = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return th
    except Exception:
        return img


def _crop(frame, box: Tuple[float, float, float, float]):
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    return frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


# Regions to search, best-first, with a confidence weight.  A PIN found inside
# the centred modal is far more trustworthy than digits scraped off the whole
# frame, which could be a clock or a channel number.
_PIN_REGIONS: Tuple[Tuple[Tuple[float, float, float, float], float], ...] = (
    ((0.25, 0.30, 0.75, 0.70), 3.0),   # centred modal
    ((0.20, 0.35, 0.80, 0.65), 2.5),   # slightly wider
    ((0.10, 0.25, 0.90, 0.75), 2.0),   # generous centre band
    ((0.05, 0.70, 0.95, 1.00), 1.5),   # bottom banner
    ((0.00, 0.00, 1.00, 1.00), 0.6),   # whole frame, last resort
)

_SCALES: Tuple[float, ...] = (2.0, 2.6, 4.0)

# How a match was obtained, and how much we trust it.
_METHOD_WEIGHT = {
    "labelled": 3.0,    # sat next to the words "code"/"pin" -- strongest signal
    "whitelist": 1.4,   # digit-only pass over the crop
    "bare": 0.8,        # loose digit run
}


# OCR effort tiers.  A single tesseract invocation costs ~100 ms, so the number
# of passes has to be budgeted explicitly: the first version of this reader tried
# every region x scale x variant x psm x whitelist combination, which came to
# ~1050 calls and 108 s for ONE frame.  wait_for_pin() polls repeatedly, so the
# per-frame cost must stay near a second and depth comes from cross-frame voting
# instead.
#
# Each plan entry is (region_index, scale, variant_names, passes) where a pass is
# ("labelled", psm) or ("strict"|"loose", psm).
_EFFORT_PLANS: Dict[str, Dict[str, Any]] = {
    # ~9 calls (~0.9 s) - the centred modal, the layouts that matter most.
    "fast": {
        "regions": (0,),
        "scales": (2.6,),
        "variants": ("otsu_inv", "gray", "adaptive_inv"),
        "passes": (("labelled", 6), ("strict", 8), ("strict", 7)),
        "max_calls": 12,
        "time_budget_s": 4.0,
    },
    # ~40 calls - MORE DEPTH ON THE SAME REGION, not a wider crop.
    #
    # Measured on a 4-font x 8-PIN synthetic sweep: an earlier "deep" tier that
    # widened the crop to regions (0,1,3) scored 78% top-1, *worse* than the
    # 81% of the narrow "fast" tier, because digits from the banner and the
    # clock got into the vote and outranked the real PIN.  Escalation therefore
    # adds polarities, scales and PSMs over the centred dialog; widening the
    # search area is reserved for the exhaustive tier, where the region weights
    # keep peripheral digits from winning.
    "deep": {
        "regions": (0, 1),
        "scales": (2.6, 4.0),
        "variants": ("otsu_inv", "gray", "closed_inv", "adaptive_inv"),
        "passes": (("labelled", 6), ("strict", 8), ("strict", 7), ("strict", 13), ("loose", 6)),
        "max_calls": 44,
        "time_budget_s": 12.0,
    },
    # ~80 calls (~8 s) - last resort, includes the whole frame.
    "exhaustive": {
        "regions": (0, 1, 2, 3, 4),
        "scales": (2.0, 2.6, 4.0),
        "variants": ("otsu", "otsu_inv", "gray", "adaptive_inv", "closed_inv"),
        "passes": (("labelled", 6), ("labelled", 11), ("strict", 8),
                   ("strict", 7), ("strict", 13), ("loose", 6)),
        "max_calls": 70,
        "time_budget_s": 25.0,
    },
}


def score_pin_candidates(
    frame=None,
    effort: str = "fast",
    time_budget_s: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Score every PIN candidate visible in one frame, within a call budget.

    Returns ``[{"pin", "score", "hits", "sources"}, ...]`` sorted best-first.
    Voting across regions/scales/polarities/PSMs is what corrects the individual
    digit confusions a single OCR pass gets wrong; ``effort`` bounds how much of
    that matrix is explored.
    """
    if frame is None:
        if _get_frame is None:
            return []
        frame = _get_frame()
    if frame is None or not getattr(frame, "size", 0):
        return []

    plan = _EFFORT_PLANS.get(effort) or _EFFORT_PLANS["fast"]
    # Budget is allocated PER REGION, not globally.  A single global counter is
    # consumed in region order, so on the exhaustive tier region 0 alone wanted
    # 3 scales x 5 variants x 6 passes = 90 calls and the bottom-banner region
    # was never reached at all -- a banner-style pairing screen returned no
    # candidates whatsoever.
    regions = tuple(plan["regions"])
    per_region = max(3, int(plan["max_calls"]) // max(1, len(regions)))
    calls_used = 0
    # Hard wall-clock stop.  Without this a single call could run for ~40 s and
    # blow straight through wait_for_pin's overall timeout, because the deadline
    # used to be checked only between polls.
    if time_budget_s is None:
        time_budget_s = float(plan.get("time_budget_s") or 0) or None
    hard_deadline = (time.time() + float(time_budget_s)) if time_budget_s else None

    def _out_of_time() -> bool:
        return hard_deadline is not None and time.time() >= hard_deadline

    scores: Dict[str, float] = {}
    hits: Dict[str, int] = {}
    sources: Dict[str, List[str]] = {}

    def _add(pin: str, weight: float, source: str) -> None:
        if not pin or not (PIN_MIN_DIGITS <= len(pin) <= PIN_MAX_DIGITS):
            return
        if len(pin) == PIN_PREFERRED_DIGITS:
            weight *= 1.6                     # firmware issues 6 digits today
        scores[pin] = scores.get(pin, 0.0) + weight
        hits[pin] = hits.get(pin, 0) + 1
        sources.setdefault(pin, [])
        if len(sources[pin]) < 5:
            sources[pin].append(source)

    for region_idx in regions:
        if _out_of_time():
            log.debug("sgs_autopair: OCR time budget reached, stopping at region %d", region_idx)
            break
        budget = per_region
        try:
            box, region_w = _PIN_REGIONS[region_idx]
            crop = _crop(frame, box)
        except Exception:
            continue
        if crop is None or not getattr(crop, "size", 0):
            continue
        # Skip regions that clearly hold no glyphs (see has_text_like_content).
        if not has_text_like_content(crop):
            log.debug("sgs_autopair: region %d has no glyph-like content, skipping", region_idx)
            continue

        for scale in plan["scales"]:
            if budget <= 0 or _out_of_time():
                break
            available = dict(_variants(crop, scale))
            for vname in plan["variants"]:
                image = available.get(vname)
                if image is None or budget <= 0:
                    continue
                for kind, psm in plan["passes"]:
                    if budget <= 0 or _out_of_time():
                        break
                    budget -= 1
                    calls_used += 1
                    tag = f"{kind}/{vname}/x{scale}/psm{psm}/r{region_idx}"

                    if kind == "labelled":
                        # Unconstrained OCR, then pull the digits that sit next
                        # to the words "code"/"pin" - the strongest signal, since
                        # it cannot be a clock or a channel number.
                        for m in _LABELLED_PIN_RE.finditer(_ocr(image, psm=psm)):
                            _add(_normalise_digits(m.group(1)),
                                 region_w * _METHOD_WEIGHT["labelled"], tag)
                        continue

                    strict = kind == "strict"
                    text = _ocr(image, psm=psm, digits_only=True, strict=strict)
                    whole = _normalise_digits(text)
                    weight = region_w * _METHOD_WEIGHT["whitelist"] * (1.5 if strict else 0.7)
                    if PIN_MIN_DIGITS <= len(whole) <= PIN_MAX_DIGITS:
                        _add(whole, weight, tag)
                    else:
                        for m in _BARE_DIGITS_RE.finditer(whole):
                            _add(m.group(1), region_w * _METHOD_WEIGHT["bare"], tag)

        # A clear winner from the centred dialog is enough; going wider only
        # invites clock/channel digits into the vote.
        if scores and region_idx <= 1:
            ranked = sorted(scores.values(), reverse=True)
            if len(ranked) == 1 or ranked[0] >= 2.0 * ranked[1]:
                break

    out = [
        {"pin": pin, "score": round(score, 2), "hits": hits[pin], "sources": sources[pin]}
        for pin, score in sorted(scores.items(), key=lambda kv: -kv[1])
    ]
    if out:
        log.debug("sgs_autopair: PIN candidates (%s, %d calls used): %s",
                  effort, calls_used,
                  [(c["pin"], c["score"], c["hits"]) for c in out[:4]])
    return out


def read_pin_candidates(frame=None, effort: str = "exhaustive") -> List[Tuple[str, str]]:
    """Back-compatible one-shot view of :func:`score_pin_candidates`.

    Defaults to the exhaustive tier because this is a single explicit read (an
    operator asking "what PIN can you see?"), not a poll inside a loop, so it
    should search every region -- including the bottom-banner layout that the
    fast/deep tiers skip on purpose.
    """
    return [(c["pin"], c["sources"][0] if c["sources"] else "?")
            for c in score_pin_candidates(frame, effort=effort)]


def pairing_screen_visible(frame=None) -> bool:
    """True when the current frame looks like the pairing dialog."""
    if frame is None and _get_frame is not None:
        frame = _get_frame()
    if frame is None or not getattr(frame, "size", 0):
        return False
    text = _ocr(_prep(_crop(frame, (0.10, 0.20, 0.90, 0.80))), psm=6).lower()
    return any(k in text for k in PAIR_SCREEN_KEYWORDS)


def wait_for_pin(
    timeout_s: float = PIN_READ_TIMEOUT_S,
    stable_reads: int = PIN_STABLE_READS,
) -> Optional[str]:
    """Poll the video feed until one PIN clearly wins.

    Two conditions must both hold before a PIN is returned:

      * it has been seen in at least ``stable_reads`` *different frames*, and
      * its accumulated score leads the runner-up by a clear margin.

    Requiring cross-frame agreement matters because the receiver invalidates the
    PIN after a rejected ``device_pairing_complete``, so a single misread digit
    costs a whole pairing session.
    """
    if _get_frame is None:
        log.error("sgs_autopair: no frame source registered — cannot OCR the PIN")
        return None

    deadline = time.time() + float(timeout_s)
    total: Dict[str, float] = {}
    frames_seen: Dict[str, int] = {}
    example: Dict[str, str] = {}
    polls = 0

    while time.time() < deadline:
        polls += 1
        # Escalate effort: cheap passes first (cross-frame voting usually settles
        # it), heavier passes only if the cheap ones are not converging.
        if polls <= 3:
            effort = "fast"
        elif polls <= 8:
            effort = "deep"
        else:
            effort = "exhaustive"
        remaining = max(1.0, deadline - time.time())
        tier_budget = float(_EFFORT_PLANS.get(effort, {}).get("time_budget_s") or remaining)
        for cand in score_pin_candidates(
            effort=effort, time_budget_s=min(tier_budget, remaining)
        ):
            pin = cand["pin"]
            total[pin] = total.get(pin, 0.0) + cand["score"]
            frames_seen[pin] = frames_seen.get(pin, 0) + 1
            example.setdefault(pin, (cand["sources"] or ["?"])[0])

        ranked = sorted(total.items(), key=lambda kv: -kv[1])
        if ranked:
            best_pin, best_score = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
            clear = best_score >= 1.5 * runner_up if runner_up else True
            if frames_seen.get(best_pin, 0) >= stable_reads and clear:
                log.info(
                    "sgs_autopair: PIN %s confirmed — score %.1f vs runner-up %.1f, "
                    "seen in %d frame(s), first via %s (%d polls, effort=%s)",
                    best_pin, best_score, runner_up,
                    frames_seen[best_pin], example.get(best_pin), polls, effort,
                )
                _set_phase("pin_read", pin_digits=len(best_pin),
                           frames=frames_seen[best_pin], polls=polls)
                return best_pin

        if polls % 5 == 0:
            log.info("sgs_autopair: still hunting the PIN (%d polls, leaders=%s)",
                     polls, [(p, round(s, 1)) for p, s in ranked[:4]])
        time.sleep(PIN_READ_INTERVAL_S)

    if total:
        best_pin, best_score = max(total.items(), key=lambda kv: kv[1])
        log.warning(
            "sgs_autopair: no PIN met the confidence bar in %.0fs; best guess %s "
            "(score %.1f, %d frame(s)) — trying it anyway",
            timeout_s, best_pin, best_score, frames_seen.get(best_pin, 0),
        )
        return best_pin

    log.error("sgs_autopair: PIN never read from screen after %.0fs (%d polls)",
              timeout_s, polls)
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Handshake steps
# ─────────────────────────────────────────────────────────────────────────────



def pair_start(alias: str) -> Dict[str, Any]:
    pair_alias, entry = _resolve_pair_target(alias)
    ip, stb_id = str(entry.get("ip") or ""), str(entry.get("stb") or "")
    if not ip or not stb_id:
        return {"ok": False, "error": f"Hopper {pair_alias!r} requires ip and RxID"}
    payload = _pair_envelope(stb_id, "device_pairing_start")
    response = _post_noauth(ip, payload, port_hint=entry.get("port"))
    ok = response.get("result") == 1
    return {
        "ok": ok,
        "requested_alias": str(alias),
        "pair_alias": pair_alias,
        "ip": ip,
        "stb": stb_id,
        "response": _safe_response(response),
    }


def pair_complete(alias: str, pin: str) -> Dict[str, Any]:
    pair_alias, entry = _resolve_pair_target(alias)
    use_pin = str(pin or "").strip()
    if not use_pin.isdigit() or not (PIN_MIN_DIGITS <= len(use_pin) <= PIN_MAX_DIGITS):
        return {"ok": False, "error": "PIN must contain 4-8 digits"}
    ip, stb_id = str(entry.get("ip") or ""), str(entry.get("stb") or "")
    if not ip or not stb_id:
        return {"ok": False, "error": f"Hopper {pair_alias!r} requires ip and RxID"}
    payload = _pair_envelope(stb_id, "device_pairing_complete", pin=use_pin)
    response = _post_noauth(ip, payload, port_hint=entry.get("port"))
    if response.get("result") != 1:
        return {"ok": False, "response": _safe_response(response)}
    username, password = response.get("name"), response.get("passwd")
    if not username or not password:
        return {"ok": False, "error": "pairing succeeded without credentials"}
    if not CredentialManager.store_credentials(pair_alias, str(username), str(password)):
        return {"ok": False, "error": "secure credential persistence failed"}
    fields: Dict[str, Any] = {
        "prod": True,
        "paired": True,
        "pair_rid": payload["receiver"],
        "paired_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if os.getenv("JAMBOREE_ALLOW_PLAINTEXT_CREDENTIALS") == "1":
        fields.update(lname=str(username), passwd=str(password))
    _store.update_stb(pair_alias, fields)
    _store.reload()
    try:
        from .sgs_bridge import clear_cid_cache

        clear_cid_cache()
    except Exception:
        pass
    return {
        "ok": True,
        "requested_alias": str(alias),
        "pair_alias": pair_alias,
        "credential_stored": True,
        "response": _safe_response(response),
    }


def _frame_delta(a: Any, b: Any) -> float:
    if a is None or b is None or not getattr(a, "size", 0) or not getattr(b, "size", 0):
        return -1.0
    try:
        import cv2
        import numpy as np

        if a.shape != b.shape:
            b = cv2.resize(b, (a.shape[1], a.shape[0]))
        return float(np.mean(cv2.absdiff(a, b)))
    except Exception:
        return -1.0


def attach(alias: str) -> Dict[str, Any]:
    try:
        from .sgs_bridge import attach_alias

        cid = attach_alias(alias)
        return {"ok": True, "cid": cid}
    except Exception as exc:
        return {"ok": False, "error": "attach_failed", "detail": str(exc)}


def verify_commands_active(alias: str, cleanup: bool = True) -> Dict[str, Any]:
    pair_alias, _entry_value = _resolve_pair_target(alias)
    out: Dict[str, Any] = {
        "requested_alias": str(alias),
        "pair_alias": pair_alias,
        "sgs_accepted": False,
        "screen_changed": None,
        "frame_delta": None,
        "errors": [],
    }
    if not CredentialManager.has_stored_credentials(
        pair_alias, _store.document() if _store else None
    ):
        out["errors"].append("not_paired")
        out["ok"] = False
        return out
    if _ctl is None:
        out["errors"].append("controller_not_registered")
        out["ok"] = False
        return out
    before = _get_frame() if _get_frame is not None else None
    target_entry = _entry(alias)
    remote = str(target_entry.get("remote") or _entry(pair_alias).get("remote") or "")
    delay = int(_CFG.get("default_delay_ms", 120))
    try:
        _ctl.handle_auto_remote(
            remote,
            str(alias),
            "info",
            delay,
            force="sgs",
            allow_rf_fallback=False,
            recover_ip=False,
        )
        out["sgs_accepted"] = True
    except Exception as exc:
        out["errors"].append(f"remote_key: {exc}")
    if out["sgs_accepted"] and before is not None:
        time.sleep(VERIFY_SETTLE_S)
        after = _get_frame() if _get_frame is not None else None
        delta = _frame_delta(before, after)
        out["frame_delta"] = round(delta, 3) if delta >= 0 else None
        if delta >= 0:
            out["screen_changed"] = delta >= SCREEN_CHANGE_THRESHOLD
    if cleanup and out["sgs_accepted"]:
        try:
            _ctl.handle_auto_remote(
                remote,
                str(alias),
                "back",
                delay,
                force="sgs",
                allow_rf_fallback=False,
                recover_ip=False,
            )
        except Exception:
            pass
    out["ok"] = bool(out["sgs_accepted"])
    out["fully_verified"] = bool(out["sgs_accepted"] and out["screen_changed"])
    return out


def verify_credentials_persisted(alias: str) -> Dict[str, Any]:
    pair_alias, entry = _resolve_pair_target(alias)
    secure = CredentialManager.status(
        pair_alias, _store.document() if _store else None
    )
    return {
        "requested_alias": str(alias),
        "pair_alias": pair_alias,
        "secure_store": bool(secure["stored"]),
        "backend": secure.get("backend"),
        "metadata_on_disk": bool(entry.get("paired") and entry.get("pair_rid")),
        "paired_ts": entry.get("paired_ts"),
        "pair_rid": entry.get("pair_rid"),
        "identity_intact": bool(entry.get("ip") and entry.get("stb")),
    }


def auto_pair(
    alias: Optional[str] = None,
    *,
    pin: Optional[str] = None,
    force: bool = False,
    verify: bool = True,
    pin_timeout_s: float = PIN_READ_TIMEOUT_S,
    max_pin_attempts: int = MAX_PIN_ATTEMPTS,
) -> Dict[str, Any]:
    requested_alias = str(alias or _CFG.get("stb_alias") or "").strip()
    result: Dict[str, Any] = {
        "requested_alias": requested_alias,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ok": False,
        "steps": {},
        "detail": "",
    }
    with _lock:
        if _state.get("active"):
            return {**result, "detail": "another pairing run is already active"}
        _state["active"] = True
        _state["alias"] = requested_alias
        _state["detail"] = {}
    try:
        _set_phase("preflight", alias=requested_alias)
        pair_alias, entry = _resolve_pair_target(requested_alias)
        result["pair_alias"] = pair_alias
        status = credentials_status(requested_alias)
        result["steps"]["preflight"] = {
            "ip": entry.get("ip"),
            "stb": entry.get("stb"),
            "credentials": status,
        }
        if status["paired"] and not status["stale_rid"] and not force:
            _set_phase("verifying_existing")
            existing = verify_commands_active(requested_alias)
            result["steps"]["verify_existing"] = existing
            if existing.get("ok"):
                result["ok"] = True
                result["detail"] = "already paired; existing credentials work"
                _set_phase("done", reason="already_paired")
                return result

        try:
            from .ip_recovery import probe_device_identity

            identity = probe_device_identity(str(entry.get("ip")), str(entry.get("stb")))
            result["steps"]["identity"] = identity
            if identity.get("is_stb") is False:
                result["detail"] = "configured IP is not a receiver"
                _set_phase("failed", reason="not_an_stb")
                return result
        except Exception as exc:
            result["steps"]["identity"] = {"is_stb": None, "reason": str(exc)}

        attempts = 1 if pin else max(1, int(max_pin_attempts))
        rejected: List[str] = []
        complete: Dict[str, Any] = {}
        use_pin = ""
        result["steps"]["attempts"] = []
        for attempt in range(1, attempts + 1):
            _set_phase("pair_start", attempt=attempt)
            start = pair_start(requested_alias)
            if attempt == 1:
                result["steps"]["pair_start"] = start
            if not start.get("ok"):
                result["detail"] = "device_pairing_start rejected"
                _set_phase("failed", reason="pair_start")
                return result
            if pin:
                _set_phase("pin_supplied")
                use_pin = str(pin).strip()
            else:
                _set_phase("pin_ocr", attempt=attempt)
                time.sleep(1.5)
                use_pin = wait_for_pin(timeout_s=pin_timeout_s) or ""
                if use_pin in rejected:
                    use_pin = wait_for_pin(
                        timeout_s=min(pin_timeout_s, 20.0),
                        stable_reads=PIN_STABLE_READS + 1,
                    ) or ""
            result["steps"]["attempts"].append(
                {
                    "attempt": attempt,
                    "pin_digits": len(use_pin),
                    "pin_source": "supplied" if pin else "ocr",
                }
            )
            if not use_pin:
                result["detail"] = "pairing PIN could not be read"
                _set_phase("failed", reason="pin_unreadable")
                return result
            _set_phase("pair_complete", attempt=attempt)
            complete = pair_complete(requested_alias, use_pin)
            result["steps"]["pair_complete"] = complete
            if complete.get("ok"):
                break
            rejected.append(use_pin)
            if attempt < attempts:
                time.sleep(2.0)
        result["steps"]["pin"] = {
            "source": "supplied" if pin else "ocr",
            "digits": len(use_pin),
            "value": "*" * len(use_pin),
            "rejected_count": len(rejected),
        }
        if not complete.get("ok"):
            result["detail"] = "device_pairing_complete failed"
            _set_phase("failed", reason="pair_complete")
            return result

        _set_phase("verify_persistence")
        persisted = verify_credentials_persisted(requested_alias)
        result["steps"]["persistence"] = persisted
        if not (persisted["secure_store"] and persisted["metadata_on_disk"]):
            result["detail"] = "credentials were issued but secure persistence is incomplete"
            _set_phase("failed", reason="not_persisted")
            return result
        if verify:
            _set_phase("verify_commands")
            verification = verify_commands_active(requested_alias)
            result["steps"]["verify_commands"] = verification
            result["ok"] = bool(verification.get("ok"))
            result["detail"] = (
                "paired and verified"
                if verification.get("fully_verified")
                else "paired; SGS accepted the command but no visible screen change was observed"
                if verification.get("ok")
                else "paired and stored, but SGS verification failed"
            )
        else:
            result["ok"] = True
            result["detail"] = "paired; command verification skipped"
        _set_phase("done" if result["ok"] else "failed", reason=result["detail"][:80])
        return result
    except Exception as exc:
        log.exception("unhandled SGS autopair error")
        result["detail"] = f"exception: {exc}"
        _set_phase("failed", reason="exception")
        return result
    finally:
        with _lock:
            _state["active"] = False
            _state["last_result"] = dict(result)


def auto_pair_async(alias: Optional[str] = None, **kwargs: Any) -> bool:
    with _lock:
        if _state.get("active"):
            return False
    threading.Thread(
        target=lambda: auto_pair(alias, **kwargs),
        name="SGSAutoPairWorker",
        daemon=True,
    ).start()
    return True
