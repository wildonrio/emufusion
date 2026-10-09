# RIFE N64 Ocarina r48-r51 — physical STOP checkpoint

Date: 2026-08-25  
Device: AYN Thor, ADB serial `427c87b2`  
Scope: qualification-only, legally redistributable RIFE v4.6/ncnn backend, Ocarina 20→40 top-screen path

## Verdict

**STOP. Do not route this backend into the normal Frame Generation: On policy.**

r51 proves that the current scheduler and Vulkan path can deliver a uniform physical 20→40 stream for an extended interval, but two independent product blockers remain:

1. A single late Vulkan FIFO presentation can move the stream one whole 120-Hz panel scan behind its immutable content target and keep it there.
2. The current 128×72 inference image is visibly unacceptable when enlarged to the top panel. The captured r51 frame has severe horizontal smearing/duplication even though the numeric content proof passes.

No threshold or verifier was weakened. The overlay remained `UNQUALIFIED RIFE`.

## Immutable physical evidence

- r49: `.evidence-rife-oot-r49-one-scan-pipeline-steady/`
  - APK SHA-256: `40abf6f71878a492bffcea44d4b14eee7fbbcaa0ead24e23d5f844b7ea1d0946`
  - Proved approximately 40 FPS before a transient `transport-busy` result.
  - Disproved a speculative one-panel-scan content offset: 409 physical rows landed on the driver/content slot, not the added content scan.
  - Old NOT_READY handling reset/re-primed on every later slot and collapsed presentation to roughly 8 FPS.

- r50: `.evidence-rife-oot-r50-pipeline0-preserve-pair/`
  - APK SHA-256: `bf62e5b498a85b80f37cd56dce8cf59ccb3d81f62bcdb69cca831cbc4231dfb9`
  - Preserving the pair removed the epoch-reset loop.
  - Every midpoint still returned `transport-busy`; the path remained endpoint-only at about 20 FPS.
  - Root cause was deterministic planning, not a stuck native worker: REAL WSI release was planned roughly 32–42 ms ahead while the next 40-FPS slot arrived after 25 ms.

- r51: `.evidence-rife-oot-r51-next-safe-lattice-slot/`
  - APK SHA-256: `58d36fc9ead23394c83be61997a69bc70922a572b3e32bec87f3c5ba45dd02f7`
  - Planner chose the next exact 3-scan target when at least 14 ms remained; otherwise it skipped one complete divisor slot.
  - Stable epoch 11 sustained approximately 39.98 physical FPS, with zero scheduler underruns and near-equal endpoint/generated counts.
  - Representative good snapshot: 111 physical timing samples, 56 endpoint + 55 generated, pipeline 0, no desired-slot miss, combined enqueue+GPU p95 about 10.54 ms.
  - Later, `desiredSlotMisses` grew from 0 to 168 and signed slot error became about +8.33 ms. Cadence remained near 40 FPS, but content was permanently one scan late.
  - Final screenshot: `r51/final-screen.png`; manual verdict is severe visible smear, hard failure.

## Source corrections preserved after r51

- `PhysicalPresentationDeadline.nextAlignedOutput` uses the first exact output-divisor target with at least `THOR_OUTPUT_SUBMISSION_LEAD_NS = 14_000_000` rather than blindly requiring a full period before lattice rounding.
- `AdaptiveFrameRateController.dropBufferedPresentationSlot()` consumes only the unavailable physical slot. It does not reset the scheduler epoch/pair, commit a presentation, spend credit, advance an endpoint, retry, or catch up.
- External NOT_READY uses that one-slot drop instead of invalidating/re-priming the pair.
- `RifePresentationTransport.pollNativeRelease()` has a fail-closed native release cutoff.
- Production and verifier expect physical presentation pipeline 0.
- A post-r51 host-green safety patch adds a session-lifetime `externalTimingRejected` latch. The first physical deadline/desired-slot/earliest-present violation disables the generated rate path and continues endpoint-only Direct through the already-live Vulkan transport. It is not yet built or physically exercised.

Host gates after the safety patch:

- `unified-android/test.sh`: PASS
- Focused Python timing/packaging/system suite: 84/84 PASS
- `git diff --check` on the bounded files: PASS before the final fallback patch; rerun before freeze.

## Required next architecture

Do not spend another device run merely tuning the 14 ms lead or accepting either physical slot.

Split inference from presentation:

1. When an adjacent safe pair and its exact future output timestamp are known, submit RIFE into a retained GPU output image.
2. Poll completion without waiting; do not expose it to WSI.
3. At the immutable release window, perform only a lightweight prepared-image copy/present.
4. Keep at least two independent preparation/presentation slots so a REAL cannot occupy the following SYNTHETIC slot.
5. Endpoint REAL should be a passthrough/copy, never a redundant RIFE inference.
6. Raise the inference resolution and remeasure. 128×72 is manually rejected. A bounded 192×108 arm is the first plausible experiment; it must still meet the exact 25 ms 20→40 period and physical-slot contract.
7. Any preparation miss drops that one output slot and retains causality. No retries, catch-up, extrapolation, fake duplicate, or relabeling.
8. Any physical slot slip disables generation for the session. Future product fallback must prove that already-queued generated rows are drained/invalidated safely before claiming atomic Direct.

Acceptance still requires a long moving-game capture, exact 3-panel-scan spacing, at least 30 generated physical rows in one stable epoch, clean content evidence, and clean manual inspection with no smear/ghost/warp.

## OLED/device state at stopping point

After r51:

- `mWakefulness=Asleep`
- both physical displays: `state OFF, committedState OFF`
- brightness setting: `0`
- `com.thorium.preview`: stopped
- `emufusion_framegen_rife_qualification`: `null`
- `emufusion_framegen_lsfg_qualification`: `null`

Future device work must wake Thor only for the bounded measured interval, then repeat and verify this exact cleanup state.
