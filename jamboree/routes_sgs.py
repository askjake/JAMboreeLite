# jamboree/routes_sgs.py
from flask import Blueprint, request, jsonify
from types import SimpleNamespace
from .sgs_lib import STB                 # relative import!
from .sgs_lib import sgs_load_base, sgs_save_base
bp_sgs = Blueprint("sgs", __name__, url_prefix="/sgs")

# helper --------------------------------------------------------------
def _stub(data):
    """Minimal Namespace for STB() that skips base-file look-ups."""
    return SimpleNamespace(
        name=None,
        stb = data.get("stb"),
        ip  = data.get("ip"),
        port= 80,            # ← *** force the no-auth endpoint port ***
        prod=False,          # stay False – we call query_noauth manually
        login=None, passwd=None, verbose=False
    )

# -------------------------------------------------------------------- #
@bp_sgs.post("/pair/start")
def pair_start():
    data = request.get_json(force=True) or {}
    if not data.get("ip") or not data.get("stb"):
        return jsonify(ok=False, msg="ip/stb required"), 400

    try:
        box  = STB(args=_stub(data), prod=False)
    except SystemExit:
        return jsonify(ok=False, msg="bad IP"), 400

    resp = box.query_noauth({
        "command":"device_pairing_start",
        "receiver":box.rid, "stb":box.stb,
        "app":"JAMboreeLite","name":"JAMboreeLite",
        "type":"web","id":"S9","mac":box.mac
    })
    ok = resp and resp.get("result") == 1


    return jsonify(ok=ok, msg=None if ok else resp), (200 if ok else 500)

# -------------------------------------------------------------------- #
@bp_sgs.post("/pair/complete")
def pair_complete():
    data = request.get_json(force=True) or {}
    pin  = data.get("pin")
    if not pin:  # 6-digit in Sling SGS
        return jsonify(ok=False, msg="missing pin"), 400

    try:
        box  = STB(args=_stub(data), prod=False)
    except SystemExit:
        return jsonify(ok=False, msg="bad IP"), 400

    resp = box.query_noauth({
        "command":"device_pairing_complete",
        "pin":pin,
        "receiver":box.rid, "stb":box.stb,
        "app":"JAMboreeLite","name":"JAMboreeLite",
        "type":"web","id":"S9","mac":box.mac
    })
    ok = resp and resp.get("result") == 1

    if ok:
        base = sgs_load_base()  # loads the dict from base.txt
        # find the matching entry by receiver ID & IP

        for alias, info in base.get("stbs", {}).items():

            if info.get("stb") == box.stb and info.get("ip") == data.get("ip"):
                    info["lname"] = resp["name"]
                    info["passwd"] = resp["passwd"]
                    sgs_save_base(base)  # writes base.txt back out
                    break
    return jsonify(ok=ok, msg=None if ok else resp), (200 if ok else 400)