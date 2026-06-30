#!/usr/bin/env python3
# DECISIVE test: does the daemon's REAL in-game rumble pattern (short buzz -> regular STOP) power
# the pad off, and after how many pulses? Fires 8 pulses SLOWLY (one every 2s), each clearly
# numbered, so you can watch the pad's LED and report the exact pulse where it dies.
#
# This is exactly what a game does: a short rumble burst followed by the [0x20,0x01,0x01] stop.
# Slow cadence = you can count. No fast multi-trial ambiguity, no reliance on lagged auto-detection.
#
# SAFE: only 0x20 OUTPUT reports via os.write. NEVER the 0x22 calib packet, NEVER [0x20,0,0]
# (proven toxic). Strong motor 0x60, under the 0xC0 cap.
#
# Run as root:   sudo python3 ~/wedge-trigger-test.py
import os, re, glob, time, subprocess

VID, PID = 0x2717, 0x3144
RUMBLE = bytes([0x20, 0x00, 0x60])
STOP   = bytes([0x20, 0x01, 0x01])
PULSES = 8

def find_hidraw():
    for h in glob.glob('/sys/class/hidraw/hidraw*'):
        try:
            u = open(os.path.join(h, 'device/uevent')).read()
        except OSError:
            continue
        m = re.search(r'HID_ID=\w+:0*([0-9A-Fa-f]+):0*([0-9A-Fa-f]+)', u)
        if m and int(m.group(1), 16) == VID and int(m.group(2), 16) == PID:
            return '/dev/' + os.path.basename(h)
    return None

print(">>> stopping daemon (sole owner of the pad)...")
subprocess.run(["systemctl", "stop", "xiaomi-gamepad"], check=False)
time.sleep(1.0)
try:
    if not find_hidraw():
        print(">>> ⚡ TURN THE PAD ON (waiting up to 90s)...")
    path = None
    for _ in range(180):
        path = find_hidraw()
        if path: break
        time.sleep(0.5)
    if not path:
        print("!!! pad never appeared; aborting."); raise SystemExit(1)
    print(">>> pad at", path)
    fd = os.open(path, os.O_RDWR)
    print("\n=== firing %d short pulses, one every 2s. WATCH THE LED. ===\n" % PULSES)
    for i in range(1, PULSES + 1):
        if not find_hidraw():
            print("   pad node GONE before pulse %d (it died on/around pulse %d)" % (i, i - 1))
            break
        print(">>> PULSE %d/%d  -- short buzz now" % (i, PULSES))
        try:
            os.write(fd, RUMBLE); time.sleep(0.15); os.write(fd, STOP)
        except OSError as ex:
            print("   write errored on pulse %d (pad died): %s" % (i, ex)); break
        time.sleep(1.85)
    print("\n>>> sequence done. Leaving motor stopped.")
    try: os.write(fd, STOP)
    except OSError: pass
    try: os.close(fd)
    except OSError: pass
finally:
    print(">>> restarting daemon...")
    subprocess.run(["systemctl", "start", "xiaomi-gamepad"], check=False)
print(">>> Tell me: did the LED go off, and on which PULSE NUMBER? Or did all 8 survive?")
