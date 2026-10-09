# RIFE N64 F-Zero X r266b reconstruction-guard visual review

Date: 2026-08-27

Status: narrow reconstruction defect visually cleared; overall N64/F-Zero qualification remains open.

## Immutable inputs

- Qualification APK: `lucent-3.2.16-rife-framegen-qualification-f85fbbb0702e0753eaa4505b6792b339f6715914efbc21ccb24b602ed89440ae.apk`
- APK SHA-256: `f85fbbb0702e0753eaa4505b6792b339f6715914efbc21ccb24b602ed89440ae`
- Packaged `librife_benchmark.so` SHA-256: `2804b286d2dce2bf534021a866791341601b8fa729260d20c53be64a19c634b6`
- Reconstruction source SHA-256: `6efbd7e67e9c8eece1eec5dd515a6c973596d5cdcec5ab2e1761a8da7cb775db`
- Reconstruction test SHA-256: `bcc01f15e8b134d5cd0ef7a0459e19f47966a2817735de88e8870dfa6c30ff17`
- Device report SHA-256: `ae061c8695d19f13c269252f1de86d91d65af95f8991b7d13ae34d4222d7ef83`
- Recovered top-display recording SHA-256: `9fea2c28f77b9bbf1b7035c2de6a00408674ae74e6ce622a939d87b3e2ae983a`

Evidence directory: `.evidence-rife-fzero-r266b-reconstruction-guard/`

## Narrow change under review

The full-resolution high-detail reconstruction shader now compares the RIFE-warped hypothesis with a direct zero-flow hypothesis. Static detail and pixels for which zero flow is materially safer use the direct hypothesis. Contradictory/occluded pixels select one endpoint instead of averaging two incompatible images. Model execution, endpoint identity, phase, timing, target selection, qualification thresholds, and fallback policy are unchanged.

The deterministic CPU mirror covers:

1. static HUD detail under hostile flow;
2. coherent moving content retaining the RIFE warp; and
3. contradictory occlusion choosing an endpoint instead of a double-image average.

## Host evidence

- Surface-transport suite: 19 passed.
- Packaging plus systemwide suite: 93 passed.
- Extracted Vulkan reconstruction shader: `glslangValidator` passed.
- Android benchmark `testDebugUnitTest` and `assembleDebug`: passed.
- Full EmuFusion product build: passed.

## Physical timing evidence

The unchanged automated report remains an honest formal FAIL because its manual moving-game content gate was not machine-resolved:

- source: 60.000 Hz
- target: 119.945 Hz
- actual physical presentation: 119.985 Hz
- physical samples: 1,550
- endpoints/generated: 775/775
- content proofs/moving generated proofs: 775/775
- numeric content gate: pass
- timing gate: pass
- combined p95: 0.501250 ms
- combined maximum: 1.056822 ms
- deadline budget: 8.337132 ms
- unsafe pairs: 0
- automated final result: fail, blocked by `moving-game visual/content proof`

No automated result or threshold was altered.

## Manual moving-game visual review

Compared with r265, which visibly alternated clean and globally deformed frames with doubled HUD, vehicle, and track geometry, the r266b RIFE-active sequence is materially clean.

Reviewed evidence includes:

- `r266b-268-detail.png`: 23 consecutive captured frames during active 60-to-120 RIFE presentation;
- `r266b-270.5-detail.png`: banked turn with a second racer;
- `r266b-274.5-detail.png`: slope and static HUD detail;
- `r266b-278.5-detail.png`: dark bank/turn;
- `rife-active-r266b-120fps-clean.mp4`: a 12.55-second RIFE-active visual excerpt (capture averaged about 115.3 samples/s; the authoritative SurfaceFlinger measurement above is 119.985 Hz).

Across those regions, the prior alternating whole-frame bowing, doubled vehicle, doubled HUD, and doubled track geometry were not observed. Consecutive frames show progressive motion rather than the r265 clean/bad alternation.

Manual verdict for this narrow defect: **PASS**. The stationary/occlusion reconstruction guard resolves the r265 failure mode in this F-Zero X scene.

## Scope and next gate

This does not certify all N64 content, all F-Zero tracks, other source-rate tiers, or the full project goal. F-Zero remains unqualified until a long, moving-game top-screen run satisfies the complete product acceptance path with constant panel-scan spacing and the formal manual visual gate. Ocarina 20-to-40 and TWINE 30-to-60 remain separate required certifications.

## OLED safety

The physical run was bounded. Cleanup set both Thor OLED backlights to zero and verified:

- `panel0-backlight/actual_brightness = 0`
- `panel1-backlight/actual_brightness = 0`
- both display brightness controllers reported `0.0`

Ambient-display suppression and `KEYCODE_SLEEP` are not used because both have caused or risked Thor display-manager deadlocks. Brightness-zero plus application teardown is the current safe black-screen mechanism.
