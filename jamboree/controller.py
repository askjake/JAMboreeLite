# --- jamboree/controller.py ---
"""Orchestrates RF, SGS and DART logic for Flask routes."""

import logging, time
from datetime import datetime, timezone
from typing import Dict

from .serial_bridge import send_rf, send_quick_dart
from .sgs_bridge import send_sgs
from .stb_store import store

RESET_DEFAULT_MS = 500

class Controller:
    def __init__(self):
        logging.info("Controller initialised – %d STBs", len(store.all()))

    # ------------------------------ helpers (centralize special commands)
    def _per_remote_reset(self, stb_name: str) -> Dict:
        """Issue a per-remote reset through the DART line so Arduino handles it uniformly."""
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found in base.txt")
        remote = stb["remote"]
        # Format B: "<remote> 99 reset" → Arduino does per-remote reset
        sent = send_quick_dart(stb_name, remote, "reset", "reset")
        return {"reset_line": sent, "ts": datetime.now(timezone.utc).isoformat()}

    def _all_up(self, stb_name: str) -> Dict:
        """Release all pressed buttons on this remote."""
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found in base.txt")
        remote = stb["remote"]
        # Either "<remote> 86 up" or "<remote> any allup" is accepted by the sketch
        sent = send_quick_dart(stb_name, remote, "allup", "allup")
        return {"allup_line": sent, "ts": datetime.now(timezone.utc).isoformat()}

    # ------------------------------ RF / AUTO
    def handle_auto_remote(self, remote: str, stb_name: str, button_id: str, delay: int) -> Dict:
        """
        AUTO path previously went straight to RF (or SGS).
        Now we special-case 'reset' and 'allup' to ensure behavior matches DART/Arduino semantics.
        """
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found in base.txt")

        # Normalize specials for both protocol families
        bid = (button_id or "").lower()
        if bid in ("reset", "rst"):
            return self._per_remote_reset(stb_name)
        if bid in ("allup", "all_up", "release"):
            return self._all_up(stb_name)

        if stb["protocol"].upper() == "SGS":
            return self.sgs_remote(stb_name, stb["ip"], stb["stb"], button_id, delay)

        # default RF via serial_mgr using the STB alias
        ack = send_rf(stb_name, remote, button_id, delay)
        return {"rf_line": ack, "ts": datetime.now(timezone.utc).isoformat()}

    # ------------------------------ SGS
    def sgs_remote(self, stb_name: str, stb_ip: str, rxid: str, button_id: str, delay: int):
        resp = send_sgs(stb_name, stb_ip, rxid, button_id, delay)
        return {"stdout": resp, "ts": datetime.now(timezone.utc).isoformat()}

    # ------------------------------ DART
    def dart(self, stb_name: str, button_id: str, action: str):
        """
        Accepts:
          action in {"down","up"} → pass through
          action == "reset"       → per-remote reset (ignores button_id)
          action == "allup"       → release all (ignores button_id)
          action is numeric ms    → Format A-style instantaneous DOWN+UP (legacy)
        """
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found in base.txt")
        remote = stb["remote"]

        act = (action or "").lower()

        if act == "reset":
            sent = send_rf(stb_name, remote, "reset", "80")
            return {"dart_line": sent, "ts": datetime.now(timezone.utc).isoformat()}

        if act in ("allup", "all_up", "release"):
            sent = send_quick_dart(stb_name, remote, "allup", "allup")
            return {"dart_line": sent, "ts": datetime.now(timezone.utc).isoformat()}

        if act in ("down", "up"):
            sent = send_quick_dart(stb_name, remote, button_id, act)
            return {"dart_line": sent, "ts": datetime.now(timezone.utc).isoformat()}

        # Fallback: if action is a number, treat as a timed press
        try:
            ms = int(act)
            sent = send_rf(stb_name, remote, button_id, ms)
            return {"dart_line": sent, "ts": datetime.now(timezone.utc).isoformat()}
        except ValueError:
            raise ValueError(f"Unsupported DART action '{action}'. Use down|up|reset|allup|<ms>.")

    # ------------------------------ UNPAIR
    def unpair(self, stb_name: str):
        """SAT 3s (hold), then DVR+Guide 3s (hold), then release both."""
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found")
        remote = stb["remote"]

        # Use /auto for SAT (allows SGS path if present), then /dart for the simultaneous two-button chord.
        # 1 · SAT hold 3 s
        #self.handle_auto_remote(remote, stb_name, "sat", 3010)
        self.dart(stb_name, "sat", "down")
        time.sleep(3.10)
        self.dart(stb_name, "sat", "up")

        # 2 · DVR & Guide down together via DART
        time.sleep(0.10)
        self.dart(stb_name, "dvr", "down")
        time.sleep(0.05)
        self.dart(stb_name, "guide", "down")

        time.sleep(3.10)

        # 3 · release both
        self.dart(stb_name, "dvr", "up")
        time.sleep(0.05)
        self.dart(stb_name, "guide", "up")

        return {"unpaired": stb_name, "ts": datetime.now(timezone.utc).isoformat()}





