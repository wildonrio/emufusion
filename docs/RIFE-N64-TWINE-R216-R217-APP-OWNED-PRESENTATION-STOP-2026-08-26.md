# RIFE N64 TWINE r216-r217 — app-owned presentation boundary

Date: 2026-08-26

Status: **HOST PASS / PHYSICAL STOP**.

This checkpoint does not qualify TWINE, N64, RIFE, or any product backend.
The physical safety gate rejected one visible scan miss exactly as intended.

## OLED and device state

The owner requires both Thor OLEDs to be illuminated only during bounded
device testing. Before r216, Android services had recovered but the launcher
was visible. EmuFusion and Pegasus were force-stopped, brightness was set to
zero, and the ordinary idle timeout was reduced to 15 seconds. No sleep key
was used. At the final check after r217:

- `mWakefulness=Asleep`;
- both physical display devices reported `state OFF, committedState OFF`;
- top hardware brightness node was `0`;
- EmuFusion and Pegasus had no process;
- all frame-generation qualification globals were removed.

The lower-panel brightness node retains its vendor last-requested value while
the lower display is powered off; Android and SurfaceFlinger both report the
physical display OFF. Do not wake either panel for host-only work.

## r216: safe 120-Hz wake defect

Evidence: `.evidence-rife-twine-r216-clock-overlay/`

The saved top preference was 120 Hz, but with `min_refresh_rate` and
`peak_refresh_rate` unset Thor woke the top OLED at 60 Hz while the lower OLED
woke at 120 Hz. The harness correctly stopped before launching gameplay:

```text
top 120-Hz display mode did not remain stable for two seconds
```

The harness now writes the temporary `120.00001` min/peak policy while both
displays are still asleep for either forced top-mode test. The 120-Hz branch
does not perform a live mode transition. Cleanup restores the owner's exact
prior null/value settings.

Frozen harness checkpoint:

- `.evidence-rife-twine-r146-30to60/run-device-test.sh`
  `2ec1696b752c63d3f34532ddc7e575880b38e1f0bd1f1996e17cbf9880fe925e`
- `tools/tests/test_rife_framegen_qualification_packaging.py`
  `668bcf925434aff4424d940042e4d07543012de619073bf1b694d2423383e230`

`bash -n` and 27 focused packaging/Android tests passed.

## r217: exact physical result

Evidence: `.evidence-rife-twine-r217-prewake120/`

APK:

```text
unified-android/build/lucent-3.2.16-rife-framegen-qualification-
c1c1c397c6331d310c52e64095351ffad206721644c197563c939113d0e0f671.apk
SHA-256 c1c1c397c6331d310c52e64095351ffad206721644c197563c939113d0e0f671
```

The pre-wake policy worked: both panels stabilized at 120.00001 Hz without a
live 60-to-120 transition. The owned no-screenshot menu replay reached moving
TWINE gameplay. Source provenance was explicit:

```text
Renderer policy engine=mupen64plus-next ...
sourceTimeline=mupen-vi-origin-filtered
Producer clock engine=mupen64plus-next declaredVideoHz=60.000000000
stamp=core-run-sequence sourceTimeline=mupen-vi-origin-filtered
```

The source classifier then proved an exact retained 30 Hz endpoint clock:

```text
candidate=30.000,count=300,one=300,two=0,other=0,
modalGap=1,ordinalBad=0,logicalHz=30.0000,rmsPpm=0,maxPpm=0
```

RIFE activated at exact midpoint phase. Four complete HEALTH windows delivered
about 59.96 physical frames per second:

| Window | Physical rate | Source | Target | Timing qualified |
|---|---:|---:|---:|---:|
| 1 | 59.955 | 30.000 | 59.975 | warming |
| 2 | 59.959 | 30.000 | 59.975 | warming |
| 3 | 59.961 | 30.000 | 59.975 | yes |
| 4 | 59.962 | 30.000 | 59.975 | yes |

Those windows had exact `phaseMin=phaseMax=0.500000`, no dropped physical
rows, no endpoint/content failures, and no scene-cut-risk output. This is
strong positive evidence for endpoint identity, source measurement, target
selection, interpolation phase, and honest physical accounting. It is not a
qualification because the following row missed.

At generated present ID 3240, the private Vulkan path landed exactly one
120-Hz scan late:

```text
contentNs=11819675825745
desiredNs=11819673825745
actualNs=11819684124604
gpuWorkNs=8790468
desiredSlotMisses=1
```

The visible cadence guard immediately logged:

```text
External generation disabled after physical-slot miss
```

and returned to Direct. This is a real visible hitch. The gate must not be
relaxed, averaged away, or reclassified as a badge issue.

## Architectural conclusion

The direct Vulkan FIFO swapchain has now accumulated a long history of
release-window, acquire, and compositor-latch tuning. r217 demonstrates the
remaining problem in the strongest form: model/content/timing evidence can be
healthy for hundreds of rows, yet one backend-owned WSI row can still latch a
scan late. More release-window tuning does not move the design toward the
stated product contract that EmuFusion owns physical presentation and a
backend only generates an image.

The next arm should therefore be an incompatible qualification path:

1. RIFE/LSFG receives exact adjacent retained endpoints and a timestamp phase.
2. It writes a private RGBA8 `AHardwareBuffer` and signals completion without a
   blocking wait or visible swapchain.
3. EmuFusion imports that completed buffer into its existing EGL/GLES
   presentation context, validates exact pair/phase/epoch ownership, and owns
   the visible `eglPresentationTimeANDROID` plus `eglSwapBuffers` operation.
4. A generated image not completed before its immutable output slot is skipped
   and the pair is re-primed; it is never presented late or caught up.
5. Only the app-owned physical-present tracker may increment `A`.
6. The old direct-WSI arm remains quarantined evidence and is not promoted.

Reuse the existing native prepared-output machinery and its three private
`AHardwareBuffer` slots; remove SurfaceControl/WSI submission from the new
backend interface rather than adding another scheduler. Add a JNI EGLImage
import/bind helper only if Android's Java EGL API cannot import the completed
buffer directly. The handoff must preserve explicit release-fence ownership,
zero-timeout readiness polling, exact sequence/timestamp/phase/epoch identity,
and safe slot recycling.

Before another physical run, host tests must prove: no backend-visible Surface,
no `vkQueuePresentKHR`/SurfaceControl call in the completed-image arm, no
blocking fence wait, exact stale-epoch rejection, swap-success-only accounting,
and Direct fallback when a completed image is unavailable. Then rebuild and
repeat the same bounded top-screen TWINE 30-to-60 run, returning both OLEDs to
black on every exit path.

