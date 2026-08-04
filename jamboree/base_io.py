"""Safe persistence primitives for JAMboree's ``base.txt`` configuration.

The configuration contains stable STB identity, mutable network data, DART wiring,
and (for backward compatibility) optional SGS credentials. Writes therefore must
be additive, atomic, and serialized across both threads and helper processes.
"""
from __future__ import annotations

import errno
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]
try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover
    msvcrt = None  # type: ignore[assignment]


class BaseFileError(RuntimeError):
    pass


class BaseFileCorruptError(BaseFileError):
    pass


PROTECTED_STB_FIELDS = (
    "lname", "passwd", "prod", "paired_ts", "pair_rid", "cid",
    "com_port", "remote", "mac",
)
_thread_lock = threading.RLock()


class _FileLock:
    def __init__(self, path: Path, timeout: float = 10.0):
        self.lock_path = Path(f"{path}.lock")
        self.timeout = max(float(timeout), 0.0)
        self._fh = None
        self._locked = False

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.lock_path, "a+b")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if os.name == "nt" and msvcrt is not None:
                    self._fh.seek(0)
                    if self._fh.read(1) == b"":
                        self._fh.seek(0); self._fh.write(b"0"); self._fh.flush()
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                elif fcntl is not None:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._locked = True
                return self
            except (OSError, IOError) as exc:
                retryable = getattr(exc, "errno", None) in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or os.name == "nt"
                if not retryable:
                    self._fh.close(); self._fh = None; raise
                if time.monotonic() >= deadline:
                    self._fh.close(); self._fh = None
                    raise TimeoutError(f"timed out locking {self.lock_path}") from exc
                time.sleep(0.05)

    def __exit__(self, *_exc):
        if self._fh is not None:
            try:
                if self._locked:
                    if os.name == "nt" and msvcrt is not None:
                        self._fh.seek(0); msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                    elif fcntl is not None:
                        fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close(); self._fh = None; self._locked = False
        return False


def _parse_document(text: str, source: Path) -> Dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BaseFileCorruptError(f"invalid JSON in {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise BaseFileCorruptError(f"{source} must contain a JSON object")
    if value.get("stbs") is not None and not isinstance(value["stbs"], dict):
        raise BaseFileCorruptError(f"{source}: 'stbs' must be an object")
    return value


def deep_merge(dst: Dict[str, Any], src: Mapping[str, Any]) -> Dict[str, Any]:
    for key, value in src.items():
        if key in dst and isinstance(dst[key], dict) and isinstance(value, Mapping):
            deep_merge(dst[key], value)
        else:
            dst[key] = value
    return dst


def read_document(path: Path) -> Dict[str, Any]:
    path = Path(path)
    primary_error: Optional[Exception] = None
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
            return _parse_document(text, path) if text.strip() else {}
        except (OSError, BaseFileCorruptError) as exc:
            primary_error = exc
    backup = Path(f"{path}.bak")
    if backup.is_file():
        try:
            text = backup.read_text(encoding="utf-8")
            return _parse_document(text, backup) if text.strip() else {}
        except (OSError, BaseFileCorruptError) as backup_error:
            raise BaseFileCorruptError(f"both {path} and {backup} are unreadable") from backup_error
    if primary_error is not None:
        raise BaseFileCorruptError(f"cannot recover corrupt {path}: no valid backup") from primary_error
    return {}


def _atomic_write(path: Path, payload: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try: os.unlink(tmp_name)
        except OSError: pass
        raise


def write_document(path: Path, document: Mapping[str, Any]) -> None:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    normalized = dict(document)
    _parse_document(json.dumps(normalized), path)
    payload = json.dumps(normalized, indent=4, ensure_ascii=False) + "\n"
    if path.is_file():
        try:
            current = path.read_text(encoding="utf-8"); _parse_document(current, path)
        except (OSError, BaseFileCorruptError):
            current = ""
        if current:
            _atomic_write(Path(f"{path}.bak"), current if current.endswith("\n") else current + "\n")
    _atomic_write(path, payload)


def merge_document(path: Path, patch: Mapping[str, Any]) -> Dict[str, Any]:
    with _thread_lock, _FileLock(path):
        document = read_document(path); deep_merge(document, patch); write_document(path, document); return document


def update_stb_fields(path: Path, alias: str, fields: Mapping[str, Any], *, create: bool = True) -> Dict[str, Any]:
    alias = str(alias).strip()
    if not alias: raise ValueError("alias is required")
    with _thread_lock, _FileLock(path):
        document = read_document(path); stbs = document.setdefault("stbs", {})
        if alias not in stbs:
            if not create: raise KeyError(f"alias {alias!r} not present in {path}")
            stbs[alias] = {}
        if not isinstance(stbs[alias], dict): raise BaseFileCorruptError(f"STB entry {alias!r} is not an object")
        deep_merge(stbs[alias], fields); write_document(path, document); return document


def replace_stb_table(path: Path, stbs: Mapping[str, Mapping[str, Any]], *, protect: Iterable[str] = PROTECTED_STB_FIELDS, allow_delete: bool = True) -> Dict[str, Any]:
    if not isinstance(stbs, Mapping): raise TypeError("stbs must be a mapping")
    protected = tuple(protect)
    with _thread_lock, _FileLock(path):
        document = read_document(path); previous = document.get("stbs", {}) or {}; merged: Dict[str, Any] = {}
        for raw_alias, raw_incoming in stbs.items():
            alias = str(raw_alias).strip()
            if not alias: raise ValueError("STB aliases may not be blank")
            if not isinstance(raw_incoming, Mapping): raise TypeError(f"STB entry {alias!r} must be a mapping")
            incoming = dict(raw_incoming); prior = dict(previous.get(alias, {}) or {}); entry = dict(prior); entry.update(incoming)
            for field in protected:
                if field not in incoming and field in prior: entry[field] = prior[field]
            merged[alias] = entry
        if not allow_delete:
            for alias, entry in previous.items(): merged.setdefault(alias, entry)
        document["stbs"] = merged; write_document(path, document); return document


def prune_aliases(path: Path, aliases: Iterable[str]) -> Dict[str, Any]:
    drop = {str(alias) for alias in aliases}
    with _thread_lock, _FileLock(path):
        document = read_document(path); stbs = document.get("stbs", {}) or {}
        for alias in drop: stbs.pop(alias, None)
        document["stbs"] = stbs; write_document(path, document); return document


def get_credentials(path: Path, alias: str) -> Optional[tuple[str, str]]:
    entry = (read_document(path).get("stbs", {}) or {}).get(str(alias)) or {}
    login, password = entry.get("lname"), entry.get("passwd")
    return (str(login), str(password)) if login and password else None
