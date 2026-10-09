# EmuFusion N64 frame generation — v57/v58 STOP (2026-08-23)

Read this before changing, building, installing, or running physical QA. This
checkpoint records a rejected optical-flow experiment and the modified product
goal. It is not a qualification pass.

## Modified goal is authoritative

The full objective is stored at:

`/Users/tyleryoung/.codex/attachments/f5a7eed9-2b48-4222-8ae9-ab08dcd621aa/goal-objective.md`

The important architectural rules are:

- Prioritize the top screen. Lower DS/3DS-screen generation is optional and
  must not delay the top-screen work.
- Measure genuinely unique source endpoints and preserve their immutable
  timestamps. Do not infer source FPS from callbacks or submissions.
- Support arbitrary stable source clocks, including rational clocks such as
  23.976, 29.97, and 59.94 when timestamps prove them.
- For source `S`, measured panel refresh `P`, and output `D`, select the highest
  defensible uniform target satisfying `S <= D <= min(2S, P)` and integer
  `P / D`.
- Never demote a proven source cadence merely to simplify scheduling.
- Every generated presentation uses the exact timestamp phase between two
  adjacent retained endpoints. Never extrapolate, catch up, interpolate across
  a discontinuity, or count a duplicate/submission as a delivered frame.
- Report sustained source `S`, selected uniform target `T`, actual successful
  physical presentation rate `A`, and active backend separately.
- Keep one user-facing setting: `Frame Generation: Off / On`. Backend choice is
  automatic: validated lawful LSFG when available, otherwise built-in, then
  direct fail-safe.
- N64 top-screen 20, 30, and 60 fps paths are the first certification target.
  Numeric verification alone is never sufficient; moving gameplay and
  SurfaceFlinger interval evidence must agree.

These rules supersede older tens-tier and aspirational `50/100` behavior.

## Device left in a safe state

- Device: AYN Thor, serial `427c87b2`
- Package: `com.thorium.preview`
- adb:
  `/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk/platform-tools/adb`
- Installed known v51 APK:
  `/Users/tyleryoung/Code/pegasus-lucent/unified-android/build/lucent-3.2.16-6d3f874883a9fa9ad7e1fab5edbc66a34ebd6f82ac618db47b8238ccb5473a3f.apk`
- APK SHA-256:
  `6d3f874883a9fa9ad7e1fab5edbc66a34ebd6f82ac618db47b8238ccb5473a3f`
- The proof setting was deleted and the app was force-stopped after restoring
  this APK. No game or automated input should be running.

Always target the serial explicitly. Minimal safe commands:

```sh
ADB=/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk/platform-tools/adb
SERIAL=427c87b2
$ADB -s "$SERIAL" get-state
$ADB -s "$SERIAL" shell am force-stop com.thorium.preview
```

## Current source is experimental, not the installed baseline

The working tree is dirty and contains user work plus a rejected v58 source
experiment. Preserve unrelated changes. Do not assume the installed APK was
built from current source.

Current relevant source hashes at this checkpoint:

| File | SHA-256 |
|---|---|
| `DisplayFrameGenerator.java` | `e91dd1ad25ff1b19b4c6ca3373f2a400e2f62edc2d7a290bca1a14c63c698af3` |
| `AdaptiveFrameRateController.java` | `5869db15520100c535ee86ce9df33e65b481c158f7e20f4247e8a8cc4ec9c04a` |
| `verify_frame_generation_evidence.py` | `91b4ef809946ad2685020a666cd263d18452985a43816a46cbf488c3771ce8a7` |
| `run_runtime_acceptance_qa.py` | `4f98df27db45280b5f88c9b5bc53278919364727c2f9d287380eb434b1a5a18d` |

Current `DisplayFrameGenerator` identifies the dense qualification arm as
schema 58 / `dense-v58-joint-cycle-rational-max2x-presented`, uses two reciprocal
refinement passes, and sets the refinement cycle-objective weight to `0.006`.
That code is preserved only as rejected experiment evidence. Do not install or
promote it as qualified.

## v57 physical result

v57 repaired compact split HEALTH transport and stayed below logcat's practical
line limit (observed base 3747 bytes, extension 3801 bytes). Its formal clean
F-Zero X run proved compositor cadence but failed motion evidence.

Artifacts:

- log: `/private/tmp/fzerox-v57-clean.log`
- SurfaceFlinger latency: `/private/tmp/fzerox-v57-clean-sf.txt`
- manifest:
  `/private/tmp/fzerox-v57-clean-evidence/fzerox-v57-clean-framegen-qualification-primary-display-0.json`

Key facts:

- SurfaceFlinger: about 119.9905 Hz, one scan per output, raw overlap 118.
- Pair plus warp gate: about 5984 microseconds, within the 7333-microsecond
  deadline budget.
- Dense validity was broad (about 57.5% backward and 58.3% forward).
- The verifier nevertheless failed the trajectory proof: only 128 selected
  motion-eligible pixels over 32 proof samples, zero motion-eligible samples,
  and zero correlated samples.

This is a genuine quality failure, not a parser or cadence failure.

## v58 physical result

v58 increased only the reciprocal cycle-objective weight from 0.0045 to 0.006
while retaining the same 40 passes, workload, and acceptance gates.

Artifact:

- log: `/private/tmp/fzerox-v58-30.log`

Stable epoch result (39 proof samples):

- eligible pixels: 3304
- motion-eligible pixels: 151
- motion-eligible samples: 0
- correlated samples: 0
- dense valid: 58.67% backward, 59.91% forward
- cycle-valid: 79.17% backward, 81.85% forward
- combined pair plus warp: about 5978 microseconds

The stronger objective improved broad flat-region consistency but did not solve
edge-aligned motion ownership or trajectory evidence. This experiment family is
exhausted. Do not make another weight-only arm and do not lower proof gates.

## Correct next implementation order

1. Implement/finish the common timestamped endpoint contract and sustainable
   source-rate authority. Preserve raw immutable endpoint identity/timestamps.
2. Replace nominal/tens-tier pacing with the measured-panel uniform-divisor
   selector. Certify the N64 20->40, 30->60, and nominal 60->120 top-screen
   paths first; arbitrary stable clocks must use the same rule.
3. Implement exact rational temporal resampling with bounded endpoint buffering,
   no extrapolation, no catch-up, explicit discontinuity/re-prime handling, and
   post-physical-presentation accounting.
4. Make the overlay report `S`, `T`, `A`, and backend truthfully. A target is not
   an actual rate.
5. Re-establish physical cadence proof for each N64 path before returning to
   optical-flow quality. The v57/v58 timing evidence may be reused only as
   historical evidence, never as certification of a new scheduler.
6. For the next built-in quality arm, target motion-boundary ownership,
   occlusion/disocclusion handling, and edge-aware confidence. Public
   consistency/occlusion research is relevant; another scalar cycle-weight
   increase is not.
7. Investigate LSFG only through a documented, lawful, Android-compatible
   interface. Do not execute or embed an unknown Windows DLL. Built-in frame
   generation must remain complete without it.

## Non-negotiable stopping rules

- Do not qualify a cadence-limited fallback as smooth.
- Do not reinterpret callback/submission counts as physical presentations.
- Do not loosen the 2x, content, trajectory, deadline, or SurfaceFlinger gates.
- Do not touch lower-panel generation if it materially delays top-screen N64.
- On any physical test failure, delete proof, force-stop the package, and leave
  a known-safe APK installed before handing off.

