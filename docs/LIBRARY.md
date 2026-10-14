# Using the Libraries in Your Own Scripts

All hardware drivers live in `ph_controller/hardware/`. You can import and use them directly from
any script in the project root without running the web app.

> **Only one program may talk to the EZO devices at a time.** These are stateful request/response
> devices on a shared bus — a second process transacting mid-exchange causes both to see failed
> reads. Stop the web app (or at least its controller) before running your own script against the
> same hardware, and see the I2C contention note in [CLAUDE.md](../CLAUDE.md).

---

## EZO I2C Driver — `hardware/ezo_i2c.py`

Low-level driver for Atlas Scientific EZO modules over I2C. Every getter returns `None` on a failed
or unparseable read rather than raising, so check before using the result.

```python
import sys
sys.path.insert(0, "ph_controller")

from hardware.ezo_i2c import EZOPH, EZOPump, scan_ezo_bus

# ── pH sensor ────────────────────────────────────────────────────
ph = EZOPH(address=99, bus=1)
reading = ph.read_ph()                  # Optional[float], e.g. 6.842 — None on failure
reading = ph.read_ph_with_temp(22.5)    # same, with temperature compensation

# Calibration (always mid first — it clears the other points)
ph.calibrate_mid(7.0)
ph.calibrate_low(4.0)
ph.calibrate_high(10.0)
ph.get_calibration_points()             # Optional[int]: 0, 1, 2, or 3
ph.get_slope()                          # Optional[PHSlope(acid_pct, base_pct, zero_mv)]
ph.clear_calibration()

ph.close()  # or use as a context manager: with EZOPH(99) as ph:

# ── Pump ─────────────────────────────────────────────────────────
pump = EZOPump(address=103, bus=1)
pump.dispense(5.0)                      # dispense 5 mL (minimum 0.5 mL)
pump.dispense_continuous()              # run until stop()
pump.dispense_over_time(20.0, 5.0)      # 20 mL spread over 5 minutes
pump.dispense_at_rate(10.0, "*")        # 10 mL/min indefinitely
pump.stop()                             # Optional[float]: mL moved in the stopped dose
pump.pause()                            # pause/resume toggle
pump.invert()                           # flip direction (retained across power cycles)
pump.calibrate(9.7)                     # store actual measured volume
pump.get_dispense_status()              # Optional[DispenseStatus(volume, pumping)]
pump.get_total_volume()                 # Optional[float]: session total (TV) — lost on power cycle
pump.get_absolute_total_volume()        # Optional[float]: absolute total (ATV) — lost on power cycle
pump.get_pump_voltage()                 # Optional[float]: motor supply voltage in V
pump.wait_until_done(timeout=120)       # block until dispensing finishes

pump.close()

# ── Scan the I2C bus for EZO devices ─────────────────────────────
for addr, info in scan_ezo_bus(bus=1, start=97, end=112):
    print(f"0x{addr:02X}  {info.device_type}  fw {info.firmware}")
```

**Timing.** A pH reading takes ~900 ms; nearly everything else takes ~300 ms. The driver already
waits for you. Reads return status `254` ("still processing") if polled too early — the driver
re-reads rather than re-sending, which is the behaviour the datasheet asks for.

## Pump Helpers — `hardware/pump.py`

Thread-safe convenience wrappers used by the web app. A good starting point for simple scripts.

```python
import sys
sys.path.insert(0, "ph_controller")

from hardware import pump

ACID_ADDR = 103
BASE_ADDR = 114
BUS       = 1

delivered = pump.dose(ACID_ADDR, 1.5, BUS)        # -> float: mL ACTUALLY moved (see below)
pump.run_continuous(ACID_ADDR, reverse=False, bus=BUS)   # prime / run
pump.stop(ACID_ADDR, BUS)
pump.invert_direction(ACID_ADDR, BUS)             # toggle direction
pump.dispense_volume(ACID_ADDR, 10.0, BUS)        # for calibration
pump.calibrate_pump(ACID_ADDR, 9.7, BUS)          # store calibration
pump.clear_calibration(ACID_ADDR, BUS)            # erase calibration
status = pump.get_status(ACID_ADDR, BUS)
# {"ok": bool, "pumping": bool, "inverted": bool, "cal_status": int, "voltage": float}
# When ok is False the other keys are absent — the device did not answer.
```

### `dose()` returns what moved, not what you asked for

`dose()` brackets the dispense with reads of the pump's absolute total volume counter (`ATV`) and
returns the **measured delta**. This matters:

- A jammed pump, empty reservoir, or blocked tube returns `0.0` (or a short volume) even though the
  `D,[ml]` command was accepted and the device believes it dispensed.
- It returns `0.0` if the counter could not be read at all. An unmeasurable dose is deliberately
  left uncounted rather than logged as a number that was never verified.

So `delivered < ml` is a signal worth acting on, and totalling the return values gives you a real
delivered volume rather than a commanded one.

## pH Sensor Helpers — `sensors.py`

```python
import sys
sys.path.insert(0, "ph_controller")

import sensors

ph = sensors.get_ph(address=99, bus=1)      # float; raises IOError if the device returns no data
sensors.calibrate_mid(7.0, address=99, bus=1)
sensors.calibrate_low(4.0, address=99, bus=1)
sensors.calibrate_high(10.0, address=99, bus=1)
sensors.clear_calibration(address=99, bus=1)
info = sensors.get_calibration_info(address=99, bus=1)
# {"points": int, "slope": {"acid_pct", "base_pct", "zero_mv"}}
```

Unlike the raw driver, `get_ph()` **raises** `IOError` instead of returning `None`, so wrap it in
`try`/`except` in a polling loop.

> On a machine without `/dev/i2c-*` (any non-Pi dev box), `sensors.py` and `hardware/pump.py`
> detect the missing driver at import time and fall back to stubs, so scripts and the web app run
> without hardware attached.

## Standalone CLI Controller — `ph_dosing_terminal_controler.py`

Runs a full dosing loop from the command line with no web interface. Useful for headless operation
or testing without the UI.

```bash
python3 ph_dosing_terminal_controler.py 7.0 --dose-ml 1.0 --interval 60
python3 ph_dosing_terminal_controler.py --help
```

It has its own argument defaults and its own `--max-dose` cumulative session cap, and does **not**
share `ph_controller/config.json` or the web app's controller. Note the web app has no equivalent
session cap — see [Safety](../README.md#safety).
