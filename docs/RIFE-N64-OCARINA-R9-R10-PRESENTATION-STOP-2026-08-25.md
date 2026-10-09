# RIFE N64 Ocarina r9/r10 presentation checkpoint — 2026-08-25

## Verdict

**STOP / not qualified.** The lawful RIFE v4.6+ncnn qualification backend now
has physically proven Direct transport and physically delivered generated
Ocarina output, but the generated path has not passed exact scan-slot timing,
content, manual motion, or complete QA. Numeric readiness and delivered-frame
counts must not be interpreted as a product pass.

The Thor OLED was awake only for the bounded r10 run at brightness 7. At the
end of the run the app was force-stopped, both RIFE and LSFG qualification
globals were deleted, brightness mode was set to manual, brightness was set to
0, and `KEYCODE_SLEEP` was sent. Final checks reported:

```text
mWakefulness=Asleep
screen_brightness_mode=0
screen_brightness=0
emufusion_framegen_rife_qualification=null
emufusion_framegen_lsfg_qualification=null
```

## r9: physical timing could not advance

APK:

```text
93c36a9e39a0524952a76a5dafc4292bf895359efa6bc912798245db3df29a06
```

The exact live log retained by Android showed two successful endpoint-only
submissions, but no released physical timing rows for the whole run:

```text
schedulerCommitted=2 schedulerReal=2
physicalPending=2 externalSubmitted=2
externalPhysicalEndpoint=0 externalPhysicalGenerated=0
swap=0.000
```

This is consistent with `VK_GOOGLE_display_timing` withholding roughly one
swapchain of tail rows. The Java presentation and evidence ledgers already had
bounded depth 16, so simply raising those queue limits was not the correction.

The source-proven coupled deadlock was endpoint preparation:

- the native import worker was forbidden whenever `submitted` contained any
  unreconciled physical-timing row;
- the worker immediately chained cold imports, leaving almost no owner callback
  in which an already prepared pair could be submitted;
- the four-entry renderer FIFO then repeatedly coalesced and reset while the
  external endpoint pool stopped advancing.

The host correction now yields when one exact adjacent prepared pair exists,
submits that pair, and permits preparation of its successor while older
physical timing rows remain delayed. Native GPU work and endpoint preparation
remain mutually exclusive, so the renderer thread never blocks on the native
context mutex. Physical timing is still the only delivered-FPS authority.

## r10: exact carrier-buffer skip

Qualification APK:

```text
8f5e91d12e51e84145581b9f921bd4df4537566653763900d553558bdab9d061
```

Evidence directory:

```text
.evidence-rife-oot-r10-preparation-fairness/
```

The runner reached the in-process Ocarina route and the generator attached on
the top display. Before a presentation could be tested, the strict ImageReader
identity check rejected:

```text
expected sequence=2 timestamp=165630216495200
actual timestamp=165630233161867
expectedDepth=2 retainedDepth=1
```

The difference is exactly 16,666,667 ns, and the actual timestamp exactly
matches the later announced endpoint. This proves one carrier buffer was
skipped. Relabeling endpoint 3 as endpoint 2 would be forbidden because it
would create false adjacency and wrong interpolation.

The post-r10 host correction searches only the bounded announced queue for an
exact timestamp. If it finds a later exact identity, it records the number of
skipped carriers, publishes a presentation-epoch discontinuity to the common
renderer, discards the active pair, and re-primes only from later adjacent
endpoints. A timestamp that is backward, unknown, or otherwise unmatched still
fails closed. The correction has not yet received physical confirmation.

Post-r10 qualification APK:

```text
1b400ec0ed47afbc4f6487821899edeae224526af68dc6b9b659041f94d08fc0
```

## r11: endpoint-only physical transport checkpoint

Evidence directory:

```text
.evidence-rife-oot-r11-carrier-reprime/
```

The post-r10 APK was installed and run on the Thor top panel. This was a
bounded transport test, not a RIFE frame-generation qualification. The
endpoint-only Direct path successfully escaped the r9/r10 preparation/carrier
deadlock and continuously retired physical presentation rows:

```text
externalSubmitted=1530
externalPhysicalEndpoint=1526
externalPhysicalGenerated=0
physicalPresented=1526
physicalDropped=0
physicalUnavailable=0
physicalPending=4
physicalAvailable=1
swap=19.995
physical=19.994
source=20.000
target=20.000
```

The four pending rows are the bounded timing tail; delivered endpoint rows
continued to advance in order. External GPU timing was also bounded
(`externalCombinedP95Ns=2171042`, `externalCombinedMaxNs=2404114`) with zero
external deadline misses. The test deliberately produced no generated frames:
numeric RIFE remains unqualified and therefore fail-closed.

The general QA runner was interrupted during its OCR-driven Ocarina HUD wait
after the transport result was decisive, so this run does not claim the full
gameplay/content/SF acceptance contract. After interruption the app was
force-stopped, the RIFE and LSFG settings were deleted, brightness was set to
zero, and Android reported `mWakefulness=Asleep` with both displays `OFF`.

## Host gates after the post-r10 correction

```text
78 focused RIFE/system/timing tests: PASS
unified-android/test.sh: PASS
```

Current source identities:

```text
71c268156bd8411abb23f42da16ad297c2fc6e61b88ccb2868f929b474ca28c4  RifePresentationTransport.java
6a17e8e9ef13cea15de7e703fdd5c0a4c8450e169b52557dabc85753a1a0eec9  ExternalFrameGenerationTransport.java
9f93a4673eb7bd5ac00a0e388a567b6daff7a6db382de9f2734c5505be4e8115  DisplayFrameGenerator.java
40aa7ab08161f4855bc5bd1516b135b3ccc5d693ee1c9234c8ec4ab69805b6a9  test_rife_framegen_qualification_packaging.py
```

## Next bounded action

The endpoint-only Direct carrier/timing checkpoint is now physically proven.
The next bounded step is generated-frame qualification, beginning with the
20-to-40 Ocarina mapping. It must retain the same timestamp, discontinuity,
physical-presentation, content, and no-more-than-double constraints. Numeric
output must remain non-qualifying until both generated content and physical
cadence pass the complete verifier contract. Do not weaken timestamp equality,
count GPU fences as scanout, or enable product routing merely because Direct
rows now drain.

## r13/r14: 20-to-40 admission and first generated delivery

The r13 diagnostic capture proved that stable gameplay had a complete
pixel-distinct 20 Hz timestamp clock while endpoint-only fallback deliberately
retained the prior 60 Hz tier:

```text
externalLockedSourceFps=60
externalPresentationSourceHz=20.000000000
externalCandidateOutput=0
```

The admission check was incorrectly using that intentionally stale fallback
tier. The host correction derives the candidate source tier only from the
durable unique-timestamp clock and atomically aligns the controller tier when
the independently supported backend path is enabled. Renderer throughput does
not fund that decision.

The resulting r14 qualification APK was:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-02c06c8330edb37fc1dc306254108ab98970c9410714191d3487cc8658852fa5.apk
```

Evidence directory:

```text
.evidence-rife-oot-r14-source-identity/
```

Physical r14 proved that admission and generated Vulkan delivery now operate:

```text
source=20.000 target=40.000 canonical=20.000 uniqueClock=20.000
externalLockedSourceFps=20 externalCandidateSource=20
externalCandidateOutput=40 externalCandidateScans=3
externalCandidateSupported=1 externalRatePathActive=1
externalGenerationAvailable=1 physical=39.990
physicalDropped=0 physicalUnavailable=0
```

Generated content rows were non-duplicates and did not cross a scene-cut risk,
but the path correctly remained unqualified because every retained timing row
missed the requested physical slot:

```text
externalTimingSamples=240
externalTimingGenerated=239
externalDeadlineMisses=0
externalDesiredSlotMisses=240
externalSlotErrorMaxNs=15692918
externalContentMovingGenerated=239
externalUnsafePairs=0
externalContentManualPassed=0
physicalQualified=0
```

The first timing defect was a clock-domain conflation. The immutable deadline
planner selected a physical scan and a 2 ms earlier completion cutoff, but
Display passed the cutoff to `VK_GOOGLE_display_timing`/EGL as the desired
presentation timestamp. At this point in the investigation the host kept three
explicit values but incorrectly treated Vulkan desired time as an exact
scanout request:

- content timestamp: the selected producer-clock sample;
- driver desired-present timestamp: initially the selected physical scan;
- hard completion deadline: physical scan minus the proven 2 ms lead.

That model was tested in r15-r18 and then superseded by the official Vulkan
semantics and physical evidence documented below.

The r14 run was stopped as soon as the timing failure was decisive. The app was
force-stopped, all RIFE/LSFG/proof globals were deleted, brightness was set to
zero, and final device checks reported `mWakefulness=Asleep`, both displays
`OFF`, and brightness `0`.

## r15/r16: physical-lattice alignment and explicit startup drop

r15 showed that sending the exact selected timestamp to Vulkan was necessary
but not sufficient. Even endpoint-only rows missed the requested slot because
the Java Choreographer phase is not the owned Vulkan swapchain's physical
presentation phase. The bounded host correction now establishes an anchor from
the returned `actualPresentTime` plus measured refresh duration and selects
future desired-present targets on that Vulkan lattice. It never reuses an
already handed scan and retains the separate scan-minus-2-ms hard cutoff.

The resulting r16 qualification APK was:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-3e8d3fc0ae5a818edf39b60bbfac708c69973317fb7de17efc765762970b96eb.apk
```

Evidence directory:

```text
.evidence-rife-oot-r16-vulkan-anchor/
```

r16 stopped at the first unambiguous transport result. Vulkan returned physical
presentation ID 2 while ID 1 had not been shown:

```text
past-presentation identity failed expectedId=1 actualId=2
```

That is an explicit compositor drop, not an identity match and not permission
to relabel ID 2 as ID 1. The old native drain incorrectly required every
submitted ID to appear and killed the whole RIFE session. The current host
correction accepts only strictly increasing returned IDs, preserves gaps, maps
each returned ID to its exact submitted request, and removes the missing
submission only as a counted physical drop. `ExternalPresentationLedger`
exposes `droppedBefore`; `PhysicalPresentationCadence.recordDropped` then
invalidates qualification until a later clean recovery interval. No missing
frame is counted as delivered.

Host gates after this correction:

```text
unified-android/test.sh: PASS
systemwide frame-generation tests: 66 PASS
RIFE qualification packaging tests: 5 PASS
```

The device was illuminated only for the bounded r16 run. Immediately after the
failure the app was force-stopped, all RIFE/LSFG/proof globals were deleted,
brightness was set to zero, and Android reported `mWakefulness=Asleep`, both
displays `OFF`, and brightness `0`.

## Current next bounded action

Compile the explicit-drop correction, then run one short r17 top-panel Ocarina
checkpoint. Startup ID gaps must be reported as `physicalDropped` and must not
terminate the transport. A later presentation-epoch reset must clear their
qualification influence before the stable generated 20-to-40 window. That
window still requires zero drops/unavailable rows, zero deadline and desired-
slot misses, physically delivered generated rows, and numeric content proof.
Manual motion inspection and the complete acceptance/verifier contract remain
mandatory before product qualification.

## r17 result

r17 used APK:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-d5d0d4ec9f19037ab350cab995cf9e76fd469cc5ba1bab9c9863460c5c8b49d0.apk
```

The explicit-drop correction worked: the session survived startup and the
stable generated path reached `source=20`, `target=40`, distinct generated
content, zero reported drops/unavailable rows, and zero completion-deadline
misses. It still failed qualification decisively. Every physical timing row
missed the requested Vulkan slot, with maximum absolute error approximately
16.72 ms, and later measured delivery fell toward 35 Hz instead of remaining
40 Hz. Therefore anchoring each future request from the latest returned actual
present timestamp is not a sufficient phase-control policy on this driver.

The run was stopped immediately after that conclusion. The app was
force-stopped, all RIFE/LSFG/proof globals were deleted, brightness was set to
zero, and final checks reported `mWakefulness=Asleep`, both displays `OFF`, and
brightness `0`.

The next investigation is host/read-only: add signed actual-minus-desired
presentation telemetry and determine whether Thor's FIFO implementation
applies a stable two-scan scheduling offset or whether the latest-actual anchor
is feeding compositor latency back into the target lattice. Do not run another
physical test until that distinction is explicit in source and host tests.

## r18 result and corrected Vulkan timing semantics

r18 used APK:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-9b3ae9265105205e2e00d4093706e91f250c62397776bf74d063e94d005f70ea.apk
```

It froze one returned actual-present anchor instead of re-anchoring every row.
That removed the r17 feedback runaway, but the signed actual-minus-target error
still rose from roughly 9.8 ms to 11.6 ms over 141 direct rows. During active
20-to-40 generation it reached roughly 12.4-13.3 ms. Generated-content proof
passed numerically, physical drops and timing-row unavailability stayed zero,
then the presentation path failed closed after crossing the hard deadline.

The run proves two separate facts:

1. Thor's returned physical scan clock differs measurably from the nominal
   Vulkan refresh duration, so indefinitely extrapolating a frozen anchor with
   only that nominal duration accumulates phase error.
2. `VkPresentTimeGOOGLE.desiredPresentTime` is not an exact scan timestamp. The
   official Vulkan contract defines it as an earliest-display bound. The
   returned `actualPresentTime` is the physical scan timestamp.

Authoritative references: [Vulkan WSI presentation timing](https://docs.vulkan.org/spec/latest/chapters/VK_KHR_surface/wsi.html)
and [`VkPresentTimeGOOGLE`](https://docs.vulkan.org/refpages/latest/refpages/source/VkPresentTimeGOOGLE.html).

The current host correction therefore uses:

- content/physical target: the selected scan on a long-baseline clock learned
  from returned actual-present rows;
- driver desired-present bound: physical target minus the proven 2 ms lead;
- hard completion deadline: the same target-minus-2-ms bound.

The physical clock keeps its first actual-present anchor, resolves whole scan
gaps with the nominal Vulkan duration, and estimates the period from the full
anchor-to-latest baseline after at least 30 scans and 500 ms. It does not copy
per-row compositor jitter into the next target. Evidence compares actual
scanout to the independently modeled content target, separately requires
actual not precede the Vulkan bound, and reports the learned period and scan
count. Host Java, systemwide, and focused RIFE packaging/timing suites pass.

Thor was force-stopped and returned to brightness zero, asleep, both displays
OFF, with all frame-generation globals deleted immediately after r18. Do not
wake it again until the corrected APK is built and the next single bounded
physical question is ready.

## r19c: physical clock alignment proven; epoch re-anchor fixed

The full-core qualification APK was:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-c9371f9d3582677ff85c96ef370318a57249ca3fe16b36eca8fc37ac411cc7ac.apk
```

Evidence:

```text
.evidence-rife-oot-r19c-direct-clock/logcat.txt
```

The bounded direct Ocarina launch physically proved the corrected target
semantics and long-baseline clock. After the initial evidence epoch, 135 direct
physical rows retained:

```text
externalDeadlineMisses=0
externalDesiredSlotMisses=0
externalEarliestPresentMisses=0
externalEarlyPresentViolations=0
externalSlotErrorSignedMinNs=-20615
externalSlotErrorSignedMaxNs=12932
externalPhysicalClockPeriodNs=8336117
externalPhysicalClockScans=444
physicalDropped=0
physicalUnavailable=0
```

The run then exposed one narrow lifecycle defect. Ocarina stopped presenting
while its source classification moved from startup 60 to 25/20, repeatedly
changing the scheduler presentation epoch. The next physical row was compared
against the old epoch's scan phase and failed closed as `external physical scan
clock is inconsistent`. Cadence evidence was already reset at that exact
boundary, but the physical clock was not.

The host correction now resets the physical clock alongside physical cadence
when the committed presentation epoch changes, before recording the first
actual-present row of the new epoch. The evidence classes already partition by
presentation epoch, so this cannot lend any old timing row to the fresh clock.
Focused Java, 67 systemwide frame-generation tests, and RIFE timing/packaging
tests pass after the fix. A later physical run should verify only the new-epoch
re-anchor and then stop; the slot-alignment model itself is already proven.

The device was used only during bounded tests. At the end it was force-stopped,
all RIFE/LSFG/proof globals were deleted, brightness was written to zero, and
Android reported `mWakefulness=Asleep` with both displays `OFF`.

## r20: epoch re-anchor physically closed

The follow-up APK was:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-2f034659626fcc4e3f9d7bfa7bf3dd56c4da37bc57245aaf271f9cfa3cc2b54d.apk
```

Evidence:

```text
.evidence-rife-oot-r20-epoch-reanchor/logcat.txt
```

The exact r19 failure point did not recur. The session crossed the startup
60-Hz epoch, the no-present source transition, and the fresh 20-Hz epoch
without `external physical scan clock is inconsistent`, a hard-deadline
exception, or a fatal process exception. The new epoch established a fresh
actual-present anchor as designed.

Within stable portions, returned physical timing again tracked the learned
clock within tens of microseconds and reported zero earliest-bound violations.
Later direct 20-Hz rows developed a persistent one-panel-scan desired-slot
offset while present IDs remained continuous. This is a separate honest timing
STOP, not a regression of epoch re-anchoring and not evidence that generated
20-to-40 is qualified. The next host-only investigation should preserve and
expose `presentMargin` minima/rolling distribution, then decide from the
official GOOGLE_display_timing feedback whether the current 2 ms earliest
bound lacks physical margin. Do not loosen the slot gate or relabel a late
physical row.

Thor was immediately force-stopped after the 25-second run, every RIFE/LSFG/
proof global was deleted, brightness was restored to zero, and both displays
were verified OFF with `mWakefulness=Asleep`.

## r21: present margin rules out an insufficient 2 ms lead

The bounded diagnostic APK was:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-beaea87bec7cfef84042dd500e4b1996885b3161b2baba7d3588e3f1cccdaae6.apk
```

Evidence:

```text
.evidence-rife-oot-r21-present-margin/logcat.txt
```

The shared physical-evidence accumulator now retains, per presentation epoch:

- lifetime minimum, maximum, and latest `presentMargin`;
- rolling p05, median, and p95 margin over at most 256 rows;
- exact early-versus-late desired-slot miss counts;
- minimum and maximum margin specifically on late-slot rows;
- the already-existing signed actual-minus-target error and learned physical
  clock identity.

The raw Vulkan member is `uint64_t`, so the initial diagnostic treated every
negative Java `long` as an invalid enormous unsigned duration. r25 later proved
that Thor's Adreno driver can instead wrap a small late margin through this
unsigned field. The superseding bounded handling is documented below; genuinely
large wrapped values still fail closed.
The offline verifier now requires the margin distribution, signed-slot,
earliest-bound, direction-conservation, and physical-clock fields atomically.
No presentation threshold or scheduling policy changed.

The first stable r21 epoch contained 36 one-scan-late rows, but their
`presentMargin` was not low:

```text
externalLateSlotMisses=36
externalPresentMarginMinNs=2423750
externalPresentMarginP05Ns=2649844
externalPresentMarginP50Ns=3347813
externalPresentMarginP95Ns=3470520
externalPresentMarginMaxNs=3517761
externalLateSlotMarginMinNs=2423750
externalLateSlotMarginMaxNs=3517761
```

This rules out the prior hypothesis that the 2 ms earliest-present lead was too
short. Vulkan reports that the queue-present commands were processed roughly
2.4-3.5 ms before the latest time that still allowed the returned
`earliestPresentTime`. The following scheduler epoch was physically clean over
36 rows (`externalDesiredSlotMisses=0`) with a similar 3.15-3.45 ms margin.
The remaining issue is therefore target-lattice/bootstrap or Android
surface-phase ownership, not GPU/compositor starvation. Do not increase the
lead or weaken the exact-slot gate from this evidence.

One later returned timing row contained a field outside the new signed-duration
contract and correctly ended the qualification session. The r21 APK's exception
did not distinguish zero `earliestPresentTime` from an unsigned-overflow margin;
the source now reports those cases separately with bounded raw values. No second
device run was performed merely to collect that diagnostic.

After the single 30-second test, Thor was force-stopped, every RIFE/LSFG/proof
global was deleted, brightness was restored to zero, and Android was explicitly
verified as `mWakefulness=Asleep` with both displays `OFF`.

## Post-r21 host fix: isolate physical-clock calibration from qualification

The r21 margin evidence rules out an insufficient present lead, but it also
showed that the first externally presented endpoints were serving two different
purposes: establishing the Vulkan actual-present clock and immediately being
judged against that newly learned lattice. The host now has an explicit,
one-way `ExternalPhysicalClockBootstrap` barrier:

- startup output remains endpoint-only; generated calibration rows fail closed;
- returned calibration presents may establish the physical anchor, but are
  excluded from timing and content qualification evidence;
- after the first anchor exists, new submissions pause until the transport and
  presentation-ledger queues both drain to zero;
- the drained boundary resets cadence, the scheduler presentation epoch,
  endpoint timeline, proof epoch, and health-window baselines exactly once;
- only post-boundary rows may activate the generated rate path or satisfy the
  offline timing verifier.

The health record now carries
`externalPhysicalClockCalibrated=1` and a positive
`externalPhysicalClockCalibrationPresents`; the verifier requires both. Queue
counts must be equal and nonnegative throughout the drain. Calibration presents
are still counted as real successful device presents before the boundary, but
cannot be lent to a later evidence window.

Host verification after the change:

```text
unified-android/test.sh: PASS
focused RIFE/systemwide Python: 79 PASS
full tools discovery: 1391 run, only the three pre-existing dirty-tree locks
  (theme frozen hash, Cemu patch size lock, stale manifest <queries>)
qualification APK build: PASS
```

Built artifact:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-4a7dd74ecbb628e9375e3a63eb27f3304fc171b562908d4b2e992b3805114575.apk
SHA-256 4a7dd74ecbb628e9375e3a63eb27f3304fc171b562908d4b2e992b3805114575
```

This is a host-qualified diagnostic APK, not physical frame-generation proof.
The next device run must prove that the isolated boundary removes the startup
slot-offset epoch and, if the later anomalous row recurs, capture the new
field-specific failure. No device run was performed for this change. Thor
remained asleep, brightness zero, and both OLED panels off throughout the
host-only implementation and build.

## r22-r25: calibration queue behavior physically characterized

Four short, bounded Ocarina runs tested only the physical-clock boundary. Their
evidence directories are:

```text
.evidence-rife-oot-r22-clock-bootstrap/
.evidence-rife-oot-r23-serialized-bootstrap/
.evidence-rife-oot-r24-epoch-isolated-bootstrap/
.evidence-rife-oot-r25-unbounded-calibration-tail/
```

r22 returned one timing row but left an unobservable pending tail when new
submissions were stopped. r23 proved that exactly one submitted presentation
does not release its own GOOGLE_display_timing row on this device. r24 proved
that an arbitrary cap of two submissions is also insufficient. The driver has
a variable multi-present feedback delay, so a queue-drain barrier cannot be the
bootstrap authority.

r25 replaced the drain with an epoch-isolated boundary:

- endpoint-only calibration submissions continue through the transport's
  already-bounded queue until the first actual-present row arrives;
- that first row establishes the long-baseline physical clock;
- the boundary resets cadence, scheduler epoch, endpoint timeline, proof epoch,
  and health baselines immediately;
- already-submitted old-epoch rows remain calibration-only even when returned
  after the boundary and cannot enter timing/content qualification;
- generated calibration rows still fail closed.

This physically succeeded:

```text
Requested game display cadence ... reason=first-physical-vulkan-calibration-present
External physical clock calibrated ... calibrationPresents=1 ...
  excludedTailPending=4 previousEpoch=5 epoch=6
```

The first post-boundary health record reported `calibrated=1`, one physical
endpoint, four excluded old-epoch rows still pending, and zero post-boundary
timing/content samples. This is the intended evidence separation. It is not yet
generated-frame qualification.

## r25 follow-up: bounded wrapped present margin

The next returned old-epoch timing row ended the session with:

```text
presentId=2
marginRawUnsigned=18446744073708987189
```

Interpreted as two's-complement signed displacement, this is `-564427 ns`. The
Vulkan structure declares `presentMargin` as `uint64_t` and describes it as how
early queue-present processing completed relative to the last safe processing
time. Thor's row therefore appears to expose a small late value by unsigned
wraparound instead of saturating it to zero. The host correction is deliberately
conservative:

- a nonnegative margin is preserved exactly;
- a wrapped-negative magnitude no larger than one returned refresh duration is
  converted to zero headroom and logged with its raw unsigned value;
- anything beyond one refresh, including `Long.MIN_VALUE`, still fails closed;
- no positive margin is fabricated, and actual/earliest/desired physical-time
  gates remain unchanged.

The authoritative Vulkan reference is
[`VkPastPresentationTimingGOOGLE`](https://docs.vulkan.org/refpages/latest/refpages/source/VkPastPresentationTimingGOOGLE.html).

Host freeze after the correction:

```text
unified-android/test.sh: PASS (including exact r25 and overflow adversaries)
focused RIFE/systemwide Python: 79 PASS
qualification APK build: PASS
```

Built artifact for the next bounded physical check only:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-093dcfd0a864f26a12639280672668f1a46c110e10275952236117c1016a17ef.apk
SHA-256 093dcfd0a864f26a12639280672668f1a46c110e10275952236117c1016a17ef
```

No r26 device run was performed. After r25, the app was force-stopped, all
qualification globals were removed, brightness was set to zero, Android was
verified asleep, and both physical displays were verified OFF. Keep the OLEDs
black until a later turn explicitly performs the single bounded r26 check.

## r26: calibration boundary survives into post-boundary evidence

Evidence:

```text
.evidence-rife-oot-r26-bounded-margin/
```

The r26 APK calibrated on its first returned physical row and retained four
old-epoch tail requests:

```text
calibrationPresents=1
excludedTailPending=4
previousEpoch=5
epoch=6
```

Unlike r25, the session did not fail on its following timing rows. There was no
`External presentation session failed closed`, fatal exception, or wrapped-
margin warning. One omitted calibration-tail present ID was conservatively
accounted as `physicalDropped=1`; it was not lent to post-boundary evidence.
Five returned old-epoch presents were ultimately counted only as calibration.

Fresh evidence then advanced normally. A stable direct epoch retained 94
post-boundary physical rows, a learned period near 8.336 ms, zero earliest-
present violations, and zero physical-unavailable rows. Ocarina later settled
to direct 20 Hz with physical delivery approximately 19.997 Hz. At capture end:

```text
source=20.000
target=20.000
physical=19.997
externalPhysicalClockCalibrated=1
externalPhysicalClockCalibrationPresents=5
physicalUnavailable=0
externalPhysicalGenerated=0
```

The short run did not qualify generation. Startup contributed a long nominal
60-Hz prefix, so the durable 20-Hz unique-source proof had only about 4.35 s of
clean evidence when capture ended; `externalCandidateOutput` remained zero.
The next bounded test must stay in moving 20-Hz gameplay long enough to test
20→40 admission, without changing any timing or quality threshold.

Immediately after capture the app was force-stopped and qualification globals
were deleted. The stored brightness was explicitly corrected to zero after the
app's shutdown restoration raced the first cleanup write. Final checks reported
Android asleep and both displays OFF.

## r27: generated admission succeeds, but cadence/classification is invalid

Evidence:

```text
.evidence-rife-oot-r27-generated-admission/
```

The longer bounded run proved that the endpoint-only preflight can now admit
the exact Ocarina candidate without a calibration or transport crash:

```text
candidateSource=20
candidateOutput=40
candidateScans=3
panelMeasured=1
supported=1
externalRatePathActive=1
```

Physical output rose from direct 20 Hz to approximately 39.19 Hz, the content
analyzer received 147 generated images, and the Vulkan timing queue remained
live. This is not a qualification pass. Two independent failures are decisive.

First, the epoch classified only one endpoint presentation followed by 147
generated presentations:

```text
externalTimingEndpoint=1
externalTimingGenerated=147
externalContentEndpoints=1
externalContentGenerated=147
schedulerReal=620        # unchanged after admission
schedulerSynthetic=151   # continues increasing
```

For the exact 20-to-40 path this must be a rational endpoint/midpoint lattice,
not an indefinitely generated-only stream. The generic timestamp resampler can
remain fractionally offset from every endpoint and rotate the retained pair
after a synthetic sample; that behavior conflicts with the schema-36 rational
accounting and the intended artifact-bounded 2x policy. A host regression must
replay an externally planned 20-to-40 physical lattice and require equal exact
REAL and SYNTHETIC commits after the initial prime.

Second, every generated physical row missed its desired slot:

```text
externalDesiredSlotMisses=147
externalLateSlotMisses=147
externalSlotErrorSignedLastNs=8316032
externalCombinedP95Ns=13256719
```

Although successive selected outputs are three panel callbacks apart, the
external deadline helper currently plans only the next physical scan after the
selection callback. That leaves roughly one scan minus the proven 2-ms driver
lead for RIFE submission, while measured combined work is about 13.3 ms p95.
The planner must reserve the next exact output-divisor slot (three scans for
20-to-40), preserving the calibrated physical phase and monotonic target
ledger. Thresholds must not be loosened to hide the miss.

The bounded test was cleaned up immediately. The app is stopped, qualification
settings are absent, brightness is zero, Android is asleep, and both Thor OLED
panels are OFF. All further diagnosis remains host-only until a frozen audited
fix justifies one new bounded physical run.

## r28 host candidate: output-slot pipeline and exact 2x endpoint ownership

The r27 failures are closed host-side without changing the source-rate rule,
quality thresholds, physical acceptance thresholds, or the built-in renderer.

`PhysicalPresentationDeadline.nextAlignedOutput` now plans external generated
work at least one complete output interval ahead on the calibrated panel
lattice. At 20-to-40 this means an exact three-scan target and approximately
23 ms before the proven 2-ms driver cutoff, instead of attempting RIFE inside
the single scan following the selection callback. Successive requests remain
exactly three scans apart; a late callback abandons an entire stale output slot
and cannot catch up.

The external backend also opts into an integer-2x endpoint contract. For
20-to-40, 30-to-60, and 60-to-120 it primes with the retained left REAL,
generates exactly one timestamp-derived intermediate without rotating the
pair, then presents and commits the exact right REAL. The interpolation phase
still comes from the immutable endpoint timestamps and selected physical time;
it is not replaced with a fabricated 0.5. A genuinely missed physical slot may
skip the intermediate and present right, but it cannot emit stale synthesis or
a burst. Built-in arbitrary-phase scheduling remains unchanged.

Host gates:

```text
unified-android/test.sh: PASS
systemwide frame-generation tests: 67/67 PASS
full tools discovery: 1391 tests, only the same three unrelated dirty-tree
  locks (theme hash, Cemu patch size, stale package-query manifest)
qualification APK build and Android javac: PASS
```

The first artifact produced during this checkpoint omitted the Phase-1
experimental core payload and was correctly rejected by the device launcher.
The rebuilt artifact that actually contains the N64 route and was used for r28
is:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-dd8d6936b3cced782e3800906adb86455d2a22c7bb359a4267389ecb08626e6c.apk
SHA-256 dd8d6936b3cced782e3800906adb86455d2a22c7bb359a4267389ecb08626e6c
```

## r28 physical result: endpoint ownership and physical slot pipeline fixed

Evidence:

```text
.evidence-rife-oot-r28-slot-pipeline/
```

The bounded Ocarina run physically proved the two r27 fixes. After admission,
the stable epoch delivered 1,189 joined physical rows as exactly 595 endpoints
and 594 generated frames. The prior generated-only stream is gone. App swaps
and Vulkan physical presents both held approximately 39.98 Hz on the measured
119.935-Hz panel divisor:

```text
externalTimingSamples=1189
externalTimingEndpoint=595
externalTimingGenerated=594
externalContentEndpoints=595
externalContentGenerated=594
externalDesiredSlotMisses=1
externalLateSlotMisses=1
externalSlotErrorSignedLastNs=6445
physical=39.986
swap=39.983
```

All 594 generated content rows remained distinct from both endpoints, with no
endpoint identity, scene-cut, tag, or content-numeric failure. After the cold
first submission, physical-slot error was only tens of microseconds rather
than r27's one full scan. This is a large product correction, but it is not yet
a qualification pass.

One cold row still took 55.185 ms of combined enqueue/GPU work and landed one
complete 24.957-ms output slot late. Every later row was clean; combined p95
settled near 10.663 ms, safely below the three-scan deadline. The remaining
miss is therefore a first-generated-use warm-up defect. It must be eliminated
before the path can be called smooth; the evidence threshold will not be
loosened to hide it.

r28 also exposed an independent verifier error. Vulkan defines
`earliestPresentTime` as the time at which the image *could* have been shown,
and explicitly allows it to precede `actualPresentTime` when a later display
time was requested. Requiring equality falsely rejected 1,188 valid rows. The
host verifier now rejects only `actualPresentTime < earliestPresentTime`, while
retaining the separate desired-slot and no-early-presentation checks. This
standards correction does not make r28 pass because its one real cold deadline
and slot miss remain intact.

Current bounded next step is host-only: pre-warm the first generated RIFE
execution without presenting it or blocking the display callback, then rerun
the exact unchanged physical gates. No rolling-window reset or ignored first
frame is acceptable, because either would hide the visible cold stall.

Cleanup was completed immediately after r28. The app is stopped, all
qualification globals are absent, brightness is zero, Android reports asleep,
and both Thor displays are OFF. The screen must only be enabled for the next
bounded device test and returned to this black/off state as soon as that test
ends.

## r29: cold warm-up fixed; early-queue behavior is now the exact STOP

Evidence:

```text
.evidence-rife-oot-r29-prewarm/
```

Artifact:

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-fe9ffc2184dddce25ca27b96a2fa0f98c57485cb22ad5b97ab795a6426f4b84f.apk
SHA-256 fe9ffc2184dddce25ca27b96a2fa0f98c57485cb22ad5b97ab795a6426f4b84f
```

The qualification-only transport now runs one validated full RIFE inference
before creating/exposing its endpoint `Surface`. On Thor that startup warm-up
took 50.581 ms (`processNs=50.408 ms`), entirely before gameplay ownership.
The first live generated epoch then had no cold GPU/work miss:

```text
externalDeadlineMisses=0
externalCombinedP95Ns=10656614
externalCombinedMaxNs=11295416
externalEnqueueMaxNs=4943958
externalGpuMaxNs=6374271
```

This closes the r28 55-ms in-game cold hitch without ignoring any physical
row. Endpoint/generated ownership remained exact (216/215 in the last joined
snapshot), numeric content proof passed, and physical cadence held about
39.984 Hz.

The faster ready time exposed the next scheduling constraint. Every r29 row
was physically displayed one panel scan before its modeled three-scan target:

```text
externalDesiredSlotMisses=431
externalEarlySlotMisses=431
externalEarlyPresentViolations=431
externalSlotErrorSignedMinNs=-8536166
externalSlotErrorSignedMaxNs=-8294324
externalPresentMarginP50Ns=20336822
```

`VK_GOOGLE_display_timing` describes `desiredPresentTime` as a time the image
*should* not precede, not an enforceable compositor barrier. With RIFE warmed,
the image reaches FIFO early enough for the preceding physical scan and Thor's
driver uses it. r28 happened to reach FIFO after that earlier scan's latch
window; relying on work being slow is not a valid scheduler.

The next host arm must therefore preserve the same calibrated three-scan
output lattice but defer submission to an explicit opening boundary. For this
20-to-40 RIFE path, measured work plus the 2-ms driver lead requires two panel
scans of preparation, not the current three-scan early queue and not r27's
unsafe one-scan deadline. The opening and hard cutoff must both be represented
in the immutable request/ledger; a late callback skips the slot and cannot
catch up. No desired-slot tolerance or early-presentation gate will be relaxed.

After r29 the app was stopped, every qualification setting was deleted, the
display brightness override was driven to zero, Android was put to sleep, and
both Thor OLED display devices report `state OFF, committedState OFF`.

## r30 host candidate: measured two-scan submission window

The r29 one-scan-early result is closed host-side without changing the target
40-Hz lattice. `nextAlignedOutput` still advances successive physical targets
by exactly three measured panel scans, but the first target must now be at least
`max(1, scansPerOutput - 1)` scans after the selection callback. At 20-to-40,
the common callback phase therefore selects the next target two scans away
instead of skipping it and queueing for the following target five scans away.

This gives warmed r29 RIFE approximately 14.7 ms before the 2-ms hard cutoff:
more than its measured 10.66-ms p95 / 11.30-ms max, while avoiding the 25-ms
early FIFO residency that caused every r29 frame to use the preceding scan.
The immutable target spacing, desired-slot tolerance, no-early gate, no-catchup
behavior, endpoint/synthetic ownership, and content gates are unchanged.

Host gates are green:

```text
unified-android/test.sh: PASS
RIFE timing + systemwide focused tests: 75/75 PASS
qualification APK build/Javac/package: PASS
```

Frozen bounded-test artifact (not installed):

```text
/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-rife-framegen-qualification-ca8e62e5f1b07b763e2113ed01cb22cdd5fc432327271ce0c2012ab010da0191.apk
SHA-256 ca8e62e5f1b07b763e2113ed01cb22cdd5fc432327271ce0c2012ab010da0191
```

No r30 device run has been performed. Thor remains asleep with the app stopped,
the qualification switch absent, and both display devices OFF. The next use of
the panel must be only the bounded r30 test, followed by the same immediate
black/off cleanup.

## r30/r31 physical follow-up: deferred release needs lookahead

The bounded r30 run was subsequently performed. It delivered 431 timed
endpoint/generated rows, but every row was still displayed one Thor scan early:

```text
externalTimingSamples=431
externalDeadlineMisses=0
externalDesiredSlotMisses=431
externalEarlyPresentViolations=431
externalEarlySlotMisses=431
externalLateSlotMisses=0
```

Moving only the desired target from three scans to two therefore did not control
release on this WSI path. The r31 host arm separated GPU submission from
`vkQueuePresentKHR`: native work retained the image and semaphore, and the owner
Handler released presentation only inside a four-millisecond window before the
existing hard cutoff. Qualification APK:

```text
773121d7fb88269e2271bdc30ae0101febf392cb2eabe544c389d45cca8a8e12
```

Physical evidence:

```text
.evidence-rife-oot-r31-deferred-wsi-release-valid/
```

The first presentation armed deferred release 1.221385 ms after its window
opened and still 2.778615 ms before cutoff. The following reactive RIFE job did
not reach release scheduling until after its own cutoff, so the arm correctly
rejected instead of presenting late:

```text
RIFE deferred WSI release armed ... latenessNs=1221385
External presentation session failed closed
Caused by: RIFE deferred WSI release crossed its hard cutoff
```

This is a product STOP, not a reason to widen thresholds. Explicit WSI release
control is necessary, but reactive per-slot inference is insufficient. The next
bounded architecture must prepare the generated frame ahead of its display slot,
retain a GPU-ready swapchain image, and use the deferred-release stage only when
the exact target window arrives. It must preserve causal endpoint identity, the
no-more-than-double rule, physical presentation timing, and all existing content
and safety gates.

The first r31 attempt accidentally omitted the explicitly qualified N64 core
and was rejected before gameplay. It remains only as packaging evidence in
`.evidence-rife-oot-r31-deferred-wsi-release/` and is not a runtime result.

For both r31 attempts the Thor was awake only during the bounded capture at low
brightness. Cleanup force-stopped the app, deleted RIFE/dense/proof globals, set
brightness to zero, sent sleep, and verified `mWakefulness=Asleep` with two
display-device `state OFF` rows before evidence analysis.

## r32-r42 checkpoint: causal generation works; Java WSI timing is the STOP

r32-r39 established the remaining causal pipeline requirements. A full output
period is reserved before the target scan. Cold AHardwareBuffer imports run off
the renderer Handler. Direct presentation stops preparation at two consecutive
endpoints. The qualified 20-to-40 path prepares a third consecutive endpoint,
then uses the current endpoint presentation to assess the next pair. No cold
lookahead import is allowed on a visible deadline.

r40 physically proved that design for the first time:

```text
evidence: .evidence-rife-oot-r40-three-prepared-window/
physical output: 39.969-39.972 fps
logical source: 20.000 fps
externalTimingEndpoint / externalTimingGenerated: 175 / 175
externalDeadlineMisses: 0
externalUnsafePairs: 0
externalContentNumericPassed: 1
```

The transport produced a strict alternating 20-real plus 20-generated stream.
Lookahead proof started and completed with exact adjacent endpoint identity.
The physical output stayed on the three-scan 120 Hz panel divisor. This closes
the former zero-synthetic and preparation-starvation defects.

r40 is still a STOP. After approximately nine clean generated seconds, the
renderer Handler was descheduled past the immutable six-millisecond WSI release
window by 1.193277 ms. The transport failed closed:

```text
RIFE bounded deferred WSI wait crossed its hard cutoff
```

r41 was not a frame-generation result. The cleanup script force-stopped only
the activity alias package, so an old lower-display process stayed alive and
the generator did not attach. Cleanup now always force-stops both
`com.thorium.preview` and `org.pegasus_frontend`.

r42 tested a separate maximum-priority Java release worker. It was also
descheduled past the same cutoff, this time by 1.736763 ms during direct
presentation. The experiment was reverted. Java Handler and Java worker timing
are therefore both physically disproven as hard WSI release authorities.

The next bounded arm must move the absolute release wait below Java. Prefer a
native Vulkan capability such as present-wait if Thor exposes it. Otherwise,
use one persistent native timed-release worker with an absolute monotonic wait,
native context locking, zero-wait Java polling, strict earliest/cutoff checks,
and bounded teardown. Do not widen the six-millisecond window: doing so can
open before the preceding 120 Hz scan and recreate the proven early-present
defect.

Current host checkpoint after reverting the failed Java-worker arm:

```text
RIFE transport: 7272f43acac037b4d762b50bbfb5f6a23a09bfffa248231ed8fcaee861599c17
external interface: 61dfbc1f209af472ad867fa2ff23259475ad638bae630a5e802b2376bf2504a1
DisplayFrameGenerator: d38cf8efd7f1ef88eed2c8e2c33b16969c496a1df4a049145e483120c55341e4
RIFE packaging test: 07cbf993674a221c94af6ef8398ef62476f17049a141733df66b95e6cd2235a2
systemwide test: 077b5b1f471c011e496c87669927f77ca3fd29d93297ac4a023fd4f5373e1f6b
focused tests: 75/75 PASS
```

This source remains qualification-only and is not product-qualified. At the
final checkpoint, both Thor displays are physically OFF, wakefulness is Asleep,
brightness is 0, both qualification globals are absent, and both app package
names are force-stopped. Do not wake the Thor until a new host-frozen native
release artifact is ready for a bounded test.
