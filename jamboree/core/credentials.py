"""SGS credential storage with keyring-first, opt-in plaintext fallback."""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

LOG = logging.getLogger(__name__)
try:
    import keyring
except ImportError:  # pragma: no cover
    keyring = None


class CredentialManager:
    SERVICE_NAME = "JAMboreeLite"

    @classmethod
    def store_credentials(cls, alias: str, username: str, password: str) -> bool:
        if not alias or not username or not password:
            return False
        if keyring is None:
            LOG.error("OS keyring is unavailable; refusing insecure credential storage")
            return False
        try:
            keyring.set_password(cls.SERVICE_NAME, f"{alias}_username", username)
            keyring.set_password(cls.SERVICE_NAME, f"{alias}_password", password)
            return True
        except Exception as exc:
            LOG.error("Failed to store SGS credentials for %s: %s", alias, exc)
            return False

    @classmethod
    def get_credentials(cls, alias: str, base_dict: Optional[dict] = None) -> Tuple[Optional[str], Optional[str]]:
        if keyring is not None:
            try:
                username = keyring.get_password(cls.SERVICE_NAME, f"{alias}_username")
                password = keyring.get_password(cls.SERVICE_NAME, f"{alias}_password")
                if username and password:
                    return username, password
            except Exception as exc:
                LOG.warning("OS keyring read failed for %s: %s", alias, exc)
        if os.getenv("JAMBOREE_ALLOW_PLAINTEXT_CREDENTIALS") == "1" and base_dict:
            entry = (base_dict.get("stbs", {}) or {}).get(alias, {}) or {}
            username, password = entry.get("lname"), entry.get("passwd")
            if username and password:
                LOG.warning("Using opt-in plaintext SGS credential fallback for %s", alias)
                return str(username), str(password)
        return None, None

    @classmethod
    def has_stored_credentials(cls, alias: str, base_dict: Optional[dict] = None) -> bool:
        username, password = cls.get_credentials(alias, base_dict)
        return bool(username and password)
