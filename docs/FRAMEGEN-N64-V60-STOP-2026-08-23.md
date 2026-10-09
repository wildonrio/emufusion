# EmuFusion N64 schema60 serial global-seed experiment — physical STOP

Date: 2026-08-23  
Device: AYN Thor (`427c87b2`)  
Candidate APK SHA-256: `ba41db0dc017e854320147774d6ce89e58da4a9c2ded7f55753e125a3c0fa9b8`  
Known-safe APK restored after the run: `6d3f874883a9fa9ad7e1fab5edbc66a34ebd6f82ac618db47b8238ccb5473a3f`

## Verdict

**STOP.** The schema60 one-pixel global-translation search is computationally
invalid for the live compositor path. It failed closed after two promotions,
before producing enough generated output to evaluate image quality.

## Candidate

- Contract: `dense-v60-independent-global-seed-rational-max2x-presented`
- Variant: `fragment-v60-independent-global-seed`
- Analysis: 128×72
- Solver passes/texels unchanged: 119,808 solve texels
- Two additional one-pixel direction-specific seed passes: 42 passes and
  144,002 total output texels per promotion
- Each seed pass performed a 9×9 coarse plus 5×5 fine translation search over
  a 12×8 robust sample grid in one fragment.
- The selected seed was only a proposal for the first coarsest solve. It had
  to improve the unchanged per-cell objective by 0.002; all independent local,
  reciprocal, cycle, photometric, texture, spatial, scene-cut, cadence, and
  maximum-2× gates remained unchanged.

## Physical evidence

TWINE reached live 30 fps gameplay and schema60 allocated correctly at 128×72:

```text
passesPerPromotion=42
solveTexelsPerPromotion=119808
totalTexelsPerPromotion=144002
requestedGles=3 actualGles=3.2
```

The first completed pyramid-stage timer was **9,571 µs**. That stage contained
the global seed work and exceeded the complete generated-frame budget of
**7,333 µs** before forward solve, reverse solve, validation, or visible warp
could complete. The candidate recorded:

- dense promotions: 2
- dense passes submitted: 84
- pyramid samples: 1
- pyramid p95/max: 9,571 µs
- completed dense pairs: 0
- `densePerformanceRejected=1`

The fail-closed path returned to direct schema22 presentation. No image-quality
claim can be made from this run.

Preserved artifacts:

- partial runner directory: `/private/tmp/twine-v60-global-seed-r2`
- partial runner result SHA-256:
  `0b553220f43fb84a0556f78a474a2e4885ee0d1600229af09cbfa2dc230359e8`
- live gameplay screenshot: `/private/tmp/twine-v60-step1.png`
- screenshot SHA-256:
  `b406c2063f4a739f512889daf45b13ed4e783b2269369d3477fd912651681209`

## Consequence

Do not ship schema60 and do not relax the 7,333 µs deadline. The failure is the
serial shader architecture, not evidence against global-camera initialization
itself: one fragment performed roughly forty thousand texture fetches across
both directions. Any follow-up must evaluate translation candidates in
parallel and reduce their already-computed costs, while keeping the seed only
as a current-objective-tested proposal and preserving all existing validity
and visual gates.

The device was restored to the known-safe APK, all frame-generation proof/dense
global settings were removed, and `com.thorium.preview` was force-stopped.
