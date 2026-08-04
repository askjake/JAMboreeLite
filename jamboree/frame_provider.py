"""Pluggable video-frame source used by OCR recovery and automatic pairing.

An application embedding JAMboree can inject local callables.  A standalone
JAMboree process can instead read aBotTesty's live frame/status endpoints using:

``JAMBOREE_FRAME_URL=http://host:8502/snapshot.jpg``
``JAMBOREE_FRAME_STATUS_URL=http://host:8502/api/active-video``
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, Optional

LOG = logging.getLogger(__name__)
_lock = threading.RLock()
_get_frame: Optional[Callable[[], Any]] = None
_get_status: Optional[Callable[[], Dict[str, Any]]] = None
_config: Dict[str, Any] = {}


def set_provider(
    *,
    get_frame: Optional[Callable[[], Any]] = None,
    get_status: Optional[Callable[[], Dict[str, Any]]] = None,
    description: str = "injected",
) -> None:
    global _get_frame, _get_status
    with _lock:
        if get_frame is not None:
            _get_frame = get_frame
        if get_status is not None:
            _get_status = get_status
        _config.update(description=description)


def _decode_jpeg(payload: bytes) -> Any:
    try:
        import cv2
        import numpy as np
    except Exception as exc:  # pragma: no cover - optional OCR install
        raise RuntimeError("OpenCV and NumPy are required to decode HTTP frames") from exc
    data = np.frombuffer(payload, dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None or not getattr(frame, "size", 0):
        raise RuntimeError("frame endpoint returned an invalid JPEG")
    return frame


def configure_http(
    frame_url: str,
    status_url: Optional[str] = None,
    *,
    timeout_s: float = 5.0,
) -> None:
    import requests

    frame_url = str(frame_url).strip()
    status_url = str(status_url or "").strip() or None
    if not frame_url:
        raise ValueError("frame_url is required")

    def http_frame() -> Any:
        response = requests.get(frame_url, timeout=timeout_s)
        response.raise_for_status()
        return _decode_jpeg(response.content)

    def http_status() -> Dict[str, Any]:
        if not status_url:
            return {"active": True, "source": frame_url}
        try:
            response = requests.get(status_url, timeout=timeout_s)
            response.raise_for_status()
            value = response.json()
            if isinstance(value, dict) and isinstance(value.get("video"), dict):
                value = value["video"]
            return dict(value) if isinstance(value, dict) else {"active": False}
        except Exception as exc:
            return {"active": False, "error": str(exc), "source": status_url}

    set_provider(
        get_frame=http_frame,
        get_status=http_status,
        description="http",
    )
    with _lock:
        _config.update(
            frame_url=frame_url,
            status_url=status_url,
            timeout_s=float(timeout_s),
        )


def configure_from_env() -> bool:
    frame_url = os.getenv("JAMBOREE_FRAME_URL", "").strip()
    if not frame_url:
        return False
    status_url = os.getenv("JAMBOREE_FRAME_STATUS_URL", "").strip() or None
    timeout = float(os.getenv("JAMBOREE_FRAME_TIMEOUT_S", "5"))
    configure_http(frame_url, status_url, timeout_s=timeout)
    LOG.info("configured HTTP frame provider: %s", frame_url)
    return True


def get_frame() -> Any:
    with _lock:
        provider = _get_frame
    if provider is None:
        return None
    try:
        return provider()
    except Exception as exc:
        LOG.warning("frame provider failed: %s", exc)
        return None


def get_status() -> Dict[str, Any]:
    with _lock:
        provider = _get_status
        config = dict(_config)
    if provider is None:
        return {"active": False, "configured": False, **config}
    try:
        value = provider() or {}
        if isinstance(value, dict) and isinstance(value.get("video"), dict):
            value = value["video"]
        return {"configured": True, **dict(value), **config}
    except Exception as exc:
        return {"active": False, "configured": True, "error": str(exc), **config}


def status() -> Dict[str, Any]:
    value = get_status()
    value.setdefault("configured", _get_frame is not None)
    return value
