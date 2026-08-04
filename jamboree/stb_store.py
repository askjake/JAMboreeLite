"""Thread-safe configuration store backed by ``base.txt``."""
from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from . import base_io
from .paths import BASE_PATH

_lock = threading.RLock()


class STBStore:
    def __init__(self, path: object = BASE_PATH) -> None:
        self.path = Path(path)
        self._data: Dict[str, Any] = {}
        self.reload()

    def all(self) -> Dict[str, Dict[str, Any]]:
        return self._data.get("stbs", {})

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self.all().get(name)

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
