#!/usr/bin/env python3
# Fire rumble on the virtual Xbox360 pad repeatedly -- test rumble + reproduce the pad's wedge
# WITHOUT launching a game. Run as your normal user (the virtual pad is user-accessible).
#   python3 tools/rumble-test.py [count] [gap_seconds]
# e.g.  python3 tools/rumble-test.py 40 1.0
import evdev, time, sys
from evdev import ff, ecodes

def find_virtual():
    for p in evdev.list_devices():
        try:
            d = evdev.InputDevice(p)
        except OSError:
            continue
        if d.info.vendor == 0x045e and d.info.product == 0x028e:
            return d
        d.close()
    return None

dev = find_virtual()
if not dev:
    print("Virtual Xbox360 pad not found. Is the daemon running and the pad on?")
    print("  check:  systemctl status xiaomi-gamepad")
    raise SystemExit(1)

count = int(sys.argv[1]) if len(sys.argv) > 1 else 40
gap   = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
print("Rumbling on %s (%s).  %d pulses, %.1fs apart." % (dev.path, dev.name, count, gap))
print("Watch the pad: it should buzz on each pulse. If it goes dead / disconnects, note the pulse #.\n")

# strong + weak rumble, 300 ms each (scaled by the daemon to motor bytes)
effect = ff.Effect(
    ecodes.FF_RUMBLE, -1, 0,
    ff.Trigger(0, 0),
    ff.Replay(300, 0),
    ff.EffectType(ff_rumble_effect=ff.Rumble(strong_magnitude=0xC000, weak_magnitude=0x8000)),
)
eid = dev.upload_effect(effect)
try:
    for i in range(1, count + 1):
        print("  pulse %2d/%d  -> buzz" % (i, count), flush=True)
        dev.write(ecodes.EV_FF, eid, 1)   # play once
        time.sleep(gap)
finally:
    try:
        dev.erase_effect(eid)
    except Exception:
        pass
print("\ndone.")
