from __future__ import annotations

import json

from jamboree.core import credentials as credentials_module
from jamboree.core.credentials import CredentialManager


class BrokenWindowsKeyring:
    def set_password(self, *_args, **_kwargs):
        raise OSError(1312, "CredRead", "A specified logon session does not exist")

    def get_password(self, *_args, **_kwargs):
        raise OSError(1312, "CredRead", "A specified logon session does not exist")

    def delete_password(self, *_args, **_kwargs):
        raise OSError(1312, "CredDelete", "A specified logon session does not exist")


def test_windows_keyring_1312_falls_back_to_dpapi(monkeypatch, tmp_path):
    path = tmp_path / "credentials.dpapi.json"
    monkeypatch.setenv("JAMBOREE_CREDENTIAL_FILE", str(path))
    monkeypatch.setattr(credentials_module, "keyring", BrokenWindowsKeyring())
    monkeypatch.setattr(credentials_module, "_is_windows", lambda: True)
    monkeypatch.setattr(
        credentials_module,
        "_dpapi_protect",
        lambda data: (b"protected:" + data[::-1], "machine"),
    )
    monkeypatch.setattr(
        credentials_module,
        "_dpapi_unprotect",
        lambda data: data.removeprefix(b"protected:")[::-1],
    )

    assert CredentialManager.store_credentials("Wally", "issued-user", "issued-secret")
    assert CredentialManager.get_credentials("Wally") == ("issued-user", "issued-secret")

    status = CredentialManager.status("Wally")
    assert status["stored"] is True
    assert status["secure"] is True
    assert status["backend"] == "windows-dpapi-machine"

    on_disk = path.read_text(encoding="utf-8")
    assert "issued-user" not in on_disk
    assert "issued-secret" not in on_disk
    doc = json.loads(on_disk)
    assert doc["records"]["Wally"]["scope"] == "machine"


def test_dpapi_record_is_preferred_over_broken_keyring(monkeypatch, tmp_path):
    path = tmp_path / "credentials.dpapi.json"
    monkeypatch.setenv("JAMBOREE_CREDENTIAL_FILE", str(path))
    monkeypatch.setattr(credentials_module, "_is_windows", lambda: True)
    monkeypatch.setattr(
        credentials_module,
        "_dpapi_protect",
        lambda data: (b"protected:" + data[::-1], "user"),
    )
    monkeypatch.setattr(
        credentials_module,
        "_dpapi_unprotect",
        lambda data: data.removeprefix(b"protected:")[::-1],
    )
    monkeypatch.setattr(credentials_module, "keyring", None)
    assert CredentialManager.store_credentials("Hopper", "u", "p")

    broken = BrokenWindowsKeyring()
    monkeypatch.setattr(credentials_module, "keyring", broken)
    assert CredentialManager.get_credentials("Hopper") == ("u", "p")


def test_plaintext_opt_in_is_not_reported_as_secure_backend(monkeypatch):
    monkeypatch.setattr(credentials_module, "keyring", None)
    monkeypatch.setattr(credentials_module, "_is_windows", lambda: False)
    monkeypatch.setenv("JAMBOREE_ALLOW_PLAINTEXT_CREDENTIALS", "1")
    base = {"stbs": {"Legacy": {"lname": "legacy-user", "passwd": "legacy-secret"}}}

    assert CredentialManager.get_credentials("Legacy", base) == ("legacy-user", "legacy-secret")
    status = CredentialManager.status("Legacy", base)
    assert status["stored"] is True
    assert status["secure"] is False
    assert status["backend"] is None
