"""JAMboreeLite Flask service with SGS recovery, autopair, and DART fallback."""
from __future__ import annotations

import atexit
import logging
import os
import socket
from collections.abc import Mapping

from flask import Flask, current_app, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import frame_provider, ip_recovery, sgs_autopair
from .controller import Controller
from .core.logging_config import setup_logging
from .paths import STATIC_DIR
from .routes_recovery import bp_recovery, set_controller
from .routes_sgs import bp_sgs
from .serial_hub import serial_mgr
from .stb_store import store

setup_logging(logging.DEBUG if os.getenv("JAMBOREE_DEBUG") == "1" else logging.INFO)

app = Flask(__name__, static_folder=str(STATIC_DIR))
app.register_blueprint(bp_sgs)
app.register_blueprint(bp_recovery)
ctl = Controller()
set_controller(ctl)

try:
    frame_provider.configure_from_env()
except Exception:
    logging.getLogger(__name__).exception("failed to configure frame provider")

CFG = {
    "stb_alias": os.getenv("JAMBOREE_STB_ALIAS", ""),
    "default_delay_ms": int(os.getenv("JAMBOREE_DEFAULT_DELAY_MS", "120")),
    "ip_recovery_cooldown_s": float(os.getenv("JAMBOREE_RECOVERY_COOLDOWN_S", "30")),
    "autopair_cooldown_s": float(os.getenv("JAMBOREE_AUTOPAIR_COOLDOWN_S", "180")),
}
ip_recovery.set_dependencies(
    store=store,
    ctl=ctl,
    get_frame=frame_provider.get_frame,
    get_status=frame_provider.get_status,
    CFG=CFG,
)
sgs_autopair.set_dependencies(
    store=store,
    ctl=ctl,
    get_frame=frame_provider.get_frame,
    CFG=CFG,
)


def init_serial_from_base(base_dict: dict) -> None:
    stbs = base_dict.get("stbs", base_dict) if isinstance(base_dict, dict) else {}
    mapping = {
        str(alias): str((info or {}).get("com_port") or "")
        for alias, info in stbs.items()
        if isinstance(info, Mapping) and (info or {}).get("com_port")
    }
    serial_mgr.sync_aliases(mapping, baud=115200)
    logging.getLogger(__name__).info("mapped %d alias(es) to DART ports", len(mapping))


@app.errorhandler(Exception)
def json_error(exc):
    """Return JSON errors without traceback-spamming expected HTTP routing misses."""
    if isinstance(exc, HTTPException):
        code = int(exc.code or 500)
        payload = {
            "ok": False,
            "error": exc.name,
            "message": exc.description,
            "status": code,
        }
        valid_methods = getattr(exc, "valid_methods", None)
        if valid_methods:
            payload["allowed_methods"] = sorted(str(method) for method in valid_methods)
        return jsonify(payload), code

    current_app.logger.exception("Unhandled request error")
    return jsonify(ok=False, error=str(exc), status=500), 500


@app.route("/")
def remote_page():
    return send_from_directory(STATIC_DIR, "JAMboRemote.html")


@app.route("/settops")
def settops_page():
    return send_from_directory(STATIC_DIR, "settops.html")


@app.route("/hostname")
def hostname():
    return jsonify(hostname=socket.gethostname())


@app.route("/api/health")
def health():
    return jsonify(
        ok=True,
        hostname=socket.gethostname(),
        stbs=len(store.all()),
        frame=frame_provider.status(),
    )


@app.route("/get-stb-list")
def get_stb_list():
    return jsonify(stbs=store.all())


@app.route("/save-stb-list", methods=["POST"])
def save_stb_list():
    payload = request.get_json(force=True, silent=False) or {}
    stbs = payload.get("stbs", payload)
    if not isinstance(stbs, Mapping):
        return jsonify(ok=False, error="stbs must be an object"), 400
    document = store.replace_stbs(stbs, allow_delete=True)
    init_serial_from_base(document)
    return jsonify(ok=True, success=True, stbs=store.all())


@app.route("/auto/<remote>/<path:stb>/<button>/<delay>", methods=["GET", "POST"])
def auto_route(remote: str, stb: str, button: str, delay: str):
    """Send one duration-based Auto command.

    Older JAMboRemote clients emitted an extra ``down`` request before the real
    duration request. Auto/SGS/RF is duration based, so acknowledge those stale
    edge events as no-ops instead of returning a routing 404 or double-sending.
    Quick-DART retains explicit down/up semantics on ``/dart``.
    """
    raw_delay = str(delay or "").strip()
    edge = raw_delay.lower()
    if edge in {"down", "up"}:
        return jsonify(
            ok=True,
            via="auto_compat",
            ignored=True,
            ignored_action=edge,
            detail="Auto mode uses a release duration; explicit down/up belongs to /dart.",
        )
    try:
        duration = int(raw_delay)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="delay must be an integer duration in milliseconds"), 400
    if duration < 0:
        return jsonify(ok=False, error="delay must be non-negative"), 400

    body = request.get_json(silent=True) or {}
    force = body.get("force") or request.args.get("force")
    allow_fallback = str(body.get("allow_rf_fallback", request.args.get("allow_rf_fallback", "true"))).lower() not in {"0", "false", "no", "off"}
    recover = str(body.get("recover_ip", request.args.get("recover_ip", "true"))).lower() not in {"0", "false", "no", "off"}
    return jsonify(
        ctl.handle_auto_remote(
            remote,
            stb,
            button,
            duration,
            force=force,
            allow_rf_fallback=allow_fallback,
            recover_ip=recover,
        )
    )


@app.route("/dart/<path:stb>/<button>/<action>", methods=["GET", "POST"])
def dart_route(stb: str, button: str, action: str):
    return jsonify(ctl.dart(stb, button, action))


@app.route("/unpair/<path:stb>", methods=["POST", "GET"])
def unpair_route(stb: str):
    return jsonify(ctl.unpair(stb))


@app.route("/whodis", methods=["POST", "GET"])
def whodis_route():
    return jsonify(result="whoami=" + socket.gethostname())


init_serial_from_base({"stbs": store.all()})
atexit.register(serial_mgr.stop_all)

if __name__ == "__main__":
    os.environ.setdefault("FLASK_ENV", "production")
    os.environ.setdefault("FLASK_RUN_FROM_CLI", "false")
    app.run(
        host=os.getenv("JAMBOREE_HOST", "0.0.0.0"),
        port=int(os.getenv("JAMBOREE_PORT", "5003")),
        debug=False,
        use_reloader=False,
    )
