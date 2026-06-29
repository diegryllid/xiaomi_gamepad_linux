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

## ⚠️ Rumble — important Bluetooth note

Rumble works on the **stock / default** BlueZ + kernel Bluetooth stack. **Do not "optimize" the BT
stack for this pad.** Specifically, do **not**:

- disable L2CAP **ERTM** (`disable_ertm=1`)
- disable **sniff** mode / `IdleTimeout=0`
- force the kernel **`hidp`** path (`UserspaceHID=false`)
- disable **USB autosuspend** on the BT controller

Each of those makes the pad **disconnect on rumble**. The pad firmware has a known quirk where a
rumble write can briefly wedge it; **ERTM's reliable L2CAP retransmission is exactly what lets the
link ride that out**. The default stack is the robust one — leave it alone.

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

```sh
systemctl status xiaomi-gamepad
sudo systemctl restart xiaomi-gamepad
journalctl -u xiaomi-gamepad -e
```

## Uninstall

```sh
sudo ./uninstall.sh
```

## Credits

The pad's HID protocol / button mapping was reverse-engineered by
[**irungentoo/Xiaomi_gamepad**](https://github.com/irungentoo/Xiaomi_gamepad) (the Windows reference
driver). This project is an original, independent **Linux** userspace implementation.

## License

[MIT](LICENSE).
