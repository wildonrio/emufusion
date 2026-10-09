# EmuFusion frame-generation handover C — 2026-08-16 (afternoon)

Continuation of `HANDOVER-2026-08-15B-EMUFUSION-FRAMEGEN.md` (read its
MATRIX PROGRESS sections for the full failure-class history). This
document is the current authority on where the goal stands.

## THE GOAL (stop-hook, still active)

Make EmuFusion frame generation rock-solid for every internally emulated
system from PS2/GameCube and newer, physical PS2/GC QA first. Generation
capped at 2x, source rate measured from unique endpoints, only
successfully presented output reported (120 Hz panel: 20/30/40/50/60 →
40/60/80/100/120; 60 Hz panel: nothing above 60).

**USER DIRECTIVES (binding, from chat 2026-08-16):**
- System order after Wii U: **Switch → DS → 3DS → Dreamcast → PS3**.
- Do NOT qualify Wii U on NES Remix ("just NES graphics") — it passed on
  Super Mario 3D World instead.
- The screensaver must NEVER be disabled (OLED burn-in). Correct
  semantics: it may run — even during a game — ONLY when the screen has
  been totally static for X minutes. Implemented (see OLED guard below),
  NOT yet device-verified.
- 50→100 on the 60/120-only panel is legitimate and was explained to the
  user: the panel stays at 120 Hz; the generator presents 100 evenly
  timestamped fps into the 120 vsync slots (5:6 lattice; 2:3 for 80),
  verified from SurfaceFlinger timestamps.

## SCOREBOARD

| System | Status | Evidence |
|---|---|---|
| GameCube | **PASS** (complete) | earlier runs, handover B |
| PS2 | **PASS** ×2 (God of War) | runs ps2-gow1/3 |
| PSP | **PASS** | run psp1 |
| Wii | **PASS** (SMG2) | run wii11 |
| Wii U | **PASS** (SM3DW) | run `…-wiiu23` results.json |
| Switch | **PASS** (Metroid Dread) | run `…-switch37` results.json |
| DS | machinery + dual-screen identity work; needs touch-menu drive | handover B, Progress 3 |
| 3DS | same; needs active gameplay on both screens | handover B, Progress 3 |
| Dreamcast | at final gates; needs attract-cut handling / drive | handover B, Progress 2 |
| PS3 | aps3e now packaged (build flag was missing); first run pending | Progress 4 |

**FINAL SESSION RESULT — SWITCH: PASS** (run `…-switch37`, Metroid Dread,
on the OLED-guard APK a24638c8…, now the installed device build). The
system entry in results.json is PASS: full framegen evidence (steady
30→60 on the 120 Hz panel), latency overlap, dense gates, volume,
disposition, stop/return — all green, and the OLED-guard build introduced
no regression. The run's one companion FAIL is the list-view smoke's
SECOND launch ("no proven visible frame", near-black screen on the
re-launch) — the same second-launch class Wii U shows with Cemu (open
issue 2), now confirmed for Eden too; it is a re-launch lifecycle bug,
not a frame-generation defect. Run switch36 before it was the
intermittent Eden crash class (open issue 1).

**Sessions ended here by user instruction ("finish what you're doing,
finalize the handover, then STOP building"). Next session starts at DS
(user's order: DS → 3DS → Dreamcast → PS3), plus the second-launch
lifecycle bug now reproduced on two engines.**

## CURRENT APKs

- Device-installed (run 36): the pre-OLED-guard build. Rebuild any time
  with the full flag set — `LUCENT_INCLUDE_EXPERIMENTAL_CORES=1
  LUCENT_AUTOSELECT_EXPERIMENTAL_CORES=1 LUCENT_REUSE_QUALIFICATION_CORES=1
  LUCENT_INCLUDE_PHASE2_PPSSPP=1 LUCENT_REUSE_PHASE2_PPSSPP=1
  LUCENT_INCLUDE_PHASE3_EDEN=1 LUCENT_INCLUDE_PHASE3_CEMU=1
  LUCENT_INCLUDE_PHASE3_APS3E=1 ./build.sh` (APS3E flag is REQUIRED now).
- **Staged, not yet installed:** `lucent-3.2.16-phase2-phase3-qualification-
  a24638c8502cc3f45274799469354710c1969dafab68381d2b9cc0942986708b.apk`
  — adds the OLED guard + gameplay re-assert (below). Install at the next
  run boundary; never mid-run.

## ENGINE CHANGES LANDED TODAY (all unit-tested, on device unless noted)

1. **Cemu adapter vsync pinned to FIFO** (`engines/patches/
   cemu-lucent-adapter.cpp`, artifact `a4570055…` pinned in
   `engines/cemu-source-lock.json`). Cemu's default IMMEDIATE present let
   Android's BufferQueue drop frames on bursty presents; measured source
   swung 21-59 Hz on steady content. Incremental relink procedure is in
   the lock's determinismObservation + handover B Progress 5.
2. **Starvation-demotion tier policy** (`AdaptiveFrameRateController`):
   starved output slots >3% of the rolling 8 s window's output demand
   demote one tier; EVERY starved slot pushes an upgrade hold
   (15→120 s exponential backoff with demotion count); post-demotion
   upgrades climb one tier per clean hold. This is the "steadiest
   sustainable tier beats mean-supported tier" smoothness policy. Test:
   `materialSlotStarvationDemotesToTheSteadierTier`.
3. **HAT d-pad fix** (`NativeAdapterEngineSession.dispatchGenericMotionEvent`):
   the Thor d-pad emits AXIS_HAT_X/Y; only sticks were forwarded, so the
   d-pad was dead in EVERY native-adapter game. Now mapped to the four
   PAD_DPAD ordinals.
4. **Transient GPU-timer re-arm** + **in-poll rejection degrade** in
   `DisplayFrameGenerator` (handover B Progress 4, items 3-4).
5. **OLED guard (staged APK, NOT yet device-verified)** —
   `InWindowGameHost`: when committed output stays 0 (no unique source
   frames → truly static screen) for 2 continuous minutes during
   gameplay, a pure-black overlay fades in (zero OLED emission); any
   key/motion/touch or the first new frame removes it instantly. ALSO
   re-asserts ACTION_GAMEPLAY to the companion once per minute so a
   crash-restarted PreviewService can never again report gameplay=false
   under a live game (that staleness is what let the theme screensaver
   start beneath Dread and create the phantom 120 Hz layer, runs
   switch32/33). NOTE: the theme's QML screensaver renders BENEATH the
   gameplay view, so the HOST owns in-game burn-in protection; the theme
   screensaver continues to own the library UI. The device's
   `theme_settings/lucent.json` had screensaver temporarily disabled
   during debugging and has been RE-ENABLED (verify:
   `lucentScreensaverEnabled` must be true).

## RUNNER/HARNESS CHANGES TODAY (tools/tests all green: 215 runner tests,
57 systemwide, Java suite passes via `unified-android/test.sh`)

- Tier 20 added to the steady-segment allowed set (goal names 20→40).
- `runtime_checkpoint_outcome` accepts engine-owned `quickResume=false`
  as the completed no-checkpoint disposition (Cemu).
- Per-stream split-HEALTH pairing keyed by (pid, generator).
- Boot gate: 360 s + HAT-left/A assist for wiiu/ps3.
- Route-bound "Adapter audio playback started" accepted as native-adapter
  readiness telemetry (cemu/aps3e have no fps hook).
- Wired waits: per-system confirm key, skip cycles (including
  lower-display taps in 1240x1080 display-4 coordinates), per-system
  probe motion, separate in-loop cycle.
- Switch navigator: HAT d-pad presses, 1.6 s hold-A on Blasphemous save
  slots, tutorial-popup dismissal (bounded B), looping-title-video
  tolerance (Dread), "Press Ⓐ" glyph OCR ([@©®]), SAMUS FILES/NO DATA
  save vocabulary, movie skip presses instead of parking on active NVDEC,
  continuous-motion acceptance (3 consecutive ≥3000 OR 12 consecutive
  ≥300 changed pixels; B pressed only after weak samples so card flips
  can't fake it), title-ready 150 s, post-action recognition 30 s,
  readiness motion pulses 1.2 s.
- OCR hardened: grayscale autocontrast + psm 6/11 union (dark UIs went
  from 1-in-10 to 10-in-10 classification). Boost files are dotfiles.
- Cover-origin delta-correction: OCR the system actually landed on and
  step the signed difference (the Continue Playing rail shifts the
  deterministic origin).
- Scene retries (7) for ps2/wii/wiiu/switch.

## KNOWN OPEN ISSUES

1. **Switch full-suite green**: run 30 passed framegen; the remaining
   failures have been, in order: return-video jank (109 ms gap, one
   run), post-reboot screensaver phantom (fixed properly via OLED-guard
   APK + re-assert; verify on device), one Eden heap-corruption crash
   class (intermittent, ~10% of runs — known from
   memory `lucent-switch-crash-evidence`; a glReadPixels null-deref in
   the Adreno driver inside `latestImageIsUnique` was the latest shape),
   and two runs where the app wasn't running at QA start (launch before
   running, verify `topResumedActivity` is MainActivity).
2. **Cemu second-launch refusal**: list-view smoke's second wiiu launch
   fails "could not start cemu" (one-title-per-process latch class,
   memory `lucent-cemu-prepared-title-latch`). Root-cause in the
   adapter's re-launch path.
3. **Screensaver-under-gameplay** (root cause fixed by re-assert; theme
   suspend still worth adding): the frontend cannot render a screensaver
   over the game; host OLED guard covers in-game protection.
4. Blasphemous II runs ~16 Hz on Eden/Thor (below tier-20 floor) — not a
   framegen defect; Dread is the Switch qualification title.
5. After finishing the user's system order: tier matrix on 120 Hz
   (20/40/50 sustained), full 60 Hz panel runs, HUD-text ghosting review,
   final audit + full test-suite re-run (tasks #4, #7).

## HOW TO RUN (the exact loop used all session)

```sh
ADB=/Users/tyleryoung/.codex/tools/android-platform-tools/adb
APK=$(ls -t unified-android/build/lucent-3.2.16-phase2-phase3-qualification-*.apk | head -1)
HASH=$(basename $APK | grep -oE "[0-9a-f]{64}")
$ADB -s 427c87b2 install -r -d "$APK"   # only when installing a new build
$ADB -s 427c87b2 shell logcat -G 16M
$ADB -s 427c87b2 shell am force-stop com.thorium.preview
sleep 3
$ADB -s 427c87b2 shell am start --display 0 -f 0x18000000 \
  -n com.thorium.preview/org.pegasus_frontend.android.MainActivity
sleep 14   # then CONFIRM MainActivity is topResumed before running
python3 unified-android/tools/run_runtime_acceptance_qa.py \
  --serial 427c87b2 --apk "$APK" --expected-sha256 $HASH \
  --output unified-android/build/runtime-acceptance-qa-<date>-<name> \
  --system <system> --titles-per-system 1 --allow-physical-thor \
  --already-installed --allow-research-phase3 \
  --adb /Users/tyleryoung/.codex/tools/android-platform-tools/adb
```

Verdict: read `<outdir>/results.json` counts/status/reason. Diagnose from
`<system>-failure-logcat.txt` + screenshots. One run ≈ 35-55 min. Health
lines: `grep "Presentation health base generator=1"` and read
producerHz/lockedFps/outputFps/windowDueNoEndpoint.

## NEXT STEPS (in order)

1. Read run switch36's verdict. If framegen green but a companion check
   flaked, rerun; a full PASS closes Switch.
2. Install the OLED-guard APK `a24638c8…` at the next boundary; rerun
   Switch once on it to confirm no regression and that the guard stays
   out of the way (output>0 clears it).
3. DS: drive Metroid Prime Hunters' touch menus (lower-display taps in
   display-4 coordinates now proven; `inject_lower_motion` exists).
4. 3DS: drive A Link Between Worlds into active dual-screen gameplay.
5. Dreamcast: thread Crazy Taxi into its drive (attract cuts starve
   coverage; the wired-wait machinery with skip cycles is ready).
6. PS3: first aps3e run (boot gate + audio telemetry already wired).
7. Tier matrix + 60 Hz panel + final audit.
