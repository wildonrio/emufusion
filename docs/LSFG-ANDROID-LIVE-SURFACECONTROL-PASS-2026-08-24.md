# LSFG live Vulkan → SurfaceControl integration — physical PASS (2026-08-24)

Status: **BOUNDED LIVE-PIPELINE AND 240-PRESENT CADENCE PASS; GAMEPLAY ROUTING REMAINS OFF**.

This checkpoint supersedes only the live-integration work item in
`LSFG-ANDROID-FEASIBILITY-PASS-2026-08-24.md`. It does not certify a game,
rate path, visual quality, or product routing.

## Physically exercised chain

The startup-only black qualification run exercised the same native chain now
used by the live LSFG transport:

1. Import two exact Java/EmuFusion `AHardwareBuffer` endpoints.
2. GPU-copy them into one of three fixed LSFG slots.
3. Run the fixed-midpoint LSFG context when requested.
4. Zero-poll the LSFG sync FD before the immutable cutoff.
5. Import that FD back into Vulkan as the exact proof/release dependency.
6. Render the asynchronous three-tile content proof and release the selected
   fixed AHB to `VK_QUEUE_FAMILY_EXTERNAL`.
7. Export the proof-ready sync FD to `ASurfaceTransaction_setBuffer`.
8. Request the exact physical CLOCK_MONOTONIC target with
   `ASurfaceTransaction_setDesiredPresentTime`.
9. Join the SurfaceControl present-fence timestamp with the Vulkan proof-fence
   timestamp and content proof.
10. Reuse a slot only after physical delivery and SurfaceFlinger's
    previous-buffer release fence.

The live path does not call `vkQueuePresentKHR` or consume
`vkGetPastPresentationTimingGOOGLE`. The old WSI implementation remains frozen
as setup/reference code and is reported as non-live.

## Physical result

Device: AYN Thor serial `427c87b2`, display 0/top panel.

APK:

`unified-android/build/lucent-3.2.16-lsfg-framegen-qualification-d86c95e4ad533b5551e722bb82547f1ba0c6c42b10172c3874c6e14f2f2fe9ea.apk`

SHA-256:

`d86c95e4ad533b5551e722bb82547f1ba0c6c42b10172c3874c6e14f2f2fe9ea`

Terminal record:

```text
RESULT PASS capabilities={
  "selfTestPassed":true,
  "selfTestEndpoint":true,
  "selfTestGenerated":true,
  "selfTestDeadline":true,
  "selfTestPhysicalTiming":true,
  "selfTestContent":true,
  "selfTestLiveSurfaceControl":true,
  "selfTestLiveCadence":true,
  "selfTestLiveCadencePresents":240,
  "selfTestLiveCadenceGenerated":120,
  "selfTestLiveCadenceMinIntervalNs":8334741,
  "selfTestLiveCadenceMaxIntervalNs":8340833,
  "selfTestLiveCadenceMaxErrorNs":7500,
  "selfTestGenerationCompleteNs":143419506405600,
  "selfTestGenerationDeadlineNs":143419613337262,
  "selfTestFirstDesiredNs":143419607003929,
  "selfTestFirstLatchNs":143419597029819,
  "selfTestFirstActualNs":143419607131276,
  "selfTestSecondDesiredNs":143419615337262,
  "selfTestSecondLatchNs":143419605291173,
  "selfTestSecondActualNs":143419615469767,
  "selfTestPhysicalIntervalNs":8338491,
  "refreshDurationNs":8333333,
  "ownedWsiImplemented":false,
  "ownedWsiFrozenReference":true,
  "surfaceControlLiveImplemented":true,
  "surfaceControlReleaseFenceReuse":true,
  "zeroWaitLivePath":true,
  "liveDeviceWaitIdle":false,
  "liveBlockingFenceWait":false
}
```

The direct physical pair interval was `8,338,491 ns` against the measured
`8,333,333 ns` refresh, an error of `5,158 ns` (`0.0619%`). The integrated
live subtest separately required exact endpoint and distinct midpoint content,
positive kernel proof timestamps no later than each immutable GPU deadline,
ordered SurfaceControl physical completion, and successful retirement of the
first slot through the second transaction's previous-buffer release fence.

The subsequent bounded soak delivered 240 consecutive physical rows—120
endpoint selections and 120 LSFG midpoints. Across all 239 intervals, the
minimum was `8,334,741 ns`, the maximum was `8,340,833 ns`, and the worst
absolute error from one measured panel scan was `7,500 ns` (`0.09%`). Every
row passed the exact ID/content/GPU-deadline join, and repeated three-slot
retirement left only the newest physically displayed buffer unreleased.

The test intentionally leaves the newest setup buffer owned until the first
live replacement; that first replacement supplies its release fence. This
proves the three-slot lifecycle without pretending the currently displayed
buffer is reusable.

## Safety

- No live CPU map/readback.
- No live blocking fence wait or sleep.
- No `vkDeviceWaitIdle` outside teardown.
- No WSI timing feedback in JNI live polling.
- No stale-frame fallback after a deadline or identity failure.
- GPU completion uses the duplicated exported sync-file's kernel timestamp,
  not a late CPU fence observation.
- Actual delivery uses the compositor present-fence timestamp.
- The user DLL is neither executed nor packaged; private shaders remain
  app-private.
- The qualification Activity was black at brightness zero. Thor was restored
  to brightness `7`, mode `0`, and `mWakefulness=Asleep`.

## Gates

- ARM64 native link: PASS.
- Owned SurfaceControl source contract: PASS.
- Focused LSFG packaging tests: 5/5 PASS.
- `unified-android/test.sh`: PASS.
- Conditional APK build/verifier: PASS.
- Bounded physical integrated self-test: PASS.

## Frozen identities

- `owned_surface_control_presenter.hpp`: `3812de4bfd6b370b9dd2095f378a624ecb51859e39b1501e225660e3b1d1aa4e`
- `owned_surface_control_presenter.cpp`: `64039ff7cec4c2b24bb2df9e694f03790b90056ef7ae92f2174b33f59a4194c9`
- `owned_vulkan_host.hpp`: `64f720c6aec2b8da0d2427ea94f20d3a14a6f84ce9764725b0ae723ecf201df9`
- `owned_vulkan_host.cpp`: `0338dcceff96c02d4c705cc0bc22f3fe9cd6de3034b997c5da3b6c85a3cad637`
- `lsfg_qualification_jni.cpp`: `2fb2f81c5a35a6545151149bad5650d213a2e3a7de4d7ab3985001833060279c`
- `LsfgPresentationTransport.java`: `f9688dc4246305571618aba096a41e34ec123579823def16344d9f6c37994b28`
- `LsfgQualificationRuntime.java`: `165ff7d7efd3b400f2674de1b776e149655a00fbe21ca3c882a8916d868eb02f`
- `LsfgQualificationSelfTestActivity.java`: `620e5fb91bd8458a639ff01e5dbf1c4aed7f22f87657676983718f31fa0ad3c5`
- `NativeLsfgBridge.java`: `e881f64ceaac2d4e1c89e72a94f47a57e6c7cae86707d5a9adf96ec2bb9be3ad`
- Source verifier: `253fd270c556aa7e201105770801ea224f7ee95ac07e56d6a34479ac486ccaff`
- Focused test: `4347ffbddfe4811759efe416c9877f0b9f576578ba0676de06c975561e373d20`

## Next bounded work

Bind the physically proven backend to EmuFusion's shared Java timing authority
and prove immutable endpoint timestamps, midpoint phase, deadline construction,
and honest S/T/A accounting. Then begin Ocarina of Time 20→40 top-screen
certification. The 240-present native transport soak cannot by itself certify a
game or the complete Java scheduling path.
