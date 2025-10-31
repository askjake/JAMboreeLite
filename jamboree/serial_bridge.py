# --- jamboree/serial_bridge.py ---
"""Serial helpers routed through the global serial_mgr (no direct pyserial)."""
import logging, time
from typing import Optional
from .commands import get_button_codes, get_button_number

# IMPORTANT: serial_mgr is created in app.py before controller imports us.
from .app import serial_mgr  # type: ignore

def _enqueue(alias_or_com: str, line: str) -> bool:
    ok = serial_mgr.write(alias_or_com, line.encode())
    if not ok:
        logging.warning("serial write enqueue failed for %s (%r)", alias_or_com, line.strip())
    return ok

def send_rf(alias_or_com: str, remote_num: str, button_id: str, delay_ms: int) -> str:
    """
    Build: <remote> <KEY_CMD> <KEY_RELEASE> <delay_ms>
    and enqueue to the serial manager under the given alias (preferred) or COM.
    """
    delay_ms = max(int(delay_ms), 80)
    codes = get_button_codes(button_id)
    if not codes:
        raise ValueError(f"Unknown button_id '{button_id}'")
    line = f"{remote_num} {codes['KEY_CMD']} {codes['KEY_RELEASE']} {delay_ms}\n"
    _enqueue(alias_or_com, line)
    # Give the board a hair so UI taps don't outrun it
    time.sleep((delay_ms + 50) / 1000.0)
    logging.debug("→ [%s] %s", alias_or_com, line.strip())
    return line.strip()

def send_quick_dart(alias_or_com: str, remote_num: str, button_id: str, action: str) -> str:
    """
    Quick-DART: <remoteNum> <buttonNumber> <action>  (action: 'down'|'up')
    """
    num = get_button_number(button_id)
    if not num:
        raise ValueError(f"Unknown button_id '{button_id}'")
    line = f"{remote_num} {num} {action}\n"
    _enqueue(alias_or_com, line)
    logging.debug("→ [%s] %s", alias_or_com, line.strip())
    return line.strip()
