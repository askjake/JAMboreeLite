# --- jamboree/paths.py ---
"""Centralised paths so every module agrees on where `base.txt` lives."""
from pathlib import Path
import os

BASE_ENV = os.getenv("JAMBOREE_BASE")
BASE_PATH = Path(BASE_ENV if BASE_ENV else Path.cwd() / "base.txt").resolve()
PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"