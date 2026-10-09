# EmuFusion controller mapping

Per-system mapping from the AYN Thor's physical controls to each console's own
controls, derived from the shape of the original controller and pinned to the
RetroPad IDs the shipped core actually reads.

One table is the source of truth.
[`SystemControlLayouts`](../unified-android/src/com/thorium/lucent/input/SystemControlLayouts.java)
holds, for every physical control, the console control it is *and* the RetroPad
ID that reaches it, in a single `Binding`;
[`LibretroJoypadLayout`](../unified-android/src/com/thorium/lucent/input/LibretroJoypadLayout.java)
reads the ID out of that entry at runtime, and every table in this document is
generated from the same entry. The name and the ID used to live in two separate
tables and they drifted: the Mega Drive advertised "C" on the right face button
while that button pressed Mega Drive **B**, and the real C sat on a shoulder. In
Disney's *Aladdin* that is the jump button.

## Where the RetroPad IDs come from

Every ID below was read out of the pinned core's own
`retro_input_descriptor` table in the built `.so` under
`engines/build/arm64-v8a/`, not from convention. Cores disagree about this more
than folklore admits — BlastEm reads RetroPad **B(0)** as Mega Drive **A** and
RetroPad **R(11)** as Mega Drive **C**, while the Genesis Plus GX convention
everyone quotes uses Y/B/A for A/B/C. Guessing is what broke jumping.

Systems whose core is not built in this tree are called out in their section;
their IDs follow the libretro convention and are unverified.

## Single-screen phone controls

The phone fallback keeps its D-pad separate from analog input. Hardware libretro
sessions expose one or two touch sticks according to the curated analog bindings
below; native-adapter sessions expose their two existing local stick axes. Each
stick retains its own finger ID, uses a radial dead zone and clamps outside drags
without also pressing D-pad buttons. A second finger can press a face button at
the same time. Pause, backgrounding, focus loss, cancellation, hiding and detaching
the overlay release held inputs. Touches outside the controls still reach the
game's stylus handler. Physical-controller mappings and saved remaps are unchanged.

Executable coverage: `tools/tests/test_phone_analog_controls.py` runs the actual
touch view with Android event test doubles. Runtime per-system acceptance remains
in `docs/qa/android-portability-2026-10-02/matrix.json`; host tests alone are not a
gameplay pass.

## The Thor's physical controls

The Thor is physically silkscreened in Nintendo positions: **B** on the bottom,
**A** on the right, **Y** on the left and **X** on top. Its Odin Settings
`Controller style` changes the evdev/Android names emitted by those same fixed
slots and changes the controller product ID. EmuFusion therefore normalizes the
two exact identities into positions before applying a console layout:

| Physical slot and printed label | Odin Style `2020:0111` | XBox Style `2020:0112` | EmuFusion canonical |
| --- | --- | --- | --- |
| Bottom (**B**) | `BTN_EAST` 305 → `KEYCODE_BUTTON_B` 97 | `BTN_SOUTH` 304 → `KEYCODE_BUTTON_A` 96 | `SOUTH` |
| Right (**A**) | `BTN_SOUTH` 304 → `KEYCODE_BUTTON_A` 96 | `BTN_EAST` 305 → `KEYCODE_BUTTON_B` 97 | `EAST` |
| Left (**Y**) | `BTN_WEST` 308 → `KEYCODE_BUTTON_Y` 100 | `BTN_NORTH` 307 → `KEYCODE_BUTTON_X` 99 | `WEST` |
| Top (**X**) | `BTN_NORTH` 307 → `KEYCODE_BUTTON_X` 99 | `BTN_WEST` 308 → `KEYCODE_BUTTON_Y` 100 | `NORTH` |

The remaining controls do not depend on that face-button style:

| Physical control | evdev | Android | EmuFusion canonical |
| --- | --- | --- | --- |
| L1 / R1 | `BTN_TL` 310 / `BTN_TR` 311 | `BUTTON_L1` 102 / `BUTTON_R1` 103 | `L1` / `R1` |
| L2 / R2 | `BTN_TL2` 312 / `BTN_TR2` 313 | `BUTTON_L2` 104 / `BUTTON_R2` 105 | `L2` / `R2` |
| D-pad | `ABS_HAT0X` / `ABS_HAT0Y` | `AXIS_HAT_X` / `AXIS_HAT_Y` | `DPAD_*` |
| Left stick | `ABS_X` / `ABS_Y` | `AXIS_X` / `AXIS_Y` | `LEFT_X_*` / `LEFT_Y_*` |
| Left stick click | `BTN_THUMBL` 317 | `BUTTON_THUMBL` 106 | `L3` |
| Right stick | `ABS_Z` / `ABS_RZ` | `AXIS_Z` / `AXIS_RZ` | `RIGHT_X_*` / `RIGHT_Y_*` |
| Right stick click | `BTN_THUMBR` 318 | `BUTTON_THUMBR` 107 | `R3` |
| Start | `BTN_START` 315 | `BUTTON_START` 108 | `START` |
| Select / Stop | `BTN_SELECT` 314 | `BUTTON_SELECT` 109 | `SELECT` on tap; EmuFusion Stop on hold |

Linux `BTN_SOUTH/EAST/NORTH/WEST` and Android `BUTTON_A/B/X/Y` are semantic
button names on this firmware, not permanent physical coordinates. Treating
`BUTTON_A` as `SOUTH` in both styles reverses all four slots in Odin Style. The
exact currently audited device is `2020:0111` (`Odin Controller`) using vendor
key layout `Vendor_2020_Product_0111.kl`, SHA-256
`b00d7b3523a0d390b14082b4db1c925c449115baba94841029e62a3a3638eee8`.
An unknown AYN `2020:*` product leaves face controls unbound until the user
remaps them; silently guessing a style would be worse than rejecting the input.

The Thor reports its D-pad as a hat, **not** as `BTN_DPAD_*` keys, so the D-pad
and the left stick both arrive as axes inside the same `MotionEvent`.

Select is dual-purpose. A tap is replayed into the game as a normal Select
press; a hold is EmuFusion's Stop gesture and never reaches the core.

## EmuFusion's own chords

Select is the modifier for everything EmuFusion itself owns, because every other
button on the Thor is a button some console shipped with, and a bare binding
would collide with a game the day someone loaded the right cartridge. All three
chords are read by `InWindowGameHost` before the event reaches the core, and the
withheld presses are replayed as taps if the chord does not complete.

- **Select held for 1 s** — Stop: save and return to the library.
- **Select + Start held for 2 s** — reset the running game.
- **Select + L1** — open or close the cheats. On the Thor this puts the cheat
  list on the **lower display** while the game keeps running above it, so a
  cheat's effect is visible as it is switched; on a single-screen device, and
  during a DS/3DS/Wii U session whose second screen already owns the lower
  display, the same chord opens the in-window cheats sheet instead. While the
  panel is open the pad drives it: D-pad up/down moves, A toggles, B or Back
  closes. Pressing A on a game with no cheats closes the panel rather than
  doing nothing.

The 1 s Stop hold and the 2 s reset countdown are both retired the moment the
cheats chord lands, so browsing a cheat list cannot exit the game underneath it.

## How placement is decided

The Thor's face cluster has four positions and no second row. Each console's
buttons are placed on it by the shape of the original controller, in this order
of precedence:

1. **A diamond maps 1:1.** SNES, PlayStation, Dreamcast, DS and 3DS all put
   four buttons in a diamond, so the console's bottom button goes to `SOUTH`,
   its right to `EAST`, its left to `WEST` and its top to `NORTH`. The RetroPad
   ID names *are* the SNES diamond, which is why this is usually also the
   identity mapping.
2. **A row maps to the arc `WEST -> SOUTH -> EAST`.** A Mega Drive's A-B-C, a
   Saturn's A-B-C and a PC Engine's I-II are horizontal rows. That arc is the
   closest a diamond gets: a thumb sweeps it left to right in the original
   order, and the middle of the row lands under the thumb at rest.
3. **A second row goes to `L1 -> NORTH -> R1`.** The Mega Drive and Saturn
   six-button pads put X-Y-Z directly above A-B-C. The Thor has no second face
   row, so each of the three sits up-and-over from its partner: X above A on
   the left shoulder, Y above B on the top face button, Z above C on the right
   shoulder. This is the one place the original geometry cannot be reproduced,
   and it is a compromise, not a preference.
4. **Two buttons put the action under the thumb.** NES A, Game Boy A, GBA A,
   Master System 1, PC Engine I, Neo Geo Pocket A, WonderSwan A and every
   joystick's Fire take `SOUTH`; the second button takes `EAST`. On the NES the
   row reads B-A left to right, so this is the one case where the action button
   is deliberately moved out of its printed order — a jump button belongs where
   the thumb already is.
5. **Console switches never sit under a thumb.** Reset, difficulty, coin and
   mode switches were never pad buttons. They go to stick clicks, the top face
   button or the triggers, and never to `SOUTH` or `EAST`.

## Rules that apply to every system

**Every control the console shipped with is reachable.** Each section lists the
console's roster, and `LibretroJoypadLayoutTest.everyConsoleControlIsReachable`
fails the build if any entry in it has no physical control. That is the check
that would have caught a Mega Drive with no jump button.

**The left stick is a second D-pad on every console that never had a stick.**
Both sources drive the same RetroPad IDs and neither cancels the other.

**Consoles whose core reads the left stick as its own analog control keep it off
the D-pad.** N64, GameCube, Wii, Dreamcast/NAOMI/Atomiswave, PSP, PS2 and 3DS
read the stick and the D-pad as different controls. ColecoVision and Apple II
are on the same list for a stranger reason: gearcoleco reads
`RETRO_DEVICE_ANALOG` index 0 as **keypad 9 and keypad 0**, and AppleWin reads it
as the two paddles, so a stick that also meant "D-pad" would type while it
steered. `LibretroJoypadLayout.hasAnalogStick` is the list.

**The right stick is never a digital button.** It is sent only as
`RETRO_DEVICE_ANALOG` index 1, which is what the N64 C-buttons, the GameCube
C-stick, Wii IR pointing, the 3DS C-stick, the DS touch cursor and the
Intellivision keypad read.

**Several physical controls may drive one console control.** The hat, the left
stick and (on other pads) `BTN_DPAD_*` keys all mean "the D-pad".
[`JoypadPressLedger`](../unified-android/src/com/thorium/lucent/input/JoypadPressLedger.java)
records which sources hold each RetroPad ID and ORs them, so a direction stays
pressed while any source holds it and is released once, when the last lets go.
Without it the last source written wins, and one centred stick clears a
physically held hat direction.

## Per-system tables

`RetroPad ID` is the `RETRO_DEVICE_ID_JOYPAD_*` value EmuFusion sends;
`analog` means the control is sent as an axis instead. `Console roster` is the
list of controls the original machine had, which the completeness test checks.

### `famicom` `nes`

*Mesen2 (built), verified: A=8, B=0, Select=2 and Start=3.* The NES has only two
action buttons, so each one is duplicated across a pair of Thor face buttons:
printed A and B both press NES A; printed X and Y both press NES B. Mesen's
RetroPad X/Y turbo inputs are deliberately unused, so the standard NES layout
has no turbo functionality.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `A` |
| `EAST` right face button | 8 | `A` |
| `WEST` left face button | 0 | `B` |
| `NORTH` top face button | 0 | `B` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `START` `SELECT`

### `gameboy` `gameboycolor` `gb` `gbc`

*SameBoy (built), verified: A=8, B=0.* Thor's printed `A` and `Y` buttons map
directly to Game Boy `A` and `B`, respectively.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `EAST` right face button (printed `A`) | 8 | `A` |
| `WEST` left face button (printed `Y`) | 0 | `B` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `START` `SELECT`

### `gameboyadvance` `gba`

*mGBA (built), verified: A=8, B=0, L=10, R=11, L3/R3 drive the solar sensor.* A
GBA is a Game Boy with shoulders, so it is mapped like one; the stick clicks
reach the Boktai cartridge's solar sensor, the only other input a GBA accepts.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `A` |
| `EAST` right face button | 0 | `B` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `L3` left stick click | 14 | `SOLAR_DARKEN` |
| `R3` right stick click | 15 | `SOLAR_BRIGHTEN` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `L` `R` `START` `SELECT`

### `snes` `superfamicom`

*Mesen-S (built), verified: A=8, B=0, X=9, Y=1, L=10, R=11.* The SNES diamond is
the diamond libretro's ID names were taken from, so this is a pure 1:1 map: **B
is the bottom button**, exactly where a SNES player's thumb rests and exactly
what *Super Mario World* jumps with. This is a deliberate reversal of an earlier
pass, which put SNES A on the bottom to match the Thor's printed label; matching
the console's geometry beats matching the silkscreen, because the muscle memory
being served is the console's.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `B` |
| `EAST` right face button | 8 | `A` |
| `WEST` left face button | 1 | `Y` |
| `NORTH` top face button | 9 | `X` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `X` `Y` `L` `R` `START` `SELECT`

### `ds` `nds` `nintendods`

*melonDS DS (built), verified: A=8, B=0, X=9, Y=1, L=10, R=11, L2=microphone,
R2=screen layout, L3=close lid, R3=touch, right stick=touch cursor.* The DS
cluster is the SNES cluster, so it is mapped the same way; the lid, microphone
and touch screen are real controls of the machine and each gets a control.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `B` |
| `EAST` right face button | 8 | `A` |
| `WEST` left face button | 1 | `Y` |
| `NORTH` top face button | 9 | `X` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `L2` left trigger | 12 | `MICROPHONE` |
| `R2` right trigger | 13 | `SCREEN_LAYOUT` |
| `L3` left stick click | 14 | `LID` |
| `R3` right stick click | 15 | `TOUCH` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| `TOUCH_PRIMARY` touchscreen | analog | `TOUCH` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| right stick | analog 1 | `TOUCH_CURSOR` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `X` `Y` `L` `R` `START` `SELECT` `TOUCH` `LID` `MICROPHONE`

### `virtualboy`

*beetle-vb is **not built** in this tree, so these IDs follow the libretro
convention and are unverified.* The Virtual Boy has two D-pads: the left one is
the D-pad and the left stick, and the right one rides the right stick, which is
the shape a second D-pad wants on a modern pad. A and B sit on the right face
as they do on the hardware, with A under the thumb.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `A` |
| `EAST` right face button | 0 | `B` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| right stick | analog 1 | `D_PAD_2_LEFT` left, `D_PAD_2_RIGHT` right, `D_PAD_2_UP` up, `D_PAD_2_DOWN` down |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `L` `R` `START` `SELECT` `D_PAD_2_UP` `D_PAD_2_DOWN` `D_PAD_2_LEFT` `D_PAD_2_RIGHT`

### `genesis` `megacd` `megadrive` `sega32x` `segacd`

*BlastEm (built), verified from the shipped core's own descriptor table: Mega
Drive **A=RetroPad B(0)**, **B=A(8)**, **C=R(11)**, X=Y(1), Y=X(9), Z=L(10),
Mode=Select(2), Start=Start(3).* The Mega Drive famously has three buttons in a
row on the right of the pad, so all three are on the face cluster in their
original left-to-right order: **A on the left button, B on the bottom, C on the
right**. B is the middle of the row and therefore the button a Mega Drive thumb
rests on, so it takes the bottom position. The six-button pad's X-Y-Z row has
nowhere to go on a single-row cluster, so X and Z take the shoulders directly
above A and C and Y takes the top face button directly above B.

This section is what the "I can't even jump in *Aladdin*" report was about. The
previous mapping sent the bottom button to RetroPad B(0), which BlastEm reads as
Mega Drive **A**, the right button to RetroPad A(8), which is Mega Drive **B**,
and left C stranded on RetroPad R(11) behind the *right shoulder*. Two of the
three buttons were mislabelled and the third was not on the face at all.

Sega CD and 32X are routed to PicoDrive, which is **not built** (license-blocked)
and follows the Genesis Plus GX convention rather than BlastEm's. They share this
table for placement; their IDs will need re-reading if that core is ever built.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `B` |
| `EAST` right face button | 11 | `C` |
| `WEST` left face button | 0 | `A` |
| `NORTH` top face button | 9 | `Y` |
| `L1` left shoulder | 1 | `X` |
| `R1` right shoulder | 10 | `Z` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `MODE` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `C` `X` `Y` `Z` `START` `MODE`

### `gamegear` `mastersystem` `sg1000`

*Gearsystem (built), verified: button 1=B(0), button 2=A(8), Start=3, and
**RetroPad Select(2) is the console's Reset switch**.* Two buttons in a row, so
button 1 goes under the thumb and button 2 to its right. Reset is a switch on
the console, not a pad button, so it is deliberately parked on the left stick
click and EmuFusion's Select tap reaches nothing here — the old mapping sent Select
straight at Reset, so tapping it restarted the game.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `1` |
| `EAST` right face button | 8 | `2` |
| `L3` left stick click | 2 | `RESET` |
| `START` Start | 3 | `START` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `1` `2` `START` `RESET`

### `saturn`

*Beetle Saturn (built), verified: A=B(0), B=A(8), C=R(11), X=Y(1), Y=X(9),
Z=L(10), L=L2(12), R=R2(13).* Structurally a Mega Drive pad with real shoulder
triggers, and it is mapped identically: A-B-C along the face arc, X-Y-Z on the
row above, and the two analog-feeling triggers on the Thor's triggers. The 3D
pad's Mode switch is on the left stick click, away from the thumb.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `B` |
| `EAST` right face button | 11 | `C` |
| `WEST` left face button | 0 | `A` |
| `NORTH` top face button | 9 | `Y` |
| `L1` left shoulder | 1 | `X` |
| `R1` right shoulder | 10 | `Z` |
| `L2` left trigger | 12 | `L` |
| `R2` right trigger | 13 | `R` |
| `L3` left stick click | 2 | `MODE` |
| `START` Start | 3 | `START` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `C` `X` `Y` `Z` `L` `R` `START`

### `atomiswave` `dreamcast` `naomi`

*Flycast (built; stripped, so these IDs are derived from the Dreamcast pad's own
geometry rather than read from a symbol table).* The Dreamcast cluster is
already a diamond — A at the bottom, B on the right, X on the left, Y on top —
so it maps 1:1. Its L and R are analog triggers on the hardware, so they go to
the Thor's analog triggers rather than its shoulders. The Dreamcast pad has no
Select button and none is invented.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `A` |
| `EAST` right face button | 8 | `B` |
| `WEST` left face button | 1 | `X` |
| `NORTH` top face button | 9 | `Y` |
| `L2` left trigger | 12 | `L` |
| `R2` right trigger | 13 | `R` |
| `START` Start | 3 | `START` |
| D-pad | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| left stick | analog 0 | `ANALOG_STICK` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `X` `Y` `L` `R` `START` `ANALOG_STICK`

### `pcengine` `pcenginecd` `turbografx16`

*Beetle PCE Fast (built), verified: II=B(0), I=A(8), III=Y(1), IV=X(9), V=L(10),
VI=R(11), mode switch=L2(12), Run=3, Select=2.* The stock pad is a two-button
row with I on the right; I is the action button, so it takes the bottom position
and II sits to its right. The Avenue Pad 6's four extra buttons continue onto
the remaining face buttons and the shoulders, and its 2/6-button mode switch is
on the left trigger. Cartridge and CD games use the same controller mapping;
the CD route must not fall back to the generic RetroPad layout. On-screen phone
controls show the guest labels, including V, VI, Mode and Run.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `I` |
| `EAST` right face button | 0 | `II` |
| `WEST` left face button | 1 | `III` |
| `NORTH` top face button | 9 | `IV` |
| `L1` left shoulder | 10 | `V` |
| `R1` right shoulder | 11 | `VI` |
| `L2` left trigger | 12 | `MODE` |
| `START` Start | 3 | `RUN` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `I` `II` `III` `IV` `V` `VI` `RUN` `SELECT` `MODE`

### `neogeopocket` `neogeopocketcolor` `ngp` `ngpc`

*Beetle NeoPop (built), verified: A=B(0), B=A(8), Option=Start(3).* A is left of
B on the hardware and is the action button, so the row falls straight onto the
bottom-then-right arc with no reordering. The Neo Geo Pocket has no Select.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `A` |
| `EAST` right face button | 8 | `B` |
| `START` Start | 3 | `OPTION` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `OPTION`

### `wonderswan` `wonderswancolor`

*Beetle Cygne (built), verified: A=A(8), B=B(0), the X cursor is the D-pad and
the second (Y) cursor is L(10) left, R(11) right, L2(12) down, R2(13) up.* A
WonderSwan is played held two ways and has two four-way cursors. The X cursor is
the D-pad; the Y cursor goes to the four index-finger controls rather than
stealing face buttons, because A and B have to stay under the thumb. Select is
the core's screen-rotate, which is how the machine switches orientation.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `A` |
| `EAST` right face button | 0 | `B` |
| `L1` left shoulder | 10 | `Y_LEFT` |
| `R1` right shoulder | 11 | `Y_RIGHT` |
| `L2` left trigger | 12 | `Y_DOWN` |
| `R2` right trigger | 13 | `Y_UP` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `ROTATE` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `START` `ROTATE` `Y_UP` `Y_DOWN` `Y_LEFT` `Y_RIGHT`

### `playstation` `ps1` `psx`

*SwanStation (built), verified: Cross=B(0), Circle=A(8), Triangle=X(9),
Square=Y(1), L1/R1=10/11, L2/R2=12/13, L3/R3=14/15.* The DualShock diamond is
the Thor's diamond, so every button is where the hand expects it. The in-process
host selects `RETRO_DEVICE_JOYPAD`, a digital pad on this core, so the left
stick doubles as the D-pad rather than feeding an analog axis the core ignores.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `CROSS` |
| `EAST` right face button | 8 | `CIRCLE` |
| `WEST` left face button | 1 | `SQUARE` |
| `NORTH` top face button | 9 | `TRIANGLE` |
| `L1` left shoulder | 10 | `L1` |
| `R1` right shoulder | 11 | `R1` |
| `L2` left trigger | 12 | `L2` |
| `R2` right trigger | 13 | `R2` |
| `L3` left stick click | 14 | `L3` |
| `R3` right stick click | 15 | `R3` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `CROSS` `CIRCLE` `SQUARE` `TRIANGLE` `L1` `R1` `L2` `R2` `START` `SELECT`

### `ps2`

*Play! (built), verified: identical IDs to the PlayStation.* Same diamond, but a
PS2 pad reads its sticks and its D-pad as different controls, so the left stick
stays analog here and does not press the D-pad.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `CROSS` |
| `EAST` right face button | 8 | `CIRCLE` |
| `WEST` left face button | 1 | `SQUARE` |
| `NORTH` top face button | 9 | `TRIANGLE` |
| `L1` left shoulder | 10 | `L1` |
| `R1` right shoulder | 11 | `R1` |
| `L2` left trigger | 12 | `L2` |
| `R2` right trigger | 13 | `R2` |
| `L3` left stick click | 14 | `L3` |
| `R3` right stick click | 15 | `R3` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| left stick | analog 0 | `LEFT_STICK` |
| right stick | analog 1 | `RIGHT_STICK` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `CROSS` `CIRCLE` `SQUARE` `TRIANGLE` `L1` `R1` `L2` `R2` `L3` `R3` `START` `SELECT` `LEFT_STICK` `RIGHT_STICK`

### `psp`

*PPSSPP (built), verified: Cross=B(0), Circle=A(8), Triangle=X(9), Square=Y(1),
L=10, R=11.* The PSP face cluster is the PlayStation's. Its single analog nub is
the left stick and is not aliased to the D-pad, because PSP games read the two
separately.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `CROSS` |
| `EAST` right face button | 8 | `CIRCLE` |
| `WEST` left face button | 1 | `SQUARE` |
| `NORTH` top face button | 9 | `TRIANGLE` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| left stick | analog 0 | `ANALOG_NUB` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `CROSS` `CIRCLE` `SQUARE` `TRIANGLE` `L` `R` `START` `SELECT` `ANALOG_NUB`

### `n64` `nintendo64`

*mupen64plus-next (built) with its shipped `mupen64plus-next-alt-map=False`,
verified: A=B(0), B=Y(1), C1=A(8), C4=X(9), Z=L2(12), L=L(10), R=R(11), R2(13)
is the "C Buttons Mode" modifier, and `Control Stick X/Y` is analog index 0 while
`C Buttons X/Y` is analog index 1.* The N64 pad's own layout is followed
directly: the analog stick is the left stick, the D-pad is the D-pad, A and B
are the two thumb buttons, Z is a trigger and L/R are the shoulders. The
four-button C cluster is a second stick in all but name, so it is the right
stick; the two C directions the core also exposes as buttons stay on the two
free face buttons as a held-R2 fallback.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `A` |
| `EAST` right face button | 1 | `B` |
| `WEST` left face button | 8 | `C_DOWN` |
| `NORTH` top face button | 9 | `C_UP` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `L2` left trigger | 12 | `Z` |
| `R2` right trigger | 13 | `C_MODE` |
| `START` Start | 3 | `START` |
| D-pad | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| left stick | analog 0 | `CONTROL_STICK` |
| right stick | analog 1 | `C_LEFT` left, `C_RIGHT` right, `C_UP` up, `C_DOWN` down |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `Z` `L` `R` `START` `CONTROL_STICK` `C_UP` `C_DOWN` `C_LEFT` `C_RIGHT`

### `gamecube` `gc` `nintendogamecube`

*Dolphin `descGC` (built), verified: A=A(8), B=B(0), X=X(9), Y=Y(1), L=L2(12),
R=R2(13), Z=R(11), L3/R3 are the triggers' full-press clicks; RetroPad L(10) is
Dolphin's "Triforce - Test" and Select(2) its "Triforce - Coin".* A GameCube pad
is not a diamond: A is a large button in the middle with B to its lower left, X
to its right and Y above it. That is exactly how it is placed here — **B on the
left face button, X on the right** — rather than in the Xbox arrangement an
earlier pass used. Its L and R are analog triggers, so they take the Thor's
triggers, and the two Triforce arcade switches are left unmapped because no
GameCube pad has them.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `A` |
| `EAST` right face button | 9 | `X` |
| `WEST` left face button | 0 | `B` |
| `NORTH` top face button | 1 | `Y` |
| `R1` right shoulder | 11 | `Z` |
| `L2` left trigger | 12 | `L` |
| `R2` right trigger | 13 | `R` |
| `L3` left stick click | 14 | `L_ANALOG` |
| `R3` right stick click | 15 | `R_ANALOG` |
| `START` Start | 3 | `START` |
| D-pad | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| left stick | analog 0 | `CONTROL_STICK` |
| right stick | analog 1 | `C_STICK` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `X` `Y` `L` `R` `Z` `START` `CONTROL_STICK` `C_STICK`

### `nintendowii` `wii`

*Dolphin `descWiimote` / `descWiimoteNunchuk` (built), verified: both agree on
A=A(8), B=B(0); X(9) is the Wiimote's **1** and the Nunchuk's **C**, Y(1) is
**2** and **Z**, L(10)/R(11) are −/+ with an extension, L2(12) shakes the
Nunchuk, R2(13) shakes the Wiimote, R3(15) is Home.* One table is correct under
both device types. The Nunchuk stick is the left stick and the right stick is
mirrored to an absolute libretro pointer over the complete IR plane. Mapped A
both remains Wiimote A and supplies pointer contact, so pointing and clicking
are one coherent action.

EmuFusion selects Dolphin's pointer-backed `dolphin_ir_mode=2` internally. This
is important: the right stick still reaches `RETRO_DEVICE_ANALOG` index 1 for
Wiimote tilt while `RETRO_DEVICE_POINTER` independently drives IR. The host does
not sacrifice tilt in order to point, and no RetroArch-style option is exposed.
`RETRO_DEVICE_WIIMOTE_NC` (`(3 << 8) | RETRO_DEVICE_JOYPAD`) is selected after
each game load, so the same session also keeps the left-stick Nunchuk extension
active.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `A` |
| `EAST` right face button | 0 | `B` |
| `WEST` left face button | 9 | `NUNCHUK_C` |
| `NORTH` top face button | 1 | `NUNCHUK_Z` |
| `L1` left shoulder | 10 | `MINUS` |
| `R1` right shoulder | 11 | `PLUS` |
| `L2` left trigger | 12 | `SHAKE_NUNCHUK` |
| `R2` right trigger | 13 | `SHAKE_WIIMOTE` |
| `R3` right stick click | 15 | `HOME` |
| `START` Start | 3 | `1` |
| `SELECT` Select (tap) | 2 | `2` |
| D-pad | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| left stick | analog 0 | `NUNCHUK_STICK` |
| right stick | analog 1 | `IR_POINTER` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `NUNCHUK_C` `NUNCHUK_Z` `1` `2` `PLUS` `MINUS` `HOME` `NUNCHUK_STICK` `IR_POINTER`

With this selected Nunchuk device, Start and Select press the remote's **1**
and **2**. Plus and Minus are on R1 and L1. The plain-Wiimote descriptor's
face-button 1/2 mapping does not apply. These labels match the existing runtime
IDs; no saved physical-button remaps are changed.

### `3ds`

*Azahar (built), verified: B=B(0), A=A(8), Y=Y(1), X=X(9), L=10, R=11, ZL=12,
ZR=13, L3=Home/swap screens, R3=touch, Circle Pad on analog 0, C-stick on analog
1.* The 3DS cluster is the SNES cluster, so B is the bottom button. The Circle
Pad is a real analog stick and is kept off the D-pad. `3ds` also has an external
route; this table applies to the internal core.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `B` |
| `EAST` right face button | 8 | `A` |
| `WEST` left face button | 1 | `Y` |
| `NORTH` top face button | 9 | `X` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `L2` left trigger | 12 | `ZL` |
| `R2` right trigger | 13 | `ZR` |
| `L3` left stick click | 14 | `HOME` |
| `R3` right stick click | 15 | `TOUCH` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| `TOUCH_PRIMARY` touchscreen | analog | `TOUCH` |
| D-pad | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| left stick | analog 0 | `CIRCLE_PAD` |
| right stick | analog 1 | `C_STICK` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `X` `Y` `L` `R` `ZL` `ZR` `START` `SELECT` `HOME` `TOUCH` `CIRCLE_PAD` `C_STICK`

### `atari2600`

*Stella is **not built** in this tree; these IDs follow the libretro convention
and are unverified.* The 2600 joystick has a single button, so Fire takes the
bottom position. Everything else on the machine is a console switch —
Reset, Select, Color/B&W and the two difficulty switches — and each of them is
placed away from the resting thumb.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `FIRE` |
| `EAST` right face button | 8 | `FIRE_2` |
| `NORTH` top face button | 9 | `COLOR_BW` |
| `L1` left shoulder | 10 | `LEFT_DIFFICULTY` |
| `R1` right shoulder | 11 | `RIGHT_DIFFICULTY` |
| `START` Start | 3 | `CONSOLE_RESET` |
| `SELECT` Select (tap) | 2 | `CONSOLE_SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `FIRE` `CONSOLE_RESET` `CONSOLE_SELECT` `COLOR_BW` `LEFT_DIFFICULTY` `RIGHT_DIFFICULTY`

### `atari5200` `atari800` `atari8bit`

*atari800 is **not built** in this tree; unverified.* Two fire buttons on the
arc, the 5200's Start/Pause/Reset on the controls a thumb does not rest on, and
the numeric keypad through the core's own overlay.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `FIRE` |
| `EAST` right face button | 8 | `FIRE_2` |
| `WEST` left face button | 1 | `RESET` |
| `NORTH` top face button | 9 | `PAUSE` |
| `L1` left shoulder | 10 | `KEYPAD_HASH` |
| `R1` right shoulder | 11 | `KEYPAD_STAR` |
| `L3` left stick click | 14 | `KEYBOARD` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `FIRE` `FIRE_2` `START` `SELECT` `PAUSE` `RESET` `KEYPAD_STAR` `KEYPAD_HASH` `KEYBOARD`

### `atari7800`

*ProSystem (built), verified: button 1=B(0), button 2=A(8), Console Reset=X(9),
Console Select=Select(2), Console Pause=Start(3), left/right difficulty=L(10)
and R(11), and analog index 1 is the second player's stick.* The ProLine pad's
two fire buttons take the arc. The four console switches are on the front panel
of the machine, not the pad, so Select and Pause take EmuFusion's Select and Start,
the difficulty switches take the shoulders, and **Reset needs a deliberate left
stick click** so it cannot be hit mid-game.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `1` |
| `EAST` right face button | 8 | `2` |
| `L1` left shoulder | 10 | `LEFT_DIFFICULTY` |
| `R1` right shoulder | 11 | `RIGHT_DIFFICULTY` |
| `L3` left stick click | 9 | `CONSOLE_RESET` |
| `START` Start | 3 | `CONSOLE_PAUSE` |
| `SELECT` Select (tap) | 2 | `CONSOLE_SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| right stick | analog 1 | `PLAYER_2_STICK` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `1` `2` `CONSOLE_RESET` `CONSOLE_SELECT` `CONSOLE_PAUSE` `LEFT_DIFFICULTY` `RIGHT_DIFFICULTY`

### `colecovision`

*Gearcoleco (built), verified: yellow/left fire=B(0), red/right fire=A(8),
keypad 1-8 on Y(1), X(9), L(10), R(11), L2(12), R2(13), L3(14), R3(15), `*` on
Start(3), `#` on Select(2), and **keypad 9 and keypad 0 are the two axes of
`RETRO_DEVICE_ANALOG` index 0**.* Many ColecoVision games cannot even be started
without the keypad, so every one of the twelve keys is reachable: ten of them on
the buttons a thumb or finger is not using, and 9 and 0 on the left stick, which
is why the ColecoVision left stick is not a second D-pad. A twelve-key pad
cannot be reproduced spatially on a gamepad; the keys are ordered by reach.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `LEFT_FIRE` |
| `EAST` right face button | 8 | `RIGHT_FIRE` |
| `WEST` left face button | 1 | `KEYPAD_1` |
| `NORTH` top face button | 9 | `KEYPAD_2` |
| `L1` left shoulder | 10 | `KEYPAD_3` |
| `R1` right shoulder | 11 | `KEYPAD_4` |
| `L2` left trigger | 12 | `KEYPAD_5` |
| `R2` right trigger | 13 | `KEYPAD_6` |
| `L3` left stick click | 14 | `KEYPAD_7` |
| `R3` right stick click | 15 | `KEYPAD_8` |
| `START` Start | 3 | `KEYPAD_STAR` |
| `SELECT` Select (tap) | 2 | `KEYPAD_HASH` |
| D-pad | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| left stick | analog 0 | `KEYPAD_0` on X, `KEYPAD_9` on Y |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `LEFT_FIRE` `RIGHT_FIRE` `KEYPAD_0` `KEYPAD_1` `KEYPAD_2` `KEYPAD_3` `KEYPAD_4` `KEYPAD_5` `KEYPAD_6` `KEYPAD_7` `KEYPAD_8` `KEYPAD_9` `KEYPAD_STAR` `KEYPAD_HASH`

### `intellivision`

*FreeIntv (built), verified: left action=A(8), right action=B(0), top action=Y(1),
last keypad=X(9), show keypad=L(10)/R(11), clear=L2(12), enter=R2(13), keypad
0=L3(14), keypad 5=R3(15), pause=Start(3), swap controllers=Select(2), and
**keypad 1-9 is `RETRO_DEVICE_ANALOG` index 1**.* The Intellivision controller
has three action buttons and a twelve-key pad. The top action button goes to the
top of the cluster and the left one to the left, exactly as on the hardware, with
the right action button under the thumb because it is the one games use most.
The keypad's own 3x3 digit grid is a circle of directions, which is precisely
what the right stick is.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `RIGHT_ACTION` |
| `EAST` right face button | 9 | `KEYPAD_LAST` |
| `WEST` left face button | 8 | `LEFT_ACTION` |
| `NORTH` top face button | 1 | `TOP_ACTION` |
| `L1` left shoulder | 10 | `SHOW_KEYPAD` |
| `R1` right shoulder | 11 | `SHOW_KEYPAD` |
| `L2` left trigger | 12 | `KEYPAD_CLEAR` |
| `R2` right trigger | 13 | `KEYPAD_ENTER` |
| `L3` left stick click | 14 | `KEYPAD_0` |
| `R3` right stick click | 15 | `KEYPAD_5` |
| `START` Start | 3 | `PAUSE` |
| `SELECT` Select (tap) | 2 | `SWAP_CONTROLLERS` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| right stick | analog 1 | `KEYPAD_1_9` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `LEFT_ACTION` `RIGHT_ACTION` `TOP_ACTION` `KEYPAD_0` `KEYPAD_5` `KEYPAD_1_9` `KEYPAD_CLEAR` `KEYPAD_ENTER` `SHOW_KEYPAD` `PAUSE`

### `odyssey2`

*o2em is **not built** in this tree; unverified.* The Odyssey² pad is a stick and
one action button; the rest of the machine is a keyboard the core overlays.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `ACTION` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `KEYBOARD` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `ACTION` `KEYBOARD`

### `jaguar`

*virtualjaguar is **not built** in this tree; unverified.* The Jaguar pad is an
A-B-C row, an Option and a Pause button, and a twelve-key pad the core overlays.
The row takes the face arc as on any three-button pad.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `B` |
| `EAST` right face button | 8 | `C` |
| `WEST` left face button | 1 | `A` |
| `NORTH` top face button | 9 | `OPTION` |
| `L1` left shoulder | 10 | `KEYPAD_STAR` |
| `R1` right shoulder | 11 | `KEYPAD_HASH` |
| `START` Start | 3 | `PAUSE` |
| `SELECT` Select (tap) | 2 | `KEYPAD` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `C` `OPTION` `PAUSE` `KEYPAD` `KEYPAD_STAR` `KEYPAD_HASH`

### `arcade` `mame` `neogeo` `neogeocd`

*MAME (built).* MAME assigns arcade buttons to RetroPad IDs from its own
per-game profile and remaps them in its TAB menu, so EmuFusion does not claim a
particular cabinet's button numbering. What it does guarantee is that all eight
buttons, the coin slot and the start button are reachable, and that buttons 1-4
read across the face cluster in the same left-to-right order as a Neo Geo's
A-B-C-D row, with 5-8 on the shoulders and triggers.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `BUTTON_1` |
| `EAST` right face button | 8 | `BUTTON_2` |
| `WEST` left face button | 1 | `BUTTON_3` |
| `NORTH` top face button | 9 | `BUTTON_4` |
| `L1` left shoulder | 10 | `BUTTON_5` |
| `R1` right shoulder | 11 | `BUTTON_6` |
| `L2` left trigger | 12 | `BUTTON_7` |
| `R2` right trigger | 13 | `BUTTON_8` |
| `START` Start | 3 | `START_1` |
| `SELECT` Select (tap) | 2 | `COIN_1` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| right stick | analog 1 | `RIGHT_STICK` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `BUTTON_1` `BUTTON_2` `BUTTON_3` `BUTTON_4` `BUTTON_5` `BUTTON_6` `BUTTON_7` `BUTTON_8` `START_1` `COIN_1`

### `zx` `zxspectrum`

*Fuse (built), verified: **Fire is A(8), X(9) and Y(1); RetroPad B(0) is joystick
Up**, L(10) is Enter, R(11) is Space and Select(2) raises the keyboard overlay.*
A Spectrum joystick has one button, so Fire takes the bottom position — the
previous mapping sent the bottom button to RetroPad B(0), which walked the player
upwards instead of firing. The core's "Up" binding is left on the top face
button, where it works as the jump button Spectrum games expect from a keyboard.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `FIRE` |
| `EAST` right face button | 9 | `FIRE_2` |
| `WEST` left face button | 1 | `FIRE_3` |
| `NORTH` top face button | 0 | `UP` |
| `L1` left shoulder | 10 | `ENTER` |
| `R1` right shoulder | 11 | `SPACE` |
| `SELECT` Select (tap) | 2 | `KEYBOARD` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `FIRE` `ENTER` `SPACE` `KEYBOARD`

### `amiga` `amigacd32`

*PUAE (built), verified: fire/red=B(0), 2nd fire/blue=A(8), green=Y(1),
yellow=X(9), rewind=L(10), forward=R(11), play=Start(3), select=2.* A plain
Amiga joystick has one red fire button, which takes the bottom position; the
other three colours are the CD32 pad and fill the cluster, with its transport
buttons on the shoulders and Start.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `RED_FIRE` |
| `EAST` right face button | 8 | `BLUE` |
| `WEST` left face button | 1 | `GREEN` |
| `NORTH` top face button | 9 | `YELLOW` |
| `L1` left shoulder | 10 | `REWIND` |
| `R1` right shoulder | 11 | `FORWARD` |
| `START` Start | 3 | `PLAY` |
| `SELECT` Select (tap) | 2 | `SELECT` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| right stick | analog 1 | `MOUSE` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `RED_FIRE` `BLUE` `GREEN` `YELLOW` `REWIND` `FORWARD` `PLAY` `SELECT`

### `apple2`

*AppleWin (built), verified: Button 0=A(8), Button 1=B(0), the D-pad drives each
paddle to its extremes and `RETRO_DEVICE_ANALOG` index 0 is the paddle pair
itself.* An Apple II game controller is two paddles and two buttons, so the left
stick is the paddle pair rather than a second D-pad, and the two buttons take
the arc.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 8 | `BUTTON_0` |
| `EAST` right face button | 0 | `BUTTON_1` |
| D-pad | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| left stick | analog 0 | `PADDLE` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `BUTTON_0` `BUTTON_1` `PADDLE`

### `c64` `commodore64`

*vice-x64sc is **not built** in this tree; unverified.* A C64 joystick is one
fire button, which takes the bottom position; Select raises the core's keyboard
overlay.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `FIRE` |
| `EAST` right face button | 8 | `FIRE_2` |
| `WEST` left face button | 1 | `BUTTON_3` |
| `NORTH` top face button | 9 | `BUTTON_4` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `L2` left trigger | 12 | `L2` |
| `R2` right trigger | 13 | `R2` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `KEYBOARD` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| right stick | analog 1 | `MOUSE` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `FIRE` `FIRE_2` `START` `KEYBOARD`

### `msx`

*bluemsx is **not built** in this tree; unverified.* An MSX joystick is two
buttons, A then B, which take the arc; Select raises the keyboard overlay.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `A` |
| `EAST` right face button | 8 | `B` |
| `WEST` left face button | 1 | `BUTTON_3` |
| `NORTH` top face button | 9 | `BUTTON_4` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `L2` left trigger | 12 | `L2` |
| `R2` right trigger | 13 | `R2` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `KEYBOARD` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| right stick | analog 1 | `MOUSE` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `A` `B` `START` `KEYBOARD`

### `amstradcpc` `atarist`

*caprice32 and hatari are **not built** in this tree; unverified.* Both machines
take a two-button digital joystick plus a keyboard the core overlays.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `FIRE_1` |
| `EAST` right face button | 8 | `FIRE_2` |
| `WEST` left face button | 1 | `BUTTON_3` |
| `NORTH` top face button | 9 | `BUTTON_4` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `L2` left trigger | 12 | `L2` |
| `R2` right trigger | 13 | `R2` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `KEYBOARD` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| right stick | analog 1 | `MOUSE` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `FIRE_1` `FIRE_2` `START` `KEYBOARD`

### `dos` `windows` `windows9x` `scummvm`

*DOSBox Pure and ScummVM (both built) build their descriptors per title and ship
their own in-core remappers*, so no fixed console layout exists to reproduce.
EmuFusion puts every RetroPad control in its standard position and leaves the
choice to the core's own mapper.

| Thor control | RetroPad ID | Console control |
| --- | --- | --- |
| `SOUTH` bottom face button | 0 | `BUTTON_1` |
| `EAST` right face button | 8 | `BUTTON_2` |
| `WEST` left face button | 1 | `BUTTON_3` |
| `NORTH` top face button | 9 | `BUTTON_4` |
| `L1` left shoulder | 10 | `L` |
| `R1` right shoulder | 11 | `R` |
| `L2` left trigger | 12 | `L2` |
| `R2` right trigger | 13 | `R2` |
| `START` Start | 3 | `START` |
| `SELECT` Select (tap) | 2 | `KEYBOARD` |
| D-pad and left stick | 4-7 | `UP` `DOWN` `LEFT` `RIGHT` |
| right stick | analog 1 | `MOUSE` |

Console roster: `UP` `DOWN` `LEFT` `RIGHT` `BUTTON_1` `BUTTON_2` `START` `KEYBOARD`

## Systems that route to an external emulator

EmuFusion does not map controls for these; the external emulator owns its own
input. See [`external-emulator-routing.md`](external-emulator-routing.md). A
system with no table above falls back to the generic RetroPad — the console's
bottom button at the bottom, right on the right, left on the left, top on top,
with the left stick doubling as the D-pad.

| System | Route |
| --- | --- |
| `wiiu` | internal Cemu adapter (`LUCENT_INCLUDE_PHASE3_CEMU=1`); external Cemu without it |
| `switch` | internal Eden adapter (`LUCENT_INCLUDE_PHASE3_EDEN=1`); external Eden without it |
| `ps3` | no maintained Android emulator; cannot launch on-device |
| `psvita` | external Vita3K |
| `xbox` | external xemu |
| `xbox360` | external Xenia |
| `windows` | internal DOSBox Pure computer layout; optional external Winlator only when explicitly selected |
| `3do` | external Opera; no curated table |
| `3ds` | external Azahar or RetroArch; the table above is the internal core |

## Known gaps

* **Wii extensions.** `portDeviceFor("wii")` asks for Dolphin's
  Wiimote+Nunchuk device, but the in-process host calls
  `set_controller_port_device(0, RETRO_DEVICE_JOYPAD)` unconditionally and has
  no JNI entry point to change it, so extension-only titles do not accept input
  yet. The mapping is already correct for that device type.
* **Cores that are not built.** Stella, atari800, PicoDrive, vice-x64sc,
  bluemsx, o2em, caprice32, hatari, beetle-vb and virtualjaguar have no
  artifact in `engines/build/arm64-v8a/`, so their IDs could not be read from a
  descriptor table. Those sections say so; re-read them when the cores land.
* **ColecoVision keypad 9 and 0** share the left stick with nothing else, but
  the host sends `RETRO_DEVICE_ANALOG` index 0 on every motion event, so a
  deflected stick types on the keypad. That is the core's own binding, not a
  EmuFusion choice.
* **MAME** owns its arcade button numbering; EmuFusion only guarantees reach.

## Remapping

Every mapping above is a default. `InputRouter` and `FileRemapStore` already
resolve and persist a per-system or per-game override of any canonical control
into `controls/remaps.properties`, and a remap that moves a live source releases
the RetroPad ID it used to hold, so a button held across a remap never sticks
down. No in-game Controls screen calls `InputRouter.saveRemap` yet, so today
these defaults are what a player gets; the console control names in the tables
above are what such a screen would show.
