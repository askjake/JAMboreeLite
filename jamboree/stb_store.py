"""Thread-safe configuration store backed by ``base.txt``.

``base.txt`` predates the explicit SGS topology fields used by the hardened
transport layer.  Some lab aliases therefore encode their host Hopper in the
alias (for example ``HOPPERPLUS-HOPPER3-PROD4``) or have a non-self ``host``
field while still carrying the legacy/default ``role=hopper`` value.

The persisted document remains untouched.  ``get()`` returns an *effective*
entry for runtime consumers so SGS pairing/transport code sees one consistent
child -> host relationship without forcing an operator migration first.
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

# These are receiver/client families which use a host Hopper for authenticated
# SGS.  Keep this intentionally narrow: topology inference only happens when an
# exact configured alias is also present as a suffix of the child alias.
_CHILD_ROLE_NAMES = {"joey", "hopperplus", "hopper_plus", "client"}
_CHILD_ALIAS_RE = re.compile(r"(?:^|[-_])(JOEY|MOCHAJOEY|HOPPERPLUS|HOPPER_PLUS)(?:[-_]|$)", re.I)


class STBStore:
    def __init__(self, path: object = BASE_PATH) -> None:
        self.path = Path(path)
        self._data: Dict[str, Any] = {}
        self.reload()

    def all(self) -> Dict[str, Dict[str, Any]]:
        return self._data.get("stbs", {})

    def _infer_legacy_host(self, name: str, entry: Mapping[str, Any]) -> Optional[str]:
        """Infer a host only for an obvious child alias and exact suffix match."""
        role = str(entry.get("role") or "").strip().lower()
        model = str(entry.get("model") or "")
        child_like = role in _CHILD_ROLE_NAMES or bool(_CHILD_ALIAS_RE.search(name)) or bool(
            _CHILD_ALIAS_RE.search(model)
        )
        if not child_like:
            return None

        upper_name = str(name).upper()
        candidates = []
        for alias in self.all():
            alias = str(alias).strip()
            if not alias or alias == name:
                continue
            # Require a separator before the exact configured host alias.  The
            # longest match wins if nested aliases exist.
            if upper_name.endswith("-" + alias.upper()) or upper_name.endswith("_" + alias.upper()):
                candidates.append(alias)
        if not candidates:
            return None
        return max(candidates, key=len)

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        raw = self.all().get(name)
        if raw is None:
            return None

        entry = raw
        alias = str(name).strip()
        role = str(raw.get("role") or "").strip().lower()
        explicit_host = str(raw.get("host") or raw.get("master_stb") or "").strip()

        # A non-self explicit host is authoritative even if a legacy row still
        # says role=hopper.  Existing SGS modules key off role=joey, so expose a
        # normalized effective role without rewriting base.txt.
        if explicit_host and explicit_host != alias:
            entry = copy.deepcopy(raw)
            entry["host"] = explicit_host
            entry["role"] = "joey"
            return entry

        if role in _CHILD_ROLE_NAMES:
            inferred = self._infer_legacy_host(alias, raw)
            if inferred:
                entry = copy.deepcopy(raw)
                entry["host"] = inferred
                entry["role"] = "joey"
                return entry

        # Legacy rows often have no role/host fields at all.  For known child
        # families, infer only when the alias ends with an exact configured
        # Hopper alias; otherwise leave the row untouched/fail closed.
        inferred = self._infer_legacy_host(alias, raw)
        if inferred:
            entry = copy.deepcopy(raw)
            entry["host"] = inferred
            entry["role"] = "joey"
            return entry

        return entry

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
