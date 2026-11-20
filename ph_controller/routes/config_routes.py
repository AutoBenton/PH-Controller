from flask import Blueprint, jsonify, render_template, request
from controller import controller
import config as cfg_mod
import sensors
import mailer

bp = Blueprint("config_routes", __name__)


@bp.route("/config")
def config_page():
    return render_template("config.html")


@bp.route("/api/config", methods=["GET"])
def api_config_get():
    try:
        return jsonify(cfg_mod.load())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/config", methods=["POST"])
def api_config_post():
    try:
        data = request.get_json(force=True)
        cfg  = cfg_mod.load()
        for k in ("ph_addr", "pump1_addr", "pump2_addr", "i2c_bus"):
            if k in data:
                v = int(data[k])
                if k != "i2c_bus" and not (1 <= v <= 127):
                    return jsonify({"error": f"{k} must be 1-127"}), 400
                cfg[k] = v
        # Bounds mirror the min/max already declared on the config.html inputs.
        # The client validates too, but this is the real boundary -- a bad value
        # here reaches the dosing loop and the pumps.
        for k, lo, hi in (
            ("deadband",    0.01, 2.0),
            ("dose_ml",     0.5,  50.0),
            ("dose_p_gain", 0.0,  100.0),
            ("poll_sec",           1.0, 300.0),
            ("dose_interval_sec",  1.0, 3600.0),
        ):
            if k in data:
                v = float(data[k])
                if not (lo <= v <= hi):
                    return jsonify({"error": f"{k} must be {lo}-{hi}"}), 400
                cfg[k] = v
        if "simulate_ph" in data:
            cfg["simulate_ph"] = bool(data["simulate_ph"])
        if "email_user" in data:
            cfg["email_user"] = str(data["email_user"]).strip()
        if "email_password" in data:
            cfg["email_password"] = str(data["email_password"])
        if "smtp_server" in data:
            cfg["smtp_server"] = str(data["smtp_server"]).strip() or "smtp.gmail.com"
        if "smtp_port" in data:
            try:
                cfg["smtp_port"] = int(data["smtp_port"])
            except (ValueError, TypeError):
                cfg["smtp_port"] = 587
        if "preset_emails" in data and isinstance(data["preset_emails"], list):
            cfg["preset_emails"] = [
                str(e).strip() for e in data["preset_emails"] if str(e).strip()
            ]
        cfg_mod.save(cfg)
        controller.reload_config()
        return jsonify(cfg)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/api/config/test-email", methods=["POST"])
def api_test_email():
    try:
        data = request.get_json(force=True, silent=True) or {}
        res = mailer.test_smtp_connection(
            email_user=data.get("email_user"),
            email_password=data.get("email_password"),
            smtp_server=data.get("smtp_server"),
            smtp_port=data.get("smtp_port")
        )
        return jsonify(res), (200 if res.get("ok") else 400)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/api/calibrate/reading")
def api_cal_reading():
    try:
        cfg  = cfg_mod.load()
        ph   = controller.current_ph
        info = sensors.get_calibration_info(cfg["ph_addr"], cfg["i2c_bus"])
        return jsonify({"current_ph": ph, **info})
    except Exception as exc:
        return jsonify({"error": str(exc), "current_ph": None,
                        "points": None, "slope": None})


@bp.route("/api/calibrate/<point>", methods=["POST"])
def api_calibrate(point):
    try:
        cfg  = cfg_mod.load()
        addr = cfg["ph_addr"]
        bus  = cfg["i2c_bus"]

        if point == "clear":
            ok = sensors.clear_calibration(addr, bus)
            return jsonify({"ok": ok})

        defaults = {"mid": 7.0, "low": 4.0, "high": 10.0}
        if point not in defaults:
            return jsonify({"error": f"unknown point '{point}'"}), 400

        data  = request.get_json(force=True) or {}
        value = float(data.get("value", defaults[point]))
        fns   = {
            "mid":  sensors.calibrate_mid,
            "low":  sensors.calibrate_low,
            "high": sensors.calibrate_high,
        }
        ok = fns[point](value, addr, bus)
        return jsonify({"ok": ok, "point": point, "value": value})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500