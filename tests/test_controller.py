from __future__ import annotations

from copy import deepcopy

import pytest

from jamboree import controller as controller_module
from jamboree import ip_recovery


class FakeStore:
    def __init__(self, entries):
        self.entries = deepcopy(entries)

    def get(self, alias):
        return self.entries.get(alias)

    def all(self):
        return self.entries

    def document(self):
        return {"stbs": deepcopy(self.entries)}


def setup_store(monkeypatch, protocol="SGS"):
    store = FakeStore(
        {
            "A": {
                "ip": "10.0.0.1",
                "stb": "R1234567890-12",
                "protocol": protocol,
                "remote": "1",
                "com_port": "COM1",
                "role": "hopper",
            }
        }
    )
    monkeypatch.setattr(controller_module, "store", store)
    return store


def test_healthy_sgs_never_touches_rf(monkeypatch):
    setup_store(monkeypatch)
    sent_rf = []
    monkeypatch.setattr(controller_module, "send_sgs", lambda *_a, **_k: '{"result":1}')
    monkeypatch.setattr(controller_module, "send_rf_strict", lambda *_a, **_k: sent_rf.append(1))
    monkeypatch.setattr(ip_recovery, "note_sgs_success", lambda _a: None)
    ctl = controller_module.Controller()
    result = ctl.handle_auto_remote("1", "A", "guide", 120)
    assert result["via"] == "sgs"
    assert sent_rf == []


def test_force_sgs_is_strict_and_does_not_recover_or_fallback(monkeypatch):
    setup_store(monkeypatch)
    recovered = []
    rf = []
    monkeypatch.setattr(controller_module, "send_sgs", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("connection refused")))
    monkeypatch.setattr(controller_module, "send_rf_strict", lambda *_a, **_k: rf.append(1))
    ctl = controller_module.Controller(recoverer=lambda alias: recovered.append(alias))
    with pytest.raises(RuntimeError, match="connection refused"):
        ctl.handle_auto_remote("1", "A", "guide", 120, force="sgs")
    assert recovered == []
    assert rf == []


def test_transport_failure_recovers_then_retries_sgs(monkeypatch):
    store = setup_store(monkeypatch)
    calls = []

    def send(*_args, **_kwargs):
        calls.append(store.get("A")["ip"])
        if len(calls) == 1:
            raise RuntimeError("connection refused")
        return '{"result":1}'

    monkeypatch.setattr(controller_module, "send_sgs", send)
    monkeypatch.setattr(ip_recovery, "note_sgs_failure", lambda *_a: None)
    monkeypatch.setattr(ip_recovery, "note_sgs_success", lambda *_a: None)

    def recover(alias):
        store.entries[alias]["ip"] = "10.0.0.44"
        return ip_recovery.RecoveryResult(
            True, alias, "10.0.0.1", "10.0.0.44", "sgs_identity", sgs_verified=True
        )

    ctl = controller_module.Controller(recoverer=recover)
    result = ctl.handle_auto_remote("1", "A", "guide", 120)
    assert result["via"] == "sgs_recovered"
    assert calls == ["10.0.0.1", "10.0.0.44"]


def test_auth_failure_at_real_receiver_autopairs_and_uses_rf(monkeypatch):
    setup_store(monkeypatch)
    monkeypatch.setattr(controller_module, "send_sgs", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("HTTP 403")))
    monkeypatch.setattr(controller_module, "send_rf_strict", lambda *_a, **_k: "1 83 03 120")
    monkeypatch.setattr(ip_recovery, "note_sgs_failure", lambda *_a: None)
    monkeypatch.setattr(
        ip_recovery,
        "verify_stored_ip_identity",
        lambda _a: {"is_stb": True, "rxids": ["123456789012"], "rxid_match": True},
    )
    paired = []
    monkeypatch.setattr(ip_recovery, "trigger_autopair", lambda a, r: paired.append(a) or True)
    ctl = controller_module.Controller()
    result = ctl.handle_auto_remote("1", "A", "guide", 120)
    assert result["via"] == "rf_fallback"
    assert "403" in result["sgs_error"]
    assert paired == ["A"]


def test_invalid_protocol_fails_closed(monkeypatch):
    setup_store(monkeypatch, protocol="IP")
    ctl = controller_module.Controller()
    with pytest.raises(ValueError, match="unsupported protocol"):
        ctl.handle_auto_remote("1", "A", "guide", 120)
