# --- jamboree/app.py ---
"""Flask entry point – serve HTML & JSON APIs."""
import logging, socket, time, os
from flask import Flask, jsonify, send_from_directory, request, current_app

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s] %(asctime)s - %(name)s - %(message)s'
)

# Local imports
from .whodis import run as whodis_run
from jamboree.serial_bridge import _open  # legacy RF helper (pyserial direct)  # :contentReference[oaicite:3]{index=3}
from .paths import STATIC_DIR                                                 # :contentReference[oaicite:4]{index=4}
from .stb_store import store                                                  # :contentReference[oaicite:5]{index=5}
from .commands import get_button_codes                                        # :contentReference[oaicite:6]{index=6}
from .routes_sgs import bp_sgs

# IMPORTANT: create serial_mgr BEFORE importing Controller to avoid circular import
from serial_manager import SerialManager                                      # :contentReference[oaicite:7]{index=7}
serial_mgr = SerialManager()

from .controller import Controller                                            # :contentReference[oaicite:8]{index=8}

app = Flask(__name__, static_folder=str(STATIC_DIR))
app.register_blueprint(bp_sgs)

ctl = Controller()

def send_rf(port: str, remote_num: str, button_id: str, delay_ms: int):
    """Write KEY_CMD/RELEASE sequence to Arduino Nano Every running the DART sketch."""
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

def init_serial_from_base(base_dict: dict):
    """
    Start (or ensure) a SerialPortWorker per STB alias found in base.
    Accepts either the full base structure {'stbs': {...}} or just the stbs mapping.
    """
    # Handle both shapes
    stbs = base_dict.get("stbs", base_dict) if isinstance(base_dict, dict) else {}
    started = 0
    for alias, info in stbs.items():
        com = (info or {}).get("com_port")
        if not com:
            continue
        serial_mgr.add_port(alias, com, baud=115200)  # soft-heals on stalls
        started += 1
    logging.info("serial_mgr init: ensured workers for %d STB(s)", started)

# ---------- Global error → JSON
@app.errorhandler(Exception)
def json_error(e):
    code = getattr(e, "code", 500)
    current_app.logger.exception(e)
    return jsonify(ok=False, msg=str(e)), code

# ---------- Easter egg
@app.route("/whodis")
def whodis_route():
    out = whodis_run()
    return jsonify({"result": out})

# ---------- Pages
@app.route("/")
def remote_page():
    return send_from_directory(STATIC_DIR, "JAMboRemote.html")

@app.route("/settops")
def settops_page():
    return send_from_directory(STATIC_DIR, "settops.html")

# ---------- Helper JSON endpoints
@app.route("/hostname")
def hostname():
    return jsonify({"hostname": socket.gethostname()})

@app.route("/get-stb-list")
def get_stb_list():
    return jsonify({"stbs": store.all()})

@app.route("/save-stb-list", methods=["POST"])
def save_stb_list():
    """
    Persist the posted base.txt JSON *and* (re)seed serial workers so the change
    takes effect without restarting Flask.
    """
    payload = request.json or {}
    store.save(payload)                                # writes base.txt      :contentReference[oaicite:9]{index=9}
    init_serial_from_base(payload)                     # hot-apply serial map :contentReference[oaicite:10]{index=10}
    return jsonify({"success": True})

# ---------- Control APIs
@app.route("/auto/<remote>/<stb>/<button>/<int:delay>", methods=["GET"])
def auto_route(remote, stb, button, delay):
    try:
        return jsonify(ctl.handle_auto_remote(remote, stb, button, delay))
    except Exception as exc:
        logging.exception(exc)
        return jsonify({"error": str(exc)}), 500

@app.route("/dart/<stb>/<button>/<action>", methods=["GET"])
def dart_route(stb, button, action):
    try:
        return jsonify(ctl.dart(stb, button, action))
    except Exception as exc:
        logging.exception(exc)
        return jsonify({"error": str(exc)}), 500

@app.route("/unpair/<stb>", methods=["GET","POST"])
def unpair_route(stb):
    try:
        return jsonify(ctl.unpair(stb))
    except Exception as exc:
        logging.exception(exc)
        return jsonify({"error": str(exc)}), 500

# ---------- Bootstrap
# Seed serial workers from the current base.txt at startup.
# (store is constructed from disk in its module import)                   :contentReference[oaicite:11]{index=11}
init_serial_from_base({"stbs": store.all()})                               # :contentReference[oaicite:12]{index=12}

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="[%(levelname)s] %(asctime)s - %(message)s")
    os.environ.setdefault("FLASK_RUN_FROM_CLI", "false")
    app.run(host="0.0.0.0", port=5003)
