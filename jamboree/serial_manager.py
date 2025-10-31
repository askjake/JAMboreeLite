# serial_manager.py
import threading, time, logging, queue, contextlib, inspect, re
from typing import Optional, Callable, Dict
import serial
from serial import SerialException
from serial.tools import list_ports

LOG = logging.getLogger("serial-manager")

DEFAULT_BAUD = 115200
KEEPALIVE_PERIOD_S = 5.0
STALL_RESET_S     = 30.0
REOPEN_BACKOFFS   = [1, 2, 5, 10, 20, 30, 60]
READ_TIMEOUT_S    = 1.0
WRITE_TIMEOUT_S   = 1.0

def _supports_exclusive_kwarg() -> bool:
    try:
        return "exclusive" in inspect.signature(serial.Serial.__init__).parameters
    except Exception:
        return False

_EXCLUSIVE_OK = _supports_exclusive_kwarg()
_COM_RE = re.compile(r"^(COM\d+|/dev/tty[^ ]+|ttyS\d+|ttyUSB\d+)$", re.I)

class SerialPortWorker(threading.Thread):
    """
    One OS handle to one physical COM port.
    This worker is keyed by COM (not alias). Multiple aliases can write to it.
    """
    def __init__(self, com: str, baud: int = DEFAULT_BAUD,
                 expect: bytes = b"PONG", ping: bytes = b"PING\n",
                 on_rx: Optional[Callable[[bytes, str], None]] = None,
                 vid: Optional[int] = None, pid: Optional[int] = None):
        super().__init__(name=f"sp-{com}", daemon=True)
        self.com   = com
        self.baud  = baud
        self.expect = expect
        self.ping   = ping
        self._on_rx = on_rx
        self._vid, self._pid = vid, pid

        self._ser: Optional[serial.Serial] = None
        self._write_q: "queue.Queue[bytes]" = queue.Queue(maxsize=256)
        self._stop = threading.Event()
        self._last_ok = time.monotonic()
        self._last_ping = 0.0

    def stop(self):
        self._stop.set()
        with contextlib.suppress(Exception):
            if self._ser and self._ser.is_open:
                self._ser.close()

    def write(self, data: bytes, timeout_s: float = 2.0) -> bool:
        try:
            self._write_q.put(data, timeout=timeout_s)
            return True
        except queue.Full:
            LOG.warning("[%-6s] write queue full; dropping write", self.com)
            return False

    def _resolve_port(self) -> str:
        if self._vid is None or self._pid is None:
            return self.com
        for p in list_ports.comports():
            if p.vid == self._vid and p.pid == self._pid:
                return p.device
        return self.com

    def _open_serial(self) -> bool:
        port = self._resolve_port()
        try:
            kwargs = dict(
                port=port,
                baudrate=self.baud,
                timeout=READ_TIMEOUT_S,
                write_timeout=WRITE_TIMEOUT_S,
                rtscts=False, dsrdtr=False,
                inter_byte_timeout=0.1,
            )
            if _EXCLUSIVE_OK:
                kwargs["exclusive"] = True  # POSIX only; ignored on Windows
            self._ser = serial.Serial(**kwargs)
            time.sleep(2.0)  # Arduino bootloader settle
            with contextlib.suppress(Exception):
                self._ser.reset_input_buffer(); self._ser.reset_output_buffer()
            LOG.info("[%-6s] opened %s @ %d", self.com, self._ser.port, self.baud)
            self._last_ok = time.monotonic()
            self._last_ping = 0.0
            return True
        except Exception as e:
            LOG.warning("[%-6s] open %s failed: %s", self.com, port, e)
            self._ser = None
            return False

    def _close_serial(self):
        if self._ser:
            with contextlib.suppress(Exception):
                port = self._ser.port
                self._ser.close()
                LOG.info("[%-6s] closed %s", self.com, port)
        self._ser = None

    def _soft_reset(self):
        if not self._ser: return
        LOG.warning("[%-6s] soft reset (DTR toggle)", self.com)
        try:
            self._ser.dtr = False
            time.sleep(0.2)
            self._ser.dtr = True
            time.sleep(2.0)
            with contextlib.suppress(Exception):
                self._ser.reset_input_buffer(); self._ser.reset_output_buffer()
            self._last_ok = time.monotonic()
            self._last_ping = 0.0
        except Exception as e:
            LOG.error("[%-6s] DTR toggle failed: %s", self.com, e)
            self._close_serial()

    def run(self):
        backoff_idx = 0
        while not self._stop.is_set():
            if not self._ser or not self._ser.is_open:
                if not self._open_serial():
                    delay = REOPEN_BACKOFFS[min(backoff_idx, len(REOPEN_BACKOFFS)-1)]
                    backoff_idx += 1
                    self._stop.wait(delay)
                    continue
                backoff_idx = 0

            now = time.monotonic()

            # Keepalive
            if self.ping and (now - self._last_ping) >= KEEPALIVE_PERIOD_S:
                try:
                    self._ser.write(self.ping)
                except Exception as e:
                    LOG.warning("[%-6s] ping write failed: %s", self.com, e)
                    self._close_serial()
                    continue
                self._last_ping = now

            # Writes
            try:
                while True:
                    payload = self._write_q.get_nowait()
                    try:
                        self._ser.write(payload)
                    except Exception as e:
                        LOG.warning("[%-6s] write failed: %s", self.com, e)
                        self._close_serial()
                        break
            except queue.Empty:
                pass

            # Read
            try:
                line = self._ser.readline()
                if line:
                    self._last_ok = now
                    if self._on_rx:
                        self._on_rx(line, self.com)
            except SerialException as e:
                LOG.warning("[%-6s] read failed: %s", self.com, e)
                self._close_serial()
                continue

            # Stall watchdog
            if (now - self._last_ok) > STALL_RESET_S:
                self._soft_reset()
                # Next loop will reopen if needed

class SerialManager:
    """
    ONE worker per COM. Many aliases can map to a single COM.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._port_workers: Dict[str, SerialPortWorker] = {}
        self._alias_to_port: Dict[str, str] = {}

    def add_port(self, alias: str, com: str, baud:int=DEFAULT_BAUD,
                 on_rx: Optional[Callable[[bytes,str],None]] = None,
                 vid: Optional[int]=None, pid: Optional[int]=None):
        with self._lock:
            self._alias_to_port[alias] = com  # map/refresh alias→COM
            if com not in self._port_workers:
                w = SerialPortWorker(com=com, baud=baud, on_rx=on_rx, vid=vid, pid=pid)
                self._port_workers[com] = w
                w.start()
                LOG.debug("alias '%s' mapped to NEW worker for %s", alias, com)
            else:
                LOG.debug("alias '%s' mapped to EXISTING worker for %s", alias, com)

    def _resolve_worker(self, alias_or_com: str) -> Optional[SerialPortWorker]:
        with self._lock:
            com = self._alias_to_port.get(alias_or_com)
            if not com and _COM_RE.match(alias_or_com or ""):
                com = alias_or_com
            return self._port_workers.get(com) if com else None

    def write(self, alias_or_com: str, data: bytes) -> bool:
        w = self._resolve_worker(alias_or_com)
        if not w:
            LOG.warning("No serial worker for '%s'", alias_or_com)
            return False
        return w.write(data)

    def stop_all(self):
        with self._lock:
            for w in self._port_workers.values():
                w.stop()
            self._port_workers.clear()
            self._alias_to_port.clear()
