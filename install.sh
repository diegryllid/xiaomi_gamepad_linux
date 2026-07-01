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

# per-game gyro config -- keep the user's existing game list if one is already there
install -d /etc/xiaomi-gamepad
[ -f /etc/xiaomi-gamepad/gyro-games.conf ] || \
  install -Dm644 "$HERE/gyro-games.conf.example" /etc/xiaomi-gamepad/gyro-games.conf

echo uinput > /etc/modules-load.d/uinput.conf
modprobe uinput || true
udevadm control --reload
systemctl daemon-reload

# On-demand: udev starts the daemon when the pad connects and stops it when the pad disconnects, so
# it uses no RAM while the pad is off. NOT enabled at boot. (Undo any old boot-enable, clear a stale
# instance, then let udev start it now iff the pad is already connected.)
systemctl disable xiaomi-gamepad.service 2>/dev/null || true
systemctl stop    xiaomi-gamepad.service 2>/dev/null || true
udevadm trigger --subsystem-match=hidraw --action=add

echo
echo "Installed (on-demand: the daemon runs only while the pad is connected)."
echo "Turn the gamepad on -- it appears as 'Microsoft X-Box 360 pad'."
echo "Verify mapping:  python3 $HERE/tools/xiaomi-verify.py"
