from __future__ import annotations

from copy import deepcopy

from jamboree import controller as controller_module
from jamboree import ip_recovery


class FakeStore:
    def __init__(self, entries):
        self.entries = deepcopy(entries)
        self.updates = []

    def get(self, alias):
        return self.entries.get(alias)

    def all(self):
        return self.entries

    def document(self):
        return {"stbs": deepcopy(self.entries)}

    def update_stb(self, alias, fields, **_kwargs):
        self.entries.setdefault(alias, {}).update(fields)
        self.updates.append((alias, dict(fields)))
        return self.document()


def test_learn_verified_mac_persists_arp_identity_without_network_probe(monkeypatch):
    store = FakeStore(
        {
            "H": {
                "ip": "192.168.1.67",
                "stb": "R1956395067-79",
                "protocol": "SGS",
                "role": "hopper",
            }
        }
    )
    monkeypatch.setattr(ip_recovery, "_store", store)
    monkeypatch.setattr(
        ip_recovery,
        "_arp_entries",
        lambda: {"192.168.1.67": "88:b6:ee:de:58:cc"},
    )
    monkeypatch.setattr(
        ip_recovery,
        "probe_device_identity",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("verified-MAC learning must not identity-probe")
        ),
    )

    result = ip_recovery.learn_verified_mac("H", "192.168.1.67")

    assert result["learned"] is True
    assert result["mac"] == "88:b6:ee:de:58:cc"
    assert store.get("H")["mac"] == "88:b6:ee:de:58:cc"
    assert ip_recovery._state("H").known_mac == "88:b6:ee:de:58:cc"


def test_learn_verified_mac_refuses_to_overwrite_existing_different_mac(monkeypatch):
    store = FakeStore(
        {
            "H": {
                "ip": "192.168.1.67",
                "stb": "R1956395067-79",
                "mac": "00:11:22:33:44:55",
            }
        }
    )
    monkeypatch.setattr(ip_recovery, "_store", store)
    monkeypatch.setattr(
        ip_recovery,
        "_arp_entries",
        lambda: {"192.168.1.67": "88:b6:ee:de:58:cc"},
    )

    result = ip_recovery.learn_verified_mac("H", "192.168.1.67")

    assert result["learned"] is False
    assert result["reason"] == "existing_mac_mismatch"
    assert store.get("H")["mac"] == "00:11:22:33:44:55"
    assert store.updates == []


def test_learn_verified_mac_skips_if_config_ip_changed_after_sgs(monkeypatch):
    store = FakeStore(
        {
            "H": {
                "ip": "192.168.1.250",
                "stb": "R1956395067-79",
            }
        }
    )
    monkeypatch.setattr(ip_recovery, "_store", store)
    monkeypatch.setattr(
        ip_recovery,
        "_arp_entries",
        lambda: {"192.168.1.67": "88:b6:ee:de:58:cc"},
    )

    result = ip_recovery.learn_verified_mac("H", "192.168.1.67")

    assert result["learned"] is False
    assert result["reason"] == "configured_ip_changed"
    assert store.updates == []


def test_find_by_mac_recovers_unidentified_receiver_when_mac_is_persisted(monkeypatch):
    store = FakeStore(
        {
            "H": {
                "ip": "192.168.1.250",
                "stb": "R1956395067-79",
                "mac": "88:b6:ee:de:58:cc",
            }
        }
    )
    monkeypatch.setattr(ip_recovery, "_store", store)
    monkeypatch.setattr(ip_recovery, "_touch_host", lambda *_a, **_k: None)
    monkeypatch.setattr(
        ip_recovery,
        "_arp_entries",
        lambda: {
            "192.168.1.67": "88:b6:ee:de:58:cc",
            "192.168.1.90": "00:11:22:33:44:55",
        },
    )
    monkeypatch.setattr(
        ip_recovery,
        "probe_device_identity",
        lambda ip, _rid: {
            "is_stb": True,
            "rxids": [],
            "rxid_match": False,
            "reason": "sgs_response",
            "ip": ip,
        },
    )

    assert ip_recovery.find_by_mac(
        "H", candidates=["192.168.1.67", "192.168.1.90"], workers=2
    ) == "192.168.1.67"


def test_controller_schedules_mac_learning_after_verified_hopper_sgs(monkeypatch):
    store = FakeStore(
        {
            "H": {
                "ip": "192.168.1.67",
                "stb": "R1956395067-79",
                "protocol": "SGS",
                "remote": "8",
                "role": "hopper",
            }
        }
    )
    monkeypatch.setattr(controller_module, "store", store)
    monkeypatch.setattr(controller_module, "send_sgs", lambda *_a, **_k: '{"result": 1}')
    monkeypatch.setattr(ip_recovery, "note_sgs_success", lambda *_a, **_k: None)
    learned = []
    monkeypatch.setattr(
        ip_recovery,
        "learn_verified_mac_async",
        lambda alias, ip: learned.append((alias, ip)) or True,
        raising=False,
    )

    result = controller_module.Controller().handle_auto_remote(
        "8", "H", "Guide", 240, allow_rf_fallback=False
    )

    assert result["via"] == "sgs"
    assert learned == [("H", "192.168.1.67")]


def test_controller_learns_host_mac_after_verified_joey_sgs(monkeypatch):
    store = FakeStore(
        {
            "H": {
                "ip": "192.168.1.67",
                "stb": "R1956395067-79",
                "protocol": "SGS",
                "remote": "8",
                "role": "hopper",
            },
            "J": {
                "ip": "192.168.1.99",
                "stb": "R1111111111-11",
                "protocol": "SGS",
                "remote": "9",
                "role": "joey",
                "host": "H",
            },
        }
    )
    monkeypatch.setattr(controller_module, "store", store)
    monkeypatch.setattr(controller_module, "send_sgs", lambda *_a, **_k: '{"result": 1}')
    monkeypatch.setattr(ip_recovery, "note_sgs_success", lambda *_a, **_k: None)
    learned = []
    monkeypatch.setattr(
        ip_recovery,
        "learn_verified_mac_async",
        lambda alias, ip: learned.append((alias, ip)) or True,
        raising=False,
    )

    result = controller_module.Controller().handle_auto_remote(
        "9", "J", "Guide", 240, allow_rf_fallback=False
    )

    assert result["via"] == "sgs"
    assert learned == [("H", "192.168.1.67")]
