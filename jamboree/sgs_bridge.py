"""
Wrapper for calling the on-disk `sgs_remote.py`, with rich debug output
 to diagnose missing modules, wrong working dir, etc.

Joey devices route commands through their host Hopper:
  • Hopper’s RID (stb) and IP become the POST target
  • Joey’s RID becomes the “cid” in the payload
"""
from __future__ import annotations
import subprocess
import json
import shutil
import logging
import sys
from pathlib import Path

from .commands import get_sgs_codes
from .sgs_lib import sgs_get_receiver_id, DEFAULT_CID
from .stb_store import store

# full path to jamboree/sgs_remote.py (or pick from $PATH)
SGS_REMOTE = (
    shutil.which("sgs_remote.py")
    or Path(__file__).with_name("sgs_remote.py")
)
if not Path(SGS_REMOTE).is_file():
    logging.error("sgs_remote.py not found at %s", SGS_REMOTE)
    sys.exit(1)


def send_sgs(
    stb_name: str,
    stb_ip: str,
    rxid: str,
    button_id: str,
    delay_ms: int,
    *,
    verbose: bool = False,
) -> str:
    """
    Send a remote_key command over Sling’s SGS API.

    Params:
      stb_name  – alias as listed in base.txt
      stb_ip    – the IP from which to POST (hopper for joeys)
      rxid      – RID from the STB row (hopper.RID or joey.RID)
      button_id – JAMbo button identifier
      delay_ms  – key press duration

    Returns: helper stdout on success, otherwise raises.
    """
    # 1) map our button → SGS key
    key_name = get_sgs_codes(button_id, delay_ms)
    if not key_name:
        raise ValueError(f"No SGS mapping for button '{button_id}'")

    # 2) look up row data
    info = store.get(stb_name) or {}
    role = info.get("role", "hopper").lower()

    # 3) decide if Joey or Hopper, and setup target and payload IDs
    if role == "joey":
        host_name = info.get("host") or ""
        host_info = store.get(host_name)
        if not host_info:
            raise ValueError(
                f"Joey '{stb_name}' references unknown host '{host_name}'"
            )
        target_ip = host_info["ip"]
        target_name = host_name
        stb_rid = host_info["stb"]
        cid = rxid
    else:
        target_ip = stb_ip
        target_name = stb_name
        stb_rid = rxid
        cid = None

    # 4) build payload
    payload = {
        "command":  "remote_key",
        "stb":      stb_rid,
        "tv_id":    0,
        "key_name": key_name,
        "receiver": sgs_get_receiver_id(),
    }
    if cid:
        payload["cid"] = cid

    # 5) collect prod/dev flags from the *target* row
    extra: list[str] = []
    tgt = store.get(target_name) or {}
    if tgt.get("lname") and tgt.get("passwd"):
        extra = [
            "--prod",
            "--login",  tgt["lname"],
            "--passwd", tgt["passwd"],
        ]

    # 6) assemble command line
    cmd = [
        sys.executable,
        "-m", "jamboree.sgs_remote",
        "-n", target_name,
        "-i", target_ip,
        *extra,
        json.dumps(payload),
    ]

    # 7) debug output
    if verbose or logging.getLogger().isEnabledFor(logging.DEBUG):
        logging.debug("—" * 60)
        logging.debug("SGS send: role=%s  alias=%s  host=%s",
                      role, stb_name, target_name)
        logging.debug(" → IP=%s  RID(stb)=%s  CID=%s  key=%s",
                      target_ip, stb_rid, cid or DEFAULT_CID, key_name)
        logging.debug(" → payload: %s", json.dumps(payload))
        logging.debug(" → cmd: %s", " ".join(cmd))

    # 8) invoke helper
    completed = subprocess.run(cmd, capture_output=True, text=True)

    # 9) log helper output
    logging.debug("← SGS returncode: %s", completed.returncode)
    logging.debug("← SGS stdout: %s", completed.stdout.strip())
    if completed.stderr:
        logging.debug("← SGS stderr: %s", completed.stderr.strip())

    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "sgs_remote error")

    return completed.stdout.strip()
