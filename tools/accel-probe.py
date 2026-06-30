#!/usr/bin/env python3
# Probe the Xiaomi pad's ACCELEROMETER. Prints HID report bytes [11..18] + the int16 decode at the
# two candidate offsets as you TILT the pad, so we can confirm the layout WITHOUT touching the daemon.
# Run as root (hidraw is root-only here):
#     sudo python3 ~/accel-probe.py            # first: is accel already streaming?
#     sudo python3 ~/accel-probe.py --enable   # only if NOT: send the accel-enable feature report
import os, re, glob, sys, struct, fcntl

def find_hidraw():
    for h in glob.glob('/sys/class/hidraw/hidraw*'):
        try: u = open(os.path.join(h, 'device/uevent')).read()
        except OSError: continue
        m = re.search(r'HID_ID=\w+:0*([0-9A-Fa-f]+):0*([0-9A-Fa-f]+)', u)
        if m and int(m.group(1), 16) == 0x2717 and int(m.group(2), 16) == 0x3144:
            return '/dev/' + os.path.basename(h)
    return None

path = find_hidraw()
if not path:
    print("pad hidraw not found (is the pad on?)"); sys.exit(1)
fd = os.open(path, os.O_RDWR)

if '--enable' in sys.argv or '--enable-ioctl' in sys.argv:
    pkt = bytes([0x31, 0x01, 0x08])     # accel ON -- the SAFE packet (0x22 calib is NEVER sent)
    if '--enable-ioctl' in sys.argv:    # the CONTROL-channel path -- known to destabilise this pad
        HIDIOCSFEATURE = lambda n: 0xC0000000 | (n << 16) | (ord('H') << 8) | 0x06
        try:
            fcntl.ioctl(fd, HIDIOCSFEATURE(len(pkt)), pkt)
            print(">>> enabled via SET_FEATURE ioctl (CONTROL channel -- the risky path)")
        except OSError as ex:
            print(">>> ioctl returned:", ex, "(continuing)")
    else:                               # the SAFE interrupt-channel path, exactly like rumble
        try:
            os.write(fd, pkt)
            print(">>> enabled via os.write (INTERRUPT channel -- the safe path, like rumble)")
        except OSError as ex:
            print(">>> os.write enable failed:", ex)

print("reading", path)
print("Hold the pad FLAT and STILL for the baseline, then TILT it slowly: left/right, then fwd/back.")
print("Look for byte-pairs that swing while triggers (b[11]/b[12]) stay put.\n")

def show(d, tag=""):
    seg = ' '.join('%02x' % b for b in d[11:19])
    a13 = struct.unpack_from('<hhh', d, 13) if len(d) >= 19 else (0, 0, 0)
    a12 = struct.unpack_from('<hhh', d, 12) if len(d) >= 18 else (0, 0, 0)
    print("  b[11..18]=%s   int16@13=%s  @12=%s %s" % (seg, a13, a12, tag), flush=True)

base = os.read(fd, 64)
show(base, "(baseline)")
last = base[11:19]
while True:
    d = os.read(fd, 64)
    if d[11:19] != last:        # only print when the accel/trigger region changes
        show(d); last = d[11:19]
