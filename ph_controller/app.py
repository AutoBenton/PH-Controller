"""
app.py -- Flask application factory.
Run: python3 app.py   then open http://<pi-ip>:8080

Remote access is gated by HTTP Basic Auth (see _check_auth below). Defaults are
user / pass for easy lab setup; override with PH_AUTH_USER / PH_AUTH_PASS in the
environment for anything more sensitive. Requests from localhost (the on-Pi
kiosk) are exempt so the local display needs no credentials.
"""

import hmac
import os

from flask import Flask, Response, request
from routes.dashboard    import bp as dashboard_bp
from routes.config_routes import bp as config_bp
from routes.pump_routes  import bp as pump_bp

app = Flask(__name__)
app.register_blueprint(dashboard_bp)
app.register_blueprint(config_bp)
app.register_blueprint(pump_bp)

_LOCAL_ADDRS = ("127.0.0.1", "::1")

# Defaults for lab convenience; override via environment for stronger creds.
_AUTH_USER = os.environ.get("PH_AUTH_USER", "user")
_AUTH_PASS = os.environ.get("PH_AUTH_PASS", "pass")


def _auth_ok(auth) -> bool:
    """Constant-time check of Basic Auth credentials."""
    if auth is None:
        return False
    # evaluate both fields to avoid short-circuit timing leaks
    ok_user = hmac.compare_digest(auth.username or "", _AUTH_USER)
    ok_pw   = hmac.compare_digest(auth.password or "", _AUTH_PASS)
    return ok_user and ok_pw


@app.before_request
def _check_auth():
    # Local kiosk (on the Pi itself) is exempt -- never prompted.
    if request.remote_addr in _LOCAL_ADDRS:
        return None
    if _auth_ok(request.authorization):
        return None
    return Response(
        "authentication required", 401,
        {"WWW-Authenticate": 'Basic realm="pH Controller"'},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)