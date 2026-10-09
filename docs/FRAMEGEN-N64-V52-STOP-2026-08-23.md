# N64 built-in frame generation v52 physical STOP — 2026-08-23

## Purpose

v52 tested one additional alternating full-resolution reciprocal-refinement
sweep on top of v51. Every directional proposal still had to improve its own
image cost by the existing strict `0.006` margin. Synthesis and all acceptance
thresholds were unchanged.

The arm was deliberately incompatible while tested:

- schema: `52`
- passes per promotion: `42`
- solve texels per promotion: `138240`
- total texels per promotion: `162432`
- qualification APK SHA-256:
  `35ac234ce89e9c7162e46d9324ad1d47ae8e18b9cb6800dfa4e246adb3661e29`

## Physical result

Device: AYN Thor `427c87b2`, top panel, F-Zero X one-player moving race,
Mupen64Plus-Next, built-in backend, `60 -> 120` target.

Epoch 17, HEALTH sequence 8 through 29:

- proof delta: `42` samples / `54432` cells per direction
- backward final valid: `21569 / 54432 = 39.626%`
- forward final valid: `21586 / 54432 = 39.657%`
- backward cycle prerequisite: `25642 / 54432 = 47.108%`
- forward cycle prerequisite: `25579 / 54432 = 46.993%`
- photometric prerequisite: `99.20% / 99.16%`
- texture prerequisite: `89.29% / 89.06%`
- combined max-pair plus warp-p95: `6915 us`
- hard budget: `7333 us` (`418 us` remaining)
- timer, atlas, partition, reserved-bit, and tag errors: zero

The overlay correctly remained `S60.0 T120 A-- UNQUALIFIED Built-in`.

## Decision

STOP. v52 was slightly worse than v51's comparable physical one-player result
(about `40.1%` final valid and `47.8%` cycle prerequisite), while using most of
the remaining GPU budget. A third reciprocal sweep is not justified.

The v52 implementation and schema were retired after the run. Source and Thor
were restored to v51. Do not treat the v52 APK as a release or qualification
candidate.

## Immutable local evidence

- log: `/private/tmp/fzerox-v52-24s.log`
  - SHA-256: `c504373a28ad07d8740eabd47a77cce34e5c5a01a2d16428fd0944fd7b0421c0`
- one-player screenshot: `/private/tmp/fzerox-v52-12s.png`
  - SHA-256: `51b49251d9e15d521f6075178f43f4f41191fcb9822fadebf171f41c2c5e2254`

## Restored v51 checkpoint

- `DisplayFrameGenerator.java` SHA-256:
  `6f5f90b93b8748935f340ad1515f714a8b1c50ab394c337cf28bd8540813ad45`
- verifier SHA-256:
  `d7ae6adcf13b71bd217672dd73aeb3666fbe8743d439d353cc1dd66987b85d52`
- runtime collector SHA-256:
  `510bb24cf1995f04c200ff03e8e529ad492e89d52132d7a625c08d128bc5f7cc`
- focused verifier/runtime/systemwide tests: `359 / 359` PASS
- full unified Android host Java suite: PASS
- extracted non-external GLSL programs: `19 / 19` PASS

The verifier checkpoint includes the narrow acquisition-parser correction:
an honest rational-clock record with `uniformOutputQualified=0`, zero panel
scans, and direct source-equals-target output is parseable but cannot qualify.
Qualified evidence still requires `uniformOutputQualified=1` and a positive
integer scan divisor.
