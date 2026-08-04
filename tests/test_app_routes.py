from __future__ import annotations

import pytest

flask = pytest.importorskip("flask")

from jamboree import app as app_module


def test_save_stb_list_replaces_visible_rows_but_preserves_hidden_fields(monkeypatch):
    app_module.store.update_stb(
        "H",
        {
            "ip": "10.0.0.1",
            "stb": "R1234567890-12",
            "remote": "1",
            "com_port": "COM1",
            "lname": "legacy-user",
            "passwd": "legacy-pass",
        },
    )
    monkeypatch.setattr(app_module, "init_serial_from_base", lambda _doc: None)
    client = app_module.app.test_client()
    response = client.post(
        "/save-stb-list",
        json={"stbs": {"H": {"ip": "10.0.0.2", "stb": "R1234567890-12"}}},
    )
    assert response.status_code == 200
    entry = app_module.store.get("H")
    assert entry["ip"] == "10.0.0.2"
    assert entry["lname"] == "legacy-user"
    assert entry["passwd"] == "legacy-pass"
    assert entry["remote"] == "1"


def test_recovery_status_route_exists():
    client = app_module.app.test_client()
    response = client.get("/api/ip_recovery/status")
    assert response.status_code == 200
    assert response.is_json
