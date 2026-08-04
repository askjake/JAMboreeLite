from __future__ import annotations

import threading
import time

from jamboree import serial_manager


class FakeSerial:
    def __init__(self, fail=False):
        self.is_open = True
        self.port = "COM1"
        self.fail = fail
        self.writes = []

    def write(self, data):
        if self.fail:
            raise OSError("wire failed")
        self.writes.append(bytes(data))

    def flush(self):
        if self.fail:
            raise OSError("flush failed")

    def close(self):
        self.is_open = False


def test_worker_does_not_shadow_thread_stop():
    worker = serial_manager.SerialPortWorker("COM1")
    assert not isinstance(getattr(worker, "_stop", None), threading.Event)
    assert isinstance(worker._stop_event, threading.Event)


def test_submit_waits_for_actual_serial_write():
    worker = serial_manager.SerialPortWorker("COM1")
    worker._ser = FakeSerial()
    worker._ready.set()
    result = {}

    def submitter():
        result["ok"] = worker.submit(b"1 4 down\n", completion_timeout_s=1)

    thread = threading.Thread(target=submitter)
    thread.start()
    for _ in range(100):
        if not worker._write_q.empty():
            break
        time.sleep(0.001)
    assert worker._drain_writes() is True
    thread.join(1)
    assert result["ok"] is True
    assert worker._ser.writes == [b"1 4 down\n"]


def test_submit_reports_write_failure():
    worker = serial_manager.SerialPortWorker("COM1")
    worker._ser = FakeSerial(fail=True)
    worker._ready.set()
    result = {}

    def submitter():
        result["ok"] = worker.submit(b"bad\n", completion_timeout_s=1)

    thread = threading.Thread(target=submitter)
    thread.start()
    for _ in range(100):
        if not worker._write_q.empty():
            break
        time.sleep(0.001)
    assert worker._drain_writes() is False
    thread.join(1)
    assert result["ok"] is False
    assert worker.last_error == "wire failed"
