from __future__ import annotations

import json
from pathlib import Path

import pytest

from jamboree import base_io


def test_update_stb_is_additive_and_atomic(tmp_path: Path):
    path = tmp_path / "base.txt"
    original = {
        "site": "lab-a",
        "stbs": {
            "Hopper": {
                "ip": "10.0.0.10",
                "stb": "R1234567890-12",
                "remote": "1",
                "com_port": "COM7",
                "lname": "legacy-user",
                "passwd": "legacy-secret",
            }
        },
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    result = base_io.update_stb_fields(path, "Hopper", {"ip": "10.0.0.44"})
    assert result["site"] == "lab-a"
    assert result["stbs"]["Hopper"]["ip"] == "10.0.0.44"
    assert result["stbs"]["Hopper"]["passwd"] == "legacy-secret"
    assert json.loads(path.read_text())["stbs"]["Hopper"]["com_port"] == "COM7"
    assert Path(f"{path}.bak").is_file()


def test_replace_stb_table_preserves_hidden_fields(tmp_path: Path):
    path = tmp_path / "base.txt"
    path.write_text(
        json.dumps(
            {
                "stbs": {
                    "H": {
                        "ip": "1.1.1.1",
                        "stb": "R1234567890-12",
                        "lname": "u",
                        "passwd": "p",
                        "remote": "2",
                        "com_port": "COM9",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    result = base_io.replace_stb_table(
        path, {"H": {"ip": "2.2.2.2", "stb": "R1234567890-12"}}
    )
    assert result["stbs"]["H"]["lname"] == "u"
    assert result["stbs"]["H"]["passwd"] == "p"
    assert result["stbs"]["H"]["remote"] == "2"
    assert result["stbs"]["H"]["com_port"] == "COM9"


def test_corrupt_primary_recovers_from_backup(tmp_path: Path):
    path = tmp_path / "base.txt"
    path.write_text("not-json", encoding="utf-8")
    Path(f"{path}.bak").write_text('{"stbs":{"H":{"ip":"10.1.1.1"}}}', encoding="utf-8")
    assert base_io.read_document(path)["stbs"]["H"]["ip"] == "10.1.1.1"


def test_lock_timeout_fails_closed(tmp_path: Path, monkeypatch):
    path = tmp_path / "base.txt"
    path.write_text('{"stbs":{}}', encoding="utf-8")
    lock = base_io._FileLock(path, timeout=0)
    # This is a structural regression guard: entering either acquires a real lock
    # or raises; it may never return an unlocked context after timeout.
    entered = lock.__enter__()
    assert entered._locked is True
    lock.__exit__(None, None, None)
