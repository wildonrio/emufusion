# RIFE N64 Ocarina live-integration STOP — 2026-08-24

## Scope and verdict

This checkpoint follows the adjusted authoritative frame-generation goal after
the bounded LSFG feasibility STOP. It tests only the lawful, GPU-resident RIFE
qualification backend on the Thor top panel. It does **not** promote RIFE into
normal product routing.

Verdict: **STOP / unqualified**. The isolated zero-copy/cached RIFE benchmark
remains useful, but the live common endpoint/presentation integration has not
yet reached gameplay-quality or cadence evidence.

## Host correction retained

The common `DisplayFrameGenerator` could materialize an exact adjacent pair in
its internal FIFO one callback before the asynchronous external transport's
ImageReader owned the corresponding two HardwareBuffers. The old path then
allowed controller selection and failed inside `presentExternalBuffered()`.

The retained fix waits before scheduler selection until all of the following
are true:

- an active left endpoint exists;
- the right endpoint is exactly `left + 1`;
- the external transport reports ownership of that exact pair.

No controller decision or presentation counter is committed while ownership is
pending. The immutable pair is retained for a later physical callback, so the
wait cannot create a catch-up burst.

External fatal errors are now latched once. The already-posted next callback
terminates without another poll or submission, while producer buffers are
drained and discarded to avoid deadlocking the emulator behind an abandoned
Surface. This closes the prior every-vsync exception/log loop without claiming
a live fallback.

## Physical evidence

### r4 — exact pair-ownership candidate

- qualification APK:
  `lucent-3.2.16-rife-framegen-qualification-30515d02d52a1c5e0f48fd16a11dec3bd8c8ad4b711fc07dc798b9f6e119bbb7.apk`
- logcat:
  `.evidence-rife-oot-r4-pair-ownership-logcat.txt`
- log SHA-256:
  `3395312083014343c9f4bb2971c216e638ef0382783fa6af88d2416b526080e3`

The original missing-pair exception did not recur. The next live blocker was:

```text
RIFE endpoint transport failed
Caused by: RIFE Image timestamp does not match announced endpoint
```

The transport failed closed before any generated output could qualify. That
record did not include the actual and expected timestamp values, so it cannot
distinguish a Thor/BufferQueue timestamp rewrite from a lost/reordered buffer.
Relaxing equality without proving ordered one-to-one ownership is forbidden.

### r5 — diagnostic/fatal-latch candidate

- qualification APK:
  `lucent-3.2.16-rife-framegen-qualification-a783c0c04fd4fc1b8667ca873c1309b19ddba4e59ec51eb8751af493bfd36d39.apk`
- logcat:
  `.evidence-rife-oot-r5-timestamp-diagnostic-logcat.txt`
- log SHA-256:
  `9beafb453941a100f59c2755ea7aca11bd1d2badf5ee4af212062bbb16061871`

The exact timestamp diagnostic and one-shot fatal latch were present. This run
failed even earlier, before the timestamp condition was reached:

```text
Frame generator attached ... externalTransport=1 displayHz=120.00001
RIFE qualification transport active; product backend assessment remains unqualified
External presentation session failed closed
Caused by: external presentation has no exact panel divisor
```

The controller selected a startup REAL before its measured uniform panel plan
had committed a positive `panelScansPerOutput`. `presentExternalBuffered()`
correctly rejected that request. The one-shot latch worked: the fatal transport
condition did not produce the earlier per-scan exception flood.

No RIFE interpolation image, physical cadence segment, or moving-quality result
was accepted in either run.

### r6 — measured-panel pre-prime candidate

- qualification APK SHA-256:
  `1ecf2706867c2e0bd9cec3a82c3f769308677678b44cdb1bd70369ae1f6d7bb5`
- logcat:
  `.evidence-rife-oot-r6-panel-prime-logcat.txt`
- log SHA-256:
  `9176d71cf49cb0cf451a2efe804fcfc21ae30071acfa03cd2cf80724a1880e5e`

The measured-panel gate worked. The generator attached at 21:47:31.601 and
did not submit while its panel divisor was provisional. At 21:47:33.605 it
committed the physical panel clock as 120 Hz from 240 samples.

The next request still came from the game's transient 60 Hz startup path. The
first native submission then spent roughly 122 ms creating/importing the live
endpoint Vulkan objects before returning `NOT_READY`; the one-scan physical
deadline was already lost:

```text
21:47:33.838 Frame rate committed source=60.0 target=120.000
21:47:33.890..33.959 Adreno Vulkan image-view/sampler setup
21:47:33.960 External presentation session failed closed
Caused by: external presentation missed its one physical deadline
```

This agrees with the earlier isolated cold-import evidence (`89.648125 ms`)
and is not an inference-threshold problem. `RIFE::load()` already creates the
ncnn model pipelines and uploads their weights during
`RifeQualificationRuntime.open()`. The deferred work is tied to the actual
gameplay `AHardwareBuffer` objects: external-memory import state, image views,
samplers, and per-buffer import pipelines are first created inside
`nativeEnqueueHardwareBufferRifePresentation()`.

The source now also has a host-tested, qualification-only rate-path gate:
RIFE and the bounded LSFG arm advertise only 20->40, and the common presenter
does not select them during a 60->120 startup/menu transient. That correction
has not been represented as a physical pass.

### r7 — asynchronous endpoint-import candidate; Direct-fallback STOP

- qualification APK SHA-256:
  `a8a93ec7c0a44d49dfaf099f53cddb1b1fd5eda392a15c811c9966a46082e3b9`
- complete logcat:
  `.evidence-rife-oot-r7-async-import-logcat.txt`
- logcat SHA-256:
  `c0c8b862a16d2bf6163c3d71c09f045231242606bc67b0e852fd0bdfda835681`
- harness result:
  `.evidence-rife-oot-r7-async-import/results.json`

This run does **not** test Ocarina or the new import worker. The phase-one
library harness selected its first alphabetical private N64 title, 007: The
World Is Not Enough, whose timestamp authority settled at 30.000 Hz. The RIFE
qualification transport truthfully authorizes only 20->40, so no endpoint was
published to RIFE and no preparation/import log exists. The transport never
submitted a presentation:

```text
Frame generator attached ... externalTransport=1
Physical panel clock committed ... measuredHz=119.940464 samples=240
Frame rate committed source=30.0 target=59.970
App swap cadence ... swap=0.000 ... externalSubmitted=0
Presentation stalled ... presents=0 ... pairReady=false
```

The exact failure is the common backend-routing architecture. The external
transport takes exclusive ownership of the output Surface before the source
rate is known. When the per-rate gate rejects 30->60, `doFrame()` returns
without either invoking RIFE or presenting Direct. The game therefore remains
black, and the harness times out waiting for a nonblack core frame. A correct
per-path refusal became a visible-output failure, violating the required
qualified-backend -> Direct fallback contract.

The following two harness rows are not independent backend evidence. After the
first timeout the harness relaunched the frontend while the old preview/game
activity still existed, then observed two live `MainActivity` records. The
13,336 subsequent Adreno `DequeueBuffer failed` messages begin when that old
`SurfaceView` reports `BufferQueue has no connected producer` / `has been
abandoned`; they are teardown contamination, not RIFE inference timing.

The asynchronous-import implementation remains host-valid but physically
unexercised. It cannot be called a success or failure from r7.

## Source-proven architecture blocker

Another physical retry is not justified by the rate-path gate alone. The
external transport takes ownership of the output Surface before a sustainable
source path is known, yet actual endpoint buffers are not imported/prepared
until a live presentation request. While an unsupported startup rate is held,
the transport also continues receiving endpoint Images; its bounded pool can
fill because no external presentation advances/reclaims them.

A defensible next RIFE design is therefore materially larger than another
deadline tweak:

1. keep Direct presentation active while source and panel timing settle;
2. stage each exact retained endpoint into the Vulkan import cache outside the
   presentation callback, without blocking the renderer thread;
3. run a bounded GPU-resident RIFE self-test on an exact adjacent pair and poll
   completion with zero-timeout checks;
4. select RIFE only at a clean session/presentation boundary after that test;
5. retain Direct if staging, self-test, timestamp identity, or deadline proof
   fails.

The cached 160x90 evidence remains encouraging but narrow: paired CPU enqueue
plus GPU work was 8.114 ms p95 against one 8.333 ms panel scan, leaving only
0.219 ms before scheduling/compositor variance. It cannot excuse cold work in
the live interval and it is not moving-game qualification.

## Next bounded material step

Do not change RIFE inference thresholds, visual gates, or the physical deadline.
Do not run another RIFE device attempt until the common backend router keeps a
visible Direct path through unsupported rates, preflight, and backend failure.
Opening a shell-only external transport must never turn an unqualified rate
into a black surface. RIFE remains STOPPED while LSFG, the goal's primary
backend, receives the first implementation of that shared routing contract.

After Direct fallback is real, a RIFE session must remain pre-prime until all
of the following are true:

1. the measured uniform panel plan has a positive integer scan divisor; and
2. the sustainable path is the backend's exact qualified 20->40 path;
3. the external transport owns and has pre-imported the exact adjacent pair;
4. its bounded GPU self-test has completed successfully.

Then use the existing expected/actual timestamp diagnostic to decide the buffer
association contract:

- exact timestamps equal: retain the current strict binding and investigate any
  queue loss/order defect;
- timestamps differ but BufferQueue FIFO ownership is independently proven
  one-to-one with no drop: preserve EmuFusion's immutable timestamp as the
  authority and treat ImageReader time only as a diagnostic;
- any ambiguity/drop/reorder: RIFE remains unsuitable for live routing.

This is now a backend-routing plus preflight/ownership milestone, not a minor
retry.
If it is not implemented as one bounded arm, preserve this STOP and proceed to
the next lawful backend or a materially different built-in estimator. Do not
spend repeated device cycles on the present deferred-import architecture.

## Frozen source/test identities

```text
fc69ceddeaf32c5b14fac9eead4ff77aa75f60d7d94d6960ecc730677c86fd22  unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java
ccce82e1d20779cc2553df8babf755bc92197a872d910aece41df3c68d6f4707  unified-android/src/com/thorium/preview/game/ExternalFrameGenerationTransport.java
0b9e22501d10177c2204dadbe4fe3225da825cbb427aa63f12f074c33d1c7eae  unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java
d379d5171f6a86b70fa043bc4d2d2bc34fc3c87619e4eac87d8900774b48c74d  unified-android/qualification-src/com/thorium/preview/game/LsfgPresentationTransport.java
379f5ea45d36981dedf263613a2cba94b42017a36e43706b9c506bf3b6185cbe  tools/tests/test_systemwide_frame_generation.py
7e0c85900bcc13d101bf928b42f8c04555c1f92d9988eb7f2617ae0294dc3216  tools/tests/test_rife_framegen_qualification_packaging.py
4347ffbddfe4811759efe416c9877f0b9f576578ba0676de06c975561e373d20  tools/tests/test_lsfg_framegen_qualification_packaging.py
```

Host gates on those bytes:

- focused system-wide/RIFE/LSFG packaging tests: 76/76 PASS on the final
  rate-path-gated source;
- the preceding r6 source also passed the unified Android Java suite and the
  full notice-complete RIFE qualification APK build.

The later r7 async-import candidate was built and host-tested on these exact
bytes (it is intentionally not a physical pass):

```text
f82733c929bac07e5b41a94f0a9e594494bca91bae332937bf902c835a1ed3ef  unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java
ccce82e1d20779cc2553df8babf755bc92197a872d910aece41df3c68d6f4707  unified-android/src/com/thorium/preview/game/ExternalFrameGenerationTransport.java
a22a5d2fda1da80c9a727f5ece1b2846ccd6adf7608d57ad3e9847ced8f06bd5  unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java
145e1deb53a6ee7c62b3837efd8a635a73425f3dbf6821b9bed8bde273463237  experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/main/java/com/emufusion/rifebenchmark/NativeRifeBridge.java
cd16735cd2dba147392cace4bb67df4edde7791637837357709143ee135563ca  experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/main/cpp/rife_benchmark_jni.cpp
bc9623576c20f11077aa213a018340c8eb00d25fb5a1d3d7d2775aa0a4c7cb37  tools/tests/test_systemwide_frame_generation.py
602df411f8955ea16872f5baabf08a95ce8f0d3e2417f0c6784a44c4e4a3e6f1  tools/tests/test_rife_framegen_qualification_packaging.py
```

Those bytes passed the focused system-wide/RIFE/LSFG packaging suite (76/76),
the unified Android host suite, and the full RIFE qualification APK build.

## Device restoration

After r7:

- `com.thorium.preview` force-stopped;
- RIFE, LSFG, and proof globals removed;
- pre-existing dense globals restored (`dense_pyramid=1`, `dense_v28_160=1`);
- brightness restored to 7, manual mode 0;
- Thor verified `Asleep`.
