# --- jamboree/serial_bridge.py ---
"""115200‑baud helper with verbose debug logging."""
import serial, time, logging
from typing import Dict

_PORTS: Dict[str, serial.Serial] = {}
BAUDRATE = 115200
READ_TIMEOUT = 0.3             # seconds to wait for Arduino echo

def _open(port: str) -> serial.Serial:
    """Open (or reuse) a serial handle."""
    if port not in _PORTS or not _PORTS[port].is_open:
        _PORTS[port] = serial.Serial(
            port=port,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=READ_TIMEOUT,
        )
        logging.info("Opened serial %s", port)
    return _PORTS[port]


# --------------------------------------------------------------------- RF helper
from .commands import get_button_codes

def send_rf(port: str, remote_num: str, button_id: str, delay_ms: int) -> str:
    """
    Build the `${remote} KEY_CMD KEY_RELEASE delay` line expected by the
    Arduino “DART” sketch, write it, then try to read back *one* line so
    you can see the board’s echo/ACK in the log.

    Returns the exact line written (stripped).
    """
    delay_ms = max(int(delay_ms), 80)
    codes = get_button_codes(button_id)
    if not codes:
        raise ValueError(f"Unknown button_id '{button_id}'")

    line = f"{remote_num} {codes['KEY_CMD']} {codes['KEY_RELEASE']} {delay_ms}\n"
    ser = _open(port)

    # ---- write
    ser.write(line.encode())
    ser.flush()
    logging.debug("→ %s | %s", port, line.strip())

    # ---- optional read‑back (non‑blocking)
    echo = b""
    start = time.time()
    while time.time() - start < READ_TIMEOUT:
        chunk = ser.readline()
        if chunk:
            echo = chunk
            break
    if echo:
        logging.debug("← %s | %s", port, echo.decode(errors='replace').rstrip())

    # small pause so GUI “tap” commands don’t outrun the MCU
    time.sleep((delay_ms + 50) / 1000.0)
    return line.strip()
