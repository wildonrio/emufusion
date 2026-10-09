# Phase 3 native-adapter architecture (Wii U first)

## September 30: Barbie audio/crash repair

Barbie Dreamhouse Party's two recorded native crashes came from guest
big-endian mixer controls being copied into native-endian internal state.
`cemu-mix-guest-endian.patch` separates the guest layout and converts it at
the HLE boundary. The sanitizer regression covers all 16,384 legal pan/span
combinations and signed mixer values.

Audio had two scheduling problems: AX consumed deadlines while a previous
mix period was still busy, and TCL graphics-ring waits did not service the
guest scheduler. `cemu-ax-pending-deadline.patch` preserves unsent periods;
`cemu-tcl-audio-fairness.patch` yields during prolonged GPU backpressure only
when guest interrupts permit and the scheduler is unlocked, then rechecks
the current ring writer. Actual-method regression tests cover both changes.
The AX fix alone still had device underruns; the combined correction did not
in the bounded Barbie test. This is not a broad Wii U or frame-generation pass.

Retained native SHA starts `f16107a0`, installed APK SHA starts `c48117e1`.
All 27 focused tests pass. Exact replacement preserved the installed package
identity. Measured gameplay had zero AudioFlinger underruns and no new crash
beyond the earlier 469-second crash time. See
[the acceptance record](qa/barbie-audio-crash-2026-09-30/result.json) for exact
hashes, measurements, test limits and the final lifecycle/OLED status.

The September 30 full configured-tree rebuild supersedes the historical
September 10 requirement to inject five retained objects into an older archive.
Those source corrections are now in the configured archives. Rebuild normally
with `/opt/homebrew/bin/ninja -C /Users/tyleryoung/Code/cemu/Cemu-0.5/build-lucent-static CemuAndroid`,
strip with the pinned NDK, and update the staged artifact/hash. This remains a
local configured-tree build, not an independently reproducible build.

October 4: Ninja 1.13.2 rebuilt all 519 steps and reproduced the tested
`fb10583d...` binary exactly after NDK29 stripping. The VulkanRenderer.cpp
source-lock row was stale and is now corrected; no native binary was changed.
Do not use the SDK's older Ninja 1.10.2 on this tree: even `-n` rejects and
removes the newer build log. See `qa/android-portability-2026-10-04-cemu-source-lock/`.

## Why

PS3 (RPCSX/aPS3e), Wii U (Cemu), and Switch (Yuzu-derived: Citron/Sudachi/Suyu;
Ryujinx is C#/.NET and not in-process embeddable on Android) have **no libretro
core**. Each is a standalone C++/Vulkan engine with an Android JNI wrapper. To
emulate them INSIDE EmuFusion — one app, one display-0 window, Lucent-owned
surfaces/input/audio/save, no external Activity — each engine is built as a
shared library implementing the EmuFusion native-adapter ABI and driven in-process.

Internal is the default. An unavailable engine or a failed internal load never
selects an external app automatically. External remains an explicit library
route preference, not an internal-session recovery action.

## The contract

`unified-android/native/include/lucent_native_adapter.h` defines the C ABI: an
adapter `.so` exports one symbol, `lucent_native_adapter_entry()`, returning a
const vtable (`describe/create/load/start/run_frame/set_control/pause/resume/
flush_save/serialize*/surface_recreated/stop/destroy`) plus an honest
`lucent_native_capabilities` (has_quick_resume, has_persistent_save, dual_screen,
required_firmware). EmuFusion verifies `abi_version` before any call and fails
closed on any missing capability — never faking a Quick Resume the engine can't
guarantee.

## Components (this milestone)

1. `include/lucent_native_adapter.h` — ABI (DONE).
2. `lucent_native_adapter_host.c` — loads an adapter `.so` by pinned path+hash,
   validates the vtable, and exposes a thin C driver used by JNI.
3. `NativeAdapterEngineSession.java` — implements `EngineSession`; owns the
   Android Surface(s), runs the frame loop on one render-owner thread (reusing
   the quiesce/detach discipline from `ExperimentalGlesRenderLoop`), maps
   `InputRouter` controls to `lucent_native_control`, wires audio to an
   `AudioTrack`, and reports capabilities to EmuFusion honestly (Wii U initially
   `has_quick_resume=false` → held-Stop flushes saves and exits, no fake QR).
3b. Dual screen: Wii U TV → display 0, GamePad → display 4 via the existing
    `SecondaryGameplaySurfaceRouter`, same path as DS/3DS.
4. `NativeAdapterCatalog.java` — registers native-adapter engines (Cemu) from
   the signed `engines/phase3-registry.json` + a `reproducibility-lock` artifact
   hash; fail-closed and absent unless the core `.so` is present in the APK.
5. `engines/cemu-source-lock.json` — pins Cemu source/deps (repo+commit already
   in `phase3-registry.json`).
6. Build recipe skeleton (`engines/build_native_adapter.sh` or a `build_core.sh`
   branch): reproducible Android ARM64 build of the Cemu engine as an adapter
   `.so`. **This is the multi-week heavy lift and is NOT done here.**
7. Routing: Wii U resolves INTERNAL by default; `GameLaunchRouter` returns an
   internal command only for a verified packaged adapter. An absent adapter
   yields no launch command. Only an explicit External choice uses another app.

## Testing without the real core

A mock adapter (`native/tests/mock_native_adapter.c`) implements the vtable with
a deterministic checkerboard + tone, so `native/run_tests.sh` proves the host,
vtable validation, capability gating, load/start/run/stop lifecycle, and
fail-closed paths under ASan/UBSan — exactly as `mock_core.c` does for libretro.
The real Cemu core plugs into the same host with no Java/host changes.

## Cemu same-process title lifecycle

Cemu's stock Android frontend is one-title-per-process: quitting a game calls
`exitProcess(0)`. EmuFusion deliberately keeps Cemu mapped so returning to the
menu and launching another Wii U title does not open another app or window.
That exposes three pieces of title-owned state which upstream can leave behind:

- `swkbdInternalState` points into guest system memory. The adapter calls
  `swkbd::resetForTitleShutdown()` before `CafeSystem::ShutdownTitle()` so an
  open software keyboard is hidden and the stale guest pointer cannot draw
  over the next title.
- `coreinit_allocFromSysArea()` is a bump allocator over the 32 MiB,
  early-mapped `CEMU_AREA`. `DestroyMemorySpace()` intentionally does not unmap
  that area. Without an explicit lifecycle boundary, every title leaked its
  8 MiB coreinit system heap and smaller guest structures. The measured failure
  entered `coreinit::InitSysHeap()` with `sysAreaAllocatorOffset = 0x1dd5000`;
  adding the next 8 MiB exceeds `0x02000000`, so the allocator's intentional
  out-of-bounds assertion raised SIGTRAP.
- The generated AArch64 recompiler entry trampoline lives for the process, but
  `PPCRecompiler_init()` frees and re-reserves `ppcRecompilerInstanceData` for
  every title. Upstream embedded the first reservation directly into the
  one-shot trampoline. The first two titles happened to receive the same mmap;
  the third did not. Its crash had x27 = `0x79b4237000` and fault address
  `0x79d4237000`: exactly x27 + `0x20000000`, the offset at which
  `ppcRecompilerDirectJumpTable` follows the 256 MiB-address-space function
  table. The trampoline now loads the current global pointer on every entry
  instead of retaining a retired reservation.

The Cemu patch now captures the process-owned system-area prefix exactly once,
after `CemuCommonInit()` and before the first title is prepared. After
`CafeSystem::ShutdownTitle()` has stopped every guest thread, it clears and
rewinds only the title-owned suffix and resets host MEM heap indexes which
pointed into that suffix. Process-wide `SysAllocator` pointers below the
boundary remain stable. The recompiler fix deliberately does not retain or
zero a one-gigabyte reservation between titles; the normal per-title ownership
and cleanup remain intact, and only the generated entry's pointer load changes.
The regression test in
`tools/tests/test_phase3_native_adapter.py` locks the source order, source and
artifact hashes, both measured crash-address calculations, repeatable reuse of
the title allocation window, and the dynamic AArch64 pointer load before the
JIT branch. Thor acceptance still has to prove at least three alternating Cemu
launches against the rebuilt exact APK; host tests cannot substitute for that
device gate.

## Firmware/keys (legal gate)

Each engine declares that it has user-supplied runtime inputs through the
adapter ABI's legacy `required_firmware` field, and
`NativeAdapterSystemDirectory` has the authoritative per-engine layout. Treat
that ABI value as a nonzero gate, not as a promise that every listed input is
universally required. EmuFusion never bundles or downloads console keys or
firmware.

The update/import scan searches readable user-authorized internal and removable
storage roots. It persists only `READY` or `NOT_READY`, never a source path,
filename, or failure detail. A verified packaged adapter remains the automatic
internal route even before a fresh device has recorded `READY`. External is
used only after an explicit user choice; missing prerequisites never authorize
a browser/download intent or an automatic standalone-app fallback. Launch
revalidates and copies the inputs into the app-private
`engine-system/<engineId>` root to close the time-of-check/time-of-use gap, and
retains the generic `Internal emulator prerequisites are unavailable` exception
at the validation boundary. The session presents fixed, system-specific setup
instructions (expected filename and public `ROMs/<system>` folder), never key
contents or a user's private source paths.

- **Switch (Eden), legacy ABI `required_firmware = 2`** — a valid
  `keys/prod.keys` is the only universal readiness requirement;
  `keys/title.keys` is optional. System firmware is title-specific, not a
  baseline requirement. If a valid user-owned `Firmware*.zip` is present,
  EmuFusion installs its NCA contents opportunistically under
  `nand/system/Contents/registered`; its absence does not prevent internal
  routing for titles that do not need firmware. Reference user layout:
  `Games/switch/Keys/`, with an optional archive beside it.
- **Wii U (Cemu), `required_firmware = 1`** — a single `keys.txt` of AES-128 disc
  keys, one 32-hex-character key per line (`#`/`;` comments), installed at the
  ROOT of the engine directory because that is where Cemu's `KeyCache_Prepare()`
  reads it from (`ActiveSettings::GetUserDataPath("keys.txt")`). There is NO Wii
  U firmware archive and no OTP dump. Reference user layout:
  `Games/wiiu/Keys/keys.txt`.

October 5 portability correction (candidate, not runtime-qualified): the legacy
count does not make disc keys mandatory for decrypted WUA/RPX/ELF/WUHB content.
The launch resolver now receives the selected file, imports valid optional keys
when present, and otherwise lets Cemu validate that decrypted content. It does
not mark encrypted-disc readiness true merely because a decrypted title can
launch. WUD/WUX/ISO and unknown types retain required-input checks; Switch and
PS3 are unchanged. No keys or firmware are bundled or downloaded.

Cemu's original one-shot key cache also retained an empty list after the first
keyless launch. `KeyCache_Reload` refreshes the list between titles, after the
initial title scan has completed and before parsing the new title, never during
active disc reads. Executable resolver/parser regressions reproduce both old
failures. Native candidate `589d8f43` and all284 production Java files compile;
controlled APK `03244295` passes packaging/signing/20-route/strict16KiB gates,
changing only Cemu and two Java classes versus private `745980f3`. It inherits
unaccepted PS2 changes and is not installed/released. No device/gameplay acceptance
yet; previous staged `fb10583d` is unchanged.
Evidence: `qa/android-portability-2026-10-05-wiiu-content-inputs/`.

Users can place their legally obtained inputs on internal or removable storage
and refresh the library. The explicitly chosen external Switch option is the official Eden Android
package `dev.eden.eden_emulator`, with the legacy Eden and Citron package IDs
retained for compatibility, and it launches the selected game directly rather
than opening an emulator library screen.

## Definition of done (per handover §8.6)

Same one-app, real-menu, controller, save, return, legal, reproducibility, and
exact-artifact gates as Phases 1/2. "The emulator exists on Android" is not
sufficient; the adapter must run several Wii U titles at full speed with sound,
correct dual-screen routing, and a clean held-Stop return.
