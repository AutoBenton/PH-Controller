"""
hardware/pump.py -- EZO-PMP pump control.
Creates a fresh EZOPump instance per call (thread-safe via _pump_lock).
Falls back to a stub when ezo_i2c is unavailable.
"""

import datetime
import threading

_pump_lock = threading.Lock()

def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")

try:
    from hardware.ezo_i2c import EZOPump
    _HW = True
    print(f"[{_ts()}] PUMP    ezo_i2c loaded -- using real EZO-PMP hardware")
except Exception as _e:
    _HW = False
    print(f"[{_ts()}] PUMP    ezo_i2c not available ({_e}) -- using stub")


# ── Auto-dosing (called by controller) ───────────────────────────

def dose(address: int, ml: float, bus: int = 1) -> float:
    """Dispense ml mL. Returns the ACTUAL mL moved, measured as the change in the
    pump's absolute total-volume counter (ATV,?). Returns 0.0 if nothing was
    dispensed OR if the counter could not be read.

    D,? reports the *commanded* volume, not what physically moved, so we bracket
    the dispense with ATV reads and accumulate only the measured delta. The
    commanded value is NEVER counted -- an unmeasurable dose is left uncounted
    rather than logged as a fabricated number.
    """
    import time
    print(f"[{_ts()}] PUMP    0x{address:02X} dose {ml:.2f} mL")
    if not _HW:
        return ml
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            before = p.get_absolute_total_volume()
            ok = p.dispense(ml)
            if not ok:
                print(f"[{_ts()}] PUMP    0x{address:02X} WARNING -- D,{ml:.2f} not acknowledged")
                return 0.0
            # Wait for the pump to finish; tolerate transient status-read misses.
            deadline = time.time() + 30.0
            while time.time() < deadline:
                ds = p.get_dispense_status()
                if ds is not None and not ds.pumping:
                    break
                time.sleep(0.3)
            else:
                print(f"[{_ts()}] PUMP    0x{address:02X} WARNING -- dose not confirmed within 30 s")
            after = p.get_absolute_total_volume()
    if before is None or after is None:
        print(f"[{_ts()}] PUMP    0x{address:02X} WARNING -- ATV unreadable; dose NOT counted")
        return 0.0
    delivered = abs(after - before)
    print(f"[{_ts()}] PUMP    0x{address:02X} delivered {delivered:.2f} mL (commanded {ml:.2f})")
    return delivered


def stop(address: int, bus: int = 1) -> None:
    """Stop the pump immediately."""
    print(f"[{_ts()}] PUMP    0x{address:02X} stop")
    if _HW:
        with _pump_lock:
            with EZOPump(address=address, bus=bus) as p:
                p.stop()


# ── Manual control (called by pump routes) ────────────────────────

def run_continuous(address: int, reverse: bool = False, bus: int = 1) -> bool:
    """Run continuously until stop() is called. Used for priming."""
    direction = "reverse" if reverse else "forward"
    print(f"[{_ts()}] PUMP    0x{address:02X} run continuous {direction}")
    if not _HW:
        return True
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            return p.dispense_continuous(reverse=reverse)


def invert_direction(address: int, bus: int = 1) -> bool:
    """Toggle dispensing direction (retained across power cycles)."""
    print(f"[{_ts()}] PUMP    0x{address:02X} invert direction")
    if not _HW:
        return True
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            return p.invert()


def dispense_volume(address: int, ml: float, bus: int = 1) -> bool:
    """Dispense a specific volume. Used in calibration step 2."""
    print(f"[{_ts()}] PUMP    0x{address:02X} dispense {ml:.2f} mL")
    if not _HW:
        return True
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            return p.dispense(ml)


def calibrate_pump(address: int, actual_ml: float, bus: int = 1) -> bool:
    """Store single-point volume calibration with measured actual_ml."""
    print(f"[{_ts()}] PUMP    0x{address:02X} calibrate actual={actual_ml:.2f} mL")
    if not _HW:
        return True
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            return p.calibrate(actual_ml)


def clear_calibration(address: int, bus: int = 1) -> bool:
    """Erase pump calibration data (Cal,clear)."""
    print(f"[{_ts()}] PUMP    0x{address:02X} clear calibration")
    if not _HW:
        return True
    with _pump_lock:
        with EZOPump(address=address, bus=bus) as p:
            return p.clear_calibration()


def get_status(address: int, bus: int = 1) -> dict:
    """Return pump state: pumping, inverted, cal_status (0-3), voltage.

    Includes an "ok" flag so callers can tell a real reading apart from a failed
    I2C read. The EZO getters return None (not an exception) when the device does
    not answer; if invert or cal comes back None we report ok=False so the UI can
    hold its last-known values instead of flipping to defaults.
    """
    if not _HW:
        return {"ok": True, "pumping": False, "inverted": False,
                "cal_status": 0, "voltage": None}
    try:
        with _pump_lock:
            with EZOPump(address=address, bus=bus) as p:
                ds      = p.get_dispense_status()
                inv     = p.get_invert()
                cal     = p.get_calibration_status()
                voltage = p.get_pump_voltage()
    except Exception as exc:
        print(f"[{_ts()}] PUMP    0x{address:02X} status read failed: {exc}")
        return {"ok": False}
    if inv is None or cal is None:
        print(f"[{_ts()}] PUMP    0x{address:02X} status incomplete -- device not responding")
        return {"ok": False}
    return {
        "ok":         True,
        "pumping":    ds.pumping if ds else False,
        "inverted":   bool(inv),
        "cal_status": cal,
        "voltage":    voltage,
    }
