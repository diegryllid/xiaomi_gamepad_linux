#!/usr/bin/env python3
# Verify the VIRTUAL Xbox360 pad -- i.e. exactly what GTA/Wine will receive.
# Run as your NORMAL user (no sudo); the daemon must be running. Press one input
# at a time and watch the label. Ctrl-C when done.
import evdev
from evdev import ecodes as e

KEYNAMES = {
    e.BTN_A: 'A  (menu accept)', e.BTN_B: 'B  (menu cancel)',
    e.BTN_X: 'X', e.BTN_Y: 'Y',
    e.BTN_TL: 'L1', e.BTN_TR: 'R1',
    e.BTN_SELECT: 'BACK/Select', e.BTN_START: 'START',
    e.BTN_THUMBL: 'L3 (left stick click)', e.BTN_THUMBR: 'R3 (right stick click)',
    e.BTN_MODE: 'GUIDE/Mi',
}

def find_virtual():
    for p in evdev.list_devices():
        try:
            d = evdev.InputDevice(p)
        except OSError:
            continue          # skips the now-root-only real pad
        if d.info.vendor == 0x045e and d.info.product == 0x028e:
            return d
        d.close()
    return None

d = find_virtual()
if not d:
    print("Virtual Xbox360 pad not found. Is the pad on + daemon running?")
    print("  check:  systemctl status xiaomi-gamepad")
    raise SystemExit(1)

print("Reading virtual pad:", d.path, "(" + d.name + ")")
print("This is EXACTLY what the game receives.\n")
print("Press, one at a time:  A B X Y, dpad U/D/L/R, L1 R1, L2 R2,")
print("RIGHT STICK (push 4 dirs), L3 R3, Back, Start.\n")

right_alive = False
for ev in d.read_loop():
    if ev.type == e.EV_KEY and ev.value in (0, 1):
        label = KEYNAMES.get(ev.code, 'KEY?%d' % ev.code)
        print(("  PRESS    -> " if ev.value else "  (release)  ") + label, flush=True)
    elif ev.type == e.EV_ABS:
        if ev.code == e.ABS_HAT0Y and ev.value:
            print("  DPAD     -> " + ("UP" if ev.value < 0 else "DOWN"), flush=True)
        elif ev.code == e.ABS_HAT0X and ev.value:
            print("  DPAD     -> " + ("LEFT" if ev.value < 0 else "RIGHT"), flush=True)
        elif ev.code == e.ABS_Z and ev.value > 30:
            print("  L2 trigger -> %d" % ev.value, flush=True)
        elif ev.code == e.ABS_RZ and ev.value > 30:
            print("  R2 trigger -> %d" % ev.value, flush=True)
        elif ev.code in (e.ABS_RX, e.ABS_RY) and abs(ev.value) > 14000 and not right_alive:
            right_alive = True
            print("  RIGHT STICK is ALIVE  (axis %s = %d)" % (
                'X' if ev.code == e.ABS_RX else 'Y', ev.value), flush=True)
