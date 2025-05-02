
# --- jamboree/stb_store.py ---
"""Thin wrapper around *base.txt* so code stays tidy."""
import json, threading
from typing import Dict, Any

from paths import BASE_PATH

_lock = threading.Lock()

class STBStore:
    def __init__(self, path=BASE_PATH):
        self.path = path
        self._data: Dict[str, Any] = {}
        self.reload()

    # public access -------------------------------------------------------
    def all(self):
        return self._data.get("stbs", {})

    def get(self, name: str):
        return self.all().get(name)

    def save(self, new_json: dict):
        with _lock:
            self._data = new_json
            self._write()

    def reload(self):
        with _lock:
            if not self.path.exists():
                raise FileNotFoundError(f"base file not found: {self.path}")
            self._data = json.loads(self.path.read_text())

    # internal ------------------------------------------------------------
    def _write(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=4)

store = STBStore()
