from __future__ import annotations

import cv2
import numpy as np

from jamboree import frame_provider


class Response:
    def __init__(self, *, content=b"", payload=None):
        self.content = content
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_http_frame_and_nested_abot_status(monkeypatch):
    image = np.zeros((12, 20, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok

    def fake_get(url, timeout):
        assert timeout == 2.0
        if url.endswith("snapshot.jpg"):
            return Response(content=encoded.tobytes())
        return Response(payload={"ok": True, "video": {"active": True, "signal_class": "active_video"}})

    import requests

    monkeypatch.setattr(requests, "get", fake_get)
    frame_provider.configure_http(
        "http://abot:8502/snapshot.jpg",
        "http://abot:8502/api/active-video",
        timeout_s=2.0,
    )
    frame = frame_provider.get_frame()
    status = frame_provider.get_status()
    assert frame.shape[:2] == (12, 20)
    assert status["active"] is True
    assert status["signal_class"] == "active_video"
