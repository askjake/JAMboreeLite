# jamboree/routes_sgs.py
import logging
from flask import Blueprint, request, jsonify
from types import SimpleNamespace
from .sgs_lib import (
    STB, resolve_sgs_ip, sgs_load_base, sgs_save_base
)
from .stb_store import store        # ← NEW
bp_sgs = Blueprint("sgs", __name__, url_prefix="/sgs")

# helper --------------------------------------------------------------
def _stub(data):
    """Minimal Namespace for STB() that skips base-file look-ups."""
    return SimpleNamespace(
        name=None,
        stb   = data.get("stb"),
        ip    = data.get("ip"),
        port  = 80,            # ← *** force the no-auth endpoint port ***
        prod  = False,         # stay False – we call query_noauth manually
        login = None,
        passwd= None,
        verbose=False
    )

# -------------------------------------------------------------------- #
@bp_sgs.post("/pair/start")
def pair_start():
    data = request.get_json(force=True) or {}
    logging.debug("pair_start called with raw payload: %s", data)

    alias = data.get("alias")  # new in UI; falls back to IP if absent
    if alias:
        try:
            resolved_ip = resolve_sgs_ip(alias)
            data["ip"] = resolved_ip
            logging.debug("Resolved alias '%s' → IP '%s'", alias, resolved_ip)
        except KeyError as e:
            logging.error("resolve_sgs_ip error: %s", e)
            return jsonify(ok=False, msg=str(e)), 400

    if not data.get("ip") or not data.get("stb"):
        logging.warning("Missing ip/stb (or alias) in request: %s", data)
        return jsonify(ok=False, msg="ip/stb (or alias) required"), 400

    logging.debug("Creating STB stub with data: %s", data)
    try:
        box = STB(args=_stub(data), prod=False)
    except SystemExit:
        logging.error("Failed to construct STB() with IP '%s'", data.get("ip"))
        return jsonify(ok=False, msg="bad IP"), 400

    payload = {
        "command": "device_pairing_start",
        "receiver": box.rid,  # third-party unique ID (per §3.1.1)
        "stb": box.stb,  # the STB’s CAID, e.g. "R1971825176-96"
        "mac": box.mac,  # device MAC in lowercase hex
        "name": "JAMboreeLite",  # friendly device name
        "type": "web",  # device type
        "app": "JAMboreeLite",  # application name
        "id": "S9"  # EchoStar-assigned App ID
    }

    logging.debug("pair_start payload: %s", payload)

    resp = box.query_noauth(payload)
    logging.debug("pair_start response: %s", resp)

    ok = resp and resp.get("result") == 1
    status_code = 200 if ok else 500
    logging.info("pair_start result for alias='%s': %s", alias or data.get("ip"), ok)

    return jsonify(ok=ok, msg=None if ok else resp), status_code

# -------------------------------------------------------------------- #

def _find_alias(data: dict) -> str | None:
    ip  = data.get("ip")
    stb = data.get("stb")
    for alias_key, info in store.all().items():
        if ip  and info.get("ip")  == ip:
            return alias_key
        if stb and info.get("stb") == stb:
            return alias_key
    return None
@bp_sgs.post("/pair/complete")
def pair_complete():
    data = request.get_json(force=True) or {}
    logging.debug("pair_complete called with raw payload: %s", data)

    alias = data.get("alias") or _find_alias(data)
    if alias:
        try:
            resolved_ip = resolve_sgs_ip(alias)
            data["ip"] = resolved_ip
            logging.debug("Resolved alias '%s' → IP '%s' for complete", alias, resolved_ip)
        except KeyError as e:
            logging.error("resolve_sgs_ip error (complete): %s", e)
            return jsonify(ok=False, msg=str(e)), 400

    pin = data.get("pin")
    if not pin:  # 6-digit in Sling SGS
        logging.warning("Missing pin in pair_complete: %s", data)
        return jsonify(ok=False, msg="missing pin"), 400

    if not data.get("ip") or not data.get("stb"):
        logging.warning("Missing ip/stb in pair_complete: %s", data)
        return jsonify(ok=False, msg="ip/stb (or alias) required"), 400

    logging.debug("Creating STB stub for complete with data: %s", data)
    try:
        box = STB(args=_stub(data), prod=False)
    except SystemExit:
        logging.error("Failed to construct STB() in pair_complete for IP '%s'", data.get("ip"))
        return jsonify(ok=False, msg="bad IP"), 400

    payload = {
        "command" : "device_pairing_complete",
        "pin"     : pin,
        "receiver": box.rid,
        "stb"     : box.stb,
        "app"     : "JAMboreeLite",
        "name"    : "JAMboreeLite",
        "type"    : "web",
        "id"      : "S9",
        "mac"     : box.mac
    }
    logging.debug("pair_complete payload: %s", payload)

    resp = box.query_noauth(payload)
    logging.debug("pair_complete response: %s", resp)

    ok = resp and resp.get("result") == 1
    if ok:
        try:
            base = sgs_load_base()
            logging.debug("Loaded base.txt to store pairing creds")

            # always write creds to the Hopper row
            hopper_alias = store.get(alias)["host"] if alias else None
            for alias_key, info in base.get("stbs", {}).items():
                if alias_key == hopper_alias:
                    info["lname"]  = resp["name"]
                    info["passwd"] = resp["passwd"]
                    sgs_save_base(base)
                    logging.info("Updated creds for Hopper '%s'", alias_key)
                    break
        except Exception as e:
            logging.error("Error saving to base.txt: %s", e)

    status_code = 200 if ok else 400
    logging.info("pair_complete result for alias='%s': %s", alias or data.get("ip"), ok)

    return jsonify(ok=ok, msg=None if ok else resp), status_code
