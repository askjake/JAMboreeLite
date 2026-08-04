"""Keyring-first SGS credential management.

Secrets are never returned by API status calls and are never written to
``base.txt`` unless the operator explicitly enables the legacy fallback with
``JAMBOREE_ALLOW_PLAINTEXT_CREDENTIALS=1``.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

LOG = logging.getLogger(__name__)
try:
    import keyring
except ImportError:  # pragma: no cover - dependency is required in normal installs
    keyring = None


class CredentialManager:
    SERVICE_NAME = "JAMboreeLite"

    @classmethod
    def _keys(cls, alias: str) -> tuple[str, str]:
        alias = str(alias).strip()
        return f"{alias}_username", f"{alias}_password"

    @classmethod
    def store_credentials(cls, alias: str, username: str, password: str) -> bool:
        alias, username, password = str(alias).strip(), str(username or ""), str(password or "")
        if not alias or not username or not password:
            LOG.error("refusing to store incomplete SGS credentials for %r", alias)
            return False
        if keyring is None:
            LOG.error("OS keyring is unavailable; refusing insecure credential storage")
            return False
        try:
            user_key, pass_key = cls._keys(alias)
            keyring.set_password(cls.SERVICE_NAME, user_key, username)
            keyring.set_password(cls.SERVICE_NAME, pass_key, password)
            return True
        except Exception as exc:
            LOG.error("failed to store SGS credentials for %s: %s", alias, exc)
            return False

    @classmethod
    def get_credentials(
        cls, alias: str, base_dict: Optional[dict] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        alias = str(alias).strip()
        if not alias:
            return None, None
        if keyring is not None:
            try:
                user_key, pass_key = cls._keys(alias)
                username = keyring.get_password(cls.SERVICE_NAME, user_key)
                password = keyring.get_password(cls.SERVICE_NAME, pass_key)
                if username and password:
                    return str(username), str(password)
            except Exception as exc:
                LOG.warning("OS keyring read failed for %s: %s", alias, exc)
        if os.getenv("JAMBOREE_ALLOW_PLAINTEXT_CREDENTIALS") == "1" and base_dict:
            entry = (base_dict.get("stbs", {}) or {}).get(alias, {}) or {}
            username, password = entry.get("lname"), entry.get("passwd")
            if username and password:
                LOG.warning("using opt-in plaintext SGS credential fallback for %s", alias)
                return str(username), str(password)
        return None, None

    @classmethod
    def status(cls, alias: str, base_dict: Optional[dict] = None) -> dict:
        username, password = cls.get_credentials(alias, base_dict)
        return {
            "alias": str(alias),
            "stored": bool(username and password),
            "backend": "keyring" if username and password and keyring is not None else None,
            "username_present": bool(username),
            "password_present": bool(password),
        }

    @classmethod
    def has_stored_credentials(cls, alias: str, base_dict: Optional[dict] = None) -> bool:
        username, password = cls.get_credentials(alias, base_dict)
        return bool(username and password)

    @classmethod
    def clear_credentials(cls, alias: str) -> bool:
        if keyring is None:
            return False
        ok = True
        for key in cls._keys(alias):
            try:
                keyring.delete_password(cls.SERVICE_NAME, key)
            except Exception as exc:
                # Missing values are harmless; backend failures are not.
                if exc.__class__.__name__ != "PasswordDeleteError":
                    LOG.warning("failed to clear keyring value for %s: %s", alias, exc)
                    ok = False
        return ok
