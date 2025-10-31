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
    def __init__(self, name: str, com: str, baud: int = DEFAULT_BAUD,
                 expect: bytes = b"PONG", ping: bytes = b"PING\n",
                 on_rx: Optional[Callable[[bytes, str], None]] = None,
                 vid: Optional[int] = None, pid: Optional[int] = None):
        super().__init__(name=f"sp-{name}", daemon=True)
        self.alias = name
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
            LOG.warning("[%s] write queue full; dropping write", self.alias)
            return False

    def _resolve_port(self) -> str:
        # If VID/PID given, prefer the current device for re-enumerations
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
                rtscts=False,
                dsrdtr=False,
                inter_byte_timeout=0.1,
            )
            if _EXCLUSIVE_OK:
                kwargs["exclusive"] = True
            self._ser = serial.Serial(**kwargs)
            time.sleep(2.0)  # Arduino bootloader settle
            with contextlib.suppress(Exception):
                self._ser.reset_input_buffer(); self._ser.reset_output_buffer()
            LOG.info("[%s] opened %s @ %d", self.alias, self._ser.port, self.baud)
            self._last_ok = time.monotonic()
            self._last_ping = 0.0
            return True
        except Exception as e:
            LOG.warning("[%s] open %s failed: %s", self.alias, port, e)
            self._ser = None
            return False

    def _close_serial(self):
        if self._ser:
            with contextlib.suppress(Exception):
                port = self._ser.port
                self._ser.close()
                LOG.info("[%s] closed %s", self.alias, port)
        self._ser = None

    def _soft_reset(self):
        if not self._ser: return
        LOG.warning("[%s] soft reset (DTR toggle)", self.alias)
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
            LOG.error("[%s] DTR toggle failed: %s", self.alias, e)
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
                    LOG.warning("[%s] ping write failed: %s", self.alias, e)
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
                        LOG.warning("[%s] write failed: %s", self.alias, e)
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
                        self._on_rx(line, self.alias)
            except SerialException as e:
                LOG.warning("[%s] read failed: %s", self.alias, e)
                self._close_serial()
                continue

            # Stall watchdog
            if (now - self._last_ok) > STALL_RESET_S:
                self._soft_reset()
                # If still closed, next loop will reopen

class SerialManager:
    """
    One worker per **COM port**, many aliases may map to the same worker.
    Writes accept either an alias or a COM path; we resolve to the worker.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._port_workers: Dict[str, SerialPortWorker] = {}
        self._alias_to_port: Dict[str, str] = {}

    def add_port(self, alias: str, com: str, baud:int=DEFAULT_BAUD,
                 on_rx: Optional[Callable[[bytes,str],None]] = None,
                 vid: Optional[int]=None, pid: Optional[int]=None):
        with self._lock:
            # Record/refresh mapping
            self._alias_to_port[alias] = com
            # Start exactly one worker per COM
            if com not in self._port_workers:
                w = SerialPortWorker(name=com, com=com, baud=baud, on_rx=on_rx, vid=vid, pid=pid)
                self._port_workers[com] = w
                w.start()

    def _resolve_worker(self, alias_or_com: str) -> Optional[SerialPortWorker]:
        with self._lock:
            com = self._alias_to_port.get(alias_or_com)
            if not com:
                # maybe user passed the COM directly
                com = alias_or_com if _COM_RE.match(alias_or_com or "") else None
            if not com:
                return None
            return self._port_workers.get(com)

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
