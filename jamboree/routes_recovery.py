"""Operational APIs for transport status, IP recovery, and automatic pairing."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from . import ip_recovery, sgs_autopair

bp_recovery = Blueprint("recovery", __name__, url_prefix="/api")
_ctl = None


def set_controller(controller) -> None:
    global _ctl
    _ctl = controller


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _alias(default: str = "") -> str:
    body = _body()
    return str(body.get("alias") or request.args.get("alias") or default).strip()


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@bp_recovery.get("/ip_recovery/status")
def recovery_status():
    alias = str(request.args.get("alias") or "").strip() or None
    return jsonify(ip_recovery.get_recovery_status(alias))


@bp_recovery.post("/ip_recovery/run")
def recovery_run():
    body = _body()
    alias = str(body.get("alias") or "").strip()
    if not alias:
        return jsonify(ok=False, error="alias is required"), 400
    if _truthy(body.get("wait")):
        result = ip_recovery.recover_alias(alias)
        return jsonify(result.to_dict()), 200 if result.ok else 502
    started = ip_recovery.recover_alias_async(alias, force=_truthy(body.get("force")))
    return jsonify(ok=started, started=started, alias=alias), 202 if started else 409


@bp_recovery.get("/sgs/pair/status")
def pair_status():
    alias = str(request.args.get("alias") or "").strip()
    output = sgs_autopair.get_status()
    if alias:
        try:
            output["credentials"] = sgs_autopair.credentials_status(alias)
        except Exception as exc:
            output["credentials"] = {"error": str(exc)}
    return jsonify(output)


@bp_recovery.post("/sgs/pair/auto")
def pair_auto():
    body = _body()
    alias = str(body.get("alias") or "").strip()
    if not alias:
        return jsonify(ok=False, error="alias is required"), 400
    kwargs = {
        "force": _truthy(body.get("force")),
        "verify": not ("verify" in body and not _truthy(body.get("verify"))),
    }
    if body.get("pin") is not None:
        kwargs["pin"] = str(body["pin"])
    if body.get("pin_timeout_s") is not None:
        kwargs["pin_timeout_s"] = float(body["pin_timeout_s"])
    if _truthy(body.get("wait")):
        result = sgs_autopair.auto_pair(alias, **kwargs)
        return jsonify(result), 200 if result.get("ok") else 502
    started = sgs_autopair.auto_pair_async(alias, **kwargs)
    return jsonify(ok=started, started=started, alias=alias), 202 if started else 409


@bp_recovery.route("/sgs/pair/verify", methods=["POST", "GET"])
def pair_verify():
    alias = _alias()
    if not alias:
        return jsonify(ok=False, error="alias is required"), 400
    commands = sgs_autopair.verify_commands_active(alias)
    persistence = sgs_autopair.verify_credentials_persisted(alias)
    ok = bool(commands.get("ok")) and bool(persistence.get("secure_store"))
    return (
        jsonify(ok=ok, alias=alias, commands=commands, persistence=persistence),
        200 if ok else 502,
    )


@bp_recovery.get("/transports/<path:alias>")
def transport_status(alias: str):
    if _ctl is None:
        return jsonify(ok=False, error="controller not configured"), 503
    try:
        return jsonify(ok=True, **_ctl.transports(alias))
    except Exception as exc:
        return jsonify(ok=False, error=str(exc), alias=alias), 400
