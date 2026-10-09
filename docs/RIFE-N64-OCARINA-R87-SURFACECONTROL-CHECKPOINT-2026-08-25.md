# RIFE N64 Ocarina r87 SurfaceControl checkpoint — 2026-08-25

## Outcome

This checkpoint is **not a frame-generation qualification pass**.

The host-side SurfaceControl recovery now distinguishes an `OnComplete`
callback that explicitly omits its physical-present fence from a valid physical
completion. The active RIFE transport marks that exact presentation ID dropped,
emits no fabricated timing row, preserves submission order, and retains the
AHardwareBuffer until SurfaceFlinger's later release fence permits retirement.
Java derives the same dropped ID from the next physically proven timing-row gap.
The generic LSFG self-test/runtime remains fail-closed on missing fence evidence.

The bounded r87 run exceeded the prior r86 failure point without a missing-fence
exception: it reached more than 1,300 submitted/physical presentation IDs and
logged no `SurfaceControl timing poll failed`, `present fence unavailable`, or
fatal exception. This run did not itself receive a fence-less callback, so it
proves long-run non-regression past the old threshold but does not physically
exercise the new drop branch.

R87 later failed closed for a separate reason. At 20-to-40 operation, two API 33
callbacks supplied seven FrameTimelines each but none had a compositor deadline
still live at selection time. The second missed callback was followed by one
physical presentation a scan late:

```text
sample=1 targetFromNowNs=22802954 supplied=7 live=0
sample=2 targetFromNowNs=21307637 supplied=7 live=0
presentId=1128 desiredNs=228684396548071 actualNs=228684406903595
```

The unchanged physical-slot gate correctly quarantined generation and continued
endpoint-only direct presentation at 20 Hz. Before quarantine, the stable path
had zero physical drops/unavailable rows and exact 20-to-40 content/timing proof;
after quarantine, final telemetry was direct 20 Hz with
`externalFrameTimelineUnavailable=2`.

## Frozen test artifact and evidence

Qualification-only debug APK:

```text
/Users/tyleryoung/Code/pegasus-lucent/unified-android/build/lucent-3.2.16-rife-framegen-qualification-e993fc2181b0d84f24c1115322c3231b62f27ea43792472e140a93014764d0ee.apk
SHA-256 e993fc2181b0d84f24c1115322c3231b62f27ea43792472e140a93014764d0ee
```

Physical log:

```text
/Users/tyleryoung/Code/pegasus-lucent/.evidence-rife-oot-r87-surfacecontrol-drop-recovery/live-logcat.txt
```

Relevant source hashes:

```text
owned_surface_control_presenter.hpp 1833cabd519aab98d93ee9f452c4c1c6cb303d157acb15a11e84f4b80b1cc88b
owned_surface_control_presenter.cpp 0e79cdcf4a2a6a049bff606f4111882c63bb904f0551b8b2ae2a9249282f5975
lsfg_qualification_jni.cpp efb89b9539af60915589d61684e93f90292c999f6443f530f35fe33409cda695
rife_benchmark_jni.cpp e23bc338fe606c73f59558660bc316226433474bf5d6655deac2e22cf37859ed
RifePresentationTransport.java 5f9c823114f393c772649494ece0cfa3d411290415d1801ac369bbc4d5e10c9d
```

Host gates:

- unified Android Java suite: PASS;
- focused systemwide/RIFE timing/packaging: 91/91 PASS;
- Phase 1 + Phase 2 + RIFE content-addressed APK build: PASS;
- full tools discovery: 1,399/1,403 PASS, with four failures reduced to three
  unrelated existing worktree issues after updating the stale RIFE packaging
  assertion (theme frozen hash, Cemu source lock, external-emulator queries).

## Next safe step

Diagnose why the two r87 callbacks exposed only expired compositor deadlines
despite a target more than 21 ms in the future. Do not widen the 250-us target
identity tolerance, accept an expired deadline, synthesize a physical timestamp,
or weaken the one-scan late rejection. Any next arm must first be host-tested,
then use one bounded Thor run.

## Thor OLED state

After r87 the app was force-stopped, both RIFE/proof switches were deleted,
brightness mode was returned to manual, Android was put to sleep, and brightness
was set to zero. Verified final state:

```text
mWakefulness=Asleep
screen_brightness=0
emufusion_framegen_proof=null
emufusion_framegen_rife_qualification=null
com.thorium.preview PID absent
```

Do not wake Thor for host work. Wake it only for a bounded device test and repeat
the same immediate black/off cleanup afterward, including on failure.
