"""Transport-aware command orchestration with SGS recovery and RF fallback."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .ip_recovery import classify_sgs_failure, recover_alias
from .serial_bridge import send_quick_dart, send_rf, send_rf_strict
from .sgs_bridge import send_sgs
from .stb_store import store

LOG = logging.getLogger(__name__)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class Controller:
    def __init__(self, *, recoverer=recover_alias) -> None:
        self._recoverer = recoverer

    @staticmethod
    def _entry(alias: str) -> Dict[str, Any]:
        entry = store.get(alias)
        if not entry:
            raise ValueError(f"STB {alias!r} not found")
        return entry

    def _rf(self, alias: str, button: str, delay: int, *, fallback_error: Optional[str] = None) -> Dict[str, Any]:
        entry = self._entry(alias)
        line = send_rf_strict(alias, entry.get("remote"), button, delay)
        result: Dict[str, Any] = {"ok": True, "via": "rf_fallback" if fallback_error else "rf", "rf_line": line, "ts": _ts()}
        if fallback_error:
            result["sgs_error"] = fallback_error
        return result

    def handle_auto_remote(self, remote: str, stb_name: str, button_id: str, delay: int, *, force: Optional[str] = None, allow_rf_fallback: bool = True, recover_ip: bool = True) -> Dict[str, Any]:
        entry = self._entry(stb_name)
        protocol = str(force or entry.get("protocol") or "").upper()
        if protocol not in {"RF", "SGS"}:
            raise ValueError(f"unsupported protocol {protocol!r}; expected RF or SGS")
        button = str(button_id or "").strip(); bid = button.lower()
        if bid in {"reset", "rst"}:
            line = send_quick_dart(stb_name, entry.get("remote"), "reset", "reset")
            return {"ok": True, "via": "dart", "dart_line": line, "ts": _ts()}
        if bid in {"allup", "all_up", "release"}:
            line = send_quick_dart(stb_name, entry.get("remote"), "allup", "allup")
            return {"ok": True, "via": "dart", "dart_line": line, "ts": _ts()}
        if protocol == "RF":
            return self._rf(stb_name, button, int(delay))
        try:
            response = send_sgs(stb_name, entry.get("ip"), entry.get("stb"), button, int(delay))
            return {"ok": True, "via": "sgs", "stdout": response, "ts": _ts()}
        except Exception as first_exc:
            first_text = str(first_exc)
            failure = classify_sgs_failure(first_exc)
            LOG.warning("SGS failed for %s (%s): %s", stb_name, failure.reason, first_text)
            if recover_ip and failure.recoverable:
                recovered = self._recoverer(stb_name)
                if recovered.ok:
                    refreshed = self._entry(stb_name)
                    try:
                        response = send_sgs(stb_name, refreshed.get("ip"), refreshed.get("stb"), button, int(delay))
                        return {"ok": True, "via": "sgs_recovered", "stdout": response, "old_ip": recovered.old_ip, "new_ip": recovered.new_ip, "ts": _ts()}
                    except Exception as retry_exc:
                        first_text = f"{first_text}; retry after IP recovery failed: {retry_exc}"
            if allow_rf_fallback:
                try:
                    return self._rf(stb_name, button, int(delay), fallback_error=first_text)
                except Exception as rf_exc:
                    raise RuntimeError(f"SGS failed ({first_text}); RF fallback failed ({rf_exc})") from rf_exc
            raise RuntimeError(first_text) from first_exc

    def dart(self, stb_name: str, button_id: str, action: str) -> Dict[str, Any]:
        entry = self._entry(stb_name)
        action = str(action).lower()
        line = send_rf(stb_name, entry.get("remote"), button_id, int(action)) if action.isdigit() else send_quick_dart(stb_name, entry.get("remote"), button_id, action)
        return {"ok": True, "via": "dart", "dart_line": line, "ts": _ts()}

    def unpair(self, stb_name: str) -> Dict[str, Any]:
        try:
            self.dart(stb_name, "sat", "down"); time.sleep(3.10); self.dart(stb_name, "sat", "up"); time.sleep(0.20)
            self.dart(stb_name, "dvr", "down"); self.dart(stb_name, "guide", "down"); time.sleep(3.50)
        finally:
            try:
                self.dart(stb_name, "allup", "allup")
            except Exception:
                LOG.exception("failed to release all buttons after unpair sequence")
        return {"ok": True, "unpaired": stb_name, "ts": _ts()}
