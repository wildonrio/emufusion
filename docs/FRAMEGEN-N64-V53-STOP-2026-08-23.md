# EmuFusion N64 frame generation — v53 coarse cost-volume STOP (2026-08-23)

## Scope

v53 tested one bounded estimator change on top of the frozen v51 128x72 path:
the first 32x18 solve pass in each direction evaluated a sparse dilated 5x5
candidate grid before the unchanged local 3x3 refinement. Candidates were
judged only by that direction's existing current-pair cost. No synthesis gate,
confidence threshold, pass count, analysis resolution, or maximum-flow limit
was relaxed.

The experiment used schema53 only so its evidence could not be interpreted as
v51 qualification evidence. Host gates passed before the physical run: 360
focused verifier/runtime/systemwide tests, the unified Java suite, and all 19
non-external extracted GLSL programs.

## Physical evidence

- Device: Thor, ADB serial `427c87b2`
- Game: F-Zero X, Mupen64Plus-Next, active one-player race
- APK SHA-256: `dd0db61f0f442c75858c4348223c18080932785cf88d2c1abcaaf519765bdcfe`
- Full log: `/private/tmp/fzerox-v53-36s.log`
- Full log SHA-256: `2df5c58cdf79269a7a49f71194f8ccb158272ed1983a1ada3b1a1f23a4c804cb`
- Screenshot: `/private/tmp/fzerox-v53-current.png`
- Screenshot SHA-256: `25098d2c21976b02412b19ce1116162dcc9335b91fd245286ca535561d5ba2d4`

The comparable stable 60/120 epoch was HEALTH seq8 through seq29:

- duration: `21.004125617 s`
- proof samples: `43`
- proof cells per direction: `55,728`
- backward final-valid: `21,842 / 55,728 = 39.194%`
- forward final-valid: `21,781 / 55,728 = 39.084%`
- backward cycle prerequisite: `25,842 / 55,728 = 46.372%`
- forward cycle prerequisite: `25,802 / 55,728 = 46.300%`
- backward photometric prerequisite: `99.137%`
- forward photometric prerequisite: `99.227%`
- backward texture prerequisite: `88.261%`
- forward texture prerequisite: `87.649%`
- combined pair-max plus warp-p95: `5,897 us` against the unchanged `7,333 us` gate
- diagnostic partition/reserved/mask errors: `0 / 0 / 0`
- atlas/tag errors: `0 / 0`

## Verdict

STOP. The broader coarse search made both the final-valid and cycle-consistent
coverage worse than v51's physical baseline (`40.24% / 40.04%` final-valid and
about `47.73% / 47.80%` cycle), while increasing GPU time from about `5.655 ms`
to `5.897 ms`. It remained well below the unchanged 50% final-valid gate.

The result rejects this sparse dilated coarse-cost-volume implementation. It
does not justify lowering confidence or content thresholds.

## Retirement

All v53 producer, parser, verifier, and test changes were removed. The device
was restored to and force-stopped on the exact known v51 qualification APK:

`unified-android/build/lucent-3.2.16-6d3f874883a9fa9ad7e1fab5edbc66a34ebd6f82ac618db47b8238ccb5473a3f.apk`

The restored host tree passes the 359 focused verifier/runtime/systemwide tests
under both system Python 3.9 and Homebrew Python. v53 must not be reused as a
release or qualification artifact.
