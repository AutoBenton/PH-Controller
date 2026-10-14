#!/usr/bin/env bash
# deploy/install.sh -- provision a fresh Raspberry Pi OS (Desktop, Bookworm/Trixie)
# for the pH controller. Idempotent: safe to re-run.
#
# Run from the repo root as the desktop user you created in Raspberry Pi Imager:
#     bash deploy/install.sh && sudo reboot
#
# Does: apt deps, I2C @100 kHz, systemd service for the Flask app, Chromium
# kiosk via labwc autostart, desktop autologin, no screen blanking.
# Does NOT: pump readdressing, probe/pump calibration, Tailscale -- per-rig
# hardware steps, done by hand.
set -euo pipefail

[ "$(id -u)" -ne 0 ] || { echo "Run as the desktop user, not root."; exit 1; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$REPO/ph_controller"
ME="$(id -un)"
[ -f "$APP/app.py" ] || { echo "Can't find $APP/app.py -- run from the repo."; exit 1; }

echo "== packages"
sudo apt-get update
sudo apt-get install -y python3-flask i2c-tools curl

echo "== I2C"
sudo raspi-config nonint do_i2c 0            # 0 = enable
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
grep -q '^dtparam=i2c_arm_baudrate=' "$CFG" \
  || echo 'dtparam=i2c_arm_baudrate=100000' | sudo tee -a "$CFG" >/dev/null
sudo usermod -aG i2c "$ME"

echo "== credentials"
if [ ! -f /etc/ph-controller.env ]; then
  read -rp  "Dashboard username: " U
  read -rsp "Dashboard password: " P; echo
  [ -n "$U" ] && [ -n "$P" ] || { echo "Username and password required."; exit 1; }
  printf 'PH_AUTH_USER=%s\nPH_AUTH_PASS=%s\n' "$U" "$P" | sudo tee /etc/ph-controller.env >/dev/null
  sudo chmod 600 /etc/ph-controller.env
fi

echo "== systemd service"
# Restart is safe: the controller always boots "stopped", never resumes dosing.
sudo tee /etc/systemd/system/ph-controller.service >/dev/null <<EOF
[Unit]
Description=pH dosing controller (Flask)
After=network.target

[Service]
User=$ME
WorkingDirectory=$APP
EnvironmentFile=/etc/ph-controller.env
ExecStart=/usr/bin/python3 -u app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "== kiosk"
BROWSER="$(command -v chromium || command -v chromium-browser || true)"
[ -n "$BROWSER" ] || { echo "Chromium not found -- use the Desktop image, not Lite."; exit 1; }
mkdir -p "$HOME/.config/labwc"
AUTOSTART="$HOME/.config/labwc/autostart"
# ponytail: --start-fullscreen (not --kiosk) so F11 still exits for WiFi setup.
# Waits for the app before opening so the kiosk never shows a connection error.
grep -q 'ph-kiosk' "$AUTOSTART" 2>/dev/null || cat >> "$AUTOSTART" <<EOF
# ph-kiosk
sh -c 'until curl -sf -o /dev/null http://127.0.0.1:8080/api/status; do sleep 2; done; exec $BROWSER --start-fullscreen --noerrdialogs --disable-session-crashed-bubble --password-store=basic http://127.0.0.1:8080' &
EOF
sudo raspi-config nonint do_boot_behaviour B4   # desktop autologin
sudo raspi-config nonint do_blanking 1          # disable screen blanking

echo "== I2C scan (before the controller starts, so it can't collide)"
sudo i2cdetect -y 1 || echo "(bus not up yet -- normal before first reboot)"

echo "== start + smoke test"
sudo systemctl daemon-reload
sudo systemctl enable --now ph-controller
for _ in $(seq 1 15); do
  curl -sf -o /dev/null http://127.0.0.1:8080/api/status && { echo "OK: dashboard up on :8080"; break; }
  sleep 1
done || true
curl -sf -o /dev/null http://127.0.0.1:8080/api/status \
  || { echo "FAIL: see  journalctl -u ph-controller -n 50"; exit 1; }

echo
echo "Done. Reboot to apply I2C group + kiosk:  sudo reboot"
echo "Then per rig: readdress pump 2 -> 0x72, calibrate probe + pumps, set up Tailscale."
