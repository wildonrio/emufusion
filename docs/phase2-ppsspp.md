# Phase 2 PPSSPP integration checkpoint

## Android 16 KiB loader repair (2026-10-04)

The pinned PPSSPP recipe now sets 16 KiB shared/module linker alignment. Two
clean different-path builds produce `376659948724e422876d31d61cc5dd130bfe5a2e941d64c6bf4225c2f2a23c6d`;
the full normal recipe also passes its updated artifact/compliance gates. The
old core fails the real Android16/16KiB loader; the rebuilt core loads and answers
libretro system-info. Exact artifacts and generated hash-only notices promoted;
source versions, runtime assets and licenses unchanged.

Candidate `4122698d...1f039c`, offline headless landscape16KiB with only EmuFusion:
normal PSP cold launch reaches Castlevania Stage0 gameplay/visible whip. Two normal
exits commit and retire; intervening Quick Resume restores the restart cutscene
and proceeds to gameplay. One first-session audio underrun remains. Idle enemy
damage confounds directional/jump checks. Menus, FMVs and pauses are not active
gameplay time; no listening, zero-judder or physical-GPU pass is claimed. Earlier
70-second clean-audio evidence below belongs to its earlier 4KiB candidate.

Evidence: `docs/qa/android-portability-2026-10-04-highend-pages/outcome.json`.
93 focused checks pass; whole APK still has Azahar/MAME alignment failures. No
fresh-empty-data installation or public release; simulator stopped, Thor untouched.

## Clean recovery build recheck (2026-10-04)

The diagnostic-only limitation below is superseded by clean candidate
`7090f362a2dd7acd5ff416b9d3dc05b96be895e35dc9ec5d98befa90c6523897`.
It has no recovery-probe logging and carries the same tested native host
`6d47f137f9b458adddc6d5c2820a9e79443d36ddc0c65e63c89197b6a95b2f77`.
The ordinary native build now reproduces that exact host into normal staging;
the Vulkan/Phase3/timer host libraries remain byte-identical. Prior staging
is backed up. This is a debug qualification candidate, not a public release.

Offline landscape Android16 normal-library launch, Continue and attack input
are exercised. Gameplay captures bracket a **70.282-second telemetry window
with zero AudioTrack underruns and zero PCM drops** (13:27:49.571–13:28:59.853).
Audio delivery/playback advances; no host pause occurs until 13:29:22.715.
Screenshots do not exclude in-game life/scene transitions between captures,
and this is not listening or distinct-frame/no-judder acceptance. The longer
run includes menus and cutscenes, and must not be reported as all active play.

Normal exit commits at 13:30:46.911 and retires the game surface. A cold app
restart logs restoration at 13:33:03.441; Stage0 is visible behind the pause
overlay afterward. This corroborates resumed game progress, not a frame-identical
restore position. Second normal exit commits/retires at 13:36:48 and visibly
returns to the library. App hash, UID and first-install time remain unchanged.

The real-entry JNI test initially failed to compile because it omitted the new
shared production helper. Its fixture now includes that helper and exercises
both presented and unpresented execution, warmup and errors. Nine affected
regression tests pass, plus the clean APK's one-app and Java/JNI contract gates.
No runtime source was changed during this clean recheck. Evidence:
`docs/qa/android-portability-2026-10-04-psp-pacing/recovery-clean/outcome.json`,
`finish.json`, `native-staging-verification.json` and `../analyze_clean.py`.
The clean candidate is retained for subsequent system qualification; other
systems' historical results are not silently elevated to passes on this APK.

## Bounded display-backlog recovery candidate (2026-10-04)

The earlier audio failure is now attributed to presentation back-pressure, not
an assumed slow core: a native timing observer reproduces the original host
byte-for-byte before instrumentation. In the gameplay-bracketed 25.083-second
window, 1,500 calls spend 1.066 seconds in emulation and 23.793 seconds in
presentation (95.7% of native work). Merely retaining 250 ms of schedule debt
still accumulates underruns; that first candidate is not a fix.

Candidate `72928adf517dd7764ccb92774f3d33787d2cc1634c707ebb04a919b0f2ba2383`
adds an explicit guest-step-without-presentation JNI path. Only PSP frontend-FBO
direct output opts into bounded catch-up: at most four consecutive offscreen
guest steps, preserving audio without claiming that a display occurred. FG input
surfaces and other cores retain their recovery policies. Warmup, close, context
ownership and first-presentation/restore behavior are preserved. PSP drains PCM
on these unpresented guest steps instead of tying audio solely to display swaps.

On offline headless landscape Android 16, the normal library route restores the
checkpoint. A reviewed gameplay window from 13:01:32.576 to 13:02:32.776 (60.2 s)
records **zero AudioTrack underruns and zero PCM drops**, including recovery
events. All health samples through 13:03:27.959 stay at zero; the longer interval
also includes game-over, Continue and transitions, so is not all active gameplay.
Normal Exit at 13:05:58 commits Quick Resume at 13:06:03 and removes the retired
surface. The new checkpoint has not yet been restored. Screenshots/telemetry do
not establish artifact-free presentation, listening quality or physical GPUs.

The 22-test regression run, four-test boundary run (overlapping tests), and actual
Java lifecycle/render-loop executables pass. Boundaries cover opt-in isolation,
FG exclusion, bounded batches, audio-only callbacks and native execution status.
The Android Java/JNI compile/export contract also passes against the isolated
candidate library without rebuilding or replacing normal native staging.
The exact installed APK/UID/first-install time are verified. Evidence and
reproducible analysis: `docs/qa/android-portability-2026-10-04-psp-pacing/`.

This remains a **qualification candidate**, not a release. Source changes are
retained, but ordinary native staging is still the previous host. The trial APK
contains recovery logging; build a clean matched Java/native artifact and rerun
restore/active audio before promotion. Never pair the new Java bridge with the
old host library. Final baseline restoration/shutdown is recorded in `finish.json`.

## Checkpoint restore and active-audio recheck (2026-10-04)

The exact `807dfefd587d040ef21dcef05dd91e66ff0508a7d29cd7c03c011b1cb47a9159`
candidate restored the earlier r22 checkpoint into Stage 0 through a normal
internal library launch on the headless, landscape Android 16 ARM64 AVD. Only
EmuFusion was installed; networking was disabled. Normal exit returned to the
library and committed a new checkpoint; APK, UID and first-install time stayed
unchanged. The simulator was then shut down. No production changes or new APK
were made for this recheck.

Audio remains **failed/unqualified**, not fixed: the visually bracketed active
gameplay interval contains a 72.783-second telemetry window with 4,200 core
callbacks (57.706/sec), 213 additional AudioTrack underruns and zero Java PCM
drops. The longest 300-callback interval took 7.060 seconds. There was no host
pause until after this window. These are core/audio counters, not distinct frame
presentation or a listening test. This run's jump attempt coincided with damage
and is not a new independent input pass. Earlier game-over/menu time is excluded.

The absolute PSP schedule and independent sink can lose buffered reserve;
simply increasing capacity does not establish a cure. Next correlate actual
producer work and deadline rebases with sink occupancy before changing recovery
or clock feedback. Do not assume clock drift alone explains the longer stalls.
Reproducible checks and full evidence:
`docs/qa/android-portability-2026-10-04-psp-active/analyze.py` and `outcome.json`.
The old statement below that checkpoint restore was untested is superseded for
this exact artifact/run; sustained audio and broad compatibility remain open.

## Single-screen Android 16 qualification checkpoint (2026-10-02)

The r22 combined qualification APK (SHA-256
`63cc95454c2c5c70c0e913aabf440fef12f19ed4047344db4aaf75fd637c553d`)
includes the pinned PPSSPP engine and its runtime assets. This supersedes the
older packaging description below for this exact qualification artifact only;
it is not a public release or a claim that every ordinary build includes it.
The landscape ARM64 Android 16 AVD has only `com.thorium.preview` installed as
a third-party package, runs with `-no-window`, and uses ADB screenshots/input.
The signed APK passes the one-app boundary verifier. No external emulator app
or chooser is involved in the tested normal library launch.

The owned Castlevania: The Dracula X Chronicles image, SHA-256
`0a809cf7a8d5e200318210607025b7815b1018d0f68c1eb569a5036dfb818511`,
was copied without changing the original. The 20:29:18–20:49:06 run in PID 15708
verified setup, title/menu navigation, a new simulator-only Player 1 slot named
`A`, actual Stage 0, visible jump and whip attack, game pause, host pause/resume,
and normal return to the library. Sparse test observations initially missed
the short title window and saw only the attract sequence. Sending Start during
that window reached the menu; no code fix for a supposed missing menu is claimed.

The five-second two-finger right/Square probe proves dispatch, not independent
movement response: the cart sequence and damage reaction do not isolate that
control. Exit commits the checkpoint at 20:49:06.472 and retires the surface at
20:49:06.677. Restoring that checkpoint was not tested. Initial active telemetry
reports near 60 callbacks/sec with zero underruns; later windows accumulate 20
underruns and zero PCM drops. Cumulative FPS after explicit pauses cannot be
used as active-play performance. Sustained audio, presentation pacing, directional
movement and broad title compatibility remain unqualified.

Evidence is in `docs/qa/android-portability-2026-10-02/`: `psp-r22-runtime.log`,
`psp-multitouch-r22.log`, and screenshots `screens/psp-save-menu-r22.png`,
`screens/psp-jump-r22.png`, `screens/psp-whip-r22.png`, and
`screens/psp-library-exit-r22.png`. This is bounded gameplay evidence; the open
release gates below remain open. The Thor was not woken or modified.

Status: **experimental, buildable, qualification-packaged, not release-qualified,
not shipped**.

This checkpoint establishes a pinned Android ARM64 compiler/linker source-build
proof for the official PPSSPP libretro target with PPSSPP's exact FFmpeg
dependency enabled. Two isolated builds reproduce byte-for-byte after removing
only the linker's path-dependent GNU build-ID note. Runtime remains unqualified
and `build.reproducible=false` until the remaining gates pass. EmuFusion hosts
that target through its own libretro ABI implementation. No RetroArch frontend
source, package, configuration, menu, or runtime is used.

## Pinned upstream identity

- Repository: <https://github.com/hrydgard/ppsspp>
- Release tag: `v1.20.4`
- Annotated tag object: `3a31057b7e44270b4d5cef8c31b6559d51802a3b`
- Peeled source commit: `fa50bb1976065c4f8b1b47af227d367fe9771555`
- Source archive SHA-256:
  `9054138072d49c306d65c17059bd85662b4ff46abe1ea6bb53d854dc80592ea6`
- Android target: `arm64-v8a`, API 23, NDK `27.0.12077973`

`engines/build_core.sh ppsspp` verifies every archive before extracting it,
stages the exact compile-input closure for this Android ARM64,
`LIBRETRO=ON`, `USE_FFMPEG=ON` profile into a clean source tree, and builds
`ppsspp_libretro_android.so` with CMake/Ninja. This wording is intentionally
configuration-specific: it does not claim every unused upstream gitlink is
part of the staged closure. The recipe does not trust floating branches or
live submodule checkouts.

The recipe ignores generic CMake, Ninja, NDK-version, and NDK-root overrides
for this proof and verifies the locked Darwin binaries/metadata before fetching
source. Builds sharing one `BUILD_ROOT` are serialized by an atomic lock;
callers may instead use a distinct `LUCENT_ENGINE_BUILD_DIR`. The checked-in
version patch is SHA-256 verified before application.

The archive has no `.git` directory, so EmuFusion applies a narrow checked-in
patch that fixes PPSSPP's reported build version to `v1.20.4-fa50bb1` instead
of allowing it to become host-dependent or `unknown`. The final staged ELF is
stripped with the pinned NDK's `llvm-strip --strip-unneeded`, then the pinned
`llvm-objcopy` removes only `.note.gnu.build-id`. Compile steps set
`SOURCE_DATE_EPOCH=1778934711`, the pinned commit timestamp, so embedded C
`__DATE__`/`__TIME__` strings cannot vary with the local build clock. The same
steps force `LC_ALL=C` and `TZ=UTC` to remove locale and timezone drift. Clang
file/debug/macro prefix maps replace repository and staging paths so the ELF
does not retain the builder's absolute workspace path.

## Production-profile reproducibility evidence

Two isolated build roots each re-extracted all checksum-verified inputs,
restaged the source tree, compiled all targets, and stripped the final ELF.
The raw outputs differed only in `.note.gnu.build-id`, whose value LLD derived
from the absolute build root. After removing that non-runtime note, the outputs
were byte-identical:

- Artifact: `engines/build/arm64-v8a/ppsspp_libretro.so`
- SHA-256: `1c1b192451375445badc7b69c917b82058d411fd94d66bd6bc00bc781e205487`
- GNU Build ID: absent by declared normalization
- Absolute builder workspace/SDK path matches: `0`

This evidence applies only to the declared Android ARM64 compiler/linker proof
with `USE_FFMPEG=ON`. It does not qualify PSP gameplay, video playback,
renderer lifecycle, save states, performance, hardware, packaging, or
distribution, and therefore does not open any release gate.

## First build scope

The first source-build proof uses:

- `LIBRETRO=ON`
- OpenGL ES and Vulkan compilation enabled by upstream's Android target
- `USE_FFMPEG=ON`
- `OPENXR=OFF`
- `USE_MINIUPNPC=OFF`
- Discord, tests, Atlas tool, and ccache disabled

OpenXR-SDK and miniupnp remain in the source closure even with their runtime
features disabled because PPSSPP still compiles translation units that include
their headers. Omitting either makes the clean build fail closed.

The resulting first proof is an ELF64 AArch64 shared object and exports the
required `retro_init`, `retro_load_game`, `retro_run`, `retro_serialize`, and
`retro_unserialize` entry points. Its dynamic dependencies are Android platform
libraries only (`log`, `OpenSLES`, `android`, `GLESv2`, `EGL`, `dl`, `m`, and
`c`). That is a compiler/linker proof, not a gameplay qualification.

The recipe pins PPSSPP's exact `ppsspp-ffmpeg` gitlink at
`1e3b4965632f60b1d85360261d1b9dd45444bc71` (FFmpeg 3.0.2), verifies the
3,381-file sparse source/build/Android closure, and verifies each upstream
Android ARM64 static archive before linking. Those archives record Android API
21 and NDK `29.0.14206865` as their upstream build identity; the final PPSSPP
shared object is independently linked and gated at API 23 with NDK
`27.0.12077973`. FFmpeg's embedded configuration has GPL, nonfree, and version3
disabled, with concluded license `LGPL-2.1-or-later AND IJG`.

### Black-transition diagnosis

The previous `USE_FFMPEG=OFF` artifact compiled PPSSPP's media-engine fallback:
`MediaEngine::stepVideo()` advanced the PSP movie timestamp and returned
success without decoding or scaling a video frame. That behavior matches the
observed clean boot followed by continuing `retro_run`/audio and repeated black
images at the first FMV/game transition. The new profile compiles the actual
FFmpeg demux/decode/scale path (`USE_FFMPEG:BOOL=ON` is recorded in the build
cache) and links the five verified ARM64 archives. This closes the provable
host-side cause; only a physical run through the affected transition can prove
the runtime symptom is resolved.

## Qualification-only Android package

EmuFusion can now package the exact compiler proof behind the explicit
`LUCENT_INCLUDE_PHASE2_PPSSPP=1` build flag. The package includes a separate
Phase 2 registry and fail-closed opt-in (`autoSelect=false`), verifies the core
hash again inside the signed APK, installs the pinned `PPSSPP` runtime asset
tree into app-private storage, and routes an explicit `engine_id=ppsspp`
request through EmuFusion's own GLES surface and controller path. Normal EmuFusion
builds contain none of these assets and do not select this route.

This is a packaging and renderer qualification milestone, not a release gate.
The qualification session has PCM transport, durable save RAM, failure-honest
Quick Resume, ten-minute active-play checkpoints with restore history,
controller remapping and dual-stick input, phone touch fallback, and a
Lucent-owned GLES surface. Native host calls remain render-thread-affine, and
state identity includes both the ROM SHA-256 and the exact pinned PPSSPP commit.
Fresh physical validation of the FFmpeg-enabled artifact, Vulkan, checkpoint
screenshots, a legal runnable PSP fixture, repeated state cycles, sustained
profiling, and broad device coverage remain absent.

## AYN Thor runtime checkpoint (2026-08-07)

EmuFusion's combined qualification APK packaged the then-current FFmpeg-off
PPSSPP artifact together with the Phase 1 cores. This historical checkpoint
does not qualify the FFmpeg-enabled artifact documented above. Both signed-APK
payload verifiers passed before install.
The final exact run used APK SHA-256
`12e0e83494a75b0f709b93b2a0c4efed9810f7c1632dc5272f2e9278ead37006`.
Gameplay remained in `org.pegasus_frontend.android.MainActivity` in EmuFusion's
single process/task/window on the upper 1920x1080 display; no PPSSPP
application, external emulator activity, RetroArch frontend, or on-screen
controls appeared. The private, excluded-from-recents `PreviewActivity` was
confined to display 4 and rendered black throughout single-screen gameplay.

Four user-supplied PSP images available on the device reached visible boot or
game content inside EmuFusion:

- LittleBigPlanet
- Castlevania: The Dracula X Chronicles
- God of War: Chains of Olympus
- God of War: Ghost of Sparta

This commercial-content smoke run is compatibility evidence only. It is not a
redistributable fixture and does not close the `legalContent` gate.

The first physical run exposed two ABI crashes in EmuFusion's host and one timing
defect, all now covered by host regressions or the render-loop contract:

1. `SET_INPUT_DESCRIPTORS` and `SET_PERFORMANCE_LEVEL` were incorrectly parsed
   as `retro_variable` arrays. They now use their actual payload types.
2. PPSSPP requires `GET_LOG_INTERFACE`; EmuFusion now supplies the libretro log
   callback instead of allowing a null call target.
3. The render loop used to wait a full frame interval *after* emulation and GPU
   work, making a nominal 60 Hz core run below real time. It now schedules
   absolute frame deadlines. Repeated AudioFlinger samples on the Thor then
   stayed at zero underruns instead of accumulating thousands of missing frames
   per second. The streaming buffer was reduced from roughly 200 ms to the
   platform minimum or 50 ms, whichever is larger.

The final automated gate dispatched physical A down/up through the Odin
Controller node, observed 1,246,166 changed upper-display pixels, and measured
60.44 FPS with 219,264 received/written stereo frames and no AudioTrack
underruns. Holding the physical Thor Stop/Select button for 1.15 seconds
returned to the same EmuFusion `MainActivity` only after the state commit
completed. A forced process death then restored Quick Resume with live video
and audio at 60.42 FPS. The lower panel capture contained zero visible pixels.
The machine-readable evidence is
`unified-android/build/one-window-phase2-psp-hardened-stop-final2/results.json`.

These results pass the exact one-window physical GLES, input, audio, lower-panel
blanking, Stop-return, and one process-death restore checkpoint,
but do not change `shipped=false` or any aggregate registry gate. One device,
four titles, one exact state journey, and a short audio run do not satisfy the
20-title/100-cycle, Vulkan, single-screen-device, remapping, migration, thermal,
or sustained frame-pacing requirements.

The same build generates and packages a deterministic SPDX 2.3 document at
`assets/phase2-sbom.spdx.json`. It identifies the exact PPSSPP source archive,
the packaged Android ARM64 binary hash, and every staged dependency archive in
`engines/ppsspp-source-lock.json`. Unknown dependency conclusions remain
`NOASSERTION`; the SBOM is provenance evidence, not a substitute for the open
file-level license audit.

### Current Quick Resume safety gate (2026-08-10)

A later frame-generation qualification run reproduced a stricter failure that
the earlier single restore did not expose: PPSSPP accepted the matching state,
continued `retro_run` and audible PCM near 60 Hz, but after title navigation it
submitted only repeated black images. Recreating the presentation surface did
not make that restored guest safe. Automatic PPSSPP snapshot restore therefore
fails closed in the current source. The verified snapshot is left on disk and
ordinary PSP savedata is still preserved, but EmuFusion performs a clean PSP
boot until restore-to-gameplay, renderer migration, and repeated-cycle tests
all pass. No release or state gate may cite the older one-cycle evidence as
proof that current automatic restore is qualified.

## Firmware and assets

PPSSPP is an HLE emulator and upstream explicitly states that it requires no
PSP BIOS. It does require PPSSPP's own redistributable runtime assets under the
frontend system directory (`PPSSPP/compat.ini`, fonts, HLE flash files, and
related data). The recipe stages the pinned upstream `assets` tree separately
as `ppsspp-system/PPSSPP`; these assets are not Sony PSP firmware.

Commercial games, decrypted modules, keys, Sony firmware, and PSP SDK content
are never fetched or distributed by EmuFusion.

## Dependency and license checkpoint

The build pins the following staged compile-input closure, including the two
nested dependencies needed by those inputs. Archive hashes are embedded in the
recipe. This is not a claim that unused upstream gitlinks are enumerated.

| Path | Commit | Preliminary license evidence |
| --- | --- | --- |
| `ext/SPIRV-Cross` | `4212eef67ed0ca048cb726a6767185504e7695e5` | Apache-2.0 |
| `ext/aemu_postoffice` | `530fee545c27ffb8524a8f496cbbcfdb687fe8c5` | GPL-3.0-only file present |
| `ext/armips` | `a8d71f0f279eb0d30ecf6af51473b66ae0cf8e8d` | MIT |
| `ext/armips/ext/filesystem` | `3f1c185ab414e764c694b8171d1c4d8c5c437517` | MIT |
| `ext/cpu_features` | `fd4ffc1632db7b4e763bd28ffa6fc9d761cf3587` | Apache-2.0 |
| `ext/glslang` | `50e0708ec3a5c16020c4f845c654b80b8edb80bd` | mixed permissive notices; file-level audit required |
| `ext/libadrenotools` | `8fae8ce254dfc1344527e05301e43f37dea2df80` | BSD-2-Clause |
| `ext/libadrenotools/lib/linkernsbypass` | `aa3975893d83ef1bc84c321ec60c65fbf1287887` | BSD-2-Clause |
| `ext/libchdr` | `8bba7745d758627258b315997a860039244cedaf` | BSD-3-Clause-style notice |
| `ext/lua` | `7648485f14e8e5ee45e8e39b1eb4d3206dbd405a` | MIT text in `lua.h` |
| `ext/miniupnp` | `27d13ca9beeb5541f5fbf11959dced03dac39972` | BSD-3-Clause |
| `ext/naett` | `5f695cfa9fcbf30668a4d3ac4b4abf1cd89a1302` | MIT |
| `ext/OpenXR-SDK` | `be392bf6949adeeabad5082aa79d12aacbda781f` | Apache-2.0 plus file-scoped notices |
| `ext/rapidjson` | `73063f5002612c6bf64fe24f851cd5cc0d83eef9` | MIT plus bundled third-party notices |
| `ext/rcheevos` | `ebfe8ca1bf944358e27200d66964fcb4e00e2487` | MIT |
| `ext/zstd` | `f8745da6ff1ad1e7bab384bd1f9d742439278e99` | BSD-3-Clause |
| `libretro/libretro-common` | `76a3d54feb0ee0ce9d59b90aa24694f3782063d3` | file-scoped permissive/public-domain notices |
| `ffmpeg` | `1e3b4965632f60b1d85360261d1b9dd45444bc71` | LGPL-2.1-or-later AND IJG; GPL/nonfree/version3 disabled |

PPSSPP itself states GPL-2.0-or-later and its top-level license also includes
PSPSDK-derived BSD-compatible notices. The generated compiled-source audit
concludes the combined binary is GPL-3.0-only because the linked closure
includes `aemu_postoffice` GPL-3.0-only material and `libkirk` GPLv3 material.
The checked-in compliance bundle records all 967 compiled files, all 3,381
FFmpeg corresponding-source files, every FFmpeg static-archive member, source
coordinates, hashes, toolchain identity, and exact license texts. This is not
final legal approval; distribution counsel, asset review, and runtime
qualification remain open.

## Legal qualification fixture

PPSSPP's pinned `pspautotests` submodule includes useful binaries but its
`LICENSE.txt` literally contains an unfilled license placeholder. EmuFusion will
not copy, execute as a release fixture, or redistribute those binaries.

Instead, `engines/qa/fixtures/ppsspp-minimal` contains Lucent-owned CC0 source
for a minimal PSP homebrew screen. No PBP is checked in. Producing one is gated
on a deterministic, source-built, fully noticed PSPDEV/PSPSDK toolchain. This
keeps the candidate fail-closed rather than asserting rights that are not
documented.

## Gates before approval

1. Physically validate the exact normalized FFmpeg-enabled core through PSP
   FMV-to-game transitions, proving non-black video callbacks and stable audio.
2. Complete final distribution review for the generated file-level notices,
   dependencies, and staged assets.
3. Build and hash the CC0 homebrew fixture using a pinned source toolchain.
4. Run EmuFusion's callback, video/audio, input, GLES, Vulkan, suspend/resume, and
   100-cycle serialize/unserialize tests with legal content.
5. Validate Quick Resume migration across PPSSPP versions and reject stale
   states safely.
6. Profile representative games on supported Android hardware.
7. Keep `shipped=false` and out of APK packaging until every gate passes.
