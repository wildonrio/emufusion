# LSFG N64 Ocarina 20→40 — live SurfaceControl cutoff STOP

Date: 2026-08-24  
Device: AYN Thor, serial `427c87b2`  
Priority: top display  
Verdict: **STOP** (safe Direct fallback; no Ocarina LSFG qualification)

## Goal boundary

This run follows the authoritative EmuFusion goal:

- LSFG is the first backend priority.
- Ocarina of Time 20→40 is the first gameplay certification path.
- EmuFusion owns endpoint identity, source timestamps, phase, target selection,
  physical deadlines, successful-presentation accounting, and fallback.
- No timing, content, visual, maximum-2×, or evidence gate may be weakened.
- The OLED must be black/asleep whenever it is not required for a brief
  physical check.

The fundamental in-process Android LSFG feasibility milestone remains PASS as
documented in `docs/LSFG-ANDROID-FEASIBILITY-PASS-2026-08-24.md`. This document
records a later gameplay-integration failure; it does not revoke that bounded
feasibility result.

## Exact candidate

APK:

`unified-android/build/lucent-3.2.16-lsfg-framegen-qualification-a50e26aaa659339caaf151e4445c734f92d2c776116615d450b60325404f4768.apk`

SHA-256:

`a50e26aaa659339caaf151e4445c734f92d2c776116615d450b60325404f4768`

The installed base APK was independently hashed on the Thor and matched the
candidate exactly. The owner-private payload remained app-private; no Windows
DLL was packaged or executed.

## Bounded runs

### Fresh-install route refresh

Evidence directory:

`.evidence-lsfg-oot-r16-live-selftest-diagnostic`

The first post-install menu action still contained Pegasus's pre-refresh
external Mupen command and therefore stopped before LSFG. The installed route
closure itself had already changed N64 to the in-process route. This is not a
frame-generation result.

### Post-refresh in-process launch

Evidence directory:

`.evidence-lsfg-oot-r17-post-route-refresh-diagnostic`

The second launch used the refreshed command and reached the intended engine:

```text
23:28:34.027 LucentInWindow: In-window route accepted
               engine=mupen64plus-next system=n64
23:28:34.028 LucentGameLayer: Gameplay layer ready 1920x1080
23:28:38.504 EmuFusionFrameGen: Frame generator attached
               externalTransport=1 displayHz=120.00001
23:28:38.504 LucentGameLayer: LSFG qualification transport active;
               product backend assessment remains unqualified
```

LSFG startup succeeded. The run then failed closed during live presentation:

```text
23:28:39.279 EmuFusion-LSFG: poll failed:
               LSFG output missed its immutable SurfaceControl cutoff
23:28:39.280 EmuFusionFrameGen: External presentation session failed closed
```

The overlay switched honestly to `Direct`; no stale or invalid LSFG image was
claimed as qualified output.

Immediately before the cutoff failure, EmuFusion rejected a startup endpoint
interval whose immutable timestamps were 550 ms apart:

```text
Buffered endpoint discontinuity ... source=60 left=1 next=2
leftTs=159131208459919 nextTs=159131758459919 spanNs=550000000
sequenceContinuous=true timestampContinuous=false
Buffered presentation epoch reset ... previousEpoch=4 epoch=5
```

This confirms that startup/menu timing was not a valid Ocarina 20→40 source
interval and was correctly excluded.

## Source-proven timing defect

The live rendering loop currently performs these operations in this order:

1. `DisplayFrameGenerator.doFrame()` calls `pollPhysicalPresentations()` at
   the beginning of a Choreographer callback.
2. Later in the same callback it creates a one-panel-scan-ahead
   `PhysicalPresentationDeadline`.
3. `presentExternalBuffered()` submits the LSFG/endpoint request after the only
   poll for that callback has already happened.
4. The next native progress poll occurs on the next Choreographer callback.

Native `OwnedVulkanHost::pollSurfaceSubmission()` must queue the
SurfaceControl transaction before `completionDeadlineNs`. With a one-scan-ahead
target and the Thor driver lead removed from that target, the next callback is
already at or after the immutable cutoff. The host therefore fails closed with
the exact error above.

The isolated 256×144 activity self-test is still a valid feasibility PASS: its
bounded test driver advances the native live pipeline between submission and
the cutoff. Gameplay at 1920×1080 currently lacks an equivalent pre-cutoff
progress opportunity. The difference is scheduling architecture, not proof
that the private shaders are absent or that the Android Vulkan host cannot run.

## Next bounded arm

Do not lower the driver lead, move the cutoff later, busy-wait, block on a
fence, or retry a missed output.

The next experiment must materially change scheduling:

- Pipeline external presentations far enough ahead that at least one normal
  zero-wait progress callback occurs before the immutable driver cutoff.
- Keep the desired physical timestamp and interpolation phase exact for that
  future target.
- Preserve constant panel-divisor spacing (Ocarina target 40 on the measured
  approximately-120 Hz panel).
- Keep endpoint IDs/timestamps immutable and never extrapolate.
- Bound the number of in-flight requests and retain the safe Direct fallback.
- Commit counters only after a physically completed presentation.
- Add host tests proving the minimum lead, constant scan spacing, no catch-up,
  no late acceptance, and no cross-epoch completion.

A two-scan-ahead pipelined request is the smallest source-supported candidate,
but it must first be proven against the controller's retained endpoint window
and exact phase contract. If exact bracketing cannot be maintained, stop that
arm rather than relaxing phase or deadline rules.

## Device restoration

After the diagnostic:

- `com.thorium.preview` was force-stopped.
- All LSFG/RIFE/proof/dense qualification globals were cleared.
- System brightness was restored to `0`.
- Power state was verified as `mWakefulness=Asleep`.

