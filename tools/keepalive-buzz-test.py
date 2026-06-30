#!/usr/bin/env python3
# Confirm the idle keep-alive packet [0x20,0x01,0x01] keeps the link warm WITHOUT buzzing.
# Phase 1: 2 real buzzes (your reference for "buzz"). Phase 2: ten [0x20,0x01,0x01] pokes, 1s apart.
#
# SAFE: only 0x20 OUTPUT reports via os.write. NEVER [0x20,0,0] (proven toxic), NEVER the 0x22 calib.
# Run as root:   sudo python3 ~/keepalive-buzz-test.py
import os, re, glob, time, subprocess

VID, PID = 0x2717, 0x3144
BUZZ  = bytes([0x20, 0x00, 0x60])   # gentle reference buzz
STOP  = bytes([0x20, 0x01, 0x01])   # the safe stop == candidate keep-alive

def find_hidraw():
    for h in glob.glob('/sys/class/hidraw/hidraw*'):
        try: u = open(os.path.join(h, 'device/uevent')).read()
        except OSError: continue
        m = re.search(r'HID_ID=\w+:0*([0-9A-Fa-f]+):0*([0-9A-Fa-f]+)', u)
        if m and int(m.group(1), 16) == VID and int(m.group(2), 16) == PID:
            return '/dev/' + os.path.basename(h)
    return None

print(">>> stopping daemon...")
subprocess.run(["systemctl", "stop", "xiaomi-gamepad"], check=False)
time.sleep(1.0)
try:
    if not find_hidraw(): print(">>> ⚡ TURN THE PAD ON...")
    path = None
    for _ in range(180):
        path = find_hidraw()
        if path: break
        time.sleep(0.5)
    if not path: print("!!! pad not found; aborting."); raise SystemExit(1)
    print(">>> pad at", path)
    fd = os.open(path, os.O_RDWR)

    print("\n=== PHASE 1: CALIBRATION -- you should FEEL 2 buzzes ===")
    for i in range(2):
        print("   buzz", i + 1); os.write(fd, BUZZ); time.sleep(0.4); os.write(fd, STOP); time.sleep(0.8)

    time.sleep(1.0)
    print("\n=== PHASE 2: KEEP-ALIVE -- ten [0x20,0x01,0x01] pokes, 1s apart ===")
    print("    >>> report: do you feel/hear ANYTHING, or dead silent? <<<")
    for i in range(10):
        print("   poke", i + 1, "/10")
        if not find_hidraw(): print("   !! pad died at poke", i + 1); break
        os.write(fd, STOP); time.sleep(1.0)

    try: os.close(fd)
    except OSError: pass
finally:
    print("\n>>> restarting daemon...")
    subprocess.run(["systemctl", "start", "xiaomi-gamepad"], check=False)
print(">>> Report: Phase 2 -- silent or buzzing? And did the pad stay on all 10 pokes?")
