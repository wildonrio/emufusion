# Frame-generation proof audit — 2026-08-10

Scope: offline source and evidence review only. No Android device was accessed.

## Bottom line

The current code does execute a GPU shader that can produce pixels different
from the two source frames, and the saved GameCube trace shows the application
layer was actually presented at about 118.34 Hz. That is stronger than an FPS
badge. It is **not**, however, proof that the displayed intermediate frames are
motion-correct, cover a meaningful portion of the image, or improve motion over
nearest-frame repetition/crossfade. The existing acceptance gate can pass a
plain crossfade or an output that changes a single pixel per synthetic frame.

The implementation and proof should therefore not be described as verified
120-fps motion-compensated frame generation yet.

## Confirmed defects in the proof gate

1. `dumpsys SurfaceFlinger --latency` was parsed using column 1. AOSP's
   `FrameTracker::dumpStats` writes `desiredPresentTime`, `actualPresentTime`,
   and `frameReadyTime`, in that order. Only column 2 proves when the frame was
   visible. An adversarial trace with 120-Hz desired timestamps and 30-Hz
   actual timestamps passed the old verifier. The verifier and regression test
   have been corrected to use actual-present timestamps and reject pending or
   non-monotonic presents. Primary source: AOSP
   [`FrameTracker.cpp`](https://android.googlesource.com/platform/frameworks/native/+/master/services/surfaceflinger/FrameTracker.cpp).

2. `syntheticDistinctFromEndpoints` compares only whole-image FNV hashes at
   64x36. Hash inequality establishes merely that at least one output byte is
   different. It does not establish how many pixels changed or by how much. A
   direct replica of `readProofHash` produced different hashes for black,
   white, 50%-gray crossfade, and black with one byte changed; both the plain
   crossfade and one-byte change satisfy the current endpoint-inequality test.

3. A fixed-pixel alpha crossfade differs from both endpoints at intermediate
   phases, so it passes the distinct-hash gate. The current verifier has no
   measurement that distinguishes motion-compensated output from crossfade.

4. The active/confident motion-vector totals are sampled from the latest motion
   texture once per health interval. They are not correlated with any sampled
   synthetic frame, and they do not prove that the vectors materially affected
   its pixels.

5. The pixel proof is rendered again into a separate 64x36 offscreen FBO after
   the display draw. SurfaceFlinger timestamps prove the app layer presented
   buffers, but there is no content identity tying those latches to the
   offscreen proof samples.

6. `changingProofOutputs` compares samples about ten presents apart. Ordinary
   game motion makes those hashes change even if every intervening panel refresh
   repeats the nearest real frame.

7. `realFrameCount` and `producerHz` count submitted buffers/callbacks, not
   content-unique source images. An emulator can submit duplicate game images
   at 60 Hz for a 30-fps title and the badge will still call them 60 real FPS.

8. The runtime harness identifies gameplay by requiring a SurfaceFlinger layer
   named `SurfaceView[com.thorium.preview/...MainActivity](BLAST)`. GameCube's
   Dolphin route is a `PpssppGlesEngineSession`, for which `InWindowGameHost`
   creates `GameSurface`, a TextureView, not `GameSurfaceView`. A TextureView is
   composed by HWUI into its parent window and has no independent SurfaceFlinger
   layer. The selected SurfaceView can therefore be Qt's layer rather than the
   GameCube video output. The current layer-name predicate does not establish
   GameCube content identity.

## Confirmed implementation quality risk

The block matcher does not search continuous or even one-pixel displacement.
Its coarse candidates are -64, -32, 0, 32, and 64 source pixels per axis. The
refine pass adds only -8, 0, or 8 pixels. A uniform region can therefore select
only these 15 final displacements per axis:

`-72, -64, -56, -40, -32, -24, -8, 0, 8, 24, 32, 40, 56, 64, 72`

Common motion of 1–7 pixels and 9–23 pixels is not directly representable.
Moreover, the matching cost uses only three luma samples rather than a block.
Low-confidence or high-residual pixels switch to the nearest real endpoint at
phase 0.5. This can preserve visible judder over most of the screen while a
small set of blended/warped pixels is sufficient for the existing hash gate to
pass.

## What the saved GameCube evidence actually proves

Artifact:
`unified-android/build/acceptance-e5817de6/gamecube-metroid/`

- 5,364 presents were labelled synthetic by the phase scheduler.
- 537 sampled shader results differed somewhere from both endpoint renders.
- The corrected actual-present timestamps contain 126 valid presents at
  118.337 Hz, with a mean interval of 8.450 ms.
- The trace proves high-rate buffer presentation and non-endpoint shader output.
- It does not prove motion accuracy, meaningful image coverage, unique content
  at every latch, or perceptual equivalence to 120-fps motion.

## Required acceptance evidence

Before calling a system verified, collect all of the following for a moving
gameplay segment:

1. **Exact presented-image provenance.** Read back or instrument the actual
   default framebuffer immediately before each audited swap, assign a monotonic
   present ID, and join that ID/window to actual-present timestamps. Do not use
   a separately replayed proof FBO as the only pixel source.

2. **Content-unique source cadence.** Hash each promoted source image and report
   submitted buffers separately from unique source images. The displayed first
   number must be based on content advancement or a trustworthy emulator frame
   counter, not SurfaceTexture callback frequency.

3. **Magnitude and coverage.** For every audited synthetic present, report the
   fraction of pixels differing from each endpoint beyond a noise threshold,
   mean absolute difference, and a perceptual metric. Reject one-pixel and
   low-coverage changes.

4. **Crossfade falsification.** Render a naive same-coordinate crossfade for the
   same endpoints and phase. Require the motion result to differ materially from
   that baseline over a meaningful area; hash inequality is insufficient.

5. **Motion correlation.** Record the active/confident-flow fraction used by
   each proof present, the fraction that used endpoint fallback, and the output
   area whose sample coordinates moved by more than a small threshold.

6. **Known-ground-truth GPU test.** Feed translated high-contrast patterns at
   1, 2, 4, 7, 12, 20, 40, and 70 pixels, render each required phase, and compare
   against exact ground-truth intermediate positions. Require the motion result
   to beat nearest-frame and crossfade baselines (PSNR/SSIM and edge error).

7. **Independent visual capture.** For final device acceptance, capture the
   physical display at at least twice its refresh rate (or use a trustworthy
   120-fps display capture path) and verify that consecutive refreshes contain
   the expected intermediate motion. App-internal counters alone are not
   independent evidence.

8. **Per-system runs.** Run a different motion-rich game for every internal
   engine route, use a bounded capture window after counters are reset, reject
   crashes/fallback presentation, and archive the raw frames, actual-present
   timestamps, source hashes, flow metrics, and verifier report under the exact
   immutable APK SHA-256.

## Minimum engineering correction

Replace the sparse three-sample matcher with a tested dense optical-flow or
hierarchical block-matching pipeline that resolves small motion (at least
one-pixel source precision with sub-pixel refinement), computes forward and
backward consistency for occlusion, and reports fallback coverage. Do not tune
the existing thresholds until the known-ground-truth suite exists; otherwise a
change can make the counters look better while motion gets worse.
