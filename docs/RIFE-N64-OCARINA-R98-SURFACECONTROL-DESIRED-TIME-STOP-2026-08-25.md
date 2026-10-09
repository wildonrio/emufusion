# RIFE N64 Ocarina r98 SurfaceControl desired-time STOP — 2026-08-25

## Verdict

STOP. The bounded Thor run disproved the hypothesis that pairing the selected
frame-timeline token with an explicit `ASurfaceTransaction_setDesiredPresentTime`
would eliminate the rare one-scan miss. It ran cleanly for roughly 75 seconds,
then the unchanged fail-closed physical gate rejected one REAL endpoint exactly
one Thor scan late.

This was a qualification-only build and does not enable product routing.

## Frozen candidate

```text
APK 271d3d50a8952bdeb6d0410e0490ce885e4c11c34f97ff0297017f7605978851
owned_surface_control_presenter.cpp da3c412b4003387331eac7b1d3d7bf588f8e4bd6633bba9f09ce5de5d15d4203
PhysicalPresentationDeadline.java 6c15f799c3a015e87c17af0fd62a5b7f2b08afcd4528fa1fa9b313d96c7fef76
FrameGenerationPresentationRequest.java a0ad92ae7fd6bf3fdca8aee66477a8c1373c40dd111e418335bb1be27a6a17b7
test_systemwide_frame_generation.py 70c6a43c478afdc14cc2b541db7de2319f850703ff132d64cdf18263dcb9fa5d
```

The correct APK included the pinned internal Mupen64Plus-Next core and RIFE.
An earlier zero-core package was detected during launch, stopped immediately,
and is not evidence.

Host gates before the device run:

- focused RIFE timing, packaging, and systemwide tests: 92 PASS;
- `unified-android/test.sh`: PASS;
- full qualification APK build with explicit experimental-core auto-selection:
  PASS.

## Physical evidence

Evidence directory:

```text
.evidence-rife-oot-r98-explicit-desired-valid/
```

The internal route loaded Ocarina through Mupen64Plus-Next. RIFE warmed before
the input surface became active. The final clean health snapshot before the
failure reported:

```text
source=20.000 target=40.000 swap=39.988 physical=39.996
externalTimingSamples=108
externalTimingEndpoint=54
externalTimingGenerated=54
externalDeadlineMisses=0
externalDesiredSlotMisses=0
externalContentNumericPassed=1
externalContentMovingGenerated=52
externalContentDistinctMovingGenerated=52
externalCombinedP95Ns=8135208
externalCombinedMaxNs=8257395
```

The first and only rejected row was:

```text
presentId=3991 generated=0 phase=1.000000
contentNs=239064222126546
desiredNs=239064220126546
timelineVsyncId=118458057
timelineExpectedNs=239064222121332
timelineDeadlineNs=239064211787999
latchNs=239064211927031
actualNs=239064230461926
enqueueWallNs=775781 gpuWorkNs=164271
deadlineMisses=0 desiredSlotMisses=1
```

The selected timeline prediction was only 5.214 microseconds before the
immutable content target. The transaction latched about 10.2 milliseconds
before that target, but crucially it latched **139.032 microseconds after the
selected timeline's own composition deadline**. The buffer then appeared about
8.335 milliseconds after the target: one physical scan late. Endpoint enqueue
wall time was 0.776 milliseconds and GPU work was 0.164 milliseconds, so this
is not RIFE compute overload. It is a transaction-handoff deadline failure that
the old selector authorized because it treated any positive remaining deadline
as meetable.

## Conclusion and next boundary

An explicit desired time can prevent readiness before a timestamp; it cannot
rescue a transaction handed to SurfaceFlinger after that timeline's composition
deadline. Keeping the frame-timeline token did not eliminate the miss because
the transaction crossed that deadline during the final Java/JNI/native handoff.
The broader claim that SurfaceControl itself cannot meet the exact-scan contract
is therefore **not established by r98**.

Do not widen the slot tolerance, ignore a rare row, or reset the evidence
window. The bounded next candidate reserves 2.000 milliseconds for compositor
handoff. Timeline selection rejects a candidate below that reserve; the Java
transport rechecks it immediately before JNI and returns `NOT_READY`; the native
presenter performs the same check immediately before constructing/applying the
SurfaceControl transaction. An unsafe slot is skipped once with no retry or
catch-up. The content timestamp, frame-timeline identity, physical-slot
tolerance, and visual gates remain unchanged. A new Thor run must prove that
every accepted transaction latches before its selected timeline deadline and
that honest cadence remains acceptable.

## OLED/device cleanup

The guard aborted at the first failure. Cleanup then:

- force-stopped `com.thorium.preview` and `org.pegasus_frontend`;
- removed RIFE, LSFG, and proof globals;
- put Android to sleep;
- set manual brightness to zero after sleep.

Verified final state:

```text
mWakefulness=Asleep
screen_brightness=0
emufusion_framegen_proof=null
emufusion_framegen_rife_qualification=null
emufusion_framegen_lsfg_qualification=null
com.thorium.preview PID absent
org.pegasus_frontend PID absent
```

Do not wake Thor for host investigation. Wake it only for the next bounded
physical test, and immediately restore this black/off state afterward.
