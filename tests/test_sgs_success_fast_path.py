"""Regression tests for the healthy SGS response fast path."""

from jamboree import ip_recovery


def test_note_sgs_success_does_not_probe_mac_or_identity(monkeypatch):
    alias = "FAST-SGS"
    state = ip_recovery._state(alias)
    state.consecutive_failures = 2
    state.last_failure = {"error": "previous failure"}
    state.known_mac = "aa:bb:cc:dd:ee:ff"

    def forbidden_probe(_alias):
        raise AssertionError(
            "healthy SGS success path must not perform MAC/identity discovery"
        )

    monkeypatch.setattr(ip_recovery, "_configured_mac", forbidden_probe)

    ip_recovery.note_sgs_success(alias)

    assert state.consecutive_failures == 0
    assert state.last_failure == {}
    assert state.known_mac == "aa:bb:cc:dd:ee:ff"


def test_mac_discovery_remains_available_to_recovery(monkeypatch):
    alias = "RECOVERY-SGS"
    calls = []

    def configured_mac(name):
        calls.append(name)
        return None

    monkeypatch.setattr(ip_recovery, "_configured_mac", configured_mac)

    assert ip_recovery.find_by_mac(alias, candidates=[]) is None
    assert calls == [alias]
