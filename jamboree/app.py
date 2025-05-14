# --- jamboree/app.py ---
"""Flask entry point – serve HTML & JSON APIs."""
import logging, socket
import time

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] %(asctime)s - %(name)s - %(message)s'
)

from flask import Flask, jsonify, send_from_directory, request
from .whodis import run as whodis_run
from jamboree.serial_bridge import _open
from .paths import STATIC_DIR
from .controller import Controller
from .stb_store import store
from .commands import get_button_codes
from .routes_sgs import bp_sgs

app = Flask(__name__, static_folder=str(STATIC_DIR))
app.register_blueprint(bp_sgs)  # ← register it here, not after app.run()

ctl = Controller()

def send_rf(port: str, remote_num: str, button_id: str, delay_ms: int):
    """Write KEY_CMD/RELEASE sequence to Arduino Nano Every running the DART
    sketch you supplied.
    """
    delay_ms = max(int(delay_ms), 80)
    codes = get_button_codes(button_id)
    if not codes:
        raise ValueError(f"Unknown button_id {button_id}")
    line = f"{remote_num} {codes['KEY_CMD']} {codes['KEY_RELEASE']} {delay_ms}\n"
    ser = _open(port)
    ser.write(line.encode())
    ser.flush()
    time.sleep((delay_ms + 50) / 1000.0)
    return line.strip()




# app.py  (add right after app.register_blueprint(bp_sgs))
@app.errorhandler(Exception)
def json_error(e):
    code = getattr(e, "code", 500)
    current_app.logger.exception(e)        # see stack-trace in the console
    return jsonify(ok=False, msg=str(e)), code

# -------------------------- easter‑egg
@app.route("/whodis", methods=["POST"])
def whodis_route():
    out = whodis_run()
    return jsonify({"result": out})

# -------------------------- pages
@app.route("/")
def remote_page():
    return send_from_directory(STATIC_DIR, "JAMboRemote.html")

@app.route("/settops")
def settops_page():
    return send_from_directory(STATIC_DIR, "settops.html")

# -------------------------- helper JSON endpoints
@app.route("/hostname")
def hostname():
    return jsonify({"hostname": socket.gethostname()})

@app.route("/get-stb-list")
def get_stb_list():
    return jsonify({"stbs": store.all()})

@app.route("/save-stb-list", methods=["POST"])
def save_stb_list():
    store.save(request.json)
    return jsonify({"success": True})

# -------------------------- control APIs
@app.route("/auto/<remote>/<stb>/<button>/<int:delay>")
def auto_route(remote, stb, button, delay):
    try:
        return jsonify(ctl.handle_auto_remote(remote, stb, button, delay))
    except Exception as exc:
        logging.exception(exc)
        return jsonify({"error": str(exc)}), 500

@app.route("/dart/<stb>/<button>/<action>")
def dart_route(stb, button, action):
    try:
        return jsonify(ctl.dart(stb, button, action))
    except Exception as exc:
        logging.exception(exc)
        return jsonify({"error": str(exc)}), 500

@app.route("/unpair/<stb>", methods=["POST"])
def unpair_route(stb):
    try:
        return jsonify(ctl.unpair(stb))
    except Exception as exc:
        logging.exception(exc)
        return jsonify({"error": str(exc)}), 500


# -------------------------- main
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="[%(levelname)s] %(asctime)s - %(message)s")
    import os; os.environ.setdefault("FLASK_RUN_FROM_CLI", "false")
    app.run(host="0.0.0.0", port=5003)
