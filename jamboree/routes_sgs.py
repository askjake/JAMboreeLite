# routes_sgs.py
from flask import Blueprint, request, jsonify, current_app
from .sgs_lib import STB
from types   import SimpleNamespace

bp_sgs = Blueprint('sgs', __name__, url_prefix='/sgs')

@bp_sgs.post('/pair/start')
def pair_start():
    data = request.get_json() or {}
    try:
        # inject ip & stb into the args so __init__ sees them immediately
        fake_args = SimpleNamespace(
            name=None,
            stb=data.get('stb'),
            ip=data.get('ip'),
            port=None,
            prod=True,
            verbose=False,
            login=None,
            passwd=None
        )
        stb = STB(args=fake_args, prod=True)
        # device_pairing_start ---------
        ok, _ = stb.sgs_command({
            "command":"device_pairing_start",
            "stb": stb.stb,
            "receiver": stb.rid,
            "app":"JAMboreeLite","name":"JAMboreeLite","type":"web","id":"S9",
            "mac":stb.mac
        })
        return jsonify(ok=True) if ok else jsonify(ok=False,msg="start‑failed")
    except Exception as e:
        return jsonify(ok=False, msg=str(e)), 500

@bp_sgs.post('/pair/complete')
def pair_complete():
    data = request.get_json() or {}
    pin = data.get('pin')
    if not pin:
        return jsonify(ok=False, msg="missing pin"), 400

    try:
        # build args so that prod=False => query_unsecure => POST /sgs_noauth
        fake_args = SimpleNamespace(
            name=None,
            stb = data.get('stb'),
            ip  = data.get('ip'),
            port= None,
            prod=False,        # <= important: force unsecure path
            verbose=False,
            login=None,
            passwd=None
        )
        stb = STB(args=fake_args)  # defaults prod=False

        # now send the “complete pairing” to the no-auth endpoint
        result = stb.query_noauth({
            "command":  "device_pairing_complete",
            "pin":       pin,
            "stb":       stb.stb,
            "receiver":  stb.rid,
            "app":       "JAMboreeLite",
            "name":      "JAMboreeLite",
            "type":      "web",
            "id":        "S9",
            "mac":       stb.mac
        })

        # query_noauth returns the JSON dict directly
        if result and result.get("result") == 1:
            return jsonify(ok=True)
        else:
            return jsonify(ok=False, msg="bad-pin")

    except Exception as e:
        current_app.logger.exception("pair_complete")
        return jsonify(ok=False, msg=str(e)), 500