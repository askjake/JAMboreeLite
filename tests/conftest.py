from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path

BASE_DIR = Path(tempfile.mkdtemp(prefix="jamboree-tests-"))
BASE_PATH = BASE_DIR / "base.txt"
BASE_PATH.write_text(json.dumps({"stbs": {}}), encoding="utf-8")
os.environ["JAMBOREE_BASE"] = str(BASE_PATH)
os.environ.pop("JAMBOREE_ALLOW_PLAINTEXT_CREDENTIALS", None)

try:
    import serial  # noqa: F401
except ImportError:
    serial_mod = types.ModuleType("serial")

    class SerialException(Exception):
        pass

    class DummySerial:
        def __init__(self, port=None, **_kwargs):
            self.port = port
            self.is_open = True
            self.dtr = True
            self.writes = []

        def write(self, data):
            if not self.is_open:
                raise SerialException("closed")
            self.writes.append(bytes(data))
            return len(data)

        def flush(self):
            return None

        def readline(self):
            return b""

        def close(self):
            self.is_open = False

        def reset_input_buffer(self):
            return None

        def reset_output_buffer(self):
            return None

    serial_mod.Serial = DummySerial
    serial_mod.SerialException = SerialException
    serial_mod.VERSION = "stub"
    tools_mod = types.ModuleType("serial.tools")
    list_ports_mod = types.ModuleType("serial.tools.list_ports")
    list_ports_mod.comports = lambda: []
    tools_mod.list_ports = list_ports_mod
    serial_mod.tools = tools_mod
    sys.modules["serial"] = serial_mod
    sys.modules["serial.tools"] = tools_mod
    sys.modules["serial.tools.list_ports"] = list_ports_mod

try:
    import keyring  # noqa: F401
except ImportError:
    keyring_mod = types.ModuleType("keyring")
    _values = {}

    def set_password(service, key, value):
        _values[(service, key)] = value

    def get_password(service, key):
        return _values.get((service, key))

    def delete_password(service, key):
        if (service, key) not in _values:
            raise PasswordDeleteError(key)
        _values.pop((service, key))

    class PasswordDeleteError(Exception):
        pass

    errors = types.SimpleNamespace(PasswordDeleteError=PasswordDeleteError)
    keyring_mod.set_password = set_password
    keyring_mod.get_password = get_password
    keyring_mod.delete_password = delete_password
    keyring_mod.errors = errors
    sys.modules["keyring"] = keyring_mod
