# ScummVM Phase 2 integration record

ScummVM can run inside EmuFusion's existing `MainActivity`. The pinned upstream
source contains its own libretro backend and an official Android `ndk-build`
target. EmuFusion implements the libretro API independently; this route does not
package or launch a RetroArch frontend and does not use ScummVM's standalone
Android Activity or launcher.

This is currently a **qualification path**, not a release approval. It proves
that a pinned Android ARM64 core can be built for EmuFusion, but it does not close
the legal-content, dependency-license, runtime, performance, or device gates.

## Exact source closure

[`engines/scummvm-source-lock.json`](../engines/scummvm-source-lock.json) pins:

- ScummVM commit `6aa8fa9b6f9e5a7ae670cc355af1b727ff75c995`
- `libretro-deps` commit `7e6e34f0319f4c7448d72f0e949e76265ccf55a1`
- `libretro-common` commit `70ed90c42ddea828f53dd1b984c6443ddb39dbd6`
- Android NDK `27.0.12077973`, API 21, `arm64-v8a`

The build uses only SHA-256-verified archives after the fetch step. It disables
the upstream helper that would otherwise clone dependencies while Make parses
the core. A second staging-only adjustment removes
`libretro-deps/libmad/version`: that file contains package metadata, not C/C++
source, and its extensionless name shadows libc++'s standard `<version>` header
under NDK r27. The staged Android makefile also receives
`-Wl,-z,max-page-size=16384`; the recipe fails unless `llvm-readelf` confirms
that every `PT_LOAD` segment uses `0x4000` alignment.
The SHA-256-locked
`engines/patches/scummvm-lucent-exit-autosave.patch` adds EmuFusion's only
core-local behavior: a synchronous, fail-closed engine-native exit autosave
and per-content resume marker. It does not add a launcher or RetroArch UI.

Run:

```sh
./engines/build_scummvm_core.sh
```

The ignored outputs are:

- `engines/build/arm64-v8a/scummvm_libretro.so`
- `engines/build/arm64-v8a/scummvm-system/scummvm/` for pinned engine data and
  themes
- `engines/build/arm64-v8a/scummvm-COPYING.txt`

The initial profile uses upstream's checked-in `lite_engines.list`, with WIP
engines disabled. This is explicitly narrower than ScummVM's complete engine
set and must not be presented as universal ScummVM compatibility.

Two path-isolated clean builds completed byte-identically. The exact stripped
core is 25,793,128 bytes with SHA-256
`668aa27dd70990921372d95338dab6384610f721b7bcb4f224b67e63e44d1f4d`.
All three `PT_LOAD` segments have `0x4000` alignment. The 207 runtime-data
files have deterministic path/content tree hash
`e84d2de3dd5ff482e186f1cf6820ecf91e99bfacc586e97b3e795245bdfbb7f1`.

To repeat the clean comparison on a macOS host with the pinned NDK installed:

```sh
./engines/build_scummvm_core.sh
cp engines/build/arm64-v8a/scummvm_libretro.so /tmp/scummvm-first.so
./engines/build_scummvm_core.sh
cmp -s /tmp/scummvm-first.so engines/build/arm64-v8a/scummvm_libretro.so
shasum -a 256 /tmp/scummvm-first.so engines/build/arm64-v8a/scummvm_libretro.so
$HOME/Library/Android/sdk/ndk/27.0.12077973/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-readelf -lW engines/build/arm64-v8a/scummvm_libretro.so
```

## Direct launch contract

The core accepts either a `.scummvm` hook or any file inside a recognized game
directory. For ordinary library entries EmuFusion may pass a stable file within
the game directory; ScummVM's detector then launches that game directly. The
standalone launcher is not part of the task or recents identity.

Controller events and mouse-style analog motion use EmuFusion's existing libretro
input bridge. The core produces software frames and stereo PCM through the
same callbacks as other in-process engines. A legal qualification candidate is
pinned in `engines/scummvm-test-content-lock.json`: ScummVM's official
*Flight of the Amazon Queen - Freeware Floppy Version* download, SHA-256
`2e59de85f708cdb32bf85c85b394ac091c05f7647e856b71f5b3ae73fde761e0`.
It is fetched directly from ScummVM for testing and is never bundled in EmuFusion;
the freeware label is not treated as permission for third-party redistribution.

## Exit persistence contract

This is a hard upstream capability boundary, not an unfinished EmuFusion flag:

```text
retro_serialize_size() = 0
retro_serialize()      = false
retro_unserialize()    = false
```

ScummVM's own core metadata likewise declares `savestate = false`. EmuFusion must
therefore never send this core through the generic serialization vault.

The patched core instead exports this optional extension alongside the normal
libretro API:

```c
bool retro_lucent_prepare_exit_autosave(void);
```

The EmuFusion host calls it on held-Stop before `retro_unload_game()`. The normal
frame loop is stopped first; the extension synchronously switches into
ScummVM's emulation co-thread, so the save runs on the engine thread rather
than the Android UI or lifecycle executor. The request advances at most 120
core frames waiting for that request to be consumed. It returns `true` only
after all of these steps succeed:

1. the engine exposes a non-negative autosave slot;
2. the engine reports that saving is safe at the current point;
3. the slot is empty or already contains an autosave, never a manual save;
4. the engine reports a successful native save; and
5. the core flushes a per-content marker containing the engine-specific slot.

When any step fails—or when the event is not consumed within the bounded
wait—the quit event is suppressed and the game remains loaded. The host must
show the failure and must not call `retro_unload_game()`. A successful next
launch reads the per-content marker and adds ScummVM's `-x <slot>` option, so
the same native save is restored. The marker is keyed by the normalized
content path hash; it cannot cause a different library item to load the save.

Coverage is deliberately runtime-exact rather than claimed by engine family:
each title is enabled only when its live engine passes the five gates above.
For example, upstream SCI/SCI32 explicitly return autosave slot `-1`, so they
fail closed. Generic arbitrary Quick Resume and the 10-minute memory-state
timeline remain unavailable.

EmuFusion's host, JNI bridge, and Java session path enforce this contract. When
the extension returns `false`, the native host does not call
`retro_unload_game`; its loaded flag stays set and another frame can run. JNI
destruction refuses to bypass the gate. The session resumes the core, keeps the
user in the game, and shows a nonfatal retry message. The native mock suite
proves both branches: rejection has one prepare call and zero unload calls;
success has a second prepare call and exactly one unload call.

## Exact dependency compliance

`engines/scummvm-dependency-audit.json` records the 15 external components and
337 external object files in the exact audited binary. The build runs
`tools/generate_scummvm_compliance_bundle.py`, which fails on an unknown
component, object-count drift, changed license evidence, or artifact hash
drift. It emits the full ScummVM copyright/GPL text, LGPL text, all required
component notices, and a per-object SHA-256 manifest under
`scummvm-compliance/`. This is a binary-specific audit; it does not assert that
unlinked directories in either dependency archive are part of the payload.

Qualification packaging is fail-closed and must perform all of these steps:

1. run `engines/build_scummvm_core.sh` rather than copying a preexisting core;
2. stage `scummvm_libretro.so` as `liblucent_core_scummvm.so`;
3. stage the complete `scummvm-system/scummvm/` runtime-data directory at the
   system path exposed to the core;
4. stage the complete `scummvm-compliance/` directory in APK assets and expose
   its notices from EmuFusion's legal/About surface; and
5. abort if the generator, registry validator, artifact hash, runtime-data tree
   hash, 16 KiB segment-alignment check, or any required input fails.

The regular release path must remain unchanged until the device gates below
are closed; qualification inclusion is explicit and never silently selected.

## Android device qualification plan

Use only the pinned official-download fixture above for the initial gate:

1. Verify the ZIP SHA-256, extract it outside the APK, and launch a stable file
   inside its directory directly from EmuFusion.
2. Confirm one EmuFusion task/window, visible frames, stereo audio, and physical
   input without a standalone ScummVM or RetroArch Activity.
3. Reach a save-safe point, hold Stop, and confirm return to EmuFusion only after
   the native save and marker exist. Relaunch and verify exact resume.
4. Trigger Stop at an unsafe point and confirm a nonfatal message, no unload,
   and an immediately playable next frame.
5. Repeat 100 save/exit/resume cycles, including Android backgrounding, surface
   recreation, and forced process restart. Hash prior saves before each run and
   reject corruption or cross-title restore.
6. Exercise an SCI/SCI32 title as a negative capability check: the core must
   reject exit autosave rather than claim unsupported persistence.
7. Inspect logs/storage to confirm ScummVM never enters generic StateVault or
   the ten-minute serialization timeline.

## Open gates

1. Complete the Android device qualification plan above. The official freeware
   fixture is pinned and host true/false behavior is proven off-device; no
   Thor/device result is claimed by this work.
2. Package the qualification-only core and runtime data only through the exact
   compliance gate, then run multi-title device tests.
3. Decide whether the lite engine profile is acceptable; a full-engine build
   needs its own size, license, compatibility, and reproducibility evidence.
