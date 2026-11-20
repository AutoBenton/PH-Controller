"""config.py -- Load/save settings from config.json next to this file."""

import json
import os

_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULTS = {
    "ph_addr":    99,    # EZO-pH  I2C address  (0x63)
    "pump1_addr": 103,   # EZO-PMP acid pump    (0x67)
    "pump2_addr": 114,   # EZO-PMP base pump    (0x72)
    "i2c_bus":    1,
    "deadband":   0.1,
    "dose_ml":    5.0,
    "dose_p_gain": 5.0,
    "poll_sec":   1.0,   # measurement interval -- how often pH is read/logged
    "dose_interval_sec": 1.0,  # min seconds between doses (settling time)
    "simulate_ph": False,
    "email_user": "",          # sender email (e.g. example@gmail.com)
    "email_password": "",      # sender password / app password (e.g. examplePSWD)
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "preset_emails": [],       # dynamic list of preset recipient emails
}


def load() -> dict:
    if os.path.exists(_PATH):
        with open(_PATH) as f:
            saved = json.load(f)
        return {**DEFAULTS, **saved}
    return dict(DEFAULTS)


def save(data: dict) -> None:
    current = load()
    current.update(data)
    with open(_PATH, "w") as f:
        json.dump(current, f, indent=2)
