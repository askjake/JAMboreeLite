"""DART/RF command formatting with honest delivery receipts."""
from __future__ import annotations

import logging
import time
from typing import Union

from .commands import get_button_codes, get_button_number
from .serial_hub import serial_mgr

LOG = logging.getLogger(__name__)


def _remote(value: Union[str, int]) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid DART remote {value!r}") from exc
    if number < 1 or number > 16:
        raise ValueError(f"DART remote must be 1..16, got {number}")
    return str(number)


def rf_available(alias_or_com: str, *, require_ready: bool = True) -> bool:
    return serial_mgr.has_port(str(alias_or_com), require_ready=require_ready)


def rf_status(alias_or_com: str) -> dict:
    return serial_mgr.status(str(alias_or_com))


def _write(alias_or_com: str, line: str, *, strict: bool = True) -> str:
    ok = serial_mgr.write(
        str(alias_or_com),
        line.encode("ascii"),
        require_ready=strict,
        wait=True,
        completion_timeout_s=4.0,
    )
    if not ok:
        readiness = "open/ready and writable" if strict else "configured"
        raise RuntimeError(f"DART port for {alias_or_com!r} is not {readiness}")
    LOG.debug("DART -> [%s] %s", alias_or_com, line.rstrip())
    return line.rstrip()


def send_rf(
    alias_or_com: str,
    remote_num: Union[str, int],
    button_id: str,
    delay_ms: Union[str, int],
) -> str:
    """Send legacy Format-A ``down/up/duration`` and wait for serial flush."""
    delay = max(int(delay_ms), 80)
    codes = get_button_codes(button_id)
    if not codes:
        raise ValueError(f"unknown button_id {button_id!r}")
    line = f"{_remote(remote_num)} {codes['KEY_CMD']} {codes['KEY_RELEASE']} {delay}\n"
    result = _write(alias_or_com, line)
    time.sleep((delay + 50) / 1000.0)
    return result


def send_rf_strict(
    alias_or_com: str,
    remote_num: Union[str, int],
    button_id: str,
    delay_ms: Union[str, int],
) -> str:
    return send_rf(alias_or_com, remote_num, button_id, delay_ms)


def send_quick_dart(
    alias_or_com: str,
    remote_num: Union[str, int],
    button_id: str,
    action: str,
) -> str:
    action = str(action).lower().strip()
    if action not in {"down", "up", "reset", "allup"}:
        raise ValueError(f"invalid DART action {action!r}")
    number = get_button_number(button_id)
    if not number:
        raise ValueError(f"unknown button_id {button_id!r}")
    return _write(alias_or_com, f"{_remote(remote_num)} {number} {action}\n")
