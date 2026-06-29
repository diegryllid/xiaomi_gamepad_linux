#!/usr/bin/env bash
# Install the Xiaomi gamepad driver: the daemon as a root systemd service, plus a udev rule that
# hides the real pad's nodes so games only ever see the clean virtual Xbox 360 pad.
set -e
[ "$(id -u)" = 0 ] || { echo "run with sudo:  sudo ./install.sh"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"

# dependency check
python3 -c 'import evdev' 2>/dev/null || {
  echo "ERROR: missing python-evdev. Install it, e.g.:"
  echo "  Arch:   sudo pacman -S python-evdev"
  echo "  pip:    pip install evdev"
  exit 1; }

install -Dm755 "$HERE/xiaomi-gamepad.py"               /usr/local/bin/xiaomi-gamepad.py
install -Dm644 "$HERE/udev/99-xiaomi-gamepad-hide.rules" /etc/udev/rules.d/99-xiaomi-gamepad-hide.rules
install -Dm644 "$HERE/systemd/xiaomi-gamepad.service"  /etc/systemd/system/xiaomi-gamepad.service

echo uinput > /etc/modules-load.d/uinput.conf
modprobe uinput || true
udevadm control --reload
systemctl daemon-reload
systemctl enable --now xiaomi-gamepad.service

echo
echo "Installed. Turn the gamepad on -- it appears as 'Microsoft X-Box 360 pad'."
echo "Verify mapping:  python3 $HERE/tools/xiaomi-verify.py"
