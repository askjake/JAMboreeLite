from __future__ import annotations

import os

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


def test_health_exposes_process_and_config_continuity_metadata():
    client = app_module.app.test_client()
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["pid"] == os.getpid()
    assert isinstance(data["uptime_s"], (int, float))
    assert data["uptime_s"] >= 0
    assert data["config"]["exists"] is True
    assert data["config"]["stbs"] == data["stbs"]
    assert data["config"]["generation"] >= 1
    assert data["config"]["external_reloads"] >= 0


def test_recovery_status_route_exists():
    client = app_module.app.test_client()
    response = client.get("/api/ip_recovery/status")
    assert response.status_code == 200
    assert response.is_json


def test_legacy_auto_down_edge_is_acknowledged_without_dispatch(monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        app_module.ctl,
        "handle_auto_remote",
        lambda *_args, **_kwargs: dispatched.append((_args, _kwargs)),
    )
    client = app_module.app.test_client()
    response = client.get("/auto/1/anything/Enter/down")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["via"] == "auto_compat"
    assert data["ignored"] is True
    assert data["ignored_action"] == "down"
    assert dispatched == []


def test_auto_duration_still_dispatches_integer_duration(monkeypatch):
    captured = {}

    def dispatch(remote, stb, button, delay, **kwargs):
        captured.update(remote=remote, stb=stb, button=button, delay=delay, kwargs=kwargs)
        return {"ok": True, "via": "test"}

    monkeypatch.setattr(app_module.ctl, "handle_auto_remote", dispatch)
    client = app_module.app.test_client()
    response = client.get("/auto/1/anything/Enter/137")
    assert response.status_code == 200
    assert response.get_json()["via"] == "test"
    assert captured["delay"] == 137
    assert isinstance(captured["delay"], int)


def test_dual_transport_failure_returns_structured_503(monkeypatch):
    def dispatch(*_args, **_kwargs):
        raise RuntimeError(
            "SGS failed (No SGS credentials for Hopper 'H'; pair first); "
            "RF fallback failed (DART port for 'J' is not open/ready and writable)"
        )

    monkeypatch.setattr(app_module.ctl, "handle_auto_remote", dispatch)
    client = app_module.app.test_client()
    response = client.get("/auto/3/J/Home/70")
    assert response.status_code == 503
    data = response.get_json()
    assert data["ok"] is False
    assert data["error"] == "all_transports_unavailable"
    assert data["alias"] == "J"
    assert "pair first" in data["detail"]
    assert "DART port" in data["detail"]


def test_expected_http_errors_are_structured_json():
    client = app_module.app.test_client()

    response = client.get("/sgs/pair/complete")
    assert response.status_code == 405
    data = response.get_json()
    assert data["status"] == 405
    assert data["error"] == "Method Not Allowed"
    assert "POST" in data["allowed_methods"]

    response = client.get("/source/credentials")
    assert response.status_code == 404
    data = response.get_json()
    assert data["status"] == 404
    assert data["error"] == "Not Found"


def test_safe_sgs_status_compatibility_routes(monkeypatch):
    app_module.store.update_stb(
        "STATUS-H",
        {
            "ip": "10.0.0.20",
            "stb": "R1234567890-20",
            "remote": "1",
            "protocol": "SGS",
            "role": "hopper",
        },
    )
    monkeypatch.setattr(
        app_module.sgs_autopair,
        "get_status",
        lambda: {"phase": "idle", "active": False, "history": []},
    )
    monkeypatch.setattr(
        app_module.sgs_autopair,
        "credentials_status",
        lambda alias: {
            "requested_alias": alias,
            "pair_alias": alias,
            "paired": True,
            "secure_backend": "windows-dpapi-machine",
            "username_present": True,
            "password_present": True,
        },
    )
    client = app_module.app.test_client()

    response = client.get("/sgs/status")
    assert response.status_code == 200
    assert response.get_json()["phase"] == "idle"

    response = client.get("/sgs/credentials/status")
    assert response.status_code == 200
    assert response.get_json()["requires_alias"] is True

    response = client.get("/sgs/credentials/status?alias=STATUS-H")
    assert response.status_code == 200
    data = response.get_json()
    assert data["paired"] is True
    assert data["secure_backend"] == "windows-dpapi-machine"
    assert "secret" not in repr(data).lower()
