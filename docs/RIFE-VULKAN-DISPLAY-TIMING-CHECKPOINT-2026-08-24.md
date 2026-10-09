# RIFE Vulkan display-timing checkpoint — 2026-08-24

## Verdict

The quarantined Android RIFE+ncnn Vulkan benchmark has now proved one narrow
transport result on the physical AYN Thor top panel:

> A GPU-resident synthetic 30→60 stream can be presented at constant two-scan
> spacing when every `vkQueuePresentKHR` carries an absolute
> `VK_GOOGLE_display_timing` timestamp 2 ms ahead of the intended scan cutoff.

This is **not** a gameplay, visual-quality, legal/provenance, or production
backend certification. The corpus is synthetic, the benchmark reports
`qualificationEligible=false`, and EmuFusion does not route games through this
backend. It proves only that the Vulkan inference/present transport can meet the
required physical cadence on this device.

## Three consecutive physical passes

Each run contains 120 measured output frames after eight warm-up submissions.
The SurfaceFlinger histogram below is computed from the last 120 named-layer
rows, not from callbacks or swap counts.

| Run | Physical Hz | Scan-interval histogram | Past timings | Withheld |
|---|---:|---:|---:|---:|
| `live-r17-singlecall-query` | 59.978560 | `{2: 119}` | 116 | 4 |
| `live-r18-lead2ms-repeat1` | 59.990494 | `{2: 119}` | 116 | 4 |
| `live-r19-lead2ms-repeat2` | 59.995781 | `{2: 119}` | 116 | 4 |

All three runs submitted 60 REAL and 60 GENERATED frames, completed all 120,
reported no busy/acquire/enqueue error, and returned monotonically ordered
`vkGetPastPresentationTimingGOOGLE` IDs. The four unavailable tail records equal
the four swapchain images still inside the driver's finite timing window; the
benchmark accounts for them explicitly rather than pretending they were
queried.

Authoritative evidence:

- `experiments/rife-ncnn-vulkan-android/android-benchmark/evidence/thor-surface-stream-2026-08-24/live-r17-singlecall-query/`
- `experiments/rife-ncnn-vulkan-android/android-benchmark/evidence/thor-surface-stream-2026-08-24/live-r18-lead2ms-repeat1/`
- `experiments/rife-ncnn-vulkan-android/android-benchmark/evidence/thor-surface-stream-2026-08-24/live-r19-lead2ms-repeat2/`

Frozen evidence hashes:

```text
r17 result  cdc2e70fadafb763d80bea9dcbab1a47624d729253020797c1d496366531d4a0
r17 latency 10b38db2871c3769e07121b5e68d80789052e453d7e25dedc74cc65cc24f8da3
r18 result  07b5b5e4528881a0a3e8989973353094ad411b4aaaf12f74fa633affa58c26c8
r18 latency 63e5ff4551b07dc90d9f8e3276ea8f046d2dc802b618335acbf22c1d445fcb22
r19 result  408c0f21ea0a23502d69b63295b8e516cade0d5be5129841fc173a63ecd0176e
r19 latency 176887bcb1265c7b6d157a38da31d8433884a22eddfdd545c636902ea6e02457
```

## Why the lead is required

Average-rate-only runs were misleading. Without the 2 ms lead, physical runs
could average approximately 60 Hz while containing a three-scan interval
immediately compensated by a one-scan interval. One captured generated frame
was ready roughly 4 ms before its desired time but was still presented
7.765688 ms after that desired time. This identified the compositor/driver
cutoff, not RIFE compute, as the stochastic interval defect.

The lead is a driver scheduling request only. The content must still be rendered
for the exact intended physical scan. EmuFusion's shared timing layer therefore
keeps two values:

1. `contentPresentationTimeNs` — owns temporal interpolation phase.
2. `driverDesiredPresentTimeNs` — exactly 2 ms earlier on the Thor.

If the early cutoff has already passed, the new product contract abandons that
scan and targets the next whole scan. It never emits a stale frame followed by
a catch-up burst.

## Product integration checkpoint

The top-panel product path now uses
`com.thorium.lucent.video.PhysicalPresentationDeadline` to create that two-time
contract. `AdaptiveFrameRateController` receives both the Choreographer callback
and the future physical presentation timestamp; only the latter advances the
endpoint phase. `DisplayFrameGenerator` supplies the early time to
`eglPresentationTimeANDROID` and commits counters only after a successful swap.

This integration is host-tested and Android-compiles, but it is not yet a
physical gameplay pass. The built-in v61 optical-flow path remains an honest
quality STOP: its last moving-game evidence did not meet confidence/coverage
requirements. Timing work must not be used to relabel that failed visual path
as qualified.

## Gates at this checkpoint

- Complete `unified-android/test.sh`: PASS.
- Frame-generation verifier/systemwide/runtime focused set: 368 PASS.
- Full debug Android APK build: PASS.
- Quarantined RIFE benchmark Python suite: 25 PASS.
- Physical Thor screen state after testing: both displays OFF / device asleep.

## Next proof work

1. Physically verify the product EGL deadline contract on direct/top-panel
   presentation before enabling generated output.
2. Certify N64 20→40, 30→60, and nominal-60→120 separately with real moving
   gameplay and SurfaceFlinger histograms.
3. Continue the built-in quality architecture; do not relax confidence,
   occlusion, scene-cut, or max-2× gates.
4. Resolve model/license provenance and complete representative moving-game
   visual inspection before RIFE can become an automatic backend candidate.

