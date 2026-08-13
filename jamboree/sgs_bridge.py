"""Direct SGS transport for Hoppers and Joeys.

No credential is placed in a subprocess argument or debug curl command.  The
client tries mutual-TLS/digest first when credentials exist, then the engineering
HTTP endpoints supported by some lab images.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from requests.auth import HTTPDigestAuth

from . import mac_learning
from .commands import get_sgs_codes
from .core.credentials import CredentialManager
from .sgs_lib import sgs_get_receiver_id
from .stb_store import store

LOG = logging.getLogger(__name__)
PACKAGE_DIR = Path(__file__).resolve().parent
CERT_PEM = PACKAGE_DIR / "cert.pem"
KEY_PEM = PACKAGE_DIR / "key.pem"
CID_CACHE: Dict[Tuple[str, str], Tuple[int, float]] = {}
CACHE_TTL_S = 150.0
DEFAULT_REQUEST_TIMEOUT_S = 2.0


def clear_cid_cache() -> None:
    CID_CACHE.clear()


def _cert() -> Optional[Tuple[str, str]]:
    if CERT_PEM.is_file() and KEY_PEM.is_file():
        return str(CERT_PEM), str(KEY_PEM)
    return None


def _verify_setting() -> bool | str:
    ca_bundle = os.getenv("JAMBOREE_SGS_CA_BUNDLE", "").strip()
    if ca_bundle:
        return ca_bundle
    return os.getenv("JAMBOREE_SGS_VERIFY_TLS", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _request_timeout_s() -> float:
    """Return the per-endpoint timeout for normal remote-key traffic.

    Three endpoints may be attempted serially. Keep the default total failure
    budget below the automation client's 10-second request timeout while still
    allowing an explicit environment override for unusual lab images.
    """
    raw = os.getenv("JAMBOREE_SGS_REQUEST_TIMEOUT_S", "").strip()
    if not raw:
        return DEFAULT_REQUEST_TIMEOUT_S
    try:
        return max(0.25, float(raw))
    except ValueError:
        LOG.warning(
            "ignoring invalid JAMBOREE_SGS_REQUEST_TIMEOUT_S=%r; using %.1fs",
            raw,
            DEFAULT_REQUEST_TIMEOUT_S,
        )
        return DEFAULT_REQUEST_TIMEOUT_S


def _credentials(alias: str) -> Optional[Tuple[str, str]]:
    username, password = CredentialManager.get_credentials(alias, store.document())
    return (username, password) if username and password else None


def _key_name_for_button(button_id: str, delay_ms: int) -> Optional[str]:
    """Preserve Sling's expected SGS button semantics."""
    normalized = str(button_id or "").strip().lower()
    if normalized in {"diamond", "d"}:
        return "Record"
    if normalized == "pause":
        return "Pause"
    if normalized == "play":
        return "Play"
    if normalized == "pauseplay":
        return "Pause/Play"
    return get_sgs_codes(button_id, int(delay_ms))


def _post(
    ip: str,
    payload: dict,
    *,
    creds: Optional[Tuple[str, str]],
    timeout: Optional[float] = None,
) -> dict:
    request_timeout = _request_timeout_s() if timeout is None else max(0.05, float(timeout))
    attempts: list[tuple[str, bool]] = []
    if creds:
        attempts.append((f"https://{ip}/www/sgs", True))
    attempts.extend(
        ((f"http://{ip}:8080/www/sgs", False), (f"http://{ip}/www/sgs", False))
    )
    errors: list[str] = []
    for url, secure in attempts:
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                auth=HTTPDigestAuth(*creds) if creds else None,
                verify=_verify_setting() if secure else True,
                cert=_cert() if secure else None,
                timeout=request_timeout,
            )
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue
        if response.status_code in (401, 403):
            clear_cid_cache()
            raise PermissionError(f"SGS authentication failed (HTTP {response.status_code})")
        try:
            data = response.json()
        except ValueError:
            errors.append(f"{url}: non-JSON HTTP {response.status_code}")
            continue
        if isinstance(data, dict) and data.get("result") == 1:
            return data
        errors.append(f"{url}: result={data.get('result') if isinstance(data, dict) else 'invalid'}")
    raise RuntimeError("SGS request failed: " + "; ".join(errors))


def _host_for(alias: str) -> tuple[str, dict, str, dict]:
    info = store.get(alias) or {}
    role = str(info.get("role", "hopper")).lower()
    if role == "joey" or info.get("master_stb"):
        host_alias = str(info.get("host") or info.get("master_stb") or "").strip()
        host = store.get(host_alias) or {}
        if not host_alias or not host.get("ip"):
            raise ValueError(f"Joey {alias!r} has no valid host Hopper")
        return alias, info, host_alias, host
    return alias, info, alias, info


def get_or_attach_cid(joey_rid: str, hopper_alias: str, hopper_ip: str) -> int:
    key = (str(joey_rid), str(hopper_ip))
    cached = CID_CACHE.get(key)
    if cached and time.monotonic() - cached[1] < CACHE_TTL_S:
        return cached[0]
    creds = _credentials(hopper_alias)
    if not creds:
        raise PermissionError(f"No SGS credentials for Hopper {hopper_alias!r}; pair first")
    data = _post(
        hopper_ip,
        {
            "command": "attach",
            "receiver": sgs_get_receiver_id(),
            "stb": str(joey_rid),
            "tv_id": 0,
            "attr": 1,
        },
        creds=creds,
    )
    if "cid" not in data:
        raise RuntimeError(f"attach succeeded without cid: {data}")
    cid = int(data["cid"])
    CID_CACHE[key] = (cid, time.monotonic())
    return cid


def attach_alias(alias: str) -> Optional[int]:
    requested, info, host_alias, host = _host_for(alias)
    rxid = str(info.get("stb") or "")
    if not rxid:
        raise ValueError(f"{requested!r} requires an RxID")
    if requested == host_alias:
        # A Hopper does not need a cid for remote_key; validate credentials with
        # a harmless authenticated attach and return any cid the image supplies.
        creds = _credentials(host_alias)
        if not creds:
            raise PermissionError(f"No SGS credentials for Hopper {host_alias!r}; pair first")
        data = _post(
            str(host.get("ip") or ""),
            {
                "command": "attach",
                "receiver": sgs_get_receiver_id(),
                "stb": rxid,
                "tv_id": 0,
                "attr": 1,
            },
            creds=creds,
        )
        return int(data["cid"]) if "cid" in data else None
    return get_or_attach_cid(rxid, host_alias, str(host["ip"]))


def send_sgs(
    stb_name: str,
    stb_ip: str,
    rxid: str,
    button_id: str,
    delay_ms: int,
    *,
    verbose: bool = False,
) -> str:
    key_name = _key_name_for_button(button_id, int(delay_ms))
    if not key_name:
        raise ValueError(f"No SGS mapping for {button_id!r}")

    requested, info, target_alias, target = _host_for(stb_name)
    target_ip = str(target.get("ip") or stb_ip or "")
    requested_rxid = str(rxid or info.get("stb") or "")
    if not target_ip or not requested_rxid:
        raise ValueError(f"{requested!r} requires IP and RxID")

    cid: Optional[int] = None
    command_stb_rid = requested_rxid
    if requested != target_alias:
        # Joey SGS is proxied through its host Hopper.  The attach identifies the
        # Joey by its own RxID and returns a child-specific CID.  remote_key is
        # then addressed to the *host Hopper RID* with that CID selecting the
        # attached Joey.  Sending the Joey RxID in remote_key.stb is accepted by
        # some images but can operate the Hopper itself instead of the child.
        cid = get_or_attach_cid(requested_rxid, target_alias, target_ip)
        command_stb_rid = str(target.get("stb") or "")
        if not command_stb_rid:
            raise ValueError(f"Host Hopper {target_alias!r} requires an RxID")

    payload = {
        "command": "remote_key",
        "receiver": sgs_get_receiver_id(),
        "stb": command_stb_rid,
        "tv_id": 0,
        "key_name": key_name,
    }
    if cid is not None:
        payload["cid"] = cid
    if verbose:
        LOG.debug(
            "SGS send alias=%s host=%s ip=%s requested_rid=%s command_stb=%s key=%s cid=%s",
            requested,
            target_alias,
            target_ip,
            requested_rxid,
            command_stb_rid,
            key_name,
            cid,
        )
    data = _post(target_ip, payload, creds=_credentials(target_alias))
    # A result=1 is the strongest cheap evidence available that this resolved
    # target alias really was reached at target_ip.  Learn its ARP MAC only after
    # that success, in a daemon worker, so healthy keypress latency is unchanged.
    mac_learning.learn_verified_mac_async(target_alias, target_ip)
    return json.dumps(data, sort_keys=True)
