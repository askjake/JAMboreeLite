# jamboree/serial_bridge.py
"""Serial helpers routed through the global serial_mgr (no direct pyserial)."""
import logging, time
from .commands import get_button_codes, get_button_number
from .serial_hub import serial_mgr  # <- import from neutral hub, not app

def _enqueue(alias_or_com: str, line: str) -> bool:
    ok = serial_mgr.write(alias_or_com, line.encode())
    if not ok:
        logging.warning("serial write enqueue failed for %s (%r)", alias_or_com, line.strip())
    return ok

def send_rf(alias_or_com: str, remote_num: str, button_id: str, delay_ms: int) -> str:
    delay_ms = max(int(delay_ms), 80)
    codes = get_button_codes(button_id)
    if not codes:
        raise ValueError(f"Unknown button_id '{button_id}'")
    line = f"{remote_num} {codes['KEY_CMD']} {codes['KEY_RELEASE']} {delay_ms}\n"
    _enqueue(alias_or_com, line)
    time.sleep((delay_ms + 50) / 1000.0)
    logging.debug("→ [%s] %s", alias_or_com, line.strip())
    return line.strip()

def send_quick_dart(alias_or_com: str, remote_num: str, button_id: str, action: str) -> str:
    num = get_button_number(button_id)
    if not num:
        raise ValueError(f"Unknown button_id '{button_id}'")
    line = f"{remote_num} {num} {action}\n"
    _enqueue(alias_or_com, line)
    logging.debug("→ [%s] %s", alias_or_com, line.strip())
    return line.strip()
