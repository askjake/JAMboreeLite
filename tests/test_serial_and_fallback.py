import threading
import types
import pytest


def test_thread_stop_name_is_not_shadowed():
    from jamboree.serial_manager import SerialPortWorker
    worker = SerialPortWorker("COM1")
    assert not isinstance(getattr(worker, "_stop", None), threading.Event)
    assert hasattr(worker, "_stop_event")


def test_serial_bridge_fails_when_port_not_ready(monkeypatch):
    from jamboree import serial_bridge
    monkeypatch.setattr(serial_bridge.serial_mgr, "write", lambda *a, **k: False)
    with pytest.raises(RuntimeError, match="not open/ready"):
        serial_bridge.send_rf("A", "1", "guide", 80)


def test_sgs_failure_falls_back_to_configured_rf(monkeypatch):
    import jamboree.controller as controller
    monkeypatch.setattr(controller.store, "get", lambda alias: {"protocol": "SGS", "ip": "10.0.0.1", "stb": "R1234567890-12", "remote": "7"})
    monkeypatch.setattr(controller, "send_sgs", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("connection timed out")))
    calls = []
    monkeypatch.setattr(controller, "send_rf_strict", lambda alias, remote, button, delay: calls.append((alias, remote, button, delay)) or "7 83 03 80")
    monkeypatch.setattr(
        controller,
        "classify_sgs_failure",
        lambda exc: types.SimpleNamespace(
            recoverable=False,
            auth=False,
            wrong_device=False,
            transport=True,
            reason="transport",
            kind="transport",
        ),
    )
    result = controller.Controller().handle_auto_remote("99", "A", "guide", 80)
    assert result["via"] == "rf_fallback"
    assert calls == [("A", "7", "guide", 80)]
    assert "timed out" in result["sgs_error"]


def test_unknown_protocol_fails_closed(monkeypatch):
    import jamboree.controller as controller
    monkeypatch.setattr(controller.store, "get", lambda alias: {"protocol": "IP", "remote": "1"})
    with pytest.raises(ValueError, match="unsupported protocol"):
        controller.Controller().handle_auto_remote("1", "A", "guide", 80)
