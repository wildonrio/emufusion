# RIFE N64 Ocarina r232 app-owned timing checkpoint — 2026-08-27

## Verdict

**PHYSICAL TIMING + NUMERIC CONTENT PASS; MANUAL VISUAL CERTIFICATION PENDING.**

The current app-owned EGL presentation path sustained Ocarina's exact
20-to-40 mapping for 64.2 seconds of controlled outdoor motion on Thor's top
120-Hz panel. The unchanged verifier passes timing and numeric moving-content
evidence. It deliberately leaves `externalContentManualPassed=0`, so this is
not a final product qualification until a human observes the live moving game
without ghosting, warping, periodic stalls, or fabricated frames.

## Immutable run

```text
Evidence: .evidence-rife-oot-r232-app-owned-current/
APK: unified-android/build/lucent-3.2.16-rife-framegen-qualification-916bab3aec896189fb476b82ec8c1cf05148d9bb081e153443e7c6c058ebd78c.apk
APK SHA-256: 916bab3aec896189fb476b82ec8c1cf05148d9bb081e153443e7c6c058ebd78c
Qualification session: qa-c3f559fc1c1f45489aacb7f1c354aa35
Activation log line: 6414
Active host interval: 64.201336 s
```

The navigation helper proved a visible gameplay HUD and an outdoor scene
before arming frame-generation proof:

```text
gameplayHudVisible=true
outdoorScene=true
greenRatio=0.046397
brownRatio=0.020563
```

## Verifier result

Machine-readable result:

```text
.evidence-rife-oot-r232-app-owned-current/rife-timing-verdict.json
```

Final selected epoch:

```text
sourceHz=20.000
targetHz=40.000
actualPhysicalHz=39.977
presentationEpoch=882
physicalSamples=2638
physicalEndpoints=1319
physicalGenerated=1319
contentProofs=1319
movingGeneratedProofs=1319
scansPerOutput=3
deadlineBudgetNs=24999999
combinedP95Ns=654844
combinedMaxNs=2005416
handledUnsafePairs=0
timingPassed=true
numericContentPassed=true
contentQualityPassed=false
qualified=false
qualificationBlockedBy=moving-game visual/content proof
```

No generated deadline miss, desired-slot miss, early/late slot miss, GPU
budget miss, scene-cut crossing, unsafe pair, endpoint failure, or fabricated
equal-endpoint output occurred in the selected epoch.

## Independent SurfaceFlinger agreement

The active game layer was:

```text
SurfaceView[com.thorium.preview/org.pegasus_frontend.android.MainActivity](BLAST)#628
```

Its latest 126 physical rows report:

```text
actual=39.974508 Hz
actual interval min=25.007760 ms
actual interval median=25.015990 ms
actual interval max=25.024219 ms
desired=39.974466 Hz
desired interval min=25.005222 ms
desired interval median=25.013385 ms
desired interval max=25.027995 ms
```

That is the exact uniform three-panel-scan cadence required by 20-to-40 on
Thor's measured approximately-120-Hz display. It contains no 16.7/33.3-ms
alternation and does not count submissions as physical output.

## OLED and cleanup safety

The first attempt was interrupted when a saved screenshot exposed a stale
orientation assumption in the pre-proof HUD classifier. Its trap immediately
returned both physical OLED backlights to zero. The corrected helper accepts
either current landscape or legacy rotated captures.

After the successful run:

```text
screen_brightness=0
panel0_actual_backlight=0
panel1_actual_backlight=0
com.thorium.preview pid=
org.pegasus_frontend pid=
```

Thor remained awake to avoid its ColorFade deadlock, but both OLEDs emitted no
light. No frame-generation settings remain enabled after cleanup.

## Remaining gate

Repeat a short bounded outdoor-motion run while the owner watches the top
screen. Accept only if panning is visibly smooth with no ghost trails,
geometric warping, doubled HUD elements, periodic hitch, static duplicates, or
endpoint flashes. Numeric evidence alone must never set the manual bit.
