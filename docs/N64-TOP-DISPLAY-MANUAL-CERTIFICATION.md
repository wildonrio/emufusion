# N64 top-display manual frame-generation certification

Status: **ready to run; no manual PASS recorded**.

This is the final human-observation gate for the three required N64 rate
families. It supplements, but never replaces, the numeric timing,
SurfaceFlinger, endpoint-identity, and generated-content verifiers.

## Safety and invocation

The guarded harness refuses to wake Thor unless the owner is actively watching:

```bash
EMUFUSION_OWNER_WATCHING_TOP=YES \
  unified-android/tools/run_n64_top_display_manual_qa.sh \
  /absolute/path/to/exact-qualification.apk \
  /absolute/path/to/new-evidence-directory
```

It installs/configures while both OLEDs are black, wakes only for the bounded
test, and traps every normal/error/signal exit. Cleanup force-stops EmuFusion,
clears qualification settings, sets brightness to zero, and requires both
`panel0-backlight` and `panel1-backlight` to report actual brightness zero.

The harness deliberately writes `manual-observer-verdict.txt` as `PENDING`.
Automation is forbidden from turning observation into a PASS.

## What to watch on the top display

| Title | Required stable overlay | Required physical pattern |
|---|---|---|
| Ocarina of Time | `S≈20 T≈40 A≈40 Backend=RIFE` | one output every three panel scans |
| 007: TWINE | `S≈30 T≈60 A≈60 Backend=RIFE` | one output every two panel scans |
| F-Zero X | `S≈60 T≈120 A≈120 Backend=RIFE` | one output every panel scan |

`S` is sustained source cadence, `T` is the selected target, and `A` is
successful physical presentation—not submissions. The lower display is not a
certification target in this run; only a lower-display fault that disrupts the
top display or the application is relevant.

For each title, observe the complete moving-game interval rather than a static
menu or a few seconds of animation. Deliberately watch:

- camera pans and track/wall edges;
- the player model/vehicle against the background;
- nearby moving characters or vehicles;
- HUD text, icons, maps, and energy bars;
- scene transitions, cuts, pauses, and recovery;
- the regularity of motion rather than only the average number in the overlay.

## Immediate FAIL conditions

Any one occurrence fails that title:

- ghost trail, doubled vehicle/character, or doubled HUD;
- bent, bowed, torn, or rectangularly corrupted geometry;
- endpoint flash, interpolation across a cut, or fabricated duplicate;
- periodic hitch, catch-up burst, alternating short/long cadence, or visible
  freeze;
- `A` materially below or oscillating around the declared target;
- wrong target mapping (including 20→60, 30→120, 40→80, or 50→100);
- backend fallback or target change during the accepted interval.

Do not reinterpret a failure as acceptable because the average FPS is close.
Do not lower a timing, cadence, or visual threshold to obtain a pass.

## Evidence binding after observation

A PASS is recordable only after all of the following exist from the same run:

1. exact installed APK SHA-256;
2. successful per-title timing and numeric-content reports;
3. SurfaceFlinger agreement at constant 3-scan, 2-scan, and 1-scan spacing;
4. zero unsafe-pair, scene-cut, deadline, and physical-slot errors;
5. the owner's explicit per-title visual PASS statement;
6. `final-oled-state.txt` proving both hardware backlights returned to zero.

If any title fails, preserve the exact title, scene, approximate time, overlay,
and observed defect. Do not certify the other systems by inference.
