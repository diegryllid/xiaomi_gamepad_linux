#!/usr/bin/env python3
"""
Xiaomi Mi Bluetooth Gamepad (VID:PID 2717:3144) userspace driver for Linux.

Why: the kernel's generic-HID driver maps this pad wrong (right stick dead,
A/B/X/Y scrambled) and exposes no force-feedback. This daemon:
  - reads the pad's RAW HID reports from /dev/hidrawN,
  - EVIOCGRAB's the mis-mapped kernel evdev node so games never see it,
  - presents ONE clean virtual "Microsoft X-Box 360 pad" (045e:028e) with the
    correct button/stick layout AND FF_RUMBLE,
  - forwards rumble to the pad as the documented hidraw packet [0x20][weak][strong],
  - optionally maps the accelerometer to tilt-aim on the right stick, PER GAME (only while a
    process listed in /etc/xiaomi-gamepad/gyro-games.conf is running).

Only the SAFE rumble (0x20) and accel-enable (0x31) packets are ever written -- and the accel one
ONLY for configured games. The destructive 0x22 calibration packet (can power-off / brick) is
NEVER sent.

Run directly for testing:  sudo python3 xiaomi-gamepad.py   (or install via ./install.sh)
"""
import os, re, glob, time, threading, select
import evdev
from evdev import UInput, ecodes as e, AbsInfo

VID, PID = 0x2717, 0x3144
STRONG_CAP = 0xC0          # big motor above this can power the pad off
REPORT_ID = 0x04           # gamepad input report id
RUMBLE_STOP = bytes([0x20, 0x01, 0x01])   # SAFE stop / silent keep-alive. NOTE: [0x20,0,0] is NOT a
                                          # stop -- it POWERS THE PAD OFF (verified). Never send it.
TOXIC_ZERO = bytes([0x20, 0x00, 0x00])    # forbidden packet -- hard-guarded in Rumble._send below
RUMBLE_ENABLED = True      # master switch for rumble output to the pad
RUMBLE_POLL_S = 0.03       # min seconds between rumble writes -- a SINGLE rate-limited writer
                           # (mirrors the reference driver) so FF bursts never flood the BT link
KEEPALIVE_S = 2.0          # idle keep-alive: while the motor is OFF, re-send the SAFE stop this often
                           # so the BT link never sits silent into the ~20s supervision-timeout drop.
                           # This pad briefly stops sending INPUT right after a rumble; with no host
                           # traffic the link then goes quiet and the pad disconnects (and powers off).
                           # The keep-alive both holds the link up AND pokes the pad to resume input.
# Wedge watchdog (LOG-ONLY): this pad reports input ON-CHANGE (not a steady stream), so a gap after a
# rumble is the firmware briefly going quiet. The KEEPALIVE above is the actual fix; this just logs.
# NOTE: keep the STOCK Bluetooth stack -- disabling ERTM/sniff/hidp makes the wedge a hard disconnect.
WEDGE_S = 1.5              # log a wedge if no input arrives this long after a recent rumble
RECENT_RUMBLE_S = 3.0      # only treat an input gap as a wedge if rumble fired within this window
FF_DEBUG = False           # set True for verbose FF + battery logging to the journal

# ---- accelerometer / per-game tilt-aim ----
# Gyro is OFF by default and for EVERY game. It activates ONLY while a process whose command line
# matches a line in GYRO_CONF is running, so non-listed games (e.g. GTA) never see any accel writes.
ACCEL_ON = bytes([0x31, 0x01, 0x08])   # accel ON -- the SAFE packet (the 0x22 calib is NEVER sent)
GYRO_CONF = '/etc/xiaomi-gamepad/gyro-games.conf'   # one process-name substring per line; # = comment
GYRO_POLL_S = 2.0          # how often to check whether a configured gyro-game is running
TILT_SCALE = 200           # tilt magnitude (accel LSB, ~256 = 1g) that maps to FULL stick deflection
TILT_DEADZONE = 16         # ignore tilt below this so a resting hand doesn't drift the aim
TILT_SMOOTH = 0.4          # low-pass 0..1 (higher = snappier) to tame accel jitter
TILT_X_SIGN = -1           # roll: tilt-right reads negative; invert so tilting right aims right
TILT_Y_SIGN = 1            # pitch sign (flip if forward/back feels inverted)
CAL_SAMPLES = 12           # samples averaged to set the "flat" center when gyro turns on

def log(*a): print("[xiaomi-pad]", *a, flush=True)

# ---- locate the pad's nodes by VID:PID (node numbers change across reconnect) ----
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

def find_evdev():
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except OSError:
            continue
        if d.info.vendor == VID and d.info.product == PID:
            return d
        d.close()
    return None

# ---- virtual Xbox 360 pad capabilities (standard xpad layout) ----
def make_uinput():
    cap = {
        e.EV_KEY: [e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y, e.BTN_TL, e.BTN_TR,
                   e.BTN_SELECT, e.BTN_START, e.BTN_MODE, e.BTN_THUMBL, e.BTN_THUMBR],
        e.EV_ABS: [
            (e.ABS_X,    AbsInfo(0, -32768, 32767, 16, 128, 0)),
            (e.ABS_Y,    AbsInfo(0, -32768, 32767, 16, 128, 0)),
            (e.ABS_RX,   AbsInfo(0, -32768, 32767, 16, 128, 0)),
            (e.ABS_RY,   AbsInfo(0, -32768, 32767, 16, 128, 0)),
            (e.ABS_Z,    AbsInfo(0, 0, 255, 0, 0, 0)),     # left trigger
            (e.ABS_RZ,   AbsInfo(0, 0, 255, 0, 0, 0)),     # right trigger
            (e.ABS_HAT0X, AbsInfo(0, -1, 1, 0, 0, 0)),     # dpad
            (e.ABS_HAT0Y, AbsInfo(0, -1, 1, 0, 0, 0)),
        ],
        e.EV_FF: [e.FF_RUMBLE],
    }
    return UInput(cap, name='Microsoft X-Box 360 pad', vendor=0x045e,
                  product=0x028e, version=0x0110, max_effects=16)

def stick(v):                      # 0..255 (center 0x80) -> signed 16-bit
    return max(-32768, min(32767, (v - 128) * 256))

# ---- per-game gyro / tilt-aim ----
def load_gyro_games():
    """Process-name substrings that should get tilt-aim (one per line; '#' = comment). Read live."""
    try:
        with open(GYRO_CONF) as f:
            return [s for s in (ln.split('#', 1)[0].strip() for ln in f) if s]
    except OSError:
        return []

def gyro_game_running(patterns, exclude_pid=None):
    """True if any running process' command line contains any configured substring.
    exclude_pid skips our own daemon, whose cmdline ('...xiaomi-gamepad.py') would otherwise
    self-match substrings like 'gamepad'/'game'/'pad' and pin tilt permanently on."""
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or (exclude_pid is not None and int(pid) == exclude_pid):
            continue
        try:
            with open('/proc/' + pid + '/cmdline', 'rb') as f:
                cmd = f.read().replace(b'\x00', b' ').decode('utf-8', 'replace')
        except OSError:
            continue
        if any(p in cmd for p in patterns):
            return True
    return False

class Tilt:
    """Accelerometer tilt -> right-stick contribution. Active only while a configured game runs.
    Owns its own watcher thread; close() joins it BEFORE the fd is closed (no write to a reused fd)."""
    def __init__(self, fd, write_lock):
        self.fd = fd
        self.write_lock = write_lock      # shared single-writer lock for the hidraw fd (with Rumble)
        self.on = False
        self.enabled_once = False
        self.lock = threading.Lock()      # guards on / center / cal / sx / sy
        self.center = None; self.cal = []; self.sx = 0.0; self.sy = 0.0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()
    def _watch(self):
        me = os.getpid()                  # never match our own cmdline ('...xiaomi-gamepad.py')
        while not self.stop.is_set():
            patterns = load_gyro_games()
            want = bool(patterns) and gyro_game_running(patterns, me)
            if want and not self.on:
                log("gyro-game detected -> tilt-aim ON"); self.enable()
            elif not want and self.on:
                log("gyro-game closed -> tilt-aim off"); self.disable()
            self.stop.wait(GYRO_POLL_S)   # returns immediately once close() sets the event
    def enable(self):
        # SAFE interrupt-channel enable (the rumble path) -- NEVER the control-channel ioctl.
        ok = True
        if not self.enabled_once:
            try:
                with self.write_lock:     # single writer: never overlap a rumble packet
                    os.write(self.fd, ACCEL_ON)
            except OSError as ex:
                log("accel enable write failed:", ex); ok = False
            if ok:
                self.enabled_once = True
        if ok:                            # only activate tilt if the sensor was actually enabled
            with self.lock:
                self.center = None; self.cal = []; self.sx = 0.0; self.sy = 0.0
                self.on = True
    def disable(self):
        with self.lock:
            self.on = False
    def contribution(self, r):
        with self.lock:
            if not self.on or len(r) < 17:
                return (0, 0)
            x = int.from_bytes(r[13:15], 'little', signed=True)   # roll  (tilt left/right)
            y = int.from_bytes(r[15:17], 'little', signed=True)   # pitch (tilt fwd/back)
            if self.center is None:                               # collect the flat baseline first
                self.cal.append((x, y))
                if len(self.cal) >= CAL_SAMPLES:
                    n = len(self.cal)
                    self.center = (sum(p[0] for p in self.cal) / n, sum(p[1] for p in self.cal) / n)
                    self.cal = []
                return (0, 0)
            dx = x - self.center[0]; dy = y - self.center[1]
            dx = 0 if abs(dx) < TILT_DEADZONE else dx
            dy = 0 if abs(dy) < TILT_DEADZONE else dy
            tx = max(-32767, min(32767, TILT_X_SIGN * dx / TILT_SCALE * 32767))
            ty = max(-32767, min(32767, TILT_Y_SIGN * dy / TILT_SCALE * 32767))
            self.sx += (tx - self.sx) * TILT_SMOOTH               # low-pass to tame jitter
            self.sy += (ty - self.sy) * TILT_SMOOTH
            return (int(self.sx), int(self.sy))
    def close(self):
        # stop + JOIN the watcher BEFORE the fd is closed, so enable() can't os.write a reused fd
        self.stop.set()
        try: self.thread.join(timeout=1.0)
        except Exception: pass

def emit_report(ui, r, tilt=None):
    if len(r) < 13 or r[0] != REPORT_ID:
        return
    # Button/axis layout taken verbatim from the proven irungentoo/Xiaomi_gamepad
    # driver (mi/Program.cs) -- the same project ground-truth for this pad (2717:3144):
    #   byte1: A=0x01 B=0x02 X=0x08 Y=0x10 L1=0x40 R1=0x80
    #   byte2: Back=0x04 Start=0x08 L3=0x20 R3=0x40
    #   byte4: dpad hat (15=centered)        byte20: Mi/Logo=0x01
    #   byte5/6/7/8: LX/LY/RX/RY (center 0x80)   byte11/12: L2/R2 analog triggers
    b1, b2, b20 = r[1], r[2], (r[20] if len(r) > 20 else 0)
    k = ui.write
    k(e.EV_KEY, e.BTN_A,      1 if b1 & 0x01 else 0)
    k(e.EV_KEY, e.BTN_B,      1 if b1 & 0x02 else 0)
    k(e.EV_KEY, e.BTN_X,      1 if b1 & 0x08 else 0)
    k(e.EV_KEY, e.BTN_Y,      1 if b1 & 0x10 else 0)
    k(e.EV_KEY, e.BTN_TL,     1 if b1 & 0x40 else 0)   # L1
    k(e.EV_KEY, e.BTN_TR,     1 if b1 & 0x80 else 0)   # R1
    k(e.EV_KEY, e.BTN_SELECT, 1 if b2 & 0x04 else 0)   # Back
    k(e.EV_KEY, e.BTN_START,  1 if b2 & 0x08 else 0)   # Start
    k(e.EV_KEY, e.BTN_THUMBL, 1 if b2 & 0x20 else 0)   # L3
    k(e.EV_KEY, e.BTN_THUMBR, 1 if b2 & 0x40 else 0)   # R3
    k(e.EV_KEY, e.BTN_MODE,   1 if b20 & 0x01 else 0)  # MI/Guide
    k(e.EV_ABS, e.ABS_X,  stick(r[5]))
    k(e.EV_ABS, e.ABS_Y,  stick(r[6]))
    rx, ry = stick(r[7]), stick(r[8])
    if tilt is not None:                 # blend accelerometer tilt into the right stick (per-game)
        tx, ty = tilt.contribution(r)
        rx = max(-32768, min(32767, rx + tx))
        ry = max(-32768, min(32767, ry + ty))
    k(e.EV_ABS, e.ABS_RX, rx)
    k(e.EV_ABS, e.ABS_RY, ry)
    k(e.EV_ABS, e.ABS_Z,  r[11])
    k(e.EV_ABS, e.ABS_RZ, r[12])
    # dpad decode straight from the reference (handles diagonals; 15 = centered)
    h = r[4]
    hx = (1 if h in (1, 2, 3) else 0) - (1 if h in (5, 6, 7) else 0)
    hy = (1 if h in (3, 4, 5) else 0) - (1 if h in (0, 1, 7) else 0)
    k(e.EV_ABS, e.ABS_HAT0X, hx)
    k(e.EV_ABS, e.ABS_HAT0Y, hy)
    ui.syn()

# ---- rumble: forward FF effects to the pad ----
# The firmware rumbles until the NEXT packet. A SINGLE rate-limited writer thread owns every rumble
# write: it polls the desired motor state and writes on change, at most every RUMBLE_POLL_S, so a
# game's rapid FF on/off bursts never flood the link. Both motors are capped. When the motor is IDLE
# it additionally re-sends the SAFE stop every KEEPALIVE_S -- a silent keep-alive that holds the BT
# link up through the brief post-rumble input gap (otherwise: silence -> supervision-timeout drop).
# It NEVER heartbeats during active rumble (that re-buzzes) and NEVER sends [0x20,0,0] (powers off).
# (Set RUMBLE_ENABLED=False to suppress all motor writes while keeping the rest of the daemon.)
class Rumble:
    def __init__(self, hidraw_fd, write_lock):
        self.fd = hidraw_fd
        self.write_lock = write_lock   # shared single-writer lock for the fd (with Tilt's enable)
        self.effects = {}
        self.target = (0, 0)       # desired (weak, strong), set by FF events
        self.written = (0, 0)      # START "already stopped" so the pump writes NOTHING on attach.
                                   # Writing a stop packet on every (re)connect intermittently
                                   # wedged the pad -> connect->wedge->disconnect->reconnect loop.
        self.active = None         # id of the effect currently driving the motor
        self.last_rumble_t = 0.0   # monotonic time of the last NON-stop motor write
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()
    def recent_rumble(self):
        return (time.monotonic() - self.last_rumble_t) < RECENT_RUMBLE_S
    def _set(self, weak, strong):
        with self.lock:
            self.target = (min(weak & 0xFF, STRONG_CAP), min(strong & 0xFF, STRONG_CAP))
    def stop(self):
        with self.lock:
            self.target = (0, 0)
    def play(self, eff):
        rum = getattr(eff.u, 'ff_rumble_effect', None) or getattr(eff.u, 'rumble', None)
        if rum is None: return
        weak, strong = rum.weak_magnitude >> 8, rum.strong_magnitude >> 8
        if FF_DEBUG: log("ff: PLAY weak=%d strong=%d" % (weak, strong))
        if weak == 0 and strong == 0:
            self.stop()
        else:
            self.active = getattr(eff, 'id', None)
            self._set(weak, strong)
    def update(self, eff):
        # a re-upload that modifies the active effect (e.g. Wine setting it to 0) must take effect
        if self.active is not None and getattr(eff, 'id', None) == self.active:
            self.play(eff)
    def _send(self, pkt):
        # Rumble = OUTPUT report on the interrupt channel (a plain hidraw write, fire-and-forget) --
        # the same path xpadneo / DS4 / SDL use. Do NOT use HIDIOCSFEATURE / SET_REPORT (the control
        # channel): it round-trips a blocking device handshake that stalls this pad under load. The
        # descriptor declares report 0x20 Feature-only, but the firmware still actuates on this write.
        if pkt == TOXIC_ZERO:          # hard safety: [0x20,0,0] powers this pad OFF -- never emit it
            return
        with self.write_lock:          # single writer: never overlap the accel-enable packet
            os.write(self.fd, pkt)
    def _pump(self):
        # Write on change; PLUS a silent idle keep-alive. The active rumble itself keeps the link
        # warm, so we re-send nothing while the motor is on (re-sending re-buzzes). But the moment
        # rumble ends this pad can briefly stop sending input -- if the host also goes quiet the link
        # sits silent into a ~20s supervision-timeout drop. So while IDLE we re-send the SAFE stop
        # (RUMBLE_STOP, silent + verified harmless) every KEEPALIVE_S to hold the link and poke the
        # pad back. The toxic [0x20,0,0] is never produced here and is hard-guarded in _send.
        # seed to NOW so the first idle keep-alive waits a full KEEPALIVE_S -- never write on attach
        # (the pad is already streaming input then; a stop-write on attach re-creates the documented
        # connect -> wedge -> disconnect -> reconnect loop the self.written=(0,0) guard exists to stop)
        last_write = time.monotonic()
        while self.running:
            with self.lock:
                tgt = self.target
            changed = (tgt != self.written)
            now = time.monotonic()
            keepalive = (RUMBLE_ENABLED and not changed and tgt == (0, 0)
                         and (now - last_write) >= KEEPALIVE_S)
            if changed or keepalive:
                if changed:
                    self.written = tgt
                    if tgt != (0, 0):
                        self.last_rumble_t = now            # for the wedge watchdog
                if RUMBLE_ENABLED:
                    pkt = RUMBLE_STOP if tgt == (0, 0) else bytes([0x20, tgt[0], tgt[1]])
                    try:
                        self._send(pkt)
                        last_write = now
                    except OSError as ex:
                        if FF_DEBUG: log("rumble write failed:", ex)
                if FF_DEBUG and changed: log("ff: motor ->", tgt)
            time.sleep(RUMBLE_POLL_S)
    def close(self):
        # stop the pump BEFORE the fd closes (never write to a closed/reused fd), motor off
        self.running = False
        try: self.thread.join(timeout=0.3)
        except Exception: pass
        # only send a stop if the motor was actually running -- avoid a needless write that could
        # wedge the pad on a clean detach
        if RUMBLE_ENABLED and self.written not in (None, (0, 0)):
            try: self._send(RUMBLE_STOP)
            except OSError: pass

def ff_loop(ui, rumble):
    for ev in ui.read_loop():
        # crash-proof: a bad event must NEVER kill this thread and leave the motor latched on
        try:
            if ev.type == e.EV_UINPUT:
                if ev.code == e.UI_FF_UPLOAD:
                    up = ui.begin_upload(ev.value)
                    up.retval = 0
                    eff = up.effect
                    rumble.effects[eff.id] = eff
                    ui.end_upload(up)
                    rumble.update(eff)
                elif ev.code == e.UI_FF_ERASE:
                    er = ui.begin_erase(ev.value)
                    er.retval = 0
                    rumble.effects.pop(er.effect_id, None)
                    ui.end_erase(er)
                    if rumble.active == er.effect_id:
                        rumble.stop()
            elif ev.type == e.EV_FF:
                if ev.value:
                    eff = rumble.effects.get(ev.code)
                    if eff: rumble.play(eff)
                else:
                    rumble.stop()
        except Exception as ex:
            log("ff event error (continuing):", ex)
            rumble.stop()

def run_once():
    """Attach to the pad if present, run until it disconnects. Returns False if no pad."""
    hidraw_path = find_hidraw()
    real = find_evdev()
    if not hidraw_path or not real:
        return False
    log("pad found -> hidraw:", hidraw_path, "| kernel evdev:", real.path)
    fd = os.open(hidraw_path, os.O_RDWR)
    ui = None; rumble = None; tilt = None; grabbed = False
    try:
        try:
            real.grab(); grabbed = True   # hide the mis-mapped kernel device from games
            log("grabbed kernel device (games won't see the broken mapping)")
        except OSError as ex:
            log("warning: could not grab kernel device:", ex)
        ui = make_uinput()
        log("virtual pad up:", ui.device.path, "-> 'Microsoft X-Box 360 pad' (045e:028e) with rumble")
        write_lock = threading.Lock()  # one writer at a time on the hidraw fd (rumble + accel-enable)
        rumble = Rumble(fd, write_lock)
        threading.Thread(target=ff_loop, args=(ui, rumble), daemon=True).start()
        tilt = Tilt(fd, write_lock)    # per-game gyro; owns its own watcher thread
        last_batt = None; wedged = False
        while True:
            rlist, _, _ = select.select([fd], [], [], WEDGE_S)
            if not rlist:
                # this pad reports input ON-CHANGE, so a gap after a rumble is the firmware briefly
                # going quiet (a hardware quirk that hits Windows too). We do NOT force-disconnect --
                # that powers the pad OFF. Just LOG it; the Rumble idle keep-alive (every KEEPALIVE_S)
                # is what actually holds the link up and pokes the pad to resume input.
                if rumble and rumble.recent_rumble() and not wedged:
                    log("pad WEDGED (no input %.1fs after a rumble) -- waiting for BT auto-recover"
                        % WEDGE_S)
                    wedged = True
                continue
            wedged = False
            data = os.read(fd, 64)        # raw HID report is ready
            if not data:
                break
            emit_report(ui, data, tilt)
            if FF_DEBUG and len(data) > 19 and data[19] != last_batt:
                last_batt = data[19]      # buf[19] = battery level
                log("battery byte[19] =", data[19])
    except OSError as ex:
        log("pad disconnected:", ex)
    finally:
        if tilt:
            try: tilt.close()         # join the watcher BEFORE os.close(fd) -- no write to a reused fd
            except Exception: pass
        if rumble:
            try: rumble.close()
            except Exception: pass
        if grabbed:
            try: real.ungrab()
            except Exception: pass
        if ui:
            try: ui.close()
            except Exception: pass
        try: os.close(fd)
        except Exception: pass
        log("detached, waiting for pad")
    return True

def main():
    # service-friendly: wait for the pad, attach, and re-attach on every reconnect
    log("xiaomi-gamepad daemon started; waiting for pad 2717:3144")
    while True:
        try:
            if not run_once():
                time.sleep(2)
        except Exception as ex:
            log("error (retrying):", ex)
            time.sleep(2)

if __name__ == '__main__':
    main()
