# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Raspberry Pi–based automated pH dosing controller for Atlas Scientific EZO-pH and EZO-PMP
hardware over I2C. It has two independent entry points:

- **`ph_controller/`** — a Flask web app (dashboard + REST API) that runs continuously on the Pi,
  reads pH on a background thread, and doses acid/base pumps to hold a target pH.
- **`ph_dosing_terminal_controler.py`** — a standalone CLI controller with its own simplified
  dosing loop, for headless use without the web UI. It imports drivers directly from
  `ph_controller/hardware/ezo_i2c.py` but does not share the Flask app's `Controller`/config
  machinery.

There is no dependency manifest (no `requirements.txt`/`pyproject.toml`) and no test suite — the
only runtime dependency is Flask (`pip install flask`).

## Running

```bash
cd ph_controller
python3 app.py                       # serves the dashboard on http://0.0.0.0:8080
```

```bash
python3 ph_dosing_terminal_controler.py <target_ph> [--dose-ml ML] [--interval SEC] ...
python3 ph_dosing_terminal_controler.py --help
```

On non-Pi dev machines, `hardware/ezo_i2c.py` fails to import (no `/dev/i2c-*`), and both
`sensors.py` and `hardware/pump.py` fall back to stub/simulated behavior automatically — the app
runs fine without real hardware attached. `config.json`'s `simulate_ph` flag additionally drives a
sine-wave pH simulation inside the controller loop itself (see `controller.py`).

There is no lint or test command configured in this repo.

## Architecture

### Flask app (`ph_controller/`)

- **`app.py`** — application factory. Registers three blueprints (`dashboard`, `config_routes`,
  `pump_routes`). Gates every remote request behind HTTP Basic Auth (`PH_AUTH_USER`/`PH_AUTH_PASS`
  env vars, default `user`/`pass`) except requests from `127.0.0.1`/`::1`, so the on-Pi touchscreen
  kiosk never sees a login prompt.
- **`controller.py`** — the `Controller` singleton (`controller = Controller()` at import time)
  owns all dosing state behind a single `threading.Lock`. A daemon reader thread starts
  immediately on import and runs forever, independent of `start()`/`stop()`, so current pH is
  always visible on the dashboard. Status is a state machine: `stopped → running → paused →
  running → stopped`, with `start()` opening a fresh session CSV only on the `stopped → running`
  transition (resuming from `paused` keeps writing to the same file).
  - Dosing uses a proportional (P) controller (`_proportional_dose`): dose volume scales with
    `pH error - deadband`, clamped to `[PUMP_MIN_ML, dose_ml]`. Setting `dose_p_gain` to 0 disables
    P-control and always doses the full `dose_ml`.
  - I2C reads run in a helper thread with a hard timeout (`_ph_read_with_timeout`) so a hung I2C
    bus can't stall the loop indefinitely; a still-running previous read thread causes the next
    cycle to skip rather than pile up threads.
  - CSV writes are batched (`BATCH_SIZE` rows) and `os.fsync()`'d on flush to bound the data lost
    on power loss (SD card safety), with buffer-preserving retry on write failure. Flushes also
    happen on `pause()`/`stop()` so no data is lost on a clean shutdown.
  - Pump convention is fixed throughout the codebase: **pump 1 = acid** (lowers pH), **pump 2 =
    base** (raises pH).
- **`hardware/ezo_i2c.py`** — the only place that speaks the Atlas Scientific I2C protocol
  (`EZOBase`/`EZOPH`/`EZOPump`). Response status bytes: `1`=OK, `2`=syntax error, `254`=still
  processing (re-read, don't re-send), `255`=no data. `query()`'s `retries` defaults to `0` for
  polling reads (fail fast, let the caller move on) and should only be raised for must-succeed
  one-shot calls like calibration.
- **`hardware/pump.py`** / **`sensors.py`** — thin wrappers around `ezo_i2c` used by the rest of
  the app; both auto-detect hardware availability at import time and fall back to stubs. A dose's
  *delivered* volume is always measured via the pump's absolute-total-volume counter (`ATV,?`)
  before/after, never the commanded value — see the long comment in `pump.dose()` for why. `ATV`
  reflects what the pump's motor/encoder actually measured moving, not what was commanded, so a
  jammed pump, empty reservoir, or blocked tubing shows up as a small or zero `ATV` delta even
  though the `D,[ml]` command was accepted (status `1`/OK) and the device thinks it dispensed.
  Trusting the commanded volume would silently over-report acid/base delivered into a session
  where the pump was physically stuck — an unmeasurable dose is left uncounted rather than logged
  as a fabricated number.
- **`routes/`** — one blueprint per concern (`dashboard.py`, `pump_routes.py`, `config_routes.py`).
  Manual single-pump control (`pump_routes.py`) is locked out with HTTP 409 while the
  auto-controller is `running`, computed purely in software (`_locked()`) so it stays reliable even
  if I2C reads are failing.
- **`config.py`** — flat `config.json` next to it, merged over `DEFAULTS` on every `load()`; no
  schema/env layering beyond that.

### Two independent cadences

`poll_sec` is the **measurement** interval (how often pH is read, appended to history, and written
to the session CSV). `dose_interval_sec` is a separate, slower gate on **dosing** only. In
`_loop`, the existing deadband/`_proportional_dose` logic is unchanged — it is simply wrapped in a
`time.time() - self._last_dose_ts >= dose_gap` check. Two things to preserve when touching this:

- `_last_dose_ts` is reset **only when a dose actually fires**, not when the gate is evaluated.
  Time spent inside the deadband therefore does not consume an interval, so a later drift is
  corrected immediately instead of waiting out an unused one.
- History/CSV appends live **outside** the gate, so pH is still logged between doses.

Both are editable from `/config`. Defaults are 1 s each, which makes dosing effectively continuous
until someone raises `dose_interval_sec`.

### Frontend

- Server-rendered Jinja2 templates (`templates/`) polling the JSON API, not a SPA framework. The
  three templates are **standalone** — no `{% extends %}`, no shared base — so anything that must
  appear on more than one page belongs in `static/`, not copied into each template.
- All color/theme tokens are CSS custom properties in `static/css/theme.css`; see
  `ph_controller/STYLE.md` for the full token table and retheme recipes. Change a token there and
  it applies everywhere the stylesheet is loaded — don't hardcode colors in templates. Note
  `config.html` does **not** load `theme.css` and hardcodes its hex values, so shared CSS should
  use `var(--token, #fallback)`.
- **Numeric input on the kiosk.** The touchscreen has no physical keyboard and Chromium raises no
  native on-screen keyboard, so `static/js/numpad.js` provides one, built on the vendored
  `simple-keyboard`. Two non-obvious details:
  - While the pad is open the field is switched to `type="text"`, because assigning a partial
    decimal (`"7."`) to a `type="number"` input silently blanks it. `type`, `min`/`max`/`step` and
    the spinners are restored on commit.
  - The pad is fixed to the bottom and tall enough to cover page content, so it reserves its own
    height as body padding and scrolls the focused field to the **top** of the viewport. Scrolling
    to centre puts the field under the pad on a short screen.
  - `index.html` also runs a *separate* QWERTY `simple-keyboard` instance for session filenames.
    They are deliberately distinct instances with different container classes; don't merge them.
- `<input type="number">` `step` is a **hard constraint** once `checkValidity()` is called, not just
  a spinner increment. `step` must divide evenly from `min` or legitimate values are rejected —
  this already bit `deadband`, where `step="0.05"` from `min="0.01"` rejected `0.1`, its own default.

### Deploying to the Pi

The app runs from `/home/pi/pHDoseingProject` (launched by `start-atlasiot.sh`). Two gotchas that
make edits appear not to take effect:

- **Templates are cached.** Flask runs `debug=False`, so Jinja's auto-reload is off — any template
  change needs the app restarted, not just a browser refresh.
- **Static files are cached for 12 h** (`max-age=43200`), and fullscreen Chromium can't easily
  hard-refresh. Bump the `?v=N` query string on a changed asset URL, following the existing
  `theme.css?v=3` convention.

To reach the Pi desktop (e.g. to change WiFi), plug in a USB keyboard and press **F11** — see
[README.md](README.md). WiFi is deliberately *not* configurable from the dashboard: the dashboard is
served over the very network you would be reconfiguring, so it cannot fix a down link, and doing so
would require giving the app root.

### Session data

Each dosing session writes a timestamped CSV to `ph_controller/sessions/` (git-ignored) with
columns `time,elapsed_min,ph,target_ph,pump1_acid_ml,pump2_base_ml`. Filenames are
`<user-supplied-name>_<timestamp>.csv` or `session_<timestamp>.csv`; user-supplied names are
sanitized with `re.sub(r"[^\w\-]", "_", ...)`. Session file endpoints
(`/api/sessions/<filename>`, download/delete/preview) validate the filename against `..`/`/` before
touching the filesystem — keep that check when touching those routes.

## Hardware reliability & known issues

**EZO-pH / EZO-PMP I2C timeouts are a known, expected issue on this rig** — not a bug to chase
every time it shows up in the logs (`sensor error: ... returned no data`, `PUMP ... status
incomplete -- device not responding`). The code already defends against it (per-cycle skip in
`controller.py`'s `_ph_read_with_timeout`, `retries=0` fail-fast polling in `ezo_i2c.py`'s
`query()`, `status.get("ok")` flags so the UI holds last-known values). If timeouts become
*frequent* or *permanent* rather than occasional, check in this order:

1. **Another process on the same I2C bus — check this first.** As of 2026-07-21 this Pi runs a
   *second* program that talks to the same EZO devices: `AtlasIoT.service` (systemd, enabled) runs
   the .NET `/home/pi/AtlasIoTCore/AtlasIOTCore`, which logs `3 New I2C Modules Found` at startup
   and polls on a 60 s interval per its `SQLSettings.json`. `sudo lsof /dev/i2c-1` shows it holding
   three FDs on the bus alongside the Python app.

   An EZO exchange is *write command → wait 900 ms → read response*. A second process transacting
   inside that window corrupts both sides, which produces exactly the observed
   `EZO-pH 0x63 returned no data` and `PUMP ... not responding` errors. This is the most likely
   cause of the intermittent timeouts and should be ruled out before chasing wiring.

   ```bash
   sudo lsof /dev/i2c-1              # who else holds the bus?
   systemctl status AtlasIoT.service # the .NET app, unrelated to this project
   ```

   Whether to stop/disable that service is the user's operational call — it belongs to a separate
   project sharing the same hardware. Do not disable it unprompted.
2. **Electrical isolation** — per the EZO-pH datasheet, the pH circuit is sensitive enough to pick
   up electrical noise bled into the solution from pumps/motors/solenoids sharing the same water.
   This is the documented reason the BOM includes the **Atlas Scientific i3 Interlink** isolator
   between the Pi and the EZO circuits — confirm it is actually wired in and working, especially
   after any rewiring.
3. Power to the EZO-PMP boards — they need **both** 3.3–5.5 V (logic) and 12–24 V (motor); the pH
   circuit only needs 3.3–5.5 V. A pump that lost motor power reads as I2C-silent, not just "not
   pumping".
4. I2C bus/address sanity (`i2cdetect -y 1`, matching `config.json`'s `ph_addr` / `pump1_addr` /
   `pump2_addr`). Note `i2cdetect` probes the bus and can itself collide with a running controller.

### Response codes & timing (confirmed against both datasheets, matches `ezo_i2c.py`)

Both boards use the same 1-byte response code on every I2C read:

| Code | Meaning |
|---|---|
| `1` | success / OK |
| `2` | syntax error |
| `254` | still processing — **also returned if the host reads before the processing delay elapsed**, a common source of spurious 254s if a delay is shortened |
| `255` | no data to send |

Processing delays (why `ezo_i2c.py` waits before reading a response):
- EZO-pH single reading (`R`, `RT`) and calibration: **900 ms**
- Everything else on both boards (`L`, `Find`, `D`, `X`, `Cal`, `Pv`, `Invert`, …): **300 ms**

I2C bus: 100–400 kHz, valid addresses `0x01`–`0x7F` (defaults `0x63` pH, `0x67` pump).

### EZO-PMP settings retained vs. lost on power cycle

Retained: baud rate, calibration, continuous-mode flag, device name, enabled/disabled parameters &
response codes, I2C/UART protocol switch, **invert direction**, LED state, protocol lock.
**Not retained**: absolute total volume (`ATV`), Find state, sleep mode, total volume (`TV`).
`pump.dose()` brackets each dispense with its own `ATV,?` reads to catch a stuck pump (above); the
fact that `ATV` also doesn't survive a power cycle just means it can never be read as a running
lifetime total, only as a delta across one dispense.

### EZO-PMP mechanical reference

Flow rate 0.5–105 mL/min, ±1% calibrated / ±5% uncalibrated, min dispense 0.5 mL (matches
`PUMP_MIN_ML`). Rated lifespans, worth checking before assuming a software/calibration fault if
dosing drifts or weakens: **tubing ~1,000 hrs, cassette ~1,500 hrs, motor ~5,000 hrs**.

### Source datasheets

- EZO-pH v5.5: https://images-na.ssl-images-amazon.com/images/I/D1fjCme5s5S.pdf
- EZO-PMP v3.0: https://files.atlas-scientific.com/EZO_PMP_Datasheet.pdf

## Known gaps

- `config.json` carries `max_volume_ml: 2500.0`, which is **dead** — not in `DEFAULTS`, never read
  anywhere. `config.py`'s merge preserves it indefinitely. The Flask controller has **no cumulative
  session dose cap at all**; `pump1_dosed`/`pump2_dosed` are display-only totals with no ceiling.
  The CLI script's `MAX_DOSE_ML` is a separate, unconnected cap.

## REST API

Full endpoint reference (bodies, config fields, CSV format) is documented in the root
[README.md](README.md) under "REST API Reference" — check it before adding or changing routes so
the docs stay in sync.
