"""
Input validation and sanitization middleware for JAMboreeLite API.

Provides utilities to validate and sanitize user input to prevent
injection attacks and ensure data integrity.
"""

import re
import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


def sanitize_alias(alias: str) -> Optional[str]:
    """
    Sanitize STB alias input.
    
    Allows alphanumeric characters, hyphens, underscores, and periods.
    
    Args:
        alias: User-provided alias string
        
    Returns:
        Sanitized alias or None if invalid
    """
    if not alias or not isinstance(alias, str):
        return None
    
    # Allow alphanumeric, hyphen, underscore, period
    # Max length 100 characters
    if not re.match(r'^[a-zA-Z0-9_.-]{1,100}$', alias):
        logger.warning(f"Invalid alias format: {alias}")
        return None
    
    return alias


def sanitize_ip(ip: str) -> Optional[str]:
    """
    Sanitize and validate IP address.
    
    Args:
        ip: User-provided IP address
        
    Returns:
        Sanitized IP or None if invalid
    """
    if not ip or not isinstance(ip, str):
        return None
    
    # Basic IPv4 validation
    parts = ip.split('.')
    if len(parts) != 4:
        logger.warning(f"Invalid IP format: {ip}")
        return None
    
    try:
        for part in parts:
            num = int(part)
            if num < 0 or num > 255:
                logger.warning(f"Invalid IP range: {ip}")
                return None
    except ValueError:
        logger.warning(f"Invalid IP format: {ip}")
        return None
    
    return ip


def sanitize_button(button: str) -> Optional[str]:
    """
    Sanitize button identifier.
    
    Args:
        button: User-provided button identifier
        
    Returns:
        Sanitized button ID or None if invalid
    """
    if not button or not isinstance(button, str):
        return None
    
    # Allow alphanumeric and common button names
    # Max length 50 characters
    if not re.match(r'^[a-zA-Z0-9_-]{1,50}$', button):
        logger.warning(f"Invalid button format: {button}")
        return None
    
    return button.lower()


def sanitize_pin(pin: str) -> Optional[str]:
    """
    Sanitize pairing PIN.
    
    Args:
        pin: User-provided PIN (usually 6 digits)
        
    Returns:
        Sanitized PIN or None if invalid
    """
    if not pin or not isinstance(pin, str):
        return None
    
    # PINs are typically 4-8 digits
    if not re.match(r'^\d{4,8}$', pin):
        logger.warning("Invalid PIN format (must be 4-8 digits)")
        return None
    
    return pin


def sanitize_com_port(port: str) -> Optional[str]:
    """
    Sanitize COM port identifier.
    
    Args:
        port: User-provided COM port (e.g., "COM1", "/dev/ttyUSB0")
        
    Returns:
        Sanitized port or None if invalid
    """
    if not port or not isinstance(port, str):
        return None
    
    # Windows: COM1-COM999
    # Linux: /dev/ttyUSB0, /dev/ttyACM0, etc.
    if not re.match(r'^(COM\d{1,3}|/dev/tty[A-Za-z0-9]+)$', port):
        logger.warning(f"Invalid COM port format: {port}")
        return None
    
    return port


def validate_delay(delay: Any) -> Optional[int]:
    """
    Validate and sanitize delay value.
    
    Args:
        delay: User-provided delay (milliseconds)
        
    Returns:
        Integer delay or None if invalid
    """
    try:
        delay_int = int(delay)
        
        # Reasonable range: 0-30000 ms (30 seconds max)
        if delay_int < 0 or delay_int > 30000:
            logger.warning(f"Delay out of range: {delay_int}")
            return None
        
        return delay_int
    except (ValueError, TypeError):
        logger.warning(f"Invalid delay value: {delay}")
        return None


def validate_stb_data(data: dict) -> bool:
    """
    Validate STB configuration data structure.
    
    Args:
        data: STB configuration dictionary
        
    Returns:
        True if valid, False otherwise
    """
    if not isinstance(data, dict):
        return False
    
    required_fields = ['alias']
    
    for field in required_fields:
        if field not in data:
            logger.warning(f"Missing required field: {field}")
            return False
    
    # Validate specific fields if present
    if 'ip' in data and data['ip']:
        if not sanitize_ip(data['ip']):
            return False
    
    if 'com_port' in data and data['com_port']:
        if not sanitize_com_port(data['com_port']):
            return False
    
    return True
