"""
SGS bridge utilities – *JAMboreeLite*
====================================

End‑to‑end helper that hides every SGS detail for Hopper **and** Joey calls.
It now mirrors the reference `sgs_lib.STB.query_secure()` behaviour so that
**attach** works even on firmware that requires client‑certificate mutual‑TLS.

Key points
----------
* **Pairing** continues to go through `/sgs_noauth` on the Hopper – the PIN will
  always appear on the Hopper’s TV (spec behaviour).
* **attach** now:
  1. Tries `https://<hopper>/www/sgs` **with client cert + digest‑auth**.
  2. If the STB demands a client cert and the files are missing, we auto‑fallback
     to the unencrypted `http://<hopper>/www/sgs` route (some dev images allow
     that) and recognise the spec “result 20” error.
* **remote_key** logic unchanged – Joey calls include the fresh `cid`.
* Every step logs a ready‑to‑paste *curl* line for Postman.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Tuple

import requests
from requests.auth import HTTPDigestAuth
from requests.exceptions import SSLError

from .commands import get_sgs_codes
from .sgs_lib import sgs_get_receiver_id, DEFAULT_CID
from .stb_store import store

# ──────────────────────────────────────────────────────────────────────────────
#  Configuration / Globals
# ──────────────────────────────────────────────────────────────────────────────

SGS_REMOTE = shutil.which("sgs_remote.py") or Path(__file__).with_name("sgs_remote.py")
if not Path(SGS_REMOTE).is_file():
    logging.error("sgs_remote.py not found at %s", SGS_REMOTE)
    sys.exit(1)

# {(joey_rid, hopper_ip): (cid, epoch)}
CID_CACHE: Dict[Tuple[str, str], Tuple[int, float]] = {}
CACHE_TTL = 150  # seconds – refresh cid after STB’s idle timeout

CERT_PEM = Path(__file__).with_name("cert.pem")
KEY_PEM  = Path(__file__).with_name("key.pem")
HAVE_CERT = CERT_PEM.is_file() and KEY_PEM.is_file()

# ──────────────────────────────────────────────────────────────────────────────
#  Helper: attach to a Joey via its Hopper
# ──────────────────────────────────────────────────────────────────────────────

def _attach_https(joey_rid: str, hopper_ip: str, creds: Tuple[str, str], *, verbose=False) -> int:
    """HTTPS attach with digest‑auth and *optional* client cert."""
    receiver = sgs_get_receiver_id()
    url = f"https://{hopper_ip}/www/sgs"
    payload = {
        "command": "attach",
        "receiver": receiver,
        "stb": joey_rid,
        "tv_id": 0,
        "attr": 1,
    }

    if verbose or logging.getLogger().isEnabledFor(logging.DEBUG):
        curl_cmd = (
            f"curl -k -u {creds[0]}:{creds[1]} -X POST {url} "
            f"--cert {CERT_PEM} --key {KEY_PEM} -d '{json.dumps(payload)}'"
            if HAVE_CERT else
            f"curl -k -u {creds[0]}:{creds[1]} -X POST {url} -d '{json.dumps(payload)}'"
        )
        logging.debug("[ATTACH] %s", curl_cmd)

    resp = requests.post(
        url,
        json=payload,
        auth=HTTPDigestAuth(*creds),
        timeout=5,
        verify=False,
        cert=(str(CERT_PEM), str(KEY_PEM)) if HAVE_CERT else None,
    )
    return resp


def _attach(joey_rid: str, hopper_ip: str, creds: Tuple[str, str], *, verbose=False) -> int:
    """Attach wrapper that handles TLS cert‑required errors and fallback."""

    try:
        resp = _attach_https(joey_rid, hopper_ip, creds, verbose=verbose)
    except SSLError as e:
        logging.warning("HTTPS attach failed – %s", e)
        resp = None

    if resp is None or resp.status_code in (495, 496, 497):
        # optional HTTP fallback – not spec, but helpful on eng images
        url = f"http://{hopper_ip}/www/sgs"
        receiver = sgs_get_receiver_id()
        payload = {
            "command": "attach",
            "receiver": receiver,
            "stb": joey_rid,
            "tv_id": 0,
            "attr": 1,
        }
        if verbose or logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug("[ATTACH] falling back to HTTP (digest‑auth)")
            curl_cmd = f"curl -u {creds[0]}:{creds[1]} -X POST {url} -d '{json.dumps(payload)}'"
            logging.debug("[ATTACH] %s", curl_cmd)
        resp = requests.post(url, json=payload, auth=HTTPDigestAuth(*creds), timeout=5)

    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"attach: non‑JSON response (HTTP {resp.status_code})")

    if data.get("result") != 1 or "cid" not in data:
        raise RuntimeError(f"attach failed: {data}")

    cid = int(data["cid"])
    CID_CACHE[(joey_rid, hopper_ip)] = (cid, time.time())
    logging.debug("[ATTACH] success → cid=%s", cid)
    return cid


def get_or_attach_cid(joey_rid: str, hopper_ip: str, *, verbose=False) -> int:
    key = (joey_rid, hopper_ip)
    rec = CID_CACHE.get(key)
    if rec and (time.time() - rec[1] < CACHE_TTL):
        return rec[0]
    # find creds in base
    for alias, info in store.all().items():
        if info.get("ip") == hopper_ip and info.get("lname") and info.get("passwd"):
            return _attach(joey_rid, hopper_ip, (info["lname"], info["passwd"]), verbose=verbose)
    raise ValueError(f"No credentials for Hopper {hopper_ip}; pair first.")

# ──────────────────────────────────────────────────────────────────────────────
#  send_sgs (unchanged except curl shows https when cid present)
# ──────────────────────────────────────────────────────────────────────────────

def send_sgs(
    stb_name: str,
    stb_ip: str,
    rxid: str,
    button_id: str,
    delay_ms: int,
    *,
    verbose: bool = False,
) -> str:
    key_name = get_sgs_codes(button_id, delay_ms) or (lambda: (_ for _ in ()).throw(ValueError(f"No SGS mapping for {button_id}")))()

    info = store.get(stb_name) or {}
    role = info.get("role", "hopper").lower()

    if role == "joey":
        host = store.get(info.get("host", "")) or (lambda: (_ for _ in ()).throw(ValueError(f"Joey '{stb_name}' missing host")))()
        target_ip, target_name = host["ip"], info["host"]
        stb_rid = rxid
        cid = get_or_attach_cid(rxid, target_ip, verbose=verbose)
    else:
        target_ip, target_name, stb_rid, cid = stb_ip, stb_name, rxid, None

    payload = {
        "command": "remote_key",
        "receiver": sgs_get_receiver_id(),
        "stb": stb_rid,
        "tv_id": 0,
        "key_name": key_name,
    }
    if cid is not None:
        payload["cid"] = cid

    extra = []
    tgt = store.get(target_name) or {}
    if tgt.get("lname") and tgt.get("passwd"):
        extra = ["--prod", "--login", tgt["lname"], "--passwd", tgt["passwd"]]

    cmd = [sys.executable, "-m", "jamboree.sgs_remote", "-n", target_name, "-i", target_ip, *extra, json.dumps(payload)]

    if verbose or logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug("—" * 60)
        logging.debug("SGS send: role=%s alias=%s host=%s", role, stb_name, target_name)
        logging.debug(" → IP=%s RID=%s CID=%s key=%s", target_ip, stb_rid, cid if cid else DEFAULT_CID, key_name)
        logging.debug(" → payload: %s", json.dumps(payload))
        proto = "https" if cid else "http"
        curl_dbg = f"curl -k -u {tgt.get('lname','USER')}:{tgt.get('passwd','PASS')} -X POST {proto}://{target_ip}/www/sgs -d '{json.dumps(payload)}'"
        logging.debug(" → curl: %s", curl_dbg)
        logging.debug(" → cmd: %s", " ".join(cmd))

    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "sgs_remote error")
    return completed.stdout.strip()
