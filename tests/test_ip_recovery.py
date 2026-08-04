from jamboree.ip_recovery import classify_sgs_failure, extract_ipv4, recover_alias


def test_classifier_does_not_recover_auth_or_empty_errors():
    assert not classify_sgs_failure("HTTP 403 auth_required").recoverable
    assert classify_sgs_failure("HTTP 403 auth_required").auth
    assert not classify_sgs_failure("").recoverable
    assert classify_sgs_failure("connection timed out").recoverable


def test_ipv4_extraction_handles_10_network():
    assert extract_ipv4("Network 10.73.185.30 mask 255.255.255.0") == ["10.73.185.30"]


def test_recovery_rejects_ambiguous_identity(monkeypatch):
    import jamboree.ip_recovery as recovery
    monkeypatch.setattr(recovery.store, "get", lambda alias: {"ip": "10.0.0.1", "stb": "R1234567890-12"})
    result = recover_alias("A", scan=lambda ip, rid: ["10.0.0.2", "10.0.0.3"])
    assert not result.ok
    assert "ambiguous" in result.reason


def test_recovery_rolls_back_actual_old_ip(monkeypatch):
    import jamboree.ip_recovery as recovery
    entry = {"ip": "10.0.0.1", "stb": "R1234567890-12"}
    updates = []
    monkeypatch.setattr(recovery.store, "get", lambda alias: dict(entry))
    def update(alias, fields):
        updates.append(dict(fields)); entry.update(fields)
    monkeypatch.setattr(recovery.store, "update_stb", update)
    checks = iter([True, False])
    result = recover_alias("A", scan=lambda ip, rid: ["10.0.0.2"], verify=lambda ip, rid: next(checks))
    assert not result.ok
    assert updates[-1] == {"ip": "10.0.0.1"}
