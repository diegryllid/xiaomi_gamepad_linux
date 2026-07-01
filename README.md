# xiaomi_gamepad_linux

A small **userspace Linux driver** for the **Xiaomi Mi Bluetooth Gamepad** (`小米蓝牙手柄`, USB/BT
**VID `0x2717` PID `0x3144`**) that re-presents it as a clean, correctly-mapped **virtual Xbox 360
controller** — with working **rumble** — so the pad just works in any game (SDL / XInput / Proton /
Wine / Lutris).

Out of the box the kernel's generic HID driver maps this pad **wrong** — scrambled A/B/X/Y, a dead
right stick — and exposes **no force feedback**. This daemon reads the pad's raw HID, hides the
broken kernel device, and serves a standard `Microsoft X-Box 360 pad` in its place.

## Features

- ✅ Correct **button / stick / trigger / D-pad** mapping
- ✅ **Rumble** (force feedback) over Bluetooth
- ✅ Shows up as a standard **Xbox 360 pad** → works in anything that supports one
- ✅ **Hides** the mis-mapped kernel device so games never bind to it
- ✅ Auto-attaches on connect, survives reconnects, runs as a **systemd** service

## How it works

```
  real pad (quirky HID)                         games / SDL / Wine see ONLY this
  ────────────────────────                      ───────────────────────────────
  /dev/hidrawN  ─┐                              /dev/input/eventN   (045e:028e
  /dev/input/eventN ── root daemon ─────────▶   "Microsoft X-Box 360 pad")
  /dev/input/jsN  ─┘   reads raw HID,           + FF_RUMBLE
                       re-maps, forwards FF
```

- A **root daemon** reads the pad's raw HID reports from `/dev/hidrawN`.
- It `EVIOCGRAB`s the kernel's mis-mapped evdev node, and a **udev rule** makes the real pad's
  `event*` / `js*` / `hidraw` nodes root-only — so games can't see the broken mapping.
- It presents **one** clean virtual `Microsoft X-Box 360 pad` (`045e:028e`) via **`uinput`**, with
  `FF_RUMBLE`.
- Rumble is forwarded to the pad as an **OUTPUT report on the interrupt channel** (`0x20 weak strong`).

## Requirements

- Linux with `uinput`
- **`python-evdev`** (`pip install evdev`, or your distro package, e.g. `python-evdev` on Arch)
- The pad paired over Bluetooth (BlueZ)

## Install

```sh
git clone https://github.com/diegryllid/xiaomi_gamepad_linux
cd xiaomi_gamepad_linux
sudo ./install.sh
```

Turn the gamepad on — it appears as **`Microsoft X-Box 360 pad`**. Verify every control maps right:

```sh
python3 tools/xiaomi-verify.py     # press each button; it prints the Xbox control the game receives
```

## Mapping (verified)

| Physical | Xbox control | HID source |
|---|---|---|
| A / B / X / Y | A / B / X / Y | byte1 `0x01` / `0x02` / `0x08` / `0x10` |
| L1 / R1 | LB / RB | byte1 `0x40` / `0x80` |
| L2 / R2 | LT / RT (analog) | byte11 / byte12 |
| Back / Start | Back / Start | byte2 `0x04` / `0x08` |
| L3 / R3 | left/right stick click | byte2 `0x20` / `0x40` |
| D-pad | hat | byte4 (8-way, `15` = centered) |
| Left stick | left stick | byte5 / byte6 |
| Right stick | right stick | byte7 / byte8 |
| Mi / Logo | Guide | byte20 `0x01` |

## ⚠️ Rumble — how the drops were actually fixed

This pad has a firmware quirk: **a rumble write briefly makes it stop sending input**, and it reports
input **on-change** (not as a steady stream). With a naive driver that only writes rumble on-change,
the host *also* goes quiet once a rumble ends → the BT link sits silent → after the ~20 s **link
supervision timeout** the pad **disconnects and powers itself off**. Two things fix it, both required:

1. **A daemon idle keep-alive (the real fix).** While the motor is idle the rumble pump re-sends the
   SAFE stop packet every `KEEPALIVE_S` (2 s) — a *silent* write that keeps the link warm and pokes
   the pad to resume input, so the post-rumble gap never grows into a supervision-timeout drop. It is
   **idle-only** (re-sending during active rumble would re-buzz the motor) and is deferred past attach.
2. **The stock BlueZ + kernel Bluetooth stack.** Do **not** "optimize" it: don't disable L2CAP
   **ERTM** (`disable_ertm=1`), **sniff** (`IdleTimeout=0`), force kernel **`hidp`**
   (`UserspaceHID=false`), or disable **USB autosuspend**. Each makes the brief wedge a *hard*
   disconnect — ERTM's reliable L2CAP retransmission is what lets the link ride the quirk out.

> **Packet safety (hardware-verified):** rumble/stop are `[0x20][weak][strong]` OUTPUT reports on the
> **interrupt** channel (`os.write`), strong motor capped at `0xC0`. The stop is `[0x20,0x01,0x01]`.
> **`[0x20,0x00,0x00]` is never sent — it POWERS THE PAD OFF** (hard-guarded in the daemon). Never use
> the control channel (`HIDIOCSFEATURE`/`SET_REPORT`) — it wedges this pad. (`tools/wedge-trigger-test.py`
> and `tools/keepalive-buzz-test.py` are the probes used to establish all of this.)

## Tested on

- **Pad:** Xiaomi Mi Bluetooth Gamepad, `2717:3144`. The behaviour the rumble fix relies on — input
  reported **on-change**, the brief **post-rumble input gap**, and **`[0x20,0,0]` powering the pad
  off** — are firmware properties of *this* pad, so they hold on any host.
- **Host Bluetooth:** Intel **AX200** (USB `8087:0029`, firmware `ibt-20-1-3` v193-33.24), **BlueZ
  5.86**, kernel **7.1.x** (Arch / CachyOS).

The **idle keep-alive** targets the *pad's* quirk and should help regardless of host. But the ~20 s
**link-supervision timeout** and the "keep the stock stack, don't disable ERTM" guidance are
properties of the **host** Bluetooth adapter + BlueZ — on a different BT chipset the exact timing and
sensitivity can differ (the underlying principle — never let the link go silent — still applies).

## Gyro / tilt-aim (per-game)

The pad has a 3-axis **accelerometer** (tilt, not a true gyroscope). The driver can map tilt onto
the right stick — but **only for games you explicitly opt in**, so it never touches the rest:

1. List the games in `/etc/xiaomi-gamepad/gyro-games.conf` — one **process-name substring** per
   line (`#` for comments). For a Wine/Proton game that's usually the `.exe` name.
2. While a listed game is running, tilt drives the right stick; when it exits, tilt switches off.
   No restart needed — the list is re-read live.

Games **not** listed never get the accelerometer enabled (zero writes to the pad on their behalf),
so titles like GTA are completely unaffected. The accel is enabled over the **interrupt channel**
(the same safe path as rumble), never the control-channel write that destabilises this pad. Tuning
knobs live at the top of `xiaomi-gamepad.py`: `TILT_SCALE` (sensitivity), `TILT_DEADZONE`,
`TILT_SMOOTH`, and `TILT_X_SIGN` / `TILT_Y_SIGN` (axis inversion).

## Tools

| tool | what it does |
|---|---|
| `tools/xiaomi-verify.py` | print which Xbox control fires for each physical button (verify mapping) |
| `tools/xiaomi-capture.py` | dump which raw HID bytes change per button (useful for porting to other pads) |
| `tools/rumble-test.py` | fire rumble pulses to test force feedback (`python3 tools/rumble-test.py 40 1`) |

## Per-game notes

- **Modern games / Proton / SDL** — just work; nothing else to do.
- **Old Wine games that need an ASI loader** (e.g. GTA San Andreas + the GInput mod) — the game
  must load its `dinput8.dll` ASI loader; see `gamepad-setup.md` for the per-game gotchas.

## Service control

The daemon is **on-demand**: a udev rule starts it the moment the pad connects and stops it when the
pad powers off, so it uses **no RAM while the pad is off** (it is *not* enabled at boot). Turn the
pad on and it's up within ~1 s; turn it off and the service goes away.

```sh
systemctl status xiaomi-gamepad          # active only while the pad is connected
journalctl -u xiaomi-gamepad -e
```

Want it always-on instead (e.g. to shave that ~1 s startup)? Add `[Install] WantedBy=multi-user.target`
to the unit and `sudo systemctl enable --now xiaomi-gamepad`.

## Uninstall

```sh
sudo ./uninstall.sh
```

Your `/etc/xiaomi-gamepad/gyro-games.conf` (your game list) is left in place; run
`sudo rm -r /etc/xiaomi-gamepad` to remove it too.

## Credits

The pad's HID protocol / button mapping was reverse-engineered by
[**irungentoo/Xiaomi_gamepad**](https://github.com/irungentoo/Xiaomi_gamepad) (the Windows reference
driver). This project is an original, independent **Linux** userspace implementation.

## License

[MIT](LICENSE).
