from __future__ import annotations

import json
from copy import deepcopy

import pytest

from jamboree import controller as controller_module
from jamboree import ip_recovery
from jamboree.stb_store import STBStore


def _write_base(path, stbs):
    path.write_text(json.dumps({"stbs": stbs}, indent=2) + "\n", encoding="utf-8")


def test_store_resolves_unique_alias_case_insensitively(tmp_path):
    path = tmp_path / "base.txt"
    _write_base(
        path,
        {
            "HOPPER3-PROD": {
                "ip": "192.168.1.67",
                "stb": "R1956395067-79",
                "protocol": "SGS",
                "remote": "8",
                "role": "hopper",
            }
        },
    )
    store = STBStore(path)

    assert store.resolve_alias("HOPPER3-Prod") == "HOPPER3-PROD"
    assert store.resolve_alias("hopper3-prod") == "HOPPER3-PROD"
    assert store.resolve_alias("HOPPER3-PROD") == "HOPPER3-PROD"


def test_store_case_collision_fails_closed(tmp_path):
    path = tmp_path / "base.txt"
    _write_base(
        path,
        {
            "XIP813-PROD": {
                "ip": "192.168.1.59",
                "stb": "R1881189943-58",
            },
            "XIP813-Prod": {
                "ip": "192.168.1.59",
                "stb": "R1881189943-58",
            },
        },
    )
    store = STBStore(path)

    with pytest.raises(ValueError, match="case-insensitive alias collision"):
        store.resolve_alias("xip813-prod")


def test_replace_stbs_rejects_case_collision(tmp_path):
    path = tmp_path / "base.txt"
    _write_base(path, {})
    store = STBStore(path)

    with pytest.raises(ValueError, match="case-insensitive alias collision"):
        store.replace_stbs(
            {
                "XIP913-PROD": {"ip": "192.168.1.88", "stb": "R1893508425-37"},
                "XIP913-Prod": {"ip": "192.168.1.88", "stb": "R1893508425-37"},
            }
        )


def test_update_stb_uses_existing_canonical_alias_instead_of_creating_case_variant(tmp_path):
    path = tmp_path / "base.txt"
    _write_base(
        path,
        {
            "HOPPER3-PROD": {
                "ip": "192.168.1.67",
                "stb": "R1956395067-79",
                "protocol": "SGS",
            }
        },
    )
    store = STBStore(path)

    store.update_stb("HOPPER3-Prod", {"mac": "88:b6:ee:de:58:cc"})

    document = store.document()
    assert set(document["stbs"]) == {"HOPPER3-PROD"}
    assert document["stbs"]["HOPPER3-PROD"]["mac"] == "88:b6:ee:de:58:cc"


class _ControllerStore:
    def __init__(self):
        self.entries = {
            "HOPPER3-PROD": {
                "ip": "192.168.1.67",
                "stb": "R1956395067-79",
                "protocol": "SGS",
                "remote": "8",
                "com_port": "COM3",
                "role": "hopper",
            }
        }

    def all(self):
        return self.entries

    def get(self, alias):
        value = self.entries.get(alias)
        return deepcopy(value) if value else None

    def document(self):
        return {"stbs": deepcopy(self.entries)}

    def resolve_alias(self, alias):
        exact = str(alias).strip()
        if exact in self.entries:
            return exact
        matches = [name for name in self.entries if name.casefold() == exact.casefold()]
        if len(matches) == 1:
            return matches[0]
        return None


def test_controller_uses_canonical_alias_for_mixed_case_auto_request(monkeypatch):
    fake_store = _ControllerStore()
    monkeypatch.setattr(controller_module, "store", fake_store)

    calls = []
    monkeypatch.setattr(
        controller_module,
        "send_sgs",
        lambda alias, ip, rid, button, duration: calls.append(
            (alias, ip, rid, button, duration)
        )
        or '{"result":1}',
    )
    successes = []
    monkeypatch.setattr(ip_recovery, "note_sgs_success", lambda alias: successes.append(alias))

    ctl = controller_module.Controller()
    result = ctl.handle_auto_remote("8", "HOPPER3-Prod", "Guide", 240)

    assert result["via"] == "sgs"
    assert calls == [
        ("HOPPER3-PROD", "192.168.1.67", "R1956395067-79", "Guide", 240)
    ]
    assert successes == ["HOPPER3-PROD"]
