# Phase 2 Azahar integration checkpoint

## October 4, 2026: 16 KiB source build and normal recipe integrated

The older official core is rejected by the actual strict 16 KiB Android loader.
The same pinned 2125.1.3 source now compiles with NDK27/API23 after correcting
the Android GNU `strerror_r` branch. The regression compiles the actual formatter
against API21 and API23, reproducing the old API23 failure before the fix.
The core's load segments now use 16 KiB alignment. The loader accepts it.

`engines/build_core.sh azahar` now builds the exact 52 recursive Git links with
that patch and builtin keyblob disabled, instead of extracting the older binary.
Clean builds at two different paths on this host match
`d7150458b86d5493f5a78d850df204fe04b854124d92d0d2040fb104b6f69c7d`.
The default build directory was tested from an absent checkout through complete
compilation. Normal staging now selects this core; its hash-named predecessor
is preserved. Unknown source/output edits are rejected without replacement.
Compiler/linker evidence advances; runtime and release gates do not.

Exact APK `9be4fbd89c415b398d9dadbc30eacb2651bb15932834286e73b0208d9e6e2dc8`
ran offline on the headless, landscape Android16/16KiB simulator, with only
EmuFusion installed and unchanged app identity. Normal Star Fox 64 3D cold
launch, touch prompts, analog bank and laser charge in the control preview,
and live training entry were observed. Normal exits committed at 22:32:14.273
and 22:42:44.233; the intervening restore at 22:39:43.908 visibly restored the
gyro tutorial, and touchscreen Next advanced to Neutral Position. Both exits
retired the game surface and returned to the library in the same process.

This is bounded functional evidence, not a full mission or smoothness pass.
The first session recorded 18 underruns and 10,880 dropped PCM samples; the
short second session recorded zero. Most elapsed time was menus, tutorials and
intentional pauses, and no audible assessment was made. Updated existing app
data is not fresh-empty-data installation evidence. The final APK still has
one strict16KiB alignment failure (MAME). No public release or Thor mutation.

Evidence: `docs/qa/android-portability-2026-10-04-azahar-pages/outcome.json`,
`normal-integration.json`, hashed screens, loader logs and build logs. There
are 123 passing affected host checks, not 123 gameplay checks. AVD and logcat
are stopped; devices and forwards are empty. Full normal APK consolidation
and remaining system/runtime/fresh-install/update qualification remain open.

## October 2, 2026: single-screen Android portability

Qualification APK r22 (`63cc95454c2c5c70c0e913aabf440fef12f19ed4047344db4aaf75fd637c553d`)
fixes a reproduced phone-only stylus blocker: the primary gameplay touch listener
previously forwarded only to software libretro sessions, excluding Azahar.
The session hook now includes phase-2 3DS, maps the contained 720x240 composite
to the right-hand touch region, tracks one finger, and releases on cancellation,
pause and teardown. A valid physical secondary panel keeps its own touch route.
Tests execute real event handling at five viewport sizes; 56 focused checks pass.

The Android 16 landscape, windowless simulator restored Star Fox 64 3D's existing
checkpoint, accepted the previously ignored “Tap to begin”, changed control types
by touch, banked/fired with simultaneous virtual controls, advanced the training
sequence and exited normally with a committed checkpoint. See
`docs/qa/android-portability-2026-10-02/matrix.json` and the r22 screenshots/logs.
This is bounded training/input evidence, not complete-game or gyro qualification.

Azahar now defaults to native resolution rather than forcing the Thor-sized 4x
setting on every Android GPU. Display size/aspect is unchanged; supported explicit
core-option overrides can still upscale. This has **not** established an audio or
judder fix: 22 underruns accumulated after initially clean reporting. The cold 4x
intro and warm 1x checkpoint are not a controlled performance comparison. No
public release or Thor installation was performed for this candidate.

## Historical integration checkpoint

Date: 2026-08-07

Status: **one retail title passes the complete Thor activity/runtime gate;
multi-title, legal-fixture, source-reproduction, and release gates remain open;
not shipped**.

EmuFusion checksum-locks Azahar 2125.1.3 source and its official Android ARM64
libretro release ZIP. The SBOM represents the embedded core as
`EXTRACTED_FROM` that ZIP; it does not claim an upstream signature or a local
source-to-binary reproduction.

- Source commit: `b42d0916ba9799297ae0e27c07d56801da1b5de5`
- Source archive SHA-256:
  `8da46436e9d4cd937af2dba5ed39a33c2102e4f833c9051a9bb6e2711831e065`
- Release ZIP SHA-256:
  `4946db52ba9a559834cb3db075544480ac71fa4ae08b090a6708825a012a7b1b`
- Embedded core SHA-256:
  `d723066fa7c812618b5695d94b0fd85594e6c196e9e08ca9ba7134371a8da645`

The first-frame failure was a frontend fence-ordering deadlock. EmuFusion reset
the current Vulkan swapchain fence before `retro_run`; Azahar waited for that
same now-unsignalled fence while recording the frame, but the frontend could
only submit work that signalled it after `retro_run` returned. The host now
keeps the fence signalled while the core records and resets it immediately
before `vkQueueSubmit`. A source-order regression test protects this invariant.

The corrected route passed the full physical AYN Thor gate with the user-owned
retail image `The Legend of Zelda: A Link Between Worlds` on exact APK SHA-256
`da91c2e923f07e917e05347c858b2cda5f184095cda2d54ff3171933f465e033`.
Evidence in `unified-android/build/phase2-azahar-da91-rerun/results.json`
proves live Vulkan video; a stable 60.02 FPS rolling interval; continuous
32.728 kHz audio; physical A-button down/up with a visible frame response; held
Stop return to the same MainActivity/task; Quick Resume after process death;
one EmuFusion process/MainActivity/window identity; no external emulator; and a
fully black lower display during single-screen gameplay.

The runnable qualification scope is decrypted, user-owned CCI content. That
scope does not require external keys or system archives. Encrypted content
stays unavailable until EmuFusion defines and audits an exact user-file identity
policy; EmuFusion does not accept or distribute console keys.

Required follow-up includes at least two more retail-title runs, a pinned legal
homebrew fixture, 100-cycle state testing, firmware/system-data policy,
dual-screen titles, sustained thermal testing, source reproduction, notices,
and multi-device/16 KiB-page qualification. This single-title pass does not
promote Azahar to a release engine.
