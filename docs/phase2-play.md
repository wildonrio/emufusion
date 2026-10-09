# Phase 2 Play! integration checkpoint

## October 4, 2026: Android 16 KiB loader repair

The existing source recipe now aligns shared/module libraries to 16 KiB. Two
clean different-path builds match SHA-256
`911fad87e54c22fa328347fc908e7af8fa7fd7e8d10c272d620171d4681f5bc4`.
The old core is rejected by the actual Android16/16KiB loader; the new core
loads and reports Play! 0.30. The verified artifact is promoted, preserving
source pins/assets/licenses. This is loader/API proof only: **no new Play ROM
or gameplay test**. Historical runtime evidence below is not reassigned to it.
See `docs/qa/android-portability-2026-10-04-highend-pages/outcome.json`.

Date: 2026-08-07

Play! is EmuFusion's BIOS-free PlayStation 2 Phase 2 candidate. This checkpoint
now establishes exact source/build evidence plus the first in-process AYN Thor
runtime and process-death state proof. It remains a qualification candidate,
not an approved or auto-selected release engine.

## Exact source closure

- Primary upstream: `https://github.com/jpd002/Play-`
- Commit: `50aedca2639521bc498ace0b2be1ea012801a86a`
- Commit archive SHA-256:
  `a1dffa7cff03de6e40297a2a16ce6a61da31305b74b9233de9fa97238888758f`
- Compile-input lock: `engines/play-source-lock.json`

The lock captures the six direct gitlinks and the six nested gitlinks staged
for this build profile, including their upstream repositories, full commits,
and commit-archive SHA-256 values. The recipe performs checksum-verified fresh
extractions and does not trust mutable checkouts or recursively fetch during
configuration.

## Qualified compiler/linker profile

The proof uses the official upstream libretro adapter with:

- Android `arm64-v8a`, API 23;
- NDK `27.0.12077973`;
- CMake `3.31.6-g38307f9` and Ninja `1.12.1`;
- `BUILD_LIBRETRO_CORE=ON`;
- the separate Play! application and upstream tests disabled;
- upstream OpenGL/GLES hardware rendering; and
- deterministic epoch and path mapping followed by NDK `llvm-strip`;
- EmuFusion's narrow JavaVM, frontend output-size, and Android ART/JIT host hooks;
- a bounded audio FIFO for Play!'s asynchronous VM thread, with explicit
  overflow-drop telemetry rather than silent replacement; and
- a VM-paused state boundary that drains pending GS work without destroying or
  blocking the live renderer.

Run the exact recipe with:

```sh
./engines/build_core.sh play
```

Two clean archive restagings produced byte-identical stripped Android AArch64
ELF files:

- path: `engines/build/arm64-v8a/play_libretro.so`
- SHA-256:
  `a90adf7f06c12c8a7505420a18b18bfaca812737a7612436b69041a89fb86843`
- ELF BuildID: `9c4069bdd8ed090a7eaa36955b1c9ecc9ccaf463`

This proves that the locked, integration-patched source closure compiles and
links reproducibly for this host/toolchain profile. It does not by itself
establish release reproducibility.

## AYN Thor runtime checkpoints

An earlier qualification APK loaded the exact artifact above with God of War
from the user's library in the now-retired separate `LucentGameActivity`.
That historical result proved basic rendering, input, and state behavior but
does not satisfy EmuFusion's current one-`MainActivity` product contract.

- Output was aspect-fit to the Thor's 1920x1080 upper display.
- A-button input advanced New Game to the difficulty menu.
- Once warm in the menu, Play! delivered the complete 44.1 kHz stereo stream
  to EmuFusion and sustained a derived 60 FPS interval after JIT warm-up.
- Stop-menu exit committed compatibility-v4 Quick Resume, returned to EmuFusion,
  and a forced process death followed by a cold launch restored the exact
  difficulty menu with live rendering and audio.
- Health telemetry continued after restore, proving the successful state call
  did not leave the emulation or renderer threads blocked.

The stricter gameplay run did **not** pass the sustained-performance gate.
After the saved God of War session entered gameplay, current throughput settled
near 38 FPS and `AudioTrack` underruns accumulated. EmuFusion therefore keeps the
PS2 route experimental and does not auto-select or ship it. Menu-speed evidence
must not be represented as game-speed qualification.

The current one-window gate repeated the test with exact hardened APK SHA-256
`12e0e83494a75b0f709b93b2a0c4efed9810f7c1632dc5272f2e9278ead37006`.
Play! correctly remained inside
`org.pegasus_frontend.android.MainActivity` on display 0 with no external
emulator task. Its measured health samples were 39.67, 47.75, 40.91, 38.07,
36.40, 35.77, 33.11, 34.45, 35.34, and 35.03 FPS; audio underruns increased
from zero to 200. The hardened result is therefore an explicit performance
**FAIL**, not an incomplete test. Evidence is in
`unified-android/build/one-window-phase2-hardened-available-matrix/results.json`.

## Gates that remain closed

- Every staged dependency still needs a file-level license and notice audit.
- A specifically licensed, reproducibly built PS2 test fixture is not pinned.
- Vulkan and repeated surface-loss/context-loss behavior remain unqualified;
  the passing physical-device route is GLES.
- The full PS2 compatibility sample has not run; one user-owned title is not a
  compatibility claim.
- One process-death restore passes, but the required 100-cycle determinism,
  JIT invalidation, corruption, and version-migration matrices remain open.
- Sustained gameplay performance currently fails on the AYN Thor; additional
  optimization or a different legally integrable in-process engine is required.

Accordingly, the registry keeps `reproducible=false`, `shipped=false`, and the
release/runtime/device gates closed. The new runtime observations are recorded
as evidence, not converted into an unsupported phase-complete claim.
