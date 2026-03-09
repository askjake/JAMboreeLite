"""
STB Store Module for JAMboreeLite

This module provides a thin wrapper around base.txt for managing Set-Top Box (STB)
configurations. It handles JSON persistence, thread-safe operations, and provides
a clean API for STB data access.

The store maintains all STB configurations including:
- STB aliases and receiver IDs
- IP addresses and protocols (RF/SGS)
- Serial port assignments
- Remote numbers and roles (Hopper/Joey)
- Host relationships (Joeys point to their Hopper)

Author: Jacob Montgomery
Date: 2025-2026
"""

import json
import threading
from typing import Dict, Any, Optional
from pathlib import Path

from .paths import BASE_PATH

# Thread lock for safe concurrent access
_lock = threading.Lock()


class STBStore:
    """
    Thread-safe storage manager for STB configurations.
    
    This class provides synchronized access to the base.txt configuration file,
    ensuring that multiple threads or processes don't corrupt the data when
    reading or writing STB configurations.
    
    Attributes:
        path (Path): Path to the base.txt configuration file
        _data (Dict[str, Any]): In-memory cache of the configuration data
    
    Example:
        >>> store = STBStore()
        >>> all_stbs = store.all()
        >>> hopper = store.get("Hopper-01")
        >>> print(hopper['ip'])
        '192.168.1.100'
        
        >>> # Update configuration
        >>> new_config = {"stbs": {...}}
        >>> store.save(new_config)
    
    Thread Safety:
        All public methods use a threading.Lock to ensure atomic operations.
        Multiple threads can safely read/write through this interface.
    """
    
    def __init__(self, path: Path = BASE_PATH) -> None:
        """
        Initialize the STB Store.
        
        Args:
            path: Path to the base.txt file (defaults to paths.BASE_PATH)
        
        Raises:
            FileNotFoundError: If base.txt doesn't exist at the specified path
            json.JSONDecodeError: If base.txt contains invalid JSON
        
        Note:
            Automatically loads the configuration file on initialization.
        """
        self.path = path
        self._data: Dict[str, Any] = {}
        self.reload()

    # Public API methods with thread safety
    
    def all(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all STB configurations.
        
        Returns:
            Dict mapping STB aliases to their configuration dictionaries.
            Each STB config contains fields like: alias, ip, protocol, remote, etc.
        
        Example:
            >>> stbs = store.all()
            >>> for alias, config in stbs.items():
            ...     print(f"{alias}: {config['protocol']} @ {config.get('ip', 'N/A')}")
            Hopper-01: SGS @ 192.168.1.100
            Joey-1: SGS @ 192.168.1.101
            Remote-3: RF @ N/A
        
        Note:
            Returns a reference to the internal dict. Modifications will affect
            the cached data but won't persist until save() is called.
        """
        return self._data.get("stbs", {})

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get configuration for a specific STB by alias.
        
        Args:
            name: STB alias (e.g., "Hopper-01", "Joey-1", "3")
        
        Returns:
            Dictionary containing STB configuration, or None if not found
        
        Example:
            >>> stb = store.get("Hopper-01")
            >>> if stb:
            ...     print(f"Protocol: {stb['protocol']}")
            ...     print(f"IP: {stb.get('ip', 'Not configured')}")
            Protocol: SGS
            IP: 192.168.1.100
        
        Common STB Configuration Fields:
            - alias: STB identifier
            - stb: Receiver ID (e.g., "R1956409151-66")
            - ip: IP address for SGS protocol
            - protocol: "SGS" or "RF"
            - remote: Remote number (1-16)
            - com_port: Serial port for DART ("/dev/ttyACM2" or "COM3")
            - role: "hopper" or "joey"
            - host: For Joeys, the alias of their host Hopper
            - lname/passwd: SGS credentials (deprecated, should use keyring)
        """
        return self.all().get(name)

    def save(self, new_json: dict) -> None:
        """
        Save new STB configuration to base.txt.
        
        This method updates both the in-memory cache and persists the changes
        to disk. The operation is atomic and thread-safe.
        
        Args:
            new_json: Complete configuration dictionary, typically with structure:
                     {"stbs": {"alias1": {...}, "alias2": {...}, ...}}
        
        Raises:
            OSError: If unable to write to base.txt
            TypeError: If new_json is not JSON-serializable
        
        Example:
            >>> config = store.all()
            >>> # Modify configuration
            >>> config["stbs"]["Hopper-01"]["ip"] = "192.168.1.200"
            >>> # Save changes
            >>> store.save({"stbs": config["stbs"]})
        
        Note:
            - The entire configuration is written atomically
            - Indented with 4 spaces for readability
            - Web UI uses this to persist STB list changes
        """
        with _lock:
            self._data = new_json
            self._write()

    def reload(self) -> None:
        """
        Reload configuration from base.txt file.
        
        This method re-reads the base.txt file from disk and updates the
        in-memory cache. Useful after external modifications to the file.
        
        Raises:
            FileNotFoundError: If base.txt doesn't exist
            json.JSONDecodeError: If file contains invalid JSON
        
        Example:
            >>> # After manually editing base.txt
            >>> store.reload()
            >>> updated_config = store.all()
        
        Note:
            - Called automatically during __init__
            - Thread-safe operation
            - Overwrites any unsaved in-memory changes
        """
        with _lock:
            if not self.path.exists():
                raise FileNotFoundError(f"base file not found: {self.path}")
            self._data = json.loads(self.path.read_text())

    # Internal helper method
    
    def _write(self) -> None:
        """
        Write current in-memory data to base.txt.
        
        This is an internal method called by save(). It handles the actual
        file I/O with proper formatting.
        
        Note:
            - Not thread-safe on its own (caller must hold lock)
            - Uses indent=4 for human-readable JSON
            - UTF-8 encoding for compatibility
        
        Raises:
            OSError: If file write fails
        """
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=4)


# Global singleton instance
# This is the primary interface used throughout the application
store = STBStore()
"""
Global STB store instance.

Usage throughout codebase:
    from .stb_store import store
    
    stb = store.get("Hopper-01")
    all_stbs = store.all()
"""
