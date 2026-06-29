# Gamepad Setup Runbook (Morphius / GEM10)

How controllers are made to "just work" in any Lutris/Wine game on this machine, how to
add a new pad, and the per-game gotchas (especially old games like GTA SA).

---

## The architecture (why it's universal)

Instead of fixing each game, we fix the pad **once at the device level** and present a
clean, standard controller to the whole system:

```
 real pad (quirky HID)                       games see ONLY this
 ───────────────────────                     ──────────────────────────
 /dev/hidraw1  ─┐                             /dev/input/event21  (045e:028e
 /dev/input/event20  ── root daemon ──────▶   "Microsoft X-Box 360 pad")
 /dev/input/js1  ─┘   reads raw HID,          + FF_RUMBLE
                      emits clean Xbox360
```

- A **root daemon** reads the real pad's raw HID, and via `uinput` presents a virtual
  **"Microsoft X-Box 360 pad" (045e:028e)** with the correct button/axis map **and** rumble.
- The real pad's own nodes (`event20`, `js1`, `hidraw1`) are **hidden from userspace**
  (root-only) by a udev rule, so games can't accidentally read the broken kernel mapping.
- Result: **any game that supports an Xbox 360 controller works** with no per-game config,
  because that's literally what it sees. This is the right layer to fix it at.

### Files

| File | Purpose |
|---|---|
| `~/.local/bin/xiaomi-gamepad.py` | the daemon: HID read → virtual Xbox360 pad + rumble |
| `~/xiaomi-gamepad-install.sh` | installs it as a systemd **system** service (runs as root) |
| `~/xiaomi-hide-install.sh` | writes the udev rule + hides the real pad's nodes |
| `/etc/systemd/system/xiaomi-gamepad.service` | the service unit |
| `/etc/udev/rules.d/99-xiaomi-gamepad-hide.rules` | hides real pad nodes on every reconnect |
| `~/xiaomi-capture.py` | diagnostic: dump which raw HID bytes change per button |
| `~/xiaomi-verify.py` | **verify the VIRTUAL pad** = exactly what the game receives |

### Service control
```
systemctl status  xiaomi-gamepad
sudo systemctl restart xiaomi-gamepad
journalctl -u xiaomi-gamepad -e
```

---

## Verifying a pad (do this BEFORE blaming a game)

```
python3 ~/xiaomi-verify.py      # press each button; shows the Xbox control the GAME gets
```
If this shows the correct mapping, the pad layer is done. Any remaining problem is
**game-side**, not pad-side. (This decoupling saved us hours — see "Lessons" below.)

---

## Adding a NEW controller

1. Pair it; find its IDs: `cat /proc/bus/input/devices` (note `Vendor=`/`Product=` and the
   `Handlers=` line → its `eventN`/`jsN`), and `HID_ID` under `/sys/class/hidraw/*/device/uevent`.
2. **Does the kernel already map it correctly?** Run `python3 ~/xiaomi-verify.py` adapted to
   its VID:PID, or `evtest`. Many modern pads need nothing.
3. If the mapping is wrong, get the **authoritative byte map** — search for an existing driver
   (we used `github.com/irungentoo/Xiaomi_gamepad`, `mi/Program.cs`) or the SDL
   `gamecontrollerdb.txt` entry. Don't hand-reverse from a single noisy capture.
4. Copy `xiaomi-gamepad.py` → `<pad>-gamepad.py`, set `VID/PID`, rewrite `emit_report()` and
   the rumble packet per that pad's protocol, install as a service, add a hide-rule.

> **Safety:** only ever write **known-safe** HID packets. For the Xiaomi pad: `0x20` (rumble,
> cap strong motor ≤0xC0) and `0x31` (enable accelerometer) are safe; **NEVER send `0x22`
> (calibration) — it can power-off / brick the pad.**

---

## Per-game notes

### Modern games (native Linux, Proton, most Wine games)
Nothing to do — they read the virtual Xbox360 pad via SDL/evdev/xinput and just work.

### Old Wine games that need an "ASI" mod for controllers (e.g. **GTA San Andreas**)
GTA SA (2005) predates XInput and mis-maps any pad with its native DirectInput. The fix is the
**GInput** mod, loaded by an **ASI loader**. Two requirements that are easy to miss:

1. **The ASI loader must actually be injected.** It's `dinput8.dll` (Ultimate ASI Loader) in
   the game folder, BUT Wine only loads it if the prefix has a DLL override:
   ```
   [Software\Wine\DllOverrides]   "dinput8"="native,builtin"
   ```
   **Gotcha we hit:** Lutris's `wine.overrides: {dinput8: native,builtin}` was NOT in the
   prefix registry, so Wine used its *builtin* dinput8 and **no ASI loaded** (no modloader,
   no SilentPatch, no GInput). Tell-tale: **no `modloader.log` is ever created.**
   Fix = add the override to `prefix/user.reg` (and/or set it in Lutris).
2. **GInput needs to see an XInput controller** — which our virtual Xbox360 pad provides.
   GInput config: `modloader/GInput/GInputSA.ini` (`Vibration=1`, `PlayStationButtons=0`).

**Diagnosing "controller does nothing / old mapping" in an ASI game:**
- `find <gamedir> -iname '*.log'` → if there's **no `modloader.log`**, the ASI chain isn't
  loading → fix the `dinput8` override first.
- If `modloader.log` exists and lists GInput but the pad is still wrong → it's an
  XInput-enumeration problem (does Wine see the virtual pad? check `wine control joy.cpl`).

---

## "Is there a Steam-Input-like layer for Linux?" — yes, several

Our device-level virtual pad already gives **universal** compatibility (the main thing Steam
Input is used for). The per-game-profile tools are complementary:

| Tool | What it is | Fit here |
|---|---|---|
| **SDL `gamecontrollerdb.txt`** (`SDL_GAMECONTROLLERCONFIG`) | community DB of controller mappings every SDL game reads | closest to "per-device compatibility DB"; fixes a pad for ALL SDL games at once |
| **Steam Input** (add non-Steam game to Steam) | the real thing: per-game profiles, remap, gyro→mouse, radial menus | works on Linux even for Lutris games — but pulls in Steam (we avoid it here) |
| **input-remapper** (sezanzeb) | **GTK3** GUI, per-device presets, gamepad→key/mouse/macro | fits this GTK3/anti-Qt desktop; good for remap profiles |
| **AntiMicroX** | gamepad→keyboard/mouse, per-profile | powerful but **Qt** (against this desktop's GTK-only rule) |
| **JoyShockMapper / JSM** | gyro/flick-stick mapper, CLI | great for gyro pads — *this* pad is accel-only, so limited |
| **evsieve** | scriptable CLI evdev remapper | lightweight, fits minimalist setups; good for one-off fixes |

**Recommendation for this machine:** keep the device-level virtual-pad daemon as the base
(universal, no Steam), and reach for **input-remapper** (GTK3) only if a specific game needs a
custom remap/profile. Use the **SDL gamecontrollerdb** route if a pad is wrong only in
SDL-native games.

---

## Future: accelerometer ("gyro") support — pad is ACCEL-ONLY

Research (workflow `xiaomi-gyro-research`) concluded this pad has a **3-axis accelerometer, no
true gyroscope** — so tilt, not angular rate. Plan when implemented:
- Enable via Set-Feature report `[0x31][0x01][0x08]` on the hidraw fd (ioctl may "fail" but
  still works — swallow the error). Disable = `[0x31][0x00][0x00]`.
- Accel = 3× int16 LE at **bytes 13/15/17** of the 21-byte report (verify empirically; the
  alt offset is 12/14/16). Self-calibrate scale from the rest gravity vector.
- Expose as **tilt → right stick (ABS_RX/RY)**, blended additively with the physical stick —
  NOT a second mouse device (Wine drops invented motion axes; ABS_RX/RY survives). On/off toggle.

---

## Lessons (what wasted time, so it doesn't again)

1. **Verify the virtual pad directly** (`xiaomi-verify.py`) before ever testing in-game. A
   pad can be perfect while the game still misbehaves for unrelated reasons.
2. **`EVIOCGRAB` only grabs the evdev node.** The same pad's `js*` (legacy joystick) and
   `hidraw` are separate paths Wine can still read — hide ALL of them (udev, root-only).
3. **No `modloader.log` == the ASI chain isn't loading.** Check the `dinput8` override in the
   prefix registry, not just the Lutris config.
4. Get mappings from an **existing driver / SDL DB**, not a single hand capture (one missed
   press shifts the whole map by one).
