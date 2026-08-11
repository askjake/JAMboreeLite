"""Transport-aware STB command orchestration.

Normal SGS commands can recover a stale IP and then fall back to DART/RF.  A
forced transport is strict: ``force='sgs'`` never hides failure behind RF, and
``force='rf'`` never touches the network.

The normal request path intentionally does not run a full subnet recovery scan
synchronously. A failed request first refreshes externally changed configuration
and retries immediately if the SGS target IP changed; otherwise expensive
recovery is scheduled as a single background operation so automation retries do
not multiply long-running scans.
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
        # Retained for API/backwards compatibility with callers that construct a
        # Controller with a custom manual recoverer. Normal /auto traffic no
        # longer invokes a full synchronous recovery scan.
        self._recoverer = recoverer
        LOG.info("Controller initialized with %d STB(s)", len(store.all()))

    @staticmethod
    def _entry(alias: str) -> Dict[str, Any]:
        entry = store.get(alias)
        if not entry:
            raise ValueError(f"STB {alias!r} not found")
        return entry

    @classmethod
    def _sgs_target(cls, alias: str) -> tuple[str, Dict[str, Any]]:
        """Return the Hopper/config entry whose IP actually receives SGS."""
        entry = cls._entry(alias)
        role = str(entry.get("role", "hopper")).lower()
        if role == "joey" or entry.get("master_stb"):
            host_alias = str(entry.get("host") or entry.get("master_stb") or "").strip()
            host = store.get(host_alias) if host_alias else None
            if host_alias and host and host.get("ip"):
                return host_alias, host
        return alias, entry

    @staticmethod
    def _refresh_store(*, force: bool = False) -> bool:
        refresh = getattr(store, "refresh_if_changed", None)
        if not callable(refresh):
            return False
        try:
            return bool(refresh(force=force))
        except TypeError:
            return bool(refresh())
        except Exception as exc:
            LOG.warning("could not refresh STB configuration after SGS failure: %s", exc)
            return False

    @staticmethod
    def _send_sgs_entry(
        stb_name: str,
        entry: Dict[str, Any],
        button: str,
        duration: int,
    ) -> str:
        return send_sgs(
            stb_name,
            str(entry.get("ip") or ""),
            str(entry.get("stb") or ""),
            button,
            duration,
        )

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

        target_alias, target = self._sgs_target(stb_name)
        initial_target_ip = str(target.get("ip") or "")

        try:
            response = self._send_sgs_entry(stb_name, entry, button, duration)
            ip_recovery.note_sgs_success(stb_name)
            return {"ok": True, "via": "sgs", "stdout": response, "ts": _ts()}
        except Exception as first_exc:
            first_text = str(first_exc)
            verdict = classify_sgs_failure(first_exc)
            if not forced:
                # Track failures against the receiver whose IP actually carried
                # SGS. For a Joey this is its host Hopper, not the child alias.
                ip_recovery.note_sgs_failure(target_alias, first_exc)
            LOG.warning(
                "SGS failed for %s target=%s ip=%s (%s): %s",
                stb_name,
                target_alias,
                initial_target_ip,
                getattr(verdict, "kind", getattr(verdict, "reason", "unknown")),
                first_text,
            )

            recovery_meta: Optional[dict] = None
            active_target_alias = target_alias

            if recover_ip and verdict.dead:
                # A separate helper/process may already have repaired base.txt.
                # Force one cheap reread and retry immediately only if the actual
                # SGS target IP changed. This is the restart-free fast path.
                self._refresh_store(force=True)
                refreshed = self._entry(stb_name)
                active_target_alias, refreshed_target = self._sgs_target(stb_name)
                refreshed_target_ip = str(refreshed_target.get("ip") or "")

                if refreshed_target_ip and refreshed_target_ip != initial_target_ip:
                    LOG.info(
                        "retrying SGS after config refresh alias=%s target=%s old_ip=%s new_ip=%s",
                        stb_name,
                        active_target_alias,
                        initial_target_ip,
                        refreshed_target_ip,
                    )
                    try:
                        response = self._send_sgs_entry(
                            stb_name, refreshed, button, duration
                        )
                        ip_recovery.note_sgs_success(stb_name)
                        return {
                            "ok": True,
                            "via": "sgs_reloaded",
                            "stdout": response,
                            "config_refresh": {
                                "target": active_target_alias,
                                "old_ip": initial_target_ip,
                                "new_ip": refreshed_target_ip,
                            },
                            "ts": _ts(),
                        }
                    except Exception as retry_exc:
                        first_text = (
                            f"{first_text}; retry after config refresh failed: {retry_exc}"
                        )
                        verdict = classify_sgs_failure(retry_exc)

                if verdict.recoverable or verdict.auth or verdict.wrong_device:
                    started = ip_recovery.recover_alias_async(active_target_alias)
                    recovery_meta = {
                        "alias": active_target_alias,
                        "started": bool(started),
                        "mode": "background",
                    }
                    state_text = "started" if started else "already active or cooling down"
                    first_text = (
                        f"{first_text}; background recovery {state_text} "
                        f"for {active_target_alias}"
                    )

            if allow_rf_fallback:
                try:
                    return self._rf_fallback(
                        stb_name,
                        button,
                        duration,
                        sgs_error=first_text,
                        recovery=recovery_meta,
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
