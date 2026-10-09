# LSFG Android feasibility checkpoint — bounded STOP (2026-08-24)

## Verdict

The in-process Android Vulkan/SurfaceControl path is technically viable, but
the current gameplay integration is **not qualified and must remain off by
default**.

The bounded startup path now proves all of the following on the AYN Thor:

- Android ARM64 native execution.
- EmuFusion-owned Vulkan initialization and fixed GPU-resident buffers.
- LSFG output presented through an EmuFusion-owned `ASurfaceControl` child.
- Exact desired-present timestamps are passed to SurfaceControl unchanged.
- Physical-present timestamps are obtained without synchronous readback.
- A 240-present startup soak completes at a measured 120.000000 Hz, including
  120 generated presentations.
- Startup completes before the emulator is given the input `Surface`, avoiding
  the prior Mupen/EGL ownership race.

The first live Ocarina stream then fails closed for two related integration
reasons:

1. A controller-selected external presentation can arrive before the
   asynchronous ImageReader transport owns the exact adjacent endpoint pair.
2. The following live request misses its immutable SurfaceControl cutoff; the
   native Vulkan host quarantines itself.

This means the feasibility milestone is not complete: the standalone transport
and physical cadence proof pass, but EmuFusion has not yet demonstrated a live
gameplay stream that supplies adjacent endpoint images early enough to meet the
same immutable deadline.

Per the project stopping rule, do not keep making small threshold or timestamp
adjustments to this integration. Either perform a material request-scheduling
redesign that makes pair readiness part of selection and queues work before the
cutoff, or proceed with the qualified built-in path while preserving this
evidence.

## Exact physical evidence

### r10 — normalized physical timestamp residual

Evidence directory:

```text
.evidence-lsfg-oot-r10-start-timeout
```

The old 2.5-second startup race was gone. The self-test rejected only because
the normalized present-fence estimate was 5.3 and 7.4 microseconds before the
two requested timestamps, despite an 8.331198 ms physical interval and 2.135
microseconds of interval error. The startup self-test was aligned with the
existing strict live evidence tolerance (minimum 150 microseconds or 2% of one
output interval); requested timestamps and maximum-late bounds were unchanged.

### r11 — fence-less callback

Evidence directory:

```text
.evidence-lsfg-oot-r11-physical-tolerance
```

Android returned a completed SurfaceControl callback without a present fence.
The NDK explicitly permits `ASurfaceTransactionStats_getPresentFenceFd()` to
return `-1` when no present fence is available. This row was never accepted as
physical evidence. A single fresh-child retry was added; the 240-present live
soak still requires a valid fence for every row.

Official references:

- <https://developer.android.com/ndk/reference/group/native-activity>
- <https://android.googlesource.com/platform/frameworks/base/+/843d5f61eb47/native/android/surface_control.cpp>

### r12 — startup/soak pass, gameplay cutoff STOP

Evidence directory:

```text
.evidence-lsfg-oot-r12-bounded-fence-retry
```

APK:

```text
unified-android/build/lucent-3.2.16-lsfg-framegen-qualification-92182cf1cb9b8eae9dbf0620d34cc8057622a03276e4648282e8ca77732d267b.apk
SHA-256 92182cf1cb9b8eae9dbf0620d34cc8057622a03276e4648282e8ca77732d267b
```

Key device records:

```text
21:06:57.133 Frame generator attached ... externalTransport=1 displayHz=120.00001
21:06:57.133 LSFG qualification transport active; product backend assessment remains unqualified
21:06:59.139 Physical panel clock committed ... measuredHz=120.000000 samples=240
21:06:59.281 external presentation lacks its exact adjacent endpoint pair
21:06:59.356 LSFG output missed its immutable SurfaceControl cutoff
21:06:59.365 owned Vulkan live host is quarantined
```

There was no frame-generator startup timeout, no `EGL_BAD_ALLOC`, and no Mupen
`cannot create/make-current` failure. The remaining failure is inside live
endpoint/deadline integration, after the native startup/soak proof.

## Required next architecture if LSFG is resumed

This must be a material lifecycle change, not a looser gate:

1. Make external endpoint ownership/readiness part of the shared controller's
   selection input. A presentation may not be selected until the exact adjacent
   pair is retained by the transport.
2. Schedule the external request early enough that GPU completion precedes the
   immutable SurfaceControl driver cutoff. Do not move the requested physical
   timestamp, fabricate completion, or submit a catch-up frame.
3. On any native quarantine or identity failure, latch the external backend
   failed once, stop polling/submitting, discard interpolation state, and ask
   the owning game surface to re-prime Direct or another qualified backend at a
   safe session boundary. Do not log the same fatal error every vsync.
4. Re-run the standalone startup self-test, 240-present soak, and then a long
   moving Ocarina 20→40 physical qualification. Startup proof alone is not a
   gameplay pass.

## Host verification

At this checkpoint:

- Native CMake arm64 target: PASS.
- LSFG owned-presentation source verifier: PASS.
- Systemwide frame-generation structural tests: 65/65 PASS.
- Unified Android host suite: PASS after the final bounded retry change.
- Full qualification APK build and one-app APK boundary: PASS.

## Frozen hashes

```text
197ee1d65df5b4d21f894602d47f42ad4e115366b39fd9cc45b6605222dc5c93  lsfg_qualification_jni.cpp
3948eb443e7897e85f5bd65d87b9e638e2c91abc8eee25ef95f64e69ea1f8516  owned_surface_control_presenter.cpp
07f58dd6ff41820cb8173300117ffaaf8b5de0833f146415273d4bb81e4e9c0b  owned_surface_control_presenter.hpp
17bc7dd1e8f2cb5b10db3e4bca23b93716cb6075f1d5d9c21bf142d63ec26e79  LsfgQualificationRuntime.java
98b6fb2aa2d2004aad8db6e4ea0b6fb0ac937d07d7202cceaa4981a68d85253b  LsfgPresentationTransport.java
1ddfed3aa1d45850adc2326041ab0155a49b05a204f72bd15f372770a277bfe9  DisplayFrameGenerator.java
50530bab52825d7a8fbb3a3a49c65ba237453a9cf441fcbc1063e0729f60049d  verify_owned_wsi_setup_source.py
14ae7f41bbd1175e4afdfdc40dc12233c9995d014f7098612f15c2166cf0701c  test_systemwide_frame_generation.py
```

## Device cleanup

After r12, `com.thorium.preview` was force-stopped, the LSFG and RIFE global
qualification switches were deleted, brightness mode was restored to manual,
brightness was restored to 7, and the Thor was put to sleep. Default product
behavior remains unaffected because this backend is shell-only and off by
default.
