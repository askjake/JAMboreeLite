"""Centralized logging setup."""
from __future__ import annotations
import logging


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="[%(levelname)s] %(asctime)s %(name)s - %(message)s",
        )
    else:
        root.setLevel(level)
