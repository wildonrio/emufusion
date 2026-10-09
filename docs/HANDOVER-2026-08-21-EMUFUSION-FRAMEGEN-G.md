# EmuFusion frame generation — HANDOVER G (2026-08-21, schema-41 stopping point)

Read this before changing, building, installing, or running physical QA. This
document supersedes handover F for the active investigation. Handover E remains
useful for older system history, but any claim that conflicts with this file or
with current physical artifacts is stale.

## Goal and product rules

The goal is genuinely smooth, physically verified frame generation for N64 and
every internally emulated system from GameCube/PS2-era onward on the AYN Thor.
The top screen is the product priority. DS/3DS lower-screen generation is
best-effort and must not delay or compromise the top-screen result.

Hard rules:

- Lock the highest real source rate the game can sustainably deliver. Never
  demote a proven source merely to make panel arithmetic convenient.
- Generate no more than 2x the source rate.
- Report only successful, physically presented output, never an aspirational
  target.
- A numeric verifier pass is not sufficient. Moving-gameplay screenshots and
  SurfaceFlinger cadence must also be credible.
- Do not loosen content, cadence, flow-consistency, or evidence gates to make a
  run pass.
- A visually doubled/ghosted scene is a product failure even if all current
  counters pass.

The Thor top panel exposes 60 Hz and 120 Hz modes to Android. Treat those device
facts as authoritative. Reported 40/80/100 modes have not been exposed by
`dumpsys display` on this unit.

## Clean stopping point

The working tree now contains an incompatible **schema 41** frame-generation
candidate. Its host tests pass and the exact APK is installed and preserved.
Physical N64 qualification cannot proceed because launching F-Zero X now
reproducibly crashes the Mupen64Plus Next hardware renderer during a duplicate
surface/context recreation. The crash happened twice with the same native
stack. This is the next blocker; do not treat it as a flaky QA failure.

The app was force-stopped before handoff. No game or automated input is still
running on the device.

This is not a completed goal and it is not safe to claim schema 41 qualified.

## Device and immutable candidate

- Device: AYN Thor
- Serial: `427c87b2`
- adb: `/Users/tyleryoung/.codex/tools/android-platform-tools/adb`
- Package: `com.thorium.preview`
- Installed APK:
  `unified-android/build/lucent-3.2.16-phase2-qualification-6ca7e2538789944144d64e1e070368d08f9e8b2b3ae88ae70a9b8f0ca093a34d.apk`
- APK SHA-256:
  `6ca7e2538789944144d64e1e070368d08f9e8b2b3ae88ae70a9b8f0ca093a34d`

Required device settings were verified and must remain enabled:

```text
emufusion_framegen_dense_pyramid=1
emufusion_framegen_dense_v28_160=1
```

Also verify after any install:

```sh
ADB=/Users/tyleryoung/.codex/tools/android-platform-tools/adb
$ADB -s 427c87b2 shell appops set com.thorium.preview SYSTEM_ALERT_WINDOW allow
```

Do not delete the dense settings. Doing so silently routes qualification back
to the old default path and invalidates the run.

## Android device control through ADB

Use the exact serial on every command. Do not rely on whichever device happens
to be first in `adb devices`.

```sh
ADB=/Users/tyleryoung/.codex/tools/android-platform-tools/adb
SERIAL=427c87b2
$ADB devices -l
$ADB -s "$SERIAL" get-state
```

Safe app lifecycle commands:

```sh
# Stop the app and every active emulation/input worker.
$ADB -s "$SERIAL" shell am force-stop com.thorium.preview

# Launch the library on the top display.
$ADB -s "$SERIAL" shell am start --display 0 -f 0x18000000 \
  -n com.thorium.preview/org.pegasus_frontend.android.MainActivity

# Confirm which task/window is actually foreground.
$ADB -s "$SERIAL" shell dumpsys activity activities
$ADB -s "$SERIAL" shell dumpsys window windows
```

Observe before and after any consequential input:

```sh
# Top-display screenshot.
$ADB -s "$SERIAL" exec-out screencap -p > /private/tmp/thor-top.png

# UI hierarchy (menus only; games usually expose few or no nodes).
$ADB -s "$SERIAL" shell uiautomator dump /sdcard/thor-ui.xml
$ADB -s "$SERIAL" pull /sdcard/thor-ui.xml /private/tmp/thor-ui.xml

# Logs. Clear only immediately before a bounded reproduction.
$ADB -s "$SERIAL" logcat -c
$ADB -s "$SERIAL" logcat -v threadtime > /private/tmp/thor-live-logcat.txt
```

The installed Android-control helper can provide a screenshot plus UI dump in
one timestamped observation:

```sh
CTL=/Users/tyleryoung/.codex/skills/android-device-control/scripts/androidctl
ANDROID_SERIAL=427c87b2 "$CTL" doctor
ANDROID_SERIAL=427c87b2 "$CTL" observe
```

For ordinary frontend navigation, Android key injection works:

```sh
$ADB -s "$SERIAL" shell input -d 0 keyevent DPAD_DOWN
$ADB -s "$SERIAL" shell input -d 0 keyevent DPAD_UP
$ADB -s "$SERIAL" shell input -d 0 keyevent ENTER
$ADB -s "$SERIAL" shell input -d 0 keyevent BACK
```

`adb shell input` is not reliable once a native game owns controller input. The
runtime runner discovers the Thor controller and injects complete kernel events
with `sendevent`; prefer that implementation rather than duplicating its logic.
The controller has commonly appeared as `/dev/input/event9`, but node numbers
can change after a reboot or reconnect. Rediscover it first:

```sh
$ADB -s "$SERIAL" shell getevent -pl
```

On the presently observed mapping, `BTN_SOUTH`/code 304 is the physical A
button. A complete manual tap must include synchronization and release events:

```sh
NODE=/dev/input/event9  # Verify with getevent; never assume blindly.
$ADB -s "$SERIAL" shell "sendevent $NODE 1 304 1; sendevent $NODE 0 0 0; \
  sleep 0.12; sendevent $NODE 1 304 0; sendevent $NODE 0 0 0"
```

For sticks, triggers, long holds, title choreography, and automatic cleanup,
use `run_runtime_acceptance_qa.py`. Its controller helper reads the device's
actual axis ranges, sends a coherent batch, and releases every held button in
`finally`. Handwritten stick values can leave a persistent nonzero kernel axis
state and corrupt later runs.

SurfaceFlinger inspection:

```sh
$ADB -s "$SERIAL" shell dumpsys SurfaceFlinger --list
```

When requesting latency, quote the entire layer name inside the device shell,
especially names containing `(BLAST)`:

```sh
$ADB -s "$SERIAL" shell \
  "dumpsys SurfaceFlinger --latency 'SurfaceView[...](BLAST)'"
```

An unquoted `(BLAST)` produces a device-shell syntax error that can be mistaken
for empty latency evidence. Always verify the selected layer is the actual
moving gameplay surface, not an overlay, retained surface, menu, or lower-panel
surface.

After manual control or an interrupted runner, always stop the package and
release any manually held kernel input before leaving the device unattended.

## What changed in schema 41

### 1. Strict temporal-flow proposal admission

Physical schema-40 F-Zero evidence exposed severe doubled car and track imagery.
The dense solver accepted a stale temporal proposal whenever its current-pair
cost was merely close to the baseline:

```glsl
tc <= bc + .008
```

That allowed prior-pair motion to survive into a stopped or substantially
different current pair. Schema 41 changes the temporal proposal into a strict
current-pair improvement:

```glsl
tf.b >= 48.0 / 255.0 && tc + .002 < bc
```

The temporal field is only a proposal; the current image pair must prove that
it is better. Temporal guide readiness is also invalidated on FIFO reset and
re-prime. Structural regressions reject the former tie allowance.

### 2. F-Zero QA now requires sustained racing

The prior runner could select a static `RETIRE` screen and report a numeric
60→120 pass even though the actual moving race was visibly broken. The N64
F-Zero flow now:

- holds A continuously for the entire motion thread;
- uses gentle alternating lateral steering rather than destructive full-axis
  sweeps;
- releases A in `finally`;
- verifies the one-player race HUD after the steady-proof wait;
- verifies the final visible screenshot is still an active race scene.

A retirement/menu/static scene can no longer satisfy the F-Zero flow.

### 3. Evidence identity bumped

Schema 40 remains parseable as historical evidence but cannot qualify the new
candidate. Current identity:

```text
proofSchemaVersion=41
proofContract=dense-fragment-128x72-v41-strict-temporal-flow-guidance-present-timed-vector-trajectory-qualification-x2-presented
denseVariant=fragment-128x72-v41-strict-temporal-flow-guidance-present-timed-vector-trajectory
```

The producer, verifier, runtime runner, direct tests, and systemwide tests were
migrated atomically. Mixed schema-40/schema-41 records reject.

## Host verification at freeze

These passed after the final schema-41 bytes:

```sh
cd /Users/tyleryoung/Code/pegasus-lucent
python3 -m unittest \
  tools.tests.test_runtime_acceptance_qa \
  tools.tests.test_systemwide_frame_generation \
  unified-android.tools.tests.test_frame_generation_evidence
# 347 tests PASS

cd unified-android
sh test.sh
# all Java host components PASS
```

`py_compile` and `git diff --check` also passed.

Exact source/test hashes:

| File | SHA-256 |
|---|---|
| `unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java` | `48fa5ef22e7ec286154c7b7aba3162f9d750beb395b58b6c423b233c4c006da1` |
| `unified-android/src/com/thorium/lucent/video/AdaptiveFrameRateController.java` | `b2d7577dc766a05d58c7700aa2a4e40a10b65db1f1ed4ce3a4eee599f14200d6` |
| `unified-android/tools/verify_frame_generation_evidence.py` | `f8d0d876a93b247c005a1dd9cc7089cc3574aa98b004ee316d02cdb6fe97218c` |
| `unified-android/tools/run_runtime_acceptance_qa.py` | `ab252dcbcbc63fa15c271b54e4bde340a8dbb190946a5e99df890834b8bc65b7` |
| `unified-android/tools/tests/test_frame_generation_evidence.py` | `2ff57835d7c0e975b312500589c1dc097381bee5685e0622440adb2574ea2b0a` |
| `tools/tests/test_runtime_acceptance_qa.py` | `12eea3f05587e545c0aa53ab7c2d2c1391e1dc870f7d4702a553de9c75fb90a4` |
| `tools/tests/test_systemwide_frame_generation.py` | `b75b1ad882bb7ca68cc19d147259b56e982fee51ff8e6c97416f51f0e801fc7d` |

The controller was not changed in this final schema-41 step.

## Physical evidence immediately before schema 41

Artifact directory:

```text
/private/tmp/n64-fzero-60x2-r22-v40
```

Current-build schema-40 conclusions:

- Ocarina of Time: honest and visually clean 20→40 evidence.
- The World Is Not Enough: honest and visually clean 30→60 evidence.
- F-Zero X: numeric runner pass must be rejected.

The F-Zero failure is visible in:

```text
/private/tmp/n64-fzero-60x2-r22-v40/n64-title-03-ps2-gameplay-probe-a.png
/private/tmp/n64-fzero-60x2-r22-v40/n64-title-03-ps2-gameplay-probe-b.png
```

Those moving-race probes show severe doubled car/track artifacts and the car at
0 km/h. The runner instead selected this static/retirement scene:

```text
/private/tmp/n64-fzero-60x2-r22-v40/n64-title-03-framegen-visible-primary.png
```

Therefore the schema-40 F-Zero 60→120 result is a false product pass, even
though `results.json` says PASS. Schema 41 was created specifically to exclude
that evidence and force an active-race verdict.

## Current physical blocker: deterministic Mupen crash

Two schema-41 attempts fail before gameplay:

```text
/private/tmp/n64-fzero-r23-v41
/private/tmp/n64-fzero-r24-v41
```

Preserve these logs before cleaning `/private/tmp`:

```text
/private/tmp/n64-fzero-r23-v41/n64-failure-logcat.txt
/private/tmp/n64-fzero-r24-v41/n64-failure-logcat.txt
```

The runner's foreground-app failure is secondary: the app crashes, then the
launcher becomes foreground. The real defect is:

```text
Fatal signal 11 (SIGSEGV), null pointer dereference
thread: lucent-experime
liblucent_core_mupen64plus_next.so
graphics::Context::deleteFramebuffer(graphics::ObjectHandle)+8
TexrectDrawer::destroy
GraphicsDrawer::_destroyData
DisplayWindow::destroyGfxContext
context_reset
lucent_retro_hw_context_reset
lucent_android_gles_attach
nativeRecreateSurfaceGles
```

The log chronology is important:

1. Mupen requests hardware rendering.
2. Initial `lucent_android_gles_attach` calls `context_reset()` successfully.
3. The backend reports hardware context reset complete and the engine becomes
   ready.
4. A second `context_reset()` arrives shortly afterward through
   `nativeRecreateSurfaceGles`.
5. Mupen destroys already-invalid graphics state and crashes in
   `deleteFramebuffer`.

Likely source path to inspect:

- `unified-android/native/lucent_android_gles_backend.c`
  - `lucent_android_gles_attach` near line 632
  - `lucent_retro_hw_context_reset` call near line 722
- `unified-android/native/lucent_libretro_jni.c`
  - `attach_java_surface(..., recreate=true)` detaches then attaches
- `ExperimentalGlesRenderLoop.attachSurface(surface)` near line 283
  - currently uses `host.recreate(surface)` whenever `surfaceAttached` is true
- `LibretroEngineSession.attachSurface`
  - stores surface/size; continue tracing `startRenderThread()` and the exact
    surface identity/generation passed to the render loop

The leading hypothesis is that a duplicate attach notification for the same
live Android `Surface` is being treated as a genuine replacement. Confirm that
with identity/generation evidence before changing behavior.

Do not suppress all recreates. A real surface replacement/context loss still
requires an ordered `context_destroy` → EGL teardown → `context_reset` path.

## Next safe implementation steps

1. Add deterministic lifecycle instrumentation or a host seam that records the
   Android `Surface` identity/generation and every attach/recreate/detach.
2. Prove whether r23/r24's second reset is the same live surface or a distinct
   replacement.
3. If it is the same live surface, make duplicate same-generation attach a
   no-op for GL ownership while still accepting dimension updates.
4. Preserve real replacement behavior and ordered context destruction.
5. Add tests for:
   - duplicate same-surface attach: no recreate/context reset;
   - distinct replacement: exactly one destroy/recreate sequence;
   - real context loss: recreate still occurs;
   - duplicate callback after engine-ready: no Mupen double-reset;
   - resize without surface replacement: no destructive recreate.
6. Re-run all native/Java lifecycle tests and the schema-41 host suites.
7. Rebuild and run only F-Zero first. Require active racing, sustained throttle,
   credible motion, no doubled vehicle/track, and honest 60→120 presentation.
8. If F-Zero passes, rerun the complete N64 set (Ocarina 20→40, TWINE 30→60,
   F-Zero 60→120) from the same immutable APK.
9. Only then regress the older system passes in priority order. Top screen
   remains first; DS/3DS lower-panel work is optional.

Suggested lifecycle test files:

```text
unified-android/native/tests/java/com/thorium/preview/ExperimentalGlesRenderLoopTest.java
unified-android/native/tests/java/com/thorium/preview/ExperimentalGlesLibretroHostLifecycleTest.java
unified-android/native/tests/android_gles_backend_test.c
unified-android/native/tests/hw_host_test.c
```

## Build and install

The exact current APK was built from `unified-android/` with:

```sh
cd /Users/tyleryoung/Code/pegasus-lucent/unified-android
LUCENT_INCLUDE_EXPERIMENTAL_CORES=1 \
LUCENT_AUTOSELECT_EXPERIMENTAL_CORES=1 \
LUCENT_REUSE_QUALIFICATION_CORES=1 \
LUCENT_INCLUDE_PHASE2_PPSSPP=1 \
LUCENT_REUSE_PHASE2_PPSSPP=1 \
./build.sh
```

The `PT_LOAD ... 0x1000` warnings are known/allowlisted and were not this
failure.

Install or verify the preserved candidate:

```sh
cd /Users/tyleryoung/Code/pegasus-lucent
ADB=/Users/tyleryoung/.codex/tools/android-platform-tools/adb
APK=unified-android/build/lucent-3.2.16-phase2-qualification-6ca7e2538789944144d64e1e070368d08f9e8b2b3ae88ae70a9b8f0ca093a34d.apk
shasum -a 256 "$APK"
$ADB -s 427c87b2 install -r "$APK"
$ADB -s 427c87b2 shell settings put global emufusion_framegen_dense_pyramid 1
$ADB -s 427c87b2 shell settings put global emufusion_framegen_dense_v28_160 1
$ADB -s 427c87b2 shell appops set com.thorium.preview SYSTEM_ALERT_WINDOW allow
```

The temporary F-Zero-only matrix used for r23/r24 is:

```text
/private/tmp/fzero-v41-matrix.json
```

It contains one N64 system, pins F-Zero X, and requires source tier 60. It is a
temporary diagnostic input, not a product manifest; recreate it if `/private/tmp`
has been cleared.

The general physical runner pattern remains:

```sh
cd /Users/tyleryoung/Code/pegasus-lucent
ADB=/Users/tyleryoung/.codex/tools/android-platform-tools/adb
APK=unified-android/build/lucent-3.2.16-phase2-qualification-6ca7e2538789944144d64e1e070368d08f9e8b2b3ae88ae70a9b8f0ca093a34d.apk

python3 unified-android/tools/run_runtime_acceptance_qa.py \
  --serial 427c87b2 \
  --apk "$APK" \
  --expected-sha256 6ca7e2538789944144d64e1e070368d08f9e8b2b3ae88ae70a9b8f0ca093a34d \
  --output /private/tmp/n64-fzero-next-v41 \
  --system n64 \
  --titles-per-system 1 \
  --allow-physical-thor \
  --already-installed \
  --adb "$ADB"
```

Use `--help` to confirm any matrix override flag before rerunning the temporary
single-title flow. Do not guess a flag and accidentally run a different title.

## Honest system scoreboard

The schema numbers below matter. Older passes are useful regression targets,
not proof that the current schema-41 APK is good.

| System | Best honest state | Current action |
|---|---|---|
| N64 | Schema-40 Ocarina 20→40 and TWINE 30→60 are clean. F-Zero numeric 60→120 is visually false. | Fix launch crash, then qualify all three under schema 41. |
| GameCube | Historical schema-39 Metroid Prime 60→120 pass. | Regress after N64 closes. |
| PS2 | Historical schema-39 God of War 60→120 pass. | Regress after N64 closes. |
| PSP | Historical schema-39 Ghost of Sparta 60→120 pass. | Regress after N64 closes. |
| Wii | Historical schema-39 both Galaxy titles at 50→100. | Regress; fixed-120 cadence remains visually important. |
| Switch | Historical schema-39 Dread 20→40 pass. | Regress after higher priorities. |
| Dreamcast | Crazy Taxi 30→60 passed once, but not with same-run relaunch smoke. | Partial; needs a complete immutable run. |
| Wii U | SM3DW evidence is partial across older runs. | Not complete. |
| DS | No honest full pass; a prior false pass was removed. | Top screen first; lower-panel generation is low priority. |
| 3DS | No complete pass. | Top screen first; lower-panel generation is low priority. |
| PS3 | No pass; ICO shows roughly 20-Hz lock with about 15-Hz delivery bursts. | Engine pacing work remains. |

NES uses an authoritative fixed-source path and must remain isolated from the
adaptive/dense policy. Do not regress its controller routing while fixing N64.

## Public research already incorporated

Useful primary/public references:

- NVIDIA Optical Flow temporal hints and confidence semantics:
  <https://github.com/NVIDIA/NVIDIAOpticalFlowSDK/blob/master/nvOpticalFlowCommon.h>
- NVIDIA Optical Flow SDK introduction:
  <https://developer.nvidia.com/blog/an-introduction-to-the-nvidia-optical-flow-sdk/>
- Optical Flow SDK 3.0 changes:
  <https://developer.nvidia.com/blog/whats-new-in-optical-flow-sdk-3-0/>
- LSFG Android implementation:
  <https://github.com/FrankBarretta/LSFG-Android>
- OCAI optical-flow consistency paper:
  <https://openaccess.thecvf.com/content/CVPR2024/papers/Jeong_OCAI_Improving_Optical_Flow_Estimation_by_Occlusion_and_Consistency_Aware_CVPR_2024_paper.pdf>

The relevant conclusions are already reflected in schema 41:

- temporal hints are proposals and must be validated against the current pair;
- forward/backward consistency and confidence are useful rejection signals, not
  guarantees of artifact-free output;
- an external MediaProjection/overlay interpolator such as LSFG is not a
  substitute for honest in-process endpoint identity and presentation timing.

## Worktree and safety notes

- The working tree is intentionally dirty: `git status --short` reported 324
  entries at handoff.
- All changes are uncommitted and user-owned. Do not reset, checkout, clean,
  stash, or broadly reformat the tree.
- Use `rg`/`rg --files` to locate current paths; several files are untracked and
  do not exist in the repository's old baseline.
- Hashes, physical artifacts, and current source behavior are more reliable
  ownership guards than `git diff` alone.
- Do not edit shared verifier/runner contracts without updating their direct,
  runtime, and systemwide tests atomically.
- Do not install a new APK until its exact hash and host gates are recorded.
- After every physical run, manually inspect moving-gameplay screenshots. A
  static screen, attract mode, retirement screen, or menu is not proof.
- Keep the top display as the acceptance authority. Lower-screen work can be
  skipped if it materially expands scope.

## Immediate one-sentence brief for the next AI

Preserve the host-green schema-41 candidate, prove and fix the duplicate Android
surface recreation that double-resets Mupen and crashes F-Zero before gameplay,
then physically qualify a sustained active F-Zero race without temporal
ghosting before regressing the rest of N64 and the older system scoreboard.
