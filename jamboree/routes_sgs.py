# routes_sgs.py
from flask import Blueprint, request, jsonify, current_app
from .sgs_lib import STB
from types   import SimpleNamespace

bp_sgs = Blueprint('sgs', __name__, url_prefix='/sgs')

@bp_sgs.post('/pair/start')
def pair_start():
    data = request.get_json() or {}
    # 1) instantiate without auto-pair in __init__ by prod=False
    stb = STB(args=None, prod=False)
    # 2) override IP / STB / PORT
    stb.ip   = data['ip']
    stb.stb  = data['stb']
    if 'port' in data:
        stb.port = int(data['port'])      # e.g. 8080 or 443

    # 3) call no-auth endpoint directly
    resp = stb.query_noauth({
      "command":  "device_pairing_start",
      "receiver": stb.rid,
      "stb":      stb.stb,
      "app":      "JAMboreeLite",
      "name":     "JAMboreeLite",
      "type":     "web",
      "id":       "S9",
      "mac":      stb.mac
    })
    ok = resp.get('result') == 1
    return jsonify(ok=ok, msg=None if ok else resp), (200 if ok else 500)


@bp_sgs.post('/pair/complete')
def pair_complete():
    data = request.get_json() or {}
    pin = data.get('pin')
    if not pin:
        return jsonify(ok=False, msg="missing pin"), 400

    # load saved credentials from base.txt
    from types import SimpleNamespace
    fake_args = SimpleNamespace(
      name=      None,
      stb=       data['stb'],
      ip=        data['ip'],
      port=      data.get('port'),
      prod=      True,
      login=     None,
      passwd=    None,
      verbose=   False
    )
    stb = STB(args=fake_args, prod=True)
    # now stb.login/stb.passwd came from base.txt,
    # so sgs_command will go down the secure path
    ok, _ = stb.sgs_command({
      "command":"device_pairing_complete",
      "pin":      pin,
      "stb":      stb.stb,
      "receiver": stb.rid,
      "app":"JAMboreeLite","name":"JAMboreeLite","type":"web","id":"S9",
      "mac":stb.mac
    })
    return jsonify(ok=ok, msg=None if ok else "bad-pin"), (200 if ok else 400)
