"""
Secure credential management for JAMboreeLite using OS keyring.

This module provides secure storage and retrieval of STB credentials using the
operating system's credential store (Windows Credential Manager, macOS Keychain,
Linux Secret Service).

Features:
- Secure credential storage via keyring
- Fallback to plaintext base.txt for backward compatibility
- Per-STB credential management (Hoppers have their own credentials)
- Joey routing (Joeys use their host Hopper's credentials)

Usage:
    from jamboree.core.credentials import CredentialManager
    
    # Store credentials after pairing
    CredentialManager.store_credentials("Hopper-01", "USER", "password123")
    
    # Retrieve credentials
    username, password = CredentialManager.get_credentials("Hopper-01")
    
    # Check if stored
    if CredentialManager.has_stored_credentials("Hopper-01"):
        print("Credentials found")
"""

import logging
from typing import Optional, Tuple

# Try to import keyring, but allow graceful fallback
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    logging.warning(
        "keyring module not available. Credentials will only be read from base.txt. "
        "Install keyring with: pip install keyring==24.2.0"
    )


class CredentialManager:
    """
    Manages STB credentials using OS keyring with fallback to base.txt.
    
    Service Name: JAMboreeLite
    Key Format: <alias>_username and <alias>_password
    
    Example keyring entries for "Hopper-01":
    - Service: JAMboreeLite, Key: Hopper-01_username, Value: USER
    - Service: JAMboreeLite, Key: Hopper-01_password, Value: secretpass
    """
    
    SERVICE_NAME = "JAMboreeLite"
    
    @staticmethod
    def store_credentials(alias: str, username: str, password: str) -> bool:
        """
        Store credentials securely in OS keyring.
        
        Args:
            alias: STB alias/name (e.g., "Hopper-01", "Joey-1")
            username: Authentication username (e.g., "USER")
            password: Authentication password
            
        Returns:
            True if stored successfully, False otherwise
        """
        if not KEYRING_AVAILABLE:
            logging.warning(
                f"Cannot store credentials for '{alias}': keyring module not available. "
                "Credentials should be manually added to base.txt with 'lname' and 'passwd' fields."
            )
            return False
        
        if not alias or not username or not password:
            logging.error("Cannot store credentials: alias, username, and password are required")
            return False
        
        try:
            username_key = f"{alias}_username"
            password_key = f"{alias}_password"
            
            keyring.set_password(CredentialManager.SERVICE_NAME, username_key, username)
            keyring.set_password(CredentialManager.SERVICE_NAME, password_key, password)
            
            logging.info(f"Successfully stored credentials for '{alias}' in OS keyring")
            return True
            
        except Exception as e:
            logging.error(f"Failed to store credentials for '{alias}' in keyring: {e}")
            return False
    
    @staticmethod
    def get_credentials(alias: str, base_dict: Optional[dict] = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Retrieve credentials from keyring, with fallback to base.txt.
        
        Args:
            alias: STB alias/name (e.g., "Hopper-01")
            base_dict: Optional base.txt data for fallback lookup
                      Expected format: {"stbs": {"alias": {"lname": "...", "passwd": "..."}}}
            
        Returns:
            Tuple of (username, password) or (None, None) if not found
        """
        if not alias:
            logging.error("Cannot retrieve credentials: alias is required")
            return None, None
        
        # Try keyring first (most secure)
        if KEYRING_AVAILABLE:
            try:
                username_key = f"{alias}_username"
                password_key = f"{alias}_password"
                
                username = keyring.get_password(CredentialManager.SERVICE_NAME, username_key)
                password = keyring.get_password(CredentialManager.SERVICE_NAME, password_key)
                
                if username and password:
                    logging.debug(f"Retrieved credentials for '{alias}' from keyring")
                    return username, password
                else:
                    logging.debug(f"No credentials found in keyring for '{alias}', trying fallback")
                    
            except Exception as e:
                logging.warning(f"Error reading from keyring for '{alias}': {e}, trying fallback")
        
        # Fallback to base.txt (backward compatibility)
        if base_dict:
            try:
                stbs = base_dict.get("stbs", {})
                stb_entry = stbs.get(alias, {})
                
                username = stb_entry.get("lname")
                password = stb_entry.get("passwd")
                
                if username and password:
                    logging.info(
                        f"Retrieved credentials for '{alias}' from base.txt (plaintext fallback). "
                        "Consider migrating to keyring for better security."
                    )
                    return username, password
                    
            except Exception as e:
                logging.error(f"Error reading credentials from base.txt for '{alias}': {e}")
        
        logging.debug(f"No credentials found for '{alias}' (checked keyring and base.txt)")
        return None, None
    
    @staticmethod
    def has_stored_credentials(alias: str, base_dict: Optional[dict] = None) -> bool:
        """
        Check if credentials exist for the given alias.
        
        Args:
            alias: STB alias/name
            base_dict: Optional base.txt data for fallback check
            
        Returns:
            True if credentials are found, False otherwise
        """
        username, password = CredentialManager.get_credentials(alias, base_dict)
        return username is not None and password is not None
    
    @staticmethod
    def clear_credentials(alias: str) -> bool:
        """
        Remove credentials from keyring.
        
        Note: This does NOT remove credentials from base.txt.
        
        Args:
            alias: STB alias/name
            
        Returns:
            True if cleared successfully, False otherwise
        """
        if not KEYRING_AVAILABLE:
            logging.warning(f"Cannot clear credentials for '{alias}': keyring module not available")
            return False
        
        if not alias:
            logging.error("Cannot clear credentials: alias is required")
            return False
        
        try:
            username_key = f"{alias}_username"
            password_key = f"{alias}_password"
            
            keyring.delete_password(CredentialManager.SERVICE_NAME, username_key)
            keyring.delete_password(CredentialManager.SERVICE_NAME, password_key)
            
            logging.info(f"Successfully cleared credentials for '{alias}' from keyring")
            return True
            
        except keyring.errors.PasswordDeleteError:
            logging.debug(f"No credentials found in keyring for '{alias}' (already cleared)")
            return True
            
        except Exception as e:
            logging.error(f"Failed to clear credentials for '{alias}': {e}")
            return False
    
    @staticmethod
    def migrate_from_base(base_dict: dict, remove_from_base: bool = False) -> dict:
        """
        Migrate credentials from base.txt to keyring.
        
        Args:
            base_dict: The loaded base.txt data structure
            remove_from_base: If True, remove 'lname' and 'passwd' from base_dict after migration
            
        Returns:
            Dictionary with migration results
        """
        if not KEYRING_AVAILABLE:
            logging.error("Cannot migrate credentials: keyring module not available")
            return {"migrated": [], "skipped": [], "failed": [], "error": "keyring not available"}
        
        results = {
            "migrated": [],
            "skipped": [],
            "failed": []
        }
        
        stbs = base_dict.get("stbs", {})
        
        for alias, stb_data in stbs.items():
            username = stb_data.get("lname")
            password = stb_data.get("passwd")
            
            if not username or not password:
                logging.debug(f"Skipping '{alias}': no credentials found")
                results["skipped"].append(alias)
                continue
            
            if CredentialManager.store_credentials(alias, username, password):
                results["migrated"].append(alias)
                
                # Optionally remove from base.txt
                if remove_from_base:
                    stb_data.pop("lname", None)
                    stb_data.pop("passwd", None)
                    logging.info(f"Removed plaintext credentials for '{alias}' from base.txt")
            else:
                results["failed"].append(alias)
        
        return results
