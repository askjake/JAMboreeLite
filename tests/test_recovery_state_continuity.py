from __future__ import annotations

import json
from copy import deepcopy

import pytest
import requests

from jamboree import base_io
from jamboree import controller as controller_module
from jamboree import ip_recovery, sgs_bridge
from jamboree.stb_store import STBStore


def _write_base(path, ip: str) -> None:
    path.write_text(
        json.dumps(
            {
                "stbs": {
                    "A": {
                        "ip": ip,
                        "stb": "R1234567890-12",
                        "protocol": "SGS",
                        "remote": "1",
                        "role": "hopper",
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_store_observes_external_base_update_without_restart(tmp_path):
    path = tmp_path / "base.txt"
    _write_base(path, "10.0.0.1")
    store = STBStore(path)
    assert store.get("A")["ip"] == "10.0.0.1"

    # Simulate a separate recovery/helper process updating the shared base file.
    base_io.update_stb_fields(path, "A", {"ip": "10.0.0.44"})

    assert store.get("A")["ip"] == "10.0.0.44"


class FakeStore:
    def __init__(self, entries, *, refresh_ip: str | None = None):
        self.entries = deepcopy(entries)
        self.refresh_ip = refresh_ip
        self.refresh_calls = 0

    def get(self, alias):
        return self.entries.get(alias)

    def all(self):
        return self.entries

    def document(self):
        return {"stbs": deepcopy(self.entries)}

    def refresh_if_changed(self, *, force: bool = False):
        self.refresh_calls += 1
        if self.refresh_ip is None:
            return False
        current = self.entries["A"]["ip"]
        if current == self.refresh_ip:
            return False
        self.entries["A"]["ip"] = self.refresh_ip
        return True


def _hopper_entries():
    return {
        "A": {
            "ip": "10.0.0.1",
            "stb": "R1234567890-12",
            "protocol": "SGS",
            "remote": "1",
            "role": "hopper",
        }
    }


def test_failed_sgs_reloads_external_ip_and_retries_before_recovery(monkeypatch):
    store = FakeStore(_hopper_entries(), refresh_ip="10.0.0.44")
    monkeypatch.setattr(controller_module, "store", store)
    monkeypatch.setattr(ip_recovery, "note_sgs_failure", lambda *_a, **_k: None)
    monkeypatch.setattr(ip_recovery, "note_sgs_success", lambda *_a, **_k: None)

    calls: list[str] = []

    def send(_name, ip, *_args, **_kwargs):
        calls.append(ip)
        if ip == "10.0.0.1":
            raise RuntimeError("connection refused")
        return '{"result": 1}'

    monkeypatch.setattr(controller_module, "send_sgs", send)
    started: list[str] = []
    monkeypatch.setattr(
        ip_recovery,
        "recover_alias_async",
        lambda alias, **_kwargs: started.append(alias) or True,
    )

    def forbidden_sync_recovery(_alias):
        raise AssertionError("normal /auto failure path must not run a full synchronous scan")

    ctl = controller_module.Controller(recoverer=forbidden_sync_recovery)
    result = ctl.handle_auto_remote("1", "A", "guide", 120, allow_rf_fallback=False)

    assert result["via"] == "sgs_reloaded"
    assert calls == ["10.0.0.1", "10.0.0.44"]
    assert store.refresh_calls >= 1
    assert started == []


def test_transport_failure_starts_background_recovery_not_sync_scan(monkeypatch):
    store = FakeStore(_hopper_entries())
    monkeypatch.setattr(controller_module, "store", store)
    monkeypatch.setattr(
        controller_module,
        "send_sgs",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("connection refused")),
    )
    monkeypatch.setattr(ip_recovery, "note_sgs_failure", lambda *_a, **_k: None)

    started: list[str] = []
    monkeypatch.setattr(
        ip_recovery,
        "recover_alias_async",
        lambda alias, **_kwargs: started.append(alias) or True,
    )

    def forbidden_sync_recovery(_alias):
        raise AssertionError("normal /auto failure path must not run a full synchronous scan")

    ctl = controller_module.Controller(recoverer=forbidden_sync_recovery)
    with pytest.raises(RuntimeError, match="connection refused"):
        ctl.handle_auto_remote("1", "A", "guide", 120, allow_rf_fallback=False)

    assert started == ["A"]


def test_joey_transport_failure_recovers_host_hopper(monkeypatch):
    store = FakeStore(
        {
            "H": {
                "ip": "10.0.0.1",
                "stb": "R1234567890-12",
                "protocol": "SGS",
                "remote": "1",
                "role": "hopper",
            },
            "J": {
                "ip": "10.0.0.9",
                "stb": "R1111111111-11",
                "protocol": "SGS",
                "remote": "2",
                "role": "joey",
                "host": "H",
            },
        }
    )
    monkeypatch.setattr(controller_module, "store", store)
    monkeypatch.setattr(
        controller_module,
        "send_sgs",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("connection refused")),
    )
    monkeypatch.setattr(ip_recovery, "note_sgs_failure", lambda *_a, **_k: None)

    started: list[str] = []
    monkeypatch.setattr(
        ip_recovery,
        "recover_alias_async",
        lambda alias, **_kwargs: started.append(alias) or True,
    )

    ctl = controller_module.Controller(
        recoverer=lambda _alias: (_ for _ in ()).throw(
            AssertionError("synchronous recovery must not run")
        )
    )
    with pytest.raises(RuntimeError, match="connection refused"):
        ctl.handle_auto_remote("2", "J", "guide", 120, allow_rf_fallback=False)

    assert started == ["H"]


def test_sgs_dead_endpoint_budget_stays_below_automation_timeout(monkeypatch):
    observed_timeouts: list[float] = []

    def fail(_url, **kwargs):
        observed_timeouts.append(float(kwargs["timeout"]))
        raise requests.Timeout("timed out")

    monkeypatch.setattr(sgs_bridge.requests, "post", fail)

    with pytest.raises(RuntimeError, match="SGS request failed"):
        sgs_bridge._post(
            "192.0.2.10",
            {"command": "remote_key"},
            creds=("user", "password"),
        )

    assert len(observed_timeouts) == 3
    assert max(observed_timeouts) <= 2.5
    assert sum(observed_timeouts) < 10.0
