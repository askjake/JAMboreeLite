# --- jamboree/controller.py ---
"""Orchestrates RF, SGS and DART logic for Flask routes."""
import logging, time
from datetime import datetime, timezone
from typing import Dict

from serial_bridge import send_rf
from sgs_bridge import send_sgs
from stb_store import store

class Controller:
    def __init__(self):
        logging.info("Controller initialised – %d STBs", len(store.all()))

    # ------------------------------------------------------------------ RF / AUTO
    def handle_auto_remote(self, remote: str, stb_name: str, button_id: str,
                           delay: int) -> Dict:
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found in base.txt")
        if stb["protocol"].upper() == "SGS":
            return self.sgs_remote(stb_name, stb["ip"], stb["stb"], button_id, delay)
        # default RF
        ack = send_rf(stb["com_port"], remote, button_id, delay)
        return {"rf_line": ack, "ts": datetime.now(timezone.utc).isoformat()}

    # ------------------------------------------------------------------ SGS
    def sgs_remote(self, stb_name: str, stb_ip: str, rxid: str,
                   button_id: str, delay: int):
        resp = send_sgs(stb_name, stb_ip, rxid, button_id, delay)
        return {"stdout": resp, "ts": datetime.now(timezone.utc).isoformat()}

    # ------------------------------------------------------------------ DART
    def dart(self, stb_name: str, button_id: str, action: str):
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found in base.txt")
        port, remote = stb["com_port"], stb["remote"]
        if action in ("down", "up"):
            # quickDART –  just forward the literal action
            line = f"{remote} {button_id} {action}\n"
        else:
            # normal DART – action == hold‑time‑ms string
            line = f"{remote} {button_id} {int(action)}\n"
        _ = send_rf(port, remote, button_id, 0)  # uses KEY_CMD/RELEASE internally
        return {"dart_line": line.strip(), "ts": datetime.now(timezone.utc).isoformat()}
