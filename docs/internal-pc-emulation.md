# Internal PC emulation

EmuFusion's `windows` collection now defaults to the bundled DOSBox Pure core
and runs through the same `InWindowGameHost` used by the other internal
systems. Selecting a compatible PC title therefore keeps the library, engine,
video, audio, controller input, held-Stop return, and serialized state inside
the single `com.thorium.preview` process and MainActivity. It does not open
Winlator, RetroArch, a browser, a second Activity, or another task.

## Supported built-in scope

The current internal PC engine covers DOS software and user-supplied Windows
3.x/9x installations stored in a supported disk image or game package. Its
accepted collection extensions mirror the pinned DOSBox Pure core exactly:

`zip dosz exe com bat iso chd cue ins img ima vhd jrc m3u m3u8 conf`

EmuFusion never bundles Microsoft Windows, BIOS images, commercial games, or
installation media. A guest operating system and its license remain the user's
responsibility. The engine itself requires no firmware.

The `windows`, `win`, `windows10`, and `pc` frontend names all canonicalize to
the same internal `windows` system. The controller layer applies the computer
layout used by DOSBox Pure: the whole RetroPad remains reachable, while the
core's per-title auto-mapper and in-core remapper decide keyboard/mouse details.

## Modern Windows boundary

DOSBox Pure is not represented as a modern x86/x86-64 Windows compatibility
layer. Native Win32/Win64 PE games that require current Windows APIs, DirectX,
or x86-64 translation still need the planned Phase 3 Wine + Box64 container
adapter. That adapter must satisfy the same one-app contract before it can
replace this route: pinned and redistributable dependency closure, an
EmuFusion-owned Surface/audio/input bridge, per-game container lifecycle,
durable saves, safe teardown, and physical-device performance evidence.

Winlator remains in the optional external-emulator catalogue for users who
explicitly choose External in per-system settings. It is never the automatic
route when the bundled PC core is present.

## Qualification contract

`emufusion-internal-pc-callback-test.zip` is a deterministic CC0 fixture made
from the same source generator as the DOS probe. It must pass:

- the core callback and 100 serialize/unserialize cycles under system id
  `windows`;
- the real EmuFusion Activity route using engine id `dosbox-pure`;
- visible frames, audio, mapped controller input, held-Stop return, and state
  commit without an Activity/process/window transition;
- exact signed-APK route closure proving that the bundled DOSBox Pure artifact
  owns both `dos` and `windows`.

The Windows system remains qualification-only until these gates are captured
on the exact APK. Source wiring alone is not a device-compatibility claim.
