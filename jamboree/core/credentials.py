"""Secure SGS credential management with a Windows DPAPI fallback.

The OS keyring remains the preferred backend. Windows Credential Manager is
not available to every logon type (notably some network/remote sessions), so on
Windows a failed keyring operation falls back to a DPAPI-protected local file.
When keyring is unusable, new fallback records deliberately use machine-scoped
DPAPI so they survive logon-session changes on the same host. Plaintext
``base.txt`` credentials remain explicit opt-in compatibility only.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
from typing import Optional, Tuple

LOG = logging.getLogger(__name__)
try:
    import keyring
except ImportError:  # pragma: no cover - dependency is required in normal installs
    keyring = None

_DPAPI_VERSION = 1
_DPAPI_UI_FORBIDDEN = 0x1
_DPAPI_LOCAL_MACHINE = 0x4
_DPAPI_LOCK = threading.RLock()
# Remember one unreadable encrypted record so every remote key does not repeat
# the same warning. Re-pairing overwrites the record and clears this cache.
_DPAPI_BAD_RECORDS: dict[str, str] = {}


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _is_windows() -> bool:
    return os.name == "nt"


def _credential_path() -> Path:
    override = os.getenv("JAMBOREE_CREDENTIAL_FILE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    root = os.getenv("LOCALAPPDATA", "").strip() or os.getenv("PROGRAMDATA", "").strip()
    if root:
        return Path(root) / "JAMboreeLite" / "sgs_credentials.dpapi.json"
    return Path.home() / ".jamboreelite" / "sgs_credentials.dpapi.json"


def _win32_libraries():
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _blob_from_bytes(data: bytes) -> tuple[_DATA_BLOB, object]:
    raw = bytes(data)
    buffer = ctypes.create_string_buffer(raw, len(raw))
    blob = _DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _protect_once(data: bytes, flags: int) -> bytes:
    if not _is_windows():
        raise RuntimeError("Windows DPAPI is unavailable on this platform")
    crypt32, kernel32 = _win32_libraries()
    in_blob, keepalive = _blob_from_bytes(data)
    out_blob = _DATA_BLOB()
    ctypes.set_last_error(0)
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "JAMboreeLite SGS credentials",
        None,
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )
    _ = keepalive
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _dpapi_protect(data: bytes, *, preferred_scope: str = "user") -> tuple[bytes, str]:
    """Protect bytes with an explicit DPAPI scope policy.

    User scope is retained for compatibility/testing, but production fallback
    after a broken Credential Manager session requests machine scope directly.
    This avoids creating a blob that only the current transient logon state can
    later decrypt.
    """
    preferred = str(preferred_scope or "user").strip().lower()
    if preferred not in {"user", "machine"}:
        raise ValueError(f"unsupported DPAPI scope {preferred_scope!r}")
    if preferred == "machine":
        order = (("machine", _DPAPI_UI_FORBIDDEN | _DPAPI_LOCAL_MACHINE),)
    else:
        order = (
            ("user", _DPAPI_UI_FORBIDDEN),
            ("machine", _DPAPI_UI_FORBIDDEN | _DPAPI_LOCAL_MACHINE),
        )
    errors: list[str] = []
    for scope, flags in order:
        try:
            return _protect_once(data, flags), scope
        except Exception as exc:
            errors.append(f"{scope}: {exc}")
    raise RuntimeError("Windows DPAPI protection failed: " + "; ".join(errors))


def _dpapi_unprotect(data: bytes) -> bytes:
    if not _is_windows():
        raise RuntimeError("Windows DPAPI is unavailable on this platform")
    crypt32, kernel32 = _win32_libraries()
    in_blob, keepalive = _blob_from_bytes(data)
    out_blob = _DATA_BLOB()
    ctypes.set_last_error(0)
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        _DPAPI_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    _ = keepalive
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _read_dpapi_document(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"version": _DPAPI_VERSION, "records": {}}
    except Exception as exc:
        LOG.warning("failed to read DPAPI credential file %s: %s", path, exc)
        return {"version": _DPAPI_VERSION, "records": {}}
    try:
        doc = json.loads(raw)
    except Exception as exc:
        LOG.warning("invalid DPAPI credential file %s: %s", path, exc)
        return {"version": _DPAPI_VERSION, "records": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("records", {}), dict):
        LOG.warning("invalid DPAPI credential document structure in %s", path)
        return {"version": _DPAPI_VERSION, "records": {}}
    doc.setdefault("version", _DPAPI_VERSION)
    doc.setdefault("records", {})
    return doc


def _write_dpapi_document(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(doc, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_name, 0o600)
        except OSError:
            pass
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


def _store_dpapi_credentials(
    alias: str,
    username: str,
    password: str,
    *,
    preferred_scope: str = "user",
) -> Optional[str]:
    if not _is_windows():
        return None
    plaintext = json.dumps(
        {"username": str(username), "password": str(password)},
        separators=(",", ":"),
    ).encode("utf-8")
    protected, scope = _dpapi_protect(plaintext, preferred_scope=preferred_scope)
    with _DPAPI_LOCK:
        path = _credential_path()
        doc = _read_dpapi_document(path)
        doc["version"] = _DPAPI_VERSION
        doc.setdefault("records", {})[str(alias)] = {
            "blob": base64.b64encode(protected).decode("ascii"),
            "scope": scope,
        }
        _write_dpapi_document(path, doc)
        _DPAPI_BAD_RECORDS.pop(str(alias), None)
    return f"windows-dpapi-{scope}"


def _get_dpapi_credentials(alias: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if not _is_windows():
        return None, None, None
    alias = str(alias)
    with _DPAPI_LOCK:
        record = (_read_dpapi_document(_credential_path()).get("records", {}) or {}).get(alias)
    if not isinstance(record, dict) or not record.get("blob"):
        return None, None, None
    blob_text = str(record["blob"])
    with _DPAPI_LOCK:
        if _DPAPI_BAD_RECORDS.get(alias) == blob_text:
            return None, None, None
    try:
        protected = base64.b64decode(blob_text, validate=True)
        payload = json.loads(_dpapi_unprotect(protected).decode("utf-8"))
        username, password = payload.get("username"), payload.get("password")
        if username and password:
            scope = str(record.get("scope") or "unknown")
            with _DPAPI_LOCK:
                _DPAPI_BAD_RECORDS.pop(alias, None)
            return str(username), str(password), f"windows-dpapi-{scope}"
    except Exception as exc:
        with _DPAPI_LOCK:
            first_failure = _DPAPI_BAD_RECORDS.get(alias) != blob_text
            _DPAPI_BAD_RECORDS[alias] = blob_text
        if first_failure:
            LOG.warning(
                "DPAPI credential record for %s is unreadable in this logon context; re-pair to replace it: %s",
                alias,
                exc,
            )
    return None, None, None


def _delete_dpapi_credentials(alias: str) -> bool:
    if not _is_windows():
        return True
    alias = str(alias)
    with _DPAPI_LOCK:
        path = _credential_path()
        doc = _read_dpapi_document(path)
        records = doc.setdefault("records", {})
        records.pop(alias, None)
        _DPAPI_BAD_RECORDS.pop(alias, None)
        _write_dpapi_document(path, doc)
    return True


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

        # Prefer the OS keyring. Verify readback because some Windows logon
        # sessions can write partially and then fail when the backend calls CredRead.
        if keyring is not None:
            try:
                user_key, pass_key = cls._keys(alias)
                keyring.set_password(cls.SERVICE_NAME, user_key, username)
                keyring.set_password(cls.SERVICE_NAME, pass_key, password)
                if (
                    keyring.get_password(cls.SERVICE_NAME, user_key) == username
                    and keyring.get_password(cls.SERVICE_NAME, pass_key) == password
                ):
                    return True
                LOG.warning("OS keyring readback verification failed for %s", alias)
            except Exception as exc:
                LOG.warning("OS keyring store failed for %s; trying secure fallback: %s", alias, exc)

        if _is_windows():
            try:
                # Reaching this block means the per-logon keyring was unavailable
                # or could not be read back. Bind fallback credentials to this
                # computer rather than to the same unreliable logon state.
                backend = _store_dpapi_credentials(
                    alias,
                    username,
                    password,
                    preferred_scope="machine",
                )
                if backend:
                    read_user, read_password, read_backend = _get_dpapi_credentials(alias)
                    if (read_user, read_password) == (username, password):
                        LOG.info(
                            "stored SGS credentials for %s using %s (verified as %s)",
                            alias,
                            backend,
                            read_backend,
                        )
                        return True
                LOG.error("DPAPI readback verification failed for %s", alias)
            except Exception as exc:
                LOG.error("secure Windows DPAPI credential persistence failed for %s: %s", alias, exc)

        LOG.error("no usable secure credential backend for %s", alias)
        return False

    @classmethod
    def _get_with_backend(
        cls, alias: str, base_dict: Optional[dict] = None
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        alias = str(alias).strip()
        if not alias:
            return None, None, None

        # Prefer a working DPAPI record once one exists. This avoids repeatedly
        # invoking Credential Manager in a logon session where CredRead fails.
        if _is_windows():
            username, password, backend = _get_dpapi_credentials(alias)
            if username and password:
                return username, password, backend

        if keyring is not None:
            try:
                user_key, pass_key = cls._keys(alias)
                username = keyring.get_password(cls.SERVICE_NAME, user_key)
                password = keyring.get_password(cls.SERVICE_NAME, pass_key)
                if username and password:
                    return str(username), str(password), "keyring"
            except Exception as exc:
                LOG.warning("OS keyring read failed for %s: %s", alias, exc)

        if os.getenv("JAMBOREE_ALLOW_PLAINTEXT_CREDENTIALS") == "1" and base_dict:
            entry = (base_dict.get("stbs", {}) or {}).get(alias, {}) or {}
            username, password = entry.get("lname"), entry.get("passwd")
            if username and password:
                LOG.warning("using opt-in plaintext SGS credential fallback for %s", alias)
                return str(username), str(password), "plaintext-opt-in"
        return None, None, None

    @classmethod
    def get_credentials(
        cls, alias: str, base_dict: Optional[dict] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        username, password, _backend = cls._get_with_backend(alias, base_dict)
        return username, password

    @classmethod
    def status(cls, alias: str, base_dict: Optional[dict] = None) -> dict:
        username, password, backend = cls._get_with_backend(alias, base_dict)
        stored = bool(username and password)
        secure = bool(stored and backend not in {None, "plaintext-opt-in"})
        return {
            "alias": str(alias),
            "stored": stored,
            "backend": backend if secure else None,
            "secure": secure,
            "username_present": bool(username),
            "password_present": bool(password),
        }

    @classmethod
    def has_stored_credentials(cls, alias: str, base_dict: Optional[dict] = None) -> bool:
        username, password = cls.get_credentials(alias, base_dict)
        return bool(username and password)

    @classmethod
    def clear_credentials(cls, alias: str) -> bool:
        keyring_ok = True
        if keyring is not None:
            for key in cls._keys(alias):
                try:
                    keyring.delete_password(cls.SERVICE_NAME, key)
                except Exception as exc:
                    # Missing values are harmless; backend failures are not.
                    if exc.__class__.__name__ != "PasswordDeleteError":
                        LOG.warning("failed to clear keyring value for %s: %s", alias, exc)
                        keyring_ok = False
        dpapi_ok = True
        try:
            dpapi_ok = _delete_dpapi_credentials(alias)
        except Exception as exc:
            LOG.warning("failed to clear DPAPI credential for %s: %s", alias, exc)
            dpapi_ok = False
        return bool(dpapi_ok and (keyring_ok or _is_windows()))