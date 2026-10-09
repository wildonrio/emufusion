# Frame-generation uniform scheduler host audit — 2026-08-26

Status: **HOST PASS; PHYSICAL CERTIFICATION STILL REQUIRED**

This checkpoint audits the current production scheduler against the Thor
contract without waking or changing the Android device.

## Production route

`DisplayFrameGenerator` calls `selectBufferedPresentation(...)` and commits a
decision only after a successful physical swap. It does not call the older
arrival-driven `selectPresentation(...)` / `presentationDue(...)` path.

The current fixed-120 target table is:

- 20 -> 40 (three panel scans)
- 30 -> 60 (two panel scans)
- 40 -> 60 (two panel scans)
- 50 -> 60 (two panel scans)
- 60 -> 120 (one panel scan)

The live tests explicitly prove fixed minimum and maximum scan gaps for
20-to-40, 40-to-60, 50-to-60, and 60-to-120; TWINE's 30-to-60 ownership and
preparation lattice is also covered. Source credits and timestamp-derived
phase enforce the maximum-2x rule, and failed swaps do not commit a real,
synthetic, or presentation count.

## Cleanup in this checkpoint

Orphaned legacy test assertions still described the rejected 40-to-80 and
50-to-100 schedules. They were corrected to the uniform-divisor policy. A
systemwide regression now rejects reintroduction of the old target table or
the old 50-to-100 assertions.

## Host evidence

- `unified-android/test.sh`: PASS, including
  `AdaptiveFrameRateControllerTest`.
- `python3 -m unittest tools.tests.test_systemwide_frame_generation`: 78/78
  PASS.
- Focused uniform-policy regression: PASS.
- `git diff --check` for the touched files: PASS.

Frozen hashes for this checkpoint:

- `AdaptiveFrameRateController.java`:
  `d35ed1cd9f8186bbbbf8fcb34f9375db8bacd996526e7666820108af016138c9`
- `DisplayFrameGenerator.java`:
  `1d79417009dd808b3f4a84578b7a32282671c40354faf429ec4c7b5b9aa52bda`
- `AdaptiveFrameRateControllerTest.java`:
  `05746eae3bb0b2f3b5b1592966a305b59dbbfa569df13aca6e7f76a8f48a4838`
- `test_systemwide_frame_generation.py`:
  `f348ce99c16512326bcb1baeae6d92aa6d0009e0159375d0dd1ac036085c5c60`

## What this does not prove

This is not a system qualification. No APK was built or installed and Thor
was not awakened. N64 certification still requires moving-game physical runs,
SurfaceFlinger agreement, constant physical scan spacing, and clean visual
inspection. The most recent TWINE device attempt remains invalid because the
Android system-server watchdog killed the system before EmuFusion could enter
the qualified route; see
`RIFE-N64-TWINE-R180-R183-COLD-PRIME-STOP-2026-08-26.md`.

