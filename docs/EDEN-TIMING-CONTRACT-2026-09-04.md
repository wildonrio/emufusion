# Switch timing source checkpoint — 2026-09-04

Status: source implemented, native artifact rebuilt and staged; all device/quality claims
UNVERIFIED. This supports, but does not complete,
[the acceptance goal](FRAME-GENERATION-GOAL-2026-09-04.md).

## Implemented boundary

- `engines/patches/eden-lucent-adapter.cpp` accepts only finite VI base-clock
  corrections within ±0.75% of declared 60 Hz, including fractional requests.
  Zero restores the upstream base; invalid requests do not alter active state.
  The C native host checks the same bound before an old adapter can be called.
- `engines/patches/eden-lucent-pacing.h` contains the compiled helper. VI uses
  double/long-double period arithmetic, retaining normalized composition swap
  interval and existing composition speed scale. Rounding one callback period
  to nanoseconds is not a measured fractional-panel phase lock.
- Native timing capability discovery is optional and versioned. Missing hooks
  mean unknown. The new Eden adapter advertises correction + submission
  diagnostics, NOT authoritative source-image timing. The Java host no longer
  assigns every native adapter an assumed 60-Hz source. This also leaves the
  old Eden/Cemu binaries and aPS3e untrusted; a declared base or average FPS
  does not grant authority. Lower-panel base-VI inference was removed too.
- Vulkan uses the actual monotonic submission timestamp for optional
  `VK_GOOGLE_display_timing`, replacing the fabricated wall-clock slot grid.
  Desired presentation time is a request, not a physical-present observation.
  Logs identify `submissionAttempt`, sampled VI callback counts, and
  `sourceIdentity=unjoined physicalPresent=unverified`. A failed submission is
  still only an attempt. These logs cannot demonstrate retired guest frames.

No guest underclock to 20/30/40/50 is allowed by these hooks. A 30-image/s title
on a 60-Hz VI base keeps its own buffer acquisition/hold semantics; one must
not set the base to 30 simply because its changing image rate is 30. Current
`hardware_composer.cpp` contains pre-existing logic that returns VI interval 1
while holding guest BufferItems according to their normalized swap interval.
This change preserves that code; its game-specific correctness is not newly
proven. Nonpositive/large swap-interval extensions retain their speed scale.

This is a VI pacing control, not proof that CPU timers, all guest logic, and
audio sample production have been reclocked together. That remains a separate
actual-guest-clock/audio validation gate. It is also not a decision to replace
frame generation permanently with Direct: the missing image join below is the
next implementation dependency for trustworthy generation.

## Next: true image identity through the used Vulkan path

The relevant source paths are relative to `engines/build/switch-src/eden/src`:

1. `core/hle/service/nvnflinger/buffer_item.h:29` already carries `timestamp`,
   `is_auto_timestamp`, and `frame_number`. A frame number belongs to a producer
   queue; combine it with session/display/layer or consumer identity. A reused
   buffer must retain its old identity, not acquire a new callback identity.
   A queued guest buffer is not automatically a retired simulation step or
   changing image; label that provenance precisely.
2. `nvnflinger/hardware_composer.cpp:49` (`ComposeLocked`, under the full
   `core/hle/service/` prefix) sees each acquired versus reused BufferItem.
   Capture per-layer provenance here. `hwc_layer.h:26` currently discards the
   frame number/timestamp when forming its composition stack. Overlay layers
   can change independently; do not turn overlay changes into guest advances.
3. `core/hle/service/nvdrv/devices/nvdisp_disp0.cpp:63` turns HwcLayers into
   `video_core/framebuffer_config.h:23` and passes them with acquire fences to
   `video_core/gpu.cpp:450` (`RequestComposite`). Carry a value-owned composition
   identity/metadata through this async work, including held/reused layers.
4. `video_core/renderer_vulkan/renderer_vulkan.cpp:176` (`Composite`) obtains a
   `Frame` from the present manager. Attach the same metadata to that frame,
   whose structure is `vk_present_manager.h:28`, before queueing it through
   `vk_present_manager.cpp:168` (`Present`). Clear metadata when frames recycle.
5. `vk_present_manager.cpp:491` currently calls
   `swapchain.Present(render_semaphore)` without the Frame metadata. Join the
   exact composition to its swapchain image/submission at this call, preserve
   it through queue failure/retry/recreation, and expose a bounded sideband to
   the host keyed to that image's actual buffer timestamp/token. Never join
   using “latest VI count”: presentation has a separate asynchronous queue.
6. Only after the host can match this metadata to the exact consumed source
   image should `AUTHORITATIVE_SOURCE_TIMELINE` be enabled. Separately collect
   physical present completion, actual guest clock/audio progression, and
   captured A/G/B provenance/held-out quality. No log or average-FPS substitution.

## Reproduce and rebuild

The source-lock `artifact` now identifies the rebuilt binary, SHA256
`d597932f0111349f341fdb8be13f5e6ddfb68bdee92c29246d8716be5bfd7004`,
35,544,128 bytes. `timingSourceCheckpoint.status` is
`rebuilt-device-unverified`. [Build/ELF evidence](EDEN-TIMING-BUILD-2026-09-04.json)
records the root-agent compile and independently inspected staged output.
No APK installation or device testing was performed by this subtask.

Read-only consistency check, from repository root:

```sh
python3 engines/tools/apply_eden_timing_patch.py
python3 -m unittest tools.tests.test_phase3_eden_timing_contract tools.tests.test_phase3_eden_core_timing tools.tests.test_phase3_eden_packaging
```

`--apply` on the script restores the tracked timing patch and canonical helper
and adapter translation unit. It rejects unknown patch contexts. This is a
timing subset, not a complete source/dependency closure; the existing source
lock's other local patches, configured CMake checkout, and ABI header remain
prerequisites. Do not reset this dirty Eden tree or other authors' changes.

The actual incremental Eden build command (from repository root) is:

```sh
/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk/cmake/3.31.6/bin/ninja -C engines/build/switch-src/eden/build-android yuzu-android
```

Its output is
`engines/build/switch-src/eden/build-android/src/android/app/src/main/jni/libyuzu-android.so`.
The configured NDK 28.2.13676358 strip tool is
`/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip`.
Strip the new output into a temporary staged file, inspect required exports and
ELF alignment, then replace only
`engines/build/arm64-v8a/liblucent_native_adapter_eden.so`. Repin artifact SHA256,
size, new capability export, and `ADAPTER_SHA256` in the packaging test; attach
build evidence and advance the checkpoint to `rebuilt-device-unverified`.

`unified-android/build.sh` only copies the staged Eden `.so` and source lock. An
APK rebuild or APK cache invalidation alone does not compile these C++ changes.
`engines/build_native_adapter.sh` is a skeleton that exits rather than building
Eden. Ninja's source/header dependencies should invalidate the affected objects;
verify its output actually recompiles the adapter, conductor, and swapchain.
No deletion of the configured build directory is necessary.

For the first device run, use Off as a baseline, record exact APK/library hashes
and the new diagnostic lines, and then restore OLED panels to black immediately
after active observation. Do not infer a smoothness/clock/quality PASS from a
successful boot or from these unit tests.
