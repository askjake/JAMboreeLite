"""Manual SGS pairing endpoints backed by the secure autopair implementation."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from . import sgs_autopair
from .stb_store import store

bp_sgs = Blueprint("sgs", __name__, url_prefix="/sgs")


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


@bp_sgs.post("/pair/start")
def pair_start():
    data = request.get_json(force=True, silent=False) or {}
    try:
        alias = _alias_from_payload(data)
        result = sgs_autopair.pair_start(alias)
        return jsonify(result), 200 if result.get("ok") else 502
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400


@bp_sgs.post("/pair/complete")
def pair_complete():
    data = request.get_json(force=True, silent=False) or {}
    try:
        alias = _alias_from_payload(data)
        result = sgs_autopair.pair_complete(alias, str(data.get("pin") or ""))
        return jsonify(result), 200 if result.get("ok") else 400
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
