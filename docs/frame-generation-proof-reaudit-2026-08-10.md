# Frame-generation proof re-audit — 2026-08-10

Scope: source-only review of the revised generator, verifier, cadence controller,
and SurfaceView routing. No device was accessed and no production file was
edited by the auditor.

## Improvements confirmed

- Every primary engine is now routed through `GameSurfaceView`, giving gameplay
  a distinct SurfaceFlinger layer instead of putting the Dolphin/GameCube image
  in a TextureView inside the Qt/HWUI window.
- SurfaceFlinger evidence uses actual-present timestamps, rejects pending and
  non-monotonic fences, and is collected for every candidate MainActivity
  SurfaceView.
- Proof telemetry now counts materially changed pixels and pixels that differ
  from a fixed-coordinate crossfade.
- Cadence telemetry contains a bounded window. Its required arithmetic is
  correct for a 120-Hz panel: 30+90, 40+80, 50+70, and 60+60 real/generated
  frames per second. A steady-state simulation of the actual
  `AdaptiveFrameRateController` produces those exact counts.
- Motion search improved from very sparse 32/8-pixel candidates. It now uses
  16-pixel coarse, 4-pixel refine, and 1-pixel final search steps.

## Corrected during the re-audit

`sampleFrameProof()` binds the proof texture's FBO, then calls
`sampleMotionEvidence()`. That method binds the motion FBO and exits by binding
framebuffer zero. `sampleFrameProof()` does not rebind the proof FBO before
drawing phase 0, phase 1, and the candidate output.

Consequences:

1. The proof draws and readbacks target the default window framebuffer, not the
   advertised proof texture.
2. Because the viewport remains 64x36, the proof replay overwrites a 64x36
   region of the visible window three times immediately before swap.
3. The saved metric is not generated through the intended offscreen evidence
   path.

A QA regression exposed this defect. Production was then corrected by sampling
motion before binding the proof target, explicitly binding the proof FBO before
the endpoint/output draws, and restoring the window viewport afterward. The
regression now passes.

## Presentation-thread performance risk

The initial revision ran proof every ten panel presents, about twelve times per
second at 120 Hz. Each proof invokes `sampleMotionEvidence()`, which synchronously reads
the whole fine flow texture back from the GPU. At a 1440x1080 source that is
roughly 180x135 RGBA, or 97 KB, plus three 64x36 proof readbacks. Repeated
GPU-to-CPU synchronization on the Choreographer/EGL presentation thread can
itself produce missed deadlines and visible judder. The interval was increased
to 30 presents (four samples/second). This is materially safer, though a final
device trace must still establish that proof readback does not miss vsync;
GPU-side correlation or bounded asynchronous readback remains preferable.

The first reduced-rate choice, interval 30, phase-locks to exact 60→120 and
40→120 cadence. Every proof then samples the same interpolation phase, which can
leave synthetic proof counts at zero indefinitely. A QA gate now requires the
interval to be coprime to 2, 3, 4, and 12 panel-tick cycles; 29 is a suitable
nearby interval. At roughly four proof samples per second, a fresh evidence
window also needs about ten seconds to collect 20 synthetic samples at 60→120.

## Remaining false-pass routes

1. The previous 5% non-crossfade threshold accepted an image that was 95%
   fixed-coordinate crossfade and only 5% arbitrary perturbation. The QA
   verifier was hardened to require at least 50% substantive and non-crossfade
   eligible pixels and 80% correlated proof samples.

2. Even the hardened aggregate test cannot establish that a warp is *correct*.
   An incorrect flow or deliberately added noise can differ from endpoints and
   crossfade. Known-ground-truth translated-pattern GPU tests are still required
   to prove that interpolation beats nearest-frame and crossfade baselines.

3. `motionCorrelatedProofSamples` is temporal but not spatial correlation. It
   combines whole-flow active/confident totals with whole-output pixel totals;
   it does not prove that the non-crossfade pixels used the measured vectors in
   their corresponding cells.

4. `realFrameCount` and `producerHz` still count buffer submissions rather than
   content-unique game images. A core submitting duplicate buffers can overstate
   the first number in the FPS badge and the number of real images available for
   interpolation.

5. SurfaceView selection remains inferential. The harness applies the same
   unlabelled generator health log to every MainActivity SurfaceView and chooses
   the sole candidate with panel-rate actual presents. If gameplay stalls while
   Qt alone presents at panel cadence, Qt can be selected. Generator telemetry,
   gameplay surface identity, and SurfaceFlinger layer identity need a shared
   role/instance identifier.

6. Dual-screen games create primary and lower-screen frame generators in the
   same process, both logging identical unqualified `Presentation health`
   records. The latest regex match can therefore contain lower-screen proof
   counters while the latency file belongs to the primary layer.

7. The audited revision originally skipped uniform integer displacements
   congruent to 2 modulo 4 and used only three luma samples. The follow-up
   implementation now searches every integer in the coarse neighborhood and
   uses a symmetric five-sample spatial cost; this historical finding remains
   here so the gap cannot silently return.

## Minimal generator-to-layer identity contract still required

1. Create a unique `sessionId` at game launch. Give every generator an immutable
   `generatorId`, `role=primary|secondary`, and `displayId`. Include all four in
   attach, health, and detach records.
2. Include monotonic `windowStartNs` and `windowEndNs` in each health record.
   The verifier groups records by the four identifiers and requires exactly one
   primary/display-0 group; it never selects the last unqualified log line.
3. Snapshot SurfaceFlinger layers immediately before physical A and again after
   the gameplay SurfaceView reports ready. The primary gameplay layer is the
   exactly-one newly created MainActivity SurfaceView on display 0. A
   pre-existing Qt layer is excluded by construction. Ambiguity fails closed.
4. Require actual-present timestamps from that exact new layer to overlap the
   selected health window, and require its refresh target to match output FPS.
5. For dual-screen games, independently identify the new PreviewActivity layer
   on the lower physical display and join it only to the secondary generator
   group from the same session.

## QA changes in this re-audit

- Added exact pass/fail cadence cases for 30/40/50/60 source locks and
  90/80/70/60 generated gaps.
- Added duplicate-endpoint, exact-crossfade, and 95%-crossfade adversarial
  evidence cases.
- Added mismatched generator/SurfaceFlinger target and twice-panel-rate cases.
- Added a steady-state Java simulation that proves real plus generated presents
  fill all 240 panel intervals over two seconds for every source tier.
- Added source assertions that all primary engines use `GameSurfaceView` and
  that the proof FBO must be rebound after motion readback.
