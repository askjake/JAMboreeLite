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
"""
from __future__ import annotations

import copy
import re
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from . import base_io
from .paths import BASE_PATH

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
        self.reload()

    def all(self) -> Dict[str, Dict[str, Any]]:
        return self._data.get("stbs", {})

    def _looks_like_child(self, name: str, entry: Mapping[str, Any]) -> bool:
        role = str(entry.get("role") or "").strip().lower()
        model = str(entry.get("model") or "")
        return (
            role in _CHILD_ROLE_NAMES
            or bool(entry.get("master_stb"))
            or bool(_CHILD_ALIAS_RE.search(str(name)))
            or bool(_CHILD_ALIAS_RE.search(model))
        )

    def _infer_legacy_host(self, name: str, entry: Mapping[str, Any]) -> Optional[str]:
        """Infer a host only for an obvious child alias and exact suffix match."""
        if not self._looks_like_child(name, entry):
            return None

        upper_name = str(name).upper()
        candidates = []
        for alias in self.all():
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
        raw = self.all().get(name)
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
            if explicit_host and explicit_host != alias and explicit_host in self.all():
                return self._normalized_child(raw, explicit_host)
            inferred = self._infer_legacy_host(alias, raw)
            if inferred:
                return self._normalized_child(raw, inferred)
            return copy.deepcopy(raw)

        # Legacy child rows frequently still say role=hopper. Prefer an exact host
        # encoded in the alias over a stale/default host column. This is what
        # distinguishes HOPPERPLUS-HOPPER3-PROD4 from a generic host=HOPPER3 value.
        if alias_child_like:
            inferred = self._infer_legacy_host(alias, raw)
            if inferred:
                return self._normalized_child(raw, inferred)
            if explicit_host and explicit_host != alias and explicit_host in self.all():
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
        return copy.deepcopy(self._data)

    def save(self, patch: Mapping[str, Any]) -> Dict[str, Any]:
        """Additively merge a partial document."""
        with _lock:
            self._data = base_io.merge_document(self.path, patch or {})
            return self.document()

    def update_stb(
        self, alias: str, fields: Mapping[str, Any], *, create: bool = True
    ) -> Dict[str, Any]:
        with _lock:
            self._data = base_io.update_stb_fields(
                self.path, alias, fields, create=create
            )
            return self.document()

    def replace_stbs(
        self,
        stbs: Mapping[str, Mapping[str, Any]],
        *,
        allow_delete: bool = True,
    ) -> Dict[str, Any]:
        with _lock:
            self._data = base_io.replace_stb_table(
                self.path, stbs, allow_delete=allow_delete
            )
            return self.document()

    def remove(self, aliases: Iterable[str]) -> Dict[str, Any]:
        with _lock:
            self._data = base_io.prune_aliases(self.path, aliases)
            return self.document()

    def reload(self) -> Dict[str, Any]:
        with _lock:
            self._data = base_io.read_document(self.path)
            self._data.setdefault("stbs", {})
            return self.document()


store = STBStore()
