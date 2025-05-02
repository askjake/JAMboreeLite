# --- jamboree/sgs_bridge.py ---
"""Tiny wrapper so we can call existing `sgs_remote.py` in‑process."""
import subprocess, json, shutil, logging
from pathlib import Path

SGS_REMOTE = shutil.which("sgs_remote.py") or Path(__file__).parent / "sgs_remote.py"

from commands import get_sgs_codes

def send_sgs(stb_name: str, stb_ip: str, rxid: str, button_id: str, delay_ms: int):
    cmd_name = get_sgs_codes(button_id, delay_ms)
    if not cmd_name:
        raise ValueError(f"Unknown SGS mapping for {button_id}")
    payload = json.dumps({"command": cmd_name, "receiver": rxid, "cid": 0,
                          "start_svc": 0, "size": 0})
    cmd = ["python3", str(SGS_REMOTE), "-n", stb_name, payload]
    logging.debug("Running %s", cmd)
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return completed.stdout