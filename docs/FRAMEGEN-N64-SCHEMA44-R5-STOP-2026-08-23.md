# EmuFusion N64 schema-44 r5 — physical product STOP (2026-08-23)

This checkpoint follows the current goal objective in
`/Users/tyleryoung/.codex/attachments/f5a7eed9-2b48-4222-8ae9-ab08dcd621aa/goal-objective.md`.
It is not a qualification pass. The top-panel built-in backend visibly fails
the artifact standard in representative Ocarina movement.

## Immutable device candidate

- Device: AYN Thor, serial `427c87b2`
- Installed package: `com.thorium.preview`
- APK:
  `unified-android/build/lucent-3.2.16-phase2-qualification-8710d16614e8a5b452a565e2b235b9f57f437a89bd372ebb817c1434aa8e13bc.apk`
- APK SHA-256:
  `8710d16614e8a5b452a565e2b235b9f57f437a89bd372ebb817c1434aa8e13bc`
- Producer identity: schema 44,
  `dense-fragment-128x72-v44-unique-endpoint-rational-clock-strict-flow-qualification-max2x-presented`

The package was force-stopped after capture, all injected controller axes and
buttons were explicitly released, and `emufusion_framegen_proof` was removed.

## QA-harness corrections

The physical r3/r4 attempts exposed two harness defects rather than product
passes:

1. Generic N64 proof motion rapidly centred/reversed both sticks and pressed
   an action button. Under strict unique-image ownership this produced real
   100–500 ms image gaps, which the renderer correctly rejected.
2. Readiness polling fetched and reparsed every Android log line every 100 ms,
   causing long campaigns to grow pathologically expensive.
3. Generic pixel-change readiness admitted an animated child-Link close-up
   before controllable Ocarina gameplay.

The current runner now:

- moves non-F-Zero N64 titles with a continuous, non-neutral left-stick orbit;
- releases that vector in `finally`;
- uses no C-button/right-stick or action-button input during the proof window;
- polls only `EmuFusionFrameGen` transport while waiting, retaining a complete
  final log capture;
- requires Ocarina's red-heart and action-button HUD before proof is armed;
- advances absent-HUD states only with N64 A, or START when OCR proves an
  explicit START-owned title/pause state.

Exact host-only hashes at this checkpoint:

- `unified-android/tools/run_runtime_acceptance_qa.py`:
  `2996936db7da0e8da7307b7805e38b4e5053c72f9541861f67fc49f8e530827a`
- `tools/tests/test_runtime_acceptance_qa.py`:
  `f2024b2fc7d50a545aebde7fca8dd01806ea38b6aad6402b5eb489a64ba79ac8`

Host gates: 356 combined runtime/systemwide/verifier tests pass; `py_compile`
and focused `git diff --check` pass.

## Physical r5 result

The new HUD gate reached a real Ocarina gameplay view before proof. The
continuous orbit then established one long schema-44 presentation epoch.
Later four-second HEALTH windows repeatedly reported:

- measured source around `20.00–20.05` unique images/s;
- locked source tier 20;
- uniform target 30 on the 120-Hz panel (four scans/output);
- 120 successful app swaps per four seconds;
- 480 display callbacks per four seconds;
- no FIFO coalescing in the stable epoch;
- `denseCombinedPairMaxWarpP95Us` about 5.4 ms, below 7.333 ms;
- no atlas/tag/timer/mask transport errors.

The source had not proved canonical exact 20 Hz, so the conservative divisor
plan remained 30 rather than 40. In later windows no output timestamp landed
exactly on an endpoint: all 30/s were bounded intermediate phases. That is not
alone a scheduler violation for an arbitrary source clock. Phase diagnostics
stayed approximately `0.10 < phase < 0.84`, endpoint spans stayed near 50 ms,
and there was no extrapolation.

The visible result nevertheless fails hard. The preserved top-screen frame
shows severe room-wide rippling/warping and distorted character geometry. The
confidence funnel accepted roughly 65–70% of dense cells while the motion was
visibly wrong, so transport correctness and GPU timing do not imply flow
correctness.

Preserved evidence:

- `/private/tmp/n64-schema44-r5-product-fail.png`
  SHA-256 `55beff137ab6f4c7980161f988fb00c1a7af79e036bd7d355c4db764496567c7`
- `/private/tmp/n64-schema44-r5-product-fail-logcat.txt`
  SHA-256 `420f6e8a04ff9d1c56b25e328f475f7792708f43230560fe6c3ac6b390892446`

No SurfaceFlinger qualification was accepted: the campaign was deliberately
stopped as soon as manual moving-gameplay inspection proved a product failure.

## Next safe product step

Do not loosen quality thresholds and do not relabel 30 as qualified. Before
another APK/device run, isolate why large incorrect flows pass the current
bidirectional/cycle/photometric/texture confidence funnel. The next arm should
be incompatible and diagnostic first. It should expose spatial residual and
coherence for accepted cells (especially global-camera/background regions),
then fail closed to an exact endpoint/hold when coherent motion cannot be
proved. A global-camera/affine proposal plus independently validated local
residual is a plausible bounded experiment; threshold relaxation or blind
flow filling is not.

After image correctness is fixed, repeat N64 certification separately for the
required 20, 30 and 60 source families, with raw SurfaceFlinger interval
histograms and long manual top-screen inspection. The lower panel remains out
of the critical path.
