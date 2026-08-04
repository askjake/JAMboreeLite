import json
from pathlib import Path
from jamboree import base_io


def test_additive_atomic_update_preserves_credentials_and_top_keys(tmp_path):
    path = tmp_path / "base.txt"
    path.write_text(json.dumps({"default_stb": "A", "stbs": {"A": {"ip": "1.1.1.1", "lname": "u", "passwd": "p", "remote": "1"}}}))
    base_io.update_stb_fields(path, "A", {"ip": "1.1.1.2"})
    data = json.loads(path.read_text())
    assert data["default_stb"] == "A"
    assert data["stbs"]["A"] == {"ip": "1.1.1.2", "lname": "u", "passwd": "p", "remote": "1"}
    assert Path(str(path) + ".bak").is_file()


def test_replace_table_preserves_hidden_fields(tmp_path):
    path = tmp_path / "base.txt"
    path.write_text(json.dumps({"stbs": {"A": {"ip": "old", "passwd": "secret", "com_port": "COM9"}}}))
    base_io.replace_stb_table(path, {"A": {"ip": "new"}})
    assert json.loads(path.read_text())["stbs"]["A"] == {"ip": "new", "passwd": "secret", "com_port": "COM9"}


def test_corrupt_primary_recovers_from_backup(tmp_path):
    path = tmp_path / "base.txt"
    path.write_text("{")
    Path(str(path) + ".bak").write_text('{"stbs":{"A":{"ip":"ok"}}}')
    assert base_io.read_document(path)["stbs"]["A"]["ip"] == "ok"
