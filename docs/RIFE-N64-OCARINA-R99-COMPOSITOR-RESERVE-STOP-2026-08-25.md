# RIFE N64 Ocarina r99 compositor-reserve STOP — 2026-08-25

## Verdict

STOP. A 2.000 ms compositor-submission reserve did not prevent the bounded Thor
run from producing one frame a physical scan late. The failure was not RIFE
compute overload. The run also exposed a measurement/ownership gap: Java chose
an immutable `(vsyncId, expectedNs, deadlineNs)` row, but the JNI/native present
path transported only `vsyncId` and re-read the timeline row. The old evidence
therefore cannot prove that native validated the same deadline Java selected.

This remains qualification-only. Product frame-generation routing is disabled.

## Physical evidence

Evidence directory:

```text
.evidence-rife-oot-r99b-compositor-reserve/
```

The internal Mupen64Plus-Next route and RIFE warmup were observed. After proof
activation and bounded moving input, the first fail-closed event was:

```text
presentId=303 generated=0 phase=1.000000
contentNs=241031495287659
desiredNs=241031493287659
timelineVsyncId=118646969
timelineExpectedNs=241031495284665
timelineDeadlineNs=241031484951332
latchNs=241031493425760
actualNs=241031503613624
enqueueWallNs=728906
gpuWorkNs=163958
deadlineMisses=0 desiredSlotMisses=1
```

The selected timeline prediction was only 2.994 microseconds before the content
target. The transaction latched 8.474428 ms after the selected composition
deadline, and actual presentation was one Thor scan late. Enqueue wall time was
0.729 ms and measured GPU work was 0.164 ms. Increasing the reserve again would
be an unsupported guess and is not authorized by this evidence.

## Bounded diagnostic correction

The next host-green candidate transports the selected deadline through Java,
JNI, and the native SurfaceControl presenter. Native requires the current row
for that token to retain the exact same deadline and still have the unchanged
2.000 ms reserve before consuming prepared work. It records:

- the immutable selected frame-timeline deadline;
- transaction-apply start and end monotonic timestamps;
- latch and actual-present timestamps already used by the physical gate.

This distinguishes a stale/revised timeline row from time spent before and
inside `ASurfaceTransaction_apply`. It does not relax any cadence, exact-slot,
content, or safety threshold.

Host qualification artifact:

```text
APK 3225fb6f28454e892a50cd523c5cbf148c9c883564a91a01e7526f7d215b2f7c
owned_surface_control_presenter.cpp aa4d8b0f6861b99e9eb30af0ab2be1c75b33cfb775a9ea6b109d2b914f141114
owned_surface_control_presenter.hpp 9491e32ce2eea9ecb27ebbd2b1ef1b55fa1cbe37a343ff04a2983adeccda5387
rife_benchmark_jni.cpp 582ad8375ce46d9e80242d96a8dde60bff6633a97392082dd4d673fa67eae7fd
NativeRifeBridge.java 453cd4c9d377edd51587e5719734325b777fea2b0d04d6e6c347c261e81a5885
RifePresentationTransport.java e4d0c7ea88837cee9f979c4c6e5afd65f40c498257dcf7ee7afaa450797037df
```

Host gates:

- focused RIFE timing, packaging, and systemwide tests: 92 PASS;
- unified Android Java suite: PASS;
- full native RIFE and qualification APK build: PASS.

No physical claim is attached to this new artifact yet.

## r100c post-proof reserve exhaustion

The immutable-deadline APK was then exercised in a bounded direct Ocarina run
under `.evidence-rife-oot-r100c-immutable-deadline/`.  The native entry check
accepted the selected compositor row, but the cold endpoint proof pipeline
consumed its remaining reserve before the SurfaceControl transaction could be
constructed:

```text
RIFE endpoint Vulkan import prepared sequence=1 wallNs=37485520
RIFE endpoint Vulkan import prepared sequence=2 wallNs=21350052
SurfaceControl endpoint present failed:
SurfaceControl frame timeline lacks submission reserve
```

This was safe but too destructive: the exception permanently disabled the
qualification route before it could measure steady physical delivery.  The
next candidate therefore treats a revised or expired immutable compositor row
after proof submission as one non-visible request.  Native returns a distinct
status before creating a transaction or physical present ID; Java retains the
already-submitted proof request only long enough to drain its GPU/content
result, records the adjacent-pair safety assessment, and returns `NOT_READY`.
It does not retry, catch up, fabricate a frame, increment the present ID, or
weaken the unchanged 2.000 ms reserve.

Host-frozen r101 candidate:

```text
APK 9891f22c7a5e50cf78e09602ff58e75f8cbf44a991519c7b832d4764c93651f3
owned_surface_control_presenter.cpp c608bbe1ac09c1dbd43f4c87f45e72b6cfed9771a7c9939cf65b507859077e26
owned_surface_control_presenter.hpp 77709956787835c8d3eee1f5b50d894948c14dcf30479a1110921ace1f147d49
rife_benchmark_jni.cpp 80b306700eec2d7aa602ac4379dbecd0a662e6cf42ed802fe1bfbe3e6ed5e476
NativeRifeBridge.java 453cd4c9d377edd51587e5719734325b777fea2b0d04d6e6c347c261e81a5885
RifePresentationTransport.java 8f633cff305bf92f52a49e1e0cd526453789caca0fadfed73ccacf1a829b6a6d
```

Host gates on these bytes:

- focused RIFE timing, packaging, and systemwide tests: 92 PASS;
- unified Android Java suite: PASS;
- full native RIFE and qualification APK build: PASS.

No physical qualification claim is attached until the bounded r101 run.

## r101 physical result: reserve skip PASS, desired-time STOP

Evidence directory:

```text
.evidence-rife-oot-r101-nonfatal-reserve/
```

The first cold post-proof row expired after GPU submission and followed the new
nonfatal path exactly once:

```text
reason=compositor-reserve-post-work left=3 right=4 generated=0
```

There was no transport teardown or native submission exception.  The GPU proof
was drained and later endpoint/pair processing continued, proving the bounded
status-2 ownership correction physically.

The generated 20-to-40 rate path later activated, but exact physical timing
still failed on endpoint presentation 707:

```text
contentNs=243729462414088
desiredNs=243729460414088
timelineExpectedNs=243729462390998
timelineDeadlineNs=243729452057665
applyStartNs=243729430868429
applyEndNs=243729430993897
latchNs=243729460553272
actualNs=243729470748533
```

The transaction was applied 21.064 ms before the selected compositor deadline,
so neither Java/JNI overhead nor RIFE GPU work caused this miss.  The explicit
desired-present bound instead held the transaction until approximately
`content-2 ms`; it latched 8.496 ms after the composition deadline and became
visible one Thor scan late.  The unchanged physical gate correctly disabled
generation.

The local Android NDK contract states that `setFrameTimeline` selects the
timeline's expected presentation, while `setDesiredPresentTime` separately
requests presentation *at or after* its timestamp.  The next arm therefore
uses the immutable, deadline-validated frame-timeline token alone for tokenized
transactions.  Desired-present remains only for the legacy no-token path.  No
reserve, cadence, slot tolerance, phase, content, or fallback gate changes.

Host-frozen r102 candidate:

```text
APK 0c07ef6592b7ae1de6cbf0403073815da9e0fe6a68b04153829f7cf6466a79e2
owned_surface_control_presenter.cpp db99db1b47a071404891ea4ea17fc23fdc9652bbe404551e8db0878f8c1d32a3
owned_surface_control_presenter.hpp 77709956787835c8d3eee1f5b50d894948c14dcf30479a1110921ace1f147d49
rife_benchmark_jni.cpp 80b306700eec2d7aa602ac4379dbecd0a662e6cf42ed802fe1bfbe3e6ed5e476
RifePresentationTransport.java 8f633cff305bf92f52a49e1e0cd526453789caca0fadfed73ccacf1a829b6a6d
```

Host gates on these bytes:

- focused RIFE timing, packaging, and systemwide tests: 92 PASS;
- unified Android Java suite: PASS;
- full native RIFE and qualification APK build: PASS.

This candidate has no physical claim until a new bounded run.

## r102 physical result: long token-only run, one prediction retarget

Evidence directory:

```text
.evidence-rife-oot-r102-token-only/
```

The token-only path materially improved the live result.  After bounded cold
reserve skips and re-prime, epoch 118 sustained exact Ocarina 20-to-40
operation for hundreds of physically joined rows:

```text
source=20.000 target=39.960 swap=39.975 physical=39.981
externalTimingQualified=1
externalDesiredSlotMisses=0
externalContentNumericPassed=1
externalTimingEndpoint=497
externalTimingGenerated=498
```

The first rejected physical row was endpoint presentation 1082:

```text
contentNs=244241027906317
desiredNs=244241025906317
timelineVsyncId=119172608
timelineExpectedNs=244241027883998
timelineDeadlineNs=244241017550665
applyStartNs=244240996573650
applyEndNs=244240996711775
latchNs=244241026059119
actualNs=244241036251671
enqueueWallNs=685625 gpuWorkNs=163437
```

The transaction was applied 20.839 ms before the selected composition
deadline.  The adjacent rows were applied with the same reserve and landed on
their exact expected scans.  There was no correlated GC, thermal, callback,
fence, or app-thread stall.  Crucially, the rejected row's latch is
`deadline + 8.508 ms` and its physical timestamp is
`expected + 8.368 ms`: both align with the selected prediction moving exactly
one Thor scan later after submission.  The prior r90, r98, and r101 failures
have the same signature.  Android documents a frame-timeline ID as a target
SurfaceFlinger *tries* to meet; it is not an immutable reservation.

The unchanged fail-closed gate rejected the row and direct presentation
continued.  Cleanup then force-stopped both apps, deleted every frame-generation
global, slept Thor, set brightness to zero, and verified asleep/PIDs absent.

## r103 host candidate: prediction-only admission, absolute presentation

The frame-timeline row remains required as exact pre-submit evidence: ID,
expected timestamp, deadline equality, and the unchanged 2 ms compositor
reserve are all checked.  The transaction no longer calls
`ASurfaceTransaction_setFrameTimeline`, because that would hand final scan
selection back to a revisable prediction.  It instead calls only
`ASurfaceTransaction_setDesiredPresentTime` with EmuFusion's immutable
`content - 2 ms` driver bound.  The preceding Thor scan is earlier than that
bound, so the first legal physical scan remains the exact content scan.  The
same public desired-present path previously passed a 240-presentation native
SurfaceControl soak.

No cadence, phase, content, slot-error, reserve, maximum-generation, fallback,
or physical-presentation gate changed.

Frozen host artifact:

```text
APK 843549b00c4d8f3d39765549c1f29c14257b96c228fb484ca484588add4b257e
owned_surface_control_presenter.cpp a063079dbc06c618782828eb9dbdf8877e955c26c4e50ce5d2dd703647f7229c
owned_surface_control_presenter.hpp 3618ecd5784b28b90af8da32ac0d3b9a13137719d0a14d202b8aa5f1cf303e6f
PhysicalPresentationDeadline.java 097c5a25c096ede544eeeffaae227cee22c88774f1f4c418d2aa36f7c1631ffb
FrameGenerationPresentationRequest.java ce5d6411083bf79bbfa9214774153c2aa15b03a06cd2ed4bc5a285c193a99fb9
rife_benchmark_jni.cpp 80b306700eec2d7aa602ac4379dbecd0a662e6cf42ed802fe1bfbe3e6ed5e476
RifePresentationTransport.java 8f633cff305bf92f52a49e1e0cd526453789caca0fadfed73ccacf1a829b6a6d
```

Host gates:

- focused RIFE timing, packaging, and systemwide tests: 92 PASS;
- unified Android Java suite: PASS;
- full native RIFE and qualification APK build: PASS.

## r103 physical result: desired-only still has an occasional late latch

The first two launch attempts were invalid setup attempts and carry no product
claim. The actual bounded run used the packaged Phase-1 N64 core and the ROM's
verified removable-storage path:

```text
.evidence-rife-oot-r103c-prediction-only-desired/
APK f38d9cf4cd1dc4b5d510c13261a1f64755340e0d59f272f54d5539f64e378331
```

The desired-only path reached Ocarina, settled at the exact 20-to-40 route,
and produced twenty consecutive calibrated physical timing samples with no
slot miss. It then failed closed at presentation 200:

```text
contentNs=246037977886446
desiredNs=246037975886446
timelineExpectedNs=246037977857664
timelineDeadlineNs=246037967524331
applyStartNs=246037947044631
applyEndNs=246037947312235
latchNs=246037969992079
actualNs=246037986217131
```

The transaction was applied 20.212 ms before the selected composition
deadline. Unlike r102's server-side token retarget, this row's desired-only
latch arrived 2.468 ms after that deadline and the image became visible one
scan late (`actual - expected = 8.359 ms`). Therefore removing the token
eliminates one failure mechanism but does not make absolute desired-present a
hard compositor reservation. The unchanged gate disabled generation at once.

The next bounded design must obtain compositor work before the target scan
without permitting early visibility. A promising but still unproven bracket
is the immediately preceding frame-timeline token plus the existing
`content - 2 ms` not-before timestamp: the earlier token supplies a full scan
of compositor margin while the timestamp forbids that preceding scan from
being shown. This needs an explicit predecessor-token identity/period contract,
reserve checks, adversarial host tests, and an independent audit before another
device run; it must not be approximated by loosening the physical slot gate.

After r103c, the harness neutralized every controller axis, force-stopped both
apps, removed all frame-generation globals, slept Thor, set brightness to zero,
and independently verified `mWakefulness=Asleep`, zero brightness, absent app
PIDs, and null proof/RIFE settings.

## r104 frozen host candidate: predecessor-token bracket

r104 implements the bounded bracket identified by r103c. The immutable visible
content target remains compositor row `T`, while the transaction is assigned
the exact immediately preceding frame-timeline token `T-1`. The separate
desired-present timestamp remains `content - 2 ms`, which lies after `T-1` and
therefore prevents the early token from authorizing early visibility. The
token supplies one full panel scan of compositor preparation margin.

Selection fails closed unless both adjacent rows are present, distinct,
unexpired, unambiguous, and separated by exactly one measured panel period.
The predecessor deadline must retain the unchanged 2 ms native submission
reserve. Native code rechecks the selected token/deadline immediately before
transaction creation, assigns the predecessor token first, then applies the
independent desired-present bound. No cadence, interpolation, content,
maximum-generation, fallback, or physical-slot acceptance gate is relaxed.

The output planning lead is 22 ms and direct bootstrap is three scans ahead so
the predecessor deadline can still be met. Visible output selection remains
the same exact 20-to-40 cadence.

Frozen host artifacts:

```text
APK 11e92a639f6f9407891d0244fc3e49725eb27c7fac4eae9a045a40961109c462
CompositorFrameTimeline.java 34516bfe3cbc6a677e744cbc5626b60460dd7ec6447b9c2aae2e5ce60285e440
FrameGenerationPresentationRequest.java d452e14dd6c5e9370db890a8b1bc7337b83b2cf03eea3cd22295d8d892c18925
PhysicalPresentationDeadline.java c0f9659cbef9cba1e49ec987853db5997de90f592ab243139b737656b18ae47d
DisplayFrameGenerator.java 6cc1387aa5b9bb7e415d8f27d69f068e2ee9dc1f1e0bb78bcd0e53d9833409d6
owned_surface_control_presenter.cpp 6948e01811c598bb8d0be4551f5f049e43e4df8b11e43477ca1cbfb61b0a9cfe
owned_surface_control_presenter.hpp fc6058006562adf84cde97fb0891d526f76c9005d075eecf05de69e3785f695f
```

Host gates on these exact product bytes:

- unified Android Java suite: PASS;
- focused RIFE timing, qualification packaging, and systemwide tests: 92 PASS;
- complete qualification APK build and one-app package verification: PASS;
- native ASan/UBSan suite: PASS.

The broader tools discovery reached 1,404 tests; its three failures are
pre-existing unrelated dirty-tree locks (theme hash, Cemu lock size, and an
external-emulator manifest query). All frame-generation-focused gates pass.

## r104 physical result: bracket improves reserve but cannot reserve a scan

Evidence directory:

```text
.evidence-rife-oot-r104-predecessor-token-bracket/
```

The bounded run reached Ocarina and sustained exact 20-to-40 generation. The
last complete health record before rejection reported:

```text
source=20.000 target=39.987 swap=39.982 physical=39.690
externalTimingQualified=1
externalTimingSamples=135
externalTimingEndpoint=68
externalTimingGenerated=67
externalDesiredSlotMisses=0
externalContentNumericPassed=1
```

The transaction bracket behaved normally for those joined physical samples,
then presentation 223 landed exactly one Thor scan late:

```text
contentNs=247636319511351
desiredNs=247636317511351
timelineVsyncId=119532318
timelineTokenExpectedNs=247636311145664
timelineExpectedNs=247636319478997
timelineDeadlineNs=247636300812331
applyStartNs=247636279237824
applyEndNs=247636279409490
latchNs=247636309359282
actualNs=247636327847511
```

The predecessor transaction was applied about 21.4 ms before its compositor
deadline. Its latch occurred before the predecessor's expected scan, so this
was not an app/GPU submission-reserve failure. Nevertheless, the physical
presentation was `8.369 ms` after the target row—one panel scan late. The
unchanged physical gate rejected that first miss and switched to direct
presentation. There was no fatal process failure.

This falsifies the predecessor-token bracket as a hard reservation mechanism.
Combining an early frame-timeline token with a later desired-present hint can
usually land on the target, but Android still does not contractually reserve
that exact physical scan. Do not weaken the slot gate or call this qualified.

The cleanup trap neutralized the controller, force-stopped both apps, removed
all frame-generation globals, and slept Thor. Android restored brightness 8
during the sleep transition; a subsequent explicit write while already asleep
set it to zero. Independent final verification recorded `Asleep`, brightness
zero, both PIDs absent, and all qualification settings null. Future harnesses
write brightness zero only after the sleep transition settles.

## OLED/device cleanup

The bounded r99b harness stopped at the first failure and restored the device.
The device has subsequently been rechecked without waking it:

```text
mWakefulness=Asleep
screen_brightness=0
emufusion_framegen_proof=null
emufusion_framegen_rife=null
emufusion_framegen_lsfg=null
com.thorium.preview PID absent
org.pegasus_frontend PID absent
```

Keep Thor black during all host work. Wake it only for a bounded test of a
frozen candidate, and use unconditional cleanup to force-stop both apps, remove
all frame-generation globals, sleep, set brightness zero after sleep, and verify
the final state even when the test fails.
