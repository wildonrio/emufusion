# EmuFusion N64 schema61 parallel global seed — physical STOP

Date: 2026-08-23  
Device: AYN Thor (`427c87b2`)  
Candidate APK SHA-256: `6faa2b9b2f8dd98e56ef9c057d93fd4b889d3215ce3cddff68a6d60ef2251e0c`  
Known-safe APK restored after the run: `6d3f874883a9fa9ad7e1fab5edbc66a34ebd6f82ac618db47b8238ccb5473a3f`

## Verdict

**STOP.** Schema61 fixed schema60's serial-shader performance failure, but it
did not fix dense-flow quality. It remained below the unchanged 50% final-valid
coverage gate in both directions and produced no motion-eligible proof sample.

## Candidate

- Contract: `dense-v61-parallel-global-seed-rational-max2x-presented`
- Variant: `fragment-v61-parallel-global-seed`
- Analysis: 128×72
- Existing solver: 119,808 solve texels
- Parallel seed work per direction:
  - 9×9 coarse candidate-cost tile
  - one-pixel coarse reduction
  - 5×5 fine candidate-cost tile
  - one-pixel final reduction
- Total: 48 passes and 144,216 output texels per promotion
- Each candidate independently used the same 12×8 robust source-backed
  luminance/chroma sample grid.
- The selected seed remained a proposal only. It had to beat the unchanged
  dense-cell objective; all independent local, reciprocal, cycle,
  photometric, texture, spatial, scene-cut, cadence, and maximum-2× gates
  remained unchanged.

## Performance result

The parallel architecture closed schema60's deadline failure:

- global-seed/pyramid p95: **421 µs** (max 426 µs)
- forward p95: **1,985 µs**
- reverse p95: **2,017 µs**
- validation p95: **1,492 µs**
- warp p95: **739 µs**
- combined pair max + warp p95: **6,803 µs**
- budget: **7,333 µs**
- performance rejection: **0**
- atlas accepted/completed: **30 / 30** over the selected segment

This proves parallel candidate evaluation is computationally viable on Thor.

## Quality result

Exact selected 30-sample segment:

- proof cells: **38,880**
- backward final-valid: **14,803 / 38,880 = 38.074%**
- forward final-valid: **15,425 / 38,880 = 39.673%**
- required final-valid coverage: **50% in each direction**
- motion-eligible proof samples: **0 / 30**
- correlated motion samples: **0 / 30**
- motion-eligible/synthesized pixels: **81 / 81**
- eligible output pixels: **4,262**
- substantive output pixels: **315 / 4,262 = 7.391%**

The initializer therefore did not solve moving-pixel ownership. Aggregate
performance success cannot override the content failure.

## Harness closure kept separate

The physical runner created a valid current-tier 30-sample manifest and
captured SurfaceFlinger latency, but the formal verifier rejected the artifact
because it did not observe the proof-enable marker exactly once. That harness
marker defect is independent of the hard content failure above; fixing it
would not make schema61 qualify.

Preserved artifacts:

- runner directory: `/private/tmp/twine-v61-parallel-global-r1`
- frame-generation log SHA-256:
  `0dd71b260efa9e40e5815d4fa360600f98626d7c1b2d292650580a012257dca6`
- selected manifest SHA-256:
  `43d0cfd7107a188e4b1ec651c0aae60c488200261da9b35601a1f6fcaf48e095`
- visible-frame screenshot SHA-256:
  `11e599bb112ddeee54ec31355bf9fa1ae31c3ea671e167a138f171cb8e6ac840`
- partial runner result SHA-256:
  `8d6e4646b64d0c08b049e169460e4a406681051d8a8e00d4ed746c8f16d18a3f`

## Consequence

Do not ship schema61 and do not relax validity or visual thresholds. A single
global translation seed is insufficient for this first-person camera scene.
The next built-in experiment should change the data term or estimator model,
not merely expand search reach: schema59 already had about 50% aggregate valid
coverage but poor changed-pixel ownership, while schema61's global proposal
reduced final-valid coverage to roughly 39%.

The device was restored to the known-safe APK, all proof/dense global settings
were removed, and `com.thorium.preview` was force-stopped.
