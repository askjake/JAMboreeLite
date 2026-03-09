"""
Serial Bridge Module for JAMboreeLite

This module provides a high-level interface for serial communication with DART boards,
abstracting the complexity of button code translation and serial port management.

The bridge sits between the controller and the actual serial hardware, routing all
serial writes through the global serial_mgr singleton to ensure proper resource
management and prevent port conflicts.

Key Features:
- Button ID to code translation
- Automatic delay management for RF commands
- Quick-DART protocol support (explicit down/up)
- Legacy timed press support (Format A)
- Centralized serial port access through serial_mgr

Author: Jacob Montgomery
Date: 2025-2026
"""

import logging
import time
from typing import Optional, Dict, Any

from .commands import get_button_codes, get_button_number
from .serial_hub import serial_mgr  # Import from neutral hub to avoid circular dependencies


def _enqueue(alias_or_com: str, line: str) -> bool:
    """
    Enqueue a command to the serial manager for transmission.
    
    This internal helper function sends a line of text to the serial port identified
    by the alias or COM port string. It handles encoding and error logging.
    
    Args:
        alias_or_com: Either an STB alias (e.g., "Hopper-01") or direct COM port (e.g., "/dev/ttyACM2")
        line: The command string to send (will be encoded to bytes)
    
    Returns:
        bool: True if enqueued successfully, False if serial write failed
    
    Example:
        >>> _enqueue("Hopper-01", "1 9 down\\n")
        True
    
    Note:
        - Logs a warning if enqueue fails
        - The serial_mgr handles the actual transmission asynchronously
        - Failures are typically due to port not open or buffer full
    """
    ok = serial_mgr.write(alias_or_com, line.encode())
    if not ok:
        logging.warning("serial write enqueue failed for %s (%r)", alias_or_com, line.strip())
    return ok


def send_rf(alias_or_com: str, remote_num: str, button_id: str, delay_ms: int) -> str:
    """
    Send a timed RF button press command (legacy Format A).
    
    This function sends a command in the format: "<remote> <key_cmd> <key_release> <delay_ms>"
    The Arduino DART board will press the button, hold for the specified duration, then release.
    
    Args:
        alias_or_com: STB alias or COM port identifier
        remote_num: Remote number (1-16) as string
        button_id: Button identifier (e.g., "Enter", "Guide", "ChannelUp")
        delay_ms: Duration to hold button in milliseconds (minimum 80ms)
    
    Returns:
        str: The formatted command string that was sent (without newline)
    
    Raises:
        ValueError: If button_id is not recognized in the button mapping
    
    Example:
        >>> send_rf("Hopper-01", "1", "Enter", 100)
        '1 9 19 100'
        # Sends: remote 1, press button 9 (Enter), release with code 19, hold 100ms
    
    Note:
        - Automatically enforces minimum delay of 80ms for reliable operation
        - Adds 50ms buffer sleep after sending for command processing
        - Uses button code lookup from commands.py (KEY_CMD and KEY_RELEASE)
        - Format A is the legacy timed press method (single command)
    """
    # Ensure minimum delay for reliable operation
    delay_ms = max(int(delay_ms), 80)
    
    # Translate button ID to command codes
    codes = get_button_codes(button_id)
    if not codes:
        raise ValueError(f"Unknown button_id '{button_id}'")
    
    # Format: <remote> <key_cmd> <key_release> <delay_ms>
    line = f"{remote_num} {codes['KEY_CMD']} {codes['KEY_RELEASE']} {delay_ms}\n"
    
    # Send to serial port
    _enqueue(alias_or_com, line)
    
    # Wait for command completion (delay + buffer)
    time.sleep((delay_ms + 50) / 1000.0)
    
    # Log the command for debugging
    logging.debug("→ [%s] %s", alias_or_com, line.strip())
    
    return line.strip()


def send_quick_dart(alias_or_com: str, remote_num: str, button_id: str, action: str) -> str:
    """
    Send a Quick-DART command with explicit button state control.
    
    Quick-DART (Format B) provides precise button control by sending separate "down"
    and "up" commands. This enables:
    - Button holds of arbitrary duration
    - Button chords (multiple buttons pressed simultaneously)
    - Precise timing for pairing sequences
    
    Args:
        alias_or_com: STB alias or COM port identifier
        remote_num: Remote number (1-16) as string
        button_id: Button identifier or special command ("allup", "reset")
        action: One of:
            - "down": Press button (does not release)
            - "up": Release button
            - "allup": Release all buttons
            - "reset": Trigger remote reset
    
    Returns:
        str: The formatted command string that was sent (without newline)
    
    Raises:
        ValueError: If button_id is not recognized
    
    Example:
        >>> # Press and hold Enter
        >>> send_quick_dart("Hopper-01", "1", "Enter", "down")
        '1 9 down'
        
        >>> # Release Enter after some time
        >>> import time; time.sleep(2.0)
        >>> send_quick_dart("Hopper-01", "1", "Enter", "up")
        '1 9 up'
        
        >>> # Button chord example (SAT + Guide for pairing)
        >>> send_quick_dart("Hopper-01", "1", "SAT", "down")
        >>> send_quick_dart("Hopper-01", "1", "Guide", "down")
        >>> time.sleep(3.0)  # Hold both for 3 seconds
        >>> send_quick_dart("Hopper-01", "1", "SAT", "up")
        >>> send_quick_dart("Hopper-01", "1", "Guide", "up")
    
    Note:
        - Format B command structure: "<remote> <button_num> <action>"
        - Uses button number lookup from commands.py
        - No automatic delays - caller controls timing
        - Special commands (allup, reset) are passed through as-is
        - Ideal for Arduino Nano Every Quick-DART firmware
    """
    # Translate button ID to button number
    num = get_button_number(button_id)
    if not num:
        raise ValueError(f"Unknown button_id '{button_id}'")
    
    # Format: <remote> <button_num> <action>
    line = f"{remote_num} {num} {action}\n"
    
    # Send to serial port
    _enqueue(alias_or_com, line)
    
    # Log the command for debugging
    logging.debug("→ [%s] %s", alias_or_com, line.strip())
    
    return line.strip()
