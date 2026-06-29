#!/usr/bin/env bash
# Remove the Xiaomi gamepad driver (service, binary, udev rule).
set -e
[ "$(id -u)" = 0 ] || { echo "run with sudo:  sudo ./uninstall.sh"; exit 1; }

systemctl disable --now xiaomi-gamepad.service 2>/dev/null || true
rm -fv /etc/systemd/system/xiaomi-gamepad.service \
       /usr/local/bin/xiaomi-gamepad.py \
       /etc/udev/rules.d/99-xiaomi-gamepad-hide.rules \
       /etc/modules-load.d/uinput.conf
systemctl daemon-reload
udevadm control --reload
echo "Uninstalled. (The pad's real input nodes are no longer hidden.)"
