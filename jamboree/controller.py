"""Transport-aware STB command orchestration.

Normal SGS commands can recover a stale IP and then fall back to DART/RF.  A
forced transport is strict: ``force='sgs'`` never hides failure behind RF, and
``force='rf'`` never touches the network.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import ip_recovery
from .core.credentials import CredentialManager
from .serial_bridge import (
    rf_available,
    rf_status,
    send_quick_dart,
    send_rf,
    send_rf_strict,
)
from .sgs_bridge import send_sgs
from .stb_store import store

LOG = logging.getLogger(__name__)

classify_sgs_failure = ip_recovery.classify_sgs_failure


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class Controller:
    def __init__(self, *, recoverer=ip_recovery.recover_alias) -> None:
        self._recoverer = recoverer
        LOG.info("Controller initialized with %d STB(s)", len(store.all()))

    @staticmethod
    def _entry(alias: str) -> Dict[str, Any]:
        entry = store.get(alias)
        if not entry:
            raise ValueError(f"STB {alias!r} not found")
        return entry

    def rf_ready(self, alias: str) -> bool:
        self._entry(alias)
        return rf_available(alias, require_ready=True)

    def rf_remote(self, alias: str, button: str, delay_ms: int) -> Dict[str, Any]:
        entry = self._entry(alias)
        line = send_rf_strict(alias, entry.get("remote"), button, int(delay_ms))
        return {
            "ok": True,
            "via": "rf",
            "rf_line": line,
            "delivery": "serial_flushed",
            "ts": _ts(),
        }

    def _rf_fallback(
        self,
        alias: str,
        button: str,
        delay_ms: int,
        *,
        sgs_error: str,
        recovery: Optional[dict] = None,
    ) -> Dict[str, Any]:
        result = self.rf_remote(alias, button, delay_ms)
        result["via"] = "rf_fallback"
        result["sgs_error"] = sgs_error
        if recovery is not None:
            result["recovery"] = recovery
        return result

    def transports(self, alias: str) -> Dict[str, Any]:
        entry = self._entry(alias)
        role = str(entry.get("role", "hopper")).lower()
        host_alias = str(entry.get("host") or entry.get("master_stb") or alias)
        host = store.get(host_alias) or entry
        paired = CredentialManager.has_stored_credentials(host_alias, store.document())
        return {
            "alias": alias,
            "configured_protocol": str(entry.get("protocol") or "").upper(),
            "role": role,
            "host": host_alias,
            "sgs": {
                "configured": bool(entry.get("stb") and host.get("ip")),
                "ip": host.get("ip"),
                "paired": paired,
            },
            "rf": {
                **rf_status(alias),
                "remote": entry.get("remote"),
                "com_port": entry.get("com_port"),
            },
        }

    def handle_auto_remote(
        self,
        remote: str,
        stb_name: str,
        button_id: str,
        delay: int,
        *,
        force: Optional[str] = None,
        allow_rf_fallback: bool = True,
        recover_ip: bool = True,
    ) -> Dict[str, Any]:
        entry = self._entry(stb_name)
        forced = str(force or "").strip().upper()
        if forced == "DART":
            forced = "RF"
        protocol = forced or str(entry.get("protocol") or "").upper()
        if protocol not in {"RF", "SGS"}:
            raise ValueError(f"unsupported protocol {protocol!r}; expected RF or SGS")

        # Forced transports are diagnostic contracts and must not silently take
        # a different path or start a recovery operation.
        if forced:
            allow_rf_fallback = False
            recover_ip = False

        button = str(button_id or "").strip()
        if not button:
            raise ValueError("button_id is required")
        duration = int(delay)
        bid = button.lower()

        if bid in {"reset", "rst"}:
            line = send_quick_dart(stb_name, entry.get("remote"), "reset", "reset")
            return {
                "ok": True,
                "via": "dart",
                "dart_line": line,
                "delivery": "serial_flushed",
                "ts": _ts(),
            }
        if bid in {"allup", "all_up", "release"}:
            line = send_quick_dart(stb_name, entry.get("remote"), "allup", "allup")
            return {
                "ok": True,
                "via": "dart",
                "dart_line": line,
                "delivery": "serial_flushed",
                "ts": _ts(),
            }

        if protocol == "RF":
            return self.rf_remote(stb_name, button, duration)

        try:
            response = send_sgs(
                stb_name,
                str(entry.get("ip") or ""),
                str(entry.get("stb") or ""),
                button,
                duration,
            )
            ip_recovery.note_sgs_success(stb_name)
            return {"ok": True, "via": "sgs", "stdout": response, "ts": _ts()}
        except Exception as first_exc:
            first_text = str(first_exc)
            verdict = classify_sgs_failure(first_exc)
            if not forced:
                ip_recovery.note_sgs_failure(stb_name, first_exc)
            LOG.warning(
                "SGS failed for %s (%s): %s",
                stb_name,
                getattr(verdict, "kind", getattr(verdict, "reason", "unknown")),
                first_text,
            )

            recovery_result = None
            should_recover = bool(recover_ip and verdict.recoverable)
            if recover_ip and verdict.auth:
                identity = ip_recovery.verify_stored_ip_identity(stb_name)
                if identity.get("is_stb") is False or (
                    identity.get("rxids") and identity.get("rxid_match") is False
                ):
                    should_recover = True
                elif identity.get("is_stb") is True:
                    ip_recovery.trigger_autopair(
                        stb_name, "SGS authentication failed at the configured receiver"
                    )

            if should_recover:
                recovery_result = self._recoverer(stb_name)
                if recovery_result.ok and recovery_result.sgs_verified:
                    refreshed = self._entry(stb_name)
                    try:
                        response = send_sgs(
                            stb_name,
                            str(refreshed.get("ip") or ""),
                            str(refreshed.get("stb") or ""),
                            button,
                            duration,
                        )
                        ip_recovery.note_sgs_success(stb_name)
                        return {
                            "ok": True,
                            "via": "sgs_recovered",
                            "stdout": response,
                            "recovery": recovery_result.to_dict(),
                            "ts": _ts(),
                        }
                    except Exception as retry_exc:
                        first_text = (
                            f"{first_text}; retry after IP recovery failed: {retry_exc}"
                        )

            recovery_dict = recovery_result.to_dict() if recovery_result else None
            if allow_rf_fallback:
                try:
                    return self._rf_fallback(
                        stb_name,
                        button,
                        duration,
                        sgs_error=first_text,
                        recovery=recovery_dict,
                    )
                except Exception as rf_exc:
                    raise RuntimeError(
                        f"SGS failed ({first_text}); RF fallback failed ({rf_exc})"
                    ) from rf_exc
            raise RuntimeError(first_text) from first_exc

    def sgs_remote(
        self,
        stb_name: str,
        stb_ip: str,
        rxid: str,
        button_id: str,
        delay: int,
    ) -> Dict[str, Any]:
        response = send_sgs(stb_name, stb_ip, rxid, button_id, int(delay))
        ip_recovery.note_sgs_success(stb_name)
        return {"ok": True, "via": "sgs", "stdout": response, "ts": _ts()}

    def dart(self, stb_name: str, button_id: str, action: str) -> Dict[str, Any]:
        entry = self._entry(stb_name)
        normalized = str(action or "").lower().strip()
        if normalized.isdigit():
            line = send_rf(stb_name, entry.get("remote"), button_id, int(normalized))
        else:
            line = send_quick_dart(
                stb_name, entry.get("remote"), button_id, normalized
            )
        return {
            "ok": True,
            "via": "dart",
            "dart_line": line,
            "delivery": "serial_flushed",
            "ts": _ts(),
        }

    def unpair(self, stb_name: str) -> Dict[str, Any]:
        try:
            self.dart(stb_name, "sat", "down")
            time.sleep(3.10)
            self.dart(stb_name, "sat", "up")
            time.sleep(0.20)
            self.dart(stb_name, "dvr", "down")
            self.dart(stb_name, "guide", "down")
            time.sleep(3.50)
        finally:
            try:
                self.dart(stb_name, "allup", "allup")
            except Exception:
                LOG.exception("failed to release all buttons after unpair sequence")
        return {"ok": True, "unpaired": stb_name, "ts": _ts()}
