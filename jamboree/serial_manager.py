"""One serial worker per physical DART port, with explicit readiness semantics."""
from __future__ import annotations

import contextlib
import inspect
import logging
import queue
import re
import threading
import time
from typing import Callable, Dict, Optional

import serial
from serial import SerialException
from serial.tools import list_ports

LOG = logging.getLogger("serial-manager")
DEFAULT_BAUD = 115200
STALL_RESET_S = 30.0
REOPEN_BACKOFFS = (1, 2, 5, 10, 20, 30, 60)
READ_TIMEOUT_S = 0.25
WRITE_TIMEOUT_S = 1.0
_COM_RE = re.compile(r"^(COM\d+|/dev/tty[^ ]+|ttyS\d+|ttyUSB\d+)$", re.I)


def _supports_exclusive_kwarg() -> bool:
    try:
        return "exclusive" in inspect.signature(serial.Serial.__init__).parameters
    except Exception:
        return False


_EXCLUSIVE_OK = _supports_exclusive_kwarg()


class SerialPortWorker(threading.Thread):
    def __init__(self, com: str, baud: int = DEFAULT_BAUD, on_rx: Optional[Callable[[bytes, str], None]] = None, vid: Optional[int] = None, pid: Optional[int] = None) -> None:
        super().__init__(name=f"sp-{com}", daemon=True)
        self.com = com
        self.baud = int(baud)
        self._on_rx = on_rx
        self._vid, self._pid = vid, pid
        self._ser: Optional[serial.Serial] = None
        self._write_q: "queue.Queue[bytes]" = queue.Queue(maxsize=256)
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._last_activity = time.monotonic()
        self.last_error: Optional[str] = None

    @property
    def is_ready(self) -> bool:
        return bool(self._ready.is_set() and self._ser and self._ser.is_open)

    def stop(self) -> None:
        self._stop_event.set()
        self._ready.clear()
        with contextlib.suppress(Exception):
            if self._ser and self._ser.is_open:
                self._ser.close()

    def write(self, data: bytes, timeout_s: float = 2.0, *, require_ready: bool = True) -> bool:
        if require_ready and not self.is_ready:
            LOG.warning("[%-6s] rejected write: port not ready", self.com)
            return False
        try:
            self._write_q.put(bytes(data), timeout=timeout_s)
            return True
        except queue.Full:
            LOG.warning("[%-6s] write queue full; dropping write", self.com)
            return False

    def _resolve_port(self) -> str:
        if self._vid is None or self._pid is None:
            return self.com
        for port in list_ports.comports():
            if port.vid == self._vid and port.pid == self._pid:
                return port.device
        return self.com

    def _open_serial(self) -> bool:
        port = self._resolve_port()
        try:
            kwargs = dict(port=port, baudrate=self.baud, timeout=READ_TIMEOUT_S, write_timeout=WRITE_TIMEOUT_S, rtscts=False, dsrdtr=False, inter_byte_timeout=0.1)
            if _EXCLUSIVE_OK:
                kwargs["exclusive"] = True
            self._ser = serial.Serial(**kwargs)
            time.sleep(2.0)
            with contextlib.suppress(Exception):
                self._ser.reset_input_buffer(); self._ser.reset_output_buffer()
            self.last_error = None
            self._last_activity = time.monotonic()
            self._ready.set()
            LOG.info("[%-6s] opened %s @ %d", self.com, self._ser.port, self.baud)
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self._ready.clear()
            self._ser = None
            LOG.warning("[%-6s] open %s failed: %s", self.com, port, exc)
            return False

    def _close_serial(self) -> None:
        self._ready.clear()
        if self._ser:
            with contextlib.suppress(Exception):
                self._ser.close()
        self._ser = None

    def _soft_reset(self) -> None:
        if not self._ser:
            return
        try:
            self._ready.clear()
            self._ser.dtr = False; time.sleep(0.2); self._ser.dtr = True; time.sleep(2.0)
            with contextlib.suppress(Exception):
                self._ser.reset_input_buffer(); self._ser.reset_output_buffer()
            self._last_activity = time.monotonic(); self._ready.set()
        except Exception as exc:
            self.last_error = str(exc)
            LOG.error("[%-6s] DTR reset failed: %s", self.com, exc)
            self._close_serial()

    def run(self) -> None:
        backoff_idx = 0
        while not self._stop_event.is_set():
            if not self._ser or not self._ser.is_open:
                if not self._open_serial():
                    delay = REOPEN_BACKOFFS[min(backoff_idx, len(REOPEN_BACKOFFS) - 1)]
                    backoff_idx += 1
                    self._stop_event.wait(delay)
                    continue
                backoff_idx = 0
            try:
                while True:
                    payload = self._write_q.get_nowait()
                    self._ser.write(payload); self._ser.flush(); self._last_activity = time.monotonic()
            except queue.Empty:
                pass
            except Exception as exc:
                self.last_error = str(exc); LOG.warning("[%-6s] write failed: %s", self.com, exc); self._close_serial(); continue
            try:
                line = self._ser.readline()
                if line:
                    self._last_activity = time.monotonic()
                    if self._on_rx:
                        self._on_rx(line, self.com)
            except SerialException as exc:
                self.last_error = str(exc); LOG.warning("[%-6s] read failed: %s", self.com, exc); self._close_serial(); continue
            if time.monotonic() - self._last_activity > STALL_RESET_S:
                self._soft_reset()
        self._close_serial()


class SerialManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._port_workers: Dict[str, SerialPortWorker] = {}
        self._alias_to_port: Dict[str, str] = {}

    def add_port(self, alias: str, com: str, baud: int = DEFAULT_BAUD, on_rx: Optional[Callable[[bytes, str], None]] = None, vid: Optional[int] = None, pid: Optional[int] = None) -> None:
        alias, com = str(alias).strip(), str(com).strip()
        if not alias or not com:
            raise ValueError("alias and com are required")
        with self._lock:
            self._alias_to_port[alias] = com
            worker = self._port_workers.get(com)
            if worker is None or not worker.is_alive():
                worker = SerialPortWorker(com, baud, on_rx, vid, pid)
                self._port_workers[com] = worker
                worker.start()

    def remove_alias(self, alias: str) -> None:
        with self._lock:
            self._alias_to_port.pop(alias, None)

    def _resolve_worker(self, alias_or_com: str) -> Optional[SerialPortWorker]:
        with self._lock:
            com = self._alias_to_port.get(alias_or_com)
            if not com and _COM_RE.match(alias_or_com or ""):
                com = alias_or_com
            return self._port_workers.get(com) if com else None

    def port_for(self, alias: str) -> Optional[str]:
        with self._lock:
            return self._alias_to_port.get(alias)

    def has_port(self, alias_or_com: str, *, require_ready: bool = False) -> bool:
        worker = self._resolve_worker(alias_or_com)
        return bool(worker and (worker.is_ready if require_ready else worker.is_alive()))

    def write(self, alias_or_com: str, data: bytes, *, require_ready: bool = True) -> bool:
        worker = self._resolve_worker(alias_or_com)
        if not worker:
            LOG.warning("No serial worker for %r", alias_or_com)
            return False
        return worker.write(data, require_ready=require_ready)

    def stop_all(self, join_timeout: float = 3.0) -> None:
        with self._lock:
            workers = list(self._port_workers.values())
            self._port_workers.clear(); self._alias_to_port.clear()
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.join(timeout=join_timeout)
