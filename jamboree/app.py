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

# Import the shared serial manager from a neutral module (no circulars)
from .serial_hub import serial_mgr

from .controller import Controller  # safe now; serial_bridge won't import app

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

@app.errorhandler(Exception)
def json_error(e):
    code = getattr(e, "code", 500)
    current_app.logger.exception(e)
    return jsonify(ok=False, msg=str(e)), code

@app.route("/")
def remote_page():
    return send_from_directory(STATIC_DIR, "JAMboRemote.html")

@app.route("/settops")
def settops_page():
    return send_from_directory(STATIC_DIR, "settops.html")

@app.route("/hostname")
def hostname():
    return jsonify({"hostname": socket.gethostname()})

@app.route("/get-stb-list")
def get_stb_list():
    return jsonify({"stbs": store.all()})

@app.route("/save-stb-list", methods=["POST"])
def save_stb_list():
    payload = request.json or {}
    store.save(payload)            # persists base.txt
    init_serial_from_base(payload) # hot-apply alias→COM map
    return jsonify({"success": True})

# Bootstrap: seed from disk once (store loaded on import)
init_serial_from_base({"stbs": store.all()})

if __name__ == "__main__":
    # Prevent a second Flask process that would fight for COM ports
    os.environ.setdefault("FLASK_ENV", "production")
    os.environ.setdefault("FLASK_RUN_FROM_CLI", "false")
    app.run(host="0.0.0.0", port=5003)
