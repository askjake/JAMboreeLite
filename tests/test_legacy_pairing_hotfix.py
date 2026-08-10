from __future__ import annotations

import json

from jamboree import app as app_module
from jamboree.stb_store import STBStore


def _store(tmp_path, stbs):
    path = tmp_path / "base.txt"
    path.write_text(json.dumps({"stbs": stbs}), encoding="utf-8")
    return STBStore(path)


def test_independent_hopper_ignores_stale_default_host(tmp_path):
    store = _store(
        tmp_path,
        {
            "HOPPER3": {"ip": "10.0.0.1", "stb": "R1000000000-00", "role": "hopper", "host": "HOPPER3"},
            "WALLY": {"ip": "10.0.0.2", "stb": "R2000000000-00", "role": "hopper", "host": "HOPPER3"},
            "XIP913": {"ip": "10.0.0.3", "stb": "R3000000000-00", "role": "hopper", "host": "HOPPER3"},
        },
    )

    wally = store.get("WALLY")
    xip = store.get("XIP913")
    assert wally["role"] == "hopper"
    assert wally["host"] == "WALLY"
    assert xip["role"] == "hopper"
    assert xip["host"] == "XIP913"
    # Persistent configuration is not rewritten by runtime normalization.
    assert store.all()["WALLY"]["host"] == "HOPPER3"


def test_legacy_hopperplus_prefers_exact_alias_suffix_over_default_host(tmp_path):
    store = _store(
        tmp_path,
        {
            "HOPPER3": {"ip": "10.0.0.1", "stb": "R1000000000-00", "role": "hopper"},
            "HOPPER3-PROD4": {"ip": "10.0.0.2", "stb": "R2000000000-00", "role": "hopper", "host": "HOPPER3"},
            "HOPPERPLUS-HOPPER3-PROD4": {
                "ip": "10.0.0.3",
                "stb": "R3000000000-00",
                "role": "hopper",
                "host": "HOPPER3",
            },
        },
    )

    child = store.get("HOPPERPLUS-HOPPER3-PROD4")
    assert child["role"] == "joey"
    assert child["host"] == "HOPPER3-PROD4"


def test_explicit_joey_host_remains_authoritative(tmp_path):
    store = _store(
        tmp_path,
        {
            "HOPPER3-PROD4": {"ip": "10.0.0.1", "stb": "R1000000000-00", "role": "hopper"},
            "HOPPERPLUS-HOPPER3-PROD4": {"ip": "10.0.0.2", "stb": "R2000000000-00", "role": "hopper"},
            "MOCHAJOEY-HOPPER3-PROD4": {
                "ip": "10.0.0.3",
                "stb": "R3000000000-00",
                "role": "joey",
                "host": "HOPPERPLUS-HOPPER3-PROD4",
            },
        },
    )

    child = store.get("MOCHAJOEY-HOPPER3-PROD4")
    assert child["role"] == "joey"
    assert child["host"] == "HOPPERPLUS-HOPPER3-PROD4"


def test_get_stb_list_redacts_legacy_credentials():
    alias = "REDACT-HOTFIX"
    app_module.store.update_stb(
        alias,
        {
            "ip": "10.0.0.40",
            "stb": "R4000000000-00",
            "protocol": "SGS",
            "role": "hopper",
            "lname": "legacy-user-should-not-leak",
            "passwd": "legacy-pass-should-not-leak",
        },
    )
    client = app_module.app.test_client()
    response = client.get("/get-stb-list")
    assert response.status_code == 200
    entry = response.get_json()["stbs"][alias]
    assert "lname" not in entry
    assert "passwd" not in entry
    # Redaction is response-only; the migration source remains available on disk.
    raw = app_module.store.all()[alias]
    assert raw["lname"] == "legacy-user-should-not-leak"
    assert raw["passwd"] == "legacy-pass-should-not-leak"


def test_pair_start_failure_exposes_safe_compat_message(monkeypatch):
    alias = "PAIRFAIL-HOTFIX"
    app_module.store.update_stb(
        alias,
        {"ip": "10.0.0.50", "stb": "R5000000000-00", "protocol": "SGS", "role": "hopper"},
    )
    monkeypatch.setattr(
        app_module.sgs_autopair,
        "pair_start",
        lambda _alias: {
            "ok": False,
            "requested_alias": _alias,
            "pair_alias": _alias,
            "response": {"result": -1, "error": "transport", "detail": "connect timed out"},
        },
    )
    client = app_module.app.test_client()
    response = client.post("/sgs/pair/start", json={"alias": alias})
    assert response.status_code == 502
    data = response.get_json()
    assert data["ok"] is False
    assert data["error"] == "transport"
    assert data["msg"] == "transport"
    assert "secret" not in repr(data).lower()
