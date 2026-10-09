# Switch runtime-navigation proof audit — 2026-08-10

## Scope

This is a host-only audit of
`unified-android/build/runtime-framegen-v5-switch-03cd44-r2`. It does not use
ADB, operate the Thor, modify `DisplayFrameGenerator`, or weaken any
frame-generation acceptance threshold.

## Frozen evidence

| Artifact | SHA-256 |
| --- | --- |
| `switch-title-01-framegen-logcat.txt` | `6392eab920837305a690fa10825011cdf7423efe314b44ca04c92508db0b7da5` |
| `switch-title-01-gameplay.png` | `731ce6c9a1f924c8e65cc7d2d4eec5d6937c19097f58eef191e694a0d04ed45d` |
| `switch-title-01-framegen-visible-primary.png` | `b6cbdbf564bb147a43fb95f2f7026cc9cc836f62428a7354e4ad42d3d16d0b10` |
| `results.json` | `68700640c2dc1fc75fadc04a5c10a428a15eb2af1946d1dc07f2189217aa4e75` |

## Finding

The old harness did not prove gameplay readiness.

- `switch-title-01-gameplay.png` OCRs as the Game Kitchen startup logo. The
  generic visible-frame gate therefore returned on a boot logo.
- The input trace then sent three unconditional A presses. The first press
  begins at host monotonic `112473 ms`; no saved screenshot binds any one of
  those presses to a recognized prompt or playable menu row.
- The proof worker then alternated both sticks and sent A after every analog
  pair for the full capture. This is menu navigation, not a safe source-motion
  stimulus.
- `switch-title-01-framegen-visible-primary.png` OCRs as `Game / Accessibility
  / Audio / Back`. It is Blasphemous II's in-game settings page, not gameplay
  and not Android Accessibility settings.
- The Eden log independently exposes the missing readiness boundary: two
  `OnOpen: NVDEC video stream started` records at guest times `32.037275` and
  `32.117633`, followed by two matching `OnClose` records at `37.922176` and
  `37.944863`. A pixel-bright logo cannot substitute for that lifecycle.

## Replacement acceptance path

`run_runtime_acceptance_qa.py` now uses a Switch-only, fail-closed state
machine before arming frame-generation proof:

1. Wait for the first guest frame as before, but allow a 30-second NVDEC
   discovery window.
2. If any NVDEC stream opens, require every observed stream to close. A close
   without a corresponding open is malformed evidence.
3. Require the same OCR-recognized actionable UI twice after decoder readiness.
   Logos, cinematics, loading screens, and unrecognized menus are not actionable.
4. Send B only from a recognized settings page; send A only from a recognized
   title prompt or after saturating Up on an OCR-recognized Play/save/difficulty
   menu. Every screen, OCR result, decoder count, and input decision is written
   to `*-switch-navigation.json` with companion full-resolution screenshots.
5. After a proven Play selection, wait through any newly opened NVDEC stream
   and require at least three strong non-menu visible transitions under
   left-stick-only input.
6. During the later v7 frame-generation capture, Switch continues to use only
   the left stick. It cannot accept Options or Accessibility even if the title
   unexpectedly returns to a menu. The existing v7 novel-pixel,
   source-correlation, non-crossfade, and SurfaceFlinger cadence verifier remains
   authoritative.

Unknown UI fails qualification. It never causes another speculative A press.

## Reuse decision

The 03cd44 run cannot be promoted or re-evaluated as passing evidence. Its only
proof-window screenshot is a settings menu, its telemetry uses the retired v5
contract, and the frame-generation gate failed before held-Stop acceptance was
executed. A new signed-APK Thor run is required. The old bundle remains useful
only as a regression fixture for the navigation failure and NVDEC lifecycle.

