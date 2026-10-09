# LSFG in-process Android feasibility — physical PASS (2026-08-24)

Status: **FUNDAMENTAL THOR FEASIBILITY PASS; PRODUCT/N64 ROUTING REMAINS OFF**.

This is the bounded milestone required before gameplay integration. It proves
that the user-owned LSFG 3.1 assets can run inside the EmuFusion process on the
AYN Thor's ARM64 Adreno Vulkan stack, consume two EmuFusion-owned RGBA8
`AHardwareBuffer` endpoints, generate a distinct midpoint into another fixed
GPU buffer, and present that buffer through an EmuFusion-owned top-display
surface without a companion app, MediaProjection, capture, or overlay.

It does **not** certify N64 gameplay, any system/rate path, redistribution of
the private shader payload, or the current product selector. Product routing
therefore remains Direct until the common live transport and the first 20→40
N64 path pass their own long moving-game acceptance runs.

## Physical result

Device serial: `427c87b2` (AYN Thor), display 0/top panel.

Final qualification APK:

`unified-android/build/lucent-3.2.16-lsfg-framegen-qualification-0ee0c81e991a3b8dceaa8c3f27c1b5268fa9372bd3310f2c68f13c65b4a2ffba.apk`

APK SHA-256:

`0ee0c81e991a3b8dceaa8c3f27c1b5268fa9372bd3310f2c68f13c65b4a2ffba`

Terminal log record:

```text
RESULT PASS capabilities={
  "selfTestPassed":true,
  "selfTestEndpoint":true,
  "selfTestGenerated":true,
  "selfTestDeadline":true,
  "selfTestPhysicalTiming":true,
  "selfTestContent":true,
  "selfTestGenerationCompleteNs":141178739931142,
  "selfTestGenerationDeadlineNs":141178846866242,
  "selfTestFirstDesiredNs":141178840532909,
  "selfTestFirstLatchNs":141178833042444,
  "selfTestFirstActualNs":141178843244371,
  "selfTestSecondDesiredNs":141178848866242,
  "selfTestSecondLatchNs":141178841373330,
  "selfTestSecondActualNs":141178851580048,
  "selfTestPhysicalIntervalNs":8335677,
  "refreshDurationNs":8333333,
  "surfaceControlPresentation":true,
  "surfaceControlDesiredPresentTime":true,
  "surfaceControlPhysicalFence":true
}
```

Derived facts:

- LSFG completion preceded the immutable generation deadline by
  `106,935,100 ns`.
- Physical present interval was `8,335,677 ns` against the measured
  `8,333,333 ns` panel interval: error `2,344 ns` (`0.0281%`).
- First and second present-fence timestamps had the same constant compositor
  offset from their requested physical targets (`2.711462 ms` and
  `2.713806 ms`), rather than alternating cadence.
- Both presentation callbacks supplied positive latch times and valid physical
  present fences. Kernel sync-fence timestamps—not callback time, submission
  count, or an FPS estimate—were used as actual presentation evidence.
- The self-test physically presented an endpoint buffer and a distinct LSFG
  output buffer in order. Setup-only content validation verified distinct left,
  right, and generated checksums. The reusable live presentation API contains
  no CPU map/readback.

## Why the Vulkan WSI arm was replaced

Thor advertises `VK_GOOGLE_display_timing`, returns a valid
`8,333,333 ns` refresh duration, and accepted both timed FIFO presents. Both
Vulkan presentation fences signaled. Nevertheless, 9,636 zero-timeout calls to
`vkGetPastPresentationTimingGOOGLE` over the bounded three-second horizon
returned zero timing records:

```json
{"pending":2,"presented":2,"presentFenceReady":2,
 "pastTimingQueries":9636,"pastTimingNonzeroQueries":0,
 "pastTimingRecords":0,"fatal":false}
```

The Activity was top-resumed on display 0 and its SurfaceView/BLAST layer was
visible in SurfaceFlinger, so this was not a hidden-window or wrong-display
failure. The advertised extension is unusable as Thor's physical-accounting
authority. It was not papered over with GPU fence time or average FPS.

The bounded replacement uses Android's public NDK SurfaceControl API:

- `ASurfaceControl_createFromWindow` creates EmuFusion's child layer.
- `ASurfaceTransaction_setBuffer` attaches the LSFG `AHardwareBuffer`
  directly.
- `ASurfaceTransaction_setDesiredPresentTime` carries the exact requested
  CLOCK_MONOTONIC target.
- `ASurfaceTransaction_setOnComplete` reports presentation asynchronously.
- `ASurfaceTransactionStats_getPresentFenceFd` supplies the physical fence.
- `sync_file_info` provides the signaled child-fence timestamp without a wait.

Primary API reference:
<https://developer.android.com/ndk/reference/group/native-activity>

## Safety and ownership

- User DLL inspected but never executed or packaged:
  `Lossless.dll` SHA-256
  `fe0faeb147accab84539ac2bdcaa4eb3dec850752a336e710b85fc87477004e4`.
- Public wrapper commit:
  `3e89e5439a98f55d5acb003d20039426ab24e69c`.
- Private payload manifest SHA-256:
  `6e025f1627115de03e2c91198023f763975aec7fd8eadbc9ae65b89ac28f3563`.
- Device-private payload contains 48 validated SPIR-V files plus one manifest,
  and zero DLL files. It is not in the APK.
- The reusable SurfaceControl submit/poll API is callback-driven and uses only
  zero-timeout fence polling. It contains no blocking wait, synchronous live
  readback, `vkDeviceWaitIdle`, capture loop, or stale-frame fallback.
- The only CPU content read is explicitly confined to the bounded setup
  self-test after LSFG completion; it is not used by live presentation.
- The qualification Activity is shell-only, black, brightness zero, and has no
  gameplay/ROM path. The Thor was returned to `mWakefulness=Asleep` with its
  original brightness `7` and mode `0` after every bounded run.

## Host gates

- Focused packaging/verifier suite: 24/24 PASS.
- Owned presentation source contract: PASS.
- `unified-android/test.sh`: PASS.
- Android ARM64 native compilation and conditional APK build: PASS.
- Conditional APK verifier: PASS; LSFG native library present, private DLL and
  shaders absent.

## Frozen milestone identities

- `owned_surface_control_presenter.hpp`:
  `fe2b23ad4b8c7b953b85dd36628aae70512893644aef16bdb26e5abcf2a7d272`
- `owned_surface_control_presenter.cpp`:
  `344941723fe2d546ac902bcf824fe97a28d204ea7f52b355940cac843a4e5d66`
- `owned_vulkan_host.hpp`:
  `3a808d755498ac60fda2c42fbcff89ff966b430cf9f1d28e6652971d3e111e19`
- `owned_vulkan_host.cpp`:
  `ab31c52972b46b51db6b9b14f47d4a93d3b74616806300d4192fa505e23b3465`
- `lsfg_qualification_jni.cpp`:
  `2d74ba3b31e7151f5291d1ea2c0b489fc996ea95e8314690b19fb62e59e44eda`
- Native `CMakeLists.txt`:
  `693ec038a8c87a97f99af197830701f9fc01a86b5bba6a6836390fdf5ae761e1`
- `LsfgQualificationSelfTestActivity.java`:
  `907aa75e39b31548def780683704a56f064b9305c82fa7cb3d0c54cde7100847`
- `LsfgQualificationRuntime.java`:
  `03ac2b4849a92d3cbbc515595f2d9b500973b6dc68ae27dea66f301749c55464`

The source hashes above describe the physical PASS APK. Any subsequent live
transport integration must supersede and re-audit them rather than silently
claiming this evidence for changed bytes.

## Next bounded work

1. Promote the proven SurfaceControl presenter from the opening self-test into
   the common live LSFG enqueue/poll path, including three-slot buffer-release
   ownership and asynchronous GPU content proof. Do not keep the nonfunctional
   `VK_GOOGLE_display_timing` join as runtime authority.
2. Re-run the opening self-test and a long no-game cadence soak with exact
   desired/latch/present-fence rows, slot release conservation, no dropped
   transactions, and no blocking calls.
3. Only then begin the first gameplay certification: N64 Ocarina of Time
   20→40 on the top screen. Product selection remains Direct until that path
   passes physical cadence and moving-video inspection.
