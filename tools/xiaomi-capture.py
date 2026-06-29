#!/usr/bin/env python3
# Capture the Xiaomi pad's raw HID report layout: prints which bytes change
# (vs a resting baseline) as you press each input. Run with the daemon STOPPED.
import os, re, glob

def find_hidraw():
    for h in glob.glob('/sys/class/hidraw/hidraw*'):
        try: u = open(os.path.join(h, 'device/uevent')).read()
        except OSError: continue
        m = re.search(r'HID_ID=\w+:0*([0-9A-Fa-f]+):0*([0-9A-Fa-f]+)', u)
        if m and int(m.group(1),16) == 0x2717 and int(m.group(2),16) == 0x3144:
            return '/dev/' + os.path.basename(h)
    return '/dev/hidraw1'

path = find_hidraw()
fd = os.open(path, os.O_RDONLY)
print("reading", path, "- keep the pad UNTOUCHED for the baseline...", flush=True)
base = os.read(fd, 64)
print("baseline (" + str(len(base)) + " bytes): " + ' '.join('%02x' % b for b in base), flush=True)
print("Now press ONE input at a time. Changed bytes shown as [index]=value:", flush=True)
last = None
while True:
    d = os.read(fd, 64)
    diff = [(i, d[i]) for i in range(min(len(d), len(base))) if d[i] != base[i]]
    key = tuple(diff)
    if diff and key != last:
        print('  ' + '  '.join('[%d]=0x%02x(%d)' % (i, v, v) for i, v in diff), flush=True)
        last = key
