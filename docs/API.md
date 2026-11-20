# REST API Reference

The web app exposes a JSON API at `http://<pi-ip>:8080`. Useful for integrating with external
systems or writing custom control scripts using `requests`.

> **Auth.** All endpoints require HTTP Basic Auth when accessed remotely (default `user` / `pass`,
> override with `PH_AUTH_USER` / `PH_AUTH_PASS`). Pass credentials with e.g. `curl -u user:pass ...`
> or `requests`' `auth=("user", "pass")`. Requests from localhost — the on-Pi kiosk — are exempt.
> See [Remote Access](../README.md#remote-access).

---

## Pages

Three server-rendered HTML pages, all `GET`:

| Path | Page |
|---|---|
| `/` | Dashboard — live pH, chart, session controls |
| `/config` | Settings and pH probe calibration |
| `/pumps` | Manual pump control and pump calibration |

## Dashboard

| Method | Endpoint | Body | Description |
|---|---|---|---|
| `GET` | `/api/status` | — | Full controller state (pH, target, pumps, dosed totals, history, session file) |
| `POST` | `/api/target` | `{"target_ph": 7.0}` | Set target pH. Rejects outside 0–14 with `400` |
| `POST` | `/api/pump/start` | `{"name": "Tank_A"}` *(optional)* | Start / resume session. A name is used for the CSV filename |
| `POST` | `/api/pump/pause` | — | Pause dosing (halts pumps, flushes the CSV buffer) |
| `POST` | `/api/pump/stop` | — | Stop and close the session |
| `GET` | `/api/debug` | — | Everything `/api/status` returns, plus `thread_alive` and the full loaded config. Handy when the controller appears stuck |

## Sessions

| Method | Endpoint | Body | Description |
|---|---|---|---|
| `GET` | `/api/sessions` | — | List saved CSV sessions (`name`, `size_kb`, `modified`) |
| `GET` | `/api/sessions/<filename>` | — | Download a session CSV |
| `POST` | `/api/sessions/save` | `{"filename": "session.csv", "csv": "..."}` | Save or upload a session CSV to the server sessions directory |
| `DELETE` | `/api/sessions/<filename>` | — | Delete a session CSV |
| `GET` | `/api/sessions/<filename>/preview` | — | Downsampled `{"ph": [...], "target": [...]}` (max 60 points) for chart previews |
| `POST` | `/api/export/email` | `{"recipient": "user@example.com", "sessions": ["session.csv"]}` | Send selected session CSV files as email attachments |

`<filename>` must end in `.csv` and may not contain `/`, `\`, or `..`; anything else returns `400`.

## Manual Pump Control

`<id>` is `1` (acid) or `2` (base).

| Method | Endpoint | Body | Description |
|---|---|---|---|
| `GET` | `/api/pump/<id>/status` | — | `{"ok", "pumping", "inverted", "cal_status", "voltage", "locked"}` |
| `POST` | `/api/pump/<id>/run` | `{"reverse": false}` | Run continuously (prime/flush) |
| `POST` | `/api/pump/<id>/stop` | — | Stop this pump |
| `POST` | `/api/pump/<id>/invert` | — | Toggle direction (retained across power cycles) |
| `POST` | `/api/pump/<id>/dispense` | `{"ml": 10.0}` | Dispense a specific volume |
| `POST` | `/api/pump/<id>/calibrate` | `{"actual_ml": 9.7}` | Store volume calibration |
| `POST` | `/api/pump/<id>/calibrate/clear` | — | Erase this pump's calibration |

> **Manual control is locked while the auto-controller is running.** Every route above except
> `status` and `stop` returns **`409`** with `{"error": "controller is running — stop it first"}`
> until you `POST /api/pump/stop`. The lock is computed in software, so it stays correct even when
> I2C reads are failing.

**On `status`:** check `ok` first. When an I2C read fails the response is `{"ok": false, "locked": ...}`
and the other fields are absent — hold your last known values rather than treating them as defaults.

## Configuration & pH Calibration

| Method | Endpoint | Body | Description |
|---|---|---|---|
| `GET` | `/api/config` | — | Read current config |
| `POST` | `/api/config` | Any subset of the fields below | Update config; applies immediately, mid-session |
| `POST` | `/api/config/test-email` | `{"email_user": "...", "email_password": "..."}` | Test SMTP connection & credentials |
| `GET` | `/api/calibrate/reading` | — | Current pH + calibration point count + probe slope |
| `POST` | `/api/calibrate/mid` | `{"value": 7.0}` | Calibrate pH mid point — **do this first** |
| `POST` | `/api/calibrate/low` | `{"value": 4.0}` | Calibrate pH low point |
| `POST` | `/api/calibrate/high` | `{"value": 10.0}` | Calibrate pH high point |
| `POST` | `/api/calibrate/clear` | — | Clear all pH calibration |

> Re-running `mid` on an already-calibrated probe **clears the other points** — a full
> recalibration is then required. This is EZO firmware behaviour, not an app choice.

### Config fields

| Key | Type | Range | UI label | Meaning |
|---|---|---|---|---|
| `ph_addr` | int | 1–127 | pH Probe I2C Address | EZO-pH address (default 99 / `0x63`) |
| `pump1_addr` | int | 1–127 | Pump 1 – Acid | EZO-PMP address (default 103 / `0x67`) |
| `pump2_addr` | int | 1–127 | Pump 2 – Base | EZO-PMP address (default 114 / `0x72`) |
| `i2c_bus` | int | — | I2C Bus Number | Usually `1` |
| `deadband` | float | 0.01–2.0 | Deadband (pH ±) | No dosing while within ± this of target |
| `dose_ml` | float | 0.5–50 | Max Dose per Cycle (mL) | Upper cap on a **single** dose, not a session total |
| `dose_p_gain` | float | 0–100 | Dose Aggressiveness (P) | mL per pH unit of error beyond the deadband; `0` always doses `dose_ml` |
| `poll_sec` | float | 1–300 | Measurement Interval (s) | How often pH is read and logged |
| `dose_interval_sec` | float | 1–3600 | Dose Interval (s) | Minimum time between doses |
| `simulate_ph` | bool | — | Simulate pH oscillation | Replaces the sensor with a sine wave for demos |
| `email_user` | str | — | Sender Email | SMTP / Gmail sender address (e.g. `example@gmail.com`) |
| `email_password` | str | — | Sender Password | App password or email account password |
| `smtp_server` | str | — | SMTP Host | Default `smtp.gmail.com` |
| `smtp_port` | int | 1–65535 | SMTP Port | Default `587` |
| `preset_emails` | list | — | Preset Recipient Emails | Saved list of recipient email addresses for quick export |

Out-of-range values are rejected with `400` and an `{"error": ...}` message.

See [How dosing works](../README.md#how-dosing-works) for what `poll_sec` and `dose_interval_sec`
do together.

## Session CSV format

```
time,elapsed_min,ph,target_ph,pump1_acid_ml,pump2_base_ml
2026-05-19 14:30:01,0.0,6.842,7.0,0.0,0.0
2026-05-19 14:30:03,0.033,6.839,7.0,0.0,0.5
...
```

The pump columns are **cumulative** mL dispensed so far in the session, and reflect volume actually
measured as moved — see [`dose()`](LIBRARY.md#pump-helpers--hardwarepumppy). One row is written per
measurement cycle, so pH is recorded between doses as well as during them.

Rows are buffered and flushed to disk in batches (10 rows) with `fsync`, and also flushed on pause
and stop. A power cut can therefore lose at most the last few rows.
