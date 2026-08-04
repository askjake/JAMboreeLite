"""One serial worker per physical DART port with synchronous write receipts.

A command is reported successful only after the worker has written and flushed it
to an open serial device.  This is stronger than merely placing bytes in a queue;
it still does not claim a receiver-side RF acknowledgement unless the board emits
one and a future protocol adapter explicitly validates it.
"""
from __future__ import annotations

import contextlib
import inspect
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Mapping, Optional

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


@dataclass
class _WriteRequest:
    data: bytes
    done: threading.Event = field(default_factory=threading.Event)
    ok: bool = False
    error: Optional[str] = None


class SerialPortWorker(threading.Thread):
    def __init__(
        self,
        com: str,
        baud: int = DEFAULT_BAUD,
        on_rx: Optional[Callable[[bytes, str], None]] = None,
        vid: Optional[int] = None,
        pid: Optional[int] = None,
    ) -> None:
        super().__init__(name=f"sp-{com}", daemon=True)
        self.com = com
        self.baud = int(baud)
        self._on_rx = on_rx
        self._vid, self._pid = vid, pid
        self._ser: Optional[serial.Serial] = None
        self._write_q: "queue.Queue[_WriteRequest]" = queue.Queue(maxsize=256)
        self._stop_event = threading.Event()  # do not shadow Thread._stop()
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
        self._fail_pending("serial worker stopped")

    def submit(
        self,
        data: bytes,
        *,
        queue_timeout_s: float = 2.0,
        completion_timeout_s: float = 4.0,
        require_ready: bool = True,
        wait: bool = True,
    ) -> bool:
        if require_ready and not self.is_ready:
            LOG.warning("[%-6s] rejected write: port not ready", self.com)
            return False
        request = _WriteRequest(bytes(data))
        try:
            self._write_q.put(request, timeout=queue_timeout_s)
        except queue.Full:
            LOG.warning("[%-6s] write queue full; dropping write", self.com)
            return False
        if not wait:
            return True
        if not request.done.wait(max(float(completion_timeout_s), 0.1)):
            LOG.warning("[%-6s] serial write receipt timed out", self.com)
            return False
        if not request.ok:
            LOG.warning("[%-6s] serial write failed: %s", self.com, request.error)
        return request.ok

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
                self._ser.reset_input_buffer()
                self._ser.reset_output_buffer()
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

    def _fail_pending(self, error: str) -> None:
        while True:
            try:
                request = self._write_q.get_nowait()
            except queue.Empty:
                return
            request.error = error
            request.ok = False
            request.done.set()
            self._write_q.task_done()

    def _soft_reset(self) -> None:
        if not self._ser:
            return
        try:
            self._ready.clear()
            self._ser.dtr = False
            time.sleep(0.2)
            self._ser.dtr = True
            time.sleep(2.0)
            with contextlib.suppress(Exception):
                self._ser.reset_input_buffer()
                self._ser.reset_output_buffer()
            self._last_activity = time.monotonic()
            self._ready.set()
        except Exception as exc:
            self.last_error = str(exc)
            LOG.error("[%-6s] DTR reset failed: %s", self.com, exc)
            self._close_serial()

    def _drain_writes(self) -> bool:
        """Write queued requests; return False if the port failed."""
        while True:
            try:
                request = self._write_q.get_nowait()
            except queue.Empty:
                return True
            try:
                if not self._ser or not self._ser.is_open:
                    raise SerialException("serial port closed before write")
                self._ser.write(request.data)
                self._ser.flush()
                self._last_activity = time.monotonic()
                request.ok = True
            except Exception as exc:
                request.error = str(exc)
                request.ok = False
                self.last_error = str(exc)
                LOG.warning("[%-6s] write failed: %s", self.com, exc)
                self._close_serial()
            finally:
                request.done.set()
                self._write_q.task_done()
            if not request.ok:
                self._fail_pending("serial connection failed before queued write")
                return False

    def run(self) -> None:
        backoff_idx = 0
        try:
            while not self._stop_event.is_set():
                if not self._ser or not self._ser.is_open:
                    if not self._open_serial():
                        delay = REOPEN_BACKOFFS[min(backoff_idx, len(REOPEN_BACKOFFS) - 1)]
                        backoff_idx += 1
                        self._stop_event.wait(delay)
                        continue
                    backoff_idx = 0

                if not self._drain_writes():
                    continue

                try:
                    line = self._ser.readline()
                    if line:
                        self._last_activity = time.monotonic()
                        if self._on_rx:
                            self._on_rx(line, self.com)
                except SerialException as exc:
                    self.last_error = str(exc)
                    LOG.warning("[%-6s] read failed: %s", self.com, exc)
                    self._close_serial()
                    continue

                if time.monotonic() - self._last_activity > STALL_RESET_S:
                    self._soft_reset()
        finally:
            self._close_serial()
            self._fail_pending("serial worker exited")


class SerialManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._port_workers: Dict[str, SerialPortWorker] = {}
        self._alias_to_port: Dict[str, str] = {}

    def add_port(
        self,
        alias: str,
        com: str,
        baud: int = DEFAULT_BAUD,
        on_rx: Optional[Callable[[bytes, str], None]] = None,
        vid: Optional[int] = None,
        pid: Optional[int] = None,
    ) -> None:
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

    def sync_aliases(self, aliases: Mapping[str, str], *, baud: int = DEFAULT_BAUD) -> None:
        """Make alias mappings exactly match the supplied non-empty COM map."""
        desired = {
            str(alias).strip(): str(com).strip()
            for alias, com in aliases.items()
            if str(alias).strip() and str(com).strip()
        }
        with self._lock:
            stale = set(self._alias_to_port) - set(desired)
            for alias in stale:
                self._alias_to_port.pop(alias, None)
        for alias, com in desired.items():
            self.add_port(alias, com, baud=baud)
        self._stop_unreferenced_workers()

    def _stop_unreferenced_workers(self) -> None:
        with self._lock:
            referenced = set(self._alias_to_port.values())
            stale = [
                (com, worker)
                for com, worker in self._port_workers.items()
                if com not in referenced
            ]
            for com, _worker in stale:
                self._port_workers.pop(com, None)
        for _com, worker in stale:
            worker.stop()
            worker.join(timeout=3.0)

    def remove_alias(self, alias: str) -> None:
        with self._lock:
            self._alias_to_port.pop(alias, None)
        self._stop_unreferenced_workers()

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

    def write(
        self,
        alias_or_com: str,
        data: bytes,
        *,
        require_ready: bool = True,
        wait: bool = True,
        completion_timeout_s: float = 4.0,
    ) -> bool:
        worker = self._resolve_worker(alias_or_com)
        if not worker:
            LOG.warning("no serial worker for %r", alias_or_com)
            return False
        return worker.submit(
            data,
            require_ready=require_ready,
            wait=wait,
            completion_timeout_s=completion_timeout_s,
        )

    def status(self, alias_or_com: str) -> dict:
        worker = self._resolve_worker(alias_or_com)
        return {
            "configured": worker is not None,
            "ready": bool(worker and worker.is_ready),
            "alive": bool(worker and worker.is_alive()),
            "port": self.port_for(alias_or_com)
            if alias_or_com in self._alias_to_port
            else alias_or_com,
            "last_error": worker.last_error if worker else None,
        }

    def stop_all(self, join_timeout: float = 3.0) -> None:
        with self._lock:
            workers = list(self._port_workers.values())
            self._port_workers.clear()
            self._alias_to_port.clear()
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.join(timeout=join_timeout)
