# jamboree/app.py
import logging, socket, os
from flask import Flask, jsonify, send_from_directory, request, current_app

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] %(asctime)s - %(name)s - %(message)s'
)

from .paths import STATIC_DIR
from .stb_store import store
from .routes_sgs import bp_sgs
from .serial_hub import serial_mgr              # singleton SerialManager (no circulars)
from .controller import Controller              # safe import (serial_bridge imports serial_hub)

app = Flask(__name__, static_folder=str(STATIC_DIR))
app.register_blueprint(bp_sgs)

ctl = Controller()

def init_serial_from_base(base_dict: dict):
    """(Re)map aliases→COM and ensure exactly one worker per COM."""
    stbs = base_dict.get("stbs", base_dict) if isinstance(base_dict, dict) else {}
    started = 0
    for alias, info in stbs.items():
        com = (info or {}).get("com_port")
        if not com:
            continue
        serial_mgr.add_port(alias, com, baud=115200)
        started += 1
    logging.info("serial_mgr init: mapped %d alias(es) to COM(s)", started)

# -------- errors as JSON
@app.errorhandler(Exception)
def json_error(e):
    code = getattr(e, "code", 500)
    current_app.logger.exception(e)
    return jsonify(ok=False, msg=str(e)), code

# -------- pages
@app.route("/")
def remote_page():
    return send_from_directory(STATIC_DIR, "JAMboRemote.html")

@app.route("/settops")
def settops_page():
    return send_from_directory(STATIC_DIR, "settops.html")

# -------- helpers for UI
@app.route("/hostname")
def hostname():
    return jsonify({"hostname": socket.gethostname()})

@app.route("/get-stb-list")
def get_stb_list():
    return jsonify({"stbs": store.all()})

@app.route("/save-stb-list", methods=["POST"])
def save_stb_list():
    payload = request.json or {}
    store.save(payload)            # persist base.txt
    init_serial_from_base(payload) # hot-apply alias→COM map
    return jsonify({"success": True})

# -------- endpoints the UI expects (JAMboRemote)
@app.route("/auto/<remote>/<stb>/<button>/<int:delay>", methods=["GET"])
def auto_route(remote, stb, button, delay):
    return jsonify(ctl.handle_auto_remote(remote, stb, button, delay))

@app.route("/dart/<stb>/<button>/<action>", methods=["GET"])
def dart_route(stb, button, action):
    return jsonify(ctl.dart(stb, button, action))

@app.route("/unpair/<stb>", methods=["POST", "GET"])
def unpair_route(stb):
    return jsonify(ctl.unpair(stb))

@app.route("/whodis", methods=["POST", "GET"])
def whodis_route():
    # Easter egg endpoint used by JAMboRemote's "enhancement code"
    return jsonify({"result": "whoami=" + socket.gethostname()})

# -------- bootstrap from disk once
init_serial_from_base({"stbs": store.all()})

if __name__ == "__main__":
    # Prevent a second Flask process grabbing the same COM ports
    os.environ.setdefault("FLASK_ENV", "production")
    os.environ.setdefault("FLASK_RUN_FROM_CLI", "false")
    app.run(host="0.0.0.0", port=5003)
