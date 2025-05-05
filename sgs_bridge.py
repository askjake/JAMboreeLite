# --- jamboree/sgs_bridge.py ---------------------------------------------
"""
Wrapper for calling the on-disk `sgs_remote.py`, with rich debug output
to diagnose missing modules, wrong working dir, etc.
"""
from __future__ import annotations
import subprocess, json, shutil, logging, sys
from pathlib import Path

from .commands import get_sgs_codes
from .sgs_lib import sgs_get_receiver_id, DEFAULT_CID     # for receiver / cid

# full path to jamboree/sgs_remote.py (or system one if on $PATH)
SGS_REMOTE = (
    shutil.which("sgs_remote.py")
    or Path(__file__).with_name("sgs_remote.py")
)

if not Path(SGS_REMOTE).is_file():
    logging.error("sgs_remote.py not found at %s", SGS_REMOTE)
    sys.exit(1)

# ---------------------------------------------------------------------------
def send_sgs(stb_name: str, stb_ip: str, rxid: str,
             button_id: str, delay_ms: int) -> str:
    """
    Translate JAMbo button -> SGS key name -> run sgs_remote.py
    Return stdout from the helper (for flask/api JSON reply)
    """
    key_name = get_sgs_codes(button_id, delay_ms)
    if not key_name:
        raise ValueError(f"No SGS mapping for button '{button_id}'")

    payload = {
        "command":  "remote_key",
        "stb":      rxid,                     # target receiver ID
        "tv_id":    0,
        "key_name": key_name,                 # e.g. "Enter"
        "receiver": sgs_get_receiver_id(),    # this PC’s RID
        "cid":      DEFAULT_CID,              # 1004 for dev boxes
    }

    cmd = [
        sys.executable,               # same interpreter that runs Flask
        str(SGS_REMOTE),
        "-n", stb_name,               # let sgs_remote read prod/dev info
        json.dumps(payload)
    ]

    logging.debug("→ Running SGS command:\n   %s", " ".join(cmd))
    completed = subprocess.run(
        cmd, capture_output=True, text=True
    )
    logging.debug("← SGS returncode: %s", completed.returncode)
    logging.debug("← SGS stdout: %s", completed.stdout.strip())
    if completed.stderr:
        logging.debug("← SGS stderr: %s", completed.stderr.strip())

    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "sgs_remote error")

    return completed.stdout.strip()