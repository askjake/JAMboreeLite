from __future__ import annotations

import json

from jamboree import sgs_autopair, sgs_bridge
from jamboree.stb_store import STBStore


def _store(tmp_path, stbs):
    path = tmp_path / "base.txt"
    path.write_text(json.dumps({"stbs": stbs}), encoding="utf-8")
    return STBStore(path)


def test_explicit_nonself_host_overrides_legacy_hopper_role(tmp_path):
    store = _store(
        tmp_path,
        {
            "HOPPER3-PROD4": {
                "ip": "10.0.0.10",
                "stb": "R1111111111-11",
                "role": "hopper",
            },
            "HOPPERPLUS-HOPPER3-PROD4": {
                "ip": "10.0.0.20",
                "stb": "R2222222222-22",
                "role": "hopper",
                "host": "HOPPER3-PROD4",
            },
        },
    )

    effective = store.get("HOPPERPLUS-HOPPER3-PROD4")
    assert effective["role"] == "joey"
    assert effective["host"] == "HOPPER3-PROD4"
    # Persisted data is not silently rewritten.
    assert store.all()["HOPPERPLUS-HOPPER3-PROD4"]["role"] == "hopper"


def test_legacy_hopperplus_alias_infers_exact_configured_host(tmp_path):
    store = _store(
        tmp_path,
        {
            "HOPPER3-PROD4": {
                "ip": "10.0.0.10",
                "stb": "R1111111111-11",
            },
            "HOPPERPLUS-HOPPER3-PROD4": {
                "ip": "10.0.0.20",
                "stb": "R2222222222-22",
                "protocol": "SGS",
            },
        },
    )

    effective = store.get("HOPPERPLUS-HOPPER3-PROD4")
    assert effective["role"] == "joey"
    assert effective["host"] == "HOPPER3-PROD4"


def test_unrelated_hopper_alias_is_not_inferred_as_child(tmp_path):
    store = _store(
        tmp_path,
        {
            "HOPPER3-PROD4": {"ip": "10.0.0.10", "stb": "R1111111111-11"},
            "LAB-HOPPER3-PROD4": {"ip": "10.0.0.30", "stb": "R3333333333-33"},
        },
    )

    effective = store.get("LAB-HOPPER3-PROD4")
    assert effective.get("host") in {None, ""}
    assert effective.get("role") in {None, "", "hopper"}


def test_autopair_and_sgs_transport_share_effective_hopperplus_host(monkeypatch, tmp_path):
    store = _store(
        tmp_path,
        {
            "HOPPER3-PROD4": {
                "ip": "10.0.0.10",
                "stb": "R1111111111-11",
                "role": "hopper",
            },
            "HOPPERPLUS-HOPPER3-PROD4": {
                "ip": "10.0.0.20",
                "stb": "R2222222222-22",
                "protocol": "SGS",
            },
        },
    )

    monkeypatch.setattr(sgs_autopair, "_store", store)
    monkeypatch.setattr(sgs_bridge, "store", store)

    pair_alias, pair_entry = sgs_autopair._resolve_pair_target(
        "HOPPERPLUS-HOPPER3-PROD4"
    )
    assert pair_alias == "HOPPER3-PROD4"
    assert pair_entry["ip"] == "10.0.0.10"

    requested, child, host_alias, host = sgs_bridge._host_for(
        "HOPPERPLUS-HOPPER3-PROD4"
    )
    assert requested == "HOPPERPLUS-HOPPER3-PROD4"
    assert child["stb"] == "R2222222222-22"
    assert host_alias == "HOPPER3-PROD4"
    assert host["ip"] == "10.0.0.10"
