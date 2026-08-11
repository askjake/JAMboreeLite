from __future__ import annotations

from copy import deepcopy

from jamboree import ip_recovery, mac_learning, sgs_bridge


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
    monkeypatch.setattr(
        ip_recovery,
        "probe_device_identity",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("verified-MAC learning must not identity-probe")
        ),
    )

    result = mac_learning.learn_verified_mac(
        "H",
        "192.168.1.67",
        store_obj=store,
        arp_reader=lambda: {"192.168.1.67": "88:b6:ee:de:58:cc"},
    )

    assert result["learned"] is True
    assert result["mac"] == "88:b6:ee:de:58:cc"
    assert store.get("H")["mac"] == "88:b6:ee:de:58:cc"
    assert ip_recovery._state("H").known_mac == "88:b6:ee:de:58:cc"


def test_learn_verified_mac_refuses_to_overwrite_existing_different_mac():
    store = FakeStore(
        {
            "H": {
                "ip": "192.168.1.67",
                "stb": "R1956395067-79",
                "mac": "00:11:22:33:44:55",
            }
        }
    )

    result = mac_learning.learn_verified_mac(
        "H",
        "192.168.1.67",
        store_obj=store,
        arp_reader=lambda: {"192.168.1.67": "88:b6:ee:de:58:cc"},
    )

    assert result["learned"] is False
    assert result["reason"] == "existing_mac_mismatch"
    assert store.get("H")["mac"] == "00:11:22:33:44:55"
    assert store.updates == []


def test_learn_verified_mac_skips_if_config_ip_changed_after_sgs():
    store = FakeStore(
        {
            "H": {
                "ip": "192.168.1.250",
                "stb": "R1956395067-79",
            }
        }
    )

    result = mac_learning.learn_verified_mac(
        "H",
        "192.168.1.67",
        store_obj=store,
        arp_reader=lambda: {"192.168.1.67": "88:b6:ee:de:58:cc"},
    )

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


def test_send_sgs_schedules_verified_mac_learning_for_hopper(monkeypatch):
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
    monkeypatch.setattr(sgs_bridge, "store", store)
    monkeypatch.setattr(sgs_bridge, "get_sgs_codes", lambda *_a, **_k: "guide")
    monkeypatch.setattr(sgs_bridge, "_credentials", lambda _alias: ("u", "p"))
    monkeypatch.setattr(sgs_bridge, "_post", lambda *_a, **_k: {"result": 1})
    learned = []
    monkeypatch.setattr(
        sgs_bridge.mac_learning,
        "learn_verified_mac_async",
        lambda alias, ip: learned.append((alias, ip)) or True,
    )

    result = sgs_bridge.send_sgs("H", "192.168.1.67", "R1956395067-79", "Guide", 240)

    assert '"result": 1' in result
    assert learned == [("H", "192.168.1.67")]


def test_send_sgs_learns_host_mac_for_joey(monkeypatch):
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
    monkeypatch.setattr(sgs_bridge, "store", store)
    monkeypatch.setattr(sgs_bridge, "get_sgs_codes", lambda *_a, **_k: "guide")
    monkeypatch.setattr(sgs_bridge, "_credentials", lambda _alias: ("u", "p"))
    monkeypatch.setattr(sgs_bridge, "get_or_attach_cid", lambda *_a, **_k: 1234)
    monkeypatch.setattr(sgs_bridge, "_post", lambda *_a, **_k: {"result": 1})
    learned = []
    monkeypatch.setattr(
        sgs_bridge.mac_learning,
        "learn_verified_mac_async",
        lambda alias, ip: learned.append((alias, ip)) or True,
    )

    result = sgs_bridge.send_sgs("J", "192.168.1.99", "R1111111111-11", "Guide", 240)

    assert '"result": 1' in result
    assert learned == [("H", "192.168.1.67")]
