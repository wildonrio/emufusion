# Eden consumed-image and guest-clock plan — 2026-09-04

Status: **consumed-image → classified/FIFO/history/export provenance implemented
and sampled on device; guest-clock/audio and generated-image qualification remain
incomplete; NOT qualified**. This preserves the
next Switch work after the current transport/lifecycle failures. The
[goal contract](FRAME-GENERATION-GOAL-2026-09-04.md) remains authoritative.
All system acceptance statuses remain UNVERIFIED.

## Existing foundation, not a completed join

Eden now copies value-owned queue/composition metadata from BufferItem through
HwcLayer, FramebufferConfig, asynchronous Composite and Frame to Vulkan present.
Its bounded sideband ledger uses the exact desired-present timestamp. Native
queries and a compiled pure Java parser exist. The renderer now carries those
records from its exact consumed image through retained signature candidates into
the classified candidate and FIFO/history/export records. The 3f121 title run
observes retained original queue gaps and exact timestamp joins without sampled
metadata failures. Its separate gameplay run reaches controllable gameplay but
fails pacing and produces zero generated frames. No authoritative-producer flag
is enabled. That is historical evidence, not the latest build. The
[current 09dd checkpoint](qa/frame-generation-v2-switch-09dd-2026-09-05/README.md)
retains the same staged Eden adapter. Live prediction planning, GPU-queued real
proof and immediate ready-frame compositor dispatch are implemented. Exact startup
joins confirm the removed callback handoff delay, but 09dd gameplay still fails:
unequal sampled physical intervals and G=0 throughout. Right/left movement was
observed. Remaining admission counters distinguish GPU-pending, absent pair and
import ownership; they do not yet separate GPU workload from delayed observation.
Source/consumed-image canonical timing, audio/guest-clock and generated-image
verification remain incomplete. All 19 systems are unverified, no producer-authority
flag is enabled, and both OLED panels were verified OFF after bounded testing.

Sources:

- [C ABI](../unified-android/native/include/lucent_native_source_image.h): version 1,
  808-byte image record, 64-byte binding, eight-layer maximum, 128 ledger rows;
  explicit accepted/pending/busy/missing/ambiguous/rejected states.
- [Canonical helper](../engines/patches/eden-lucent-source-image.h),
  [combined patch](../engines/patches/eden-lucent-clock.patch) and
  [reproduction tool](../engines/tools/apply_eden_timing_patch.py).
- [NativeSourceImage](../unified-android/src/com/thorium/lucent/video/NativeSourceImage.java):
  setup-allocated sealed snapshots and exact-pair compatibility checks. An accepted
  row proves queued-image provenance, not changed pixels, guest progress or scanout.
- [Source checkpoint](EDEN-SOURCE-IMAGE-JOIN-CHECKPOINT-2026-09-04.md) and
  [artifact evidence](EDEN-SOURCE-IMAGE-LIFECYCLE-BUILD-2026-09-04.json).

The [b14 retest](qa/frame-generation-v2-switch-retest-2026-09-04/README.md) is a
limited Off lifecycle smoke and failed LSFG run, not cadence/image qualification.
It produced no generated-image triplets. Runtime error reporting and retirement
fixes are separate work, not proof of this image/clock contract.

### Earlier September 4 foundation checkpoint (historical)

[NativeSourceImageLedger](../unified-android/src/com/thorium/lucent/video/NativeSourceImageLedger.java)
and Slot.copyFrom/moveFrom/clear now exist as an **unwired pure-Java foundation**.
The fixed-capacity ledger preserves exact raw PTS, provider generation, expected
session/surface epochs, decode status and sealed original queue records.
Per-occupancy monotonic leases reject stale release/copy/move after index reuse;
occupied destinations never overwrite, and failed moves preserve the source.
Establish destination image ownership while retaining the source, commit metadata,
then retire the source image only on successful move. The helper owns no GPU images.

PENDING/BUSY/error observations are immutable one-shot records without accepted
snapshots. There is deliberately no query/retry loop, nearest timestamp lookup,
renderer/session wiring, clock-policy change or source authority. The planned
two-candidate/age-bounded retry remains unimplemented. Host tests execute actual
production methods, including zero warmed-up hot-path allocation accounting; they
do not qualify device image ownership, clocks, scanout or generation.

### Later September 4 used-renderer checkpoint

`NativeSourceImageProvider` is pinned to one exact `NativeAdapterHost` and attached
only to the registered renderer for the session's exact input Surface. Off has no
registered frame generator and creates no provider or observer. The renderer lazily
constructs `NativeSourceImageObserver` on its owner thread. Binding plus image query
are one-shot/nonblocking through the host lifetime lease; a nonpositive raw consumed
PTS causes no native query. Software uploads explicitly record missing native PTS.

The observer follows latest → retained signature candidate → classified candidate,
including delayed asynchronous results. It validates binding/query swapchain epoch
as well as exact timestamp/session/surface, preserves immutable failures, and counts
held/adjacent/gap records separately from pixel verdicts. First-image bootstrap and
blind GL fallback are **pixel unknown**, not proof of a changing image. Provider
replacement, texture allocation/resize and close invalidate metadata; lifetime
counters survive resets. Periodic logs explicitly say `authority=false`.

Host tests execute the actual attachment and renderer methods with controlled
platform leaves, plus the actual parser/ledger/observer and zero warmed-up allocation
checks. These are not hardware ownership or quality proof. No clock, generation
policy, guest speed, aspect or strict-Off route was changed by this integration.
The map below remains incomplete after classification; no A/G/B provenance or
guest-clock/audio authority can be inferred from the observer.

The [aa09 hardware retest](qa/frame-generation-v2-switch-aa09-2026-09-04/README.md)
fixes the previously stale Java host capacity guard and observes accepted exact
native/classified records. It still generates zero frames and exposes duplicate
physical-slot admission across a phase reanchor. All acceptance statuses remain
UNVERIFIED; this runtime evidence advances only the narrow metadata join.

Earlier transport checkpoint: the
[5075 retest](qa/frame-generation-v2-switch-5075-2026-09-05/README.md)
includes the aa79 duplicate-slot guard and private real-pair copy/proof readiness
before visible activation. Its focused regressions pass, but the title-only run
fails with `LSFG endpoint pool is full` and zero generated presentations. Resolve
that image-lease/admission failure before further device qualification. None of
this supplies the downstream source retention, guest-clock or audio authority
still required below.

Earlier: the [46a0 retest](qa/frame-generation-v2-switch-46a0-2026-09-05/README.md)
shortens original carrier retention to all matching exact source-copy fences, while
preserving fixed-output proof/presentation leases, and counts/refuses full-pool
admission before any image export. The title pool failure did not recur; gameplay
was reached with zero observed capacity rejections. The run still generated zero
frames and failed at request3742 when SurfaceControl omitted its present fence.
The measured apply call crossed its token deadline. Investigate that physical
submission boundary next. These transport changes supply none of the downstream
guest-clock/audio or source-authority proof required by this plan.

Earlier: the [2ffe retest](qa/frame-generation-v2-switch-2ffe-2026-09-05/README.md)
keeps prompt immutable-target submission. Request5516 nevertheless has no physical
fence, despite a463us apply ending20.455ms before its deadline. The generic
timestamp predicate did not fail in this run. All188 health snapshots show zero
generated; compositor gameplay intervals remain uneven. Commit observations and
eventually a joined compositor/drop trace are needed to discriminate the cause.
The separate asynchronous latch-order correction has a controlled red/green test;
it is not a demonstrated remedy for the missing fence.

Follow-on app source now copies the full classified observation before
`finishClassified()` clears it, through actual admission/FIFO/history/rotation and
exact expected/retained LSFG carrier ownership. Fixed ledgers preserve original
query status, pixel verdict, raw PTS, provider/epoch identity and queue gaps;
classified/export timestamp joins are separate observations, not rewritten source
facts. Actual-method host tests and independent review cover these paths, but no
runtime capture yet proves this new metadata follows real generated A/G/B frames.
Earlier: the [4af5 retest](qa/frame-generation-v2-switch-4af5-2026-09-05/README.md)
samples that retention at runtime: 38 snapshots, no observed missing/copy/mismatch
errors, 14 original queue-gap pairs and 3 adjacent pairs. The other 21 snapshots
have absent/reset sides; transport coverage does not imply accepted provenance.
The title run crashes in EGL makeCurrent during endpoint export before gameplay,
with zero generated frames. Latest: [3f121](qa/frame-generation-v2-switch-3f121-2026-09-05/README.md)
removes steady-state LSFG EGL switching and preserves native in-flight ownership
on exceptions. Its title run has 231 provenance snapshots without sampled
metadata errors; two PENDING observations remain PENDING through classification,
but their export is not established by periodic active-pair snapshots. The separate
gameplay run reaches movement, has nonuniform physical intervals and zero generated
frames. Neither bounded run repeats the EGL crash or missing-fence diagnostic;
that does not establish permanent remedies. Per-image epoch joins and guest/audio
proof remain unverified. No source-authority or cadence-policy branch was changed. The source-cadence
gate currently yields zero candidates, before LSFG priming. Stable renderer PTS
alone could satisfy its existing heuristic; that is not guest-clock/audio proof.
Do not turn on the native authority flag to bypass it. AI work inside the Eden
checkout trees remains pending an explicit policy clarification; none was performed.

## Exact consumed-image integration map

Attach a separate **diagnostic** source-image provider, pinned to the active
NativeAdapterHost plus local provider generation, where
[NativeAdapterEngineSession.publishProducerTiming](../unified-android/src/com/thorium/preview/game/NativeAdapterEngineSession.java)
already finds the renderer by its exact input Surface (around line 395).
Do not grant authority through setProducerTimelineHz/setSlotLatticeProducer.
Existing sourceImageBinding/querySourceImage methods use a nonblocking host
lifetime lease; no native pointer may escape.

All renderer locations below are in
[DisplayFrameGenerator](../unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java).
Method names are durable anchors; lines describe this audit snapshot.

| Stage | Required identity/ownership |
| --- | --- |
| onFrameAvailable, ~2458 | After updateTexImage, getTimestamp, transform acquisition and copyExternalTo(latestTexture), query the **raw positive consumed buffer timestamp** before classification. The current missing-PTS arrival-time fallback must never become a metadata key or cadence proof. |
| retainSignatureCandidate, ~4077 | Retain metadata/status with the exact copied 2D candidate, not one mutable “latest metadata” field. Integrate the now-tested snapshot/ledger copy/move APIs; never overwrite occupied sealed slots. |
| latestImageIsUnique completedCandidate, ~3842 | An asynchronous result belongs to the earlier candidate. Move that candidate's metadata with classifiedUniqueTexture/timestamp/submission, not the callback completing the query. |
| consumeClassifiedFrame / acceptPresentationEndpoint, ~3756 / ~4163 | Carry that record through admission and every FIFO slot. Preserve original queue_frame_number separately from host endpointSequence/uniqueSequence, which renumber accepted frames. |
| consumeEndpointIntoHistory, ~4366 | Move FIFO metadata with the copied history texture into the exact active left/right endpoint. Release slots only after their image is no longer usable. |
| Active right-to-left rotation, ~4753 | Rotate metadata, texture, timestamp, host handle and original queue identity together. Invalidate on eviction, discontinuity, resize, provider replacement, pause/rebind and session/surface/swapchain epoch changes. |
| External export / triplet capture | Map transport endpoint handles to those exact retained source records and captured bytes. A host sequence is not a guest queue identity. |

Use setup-allocated direct query buffers and fixed snapshot slots. Pending/busy
queries may retry only while the **same retained image and exact key** survive:
at most two pending candidates and a finite declared scan-age limit on existing
render ticks. Never wait on the producer thread, query a nearest timestamp,
overwrite a pending image, allocate per frame or retry indefinitely. Expiry and
pressure mean missing evidence. Presentation must not wait for an observer query.

Count query/decode/pair rejections, pending age, eviction, epoch changes and missing
raw PTS; include provider/native epochs and workload identity. Preserve cumulative
run failures across presentation resets.

Observe only first. A future eligible pair requires accepted exact records,
complete composition, one visible non-overlay layer in the initial subset,
NativeSourceImage.compare == ADJACENT_QUEUED_IMAGES, consecutive original frames,
stable epochs/queue/crop/transform/geometry/swap semantics, independent changed-pixel
and scene-quality evidence, and separately verified clock/physical contracts.
Held queue identity is not a new endpoint and must not generate a midpoint.
Multilayer, overlays, extended raw swap modes and unknown geometry remain explicitly
unsupported initially. The current signatureReadbackSafe == false fallback can
return “unique” without a pixel test; it is not changed-pixel evidence.

## Missing guest-clock and audio proof

The [adapter setter](../engines/patches/eden-lucent-adapter.cpp), around line 910,
delegates to SetPacedVsyncHz. Conductor.GetFramePeriodNs/GetNextTicks use that value
for VI composition scheduling. Preserving swap_interval is necessary, but a
VI-only scheduling change does not prove whole-game/audio reclocking.

In the built Eden checkout, src/core/core_timing.cpp:GetClockTicks (~230) reads
wall CNTPCT in multicore mode with existing CPU/speed-limit semantics;
GetGlobalTimeNs (~319) also reads host wall time. Neither is a retired guest-work
counter. The adapter audio pump (~175 and ~296) consumes fixed 48 kHz blocks on its
own wall schedule and can emit silence/drop late backlog. Counting output blocks
therefore does not establish actual guest audio progress.

Before enabling whole-game trim, implement and test:

- Queue-accept monotonic observations tied to original BufferItem identity,
  explicit guest-visible counter domain/frequency, and an independently meaningful
  retired guest-progress observable. Never label host wall time as retired work.
- Actual processed VI scheduled timestamp, event identity, lateness and coalesced
  count. Conductor's multicore signal/wait before ProcessVsync currently does not
  retain a record for every individual scheduled callback.
- Clock-configuration/trim epoch and effective readback scale: which guest
  clocks/timers change, and how pause/resume rebases them.
- Actual guest audio samples consumed versus silence, underruns, dropped samples
  and queued depth, joined to AudioTrack hardware timestamps. A permitted speed
  change must be consistent in audio without concealing drift or damage.
- Final composed output dimensions/transform and host geometry epoch, to bind the
  captured endpoint to preserved game aspect ratio.

Observe unmodified clocks first. Choose and implement a real correction mechanism
only after establishing multicore, guest timer, VI and audio semantics. New
timestamp labels are not a substitute.

## Rate relationship and safe adaptation

Use original core clock C, true changing-image cadence F, speed correction r,
measured physical panel rate R, multiplier m in {1,2}, and integer scans/output n:

```text
C' = r C       F' = r F       O = m F'       R = n O
r = R / (n m F), only when F's relation to C is established
abs(r - 1) <= 0.0075, relative to ORIGINAL C
```

A 20 FPS game on a 60 Hz core retains a near-60 Hz core; do not set C' to 20.
At 120 Hz, 20→40 uses three scans/output, 30→60 uses two, and 60→120 uses one.
40→80 cannot be uniform on 120 Hz: preserve 40 direct with three scans instead
of underclocking to 30. Equal scan holds are not synthetic frames. Permit only
one useful midpoint between adjacent changing endpoints.

Measure a stable physical baseline and verify scan counts; a mode vote or first
nominal timestamp row is insufficient. PhysicalPresentationClock.available()
alone does not establish that baseline. Use rational/accumulated deadlines,
phase-error measurements, bounded correction and hysteresis. Under overload,
preserve guest speed and withdraw unsafe generation; never reinterpret low
throughput as a lower nominal guest clock.

## Implementation and acceptance sequence

1. **Off observer, no authority:** retain strict Off's direct engine Surface and
   zero frame-generator construction. Add opt-in native observations without
   inserting an intermediate renderer/SurfaceTexture. Native submission records
   alone are not consumed-image or physical-present joins.
2. **Consumed-image observer in existing generated routes:** implement the exact
   retention map with no timing/generation/clock-policy change. Test pending,
   busy, expiry, late classification, held frames, original-frame gaps, multilayer,
   geometry and ownership epochs before device testing.
3. **Clock/audio observation:** establish the missing observables and long-run
   baseline. Prove C→F relationships without equating submission, callbacks,
   changed pixels, physical presents or guest progress.
4. **Near-native correction:** implement only a measured bounded change that
   reaches relevant guest clocks/audio. Verify readback, phase, speed preservation
   under overload and lifecycle resets. A successful setter grants no authority.
5. **Exact 2× qualification:** join captured A/G/B bytes/provenance to physical
   completion; compare with held-out true middle frames and copy/blend baselines,
   including HUD/local damage, motion and occlusions. Independently verify scan
   intervals, guest/audio progress, adaptation, aspect and OLED lifecycle.
   Missing/ambiguous joins remain unqualified.

Existing isolated host regressions:

```sh
python3 -m unittest tools.tests.test_phase3_eden_source_image_join tools.tests.test_native_source_image_java tools.tests.test_native_source_image_ledger tools.tests.test_phase3_eden_core_timing
```

Add tests for the **used renderer retention path**, not just an unused parser.
Reproduce cached Eden source through apply_eden_timing_patch.py and record source,
helper, ABI and artifact hashes before an authorized rebuild/staging. Do not claim
PASS from host tests, a build, submission FPS, endpoint screenshots, startup
self-tests or historical summaries. Keep panels black outside bounded device tests.
