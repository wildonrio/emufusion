# RIFE N64 TWINE r180-r183 cold-prime checkpoint — 2026-08-26

## Verdict

**HOST PASS; PHYSICAL QUALIFICATION REMAINS STOP.**

The current top-screen TWINE 30→60 qualification APK is preserved at:

```text
unified-android/build/lucent-3.2.16-rife-framegen-qualification-c6d22a9d4821f27db0a68585ca924b1af575323329f4ea6189413b47817775d2.apk
SHA-256 c6d22a9d4821f27db0a68585ca924b1af575323329f4ea6189413b47817775d2
```

It is not qualified. No r180-r183 run produced a long moving-game generated
window, a SurfaceFlinger cadence pass, or manual artifact acceptance.

## What the four runs proved

- **r180** exposed an invalid one-scan pre-calibration Direct planner. The
  external WSI slot remained occupied and the transport failed closed with
  repeated swapchain-acquire starvation. The uncalibrated Direct path now uses
  the generic future external deadline again.
- **r181** removed that cold-start starvation and sustained roughly 1,900
  endpoint-only Direct presents. Repeated screenshot/OCR inspection then
  stalled the compositor/app for about eight seconds. A completed request from
  the ended Direct epoch reached the physical clock after the new scheduler
  epoch and correctly exposed an epoch-boundary accounting gap. The current
  source permits re-anchoring only for a non-generated row from an ended Direct
  epoch; generated or current-epoch inconsistencies still fail closed.
- **r182** reached a narrow native-release deadline failure while Android was
  under screenshot/process-reclamation pressure. The timing gate was not
  loosened. All screenshot checkpoints were removed from navigation and active
  timing collection.
- **r183** never reached the in-window route or frame-generation activation.
  Android's watchdog killed `system_server` after ActivityManager and
  WindowManager deadlocked. The decisive log is:

  ```text
  WATCHDOG KILLING SYSTEM PROCESS
  Blocked in monitor com.android.server.am.ActivityManagerService
  waiting to lock WindowManagerGlobalLock
  Watchdog: *** GOODBYE
  ```

  EmuFusion did not report a Java/native fatal crash. This is a device-system
  failure and supplies no positive or negative frame-generation verdict.

## Current cold-prime safeguards

- A complete private RIFE pipeline must retire before generated presentation
  can activate. Its output is discarded; it authorizes neither a pair nor a
  visible frame.
- Before the physical clock is calibrated, a visible controller slot is not
  selected while the transport has a pending native presentation or private
  preparation. This is a zero-wait capacity check only.
- The TWINE navigator replays the independently established fresh-session
  sequence without `screencap`, UIAutomator, OCR, or screen recording.
- The harness now rejects Android watchdog death, `DEAD_OBJECT`, or loss of
  `settings`, `input`, `activity`, or `window` services. It retains the trapped
  cleanup that stops both apps, clears test overrides, suppresses ambient
  display, sets brightness to zero, and sleeps the device.

Current relevant source hashes:

| File | SHA-256 |
|---|---|
| `DisplayFrameGenerator.java` | `1d79417009dd808b3f4a84578b7a32282671c40354faf429ec4c7b5b9aa52bda` |
| `ExternalFrameGenerationTransport.java` | `519d89ae0e508bcdb0edc8ed40d24e0c0c404ab0d7ecf553665ff07429345bce` |
| `RifePresentationTransport.java` | `bab0041c054b8a706daf24c27a47224a62062515683df08ce5f0656ae7740927` |
| TWINE physical harness | `50452e42c12923c338f2180db867b9cccead06f4f55ed66e9c2570f283d413fd` |
| zero-screenshot navigator | `73b13d6d2dc1a75d233a2506ffc616072512d0b414f053d5635701db52017c29` |

The final two harness hashes include the post-r183 Android-service watchdog
checks and are not packaged in the APK.

## Host verification

After the post-r183 harness hardening:

```text
python3 -m unittest \
  tools.tests.test_rife_framegen_qualification_packaging \
  tools.tests.test_systemwide_frame_generation
85 tests PASS

cd unified-android && sh test.sh
PASS
```

`bash -n` for the harness and `py_compile` for the no-screenshot navigator also
pass.

## Next physical step

Do not run another device qualification merely to repeat r183. First verify a
healthy post-boot `settings`/`input`/`activity`/`window` service set while the
OLED remains asleep. Then run exactly one bounded top-screen TWINE session with
the no-screenshot navigator. If Android services fail, stop and restore the
black screen; do not classify the backend. If generated 30→60 activates, the
unchanged physical-slot, SurfaceFlinger, numeric-content, and long manual
moving-game gates remain mandatory.

LSFG remains a separate internal feasibility path. The THS permission request
is still a draft in `docs/THS-LSFG-PERMISSION-REQUEST-2026-08-25.md`; no written
redistribution or naming permission has been received.
