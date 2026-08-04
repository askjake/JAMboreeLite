"""SGS pairing routes with Hopper-aware identity and secure persistence."""
from __future__ import annotations

import os
import re
from types import SimpleNamespace
from flask import Blueprint, jsonify, request

from .core.credentials import CredentialManager
from .sgs_lib import STB
from .stb_store import store

bp_sgs = Blueprint("sgs", __name__, url_prefix="/sgs")
_PIN_RE = re.compile(r"^\d{6}$")


def _resolve(data: dict) -> tuple[str, dict]:
    alias = str(data.get("alias") or "").strip()
    entry = store.get(alias) if alias else None
    if entry and str(entry.get("role", "hopper")).lower() == "joey":
        alias = str(entry.get("host") or "")
        entry = store.get(alias)
    if not entry:
        matches = [(name, info) for name, info in store.all().items() if (data.get("stb") and info.get("stb") == data.get("stb")) or (data.get("ip") and info.get("ip") == data.get("ip"))]
        if len(matches) != 1:
            raise ValueError("pairing requires an unambiguous configured Hopper alias")
        alias, entry = matches[0]
    return alias, entry


def _stub(ip: str, stb: str) -> SimpleNamespace:
    return SimpleNamespace(name=None, stb=stb, ip=ip, port=80, prod=False, login=None, passwd=None, verbose=False)


def _box(data: dict) -> tuple[str, STB]:
    alias, entry = _resolve(data)
    ip, stb = str(entry.get("ip") or ""), str(entry.get("stb") or "")
    if not ip or not stb:
        raise ValueError(f"Hopper {alias!r} requires ip and full RxID")
    try:
        return alias, STB(args=_stub(ip, stb), prod=False)
    except SystemExit as exc:
        raise ValueError("invalid Hopper pairing configuration") from exc


@bp_sgs.post("/pair/start")
def pair_start():
    data = request.get_json(force=True, silent=False) or {}
    try:
        alias, box = _box(data)
        payload = {"command": "device_pairing_start", "receiver": box.rid, "stb": box.stb, "mac": box.mac, "name": "JAMboreeLite", "type": "web", "app": "JAMboreeLite", "id": "S9"}
        response = box.query_noauth(payload)
        ok = bool(response and response.get("result") == 1)
        return jsonify(ok=ok, alias=alias, msg=None if ok else response), 200 if ok else 502
    except ValueError as exc:
        return jsonify(ok=False, msg=str(exc)), 400


@bp_sgs.post("/pair/complete")
def pair_complete():
    data = request.get_json(force=True, silent=False) or {}
    pin = str(data.get("pin") or "").strip()
    if not _PIN_RE.fullmatch(pin):
        return jsonify(ok=False, msg="pin must be exactly six digits"), 400
    try:
        alias, box = _box(data)
        payload = {"command": "device_pairing_complete", "pin": pin, "receiver": box.rid, "stb": box.stb, "app": "JAMboreeLite", "name": "JAMboreeLite", "type": "web", "id": "S9", "mac": box.mac}
        response = box.query_noauth(payload)
        ok = bool(response and response.get("result") == 1)
        if not ok:
            return jsonify(ok=False, alias=alias, msg=response), 400
        username, password = response.get("name"), response.get("passwd")
        if not CredentialManager.store_credentials(alias, username, password):
            return jsonify(ok=False, alias=alias, msg="paired, but secure credential persistence failed"), 500
        store.update_stb(alias, {"prod": True, "paired": True, "pair_rid": payload["receiver"]})
        if os.getenv("JAMBOREE_ALLOW_PLAINTEXT_CREDENTIALS") == "1":
            store.update_stb(alias, {"lname": username, "passwd": password})
        return jsonify(ok=True, alias=alias, msg=None), 200
    except ValueError as exc:
        return jsonify(ok=False, msg=str(exc)), 400
