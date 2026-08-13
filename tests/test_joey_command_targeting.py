from __future__ import annotations

import json

from jamboree import sgs_bridge


class _Store:
    def __init__(self, entries):
        self.entries = entries

    def get(self, alias):
        value = self.entries.get(alias)
        return dict(value) if value is not None else None

    def document(self):
        return {"stbs": self.entries}


def test_sling_play_pause_aliases_use_same_toggle_command():
    for button in ("Pause", "Play", "pauseplay", "playpause"):
        assert sgs_bridge._key_name_for_button(button, 240) == "Pause/Play"


def test_sling_diamond_uses_sgs_record_contract():
    assert sgs_bridge._key_name_for_button("diamond", 240) == "Record"
    assert sgs_bridge._key_name_for_button("d", 240) == "Record"


def test_joey_attach_uses_child_rid_but_remote_key_uses_host_rid(monkeypatch):
    store = _Store(
        {
            "HOPPER3-PROD4": {
                "role": "hopper",
                "ip": "10.0.0.10",
                "stb": "RHOST000001-11",
            },
            "MOCHAJOEY-HOPPER3-PROD4": {
                "role": "joey",
                "host": "HOPPER3-PROD4",
                "ip": "10.0.0.20",
                "stb": "RJOEY000001-22",
            },
        }
    )
    monkeypatch.setattr(sgs_bridge, "store", store)
    monkeypatch.setattr(sgs_bridge, "get_sgs_codes", lambda _button, _delay: "GUIDE")
    monkeypatch.setattr(sgs_bridge, "sgs_get_receiver_id", lambda: "XAFCLIENT")
    monkeypatch.setattr(sgs_bridge, "_credentials", lambda alias: ("u", "p") if alias == "HOPPER3-PROD4" else None)

    attach_calls = []

    def attach(child_rid, host_alias, host_ip):
        attach_calls.append((child_rid, host_alias, host_ip))
        return 4321

    monkeypatch.setattr(sgs_bridge, "get_or_attach_cid", attach)

    posts = []

    def post(ip, payload, *, creds, timeout=7.0):
        posts.append((ip, dict(payload), creds, timeout))
        return {"result": 1}

    monkeypatch.setattr(sgs_bridge, "_post", post)

    out = json.loads(
        sgs_bridge.send_sgs(
            "MOCHAJOEY-HOPPER3-PROD4",
            "10.0.0.20",
            "RJOEY000001-22",
            "Guide",
            75,
        )
    )

    assert out["result"] == 1
    assert attach_calls == [
        ("RJOEY000001-22", "HOPPER3-PROD4", "10.0.0.10")
    ]
    assert len(posts) == 1
    ip, payload, creds, _timeout = posts[0]
    assert ip == "10.0.0.10"
    assert creds == ("u", "p")
    assert payload["command"] == "remote_key"
    assert payload["stb"] == "RHOST000001-11"
    assert payload["cid"] == 4321
    assert payload["receiver"] == "XAFCLIENT"
    assert payload["key_name"] == "GUIDE"


def test_hopper_remote_key_still_uses_its_own_rid_without_child_cid(monkeypatch):
    store = _Store(
        {
            "HOPPER3-PROD4": {
                "role": "hopper",
                "ip": "10.0.0.10",
                "stb": "RHOST000001-11",
            }
        }
    )
    monkeypatch.setattr(sgs_bridge, "store", store)
    monkeypatch.setattr(sgs_bridge, "get_sgs_codes", lambda _button, _delay: "HOME")
    monkeypatch.setattr(sgs_bridge, "sgs_get_receiver_id", lambda: "XAFCLIENT")
    monkeypatch.setattr(sgs_bridge, "_credentials", lambda _alias: ("u", "p"))
    monkeypatch.setattr(
        sgs_bridge,
        "get_or_attach_cid",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected child attach")),
    )

    posts = []

    def post(ip, payload, *, creds, timeout=7.0):
        posts.append((ip, dict(payload), creds, timeout))
        return {"result": 1}

    monkeypatch.setattr(sgs_bridge, "_post", post)

    out = json.loads(
        sgs_bridge.send_sgs(
            "HOPPER3-PROD4",
            "10.0.0.10",
            "RHOST000001-11",
            "Home",
            100,
        )
    )

    assert out["result"] == 1
    assert len(posts) == 1
    _ip, payload, _creds, _timeout = posts[0]
    assert payload["stb"] == "RHOST000001-11"
    assert "cid" not in payload
