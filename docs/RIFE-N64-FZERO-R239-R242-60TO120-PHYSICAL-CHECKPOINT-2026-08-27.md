# RIFE N64 F-Zero r239-r242 60-to-120 physical checkpoint — 2026-08-27

## Verdict

**QUARANTINED PHYSICAL STOP. DO NOT ROUTE THIS PATH AS A PRODUCT DEFAULT.**

The 160x90 RIFE arm proved that Thor can sustain the intended 60-to-120
presentation cadence for several seconds with numeric moving-content evidence
and adequate GPU time. It did not complete qualification: r242 eventually
recorded one real endpoint one physical scan late. The fail-closed fallback to
Direct FPS was correct.

Thor was returned to a black, non-emissive state after every bounded device
run. Future work must prepare and audit a test completely before illuminating
the device, and must restore both OLED backlights to zero immediately after the
test.

## Immutable artifacts

```text
r240: .evidence-rife-fzero-r240-history-window-recovery/
r241: .evidence-rife-fzero-r241-160x90-history-recovery/
r242: .evidence-rife-fzero-r242-160x90-sparse-loss/

r242 APK:
unified-android/build/lucent-3.2.16-rife-framegen-qualification-d66877deeec533646a495c1aeb164ab90fb28f834010f7a9843e09da5cb16683.apk
SHA-256: d66877deeec533646a495c1aeb164ab90fb28f834010f7a9843e09da5cb16683
```

Current key source hashes at this checkpoint:

```text
AdaptiveFrameRateController.java
61c565e15d9fbaec2cfe00105d33cf05bf6546fb7e1aeba2371a8db59bb42f52

RifeQualificationTransportFactory.java
1ca6a996c2a18ce4507f759d6aa8fc76858b5ea80e9343e500591e7a9b064244

DisplayFrameGenerator.java
5bc67acf786ccb763feba35b4a81501238cd5dac1cc96257a273893bbefa43ee
```

The repository worktree contains extensive pre-existing user work. Hashes and
the immutable evidence directories are the ownership guard; do not infer this
checkpoint from a broad Git diff.

## What was fixed and proved

### EGL history-window recovery

`EGL_ANDROID_get_frame_timestamps` does not promise terminal timestamp events
in submission order, and Android SurfaceFlinger retains a small bounded history.
The native timing tracker now caches newer terminal rows while continuing to
poll the oldest submitted row. It emits evidence strictly in submission order.

An expired timestamp row reported as `EGL_BAD_ACCESS`/UNAVAILABLE now restarts
only the external timing/content evidence window. It does not falsely claim a
physical drop and does not disable an otherwise healthy visible presentation
path. Explicit DROPPED results remain fail-closed.

Official references:

- Khronos `EGL_ANDROID_get_frame_timestamps` specification:
  https://registry.khronos.org/EGL/extensions/ANDROID/EGL_ANDROID_get_frame_timestamps.txt
- AOSP `FrameTimestamps.h`, including the bounded history implementation:
  https://android.googlesource.com/platform/frameworks/native/+/6658f2faec45be866495f3f360c7ed761e864ad9/include/gui/FrameTimestamps.h

### 192x108 was too expensive

r240 recovered correctly from timestamp-history expiry, but a 192x108 generated
pair reached `gpuWorkNs=8077500` and missed the 120-Hz generated-frame budget.
That arm is rejected.

### 160x90 has sufficient measured GPU budget

r241 and r242 used a quarantined 160x90 endpoint geometry. r242's last complete
health snapshot before rejection reported:

```text
app swap cadence:       119.901 Hz
physical cadence:       119.915 Hz
externalTimingQualified=1
externalContentNumericPassed=1
externalTimingWindow=40
externalTimingSamples=1384
externalGpuMaxNs=5934635
externalGpuBudgetMisses=0
externalPhysicalClockPeriodNs=8338574
externalPhaseMax=0.500000
physicalDropped=0
```

This proves that the 160x90 GPU workload is materially safer than 192x108. It
does not prove the whole system is qualified.

### Sparse source-gap retention

r241 was torn down because one ordinary 33.333-ms source period appeared in a
599-period proof despite an otherwise exact 60-Hz clock. The controller now
permits a sparse exact-two-period gap only when retaining an already-proven
canonical clock. It cannot acquire a clock from such evidence, cannot
interpolate across the missing adjacent pair, and revokes retention when the
bounded one-percent allowance is exceeded. Host tests cover retention,
non-interpolability, and persistent-change revocation.

## r242 exact stop

r242 did not suffer another source-proof transition. After approximately seven
seconds of stable 119.9-Hz operation, app-owned physical timing rejected one
real endpoint:

```text
frameId=3420
generated=0
desiredNs=15318178572977
actualNs=15318186902228
actual-desired=8329251 ns
bindWallNs=1
swapWallNs=463906
gpuWorkNs=0
```

The endpoint arrived almost exactly one measured panel scan late. Because it
was a real endpoint with zero RIFE GPU work, this is not evidence that 160x90
optical-flow computation exceeded budget. It is a presentation scheduling,
compositor, or system-contention miss. The evidence path correctly stopped
claiming 120 Hz and committed Direct FPS.

The run also logged 577 stale private RIFE outputs and 1,085 Phase 2 PCM FIFO
overflows after activation. Neither may be waved away. The stale-output stream
needs a bounded causal audit, and the continuous audio FIFO overflow/logging is
a separate system-health defect that may contribute contention. Do not loosen
the physical timing gate to make this run pass.

## Host verification

The final controller and evidence-window source passed:

```text
unified-android/test.sh: PASS
focused frame-generation/controller suite: 123 PASS
native ASan/UBSan timing tracker suite: PASS
```

## Next safe work

No further physical test should run until the following are resolved from
saved logs and host tests:

1. Determine why private RIFE outputs became stale at high frequency while
   visible cadence remained near 120 Hz.
2. Diagnose and stop the per-frame Phase 2 PCM FIFO overflow storm without
   changing video acceptance criteria.
3. Add full critical-path attribution for the real-endpoint one-scan miss so a
   subsequent bounded run can distinguish scheduler lateness, EGL swap delay,
   compositor delay, and unrelated engine contention.
4. Re-run 160x90 only after those changes pass host tests and an independent
   audit. Require a substantially longer clean 60-to-120 physical window; do
   not qualify from the pre-failure seven-second interval.

The 128x72 arm remains manually rejected for severe smearing. The 192x108 arm
is physically over budget. Therefore 160x90 remains the only defensible
quarantined geometry, but it is not yet product-ready.

## OLED cleanup state

After r242:

```text
device serial=427c87b2
screen_brightness=0
panel0 actual backlight=0
panel1 actual backlight=0
com.thorium.preview pid=
org.pegasus_frontend pid=
```

The device is intentionally left awake with both OLEDs black to avoid Thor's
ColorFade/sleep deadlock. Do not send `KEYCODE_SLEEP`.
