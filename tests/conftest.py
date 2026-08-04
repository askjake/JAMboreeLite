from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).parents[1]))

# Minimal pyserial shim for source-unit tests in environments without hardware deps.
if "serial" not in sys.modules:
    serial = types.ModuleType("serial")
    class SerialException(Exception):
        pass
    class Serial:
        def __init__(self, *args, **kwargs):
            self.is_open = True
            self.port = kwargs.get("port")
        def close(self): self.is_open = False
        def write(self, data): return len(data)
        def flush(self): pass
        def readline(self): return b""
        def reset_input_buffer(self): pass
        def reset_output_buffer(self): pass
    serial.Serial = Serial
    serial.SerialException = SerialException
    tools = types.ModuleType("serial.tools")
    list_ports = types.ModuleType("serial.tools.list_ports")
    list_ports.comports = lambda: []
    tools.list_ports = list_ports
    sys.modules.update({"serial": serial, "serial.tools": tools, "serial.tools.list_ports": list_ports})
