# Proposed Switch source-image join — 2026-09-04

Proposal only. No production, staged library, or source-lock changes accompany
this document. The packaged Off baseline must remain unchanged until the root
agent grants the next source integration window. All authority/quality status
remains UNVERIFIED; no `AUTHORITATIVE_SOURCE_TIMELINE` bit is enabled here.

The proposal above is historical. See the [source implementation checkpoint](EDEN-SOURCE-IMAGE-JOIN-CHECKPOINT-2026-09-04.md)
for the subsequently authorized source-only implementation and remaining gates.

## Finding and practical join key

`BufferQueueProducer::QueueBuffer` assigns `BufferItem.frame_number` from the
producer queue's frame counter (`src/core/hle/service/nvnflinger/buffer_queue_producer.cpp:487`).
This is a queued-buffer identity, not a retired game simulation step. Its raw
`timestamp` comes from guest input and may be automatic or unspecified; preserve
that value and its flag without claiming it is Android monotonic time.

The compositor observes acquired versus reused items, but `HwcLayer` currently
drops identity. The GPU's existing `RequestComposite` captures its
`FramebufferConfig` vector by value, including into asynchronous acquire-fence
callbacks. Extending that value payload avoids a new asynchronous metadata
channel between VI and the renderer.

For the final producer-to-host join, use the exact timestamp of the consumed
buffer, not callback time or nearest timestamp. Android explicitly documents
that a Vulkan producer's `SurfaceTexture.getTimestamp()` returns its
`VK_GOOGLE_display_timing` desired present time. The current Eden timestamp is
actual monotonic submission time, not a fabricated cadence grid.
[Android SurfaceTexture reference](https://developer.android.com/reference/android/graphics/SurfaceTexture#getTimestamp())

Vulkan's desired time is only the earliest requested display time; it does not
prove physical presentation. `presentID` separately identifies presentation
timing results and is not exposed by the Java SurfaceTexture interface.
[Khronos VkPresentTimeGOOGLE reference](https://docs.vulkan.org/refpages/latest/refpages/source/VkPresentTimeGOOGLE.html)

Proposed lookup key: `{adapterSessionEpoch, sourceSurfaceEpoch, exactBufferTimestampNs}`.
`sourceSurfaceEpoch` names the specific host producer surface binding, not just
display 0 or an Android native pointer. A swapchain generation is also recorded
and splits all source-pair continuity. No comparison across surfaces/sessions.

## Minimal value payload and interfaces

Names below are proposed; final ABI layout should be a fixed-size, versioned C
record with explicit integer widths and no pointers or STL members.

`LayerSourceV1`:

- Queue-lifetime epoch, consumer ID, original queue frame number and slot.
- Raw guest timestamp and `is_auto_timestamp`; timestamp domain is
  `guest_requested_unspecified`, not `android_monotonic`.
- Raw and normalized swap interval; composition speed scale remains separate.
- Acquired-new versus held/reused; overlay and visibility flags; z order.
- Crop, transform, pixel format and dimensions to detect geometry changes.
- Optional actual host queue-observation time, captured when QueueBuffer accepts
  the item. It describes queue submission, not pixel readiness or guest clock.

`CompositionSourceV1`:

- Adapter session, display ID, composition ordinal and host composition-observed
  time. Composition ordinal increments only when a composition is submitted.
- Up to eight visible layer records by value, with explicit count/completeness.
  If the stack exceeds eight, mark metadata unsupported instead of truncating
  it and claiming the remaining layers represent the entire image. Rendering
  continues unchanged. Never hold a `BufferItem`, layer or GraphicBuffer pointer
  merely to retain provenance.
- No single synthetic `guestFrameNumber` constructed from the composition
  ordinal. Primary and overlay layers can advance independently.

`SourceImageRecordV1` adds source-surface/swapchain epochs, actual monotonic
submission timestamp, submission ordinal, Vulkan image index and present ID,
plus state `Pending`, `Accepted`, `Rejected`, or `Ambiguous`. Vulkan success or
suboptimal means accepted queue submission; it still does not mean scanout.

Proposed optional exports:

```c
uint32_t lucent_native_adapter_query_source_image_v1(
    uint64_t adapter_session_epoch,
    uint64_t source_surface_epoch,
    uint64_t exact_buffer_timestamp_ns,
    lucent_source_image_v1 *out,
    uint32_t out_size);
```

Return codes distinguish `MATCH_ACCEPTED`, `PENDING`, `BUSY`, `NOT_FOUND`,
`AMBIGUOUS`, `REJECTED`, `UNSUPPORTED`, `CLOSED`, and `BAD_ARGUMENT`.
`struct_size` and `version` are validated before any payload copy. Missing
optional exports stay unsupported. Setup/rebind also needs an explicit
host-owned binding epoch handoff; a raw ANativeWindow address is not an epoch.

Use a 128-entry fixed ring owned by the adapter session. Both writer and reader
use `try_lock` only, copy small value records, and return immediately if busy.
Do not use an unguarded C++ seqlock over non-atomic structs: that is a data race.
No allocation, disk access, pixel readback, GPU wait or callback into Java occurs
in this ring. Counters expose skipped publication, eviction and lookup misses.

A Java renderer receives a session-scoped metadata provider only after start.
JNI copies into a preallocated output buffer rather than allocating per frame.
The provider must acquire a nonblocking session lease: unbind prevents new
queries before engine shutdown/dlclose, and teardown alone may wait for the
bounded in-flight copy to finish. A bare native host pointer read concurrently
with destroy is not acceptable.

## Source integration points

All Eden paths below are under `engines/build/switch-src/eden/src`.

1. `nvnflinger/buffer_item.h` and `display.h` under
   `core/hle/service/`: retain queue-lifetime identity. Consumer IDs alone can be
   reused. Allocate an epoch at the BufferQueue or layer's creation, not at
   every acquisition; preserve it across held items.
2. `core/hle/service/nvnflinger/hardware_composer.cpp:49`, `ComposeLocked`:
   copy each visible item's metadata while acquisition state is known and
   sort it with its HwcLayer. Preserve the existing guest swap-interval logic.
   Invisible new buffers must not imply visible-game advancement.
3. `core/hle/service/nvnflinger/hwc_layer.h:26` and
   `core/hle/service/nvdrv/devices/nvdisp_disp0.cpp:63`: copy metadata into
   `video_core/framebuffer_config.h:23`. All layers share the same composition
   envelope; reject inconsistent envelopes in the consumer helper.
4. `video_core/gpu.cpp:235`: existing moved vector and by-value callback capture
   retain the payload. No “latest composition” global or pointer into the
   original mutable layer stack. Test both no-fence and delayed-multiple-fence
   paths.
5. `video_core/renderer_vulkan/renderer_vulkan.cpp:176`: freeze the composite
   payload into `Frame` after it is acquired and before it is queued. Clear
   old metadata when a Frame is recycled. Capture-only temporary Frames remain
   unqualified and must not publish source-present entries.
6. `video_core/renderer_vulkan/vk_present_manager.cpp:491`: pass the actual
   Frame's payload into `Swapchain::Present`. The swapchain image index alone
   is a reusable slot, not source identity.
7. `video_core/renderer_vulkan/vk_swapchain.cpp:217`: reserve a `Pending` entry
   immediately before `vkQueuePresentKHR`, using the actual same timestamp
   passed to Vulkan; finalize with the returned result. Never hold the sideband
   lock across the Vulkan call. Both timestamp collisions and generation
   invalidation fail closed. Do not increment a timestamp to hide a collision.
8. `DisplayFrameGenerator.onFrameAvailable` currently obtains the exact
   `SurfaceTexture.getTimestamp()` after `updateTexImage` (around line 2428).
   Attach a copied lookup result to that retained image before classification;
   never to the next callback. Missing timestamps must not gain source authority
   through the current arrival-time diagnostic fallback.

Pending lookup can happen because Android delivers the callback before the
producer finalizes its present return value. Keep at most two immutable retained
image candidates and retry nonblocking on an existing renderer tick. Do not
block the producer or re-query against a different `updateTexImage` result.
Expiry or retention pressure makes that interval unqualified, with a counted
reason; no nearest-row substitute and no invented guest hold.

## Failure and content semantics

- Same queued-buffer identity reused across VI/compositor callbacks is held
  content. Do not increment its guest sequence or generate between equal IDs.
- New queue frame numbers can still contain duplicate pixels. Keep existing
  image-change/scene safety checks; metadata proves provenance, not usefulness.
- A jump in a producer queue's original frame number is a dropped/skipped
  source interval, not adjacency renumbered to conceal the gap.
- Composite identity is the ordered full layer identity/geometry tuple, not a
  potentially colliding checksum. Overlay-only updates are distinct composite
  images but not main-game simulation advancement. The first qualified subset
  should require one visible non-overlay producer; mixed-layer generation needs
  a separate policy/quality gate and must not select a main layer heuristically.
- A queue replacement, geometry/crop change, display move, surface rebind or
  swapchain recreation invalidates interpolation adjacency. Keep metadata for
  audit only or invalidate old rows; do not bridge epochs.
- Failed presents are rejected rows. Retrying a Frame preserves its composition
  identity but uses a new actual submission timestamp/present attempt. Old rows
  cannot be relabeled successful. Coalesced SurfaceTexture updates match only
  the image actually returned, and skipped records remain skipped.
- No extension, ring collision, busy lock, dropped publication, late query,
  lifecycle closing, unknown guest timestamps or overfull layer metadata grants
  authority. Normal rendering must remain possible and its failure reason logged.

## Tests before enabling any authority

Pure helper/native tests:

1. Acquisition versus hold, overlay-only advance, multiple queues both at frame
   1, queue recreation, invisible acquisition and original queue-number gaps.
2. Full layer tuple equality, z/crop/transform changes, nine-layer overflow,
   inconsistent composition envelopes and no silent truncation/hash authority.
3. Value copy survives mutation/destruction of original containers; delayed GPU
   fence callbacks and Frame reuse cannot replace the payload with a later one.
4. Exact timestamp key only; neighboring timestamp misses, duplicate timestamp
   poisons both candidates, missing/zero timestamp and unsupported extension.
5. Pending-before-present-return, accepted/suboptimal, rejected, retry, sideband
   eviction, reader/writer contention, old surface/swapchain/session and close.
6. Bounded reader lease racing shutdown, no query into unloaded code, no lock
   held over Vulkan/Java, fixed memory and no waits/allocations in live lookup.
7. Two pending retained images, coalesced callbacks, expiry, and no metadata
   reassignment after `updateTexImage` consumes a different buffer.

Device gates (separate from these unit contracts):

- A deterministic test producer with distinguishable images and deliberately
  delayed/coalesced callbacks proves requested timestamps and exact consumed
  images join on the actual device/driver. Include surface recreation and retry.
- Real Switch gameplay logs show queue identities, composition IDs, source
  timestamp matches, holds/skips and geometry epochs across the used Vulkan path.
  Capture the retained endpoint bytes with their joined records for inspection.
- Independently measure guest-time/audio progression and physical presentation.
  Raw guest-requested timestamps or monotonic submission cadence are not enough
  to advertise a stable source-content clock. Image identity is one prerequisite,
  not proof of near-native phase lock or of a useful interpolated midpoint.

Only then consider exposing qualified source-image authority; it must remain
separate from mere presence of the sideband export. No historical average-FPS,
startup success, or source-only unit result advances the acceptance manifest.
