from __future__ import annotations

from copy import deepcopy

from jamboree import ip_recovery


class FakeStore:
    def __init__(self, stbs):
        self.data = {"stbs": deepcopy(stbs)}

    def get(self, alias):
        return self.data["stbs"].get(alias)

    def all(self):
        return self.data["stbs"]

    def update_stb(self, alias, fields, **_kwargs):
        self.data["stbs"].setdefault(alias, {}).update(fields)
        return self.data

    def reload(self):
        return self.data

    def document(self):
        return deepcopy(self.data)


def exact_identity(_ip, _rid):
    return {
        "is_stb": True,
        "rxids": ["123456789012"],
        "rxid_match": True,
        "reason": "rxid_match",
    }


def test_failure_classification_is_transport_aware():
    auth = ip_recovery.classify_sgs_failure(PermissionError("HTTP 403"))
    assert auth.auth and auth.needs_pairing and not auth.recoverable
    transport = ip_recovery.classify_sgs_failure(RuntimeError("connection refused"))
    assert transport.transport and transport.recoverable
    wrong = ip_recovery.classify_sgs_failure(RuntimeError("rxid mismatch"))
    assert wrong.wrong_device and wrong.threshold == 1
    application = ip_recovery.classify_sgs_failure(RuntimeError("result 20"))
    assert not application.dead


def test_identity_scan_rejects_ambiguous_exact_matches(monkeypatch):
    store = FakeStore({"A": {"ip": "10.0.0.1", "stb": "R1234567890-12"}})
    monkeypatch.setattr(ip_recovery, "_store", store)

    def probe(_ip, _rid):
        return {"is_stb": True, "rxids": ["123456789012"], "rxid_match": True}

    candidate, error = ip_recovery.find_by_identity(
        "A", candidates=["10.0.0.2", "10.0.0.3"], probe=probe
    )
    assert candidate is None
    assert "ambiguous" in error


def test_failed_post_write_verification_rolls_back_original_ip(monkeypatch):
    store = FakeStore({"A": {"ip": "10.0.0.1", "stb": "R1234567890-12"}})
    monkeypatch.setattr(ip_recovery, "_store", store)
    result = ip_recovery.recover_alias(
        "A",
        mac_finder=lambda *_a, **_k: "10.0.0.44",
        identity_finder=lambda *_a, **_k: (None, "unused"),
        navigator=lambda _alias: False,
        identity_probe=exact_identity,
        sgs_verifier=lambda _alias: (False, RuntimeError("connection refused")),
    )
    assert not result.ok
    assert "rolled back" in result.reason
    assert store.get("A")["ip"] == "10.0.0.1"


def test_auth_failure_at_verified_new_receiver_keeps_ip_and_autopairs(monkeypatch):
    store = FakeStore({"A": {"ip": "10.0.0.1", "stb": "R1234567890-12"}})
    monkeypatch.setattr(ip_recovery, "_store", store)
    triggered = []
    monkeypatch.setattr(
        ip_recovery,
        "trigger_autopair",
        lambda alias, reason: triggered.append((alias, reason)) or True,
    )
    result = ip_recovery.recover_alias(
        "A",
        mac_finder=lambda *_a, **_k: "10.0.0.55",
        identity_finder=lambda *_a, **_k: (None, "unused"),
        navigator=lambda _alias: False,
        identity_probe=exact_identity,
        sgs_verifier=lambda _alias: (False, PermissionError("HTTP 403")),
    )
    assert result.ok
    assert result.needs_pairing
    assert result.autopair_started
    assert store.get("A")["ip"] == "10.0.0.55"
    assert triggered and triggered[0][0] == "A"


def test_extract_ipv4_filters_invalid_values():
    assert ip_recovery.extract_ipv4("IP address 192.168.7.23 gateway 999.1.2.3") == [
        "192.168.7.23"
    ]


def test_auth_failure_at_real_receiver_triggers_pair_not_recovery(monkeypatch):
    store = FakeStore({"A": {"ip": "10.0.0.1", "stb": "R1234567890-12"}})
    monkeypatch.setattr(ip_recovery, "_store", store)
    state = ip_recovery._state("A")
    state.consecutive_failures = 1  # next failure reaches auth threshold 2
    monkeypatch.setattr(
        ip_recovery,
        "verify_stored_ip_identity",
        lambda _alias: {"is_stb": True, "rxids": ["123456789012"], "rxid_match": True},
    )
    paired = []
    recovered = []
    monkeypatch.setattr(ip_recovery, "trigger_autopair", lambda a, r: paired.append(a) or True)
    monkeypatch.setattr(ip_recovery, "maybe_trigger_recovery", lambda a: recovered.append(a) or True)
    ip_recovery.note_sgs_failure("A", PermissionError("HTTP 403"))
    assert paired == ["A"]
    assert recovered == []
