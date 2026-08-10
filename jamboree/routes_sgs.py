"""Manual SGS pairing endpoints backed by the secure autopair implementation."""
from __future__ import annotations

import json
import logging

from flask import Blueprint, jsonify, request

from . import sgs_autopair
from .stb_store import store

bp_sgs = Blueprint("sgs", __name__, url_prefix="/sgs")
LOG = logging.getLogger(__name__)
_SECRET_STB_FIELDS = {"lname", "passwd", "username", "password"}


def _alias_from_payload(data: dict) -> str:
    alias = str(data.get("alias") or "").strip()
    if alias:
        if not store.get(alias):
            raise ValueError(f"unknown STB alias {alias!r}")
        return alias
    matches = [
        name
        for name, info in store.all().items()
        if (data.get("stb") and info.get("stb") == data.get("stb"))
        or (data.get("ip") and info.get("ip") == data.get("ip"))
    ]
    if len(matches) != 1:
        raise ValueError("pairing requires an unambiguous configured alias")
    return matches[0]


def _failure_message(result: dict) -> str:
    """Return one safe, human-readable pairing failure reason."""
    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    for value in (
        result.get("error"),
        response.get("error"),
        response.get("detail"),
        response.get("msg"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    status = response.get("_http_status") or response.get("http_status")
    if status:
        return f"SGS pairing request failed (HTTP {status})"
    code = response.get("result")
    if code not in (None, 1):
        return f"SGS pairing request failed (result={code})"
    return "SGS pairing request failed"


def _decorate_failure(result: dict, *, alias: str, phase: str) -> dict:
    if result.get("ok"):
        return result
    message = _failure_message(result)
    result.setdefault("error", message)
    # Compatibility for the existing settops.html, which historically reads j.msg.
    result.setdefault("msg", message)
    LOG.warning(
        "SGS pair %s failed requested_alias=%s pair_alias=%s: %s",
        phase,
        alias,
        result.get("pair_alias"),
        message,
    )
    return result


@bp_sgs.after_app_request
def sanitize_stb_list_response(response):
    """Never serialize legacy credential fields through /get-stb-list."""
    if request.endpoint != "get_stb_list" or not response.is_json:
        return response
    data = response.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("stbs"), dict):
        return response
    public = {}
    for alias, entry in data["stbs"].items():
        if isinstance(entry, dict):
            public[alias] = {
                key: value
                for key, value in entry.items()
                if str(key).lower() not in _SECRET_STB_FIELDS
            }
        else:
            public[alias] = entry
    data["stbs"] = public
    response.set_data(json.dumps(data, separators=(",", ":")))
    response.content_type = "application/json"
    return response


@bp_sgs.get("/status")
def status():
    """Compatibility status endpoint; never exposes credentials."""
    return jsonify(ok=True, **sgs_autopair.get_status())


@bp_sgs.get("/credentials/status")
def credential_status():
    """Report pairing persistence metadata without returning secret values."""
    data = request.args.to_dict(flat=True)
    if not any(str(data.get(key) or "").strip() for key in ("alias", "stb", "ip")):
        return jsonify(ok=True, requires_alias=True, detail="Pass alias, stb, or ip for credential status")
    try:
        alias = _alias_from_payload(data)
        return jsonify(ok=True, **sgs_autopair.credentials_status(alias))
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400


@bp_sgs.post("/pair/start")
def pair_start():
    data = request.get_json(force=True, silent=False) or {}
    try:
        alias = _alias_from_payload(data)
        result = _decorate_failure(
            sgs_autopair.pair_start(alias), alias=alias, phase="start"
        )
        return jsonify(result), 200 if result.get("ok") else 502
    except ValueError as exc:
        message = str(exc)
        return jsonify(ok=False, error=message, msg=message), 400


@bp_sgs.post("/pair/complete")
def pair_complete():
    data = request.get_json(force=True, silent=False) or {}
    try:
        alias = _alias_from_payload(data)
        result = _decorate_failure(
            sgs_autopair.pair_complete(alias, str(data.get("pin") or "")),
            alias=alias,
            phase="complete",
        )
        return jsonify(result), 200 if result.get("ok") else 400
    except ValueError as exc:
        message = str(exc)
        return jsonify(ok=False, error=message, msg=message), 400
