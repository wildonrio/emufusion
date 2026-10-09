# RIFE N64 Ocarina r105-r112 exact-target timing checkpoint — 2026-08-26

## Verdict

**r112 BOUNDED PHYSICAL TIMING PASS; r113 DURABILITY STOP; PRODUCT
QUALIFICATION REMAINS STOP.**

r112 is the first bounded integrated Ocarina run in this investigation to
pass the unchanged RIFE timing verifier after exact 20-to-40 generation became
active. It does not certify visual quality. The runtime deliberately leaves
`externalContentManualPassed=0` and `physicalQualified=0` until a long moving
gameplay capture is inspected and accepted without ghosting, warping, duplicate
images, periodic stalls, or other interpolation artifacts.

The longer r113 follow-up subsequently proved that this exact SurfaceControl
transport is not durable enough to qualify. It retained clean content and
timing evidence for 953 physical rows, then one presentation landed exactly
one Thor scan late despite the transaction having been applied roughly 20 ms
before its requested scan. The unchanged fail-closed gate disabled external
generation immediately. r112 remains valid as a short bounded result, but it
must not be interpreted as durable transport qualification.

Evidence:

```text
.evidence-rife-oot-r112-exact-target-tolerance/
APK 0d802c76405927a3f21b2c8aa3fdf78770819f4eb40d708ad554ce0aae8ba44a
```

Machine-readable verifier output:

```text
.evidence-rife-oot-r112-exact-target-tolerance/timing-report.json
```

## What r105-r111 established

The earlier arms deliberately retained the same physical-slot, cadence,
maximum-2x, content, and fallback gates:

- r105 introduced timed SurfaceControl apply rather than relying on a hint to
  reserve the target scan;
- r106-r107 made asynchronous physical drops explicit and proved that an
  insufficient timed-apply schedule fails closed instead of fabricating
  delivery;
- r108 required one refresh plus the existing 2 ms compositor reserve at
  timed-apply admission;
- r109 derived the planning lead from the measured refresh interval;
- r110 fixed bootstrap reserve and physically completed 223 submissions, but
  the predecessor frame-timeline token made 93 rows visible one scan early;
- r111 moved the transaction to the exact visible-target token. Its first two
  physical rows landed approximately 33 and 44 microseconds from that target,
  but a deterministic exact-equality check rejected the third row because the
  live Android prediction and EmuFusion's calibrated physical lattice differed
  by only a few microseconds;
- r112 retained exact-target ownership and bounded that target-identity check
  by the existing 250 microsecond frame-timeline tolerance. It did not change
  the physical-present acceptance tolerance.

This progression rejected predecessor-token early visibility instead of
loosening the gate around it.

## Frozen r112 source and host gates

```text
CompositorFrameTimeline.java
  7c2eb31dda697cb4cb4486ccd555c1d4ec8e6f5c6e9bf573e3d6e6a77c9173b9
FrameGenerationPresentationRequest.java
  c344cf299f36501a4f83926fe2404b2bb484a2b3c79b97971e2984173c6e1371
DisplayFrameGenerator.java
  badf69fda34dc3139ce2388036e08f74411ba5dfeb244d2fbd9a6e6b9f7cedda
owned_surface_control_presenter.cpp
  772da4fdcb8ca4af486b75a024dca9ca1a3ae5e49f873a85e8c253a7025a15ee
owned_surface_control_presenter.hpp
  1174239ffb3e55f1a47e2329a4f0ac47610bb96fd9388051f3056aa946827364
CompositorFrameTimelineTest.java
  a5fabb12c2cbc5ca4bfadc6486833cda8e4a63e2fe7e581b8e3156f56da993c9
FrameGenerationPresentationRequestTest.java
  6813e7866bf14e1e7d09951970e07dbf84fe1cfbe6c869f7d5166416e387d685
test_systemwide_frame_generation.py
  7ceccc93f5dc85496bf8e02d0c38dc8d2bc3c34b1fe9fba34e3fffdbe68a0cfd
r112 harness
  98bb7b5aa55b47844bfd43d47ef716554d7dc05db521ce4d563479bf396ed9e4
```

Host verification on these bytes:

- focused systemwide, RIFE timing, RIFE packaging, and LSFG packaging tests:
  100/100 PASS;
- unified Android Java suite: PASS;
- native ASan/UBSan suite: PASS;
- complete experimental-core plus RIFE qualification build: PASS;
- APK inspection: 16 internal cores including Mupen64Plus-Next, plus
  `lib/arm64-v8a/librife_benchmark.so`.

## Exact r112 physical result

The run used the packaged Mupen64Plus-Next route, Ocarina Rev 2, measured
Thor presentation fences, and bounded controller motion. The final joined
epoch reported:

```text
source=20.000
target=39.978
physical=39.995
externalTimingQualified=1
externalTimingSamples=112
externalTimingEndpoint=56
externalTimingGenerated=56
externalPhysicalEndpoint=361
externalPhysicalGenerated=56
physicalPresented=417
physicalDropped=0
physicalUnavailable=0
externalDeadlineMisses=0
externalDesiredSlotMisses=0
externalEarliestPresentMisses=0
externalEarlyPresentViolations=0
externalEarlySlotMisses=0
externalLateSlotMisses=0
externalSlotErrorMaxNs=25136
externalContentNumericPassed=1
externalContentProofs=112
externalContentEndpoints=56
externalContentGenerated=56
externalContentMovingGenerated=44
externalContentDistinctMovingGenerated=44
externalUnsafePairs=0
externalContentSceneCutRisk=0
externalContentEndpointFailures=0
```

Performance retained large 20-to-40 margin:

```text
combined p95       8,061,719 ns
combined max       8,833,855 ns
deadline budget   22,999,999 ns
```

The checked verifier result is:

```text
timingPassed=true
numericContentPassed=true
contentQualityPassed=false
qualified=false
qualificationBlockedBy="moving-game visual/content proof"
```

The repeated `RIFE compositor deadline miss evidence` diagnostic in this log
describes latch occurring after Android's composition deadline; it is not the
physical acceptance authority. The present fence is authoritative. In the
qualified 20-to-40 epoch the present-fence ledger reports zero early, late, or
desired-slot misses. The diagnostic label should be corrected separately so it
cannot be mistaken for a physical miss.

## r113 durable SurfaceControl result

Evidence:

```text
.evidence-rife-oot-r113-exact-target-visual/
moving-gameplay.mp4
```

The last complete HEALTH row before rejection still passed the numeric timing
and content verifiers:

```text
source                 20.000 Hz
target                 39.960 Hz
physical               39.977 Hz
timing samples         953 (476 endpoint + 477 generated)
moving generated       427 / 427 distinct
physical drops         0
early/late misses      0
combined p95           8,056,719 ns
combined max           8,864,166 ns
deadline budget       22,999,999 ns
```

The next generated presentation, `presentId=1098`, produced the first durable
failure:

```text
target expected       255478434180331 ns
transaction apply     255478413544155..255478413703738 ns
compositor deadline   255478423846998 ns
latch                 255478424066968 ns
physical present      255478442555613 ns
desired-slot miss     1
```

The transaction therefore completed about 20.48 ms before the requested
physical scan, and latch was only about 220 microseconds after Android's
compositor deadline, yet the present fence reported the following scan: about
8.375 ms late. This is not a RIFE compute overrun. It proves that an exact
SurfaceControl frame-timeline token remains a prediction/hint rather than a
hard reservation of the requested physical scan on Thor. The slot gate must
not be weakened.

The r113 screen recording contains the title-screen attract sequence rather
than controlled active gameplay, so it supplies no manual moving-game quality
pass. Its useful result is the longer physical-timing STOP.

## Remaining bounded work

1. Preserve both physical transport STOPs and their unchanged exact-slot gate:
   SurfaceControl failed once after 953 clean rows, while direct Vulkan failed
   frequently as described below.
2. Do not spend another device run on either transport without a source-backed
   mechanism that materially changes physical scan ownership. More queue lead,
   compute tuning, or a looser one-scan tolerance is not such a mechanism.
3. Keep the current physical timing verifier as authority and do not set the
   manual certification bit until a durable exact-slot pass and a long,
   controlled active-game visual capture both pass.
4. After Ocarina passes, repeat the same physical timing and visual procedure
   for TWINE 30-to-60 and F-Zero X 60-to-120.
5. Keep LSFG redistribution disabled until written THS permission exists.

## r114 direct Vulkan exact-content result

Evidence:

```text
.evidence-rife-oot-r114-direct-vulkan-exact-content/
```

The integrated direct Vulkan swapchain successfully initialized on the real
GameSurfaceView output Surface. The native timed-release worker and
`VK_GOOGLE_display_timing` path ran, the physical clock calibrated, and the
20 Hz Ocarina source eventually selected the supported 20-to-40 rate path.
This rules out a packaging, Vulkan-capability, or initialization failure.

The direct path nevertheless failed physical slot ownership much more often
than SurfaceControl. Before generation activated, the last complete endpoint
ledger contained:

```text
timing samples          380
desired-slot misses     110
early-slot misses        21
late-slot misses         89
deadline misses           0
GPU + enqueue p95   ~1.78 ms
presentation lead    ~13-29 ms
```

The misses were predominantly exactly one Thor scan (about 8.335 ms) away
from the requested slot. They occurred despite ample submission lead and no
hard-deadline miss, so they are not a RIFE compute overrun or a too-late queue
submission.

At the first active 20-to-40 window, one generated submission was honestly
dropped while the single visible WSI request was still pending. The first
subsequent endpoint result then landed one complete scan late and immediately
tripped the unchanged fail-closed gate:

```text
presentId       529
generated         0
phase            1.0
desired   256795869388167 ns
actual    256795877713964 ns
error          8,325,797 ns
```

No generated output qualified. The result is a transport STOP: Android's
direct app swapchain plus `VK_GOOGLE_display_timing` can express a desired
presentation time, but on this Thor path it did not reserve that physical scan.
Requesting one scan earlier would merely trade late results for early results;
accepting either adjacent scan would reintroduce the visible judder that the
exact-slot gate exists to prevent.

## r115 direct Vulkan two-time contract

Evidence:

```text
.evidence-rife-oot-r115-direct-vulkan-two-time-contract/
```

r115 restored the intended two-time request on direct Vulkan: the immutable
content timestamp remained the exact physical scan, while
`VkPresentTimeGOOGLE.desiredPresentTime` received the earlier target-minus-2-ms
driver timestamp. In the active 20-to-40 epoch, 52 endpoint rows landed on the
exact content lattice:

```text
timing samples           52
endpoint rows            52
generated rows            0
desired-slot misses       0
early/late misses         0
slot-error max      109,824 ns
```

This is a valid physical proof that the two timestamps must remain distinct.
It is not a generation qualification. The direct transport still allowed only
one visible request to be pending, and the SurfaceControl-derived planning
reserve selected an endpoint far enough ahead that it still owned the transport
when its midpoint became due. The first generated request hit
`transport-busy nativePending=1`; subsequent prepared outputs became stale one
pair behind. The measured app output therefore remained about 20 Hz.

## r116 direct next-divisor-slot result

Evidence:

```text
.evidence-rife-oot-r116-direct-vulkan-next-divisor-slot/
```

r116 split direct-W-S-I planning from SurfaceControl planning. The direct path
selected the next exact three-scan 20-to-40 output slot with an eight-millisecond
submission lead, rather than carrying SurfaceControl's more-than-30-ms reserve.
This removed the long ownership interval, but the first completed endpoint in
the active epoch was reported one physical scan early:

```text
presentId       530
generated         0
phase            1.0
content   257913659238263 ns
driver    257913657238263 ns
actual    257913650806194 ns
error         -8,432,069 ns
```

The unchanged exact-slot verifier correctly disabled generation. Two generated
requests immediately before this row were also unavailable because their
private output was still one pair stale; no generated row physically qualified.

The official `VK_GOOGLE_display_timing` contract says a nonzero desired time on
a FIFO swapchain must prevent earlier display. Thor's returned row is therefore
not permission to reinterpret `desiredPresentTime` as a best-effort hint or to
loosen the verifier. It is evidence that this particular short-lead gated
presentation did not preserve the required observable contract (whether due to
the implementation/driver boundary or a still-unproven clock/queue interaction).
A next device run requires bounded diagnostics that bind the native gate-release
timestamp to each present ID and prove the exact queue/semaphore ordering; blind
lead tuning is not justified.

## OLED cleanup

The r112 through r116 traps plus independent cleanup neutralized the controller,
force-stopped EmuFusion, removed every frame-generation global, slept Thor,
and set brightness to zero. Final recheck:

```text
mWakefulness=Asleep
screen_brightness=0
emufusion_framegen_proof=null
emufusion_framegen_rife_qualification=null
emufusion_framegen_lsfg_qualification=null
com.thorium.preview PID absent
org.pegasus_frontend PID absent
```

Keep the OLED black during host-only work. Wake it only for a bounded physical
test of a frozen artifact, then perform the same independent cleanup.

## r117-r127: release-window bracket and stale private-pipeline diagnosis

The later Direct experiments retained the exact two-time contract and did not
weaken the physical-slot verifier. They bounded the content-specific native WSI
release windows to five milliseconds for generated rows and four milliseconds
for endpoints, plus the unchanged two-millisecond earliest-display lead. The
visible request is prequeued before that gate opens; private RIFE work starts
only after the preceding visible WSI request is safely queued.

r124/r125 proved that changing the Java prequeue reserve alone could not sustain
20-to-40 generation. r125 used the bounded one-millisecond reserve and still
settled into a repeating generated/endpoint/stale lifecycle: the prepared
midpoint for pair N/N+1 was discarded when N+1/N+2 became current. r126 briefly
showed no stale output after increasing the external FIFO prime depth from three
to four endpoints, but the active sample was too short to decide. The sustained
r127 run disproved that apparent fix:

```text
active requested source/output     20 / 40
final physical/app cadence      19.986 / 19.988 Hz
active timing samples                   311
active endpoint/generated             311 / 0
stale private outputs                     330
generated slots dropped                  329
desired/early/late slot misses          0 / 0 / 0
```

The decisive r127 fingerprint was not slow inference. Every generated request
was rejected as `transport-busy nativePending=1`, while its desired scan was
about 32.0 ms in the future. At 40 Hz the next selection callback arrives about
25 ms later, but the preceding endpoint's immutable release gate was still
owned for roughly one additional millisecond. Because Direct intentionally has
one prequeued visible request, the phase could never recover: every completed
private output became exactly one pair stale.

## r128: causal Direct divisor-phase bootstrap — sustained physical pass

Evidence:

```text
.evidence-rife-oot-r128-direct-phase-bootstrap/
```

APK:

```text
unified-android/build/
  lucent-3.2.16-rife-framegen-qualification-
  41bc1341d5a7bf19c181c0cef4d8d3e7607739a0cadbae8d1317e97793445728.apk
```

There are three valid 40-Hz phases on Thor's measured 120-Hz scan lattice.
The previous implementation inherited the arbitrary calibration-row phase.
r128 instead bootstraps the Direct generated-rate path on the first panel scan
that retains the complete eight-millisecond prequeue admission, then commits
that successfully submitted scan as the immutable output-divisor anchor. Every
later 40-Hz target remains exactly three panel scans apart. On the measured
r127 callback phase this rotates the target from about 32 ms ahead to about
15 ms ahead, so both endpoint and generated gates retire well before the next
25-ms output callback.

The 44-second physical r128 run produced the first sustained automated timing
and numeric-content pass for Ocarina's stable 20-to-40 path:

```text
final source / target             20.000 / 39.977 Hz
final app swap cadence                     39.972 Hz
final physical cadence                     39.981 Hz
active timing samples                             628
active endpoint / generated                   314 / 314
active content proofs                             628
moving / distinct generated                    295 / 295
stale private outputs                                  0
active transport-busy / dropped slots                0 / 0
desired-slot misses                                     0
early / late slot violations                          0 / 0
unsafe pairs                                            0
slot-error maximum                                75,718 ns
GPU + enqueue p95                              9,232,395 ns
timing qualified                                        1
numeric content proof passed                            1
```

The final physical rows alternate endpoint/generated exactly, and the last 20
physical gaps are all approximately 25.01 ms. Five transition/warm-up gaps in
the full active log are outside the final stable epoch; the final epoch itself
contains 314/314 balanced rows and qualifies. All 170 `transport-busy` startup
drops occurred before the generated rate-path transition; after activation
there were zero busy drops and zero stale outputs.

Exact frozen r128 hashes:

```text
a44a34e97f36e366b06182c5039217b541170ab2c54307b1593b20f111281d31  DisplayFrameGenerator.java
1b93e3ef6f5add42e9fbe8e533d580d143b7eda5aa0b3686b2602594ccfe0af5  PhysicalPresentationDeadline.java
3945b9f3658d73b02177789445d0d06a9aabb943394a6d66366d556158fb132d  RifePresentationTransport.java
14eb22c89fedafd21a1226bb52435261f4596f311c90d7bcbebbdec42cf3ce47  PhysicalPresentationDeadlineTest.java
38902a5c5c9d2ef3f0ebf4f55d6eb10de97441766f6df5b6c62c9f02851221c7  test_systemwide_frame_generation.py
99dbdf0308b91cd5c5b0b7f6e76f524d2373e506c7f467b43b73e517809092af  rife_benchmark_jni.cpp
41bc1341d5a7bf19c181c0cef4d8d3e7607739a0cadbae8d1317e97793445728  qualification APK
```

Host gates before r128 were the complete `unified-android/test.sh`, the 77-case
systemwide frame-generation suite, the direct physical-deadline Java test, the
full Android source build, and the RIFE/native qualification build. All passed.

This is a bounded N64/Ocarina 20-to-40 qualification result, not completion of
the overall multi-system release goal. The generated backend remains
qualification-only, and later systems still require their own honest physical
cadence, content, legal/provenance, and automatic-routing evidence.

After r128 the harness and an independent check force-stopped both packages,
cleared every `emufusion_framegen*`/`thorium_rife*` global, set brightness to
zero, and slept Thor. The verified final device state is `mWakefulness=Asleep`,
brightness `0`, with both application PIDs absent.
