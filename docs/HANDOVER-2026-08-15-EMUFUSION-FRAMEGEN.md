# EmuFusion frame-generation handover — 2026-08-15

## Objective and completion status

The active objective is to make EmuFusion frame generation rock-solid for every
internally emulated system from PlayStation 2 / GameCube and newer, prioritizing
physical PS2 and GameCube QA. Source throughput must be measured from actual
unique endpoints. Generation is capped at 2x and must report only successfully
presented output:

- 120 Hz panel: 20/30/40/50/60 -> 40/60/80/100/120.
- 60 Hz panel: 20 -> 40; 30/40/50/60 -> 60.

This objective is **not complete**. The scheduler/evidence infrastructure and
one PS2 moving-scene run are strong, but controllable PS2 camera motion,
GameCube, the lower tiers, 60 Hz operation, and the rest of the newer-system
matrix still need physical qualification. Do not mark the goal complete from
the existing evidence.

## Safe checkpoint

Workspace:

`/Users/tyleryoung/Code/emufusion`

The worktree contains a very large set of pre-existing user/agent changes,
including many untracked source files. **Do not reset, clean, checkout, or
rewrite unrelated files.** `DisplayFrameGenerator.java` and several core frame
generation files are untracked relative to the repository baseline; use exact
hashes rather than `git diff` as the ownership boundary.

Latest built but not yet physically installed schema-39 APK:

`/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-phase2-qualification-fc87b82d3ff1d34a58700652bf67b688b0e8db66416567cd40e943304aab0189.apk`

SHA-256: `fc87b82d3ff1d34a58700652bf67b688b0e8db66416567cd40e943304aab0189`

Build command:

```sh
cd /Users/tyleryoung/Code/emufusion/unified-android
LUCENT_INCLUDE_PHASE2_PPSSPP=1 LUCENT_REUSE_PHASE2_PPSSPP=1 ./build.sh
```

Exact source/checkpoint hashes:

| File | SHA-256 |
|---|---|
| `unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java` | `ab78150d1c676192b79f73b6dcdfb7e01882f5effa8fab174e57788e5052ab77` |
| `unified-android/src/com/thorium/lucent/video/AdaptiveFrameRateController.java` | `b4282eae34dedf737a31d45e87fbd79eb38ccebe5f7b3ff4e2b5199e6c2e2abf` |
| `unified-android/src/com/thorium/lucent/video/FrameGenerationCadence.java` | `024fdf88a4dfebb7b56ecdac54976411b09d2902aa49e94f2abd30c5c442331f` |
| `unified-android/tools/verify_frame_generation_evidence.py` | `ee7b35124fd386029f6880190233aedcb8b7d25d63679e207ff1e255625d9ca8` |
| `unified-android/tools/run_runtime_acceptance_qa.py` | `801d49066332b40e1ac108bc1892fd9f6b5f1793da3defa77f62e74a926e9ac8` |
| `unified-android/tools/tests/test_frame_generation_evidence.py` | `38bb5e78eaa0fda6214d0d0c48c033afd9c6b08a139c42dbefd840fabcd16488` |
| `tools/tests/test_runtime_acceptance_qa.py` | `ea4ec438dd81fea677a0e4923f5583170fc4b54c615c0674c69c6c1f61689df8` |
| `tools/tests/test_systemwide_frame_generation.py` | `a3030e93649d443afeb3f184917e15a3b30cd2ffe8290dc760bf43acd50060af` |
| `unified-android/test/com/thorium/lucent/video/FrameGenerationCadenceTest.java` | `36f529df48c71361f3a8c70779db6a373b34949d4431317e85b5b4beed09f523` |

## What changed in the final checkpoint

### Physical presentation pacing

`DisplayFrameGenerator` now calls
`EGLExt.eglPresentationTimeANDROID(...)` immediately before every visible
`eglSwapBuffers`, targeting the next physical display tick. Stale target times
are advanced rather than submitted in the past. The helper is in
`FrameGenerationCadence.nextPresentationTimeNs`.

This is in addition to the existing rational physical-callback accumulator:
80/120 uses a balanced 2-of-3 callback selection, and 100/120 uses 5-of-6.
These are honest average output rates on a fixed 120 Hz scan, not fictional
uniform 12.5 ms or 10 ms physical intervals.

Dense cadence rejection now requires three consecutive eligible under-target
HEALTH windows. The existing 96% presented-output threshold is unchanged. Any
ineligible/source-starved window clears the consecutive failure count.

### Qualification restart lifecycle

A physical proof off/on test exposed a concrete native lifecycle bug. Dense GL
textures survived, but a newly created `DenseGpuTimer` skipped proof-atlas PBO
and fence-ring configuration because `ensureDenseResources()` returned early.
`ensureProofAtlasTimerConfigured()` now configures every fresh timer even when
textures already exist. Error paths remain fail-closed.

### Evidence schema 39

Schema 38 remains immutable. The new producer emits:

- contract `dense-fragment-128x72-v39-present-timed-vector-trajectory-qualification-x2-presented`;
- variant `fragment-128x72-v39-present-timed-vector-trajectory`;
- `proofSchemaVersion=39`;
- `presentationTimingMode=egl-android-next-vsync`;
- `cadenceRejectConsecutiveWindows=3`.

The verifier and runtime runner parse schema 39 before older grammars, require
the exact timing fields, retain every schema-38 vector/atlas/endpoint gate, and
continue parsing schemas 22 through 38 without reinterpretation. Missing or
mixed schema-39 fields reject.

## Tests at checkpoint

Passed:

- `./unified-android/test.sh` (all Java host tests).
- `python3 -m unittest unified-android/tools/tests/test_frame_generation_evidence.py tools/tests/test_runtime_acceptance_qa.py`: **257 tests**.
- Focused schema-39 verifier, runner, producer/scheduler structural tests.
- Python `py_compile` for verifier and runner.
- Full APK build above.

The full `tools/tests/test_systemwide_frame_generation.py` currently runs 54
tests with four failures. They predate and are unrelated to schema 39, and are
stale structural assertions against the evolving shared runner/source:

- `test_dual_screen_proof_is_bound_to_secondary_display`
- `test_every_primary_engine_uses_a_distinct_gameplay_surface_layer`
- `test_fixed_rate_legacy_systems_use_core_cadence_not_image_uniqueness`
- `test_starved_source_holds_real_endpoint_instead_of_extrapolating`

Do not claim a completely green repository suite until those are reconciled.

## Physical PS2 evidence already obtained

Device:

- AYN Thor serial `427c87b2`
- adb `/Users/tyleryoung/.codex/tools/android-platform-tools/adb`
- Android reports physical display modes at 60 and 120 Hz. Treat 80 and 100 as
  balanced subsets of 120 unless new device evidence proves additional modes.

The physically installed build is the preceding schema-38 artifact, not the
new schema-39 checkpoint:

`unified-android/build/lucent-3.2.16-phase2-qualification-160a35c20c8aa6e8dd877a4640872d0c3906cd915a80207a33d660b8ef522bc8.apk`

On Shadow of the Colossus through ARMSX2, the moving title/attract cinematic
produced:

- screen recording: 2398 frames / 19.978 s = 120.03 fps;
- fresh SurfaceFlinger sample: 125 consecutive intervals averaging 8.332 ms,
  range 8.330-8.334 ms, zero intervals above 12.5 ms;
- app HEALTH: 120 successful presents per about 1.000 s, exactly 60 real plus
  60 generated;
- no stable every-other duplicate parity in decoded frame differences;
- dense combined GPU pair-plus-warp about 5.2 ms, below the 7.333 ms gate.

Local recordings (temporary and not qualification manifests):

- `/tmp/shadow_pan_20s.mp4`
- `/tmp/shadow_forced_pan.mp4`

After the timer reconfiguration fix, proof off/on was retested physically:

- new epoch reported `denseProofAtlasCapability=63`;
- atlas enqueue/complete/accept progressed from 1 through at least 17;
- ring, tag, atlas, and fallback error counters remained zero;
- no `Dense pyramid rejected` or `densePerformanceRejected=1` occurred.

The scene was title/intro motion, not player-controlled camera panning. This is
strong pacing evidence but not final visual-quality acceptance.

Current device settings used:

```sh
adb -s 427c87b2 shell settings put global emufusion_framegen_proof 1
adb -s 427c87b2 shell settings put global emufusion_framegen_dense_pyramid 1
adb -s 427c87b2 shell settings put global emufusion_framegen_dense_v28_160 1
```

The source switch name still says `v28_160` for historical compatibility even
though the current analysis grid is 128x72 and the evidence contract is v39.

Useful launch notes:

- Main activity:
  `adb -s 427c87b2 shell am start --display 0 -n com.thorium.preview/org.pegasus_frontend.android.MainActivity`
- The Odin controller node used during this run was `/dev/input/event9`.
- Pegasus launch required raw `BTN_SOUTH` code 304; Android keyevent 96 did
  not launch from the frontend, although it affected in-game menus.
- Surface layer IDs are dynamic. Resolve with
  `adb -s 427c87b2 shell dumpsys SurfaceFlinger --list | rg 'SurfaceView.*MainActivity.*BLAST'`
  and quote the exact layer name when invoking `--latency`.

## Public research and defensible conclusions

Primary/public references:

- Android Frame Pacing / Swappy:
  https://developer.android.com/games/sdk/frame-pacing
- EGL Android presentation-time specification:
  https://android.googlesource.com/platform/frameworks/native/+/master/opengl/specs/EGL_ANDROID_presentation_time.txt
- Official Lossless Scaling Steam page:
  https://store.steampowered.com/app/993090/Lossless_Scaling/
- lsfg-vk public configuration and pacing documentation:
  https://github.com/PancakeTAS/lsfg-vk/blob/develop/docs/Configuration.md
- Public Android LSFG implementation overview:
  https://github.com/FrankBarretta/LSFG-Android

The relevant conclusions are:

1. Android's supported mechanism for preventing early presentation is a
   presentation timestamp (`EGL_ANDROID_presentation_time` for GLES;
   Swappy also uses platform timing extensions).
2. lsfg-vk explicitly documents presenting generated frames as fast as
   possible as flawed because the display skips frames; generation needs an
   output pacing regime tied to display refresh.
3. Lossless Scaling's public guidance favors stable base rate and fixed
   multipliers. EmuFusion deliberately remains at maximum 2x because higher
   multipliers consume more synthetic evidence and raise artifact/latency risk.
4. The Android LSFG projects use GPU frame generation, pacing controls, queue
   depth, jitter smoothing, and real-vs-total counters. The proprietary LSFG
   model/shaders are not public implementation guidance and must not be copied
   or bundled. EmuFusion's independently implemented optical-flow path and
   existing licensing boundary must remain intact.
5. Never equate a target badge or callback count with presented FPS. Continue
   joining successful swaps, SurfaceFlinger timestamps, endpoint provenance,
   asynchronous atlas proof, and content-quality gates.

### 2026-08-20 source-level LSFG/Android recheck

The public Android implementation was re-read at exact submodule commits
`LSFG-Android-Application@b84754199823615d32d65fe33ea59481dca88dcf` and
`lsfg-vk-android@b55b1820c81294b62c787384462eaef9bb6d6e7d` rather than relying
on feature-list summaries. The transferable engineering conclusions are:

- its HUD distinguishes pixel-unique captures from total successful overlay
  posts; EmuFusion's badge must likewise remain source-unique / successful
  present truth, never requested output or emulator callback frequency;
- pixel-identical capture frames are discarded before the expensive optical
  flow pipeline, while each retained frame keeps its capture timestamp;
- retained unique frames enter a bounded FIFO, and generated/real posts are
  paced into distinct display-vsync slots so SurfaceFlinger cannot collapse
  back-to-back submissions into one visible flip;
- source timing uses an EMA with ratio-based outlier rejection and resets only
  after persistent regime change. EmuFusion's longer fixed-tier decision
  window is intentionally more conservative, but it shares the critical rule
  that one timestamp spike cannot rewrite the source rate;
- Android LSFG counts a frame only after its output post succeeds and falls
  through to captured-frame passthrough on unrecoverable GPU failure. This
  directly supports EmuFusion's successful-`eglSwapBuffers` accounting and
  endpoint-only failure mode;
- the public Android port uses MediaProjection/AHardwareBuffer plus an overlay
  because it cannot inject into another app. EmuFusion is already inside the
  emulator compositor, so adopting that capture/overlay path would add its
  documented latency and permissions without improving endpoint ownership.

These are architecture references, not permission to copy the proprietary
Lossless Scaling shaders or model. EmuFusion retains its independently written
bidirectional flow, cycle/photometric confidence and evidence gates.

`docs/systemwide-frame-generation.md` is stale (for example it still describes
`50 / 120` and older qualification evidence). Do not use it as current truth
until it is rewritten against schema 39 and the final physical matrix.

## Exact next work

1. **Install and smoke schema 39.** Install the hash-suffixed checkpoint with
   `adb install -r`; verify the installed base APK hash. Confirm the first live
   dense HEALTH pair contains the exact schema-39 contract, timing mode, and
   three-window value. Repeat proof 0 -> 1 and require capability 63 plus fresh
   atlas progress with zero errors.
2. **Run controllable PS2 motion.** Use a title/save state that reaches camera
   control quickly. Pan continuously for at least 60 s. Capture synchronized
   logcat, SurfaceFlinger latency, screen recording, and screenshots. Require
   stable source tier, truthful badge, balanced physical intervals, no dense
   rejection, no FIFO coalescing/timestamp correction increase, and no visible
   doubling/ghost rectangles/tearing.
3. **Run GameCube next.** Prioritize Dolphin with Metroid Prime or Super Mario
   Galaxy 2. Repeat the same evidence. Do not accept a title screen. GameCube
   was the original source of false 60 -> 50 demotion and must hold the measured
   unique source tier through sustained camera movement.
4. **Exercise every tier.** Host tests prove the tier table, but physical
   evidence is still missing for 20/30/40/50 on 120 Hz and all mappings on 60
   Hz. On 120 Hz, verify 80 as a balanced 2/3 callback lattice and 100 as 5/6;
   do not demand impossible uniform 12.5/10 ms physical intervals. On 60 Hz,
   confirm actual presented output never exceeds 60 and the badge reports the
   committed rate, not the target.
5. **Run the current verifier/runner end-to-end.** Produce a real schema-39
   manifest with a current >=11 s tier segment, >=30 post-baseline proof
   samples, raw SurfaceFlinger overlap, and all vector/content/timer/atlas
   predicates. A clean pacing trace alone is insufficient.
6. **Expand newer-system QA.** After PS2/GameCube, qualify every internally
   routed newer system (including Wii and native-adapter systems present in the
   matrix). Preserve external-emulator boundaries and dual-display identities.
7. **Reconcile the four stale systemwide tests**, update the stale design doc,
   rerun the complete host/native/shader suites, and obtain an independent
   read-only audit before freezing a release candidate.

## Non-negotiable invariants

- Maximum 2x generated output; no extrapolation past retained endpoints.
- Count/report only after successful `eglSwapBuffers`.
- Unique source timestamps/ordinals own source-tier measurement; presentation
  misses must never rewrite a proven source rate.
- Every synthetic sample is bound to exact adjacent retained endpoints and a
  monotonic source target.
- SurfaceFlinger timestamps, not the FPS badge, are presentation authority.
- Any timer, GL, atlas, tag, context, discontinuity, or proof error fails
  closed to safe direct presentation.
- NES authoritative cadence and dual-screen routing must remain isolated.
- Do not weaken the 50% dense validity/content gates merely to pass a scene.
