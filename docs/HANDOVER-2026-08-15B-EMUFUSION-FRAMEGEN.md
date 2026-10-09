# EmuFusion frame-generation handover B — 2026-08-15 (afternoon)

## MATRIX PROGRESS 6 (2026-08-16 ~11:30 — **WII U PASS**)

**Wii U system qualification PASSED** (run `…-wiiu23`, Super Mario 3D
World, APK 42431e9f…): framegen reports passed:true on BOTH displays in
run 21 and the full suite went green in run 23 once the two remaining
non-framegen gates were fixed. The path there (runs 18-23):
- **ENGINE: starvation-demotion tier policy** in
  AdaptiveFrameRateController — recordUnavailableSlot() demotes one tier
  when starved output slots exceed 3% of the rolling 8 s window's output
  demand (proportional so Wii r52's ~1% empty-slot hold at 60 is
  untouched); EVERY starved slot pushes an upgrade hold forward
  (clean-window requirement, exponential backoff 15→120 s with demotion
  count) and post-demotion upgrades climb ONE tier per clean hold. SM3DW
  settles churn-free at lock 20 → 40 output with 30-second clean
  stretches. New unit test: materialSlotStarvationDemotesToTheSteadierTier.
- Runner: tier 20 added to the steady-segment `allowed` set (the goal
  names 20→40; the verifier already accepted 20 everywhere — only this
  runner set omitted it and made the settled 20-tier unqualifiable).
- Runner: runtime_checkpoint_outcome accepts the engine-owned
  "Adapter ready … quickResume=false" declaration as the completed
  no-checkpoint disposition (Cemu is the first no-quick-resume engine
  through the gate).
- KNOWN REMAINING (not framegen): the list-view smoke's SECOND cemu
  launch in the same process fails with "EmuFusion could not start cemu"
  — the one-title-per-process latch class from
  memory lucent-cemu-prepared-title-latch. Root-cause the second-launch
  refusal in the adapter's re-launch path.
Next per the user's priority order: **Switch → DS → 3DS → Dreamcast →
PS3** (Switch fixes pre-landed: HAT d-pad presses + 1.6 s hold-A on the
save slot).

## MATRIX PROGRESS 5 (2026-08-16 morning — USER DIRECTIVES + FIFO fix)

**USER DIRECTIVES (2026-08-16 ~07:30, from chat — binding):** do NOT
qualify Wii U on NES Remix Pack ("just NES graphics — use pretty much any
other game"); after Wii U the priority order is **Switch → DS → 3DS →
Dreamcast → PS3**. The user also asked how 50→100 works on a 60/120-only
panel — answered: the panel stays at 120 Hz and the generator presents
100 evenly-spaced fps into the 120 slots via the 5:6 lattice (2:3 for
80); SurfaceFlinger timestamps verify the cadence.

- **ENGINE (major): Cemu adapter now pins vsync=FIFO**
  (engines/patches/cemu-lucent-adapter.cpp process init; new artifact
  a4570055… staged + pinned in cemu-source-lock.json; incremental relink
  procedure: ninja `src/android/app/src/main/cpp/libCemuAndroid.so` in
  /Users/tyleryoung/Code/cemu/Cemu-0.5/build-lucent-static with the
  android-sdk cmake-3.31.6 ninja, NDK-28.2 llvm-strip --strip-unneeded,
  copy to engines/build/arm64-v8a/, update lock sha256; build.sh
  regenerates the APK manifests). Default vsync=0 (IMMEDIATE) let
  Android's BufferQueue DROP queued frames on bursty presents → measured
  source rate swung 21-59 Hz on steady content. With FIFO run 15 showed
  sustained 50 lock → 98-99 committed (target 100) for the first time.
- Wii U runs 13-16 (NES Remix, now abandoned per directive): full
  autonomous navigation worked end-to-end (selector HAT-left+A → title →
  Miiverse "No" tap at display-4 438,687 → stage focus → live NES
  gameplay on the TV). Failure classes fixed along the way: probe motion
  is now per-system (lateral for platformers), the sampling loop's press
  cycle is separate from the entry cycle (START pauses a running
  challenge), and the boot-gate assist alternates HAT-left/A for
  focusless selectors. Remaining failure at abandonment: challenge
  cards/restarts + residual producer wobble kept the latency capture from
  overlapping an 11 s steady segment.
- Run wiiu17 IN FLIGHT at handover: Super Mario 3D World retry on the
  FIFO adapter (entry START/A ×8, loop_cycle=(A,), lateral probe motion,
  stick-only sustainer). SM3DW previously failed ONLY on pre-FIFO pacing.
- **Switch pre-landed fixes (untested)**: navigator d-pad presses now use
  controller.hat() (EV_KEY dpad never reaches a native-adapter game — the
  same bug as Cemu's, proven by switch3's six dead UP presses), and the
  save-slot A press holds 1.6 s (Blasphemous slots are HOLD-to-confirm;
  the 55 ms tap parked switch3 on the recognized slot screen until the
  state budget ran out).

## MATRIX PROGRESS 4 (2026-08-16 early morning, Wii U + PS3 survey)

Current APK: `lucent-3.2.16-…-d46d9c82…` (adds the aps3e adapter, the
HAT d-pad engine fix, the transient-timer re-arm, and the
synthetic-selection degrade). Build now REQUIRES
`LUCENT_INCLUDE_PHASE3_APS3E=1` alongside the full flag set.

- **PS3 (aps3e): blocked only on the rebuilt APK when first tried** —
  `exact packaged engine is absent … liblucent_native_adapter_aps3e.so`;
  the adapter was staged but the flag wasn't in the build recipe. The
  d46d9c82 APK packages it; a ps3 diagnostic run has NOT yet been
  relaunched on it. That is the next unstarted survey item.
- **Wii U (cemu): nine distinct failure classes root-caused and fixed
  across runs wiiu1-12** (NES Remix Pack is the pinned matrix title —
  the only library title Cemu delivers steadily on the Thor; Bayonetta
  attract and SM3DW gameplay swing 29-64 Hz producer and can never hold
  the 11 s steady segment):
  1. Boot gate: Cemu spends minutes on solid black/white (shader
     compile, intro flash) — `wait_presented_frame` now takes
     timeout=360 s + an A-press assist for wiiu/ps3.
  2. Readiness telemetry: cemu/aps3e export no measured-fps hook (only
     Eden does), so "First guest frame" can never log; the runner now
     accepts route-bound "Adapter audio playback started" (guest DSP
     samples) as the native-adapter readiness marker.
  3. **ENGINE: one garbage GPU timer read permanently killed generation**
     — an Adreno all-ones elapsed (STATUS_ELAPSED_OVERFLOW, one event in
     ~9000 warps under Cemu's Vulkan load) latched densePyramidUnavailable
     for the session. rejectDense now classifies disjoint/overflow as
     transient: same epoch teardown + endpoint-only collapse, but the
     HEALTH-boundary switch refresh may re-arm a fresh timer/epoch, capped
     at 8/session ("recoverable=1 transientRejections=N" in the log).
  4. **ENGINE: in-poll rejection race threw in presentBuffered** —
     "buffered synthetic selected without an adjacent ready pair" when
     pollDenseTimers rejected after the synthetic selection; now degrades
     that swap to the retained left endpoint (mirrors the warp-timer
     path); the strict throw remains for genuinely impossible states.
  5. Split-HEALTH pairing: two live generators (dual-screen) interleave
     base/extension lines in one logcat — pairing is now keyed by
     (pid, generator id); all anti-splicing checks are per-stream.
  6. Steady scene: wiiu wired into the generic advance branch, the
     live-gameplay wait, and scene_attempts=7.
  7. Confirm key: the wait's alternation hardcoded raw south B — Wii U
     CANCEL — bouncing NES Remix title↔menu forever; the wait now takes
     confirm_key (wiiu passes raw east A) and a generalized skip_cycle.
  8. **ENGINE: d-pad was dead in every native-adapter game** — the Thor
     d-pad emits HAT axes; dispatchGenericMotionEvent forwarded only
     sticks. It now maps AXIS_HAT_X/Y to the four PAD_DPAD ordinals
     (log: "control=HAT directions=N"). Harness: controller.hat()
     injects ABS_HAT0X/Y (EV_KEY 544-547 never reach a game).
  9. NES Remix's one-time Miiverse applet dialog is touch-ONLY (EAST,
     START, HAT-left all reached the adapter; dialog held). The skip
     cycle now includes a lower-display tap ("lower-tap", 782, 767 =
     "No", privacy default) through onSecondaryTouch → LUCENT_PAD_TOUCH_*.
     Run wiiu12 (in flight at handover) is the first with the tap.
  Also: run wiiu10 was a flaky all-black Cemu boot (audio ran, TV black,
  badge 60/—) — retry recovered; treat as known Cemu boot flake.

## MATRIX PROGRESS 3 (2026-08-16 ~01:40)

- **DS: v28 workload-identity FIXED end-to-end.** The generator now logs
  `Frame generator resized …` and authoritative `Frame generator
  dense-allocated … history=WxH analysis=WxH` records; the verifier binds
  workload identity to the latest allocation record (attach-record dims
  are stale after post-attach resizes). Both DS streams emit schema-39
  dense evidence. Remaining: Metroid Prime Hunters sits in TOUCH-driven
  menus (all failures are content-starvation classes) — the DS needs a
  lower-screen stylus tap flow (case.lower_touch machinery exists:
  inject_lower_motion) to reach gameplay before proof.
- **3DS (runs n3ds1-3):** dual-screen machinery + identity all work (the
  DS fixes carry over). Failure is now precise: at menus the LOWER screen
  (Zelda's map) is static, so its SurfaceFlinger ring has "fewer than 31
  valid timestamps" — fail-closed and correct for static content. Both
  dual-screen systems converge on the same need: drive into ACTIVE
  gameplay (both screens updating) before proof — touch taps for DS/MPH,
  menu presses for 3DS/ALBW.
- **Switch (Blasphemous/Eden, runs switch1-3):** the fail-closed state
  machine now recognizes the gothic main menu via the OPTIONS+CREDITS
  co-occurrence fallback (stylized "Pilgrimage" defeats OCR), selects
  Play, and the post-Play motion gate has a 120 s allowance for the
  poetry load card. Remaining: the save-slot screen needs its own
  recognized state (currently unknown → the navigator loops to the
  ten-recognized-states cap). Teach `classify_switch_screen` the slot
  screen from `switch-title-01-switch-navigation-*.png` in run switch3,
  with A-on-default as its safe action.
- Dreamcast state unchanged from Progress 2 (needs card/attract rejection
  or threading into a drive).

## MATRIX PROGRESS 2 (2026-08-16 early morning)

- **Dreamcast (Crazy Taxi/flycast): reached the final framegen gates.**
  Landed: START/A alternating advance presses; wired into the generic
  live-gameplay wait with per-system skip key (START) and alternating
  skip/confirm presses for mixed prompt chains (VMU wants Start, name
  registration wants A). Remaining: the wait accepts on boot-card
  transitions (white SEGA cards have large inter-probe diffs) and the
  attract's hard cuts fail bidirectional coverage — the wait needs a
  card/attract rejector (structure alone is insufficient; consider
  requiring N consecutive live probes AND rejecting near-white frames), or
  thread fully into a drive (arcade → character select needs A presses
  timed past the attract acceptance).
- The generic wait now takes `entry_presses`, `skip_key`, `skip_label`
  and alternates skip/confirm on both entry and in-loop presses.

## MATRIX PROGRESS (overnight into 2026-08-16)

- **PSP: PASS** first try (God of War: Ghost of Sparta / PPSSPP, all
  gates, `…-psp1`). Only the list-view smoke's second-launch lottery
  remained.
- **Wii: framegen PASSED** (`wii-title-01-framegen-report.json`
  passed:true on live SMG2 gameplay, run `…-wii11`). Landed on the way:
  the generic proven-live-gameplay wait now guards wii too; SMG2
  preferred over SMG1 (save drift); Galaxy A+B prompt OCR accepts
  P/B+AND/OND confusions; dual-tree file-select flow; proof armed exactly
  once across scene retries (per-attempt re-arming trips the verifier's
  exactly-once contract); getevent tap capture -c 4→12 with bounded
  re-tap; SurfaceFlinger cadence-transient classes are scene-retryable.
- **DS: two real findings.** (1) FIXED: PreviewActivity built the
  secondary (lower-screen) generator with the one-switch constructor whose
  dense switch is hardwired false — no dual-screen system could ever emit
  schema-39 secondary evidence; the full switch set is now mirrored into
  PreviewActivity. (2) OPEN: with dense armed, the DS's low-res source
  selects the low-res analysis divisors so the verifier reports "v28
  reduced-analysis workload identity is absent or impossible" for that
  stream — the workload-identity check needs the low-res variant taught,
  or the secondary needs its own expected identity. Also MPH's menu-heavy
  first boot needs a DS scene flow (same recipe as PS2/Wii).
- Engine-name identity fallback added (route ids are separator-free,
  packaged libs keep underscores — melondsds vs melonds_ds).

## HEADLINE (final state of the day)

**PS2 PASSED the full acceptance case** — God of War, all schema-39
framegen gates, twice (runs `…-ps2-gow1` and `…-ps2-gow3`) on the
fully-fixed build (phase + tier + 83px flow reach + solver-resolution
validity base). GameCube already had a `complete: true` manifest. The
goal's first priority — physical PS2/GC frame-generation QA — is
qualified with passing evidence. Only the list-view smoke's SECOND-launch
quick-resume scene lottery still flakes on PS2 (a UI smoke whose routing
already passed system-wide in the GC manifest; next lever: clear or
seed the quick-resume state before the smoke's relaunch).

Wii (Super Mario Galaxy) is the next system in flight: navigation reaches
the title attract but the proof windows sample the static starfield;
scene retries were extended to wii (`scene_attempts` set), and the flow
needs the PS2 treatment — deterministic A+B → file select → gameplay with
motion during proof. Remaining after Wii: PSP, 3DS, DS, Dreamcast, and
the phase-3 research routes (PS3/WiiU/Switch), each expected to need one
scene-flow calibration pass with this now-proven recipe; then all tiers
on 120 Hz, the 60 Hz panel matrix, HUD-ghosting review, and the final
audit.

## LATE ADDITION — the judder root cause was found and fixed

After this handover was first written, frame-by-frame decoding of the
recordings proved generated frames were advancing only ~9-28% of the source
motion step (near-duplicates, not crossfades): the scheduler's synthetic
phase swept a slow sawtooth (0.58→0.84/20 s) because the buffered playhead
was wall-clock-anchored once at prime and clock skew accumulated unbounded.
Fixed in `AdaptiveFrameRateController` by computing synthetic phase from the
physical slot offset since the last committed real present divided by the
producer span (rotation cadence untouched; a naive playhead re-anchor broke
the 5:6 lattice — see memory `lucent-framegen-phase-drift-bug`). Verified:
phaseMean 0.4996–0.5001 on Dolphin and ARMSX2; content advance fractions
~0.4–0.5; visual A/M/B frame proof delivered. A `Phase diagnostic` log line
(rate-limited, schema-independent) now reports phase stats every stats
window. New host test:
`bufferedSyntheticPhaseStaysCenteredUnderClockSkew`. Installed build with
the fix: `lucent-3.2.16-phase2-phase3-qualification-6c6e593c….apk`.
The FRAME GENERATION settings toggle (Display settings page 3/3) was
physically verified: present, ON by default, toggles OFF/ON.

All pre-fix physical "pass" claims below remain valid for pacing and
counters but UNDERSTATED the content defect; the frame-level displacement
analysis (scratchpad `proof_*` directories) is now the required evidence
standard for any smoothness claim.

## FIRST COMPLETE ACCEPTANCE PASS — GameCube, end to end

`unified-android/build/runtime-acceptance-qa-2026-08-15-gc-final2/results.json`:
`complete: true`, counts `PASS 1 / FAIL 0`, on the phase-fixed build
(`6c6e593c…`) with `--system gc --titles-per-system 1`. Metroid Prime
qualified through EVERY schema-39 gate — 900 real + 900 generated presents
in a 14.1 s proof window with zero fallbacks, 900/903 unique source images,
`syntheticDistinctFraction=1.0`, `nonCrossfadePixelFraction=0.84`,
~1200 confident motion vectors, vector-trajectory contract true, 107 raw
SurfaceFlinger overlap frames — plus volume evidence, stop-and-return, and
the list-view smoke with a second complete launch+qualification.

Two harness robustness fixes were required (evidence gates untouched):
strict UTF-8 decode of logcat crashed on a raw emulator byte
(`run_phase1a_activity_qa.run` now decodes with `errors="replace"`), and
adb latency occasionally stretched the 40 ms volume quick-tap past the
35-60 ms kernel-timed acceptance band (out-of-band taps are now discarded,
state-restored, and re-attempted, bounded at three).

Library data discovery: the device's `Burnout 2: Point of Impact` GameCube
RVZ is TRUNCATED (declared 933,938,844 bytes, only 6,678,447 on disk).
`DiscImagePreflight` correctly fails it closed with a user-facing message.
Multi-title GC runs will fail on it until the image is re-imported; other
titles were not audited.

## NEXT CRITICAL FIX — ARMSX2 double-submission defeats tier measurement

An offline golden-capture experiment (KH platform, held stick, 16 MB logcat
ring for the identity chain, `_write_framegen_qualification` +
`frame_gen.verify` run by hand — see scratchpad `g3_*` and
`golden_qual/`) exposed the remaining PS2 judder source: HEALTH shows
`lockedFps=60 outputFps=120` while `producerHz≈28.5–31.7`. ARMSX2 submits
each 30-fps frame TWICE with distinct timestamps on this scene, the tier
locks onto submissions (60) instead of unique content (30), and the
generator presents 120 where half the synthetic frames interpolate between
duplicate endpoints — motionless duplicates again, but now from tier
mismeasurement rather than phase drift. The verifier correctly rejects the
segment ("schema39 HEALTH is impossible: v37 output does not match the
exact x2 panel policy"). This violates the core invariant that unique
source timestamps/ordinals own tier measurement.

Note the morning fc87b82d platform run locked 30/60 correctly on the same
scene — the double-submission pattern is state-dependent (possibly the
tutorial-dialog overlay); reproduce with the golden-capture procedure
before designing the fix. The fix direction: unique-IMAGE detection (the
dense pair signature / densePairMeanDifference already measures endpoint
similarity) must collapse duplicate submissions for adaptive GPU engines
before tier voting, without regressing the fixed-rate authoritative-cadence
path or the endpoint FIFO contracts. The PS2 runner case (deterministic KH
navigation, which WORKS — title cross + three setup cards + green/dark
platform signature all landed correctly) will pass once tier measurement is
truthful on this scene.

## FINAL PS2 STATUS UPDATE 2 (very end of session)

The tier-adaptive flow reach LANDED: coarsest solve step doubles to 9.0
(83px reach, identical GPU cost) when lockedSourceFps<=30 —
block-matched real displacements on tier-30 content measured up to 72px
against the old 47px reach. Host test updated
(`lockedSourceFps() <= 30 ? 9.0f : 4.5f`). GTA III run 6 on this build
(scene pre-gates removed — they mispredicted the verifier; dense gates are
the arbiter, retries resample) reached live street traversal and is now
down to EXACTLY ONE failing gate on the real layer:
'too few changing pixels have a confident selected motion vector'.
Next levers, in order: (1) check whether the sampled window was partly
wedged/idle (turning traversal `motion_pair(left, right, hold=2.0)` may
still wall-stall — consider wall-escape via alternating diagonals);
(2) inspect the dense shader's match-quality/confidence threshold against
GTA III's low-contrast dawn textures — displacement is now within reach,
so confidence scoring is the remaining suspect; (3) a daylight/bright PS2
title with open traversal (e.g. Katamari gameplay at tier 30, Sly 2) using
this exact runner config.

## FINAL PS2 STATUS (end of 2026-08-15 session)

The runner now reaches REAL PS2 GAMEPLAY deterministically: matrix title
"Grand Theft Auto III", one Cross at title-ready, bounded menu/cutscene
Cross presses inside the probe loop, acceptance gated on stable tier +
bright (dark<=0.6) + structured (gray stddev>=35, rejects cutscene fades)
+ fast inter-probe motion (>=12) held for two consecutive probes, and
held-forward traversal during proof. Verified by screenshots: proof ran on
live street walking with HUD at a truthful 30/59.

The one remaining failure is now a well-characterized ENGINE defect, not
harness/scene: 'too few changing pixels have a confident selected motion
vector' (+ trajectory correlation) fails on every ARMSX2 tier-30 scene —
KH platform orbit, GTA III street traversal — while 60-fps Dolphin content
passes easily. Working hypothesis: tier-30 content has ~2x the per-frame
displacement of 60-fps content for the same scene speed; near-field motion
(road texture streaming past a walking camera) exceeds the dense flow's
search reach (MAX_FLOW_PIXELS=80, comment says "exact 47px reach"), so
those cells never reach confidence. Next fix: measure actual per-frame
displacement in the gta3 run recordings, then either extend the coarse
pyramid reach for 30-fps sources or scale search radius by source period.
Scene-selection work is DONE — do not spend more device runs on titles.

UPDATE (same day, later): the double-submission tier defect is FIXED and
verified. `AdaptiveFrameRateController.updateTier` now lets the submission
clock vouch for a held 60 tier only when the window is NOT an exact
supported duplicate schedule (`exactDuplicateSchedule` via
`duplicateFilteredDowngradeIsSupported`); two new ordinal-fed host tests
(`acquiredSixtyDemotesOnExactDoubleSubmissionSchedule`,
`acquiredSixtyHoldsThroughIrregularStaticContent`) close the coverage gap —
the old campaign test fed zero ordinals so the submission clock never
vouched in-test. On-device HEALTH now reads locked=30/out=60 at
producer≈30 on the KH platform (was locked=60/out=120). Installed build:
`…-0159601e….apk`.

PS2 runner navigation: solved. PS2 tier truthfulness: solved. The one
remaining miss is proof-window timing: the platform sequence intersperses
scripted narration cutscenes, and held-stick movement itself triggers the
pedestal cutscene, so the runner's proof windows kept sampling scripted
moments (7 attempts). Next session: either wait out the pedestal cutscene
before arming proof (probe for the dialog text box / wait ~60 s after the
first platform sighting), or run proof during the post-cutscene free-roam
where Sora can circle indefinitely. Everything else in the PS2 case is in
place.

Continues `HANDOVER-2026-08-15-EMUFUSION-FRAMEGEN.md`. The objective is
unchanged and **still not complete**: rock-solid frame generation for every
internally emulated system from PS2/GameCube up, physical PS2/GC QA first,
2x cap, unique-endpoint source measurement, presented-output-only reporting.

## Builds and device state

- The morning schema-39 checkpoint APK `fc87b82d…` was installed, its hash
  verified on device, and the full smoke passed (exact contract fields,
  proof off/on epoch advance, capability 63, atlas restart, zero errors).
- The handover's build command was missing flags (the known
  `LUCENT_AUTOSELECT_EXPERIMENTAL_CORES` trap — see
  memory `lucent-build-flags`): it packaged no phase-1 cores, so the
  runner's route closure correctly failed on `genesis->megadrive/blastem`.
  A full-flag build was produced and is NOW INSTALLED on the Thor:

  `unified-android/build/lucent-3.2.16-phase2-phase3-qualification-85675ab23404fbabe2ded242d9a7489ec304e6e1be1634661509e24dd53f0910.apk`

  SHA-256 `85675ab2…` (verified on device). All 27 phase-1 cores,
  `autoSelect: true`, and the cemu+eden+host adapters are packaged.
- Device settings remain `emufusion_framegen_proof=1`,
  `emufusion_framegen_dense_pyramid=1`, `emufusion_framegen_dense_v28_160=1`.
- The acceptance runner deletes the proof setting in its finally block —
  after any runner invocation, re-arm proof before manual dense evidence.

## Physical evidence obtained today (all on schema-39 builds)

1. **PS2 tier 30, player-controlled motion — full pass.** Kingdom Hearts,
   Dive to the Heart platform, 58+ s held-stick perimeter run: locked
   `30/60` every window, producerHz 29.52–30.15, exactly 30 real + 30
   generated, ZERO counter movement, zero rejections, 99.87%-clean 16.67 ms
   every-other-vsync lattice on the gameplay layer, and decoded-recording
   parity showing ~58.5 unique presents/s alternating half-step (generated)
   and full-step (real) diffs. Artifacts: scratchpad `kh_run30.mp4`,
   `kh_latency.txt`, `full_logcat.txt` (session-temporary).
2. **GameCube tier 60, player-controlled motion — strong pass with one
   caveat.** Metroid Prime via Dolphin, Quick-Resumed directly into frigate
   gameplay, 58 s Morph Ball traversal with proof on: locked `60/120` in
   all sustained windows, 60 real + 60 generated, zero rejections, atlas
   62→221 no errors, one SurfaceFlinger stream with zero >12.5 ms intervals
   in 3125. The 40→80 and 50→100 lattices appeared physically during room
   transitions. Corrections +30 at Dolphin room-load hitches (title
   characteristic). CAVEAT: frame extracts suggest slight HUD-text doubling
   on generated frames during fast motion — screen-fixed-HUD visual quality
   needs review before any release claim.
3. **Half-Life PAL robustness data**: badge truthful and pacing 98.5% clean
   while the engine oscillated 30↔60; corrections at zone loads.
4. **God of War discovery**: during combat, endpoint timestamp corrections
   accumulate continuously (74→104 inside a single steady-segment attempt)
   and dense proof samples stall; combat scenes cannot satisfy the
   correction-free 11 s steady gate. Kratos also dies in ~60 s without
   attack input, and blind cross-mash kills him too. GoW is structurally
   unsuited as the automated PS2 qualification scene.

## Repository changes (uncommitted, on top of the morning checkpoint)

- `tools/tests/test_systemwide_frame_generation.py`: the four stale
  assertions reconciled against current code (endpoint selector spelling,
  uniquely-strongest candidate gates, strengthened sustainability guard).
  All 54 tests pass; intent preserved or strengthened, never weakened.
- `unified-android/tools/run_runtime_acceptance_qa.py`:
  - PS2 navigation rewritten: the cadence-only "movie-started (locked<=40)"
    phase was physically impossible (the emulated PS2 scans out ~60
    continuously) and was removed; title-ready cadence is retained.
  - Scene-retry wrapper around `frame_generation_evidence` (PS2: 5 attempts,
    75 s apart) that retries ONLY scene-dependent failures
    (`_is_content_starved_framegen_failure`): content-starvation classes and
    the steady/latency timeouts. Pacing/atlas/timer failures raise
    immediately. Gates themselves untouched.
  - Per-phase budgets: `FRAMEGEN_CURRENT_STEADY_DEADLINE_SECONDS=180`,
    fresh `FRAMEGEN_LATENCY_CAPTURE_SECONDS=90` window after each steady
    confirmation, absolute `FRAMEGEN_TOTAL_CAPTURE_CAP_SECONDS=420`.
  - PS2 proof motion is currently INPUT-FREE and the PS2 required title is
    "Shadow of the Colossus" (self-playing attract). See "Runner status".
  - `screenshot_mean_abs_diff`, `ps2_platform_green_fraction` (calibrated:
    KH platform 0.17 vs <=0.002 elsewhere — beware green-tinted cutscene
    faces defeating it at low thresholds), `ps2_sustained_gameplay_windows`
    (any supported tier 20–60 with producer >= 0.9×locked).
- `unified-android/tools/runtime-acceptance-matrix.json`: ps2 requiredTitles
  God of War → Kingdom Hearts → now "Shadow of the Colossus".
- `tools/tests/test_runtime_acceptance_qa.py`: updated to each change;
  212→218 tests, all passing (266 with the systemwide suite).
- `docs/systemwide-frame-generation.md`: fully rewritten against schema 39,
  the 2x cap, presentation timing, today's evidence, and per-title
  qualification-scene characteristics.

## Runner status — the one unfinished gate (task: end-to-end PS2 manifest)

Sixteen physical runner iterations were burned learning this: **the steady
gate and the content gates constrain scenes in opposite directions.**

- GoW (runs 1–7): navigation fixed, then steady gate unreachable in combat.
- KH (runs 8–15): steady gate trivially satisfied on the platform
  (physically proven), but automation kept overshooting the platform
  (menu-press races; the platform progresses on Cross) or landing proof in
  the 4-minute dive movie / beach cutscenes, which starve content gates.
  Best KH attempt (run 13) failed ONLY
  `too few changing pixels have a confident selected motion vector` —
  coherent held-direction traversal was the missing piece, but runs 14/15
  regressed by leaving the platform (edge-stall + racy presses).
- SotC (run 16): input-free attract has ideal content motion but scene cuts
  break the 11 s steady window — all five attempts timed out on steady.

Most promising paths for the next session, in order:
1. **KH platform with input-free-until-platform + held-direction proof**:
   deterministic Cross sequence (title, difficulty, vibration, proceed —
   exactly 4 presses), wait for the green-platform signature
   (`ps2_platform_green_fraction >= 0.05` — raise threshold or add a
   shape check to reject green-tinted cutscenes), then continuous
   `motion_pair("right","right", hold=2.5)` in the sustainer (currently
   input-free for SotC — must be switched back for KH) and proof there.
   The morning's manual run proves the scene passes the steady gate; the
   held-direction traversal was never yet combined with a clean platform
   proof window in a single runner attempt.
2. **Offline verification of the manual KH evidence** to confirm the
   content gates pass on that exact scene before burning device runs. The
   manual capture used `logcat -v time`; the verifier's strict process
   identity parse expects the runner's `-v brief` capture. Re-capture with
   `-v brief` or teach the offline experiment the time format.
3. If the platform's content signal proves insufficient, find a PS2 scene
   with BOTH properties (stable tier, no corrections, full-screen coherent
   motion): candidate ideas — Sly 2 gameplay (60 fps platformer, free roam
   hub), Tekken 5 attract replays, SotC in-game save near open field
   (requires creating a save first).

Also unfinished from the original list: 20 tier and sustained 40/50 tiers
on 120 Hz, every mapping on a 60 Hz panel, newer-system matrix (Wii, 3DS,
PSP, Dreamcast, PS3/WiiU/Switch research routes), HUD visual-quality
acceptance, complete host/native/shader suite rerun, independent audit.

## Techniques that keep working (see also memory files)

- Frontend nav: `input -d 0 keyevent DPAD_*`/F3/F4; launch with raw
  BTN_SOUTH 304 sendevent. In-game: cross=305, triangle=307, START=315,
  Select-hold 314 (1.8 s) exits. Right stick = ABS_Z/ABS_RZ (codes 2/5),
  left stick = ABS_X/ABS_Y (0/1); hold by writing the value once, release
  with 0.
- Screen layers: two `SurfaceView…(BLAST)` layers exist; the QML frontend
  renders a flat-120 stream behind the game. Identify the gameplay layer by
  its cadence (e.g. 16.67 ms lattice for a 60-present stream), never by ID.
- Half-Life PAL memory-card prompts: "▷" glyph = START, not Cross.
- KH: attract loop returns to title on START; real flow is
  title→difficulty→vibration→proceed→movie(~4 min)→platform; platform
  progresses ONLY on Cross; stick pulses toggle menu selections.

## Non-negotiable invariants (unchanged)

All invariants from the morning handover hold verbatim: max 2x, count only
after successful `eglSwapBuffers`, unique endpoints own tier measurement,
SurfaceFlinger authority, fail-closed error paths, NES/dual-screen
isolation, and the 50% dense validity/content gates are never weakened to
pass a scene. Today's runner changes alter only navigation, budgets, and
retry policy — never a verifier predicate.

## ADDENDUM (2026-08-16 ~15:30): screensaver-under-gameplay bug

The frontend's screensaver idle timer keeps running while a game owns the
in-window session: after ~20 min of gameplay it starts its VIDEO
(lucentScreensaverLastVideo) on a hidden 120 Hz Qt Multimedia SurfaceView
under the game. First surfaced post-reboot in runs switch32/33 as a phantom
second "primary gameplay" layer that poisoned the SurfaceFlinger
uniquely-strongest selection ("did not latch at the reported output
cadence" on the phantom + "no visible compositor output" on the real
layer). QA now runs with lucentScreensaverEnabled=false in
theme_settings/lucent.json on the Thor. REAL FIX NEEDED: the theme must
suspend its screensaver timer while a game session is active.
