# jamboree/serial_hub.py
"""
Holds the single SerialManager instance so app, controller, and serial_bridge
can all share it without circular imports.
"""
from .serial_manager import SerialManager

# One manager for the entire process
serial_mgr = SerialManager()
