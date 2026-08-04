"""Direct SGS transport for Hoppers and Joeys without credential-bearing subprocesses."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from requests.auth import HTTPDigestAuth

from .commands import get_sgs_codes
from .core.credentials import CredentialManager
from .sgs_lib import DEFAULT_CID, sgs_get_receiver_id
from .stb_store import store

LOG = logging.getLogger(__name__)
PACKAGE_DIR = Path(__file__).resolve().parent
CERT_PEM = PACKAGE_DIR / "cert.pem"
KEY_PEM = PACKAGE_DIR / "key.pem"
CID_CACHE: Dict[Tuple[str, str], Tuple[int, float]] = {}
CACHE_TTL_S = 150.0


def _cert() -> Optional[Tuple[str, str]]:
    if CERT_PEM.is_file() and KEY_PEM.is_file():
        return str(CERT_PEM), str(KEY_PEM)
    return None


def _post(ip: str, payload: dict, *, creds: Optional[Tuple[str, str]], timeout: float = 7.0) -> dict:
    attempts = []
    if creds:
        attempts.append((f"https://{ip}/www/sgs", True))
    attempts.extend(((f"http://{ip}:8080/www/sgs", False), (f"http://{ip}/www/sgs", False)))
    errors = []
    for url, secure in attempts:
        try:
            response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, auth=HTTPDigestAuth(*creds) if creds else None, verify=False if secure else True, cert=_cert() if secure else None, timeout=timeout)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue
        if response.status_code in (401, 403):
            raise PermissionError(f"SGS authentication failed (HTTP {response.status_code})")
        try:
            data = response.json()
        except ValueError:
            errors.append(f"{url}: non-JSON HTTP {response.status_code}")
            continue
        if data.get("result") == 1:
            return data
        errors.append(f"{url}: {data}")
    raise RuntimeError("SGS request failed: " + "; ".join(errors))


def _credentials(alias: str) -> Optional[Tuple[str, str]]:
    username, password = CredentialManager.get_credentials(alias, store.document())
    return (username, password) if username and password else None


def get_or_attach_cid(joey_rid: str, hopper_alias: str, hopper_ip: str) -> int:
    key = (joey_rid, hopper_ip)
    cached = CID_CACHE.get(key)
    if cached and time.monotonic() - cached[1] < CACHE_TTL_S:
        return cached[0]
    creds = _credentials(hopper_alias)
    if not creds:
        raise PermissionError(f"No SGS credentials for Hopper {hopper_alias!r}; pair first")
    data = _post(hopper_ip, {"command": "attach", "receiver": sgs_get_receiver_id(), "stb": joey_rid, "tv_id": 0, "attr": 1}, creds=creds)
    if "cid" not in data:
        raise RuntimeError(f"attach succeeded without cid: {data}")
    cid = int(data["cid"])
    CID_CACHE[key] = (cid, time.monotonic())
    return cid


def send_sgs(stb_name: str, stb_ip: str, rxid: str, button_id: str, delay_ms: int, *, verbose: bool = False) -> str:
    key_name = get_sgs_codes(button_id, int(delay_ms))
    if not key_name:
        raise ValueError(f"No SGS mapping for {button_id!r}")
    info = store.get(stb_name) or {}
    role = str(info.get("role", "hopper")).lower()
    target_alias, target_ip, cid = stb_name, str(stb_ip), None
    if role == "joey":
        target_alias = str(info.get("host") or "")
        host = store.get(target_alias) or {}
        if not target_alias or not host.get("ip"):
            raise ValueError(f"Joey {stb_name!r} has no valid host Hopper")
        target_ip = str(host["ip"])
        cid = get_or_attach_cid(str(rxid), target_alias, target_ip)
    payload = {"command": "remote_key", "receiver": sgs_get_receiver_id(), "stb": str(rxid), "tv_id": 0, "key_name": key_name}
    if cid is not None:
        payload["cid"] = cid
    creds = _credentials(target_alias)
    if verbose:
        LOG.debug("SGS send alias=%s host=%s ip=%s key=%s cid=%s", stb_name, target_alias, target_ip, key_name, cid or DEFAULT_CID)
    return str(_post(target_ip, payload, creds=creds))
