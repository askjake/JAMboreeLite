"""
Controller Module for JAMboreeLite

This module orchestrates RF, SGS, and DART logic for Flask routes, providing a unified
interface for controlling STBs (Set-Top Boxes) through various protocols.

The Controller class acts as the main coordinator between:
- Serial/DART communication for RF remotes
- SGS (Sling Gateway Service) for IP-based communication
- STB configuration management

Author: Jacob Montgomery
Date: 2025-2026
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Any

from .serial_bridge import send_rf, send_quick_dart
from .sgs_bridge import send_sgs
from .stb_store import store

# Default reset duration in milliseconds
RESET_DEFAULT_MS = 500


class Controller:
    """
    Main controller class for orchestrating STB remote control operations.
    
    This class provides a high-level interface for sending commands to STBs through
    various protocols (RF, SGS, DART). It handles special commands like reset and
    allup (release all buttons) uniformly across protocols.
    
    Attributes:
        None (stateless controller, relies on global store)
    
    Example:
        >>> controller = Controller()
        >>> result = controller.handle_auto_remote("1", "STB1", "Enter", 100)
        >>> print(result)
        {'rf_line': '1 9 down', 'ts': '2026-03-09T...'}
    """
    
    def __init__(self):
        """
        Initialize the Controller.
        
        Logs the number of STBs currently configured in the system. This constructor
        is lightweight as the controller is stateless and relies on the global store.
        
        Raises:
            ValueError: If store is not properly initialized
        """
        logging.info("Controller initialised – %d STBs", len(store.all()))

    # ------------------------------ Private Helper Methods ------------------------------
    
    def _per_remote_reset(self, stb_name: str) -> Dict[str, Any]:
        """
        Issue a per-remote reset through the DART line.
        
        This method sends a reset command that the Arduino DART board handles uniformly
        for the specified remote. The reset clears any stuck button states on that
        particular remote without affecting others.
        
        Args:
            stb_name: The alias/name of the STB to reset (e.g., "STB1", "Hopper-01")
        
        Returns:
            Dict containing:
                - reset_line (str): The formatted command sent to the serial port
                - ts (str): ISO 8601 timestamp of when the command was executed
        
        Raises:
            ValueError: If STB name not found in base.txt configuration
            
        Example:
            >>> controller._per_remote_reset("Hopper-01")
            {'reset_line': '1 reset 80', 'ts': '2026-03-09T10:30:00Z'}
        
        Note:
            The reset command format is: "<remote> reset 80" where 80ms is the
            duration for the Arduino to execute the reset sequence.
        """
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found in base.txt")
        
        remote = stb["remote"]
        # Format B: "<remote> 99 reset" → Arduino does per-remote reset
        # Using send_rf with reset command and 80ms duration
        sent = send_rf(stb_name, remote, "reset", "80")
        
        return {
            "reset_line": sent,
            "ts": datetime.now(timezone.utc).isoformat()
        }

    def _all_up(self, stb_name: str) -> Dict[str, Any]:
        """
        Release all pressed buttons on the specified remote.
        
        This is a safety command that ensures no buttons are stuck in the "pressed"
        state. Useful when a sequence of commands may have left buttons in an
        inconsistent state.
        
        Args:
            stb_name: The alias/name of the STB whose remote should release all buttons
        
        Returns:
            Dict containing:
                - allup_line (str): The formatted command sent ("allup")
                - ts (str): ISO 8601 timestamp of execution
        
        Raises:
            ValueError: If STB name not found in configuration
            
        Example:
            >>> controller._all_up("Joey-1")
            {'allup_line': '3 allup allup', 'ts': '2026-03-09T10:31:00Z'}
        
        Note:
            The Arduino DART sketch accepts either "<remote> 86 up" or 
            "<remote> any allup" formats. This uses the "allup" format.
        """
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found in base.txt")
        
        remote = stb["remote"]
        # Send "allup" command via DART - Arduino recognizes this as release-all
        sent = send_quick_dart(stb_name, remote, "allup", "allup")
        
        return {
            "allup_line": sent,
            "ts": datetime.now(timezone.utc).isoformat()
        }

    # ------------------------------ Public API Methods ------------------------------

    def handle_auto_remote(self, remote: str, stb_name: str, button_id: str, delay: int) -> Dict[str, Any]:
        """
        Handle automatic remote control commands (legacy AUTO path).
        
        This is the main entry point for remote control commands. It intelligently
        routes commands to either RF or SGS based on the STB's protocol configuration,
        and handles special commands (reset, allup) uniformly.
        
        Args:
            remote: Remote number/ID (e.g., "1", "2", "15")
            stb_name: STB alias from configuration (e.g., "Hopper-01", "Joey-1")
            button_id: Button identifier (e.g., "Enter", "Guide", "reset", "allup")
            delay: Duration in milliseconds for timed button press
        
        Returns:
            Dict containing command result and timestamp:
                - For RF: {'rf_line': str, 'ts': str}
                - For SGS: {'stdout': str, 'ts': str}
                - For special commands: {'reset_line': str, 'ts': str}
        
        Raises:
            ValueError: If STB not found or configuration invalid
            
        Example:
            >>> # Regular button press
            >>> controller.handle_auto_remote("1", "Hopper-01", "Enter", 100)
            {'rf_line': '1 9 down', 'ts': '2026-03-09T...'}
            
            >>> # Special reset command
            >>> controller.handle_auto_remote("1", "Hopper-01", "reset", 0)
            {'reset_line': '1 reset 80', 'ts': '2026-03-09T...'}
        
        Note:
            - Special commands (reset, allup) bypass normal protocol routing
            - SGS commands are converted to IP-based HTTP requests
            - RF commands are sent via serial/DART to Arduino board
        """
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found in base.txt")

        # Normalize button_id for special command detection
        bid = (button_id or "").lower()
        
        # Handle special commands that work across all protocols
        if bid in ("reset", "rst"):
            return self._per_remote_reset(stb_name)
        
        if bid in ("allup", "all_up", "release"):
            return self._all_up(stb_name)

        # Route to appropriate protocol handler
        if stb["protocol"].upper() == "SGS":
            return self.sgs_remote(stb_name, stb["ip"], stb["stb"], button_id, delay)

        # Default to RF via serial_mgr using the STB alias
        ack = send_rf(stb_name, remote, button_id, delay)
        return {
            "rf_line": ack,
            "ts": datetime.now(timezone.utc).isoformat()
        }

    def sgs_remote(self, stb_name: str, stb_ip: str, rxid: str, button_id: str, delay: int) -> Dict[str, Any]:
        """
        Send SGS (Sling Gateway Service) remote control command.
        
        This method sends button press commands to STBs that support the SGS protocol
        via HTTP/HTTPS. SGS is used for Hopper and Joey devices that are network-connected.
        
        Args:
            stb_name: STB alias for logging and identification
            stb_ip: IP address of the STB (or its host Hopper for Joeys)
            rxid: Receiver ID (e.g., "R1956409151-66")
            button_id: Button to press (e.g., "Enter", "Guide", "ChannelUp")
            delay: Duration of button press in milliseconds
        
        Returns:
            Dict containing:
                - stdout (str): Response from SGS command execution
                - ts (str): ISO 8601 timestamp
        
        Raises:
            ValueError: If SGS command fails or STB credentials not found
            
        Example:
            >>> controller.sgs_remote("Hopper-01", "192.168.1.100", 
            ...                       "R1956409151-66", "Guide", 200)
            {'stdout': '{"result": 1}', 'ts': '2026-03-09T...'}
        
        Note:
            - Requires STB to be paired (credentials in keyring or base.txt)
            - Joey commands are automatically routed through their host Hopper
            - Uses HTTPS with digest authentication when possible
        """
        resp = send_sgs(stb_name, stb_ip, rxid, button_id, delay)
        return {
            "stdout": resp,
            "ts": datetime.now(timezone.utc).isoformat()
        }

    def dart(self, stb_name: str, button_id: str, action: str) -> Dict[str, Any]:
        """
        Send DART (Direct Arduino Remote Trigger) command.
        
        DART provides precise button control with explicit down/up actions, allowing
        for button holds, chords (multiple buttons pressed simultaneously), and
        timing-critical sequences.
        
        Args:
            stb_name: STB alias from configuration
            button_id: Button identifier (ignored for reset/allup commands)
            action: One of:
                - "down": Press button down
                - "up": Release button
                - "reset": Per-remote reset (ignores button_id)
                - "allup": Release all buttons (ignores button_id)
                - numeric string: Milliseconds for timed press (legacy Format A)
        
        Returns:
            Dict containing:
                - dart_line (str): Command sent to Arduino
                - ts (str): ISO 8601 timestamp
        
        Raises:
            ValueError: If STB not found or action is invalid
            
        Example:
            >>> # Press and hold Guide button
            >>> controller.dart("Hopper-01", "Guide", "down")
            {'dart_line': '1 4 down', 'ts': '2026-03-09T...'}
            
            >>> # Release Guide button
            >>> controller.dart("Hopper-01", "Guide", "up")
            {'dart_line': '1 4 up', 'ts': '2026-03-09T...'}
            
            >>> # Button chord: can do down1, down2, up1, up2 sequence
            >>> controller.dart("Hopper-01", "DVR", "down")
            >>> controller.dart("Hopper-01", "Guide", "down")  # Both pressed
            >>> controller.dart("Hopper-01", "DVR", "up")
            >>> controller.dart("Hopper-01", "Guide", "up")
        
        Note:
            - Format supports Arduino Nano Every Quick-DART protocol
            - down/up commands enable precise timing control
            - Useful for pairing sequences and button combinations
        """
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found in base.txt")
        
        remote = stb["remote"]
        act = (action or "").lower()

        # Handle special commands
        if act == "reset":
            sent = send_rf(stb_name, remote, "reset", "80")
            return {
                "dart_line": sent,
                "ts": datetime.now(timezone.utc).isoformat()
            }

        if act in ("allup", "all_up", "release"):
            sent = send_quick_dart(stb_name, remote, "allup", "allup")
            return {
                "dart_line": sent,
                "ts": datetime.now(timezone.utc).isoformat()
            }

        # Handle explicit down/up actions (Quick-DART format)
        if act in ("down", "up"):
            sent = send_quick_dart(stb_name, remote, button_id, act)
            return {
                "dart_line": sent,
                "ts": datetime.now(timezone.utc).isoformat()
            }

        # Fallback: treat action as timed press duration (legacy Format A)
        try:
            ms = int(act)
            sent = send_rf(stb_name, remote, button_id, ms)
            return {
                "dart_line": sent,
                "ts": datetime.now(timezone.utc).isoformat()
            }
        except ValueError:
            raise ValueError(
                f"Unsupported DART action '{action}'. "
                f"Use 'down', 'up', 'reset', 'allup', or milliseconds (e.g., '100')"
            )

    def unpair(self, stb_name: str) -> Dict[str, Any]:
        """
        Execute the unpair sequence for a DISH remote.
        
        This performs the standard DISH unpair sequence:
        1. Hold SAT button for 3 seconds
        2. Press and hold DVR+Guide simultaneously for 3 seconds
        3. Release both buttons
        
        Args:
            stb_name: STB alias to unpair
        
        Returns:
            Dict containing:
                - unpaired (str): Name of unpaired STB
                - ts (str): Timestamp of completion
        
        Raises:
            ValueError: If STB not found
            
        Example:
            >>> controller.unpair("Hopper-01")
            {'unpaired': 'Hopper-01', 'ts': '2026-03-09T...'}
        
        Note:
            - Uses DART for precise timing control
            - Total sequence takes approximately 7 seconds
            - Remote LED will flash to indicate successful unpair
        """
        stb = store.get(stb_name)
        if not stb:
            raise ValueError(f"STB '{stb_name}' not found")
        
        remote = stb["remote"]

        # Step 1: Hold SAT button for 3+ seconds
        self.dart(stb_name, "sat", "down")
        time.sleep(3.10)
        self.dart(stb_name, "sat", "up")

        # Step 2: Wait briefly, then press DVR & Guide together
        time.sleep(0.20)
        self.dart(stb_name, "home", "down")  # Using 'home' as DVR equivalent
        time.sleep(0.1)
        self.dart(stb_name, "guide", "down")

        # Step 3: Hold for 3.5 seconds
        time.sleep(3.50)

        # Step 4: Release both buttons
        self.dart(stb_name, "home", "up")
        time.sleep(0.1)
        self.dart(stb_name, "guide", "up")

        return {
            "unpaired": stb_name,
            "ts": datetime.now(timezone.utc).isoformat()
        }
