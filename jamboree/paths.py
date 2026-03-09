"""
Paths Module for JAMboreeLite

Centralized path configuration to ensure all modules agree on file locations.
This module uses environment variables for flexibility and provides Path objects
for all critical directories and files.

Environment Variables:
    JAMBOREE_BASE: Override path to base.txt configuration file

Author: Jacob Montgomery
Date: 2025-2026
"""

from pathlib import Path
import os

# Base configuration file path
# Can be overridden with JAMBOREE_BASE environment variable
BASE_ENV = os.getenv("JAMBOREE_BASE")
BASE_PATH = Path(BASE_ENV if BASE_ENV else Path.cwd() / "base.txt").resolve()
"""
Path to base.txt configuration file.

Default: ./base.txt (current working directory)
Override: Set JAMBOREE_BASE environment variable

Example:
    export JAMBOREE_BASE=/etc/jamboreelite/base.txt
    python -m jamboree.app
"""

# Package directory (where this file lives)
PACKAGE_DIR = Path(__file__).resolve().parent
"""
Path to the jamboree package directory.

This is the directory containing app.py, controller.py, etc.
Used for locating static files, certificates, and other package resources.
"""

# Static files directory for web UI
STATIC_DIR = PACKAGE_DIR / "static"
"""
Path to static web resources directory.

Contains:
    - JAMboRemote.html: Main remote control UI
    - settops.html: STB configuration UI  
    - Images and CSS files
"""
