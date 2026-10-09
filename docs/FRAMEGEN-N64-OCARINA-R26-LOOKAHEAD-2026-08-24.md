# N64 Ocarina r26 — causal look-ahead cadence checkpoint

Date: 2026-08-24

Status: **20 -> 40 presentation cadence fixed; visual/frame-generation quality
not yet qualified.**

## Defect closed

The filtered Mupen VI-origin stream physically proved an exact 20.000 Hz
unique-image clock, but the two-endpoint renderer prime left no classified
successor behind the active interpolation pair. After the first midpoint
rotated `right -> left`, asynchronous signature classification had not yet
made `sequence + 2` available. The following uniform 40 Hz slot was skipped,
repeating once per source interval and collapsing actual output toward 20 Hz.

Generated modes now wait for three retained adjacent endpoints before starting:
the active `left/right` pair plus one exact future endpoint. This is one bounded
source-frame of causal look-ahead. Direct fallback remains able to present one
independently classified real endpoint immediately.

## Host evidence

- Deterministic causal 20 -> 40 replay: 20 measured seconds, exactly 800
  successful outputs (400 real + 400 generated), every output exactly three
  120 Hz panel callbacks apart, zero underruns.
- Frame-generation verifier/runtime/systemwide suites: 398/398 pass.
- Unified Java suite: pass.
- Native ASan/UBSan suite: pass.
- APK gates: one-app, Phase 1, Phase 2, and N64 ABI/core all pass.
- Repository-wide Python discovery has three unrelated pre-existing failures:
  frozen theme hash, Cemu patch-lock metadata, and stale external-emulator
  `<queries>` metadata. None touches this frame-generation change.

Candidate APK:

`unified-android/build/lucent-3.2.16-phase2-qualification-b5165ddcf37e383872ff1422d3f84429e5d3a609c0d2db7b95de36d3664a70bb.apk`

Mupen core SHA-256:

`4d1ddf5c2d0be9d70cc6dcd069fb598840e3aacbba1489ca005e683260c5bdf0`

## Physical evidence

Evidence directory:

`.evidence-n64-lookahead-r26/`

Ocarina's moving title/demo reached and held:

`S20.0 T40 A40.1 UNQUALIFIED Built-in`

and later:

`S20.0 T40 A39.9 UNQUALIFIED Built-in`

The top gameplay SurfaceFlinger layer retained 127 valid timestamps / 126
intervals over 3.149868666 seconds:

- measured rate: **40.001668 Hz**
- desired-present deltas: **24.983–25.016 ms**
- actual-present deltas: **24.991–25.008 ms**
- no alternating 2/4-scan pattern; every retained interval is the intended
  three-scan 40 Hz slot on the measured ~119.958 Hz panel clock.

The app's one-second windows likewise reported 39.67–40.00 successful swaps,
physical presentation near 40.00, zero physical drops, and exact canonical
source proof (`candidate=20,count=600,one=600,other=0,rmsPpm=0,maxPpm=0`).

The OLED was awake only for this monitored run and was returned to
`mWakefulness=Asleep` immediately afterward. Persistent dense/v28 settings were
preserved and the transient proof setting remains absent.

## What this does not prove

The run intentionally kept qualification proof off, so the overlay correctly
said `UNQUALIFIED`. This checkpoint proves source identity, target selection,
causal buffering, successful-swap accounting, and uniform physical 20 -> 40
cadence. It does **not** certify interpolation image quality. The next N64 step
is a current proof-enabled moving-gameplay run and, if quality still fails,
improvement of the built-in flow/occlusion backend without weakening the
existing content gates. N64 30 -> 60 and nominal 60 -> 120 remain separately
uncertified under this candidate.
