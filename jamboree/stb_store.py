"""Thread-safe configuration store backed by ``base.txt``.

``base.txt`` predates the explicit SGS topology fields used by the hardened
transport layer. Some older installs wrote a default ``host`` value onto many
otherwise-independent Hopper/XIP/Wally rows. Runtime topology therefore treats
host metadata as authoritative only for genuine child/client rows, while keeping
normal Hopper-family rows self-hosted unless their alias/model clearly identifies
a child receiver.

The persisted document remains untouched. ``get()`` returns an *effective*
entry for runtime consumers so pairing/transport behavior is corrected without
silently rewriting the operator's configuration.

The file may also be updated by another JAMboree process, recovery helper, or an
operator. A long-running server therefore tracks the file identity/timestamps
and transparently reloads external changes before serving configuration reads.
"""
from __future__ import annotations

import copy
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from . import base_io
from .paths import BASE_PATH

LOG = logging.getLogger(__name__)
_lock = threading.RLock()

# These receiver/client families use a host Hopper for authenticated SGS. Keep
# this intentionally narrow so stale/default host fields on ordinary rows do not
# turn independent receivers into children.
_CHILD_ROLE_NAMES = {"joey", "hopperplus", "hopper_plus", "client"}
_CHILD_ALIAS_RE = re.compile(
    r"(?:^|[-_])(JOEY|MOCHAJOEY|HOPPERPLUS|HOPPER_PLUS)(?:[-_]|$)", re.I
)


class STBStore:
    def __init__(self, path: object = BASE_PATH) -> None:
        self.path = Path(path)
        self._data: Dict[str, Any] = {}
        self._file_signature: Optional[tuple[int, int, int, int, int]] = None
        self._generation = 0
        self._external_reloads = 0
        self.reload()

    def _stat_signature(self) -> Optional[tuple[int, int, int, int, int]]:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return (
            int(getattr(stat, "st_dev", 0)),
            int(getattr(stat, "st_ino", 0)),
            int(stat.st_size),
            int(stat.st_mtime_ns),
            int(stat.st_ctime_ns),
        )

    def _read_locked(self) -> Dict[str, Any]:
        self._data = base_io.read_document(self.path)
        self._data.setdefault("stbs", {})
        self._file_signature = self._stat_signature()
        self._generation += 1
        return self._data

    def _record_local_write_locked(self, document: Dict[str, Any]) -> None:
        self._data = document
        self._data.setdefault("stbs", {})
        self._file_signature = self._stat_signature()
        self._generation += 1

    def _refresh_if_changed_locked(self, *, force: bool = False) -> bool:
        current = self._stat_signature()
        changed = current != self._file_signature
        if not force and not changed:
            return False
        previous = self._file_signature
        self._read_locked()
        if changed and previous is not None:
            self._external_reloads += 1
            LOG.info(
                "reloaded STB configuration after external file change path=%s generation=%d",
                self.path,
                self._generation,
            )
        return changed

    def refresh_if_changed(self, *, force: bool = False) -> bool:
        """Reload an externally modified ``base.txt`` without restarting Flask.

        Returns ``True`` only when the observed file signature changed. ``force``
        rereads the file even when metadata is unchanged; this is useful after a
        transport failure where another process may have just replaced the file.
        """
        with _lock:
            return self._refresh_if_changed_locked(force=force)

    def all(self) -> Dict[str, Dict[str, Any]]:
        with _lock:
            self._refresh_if_changed_locked()
            return self._data.get("stbs", {})

    @staticmethod
    def _validate_alias_table(stbs: Mapping[str, Any]) -> None:
        """Reject aliases that become ambiguous under case-insensitive clients."""
        seen: Dict[str, str] = {}
        for raw_alias in stbs:
            alias = str(raw_alias).strip()
            if not alias:
                raise ValueError("STB aliases may not be blank")
            folded = alias.casefold()
            prior = seen.get(folded)
            if prior is not None and prior != alias:
                raise ValueError(
                    "case-insensitive alias collision: "
                    f"{prior!r} conflicts with {alias!r}"
                )
            seen[folded] = alias

    def resolve_alias(self, name: str) -> Optional[str]:
        """Resolve one request spelling to the unique configured alias.

        Automation and historical clients are inconsistent about alias casing
        (for example ``HOPPER3-Prod`` versus ``HOPPER3-PROD``). Keep one
        canonical key in ``base.txt`` and accept a unique case-insensitive
        spelling at runtime. If the configuration itself contains two keys that
        differ only by case, fail closed instead of selecting the wrong receiver,
        credential record, or DART mapping.
        """
        requested = str(name or "").strip()
        if not requested:
            return None
        with _lock:
            self._refresh_if_changed_locked()
            stbs = self._data.get("stbs", {})
            folded = requested.casefold()
            matches = [
                str(alias)
                for alias in stbs
                if str(alias).strip().casefold() == folded
            ]
            if not matches:
                return None
            if len(matches) != 1:
                raise ValueError(
                    "case-insensitive alias collision for "
                    f"{requested!r}: {sorted(matches)!r}"
                )
            return matches[0]

    def _looks_like_child(self, name: str, entry: Mapping[str, Any]) -> bool:
        role = str(entry.get("role") or "").strip().lower()
        model = str(entry.get("model") or "")
        return (
            role in _CHILD_ROLE_NAMES
            or bool(entry.get("master_stb"))
            or bool(_CHILD_ALIAS_RE.search(str(name)))
            or bool(_CHILD_ALIAS_RE.search(model))
        )

    def _infer_legacy_host(
        self,
        name: str,
        entry: Mapping[str, Any],
        stbs: Optional[Mapping[str, Any]] = None,
    ) -> Optional[str]:
        """Infer a host only for an obvious child alias and exact suffix match."""
        if not self._looks_like_child(name, entry):
            return None

        upper_name = str(name).upper()
        candidates = []
        source = stbs if stbs is not None else self._data.get("stbs", {})
        for alias in source:
            alias = str(alias).strip()
            if not alias or alias == name:
                continue
            # Require a separator before the exact configured host alias. The
            # longest match wins if nested aliases exist.
            if upper_name.endswith("-" + alias.upper()) or upper_name.endswith(
                "_" + alias.upper()
            ):
                candidates.append(alias)
        if not candidates:
            return None
        return max(candidates, key=len)

    @staticmethod
    def _normalized_child(raw: Mapping[str, Any], host_alias: str) -> Dict[str, Any]:
        entry = copy.deepcopy(dict(raw))
        entry["host"] = host_alias
        entry["role"] = "joey"
        return entry

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        with _lock:
            self._refresh_if_changed_locked()
            stbs = self._data.get("stbs", {})
            raw = stbs.get(name)
            if raw is None:
                return None

            alias = str(name).strip()
            role = str(raw.get("role") or "").strip().lower()
            explicit_host = str(raw.get("host") or raw.get("master_stb") or "").strip()
            explicit_child_role = role in _CHILD_ROLE_NAMES or bool(raw.get("master_stb"))
            alias_child_like = bool(_CHILD_ALIAS_RE.search(alias)) or bool(
                _CHILD_ALIAS_RE.search(str(raw.get("model") or ""))
            )

            # Explicitly modelled Joey/client rows should honor their configured host.
            # This covers nested topologies such as a MoCA Joey whose saved host is a
            # HopperPlus alias.
            if explicit_child_role:
                if explicit_host and explicit_host != alias and explicit_host in stbs:
                    return self._normalized_child(raw, explicit_host)
                inferred = self._infer_legacy_host(alias, raw, stbs)
                if inferred:
                    return self._normalized_child(raw, inferred)
                return copy.deepcopy(raw)

            # Legacy child rows frequently still say role=hopper. Prefer an exact host
            # encoded in the alias over a stale/default host column. This is what
            # distinguishes HOPPERPLUS-HOPPER3-PROD4 from a generic host=HOPPER3 value.
            if alias_child_like:
                inferred = self._infer_legacy_host(alias, raw, stbs)
                if inferred:
                    return self._normalized_child(raw, inferred)
                if explicit_host and explicit_host != alias and explicit_host in stbs:
                    return self._normalized_child(raw, explicit_host)
                return copy.deepcopy(raw)

            # Old settops UIs could populate host=HOPPER3 on every row. For an ordinary
            # Hopper/Wally/XIP row that field is not topology; normalize the *runtime*
            # view back to self-hosting while leaving base.txt untouched.
            if explicit_host and explicit_host != alias:
                entry = copy.deepcopy(raw)
                entry["host"] = alias
                return entry

            return raw

    def document(self) -> Dict[str, Any]:
        with _lock:
            self._refresh_if_changed_locked()
            return copy.deepcopy(self._data)

    def status(self) -> Dict[str, Any]:
        """Return non-secret runtime/config continuity diagnostics."""
        with _lock:
            self._refresh_if_changed_locked()
            return {
                "path": str(self.path),
                "exists": self.path.is_file(),
                "generation": self._generation,
                "external_reloads": self._external_reloads,
                "stbs": len(self._data.get("stbs", {})),
            }

    def save(self, patch: Mapping[str, Any]) -> Dict[str, Any]:
        """Additively merge a partial document."""
        with _lock:
            document = base_io.merge_document(self.path, patch or {})
            self._record_local_write_locked(document)
            return copy.deepcopy(self._data)

    def update_stb(
        self, alias: str, fields: Mapping[str, Any], *, create: bool = True
    ) -> Dict[str, Any]:
        with _lock:
            requested = str(alias or "").strip()
            if not requested:
                raise ValueError("alias is required")
            # Reuse an existing configured key even when a caller uses a casing
            # variant. This prevents background recovery, pairing, or MAC-learning
            # writers from recreating duplicate logical STBs after request-side
            # canonicalization has resolved the alias.
            canonical = self.resolve_alias(requested)
            target_alias = canonical or requested
            document = base_io.update_stb_fields(
                self.path, target_alias, fields, create=create
            )
            self._record_local_write_locked(document)
            return copy.deepcopy(self._data)

    def replace_stbs(
        self,
        stbs: Mapping[str, Mapping[str, Any]],
        *,
        allow_delete: bool = True,
    ) -> Dict[str, Any]:
        with _lock:
            self._validate_alias_table(stbs)
            document = base_io.replace_stb_table(
                self.path, stbs, allow_delete=allow_delete
            )
            self._record_local_write_locked(document)
            return copy.deepcopy(self._data)

    def remove(self, aliases: Iterable[str]) -> Dict[str, Any]:
        with _lock:
            document = base_io.prune_aliases(self.path, aliases)
            self._record_local_write_locked(document)
            return copy.deepcopy(self._data)

    def reload(self) -> Dict[str, Any]:
        with _lock:
            self._read_locked()
            return copy.deepcopy(self._data)


store = STBStore()
