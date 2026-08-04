from __future__ import annotations

from copy import deepcopy

from jamboree import sgs_autopair
from jamboree.core.credentials import CredentialManager


class FakeStore:
    def __init__(self, entries):
        self.entries = deepcopy(entries)

    def get(self, alias):
        return self.entries.get(alias)

    def all(self):
        return self.entries

    def update_stb(self, alias, fields, **_kwargs):
        self.entries.setdefault(alias, {}).update(fields)
        return {"stbs": self.entries}

    def reload(self):
        return {"stbs": self.entries}

    def document(self):
        return {"stbs": deepcopy(self.entries)}


def test_joey_pairing_resolves_to_host_hopper(monkeypatch):
    store = FakeStore(
        {
            "H": {"ip": "10.0.0.1", "stb": "R1234567890-12", "role": "hopper"},
            "J": {"ip": "10.0.0.2", "stb": "R1987654321-34", "role": "joey", "host": "H"},
        }
    )
    monkeypatch.setattr(sgs_autopair, "_store", store)
    alias, entry = sgs_autopair._resolve_pair_target("J")
    assert alias == "H"
    assert entry["stb"] == "R1234567890-12"


def test_pair_complete_stores_keyring_and_not_plaintext(monkeypatch):
    store = FakeStore(
        {"H": {"ip": "10.0.0.1", "stb": "R1234567890-12", "role": "hopper"}}
    )
    monkeypatch.setattr(sgs_autopair, "_store", store)
    monkeypatch.delenv("JAMBOREE_ALLOW_PLAINTEXT_CREDENTIALS", raising=False)
    monkeypatch.setattr(
        sgs_autopair,
        "_post_noauth",
        lambda *_a, **_k: {"result": 1, "name": "issued-user", "passwd": "issued-secret"},
    )
    result = sgs_autopair.pair_complete("H", "123456")
    assert result["ok"]
    assert "name" not in result["response"]
    assert "passwd" not in result["response"]
    assert "lname" not in store.get("H")
    assert "passwd" not in store.get("H")
    assert store.get("H")["paired"] is True
    username, password = CredentialManager.get_credentials("H", store.document())
    assert (username, password) == ("issued-user", "issued-secret")


def test_credentials_status_never_returns_secret(monkeypatch):
    store = FakeStore(
        {"H2": {"ip": "10.0.0.1", "stb": "R1234567890-12", "role": "hopper"}}
    )
    monkeypatch.setattr(sgs_autopair, "_store", store)
    assert CredentialManager.store_credentials("H2", "user", "secret")
    status = sgs_autopair.credentials_status("H2")
    assert status["paired"] is True
    assert "secret" not in repr(status)
    assert all(value != "user" for value in status.values())


def test_wait_for_pin_requires_cross_frame_agreement(monkeypatch):
    monkeypatch.setattr(sgs_autopair, "_get_frame", lambda: object())
    calls = []

    def scored(**_kwargs):
        calls.append(1)
        return [{"pin": "123456", "score": 5.0, "hits": 2, "sources": ["mock"]}]

    monkeypatch.setattr(sgs_autopair, "score_pin_candidates", scored)
    monkeypatch.setattr(sgs_autopair.time, "sleep", lambda _s: None)
    assert sgs_autopair.wait_for_pin(timeout_s=2, stable_reads=2) == "123456"
    assert len(calls) >= 2


def test_auto_pair_explicit_pin_runs_secure_persistence(monkeypatch):
    store = FakeStore(
        {"H3": {"ip": "10.0.0.1", "stb": "R1234567890-12", "role": "hopper"}}
    )
    monkeypatch.setattr(sgs_autopair, "_store", store)
    monkeypatch.setattr(
        sgs_autopair,
        "credentials_status",
        lambda _a: {"paired": False, "stale_rid": False},
    )
    monkeypatch.setattr(sgs_autopair, "pair_start", lambda _a: {"ok": True})
    monkeypatch.setattr(
        sgs_autopair,
        "pair_complete",
        lambda _a, _p: {"ok": True, "credential_stored": True},
    )
    monkeypatch.setattr(
        sgs_autopair,
        "verify_credentials_persisted",
        lambda _a: {"secure_store": True, "metadata_on_disk": True},
    )
    result = sgs_autopair.auto_pair("H3", pin="123456", verify=False)
    assert result["ok"]
    assert result["steps"]["pin"]["value"] == "******"
