# Switch source-image metadata checkpoint — 2026-09-04

Status: native-rebuilt/staged, device-unverified. This is not a frame-generation
or judder-free PASS. The current artifact is
`74efdc7a95e63f5434ee4cd0a27b1200d66f141f128dbfb7a66fe4797d30a8d4`;
the previous `d597932f` artifact is retained in the build-evidence backup path.
See [measured build evidence](EDEN-SOURCE-IMAGE-LIFECYCLE-BUILD-2026-09-04.json).
The older
[proposal](EDEN-SOURCE-IMAGE-JOIN-PROPOSAL-2026-09-04.md) describes the rationale,
Android/Khronos timestamp references and further device gates.

## Implemented source contract

The original `BufferItem.frame_number`, guest-requested timestamp and automatic
timestamp flag, queue-lifetime epoch, acquisition/hold state, swap interval and
layer geometry are copied through `HwcLayer`, `FramebufferConfig`, the existing
by-value asynchronous composite request, and the actual Vulkan `Frame`. No
pointer to a mutable guest buffer or latest-composition singleton is retained.
Up to eight visible layers are recorded; overflow or inconsistent composition
headers clears completeness. Queued-buffer identity does not establish changing
pixels, a retired guest simulation step, or any specific guest clock.

The 128-row, fixed-size value ledger reserves a pending record immediately
before queue present, with the exact timestamp passed to
`VK_GOOGLE_display_timing`. Finalization records the actual return code.
`MATCH_ACCEPTED` means queue submission was accepted, not physically displayed.
All ledger reads/writes use `try_lock`; contention drops diagnostic coverage,
never blocks the renderer. No allocation, readback, logging or filesystem work
is added to lookup. Session/surface/swapchain epochs invalidate old entries;
timestamp collisions and nonmonotonic submission keys remain ambiguous.

The optional C ABI provides `lucent_native_adapter_source_image_binding_v1`
and `lucent_native_adapter_query_source_image_v1`, with fixed-width, versioned
records. Native host resolves symbols once and checks size, version and exact
keys. JNI copies through an aligned local value into caller-preallocated direct
buffers. Java query uses a nonblocking read lease; teardown closes admission
before waiting for the short native copy, preventing a query into an unloaded
adapter. Older adapters without these exports remain unsupported.

Canonical and installation sources:

- `engines/patches/eden-lucent-source-image.h` — actual compiled ledger helper.
- `unified-android/native/include/lucent_native_source_image.h` — C ABI, copied
  to Eden `src/common/lucent_source_image_types.h`.
- `engines/patches/eden-lucent-adapter.cpp` — lifecycle epochs and optional exports.
- `engines/patches/eden-lucent-clock.patch` — combined tracked Eden timing,
  per-image propagation and reviewed surface-lifecycle changes.
- `engines/tools/apply_eden_timing_patch.py` — verifies that patch plus exact
  canonical helper/TU copies; `--apply` restores only this explicitly scoped set.
- `unified-android/native/lucent_native_adapter_host.c` and
  `lucent_native_adapter_jni.c` — optional host/JNI bridges.
- `unified-android/src/com/thorium/preview/NativeAdapterHost.java` and
  `game/NativeAdapterEngineSession.java` — leased direct-buffer query endpoint.

## Tests and next consumer integration

`python3 -m unittest tools.tests.test_phase3_eden_source_image_join` compiles
the actual C++ ledger and C host with dynamic mock adapters. It covers full
value copies, holds/multiple layers, overflow, exact timestamp misses,
pending/accepted/rejected/ambiguous results, eviction, lifecycle invalidation,
concurrent readers/writers, missing/malformed optional hooks and source wiring.
These are host contracts, not Android/Vulkan empirical proof.

The platform-neutral `NativeSourceImage` Java parser validates the actual C ABI
without per-frame allocation and seals private preallocated value slots until
explicit owner release. Pure pair checks distinguish original queue adjacency,
holds, gaps, epochs, complete single non-overlay layers and geometry changes.
`tools.tests.test_native_source_image_java` compiles the Java test against bytes
emitted by the actual C header, including fixed-size and offset assertions.
These checks establish queue-provenance compatibility only, never interpolation
permission. Extended Eden swap-interval speed modes remain unqualified by this
initial helper subset.

The renderer does not yet call this endpoint after `updateTexImage`, retain
pending candidates or attach the result to the consumed endpoint bytes.
Implement that bounded consumer join next; never match by nearest timestamp or
callback wall time. Prove exact distinguishable image-to-timestamp association
on the real driver, including coalesced callbacks, holds and surface recreation.
Then capture the actual retained images with those same records. The native
capability remains clock/submission diagnostics only (flags 3); no
`AUTHORITATIVE_SOURCE_TIMELINE` bit has been enabled.

Separate remaining gates: actual guest-time and audio progression, physical
presentation intervals, useful exact midpoint quality, overload behavior and
OLED-safe lifecycle. All system acceptance status remains UNVERIFIED.

## Rebuild boundary

First run `python3 engines/tools/apply_eden_timing_patch.py` (read-only check).
Then, only in the declared build window:

```sh
ninja -C engines/build/switch-src/eden/build-android -j6 yuzu-android
```

The broad `FramebufferConfig` value change legitimately rebuilds dependent
video/core objects. Do not reuse the previously stripped library or claim the
cached artifact contains the new exports. After completion strip into an
isolated temporary location, inspect the ELF/required exports and hash, then
stage and update the source-lock/artifact test pin together. This boundary has
now been performed for the artifact above; the historical first timing-build
evidence remains unchanged. Rebuild the APK before any device claim; old APKs
do not acquire a staged native-library update automatically.
