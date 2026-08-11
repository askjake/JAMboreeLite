"""Identity-safe SGS IP recovery with RF-driven on-screen OCR fallback.

Recovery is conservative: network candidates must match the configured receiver
identity, ambiguous matches are rejected, writes are atomic, and a failed
post-write SGS verification rolls back to the exact pre-recovery IP.  When an
HTTP 401/403 comes from a real receiver, the problem is treated as pairing—not
as proof that the IP changed—and automatic pairing is offered instead.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import platform
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

import requests

LOG = logging.getLogger(__name__)
_RXID_RE = re.compile(r"R\d{10}(?:-\d{2})?", re.I)
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)"
_IP_RE = re.compile(rf"(?<![\d.])({_OCTET}(?:\.{_OCTET}){{3}})(?![\d.])")
_MAC_RE = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I)

NON_STB_HEADER_MARKERS = (
    "x-jenkins",
    "x-hudson",
    "x-atlassian-token",
    "x-sonatype",
    "x-gitlab-feature-category",
    "x-influxdb-version",
)
NON_STB_BODY_MARKERS = (
    "crumbissuer",
    "jenkins",
    "hudson",
    "gitlab",
    "grafana",
    "kibana",
    "phpmyadmin",
    "tomcat",
    "artifactory",
    "nexus repository",
)
NON_STB_SERVER_MARKERS = (
    "apache/",
    "nginx/",
    "gunicorn",
    "werkzeug",
    "iis/",
    "lighttpd",
)


@dataclass(frozen=True)
class FailureClass:
    dead: bool
    kind: str
    threshold: int
    recoverable: bool = False
    auth: bool = False
    wrong_device: bool = False
    transport: bool = False
    needs_pairing: bool = False
    reason: str = "unknown"

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryResult:
    ok: bool
    alias: str
    old_ip: str
    new_ip: Optional[str] = None
    strategy: Optional[str] = None
    reason: Optional[str] = None
    sgs_verified: bool = False
    needs_pairing: bool = False
    autopair_started: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _AliasState:
    active: bool = False
    last_attempt_ts: float = 0.0
    consecutive_failures: int = 0
    last_failure: dict = field(default_factory=dict)
    last_result: dict = field(default_factory=dict)
    known_mac: Optional[str] = None
    autopair_last_ts: float = 0.0
    autopair_last: dict = field(default_factory=dict)


_store: Any = None
_ctl: Any = None
_get_frame: Optional[Callable[[], Any]] = None
_get_status: Optional[Callable[[], Dict[str, Any]]] = None
_CFG: Dict[str, Any] = {}
_state_lock = threading.RLock()
_states: Dict[str, _AliasState] = {}


def _state(alias: str) -> _AliasState:
    with _state_lock:
        return _states.setdefault(str(alias), _AliasState())


def set_dependencies(
    *,
    store: Any = None,
    ctl: Any = None,
    get_frame: Optional[Callable[[], Any]] = None,
    get_status: Optional[Callable[[], Dict[str, Any]]] = None,
    CFG: Optional[Dict[str, Any]] = None,
) -> None:
    global _store, _ctl, _get_frame, _get_status, _CFG
    if store is not None:
        _store = store
    if ctl is not None:
        _ctl = ctl
    if get_frame is not None:
        _get_frame = get_frame
    if get_status is not None:
        _get_status = get_status
    if CFG is not None:
        _CFG = CFG
    LOG.info(
        "IP recovery dependencies registered (store=%s ctl=%s frame=%s)",
        _store is not None,
        _ctl is not None,
        _get_frame is not None,
    )


def normalize_rxid(value: object) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return digits[:12]


def extract_ipv4(text: str) -> list[str]:
    values: list[str] = []
    for candidate in _IP_RE.findall(text or ""):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if (
            address.version == 4
            and not address.is_unspecified
            and not address.is_loopback
            and not address.is_multicast
            and not address.is_reserved
        ):
            values.append(str(address))
    return list(dict.fromkeys(values))


def classify_sgs_failure(exc: Optional[BaseException | str]) -> FailureClass:
    text = str(exc or "").strip().lower()
    if not text:
        return FailureClass(
            True,
            "unknown",
            3,
            recoverable=False,
            reason="empty_error",
        )
    if any(
        marker in text
        for marker in (
            "not_an_stb",
            "wrong receiver",
            "wrong device",
            "rxid mismatch",
            "identity mismatch",
        )
    ):
        return FailureClass(
            True,
            "wrong_device",
            1,
            recoverable=True,
            wrong_device=True,
            reason="identity",
        )
    if any(
        marker in text
        for marker in (
            "401",
            "403",
            "digest",
            "credential",
            "auth_required",
            "unauthorized",
            "forbidden",
            "not_paired",
            "pair first",
            "no credentials",
            "result\": -13",
        )
    ):
        return FailureClass(
            True,
            "auth",
            2,
            recoverable=False,
            auth=True,
            needs_pairing=True,
            reason="authentication",
        )
    if any(
        marker in text
        for marker in (
            "timed out",
            "timeout",
            "connection refused",
            "no route",
            "unreachable",
            "network is unreachable",
            "name resolution",
            "connection aborted",
            "connection reset",
            "max retries",
            "failed to connect",
            "broken pipe",
            "non-json",
        )
    ):
        return FailureClass(
            True,
            "transport",
            3,
            recoverable=True,
            transport=True,
            reason="transport",
        )
    return FailureClass(False, "application", 3, reason="application")


def _entry(alias: str) -> Dict[str, Any]:
    if _store is None:
        return {}
    return dict(_store.get(alias) or {})


def _default_alias() -> str:
    configured = str(_CFG.get("stb_alias") or os.getenv("JAMBOREE_STB_ALIAS", "")).strip()
    if configured:
        return configured
    if _store is not None:
        aliases = list((_store.all() or {}).keys())
        if aliases:
            return str(aliases[0])
    return ""


def _all_strings(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _all_strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _all_strings(item)
    elif value is not None:
        yield str(value)


def probe_device_identity(
    ip: str,
    expected_rxid: str = "",
    *,
    timeout: float = 2.0,
    request_post: Callable[..., Any] = requests.post,
) -> Dict[str, Any]:
    """Fingerprint an address and collect any receiver IDs it exposes."""
    expected = normalize_rxid(expected_rxid)
    server = ""
    saw_response = False
    positive = False
    rxids: set[str] = set()
    observations: list[dict] = []
    endpoints = (
        (f"http://{ip}:8080/sgs_noauth", False),
        (f"http://{ip}:8080/www/sgs", False),
        (f"http://{ip}/www/sgs", False),
        (f"https://{ip}/www/sgs", True),
    )
    commands = ("get_stb_information", "get_receiver_id", "get_version")
    for url, secure in endpoints:
        for command in commands:
            try:
                response = request_post(
                    url,
                    json={"command": command},
                    timeout=timeout,
                    verify=False if secure else True,
                    headers={"Content-Type": "application/json"},
                )
            except Exception:
                continue
            saw_response = True
            headers = {str(k).lower(): str(v).lower() for k, v in response.headers.items()}
            body = (response.text or "")[:4000].lower()
            server = headers.get("server", server)
            for marker in NON_STB_HEADER_MARKERS:
                if marker in headers:
                    return {
                        "is_stb": False,
                        "reason": f"header:{marker}",
                        "server": server,
                        "rxids": [],
                        "rxid_match": False,
                    }
            for marker in NON_STB_BODY_MARKERS:
                if marker in body:
                    return {
                        "is_stb": False,
                        "reason": f"body:{marker}",
                        "server": server,
                        "rxids": [],
                        "rxid_match": False,
                    }
            for marker in NON_STB_SERVER_MARKERS:
                if marker in server:
                    return {
                        "is_stb": False,
                        "reason": f"server:{marker}",
                        "server": server,
                        "rxids": [],
                        "rxid_match": False,
                    }
            auth_header = headers.get("www-authenticate", "")
            if "digest" in auth_header:
                positive = True
            try:
                data = response.json()
            except Exception:
                data = None
            if isinstance(data, dict):
                if "result" in data:
                    positive = True
                found = {
                    normalize_rxid(match)
                    for text in _all_strings(data)
                    for match in _RXID_RE.findall(text)
                    if normalize_rxid(match)
                }
                rxids.update(found)
                observations.append(
                    {
                        "url": url,
                        "command": command,
                        "status": int(response.status_code),
                        "result": data.get("result"),
                    }
                )
    normalized_rxids = sorted(rxids)
    match = bool(expected and expected in rxids)
    return {
        "is_stb": True if positive else (None if not saw_response else None),
        "reason": "rxid_match"
        if match
        else ("sgs_response" if positive else "unreachable" if not saw_response else "inconclusive"),
        "server": server,
        "rxids": normalized_rxids,
        "rxid_match": match if expected else None,
        "observations": observations[-6:],
    }


def verify_stored_ip_identity(alias: Optional[str] = None) -> Dict[str, Any]:
    alias = str(alias or _default_alias())
    entry = _entry(alias)
    ip = str(entry.get("ip") or "").strip()
    if not ip:
        return {"alias": alias, "ip": None, "is_stb": None, "reason": "no_stored_ip"}
    result = probe_device_identity(ip, str(entry.get("stb") or ""))
    return {"alias": alias, "ip": ip, **result}


def _video_alive() -> bool:
    if _get_status is None:
        return True  # standalone JAMboree may not have a capture pipeline
    try:
        status = _get_status() or {}
    except Exception:
        return False
    if isinstance(status.get("video"), dict):
        status = status["video"]
    if status.get("active") is False:
        return False
    signal = str(status.get("signal_class") or "").lower()
    return signal not in {"black_screen", "blank_or_no_signal", "no_frame"}


def _arp_entries() -> Dict[str, str]:
    commands = (
        ["ip", "neigh", "show"],
        ["arp", "-a"] if platform.system() == "Windows" else ["arp", "-n"],
    )
    entries: Dict[str, str] = {}
    for command in commands:
        try:
            output = subprocess.check_output(
                command, text=True, stderr=subprocess.DEVNULL, timeout=5
            )
        except Exception:
            continue
        for line in output.splitlines():
            ip_match = _IP_RE.search(line)
            mac_match = _MAC_RE.search(line)
            if ip_match and mac_match:
                entries[ip_match.group(1)] = mac_match.group(0).replace("-", ":").lower()
        if entries:
            break
    return entries


def _configured_mac(alias: str) -> Optional[str]:
    entry = _entry(alias)
    mac = str(entry.get("mac") or "").replace("-", ":").lower().strip()
    if _MAC_RE.fullmatch(mac):
        return mac
    old_ip = str(entry.get("ip") or "")
    entries = _arp_entries()
    if old_ip in entries:
        identity = probe_device_identity(old_ip, str(entry.get("stb") or ""))
        if identity.get("is_stb") is not False:
            mac = entries[old_ip]
            _state(alias).known_mac = mac
            return mac
    return _state(alias).known_mac


def _subnets(alias: str) -> list[ipaddress.IPv4Network]:
    networks: list[ipaddress.IPv4Network] = []
    entry = _entry(alias)
    old_ip = str(entry.get("ip") or "")
    try:
        networks.append(ipaddress.ip_network(f"{old_ip}/24", strict=False))
    except ValueError:
        pass
    raw = _CFG.get("ip_recovery_subnets") or os.getenv("JAMBOREE_RECOVERY_SUBNETS", "")
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    for item in raw or []:
        try:
            network = ipaddress.ip_network(str(item), strict=False)
            if network.version == 4 and network not in networks:
                networks.append(network)
        except ValueError:
            LOG.warning("ignoring invalid recovery subnet %r", item)
    return networks


def _candidate_hosts(alias: str, max_hosts: int = 512) -> list[str]:
    hosts: list[str] = []
    for network in _subnets(alias):
        for host in network.hosts():
            hosts.append(str(host))
            if len(hosts) >= max_hosts:
                return hosts
    return hosts


def _touch_host(ip: str, timeout: float = 0.2) -> None:
    for port in (8080, 80, 443):
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return
        except OSError:
            continue
    # Ping is a final cache-population attempt; failure is harmless.
    if platform.system() == "Windows":
        command = ["ping", "-n", "1", "-w", str(max(100, int(timeout * 1000))), ip]
    else:
        command = ["ping", "-c", "1", "-W", "1", ip]
    try:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except Exception:
        pass


def find_by_mac(
    alias: str,
    *,
    candidates: Optional[Sequence[str]] = None,
    workers: int = 48,
) -> Optional[str]:
    mac = _configured_mac(alias)
    if not mac:
        return None
    hosts = list(candidates) if candidates is not None else _candidate_hosts(alias)
    host_set = set(hosts)
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 96))) as pool:
        list(pool.map(_touch_host, hosts))
    # The same physical device can legitimately appear more than once in the OS
    # ARP table (for example, one RFC1918 address plus an APIPA/link-local alias).
    # Recovery is scoped to the candidate hosts we deliberately scanned, so an
    # out-of-scope duplicate must not make an otherwise unique candidate
    # ambiguous. Multiple in-scope matches remain a hard failure.
    matches = sorted(
        ip
        for ip, value in _arp_entries().items()
        if value == mac and ip in host_set
    )
    if len(matches) != 1:
        if len(matches) > 1:
            LOG.error("MAC %s resolved ambiguously within candidate scope: %s", mac, matches)
        return None
    candidate = matches[0]
    identity = probe_device_identity(candidate, str(_entry(alias).get("stb") or ""))
    if identity.get("is_stb") is False:
        return None
    return candidate


def scan_identity_candidates(
    alias: str,
    *,
    candidates: Optional[Sequence[str]] = None,
    workers: int = 48,
    probe: Callable[[str, str], Dict[str, Any]] = lambda ip, rxid: probe_device_identity(ip, rxid),
) -> tuple[list[str], list[str]]:
    entry = _entry(alias)
    expected = normalize_rxid(entry.get("stb"))
    hosts = list(candidates) if candidates is not None else _candidate_hosts(alias)
    exact: list[str] = []
    unidentified: list[str] = []

    def check(ip: str) -> tuple[str, Dict[str, Any]]:
        return ip, probe(ip, expected)

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 96))) as pool:
        futures = [pool.submit(check, ip) for ip in hosts]
        for future in as_completed(futures):
            try:
                ip, identity = future.result()
            except Exception:
                continue
            if identity.get("is_stb") is not True:
                continue
            if identity.get("rxid_match") is True:
                exact.append(ip)
            elif not identity.get("rxids"):
                unidentified.append(ip)
    return sorted(set(exact)), sorted(set(unidentified))


def find_by_identity(
    alias: str,
    *,
    candidates: Optional[Sequence[str]] = None,
    probe: Callable[[str, str], Dict[str, Any]] = lambda ip, rxid: probe_device_identity(ip, rxid),
) -> tuple[Optional[str], Optional[str]]:
    exact, unidentified = scan_identity_candidates(alias, candidates=candidates, probe=probe)
    if len(exact) > 1:
        return None, f"ambiguous RxID matches: {exact}"
    if len(exact) == 1:
        return exact[0], None
    allow_singleton = str(
        _CFG.get("ip_recovery_allow_unidentified_singleton", "false")
    ).lower() in {"1", "true", "yes", "on"}
    if allow_singleton and len(unidentified) == 1:
        return unidentified[0], None
    if unidentified:
        return None, f"receiver candidates did not expose matching RxID: {unidentified}"
    return None, "no receiver identity match"


def _get_pytesseract() -> Any:
    try:
        import pytesseract

        return pytesseract
    except Exception:
        return None


def _ocr_frame(frame: Any, psm: int = 6) -> str:
    if frame is None or not getattr(frame, "size", 0):
        return ""
    pytesseract = _get_pytesseract()
    if pytesseract is None:
        return ""
    try:
        import cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        scale = 2.5
        up = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        up = cv2.GaussianBlur(up, (3, 3), 0)
        threshold = cv2.adaptiveThreshold(
            up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5
        )
        raw = pytesseract.image_to_string(
            threshold,
            config=f"--oem 3 --psm {int(psm)} -c user_defined_dpi=300",
        )
        return re.sub(r"\s+", " ", str(raw or "")).strip()
    except Exception as exc:
        LOG.debug("OCR failed: %s", exc)
        return ""


def _ocr_region(frame: Any, box: tuple[float, float, float, float], psm: int = 6) -> str:
    if frame is None or not getattr(frame, "size", 0):
        return ""
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = box
    crop = frame[
        max(0, int(y0 * height)) : min(height, int(y1 * height)),
        max(0, int(x0 * width)) : min(width, int(x1 * width)),
    ]
    return _ocr_frame(crop, psm=psm)


def _screen_contains(keywords: Sequence[str]) -> bool:
    if _get_frame is None:
        return False
    frame = _get_frame()
    text = _ocr_frame(frame, psm=11).lower()
    return any(str(keyword).lower() in text for keyword in keywords)


def _rf_ready(alias: str) -> bool:
    if _ctl is None:
        return False
    try:
        return bool(_ctl.rf_ready(alias))
    except Exception:
        try:
            from .serial_bridge import rf_available

            return bool(rf_available(alias, require_ready=True))
        except Exception:
            return False


def _rf_press(alias: str, button: str, delay_ms: int, settle_s: float = 2.2) -> bool:
    if _ctl is None:
        return False
    entry = _entry(alias)
    remote = str(entry.get("remote") or "")
    try:
        _ctl.handle_auto_remote(
            remote,
            alias,
            button,
            int(delay_ms),
            force="rf",
            allow_rf_fallback=False,
            recover_ip=False,
        )
        time.sleep(max(0.0, float(settle_s)))
        return True
    except Exception as exc:
        LOG.warning("RF navigation press %s failed for %s: %s", button, alias, exc)
        return False


def navigate_to_network_screen(alias: str) -> bool:
    """Use RF4CE/DART to open the receiver's network-information screen."""
    if not _rf_ready(alias):
        return False
    default_sequence = [
        {
            "button": "home",
            "delay_ms": 3000,
            "expect": ["settings", "network", "diagnostics", "system", "info"],
        },
        {
            "button": "2",
            "delay_ms": 80,
            "expect": ["network", "ip address", "ethernet", "wifi", "internet"],
        },
    ]
    sequence = _CFG.get("ip_recovery_nav_sequence") or default_sequence
    attempts = int(_CFG.get("ip_recovery_key_attempts", 5))
    settle = float(_CFG.get("ip_recovery_key_settle_s", 2.2))
    for step in sequence:
        button = str(step.get("button") or "")
        delay = int(step.get("delay_ms", 80))
        expected = list(step.get("expect") or [])
        confirmed = False
        for _attempt in range(max(1, attempts)):
            if not _rf_press(alias, button, delay, settle_s=settle):
                return False
            if not expected or _screen_contains(expected):
                confirmed = True
                break
        if not confirmed:
            return False
    return True


def read_ip_from_screen(alias: str) -> Optional[str]:
    del alias  # frame already belongs to the RF-controlled receiver
    if _get_frame is None:
        return None
    frame = _get_frame()
    if frame is None:
        return None
    boxes = (
        ((0.08, 0.20, 0.92, 0.85), 6),
        ((0.08, 0.30, 0.70, 0.75), 6),
        ((0.0, 0.0, 1.0, 0.55), 6),
        ((0.0, 0.0, 1.0, 1.0), 11),
    )
    for box, psm in boxes:
        values = extract_ipv4(_ocr_region(frame, box, psm=psm))
        private = [
            value
            for value in values
            if ipaddress.ip_address(value).is_private
            or ipaddress.ip_address(value).is_link_local
        ]
        if len(private) == 1:
            return private[0]
    return None


def _escape_to_live(alias: str) -> None:
    for button in ("back", "back", "live"):
        if not _rf_press(alias, button, 120, settle_s=0.35):
            break


def _verify_sgs(alias: str) -> tuple[bool, Optional[BaseException]]:
    if _ctl is None:
        return False, RuntimeError("controller not configured")
    entry = _entry(alias)
    remote = str(entry.get("remote") or "")
    delay = int(_CFG.get("default_delay_ms", 120))
    try:
        _ctl.handle_auto_remote(
            remote,
            alias,
            "info",
            delay,
            force="sgs",
            allow_rf_fallback=False,
            recover_ip=False,
        )
        return True, None
    except BaseException as exc:  # preserve the exact classification evidence
        return False, exc


def trigger_autopair(alias: str, reason: str) -> bool:
    state = _state(alias)
    cooldown = float(_CFG.get("autopair_cooldown_s", 180.0))
    now = time.time()
    with _state_lock:
        if state.autopair_last_ts and now - state.autopair_last_ts < cooldown:
            state.autopair_last = {
                "triggered": False,
                "reason": "cooldown",
                "retry_in_s": round(cooldown - (now - state.autopair_last_ts), 1),
            }
            return False
        state.autopair_last_ts = now
    if str(os.getenv("JAMBOREE_AUTOPAIR", "1")).lower() in {"0", "false", "no", "off"}:
        state.autopair_last = {"triggered": False, "reason": "disabled_by_env"}
        return False
    try:
        from . import sgs_autopair

        started = bool(sgs_autopair.auto_pair_async(alias))
    except Exception as exc:
        state.autopair_last = {"triggered": False, "reason": f"launch_failed: {exc}"}
        return False
    state.autopair_last = {
        "triggered": started,
        "reason": reason if started else "already_running",
        "alias": alias,
    }
    return started


def recover_alias(
    alias: str,
    *,
    candidates: Optional[Sequence[str]] = None,
    mac_finder: Callable[..., Optional[str]] = find_by_mac,
    identity_finder: Callable[..., tuple[Optional[str], Optional[str]]] = find_by_identity,
    navigator: Callable[[str], bool] = navigate_to_network_screen,
    screen_reader: Callable[[str], Optional[str]] = read_ip_from_screen,
    identity_probe: Callable[[str, str], Dict[str, Any]] = lambda ip, rid: probe_device_identity(ip, rid),
    sgs_verifier: Callable[[str], tuple[bool, Optional[BaseException]]] = _verify_sgs,
) -> RecoveryResult:
    """Synchronously recover one alias and verify or roll back its IP."""
    alias = str(alias).strip()
    entry = _entry(alias)
    old_ip = str(entry.get("ip") or "").strip()
    expected_rxid = str(entry.get("stb") or "").strip()
    if not alias or not old_ip or not expected_rxid:
        return RecoveryResult(False, alias, old_ip, reason="alias requires IP and RxID")

    details: Dict[str, Any] = {}
    candidate: Optional[str] = None
    strategy: Optional[str] = None

    # Strategy 1: stable MAC plus ARP.  This remains useful when the receiver's
    # unauthenticated SGS endpoint does not disclose an RxID.
    try:
        candidate = mac_finder(alias, candidates=candidates)
    except TypeError:
        candidate = mac_finder(alias)
    except Exception as exc:
        details["mac_error"] = str(exc)
    if candidate:
        strategy = "arp_mac"

    # Strategy 2: exact receiver ID exposed by SGS discovery.
    if not candidate:
        try:
            candidate, error = identity_finder(alias, candidates=candidates)
        except TypeError:
            candidate, error = identity_finder(alias)
        except Exception as exc:
            candidate, error = None, str(exc)
        if error:
            details["identity_scan"] = error
        if candidate:
            strategy = "sgs_identity"

    # Strategy 3: RF-driven Diagnostics/Network screen and OCR.
    if not candidate and _get_frame is not None:
        if navigator(alias):
            candidate = screen_reader(alias)
            if candidate:
                strategy = "rf_ocr"
        else:
            details["rf_ocr"] = "navigation_failed"

    if not candidate:
        return RecoveryResult(
            False,
            alias,
            old_ip,
            reason="no identity-safe replacement IP",
            details=details,
        )

    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return RecoveryResult(False, alias, old_ip, candidate, strategy, "invalid candidate IP")

    identity = identity_probe(candidate, expected_rxid)
    details["candidate_identity"] = identity
    if identity.get("is_stb") is False:
        return RecoveryResult(
            False, alias, old_ip, candidate, strategy, "candidate is not a receiver", details=details
        )
    if strategy != "rf_ocr" and identity.get("rxids") and identity.get("rxid_match") is not True:
        return RecoveryResult(
            False, alias, old_ip, candidate, strategy, "candidate RxID mismatch", details=details
        )

    if candidate == old_ip:
        ok, error = sgs_verifier(alias)
        if ok:
            note_sgs_success(alias)
            return RecoveryResult(
                True,
                alias,
                old_ip,
                candidate,
                "unchanged",
                sgs_verified=True,
                details=details,
            )
        verdict = classify_sgs_failure(error)
        if verdict.auth and identity.get("is_stb") is True:
            started = trigger_autopair(alias, "stored IP is correct but SGS authentication failed")
            return RecoveryResult(
                True,
                alias,
                old_ip,
                candidate,
                "unchanged",
                reason="receiver requires pairing",
                needs_pairing=True,
                autopair_started=started,
                details=details,
            )
        return RecoveryResult(False, alias, old_ip, candidate, "unchanged", str(error), details=details)

    _store.update_stb(
        alias,
        {
            "ip": candidate,
            "ip_recovery_strategy": strategy,
            "ip_recovered_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    try:
        _store.reload()
    except Exception:
        pass

    try:
        ok, error = sgs_verifier(alias)
        if ok:
            note_sgs_success(alias)
            return RecoveryResult(
                True,
                alias,
                old_ip,
                candidate,
                strategy,
                sgs_verified=True,
                details=details,
            )
        verdict = classify_sgs_failure(error)
        post_identity = identity_probe(candidate, expected_rxid)
        details["post_identity"] = post_identity
        # An auth failure against the correct receiver means the IP recovery was
        # successful; retain it and repair pairing rather than rolling it back.
        if verdict.auth and post_identity.get("is_stb") is True and (
            post_identity.get("rxid_match") is True
            or strategy in {"arp_mac", "rf_ocr"}
            or not post_identity.get("rxids")
        ):
            started = trigger_autopair(alias, "new receiver IP requires pairing")
            return RecoveryResult(
                True,
                alias,
                old_ip,
                candidate,
                strategy,
                reason="IP recovered; receiver requires pairing",
                needs_pairing=True,
                autopair_started=started,
                details=details,
            )
        raise RuntimeError(str(error or "post-write SGS verification failed"))
    except Exception as exc:
        # Restore the snapshot taken before any write—not the now-updated entry.
        _store.update_stb(alias, {"ip": old_ip, "ip_recovery_rollback": str(exc)[:300]})
        try:
            _store.reload()
        except Exception:
            pass
        return RecoveryResult(
            False,
            alias,
            old_ip,
            candidate,
            strategy,
            f"post-write verification failed; rolled back: {exc}",
            details=details,
        )
    finally:
        if strategy == "rf_ocr":
            _escape_to_live(alias)


def recover_alias_async(alias: str, *, force: bool = False) -> bool:
    alias = str(alias or _default_alias())
    state = _state(alias)
    cooldown = float(_CFG.get("ip_recovery_cooldown_s", 30.0))
    with _state_lock:
        now = time.time()
        if state.active:
            return False
        if not force and state.last_attempt_ts and now - state.last_attempt_ts < cooldown:
            return False
        state.active = True
        state.last_attempt_ts = now

    def worker() -> None:
        try:
            result = recover_alias(alias)
            state.last_result = result.to_dict()
        except Exception as exc:
            LOG.exception("IP recovery worker failed for %s", alias)
            state.last_result = {
                "ok": False,
                "alias": alias,
                "reason": f"unhandled exception: {exc}",
            }
        finally:
            with _state_lock:
                state.active = False

    threading.Thread(target=worker, name=f"IPRecovery-{alias}", daemon=True).start()
    return True


def maybe_trigger_recovery(alias: Optional[str] = None) -> bool:
    alias = str(alias or _default_alias())
    if not alias or not _video_alive():
        return False
    return recover_alias_async(alias)


def note_sgs_failure(alias: str, exc: Optional[BaseException]) -> FailureClass:
    alias = str(alias)
    verdict = classify_sgs_failure(exc)
    state = _state(alias)
    with _state_lock:
        state.consecutive_failures += 1
        state.last_failure = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "error": str(exc or "")[:400],
            **verdict.to_dict(),
        }
        count = state.consecutive_failures
    if count < verdict.threshold or not verdict.dead:
        return verdict
    if verdict.auth:
        identity = verify_stored_ip_identity(alias)
        if identity.get("is_stb") is True and (
            identity.get("rxid_match") is True or not identity.get("rxids")
        ):
            trigger_autopair(alias, "SGS authentication failed at current receiver IP")
            return verdict
    if verdict.recoverable or verdict.auth:
        maybe_trigger_recovery(alias)
    return verdict


def note_sgs_success(alias: str) -> None:
    """Record a healthy SGS command without blocking the response path.

    MAC/identity discovery can probe multiple receiver endpoints and is reserved
    for recovery. A successful remote key must return as soon as SGS confirms it.
    """
    state = _state(alias)
    with _state_lock:
        state.consecutive_failures = 0
        state.last_failure = {}


def get_recovery_status(alias: Optional[str] = None) -> Dict[str, Any]:
    aliases = [str(alias)] if alias else sorted(_states)
    if not aliases:
        default = _default_alias()
        aliases = [default] if default else []
    output: Dict[str, Any] = {}
    for name in aliases:
        state = _state(name)
        with _state_lock:
            output[name] = {
                "active": state.active,
                "last_attempt_ago_s": round(time.time() - state.last_attempt_ts, 1)
                if state.last_attempt_ts
                else None,
                "consecutive_sgs_failures": state.consecutive_failures,
                "last_failure": dict(state.last_failure),
                "last_result": dict(state.last_result),
                "known_mac": state.known_mac,
                "autopair": dict(state.autopair_last),
                "rf_ready": _rf_ready(name),
                "stored_identity": verify_stored_ip_identity(name),
            }
    if alias:
        return output.get(str(alias), {})
    return {"aliases": output}
