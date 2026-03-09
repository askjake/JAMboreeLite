"""
JAMboreeLite Core Module

Provides secure credential management, logging configuration, and core utilities.

This module separates security-critical components from business logic.
"""

from .credentials import CredentialManager, get_stb_credentials, store_stb_credentials

__all__ = [
    'CredentialManager',
    'get_stb_credentials', 
    'store_stb_credentials',
]
