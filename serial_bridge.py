# --- jamboree/serial_bridge.py ---
"""Opens a 115200 8‑N‑1 port on‑demand and caches handle per COM/tty."""
import serial, time, logging
from typing import Dict

_PORTS: Dict[str, serial.Serial] = {}
BAUDRATE = 115200

def _open(port: str) -> serial.Serial:
    if port not in _PORTS or not _PORTS[port].is_open:
        _PORTS[port] = serial.Serial(port=port,
                                     baudrate=BAUDRATE,
                                     bytesize=serial.EIGHTBITS,
                                     parity=serial.PARITY_NONE,
                                     stopbits=serial.STOPBITS_ONE,
                                     timeout=1)
        logging.info("Opened serial %s", port)
    return _PORTS[port]

# -----------------------------------------------------------------------
# RF helper
# -----------------------------------------------------------------------
from commands import get_button_codes

def send_rf(port: str, remote_num: str, button_id: str, delay_ms: int):
    """Write KEY_CMD/RELEASE sequence to Arduino Nano Every running the DART
    sketch you supplied.
    """
    delay_ms = max(int(delay_ms), 80)
    codes = get_button_codes(button_id)
    if not codes:
        raise ValueError(f"Unknown button_id {button_id}")
    line = f"{remote_num} {codes['KEY_CMD']} {codes['KEY_RELEASE']} {delay_ms}\n"
    ser = _open(port)
    ser.write(line.encode())
    ser.flush()
    time.sleep((delay_ms + 50) / 1000.0)
    return line.strip()


