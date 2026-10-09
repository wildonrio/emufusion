# EmuFusion system-wide frame generation

> **Current contract (2026-09-04):** see
> [FRAME-GENERATION-GOAL-2026-09-04.md](FRAME-GENERATION-GOAL-2026-09-04.md).
> Its exact 1×/2× and small-clock-correction rules supersede the 3×/tier-slowdown
> policy below. This file is a historical lab notebook, not the current acceptance
> matrix; earlier PASS/PROVEN labels do not qualify the revised implementation.

Updated 2026-09-01 to the owner's tier protocol. The schema-39 discussion
later in this file is retained as historical evidence only. The 2026-08-26
"never more than 2×" contract below it is likewise superseded: 20 and 40
now triple onto the exact 60 and 120 Hz scan lattices.

## User contract (tier protocol, 2026-09-01)

Frame generation presents newly composed intermediate frames for internally
emulated systems. It runs strictly after the per-system display clock
synchronization (`DisplaySyncPolicy.synchronizedSourceHz`, the sub-1 %
NTSC-family speed correction onto an exact panel divisor); that layer is
never modified by generation.

The generator locks one stable real-frame **tier** from the game's sustained
unique-frame delivery and multiplies it by an **integer** factor onto an
output that occupies an **integer number of panel scans**:

```text
120 Hz panel (Thor top screen)        60 Hz panel (separate protocol)
  sustained 60      -> 60 -> 120 (x2)    sustained 60      -> 60 direct
  sustained 50-59   -> 40 -> 120 (x3)    sustained 40-59   -> 30 ->  60 (x2)
  sustained 40-49   -> 40 -> 120 (x3)    sustained 30-39   -> 30 ->  60 (x2)
  sustained 30-39   -> 30 ->  60 (x2)    sustained 20-29   -> 20 ->  60 (x3)
  sustained 20-29   -> 20 ->  60 (x3)
```

50 is not a tier: it has no integer path onto a 120 Hz scan, so a 50-59
source is demoted to 40. The generation factor is never more than three.
There is no 40→80 or 50→100 schedule; their alternating scan gaps are visible
judder.

**Downgrade means pace the core.** A libretro core that cannot hold its own
synchronized clock is paced at the locked tier (the same pacer/audio-multiplier
mechanism the clock synchronization already uses), so generation always
consumes an exact clock instead of a wobbling one. A core running at full
speed whose game updates less often (Ocarina: 60 core frames, 20 unique) is
never paced. Pacing is lifted only after the core proves work-time headroom
for its full clock, as a bounded probe; a failed probe re-paces with backoff.

The tier is measured from unique source endpoints (timestamps/ordinals), never
from presentation success, and changes only from a complete rolling
ten-second producer-time observation, so bounded content patterns (logos,
blinks, camera cuts) cannot churn the output cadence. Below a sustainable
generation rate (20 fps source) generation stops and the newest real endpoint
is presented directly — the generator never extrapolates past retained
endpoints. The in-game corner badge reports `source → target`, the delivered
rate, the backend, and `paced N` while a tier pace is active.

## Status 2026-09-01 (tier protocol on the Thor)

Verified on the device with the built-in generator and the acceptance
harness's scan-out capture (SurfaceFlinger actual present times):

- Ocarina of Time (N64, 20 fps): 20 real + 40 generated per second on the
  60 Hz two-scan lattice, every output on its scan (on-time fraction 1.0,
  phase excursion 0). The x3 path.
- God of War: Ghost of Sparta (PSP, 60 fps): 60 real + 60 generated per
  second at 120 Hz, clock reads an exact 60.000 after the stamp-clock fix,
  every output on its scan.
- F-Zero X (N64, 60 fps): 60 real + 60 generated at 120 Hz.

Fixes that made this work: the generator follows the panel to its 120 Hz
mode after the window's mode request lands; hardware cores are stamped on
the clock they are paced at (a 59.94-declared core paced at 60.00 used to
lag 1001 ppm and skip one generated frame every second); one exact REAL per
source interval through a symmetric half-output-period endpoint snap with
monotonicity judged on the pre-snap playhead; the dense epoch is rebuilt when
proof is armed; a source that sustains 50-59 fps demotes to 40 and is paced
there; the corner badge reports source → target, delivered rate and backend.

- Wii U tier pacing (2026-09-02): the Cemu adapter now exports optional
  pacing hooks (`lucent_native_adapter_declared_video_hz`,
  `lucent_native_adapter_set_paced_video_hz`) that the native host resolves
  by dlsym; the Java adapter session implements `declaredVideoHz` /
  `setPacedVideoHz`, so the load-hold downgrade probe can pace Cemu at 40
  (or 30/20) exactly like a libretro core. The pace is Cemu's own emulated
  vsync frequency; the display-timing stamp lattice follows the same period
  and re-bases on a change; the trusted producer timeline follows the paced
  clock. Every Cemu start now pins the emulated vsync to exactly 60 Hz:
  Cemu's default 59.88 Hz overshoot skipped one 60-Hz stamp slot every ~8 s
  and read as a held frame at the host.

- 3DS lower display (2026-09-02): the clockwise producer path asked for a
  portrait buffer by swapping the display mode's physical width and
  height, but the Thor reports display 4's physical mode as 1080x1240
  (portrait panel rotated to a 1240x1080 logical display), so the swap
  yielded the landscape buffer the harness rejected. The path now requests
  shorter-edge-wide, longer-edge-tall whichever way the mode is reported.

- DS / software-fed cores (2026-09-02, not yet device-verified): two
  fixes from run nds-b51. The launch curtain lifted only on the
  SurfaceTexture submit path, so every software-fed stream (melonDS:
  hwSubmits=0, swSubmits=60) ran behind a black curtain for the whole
  session; the software upload now notifies the first submitted frame.
  Software frames were stamped with the upload thread's arrival time, so
  melonDS's exact 2:1 stream (30 unique of 60) never proved its clock and
  fell to the 20 tier with generation off; the libretro frame loop now
  stamps each frame with the pacer's absolute due time
  (`AbsoluteFramePacer.deadlineNanos`, carried on
  `LibretroHost.VideoFrame.producerTimestampNs`) and the generator's
  software submit takes that stamp.

- Wii U pacing verified on the Thor (run wiiu-b56b, 2026-09-02): the
  load-hold probe paced Cemu at 40 and the paced lattice qualified
  (40 real + 80 generated at 120 Hz, probe kept). After the timed lift the
  game sat at 52-59 unique of 60, unqualified, for an hour and never
  re-paced: the 55-unique light-hold exclusion reset the evidence streak
  every few seconds. The generator now reports the light-hold band
  separately and the host demands 120 consecutive unqualified reports for
  it (45 for an irregular stream); each re-pace after a lift doubles the
  next lift hold (120 s up to 30 min).

- DS on the Thor (run nds-b57, 2026-09-02): the curtain fix is verified
  and the top screen is live. Remaining: the lower display presented a
  stale boot frame while the top screen had progressed (the lower-display
  presentation break first seen 2026-08-19), and on a low-unique irregular
  stream (12-15 unique of 60) the buffered scheduler presents only 6-9
  swaps per second because no endpoint pair forms.

- Switch tier pacing (2026-09-02, not yet device-verified): Eden now
  exports the same optional pacing hooks as Cemu. Eden's own speed limit
  is an integer percent and cannot express 40 of 60, so a Lucent-authored
  header-only atomic (`src/common/lucent_pacing.h`) carries the exact paced
  vsync clock; the VI conductor uses it as the vsync base clock and the
  Vulkan swapchain's display-timing stamps follow the same period.

- Wii U re-pacing (run wiiu-b58, 2026-09-02): the light-hold streak
  re-paced Cemu at 40 three times and each kept pace delivered 40 real +
  80 generated at 120 Hz for its whole hold; every lift probe then failed
  and one re-probe paced the game to 20 because the unpaced scene read
  20-29 at that instant. A failed lift now re-paces at the last kept tier
  immediately, and a later probe prefers the kept tier over a momentary
  lower reading.

- 3DS (run n3ds-b58b, 2026-09-02): full harness PASS on build 58 after the
  portrait-buffer fix, 60 real + 60 generated at 120 Hz on the primary with
  the clockwise lower display live.

- Switch pacing verified on the Thor (run switch-b59, 2026-09-02): the
  load-hold probe paced Eden at 40, the swapchain stamp lattice re-based
  to 40 Hz, the paced lattice qualified (40 real + 80 generated at 120 Hz)
  and the probe was kept; after the lift the 60 lattice qualified
  intermittently at 55-60 unique. The process survived the whole run. The
  harness then failed only on proof-region telemetry coverage of the
  post-lift 60 segment.

- Proof re-arm telemetry (run switch-b59, 2026-09-02): re-arming the
  qualification proof after a pacing lift reset the proof sample count but
  not the candidate-lattice and regional-flow counters, so every later
  health record failed the verifier's "telemetry covers every proof region"
  rule. All 48 lattice/regional counters now reset with the proof.

- Wii U re-pacing evidence (run wiiu-b60, 2026-09-02): a lift probe that
  succeeds for one minute and then degrades to 43-58 unique left the game
  unpaced for 40 minutes because a few qualified seconds per minute reset
  the consecutive light-hold streak. The light-hold evidence is now a
  rolling 120-report window that fires at 108 unqualified reports.

- Interpolation content (2026-09-02, from a panel recording of the Wii U
  40 to 120 output): the two synthesized slots of a fast pan were exact
  copies of the neighbouring real frames because the dense solver's 47 px
  reach saturated, validation rejected the moving cells, and the
  presentation's only fallback was the exact nearest endpoint (the legacy
  global pass never runs in dense mode). Fixes: the reach follows the
  motion-bounds limit (108 px at 1080p) with a derived coarse step and
  reciprocal tolerance; the spatial-agreement gate scales with vector
  magnitude; a two-pass neighbour fill warps isolated rejections with
  their validated surroundings; unsupported cells fall back to the dense
  global seed. Verification is the recording proof: generated frames must
  sit at intermediate displacement fractions, never at 0 or 1.

- Interpolation content, second round (2026-09-02, builds 69-72): the
  validation keeps photometrically plausible one-sided matches at a weak
  confidence below the proof threshold so the presentation can warp with
  them; the presentation lends a validated direction's negated vector to
  the other side when that side is weak or empty (the first synthetic slot
  used to sit on the left endpoint while the second warped); adapter
  pacing cascades one tier after a failed probe only on qualified lower
  readings taken outside clock acquisition, with a 90-s window for the
  cascaded probe. The build-70 panel recording, taken while qualified and
  generating, was the first with real in-betweens: median generated-frame
  advance 0.27 and 0.68 against ideals of 0.33 and 0.67, blend distance
  0.33 of the step, near-zero steps down from 52 to 20 percent.

- Interpolation content, third round (2026-09-02, builds 74-76): the
  presentation's seed fallback samples the 1x1 seed textures instead of a
  per-pair readback (a readback-driven GPU stall had tripped a permanent
  timer-ring rejection and silently switched a session to direct
  presentation); timer-ring and budget rejections are now recoverable
  under the existing bounded re-arm; two relaxed fill passes diffuse
  motion into flat cells that failed only the texture gate. The build-74
  panel recording (paced 40 to 120, kept) measured median generated-frame
  advances of 0.28 and 0.71 with no crossfades and endpoint copies left in
  36 percent of the busiest windows, concentrated in an animated header.

- Interpolation content, fourth round (2026-09-02, builds 78-80): two
  wide 7x7 occlusion-inpainting fill passes give cells with no support in
  either direction the dominant motion of their neighbourhood at weak
  confidence, and the static-HUD hold no longer fires on regions the
  motion field says are moving (a slowly sliding menu header at about 6
  of 255 mean change was being held on both synthetic slots). Comparable
  proof metric across recordings (scene cuts excluded, both slots at an
  intermediate position): build 70 0.53, build 74 0.47, build 75 0.43;
  unpaced light-hold streams are not comparable because the source itself
  repeats frames.

- Synthetic phase lattice (2026-09-02, build 81): the generator's own
  phase diagnostic showed the two synthetic slots of a paced 40 to 120
  stretch at 0.44 and 0.77 instead of 0.33 and 0.67, a constant 2.7 ms
  offset inherited from the priming slot's predicted present time, which
  turns correct in-betweens into uneven motion steps. When a pair spans an
  integer number of output scans the synthetic fraction now snaps to the
  exact k/N of the output lattice.

- GPU budget policy (2026-09-02, build 82): an over-budget dense pair or
  warp now sheds work (fewer coarse iterations, fewer fill passes, then no
  reciprocal refinement) and earns it back after 1200 healthy pairs, instead
  of counting toward a permanent fail-closed; the combined pair-plus-warp
  check uses a windowed maximum. A session that hit nine over-budget
  rejections in ten seconds had silently fallen to direct presentation.

- Starvation fallback (2026-09-02, build 84): a generated schedule that
  cannot prime (its pair keeps being cut by held-frame discontinuities on a
  heavy unpaced scene) used to leave the panel at about 20 presents per
  second while the game rendered 55; after six consecutive prime waits each
  newly retained real frame is now shown once through the direct path, so
  the panel never falls below the source rate. Pacing evidence uses the
  measured delivery tier while the stream is unqualified (build 83), so a
  bridged 60 lattice over 52-58 unique frames no longer hides the downgrade.

- GPU budget policy, second round (2026-09-02, build 85): over-budget
  pairs, stages and warps and timer-ring bookkeeping anomalies (wrapped,
  stale or duplicate query slots) now only shed work; they never reject the
  dense path. A completed pair that ran long is already presented, and
  tearing the epoch down afterwards only produced thrash (33 rejections in
  four minutes on one heavy scene). Lateness is judged by the physical
  cadence gates instead.

- Phase snap follow-through (2026-09-03, build 88): the presentation
  request re-derives its phase from the selected timestamp and asserts it
  equals the controller's phase; the build-81 lattice snap moved the phase
  without moving that timestamp, so every synthetic present threw and reset
  the epoch (2,533 times in one session, with the panel starved to 6 to 20
  presents per second). Synthetic requests now carry the timestamp of the
  snapped lattice position. Also found: a detached device sleeps within
  minutes without harness input (kept awake with the power service during
  proofs).
- Output-lattice snap (2026-09-03, build 89): the build-81 snap quantised
  the synthetic phase to the PANEL scan lattice, so a 30 -> 60 pair on the
  120-Hz panel (four scans, two outputs) could land at 0.25/0.75 instead of
  0.5; the build-88 proof recording showed the big/small/big step triple
  (0.44, 0.14, 0.42). The snap now quantises to the uniform OUTPUT period.
- Recording-side labelling (2026-09-03, build 90): while
  /data/local/tmp/lucent-proofmark exists, every presented synthetic frame
  carries a 32-px magenta tag in the window's top-left corner (real frames
  carry nothing), so a panel recording labels real/generated frames from the
  pixels alone. The tag is polled every 120 synthetic presents and is off by
  default; it is a debugging aid, never product output.
- Build 91 (2026-09-03) loosened the cycle/spatial gate magnitude slopes
  (.04 -> .10) and wide inpainting (8 -> 5 agreeing cells) against a
  "dashing sprite holds an endpoint" reading. That reading was a tracker
  artefact (see the correction below); the change produced no measurable
  difference and was reverted to the calibrated values in build 96.
- Hard cuts (2026-09-03, build 92): the Java scene-cut guard was dead code
  (densePairMeanDifference was only ever reset to zero), and at the GC
  title flash (black -> logo) surviving photometric matches warped pieces
  of the logo into the synthetic. A 1x1 pass now measures the fraction of
  the global-seed sample grid whose luminance differs by more than 0.12 at
  the zero and seed shifts; above 0.35 the interpolate shader presents the
  exact left endpoint for the whole synthetic.
- DS lower panel (2026-09-03, build 97): harness run nds-b57's "rendered no
  lower UI" was the downstream symptom of an uncommitted 2026-09-02 swap of
  the melonDS stacked halves in LibretroEngineSession.presentVideo (and the
  matching Vulkan region): the DS top screen went to the Thor lower panel
  and the touch screen to the main panel, so every lower-panel gate could
  only ever see boot logos. The b57 captures (touch-screen "Saving..." on
  display 0, KONAMI on display 4) against nds33d/nds34 (emblem editor and
  gameplay on display 4) settle it. Reverted to the top-first split.
  Still latent: the secondary generator never posts a buffer for a static
  lower crop until a unique endpoint survives an epoch resync.
  Build 98 also publishes the core's paced/synchronized cadence to the
  lower-panel generator at surface attach and on every pacing change
  (LibretroEngineSession.publishLowerSourceCadence), and the generator
  goes direct the moment that clock arrives (displayId > 0), so a static
  touch-screen crop is shown at once instead of waiting for a unique frame
  to survive an epoch resync. The harness (run_runtime_acceptance_qa.py)
  now host-resets melonDS at Portrait of Ruin entry, settle-polls the
  lower panel for a stable rendered frame, presses START only, counts
  text-on-black as rendered, polls the slot gate for 3 s, and requires the
  secondary generator's first successful swap within 10 s of the primary.
- Build 99 (2026-09-03): the same cadence publish for native-adapter
  sessions (Cemu's GamePad view on the lower panel sat at presents=0 for a
  whole harness run, wiiu-b98b, so the steady-tier gate saw no display-4
  health records). The harness's reviewed motion-bound cap moved from 80 to
  108 px to match MAX_FLOW_PIXELS (raised 2026-09-02); every 1080p source
  reports 108.0 and had been failing the evidence gate on that mismatch
  (switch-b98b).
- Builds 100-102 (2026-09-03) tried to treat a full asynchronous signature
  ring as backpressure (melonDS submits 60 software frames/s while the
  unqualified panel presents 16-20; nds-b99 rejected dense seven times on
  it). Keeping the ring and classifying synchronously stalled the GPU every
  frame (build 100); re-arming without counting (build 102) restarted
  qualification too often. Both are reverted; the ring-full case is again a
  counted transient rejection as in build 99, which the Thor bisect showed
  qualifying the Wii U attract within 3.5 minutes. The harness's Portrait
  of Ruin story advance grew from 180 to 400 A presses with a START every
  24 to skip the opening cutscene.
- Operational trap (2026-09-03 13:34): the device's durable Frame
  Generation preference (display-frame-generation.xml) had been left at
  mode=lsfg by the LSFG demonstration, so every built-in proof attached the
  LSFG private-beta transport, accepted no endpoints and never qualified;
  ten proof runs timed out before the log line "LSFG private beta
  qualification transport active" was noticed. Built-in proofs must set
  the mode back (scratchpad set_framegen_mode.sh built-in-alpha) first.
- Per-system proof protocol (2026-09-03, the owner's standard): a tagged
  120-fps panel recording under stick motion; every generated frame between
  two real frames is judged on the busiest 2 % of pixels (advance between
  0.12 and 0.88, not within 10 % of an endpoint, blend distance above 0.08
  where a crossfade scores 0.00 and a rigid true intermediate 0.23-0.28);
  cut runs (a near-black endpoint) are judged separately against the
  hold-left contract. Tooling: scratchpad proof_all.sh, prove_system.py,
  proof_report.py. Build 102 results: Wii U PROVEN (202 frames, 98.5 %
  useful, 1 % duplicates, 0 % crossfades); GameCube attract WEAK (cut and
  fade heavy scene; 18 cut violations from a logo flash under the 0.35
  cut threshold).
- Builds 103-104 (2026-09-03): the static-HUD hold survives moving flow
  where the warp would replace a static pixel with clearly different
  content (the "A Start" prompt was bent on Wii U); the hard-cut threshold
  drops to 0.25 of the sample grid.
- Cadence reject is recoverable (2026-09-03, build 93): three slow HEALTH
  windows in the 3D World level (heavier than its map) rejected dense with
  recoverable=0 and the session presented direct for good. The reason is
  now in the transient list, so a later HEALTH boundary re-arms dense under
  the same bounded limit once the cadence is sustainable again.
- Corrected (2026-09-03, later): the "fast sprite holds" reading above was
  a measurement artefact. The 48x48 template tracker locked onto dust and
  grass while Mario stood still, which produced fake 25-52 px "moves" with
  copy-of-A / copy-of-B slots. A metric that measures the advance inside a
  box around Mario's own red centroid (scratchpad box_metric.py) puts the
  generated frames at ~0.30 / ~0.66 for Mario moves of 6-30 capture px
  (12-60 px at 1080p) on builds 90, 91, 93 and 94-off, with zero endpoint
  holds. Note the screen recording is 960x540, so every pixel figure in
  the proof panels is half of the 1080p value. The remaining confirmed
  defect on sprites is ghosting on fast skid reversals (a pose flip with
  ~80 px of motion at 1080p), which no flow method resolves cleanly.
- Build 94 (2026-09-03, design workflow wf_e0d42d36-74d): advected temporal
  prior. The previous pair's validated backward field is carried forward
  (direction 1 exactly, direction 0 by a 9x9 gather + fixed point) into a
  128x72 predicted-flow texture per direction; the solver offers it at
  level-2 it0, level-1 it0 and level-0 it1; validation admits a temporal
  tier (41-44/255) for one-sided matches that agree with the prediction
  and changed between the endpoints; the fill keeps temporally consistent
  weak vectors; wide inpainting is dropped (fill passes 6 -> 4) and the
  legacy global block is branched out of the dense warp to pay for it.
  Kill switch /data/local/tmp/lucent-temporal-off for same-session A/B.
  Verdict (same session, level 1-1, two 8-s dash clips per arm): the
  box-around-Mario metric was already at 0.39 / 0.63 with the prior off and
  0.34 / 0.65 with it on (no gain), while the frame-wide tagged intermediate
  fraction fell from 97.5-98.3 % to 91.7-94.1 % and endpoint holds rose from
  0.1-1.5 % to 3-6 %. Reverted (build 95); only the dense-mode branch around
  the inert legacy global block of the warp shader is kept.

Per-system tagged proofs on build 99 (2026-09-03, scratchpad prove_system.py;
strict = generated frame's textured blocks match a real neighbour with
coherence >= 0.9, lenient >= 0.6; duplicates and crossfades counted
separately):

| System | Scene | Judged | Dup | Xfade | Lenient | Strict |
|---|---|---|---|---|---|---|
| Wii U | 3D World attract 30->60 | 206 | 0.5 % | 0 % | 92 % | 81 % (PROVEN) |
| 3DS | A Link Between Worlds 40->120 | 462 | 0 % | 0 % | 99 % | 70 % |
| PSP | God of War intro 30->60 | 240 | 0 % | 0 % | 96 % | 47 % |
| Dreamcast | Crazy Taxi attract 40->120 | 58 | 2 % | 0 % | 91 % | 53 % |
| PS2 | God of War combat 30->60 | 239 | 0 % | 0 % | 86 % | 26 % |
| GameCube | Metroid Prime attract video | 240 | 25 % | 8 % | 51 % | 48 % |
| N64 | Ocarina attract 20->60 | 286 | 0 % | 0 % | 30 % | 4 % |
| Switch, Wii, DS | no sustained qualification within 15 min | - | - | - | - | - |

Duplicates and crossfades are essentially gone; the remaining defect is
warp coherence on fast or non-rigid motion (combat, 20-Hz pans,
interlaced video), which is the estimator's design limit rather than a
tuning matter.

- Build 104 (2026-09-03, first "mirror FSR 3" change): the dense pyramid
  is now a box-filter ladder (history -> /4 -> /16 with exact 4x4 boxes
  from paired bilinear taps, then 64x36 and 32x18 with exact 2x2 boxes)
  instead of a direct draw that kept a 2x2 point sample of every 30x30
  block. The solver review found that aliasing to be the main reason the
  32x18 search has no clean basin for large motion. To be judged with the
  tagged proof on N64, PS2 and GameCube against build 99.
- Build 107 (2026-09-04): pop-in guard in the interpolate shader. Content
  that appears or disappears between the endpoints (a blinking PRESS START
  on the GBC title, gbc-q1) has no physical intermediate; where only
  weak/filled vectors support such a cell the photometric one-sided match
  is a fragment of unrelated text, so those cells now hold the exact
  nearest endpoint. Validated vectors still warp.
- Build 112 (2026-09-04): the scaled budget now derives the output slot
  from panelScansPerOutput() x panelPeriodNs (targetOutputHz() reports the
  panel lattice on the Thor, so build 111 still returned 7333 on the
  2-scan tiers: v26c PS2 log denseGpuBudgetUs=7333 with MaxUs 7556 shed).
  Results on 111 with the 256x144 finest level (v26 opt-out): PS2 Shadow
  of the Colossus 30 -> 60 PROVEN 100 %/100 % (n=320, 0 dup, 0 xfade);
  N64 OoT qualified 20 -> 60 (835 qualified polls) but the proof never
  reached READY (windowGenerated stayed below the 20-frame gate), rerun on
  112 as v26d. GameCube Metroid Prime 20 -> 60 PROVEN 100 %/100 % (n=282)
  once the entry used Dolphin's mapping (pad B = GC A); the earlier attract
  clip had scored 9 %. Proven so far with the built-in generator: Switch,
  Wii U, Mega Drive, GBC, GameCube, PS2.
- Producer-collapse diagnosis (2026-09-04 evening, 4-reader workflow with
  adversarial verification; synthesis cut short by the session limit).
  Surviving hypotheses, ranked: (1) the tier pacer paces the core's stamp
  clock to 20 Hz after a transient (heavy first pairs at 256x144 level 1,
  or the harness kill on build 108); OoT presents every 3rd VI, so paced
  stamps span exactly 3 periods = 150 ms, which the generator's continuity
  gate (endpointSpanBridgesHeldFrames accepts 1.5-2.5 periods) rejects on
  every endpoint, so no pair forms, the work level never restores and the
  pacer's only lift path re-latches within one report (the 20 -> 19 -> 20
  limit cycle in the log). (2) The paced 150-ms stream is invisible to the
  feedback paths, so pace, tier reading and work level latch one-way.
  (3) The pacer has hysteresis on entry but no exit. Native-adapter PS2 is
  immune because it is never paced. Confirming checks and the fix were
  not applied yet: the pacing code was being refactored concurrently by
  another session (InWindowGameHost.java rewritten 20:37).
- 256x144 on N64 starves the core (build 112, v26d, 2026-09-04): with the
  scaled budget the generator stayed at work level 1 (one shed at launch,
  no level-2 collapse), windowGenerated 60 per 120 presents, but the core
  submitted only 6.2 fps mean (hwSubmits 7/s, hardwareHz 6.94) for the
  whole 20-minute session, so the committed cadence never qualified
  (target 19, actual 5-6) and the proof timed out. PS2 (ARMSX2, its own
  Vulkan swapchain) ran the same 256x144 level at full rate and proved
  100 %; the libretro GL producer path is what stalls. Next: 192x108 (v27)
  on N64, and find the per-pair wait that holds the producer.
- Harness NES header resolution (2026-09-04): the device library index
  holds exactly one "nes|10-yard fight" row (1082 NES rows), yet run e2-nes
  failed with "does not resolve uniquely ... matches=[0, 543, ...]": the
  verbatim-containment tiebreak also kept the two-letter row "Ys", whose
  normalized title sits inside the header's own SYSTEM. Among verbatim
  containments the strictly longest title now wins when every other
  candidate is under four characters; equal-length duplicates and
  "Beta" vs "Beta Special" stay ambiguous (both pinned by tests). The
  ".fcs files indexed as games" hypothesis was wrong.
- Handheld entry results (build 111, chain 4): GB Adventure Island reached
  gameplay but the stick pattern does not move a d-pad game (15 motion
  frames, lenient 100 %), so the motion proof gained AXIS_CODE=16 (HAT
  d-pad); Game Gear Addams Family reached the in-game status card (the
  second START paused it); GBA 007 EoN still sits on the language select
  (A and START do not confirm; B is next).
- Harness matrix (2026-09-04): requiredTitles now name the proof scenes
  the physical runs actually used, so the alphabetical first title cannot
  silently replace them: gb Adventure Island (the first title, 4-in-1
  Funpak, is board games with no motion), psx Mega Man X4 (Bushido Blade's
  attract demo cuts every second), dreamcast Crazy Taxi, psp God of War:
  Ghost of Sparta, wiiu Super Mario 3D World, switch Metroid Dread. The
  harness startup check also accepts the CONTINUE PLAYING / MOST PLAYED
  home rows when the small footer OCR fails over busy artwork.
- Build 111 (2026-09-04): per-pair GPU budget scaled to the output
  lattice. The 256x144 finest-level experiment on N64 (v26b: opt out of
  the v28 128x72 analysis) hit "Dense work shed reason=async-gpu-pair-
  over-budget" twice within 12 s of launch and then cycled restore/shed
  every 60 s on combined-pair-warp-over-budget, so it sat at work level 2,
  which runs zero synthesis passes: the session qualified 20 -> 60 but
  presented endpoints only (no tagged frames, proof TIMEOUT). Level-2
  pairs cost 1.9-2.3 ms; level-1 pairs plus the 0.5-0.7 ms warp exceeded
  7333 us. The fixed budget is 88 % of one 120-Hz scan, but the 20/30-Hz
  tiers output on a 60-Hz lattice with 16.7-ms slots, so denseGpuBudgetUs()
  is now 80 % of the output period minus a 1-ms warp reserve, never below
  7333 (unchanged at 120-Hz output). Entry-sequence proofs on build 110:
  Mega Drive PROVEN 84 %/99.9 % (n=709), GBC PROVEN 96 %/98 % (n=280,
  007 TWINE gameplay after START,A,A,A); GBA still on menus (13 frames).
- Build 110 (2026-09-04): generator startup off the UI thread. The
  frontend showed Android's "EmuFusion+ isn't responding" dialog over live
  gameplay (ANR traces 09-03 09:10 / 13:06 / 18:00, 09-04 03:19; one was
  captured inside the Mega Drive proof clip). GameSurfaceView.surfaceChanged
  runs inside the window's pre-draw traversal on the UI thread and
  constructed the generator synchronously there: the LSFG startup proof
  plus its bounded clean-transport retry took 2.8 + 4.8 s (Davey 7653 ms
  and 8896 ms on the app's RenderThread, then "Input dispatching timed
  out ... Waited 5001ms for KeyEvent"). Startup now runs on a single
  daemon worker; the UI thread publishes the engine Surface afterwards
  (listener.onSurfaceAvailable), a destroy that lands mid-startup bumps
  the surface generation so the finished generator is closed instead of
  attached, and Off keeps its synchronous direct bypass. The proof/harness
  detach scripts (launch_detach_only.sh) also no longer wait for a NEW app
  pid, which left N64 OoT running unproven for 30 min on 2026-09-04.
  Verified 2026-09-04 09:23 on the Thor (N64 OoT, LSFG selected, harness
  launch then 40 s of gameplay): 0 "ANR in com.thorium.preview" lines, no
  app Davey frame at all, and "Generator startup completed off the UI
  thread elapsedMs=4798" followed by a qualified 20 -> 40 LSFG cadence.
- Build 109 (2026-09-04): aperture tie-break in the dense solver. The
  snes-q1 proof (a baseball field: flat green with horizontal yard lines)
  shredded the lines into differently displaced segments because a
  horizontal line matches itself under any horizontal shift, and both the
  scan-ordered exhaustive search and the greedy walk take the first of
  many equal-cost candidates (the most negative x). Every candidate now
  carries a 0.0025/px penalty (capped at 12 px) on its distance from the
  prior neighbourhood median (zero at the coarsest level), which is far
  below a textured match's photometric gain and only decides otherwise
  indistinguishable candidates; FSR 3 keeps its centre candidate on ties
  the same way.
- Measured 2026-09-04 (build 109, N64 OoT 20 -> 60, analysis 128x72):
  denseGpuCompleteLastUs 4496, MaxUs 5025, warp P95 929 us against the
  fixed DENSE_GPU_BUDGET_US 7333. The q1 N64 clip's real displacement was
  median 31 px / p90 42 px / max 71 px at 1080p (inside the old 108-px
  bound); its failure mode is object-level parallax (a tree stump and Navi
  torn into differently displaced pieces), i.e. the 128x72 finest level
  (15-px cells) cannot separate thin foreground from background. A finer
  finest level is the next FSR 3 / LSFG-style change, but at 4x the
  fine-level work it does not fit the fixed budget unless the budget
  scales with the source period (50 ms at 20 Hz).
- Build 108 (2026-09-04): MAX_FLOW_PIXELS 108 -> 216 and
  MAX_FLOW_SOURCE_FRACTION 0.10 -> 0.20 (a 20-Hz N64 pan moves about
  200 px per source frame at 1080p; the SNES baseball field scroll and the
  GameCube attract exceeded 108 too). The validated flow planes switch to
  a signed square-root encoding (code = sign(n) sqrt(|n|), n = v / limit)
  so a 1-px vector still spans about 9 codes at the doubled range; the
  fill, temporal-guide and interpolate decoders and the offline dump
  reader follow. The harness's reviewed cap is min(216, 0.20 x shorter)
  and its range rule is 20 %.
- Build 105 (2026-09-03, second FSR 3-style change): the coarsest level's
  first iteration evaluates a full 9x9 candidate grid at the coarse step
  (+-48 px at 1080p, 81 objective evaluations on 576 texels per direction)
  before the greedy 3x3 walk, so a coarse texel cannot stall on a plateau
  of the cost. Judged in the same n64/ps2/gc proof sequence after 104.
- Results of 104/105 against 99 on the same scenes (strict/lenient
  coherent-intermediate fractions, duplicates and crossfades ~0 unless
  noted): PS2 God of War combat 26/86 % -> 55/98 % (104) -> 60/99 % (105);
  N64 Ocarina attract 4/30 % -> (104 did not qualify in time) -> 5/55 %
  (105); GameCube Metroid attract 48/51 % -> 12/59 % -> 11/37 % with 30 %
  duplicates on 105 (the attract's video sections differ run to run, so
  GC is not a like-for-like benchmark). The two FSR 3-style changes more
  than doubled PS2 combat coherence; the 20-Hz N64 pan (about 200 px per
  source frame at 1080p) is beyond the 48-px exhaustive reach and needs
  the deeper pyramid search FSR 3 uses (7 levels, +-8 px each).

Still open:

- N64 at 20 Hz: the Ocarina attract pans about 200 px per source frame at
  1080p, beyond MAX_FLOW_PIXELS (108, 10 % of the height) and the 48-px
  exhaustive coarse reach. FSR 3 tracks up to 512 px with seven +-8 px
  levels. Either raise the bound source-rate-aware (and the harness's
  reviewed cap with it) and add a coarser level, or route N64 through LSFG
  once its transport opens on this build lineage.
- Wii (Super Mario Galaxy 2): the A+B chord leaves the title, the Wii
  pointer is the right stick as an absolute IR position (pad B is Wii A),
  and the harness's hotspots create a file and reach the storybook intro;
  the storybook page did not advance on further pad-B presses, so no
  controllable-gameplay clip exists yet. Switch: no sustained qualification within 30 minutes on
  Metroid Dread. DS: the game was not running when the proof waited.

- The harness's optical-flow content gate ("dense bidirectional final-valid
  coverage ≥ 50 %") was first met physically on 2026-09-02 by PS2 (ARMSX2,
  GTA III street traversal, 40 -> 120 x3: full PASS with
  syntheticDistinctFraction 1.0) and then by Wii (Dolphin on the Vulkan
  runtime, Super Mario Galaxy 2, 60 -> 120 x2, report passed with
  syntheticDistinctFraction 1.0; the run then failed only the return-to-
  library recording smoke); before that it had never been met by any core
  since it was introduced (`FRAMEGEN-N64-V53-STOP-2026-08-23.md` records 39-40 % as the
  best result), so no run earns a PASS verdict even when its cadence is
  perfect. It is a generator-quality bar, independent of the tier protocol.
- Interior phases still wander by up to ±0.1 of a source period (display
  prediction versus ideal stamps); presents remain on their scans. The
  `Phase diagnostic` log now carries `endpointOffsetUs`/`driftUsPerS` for
  the follow-up exact-phase work.
- N64 scene automation: Ocarina's staged scene yields too few confident
  motion samples; F-Zero's attract races end around the capture; 007's
  mission intro needs the longer 180 s owned-menu bound.

- Held-frame clock funding (builds 28-29, Dolphin Metroid Prime, ~4-11 %
  ordinal-proven held frames in clusters): the 30-second canonical
  re-acquisition completed on the proven-duplicates matcher but generation
  is funded only by the qualified unique clock, whose strict ten-second
  proof admits zero held frames. The completed duplicates window now funds
  the qualified clock directly (the low-rate ordinal grid stays
  diagnostic-only), and retention admits 80 % ordinary periods against the
  90 % acquisition bound (`ACQUISITION_ORDINARY_PERCENT` /
  `RETENTION_ORDINARY_PERCENT` in AdaptiveFrameRateController) so clustered
  holds do not bounce the lattice back into re-acquisition.
- Vulkan-runtime cores (ARMSX2, Azahar, Dolphin on Wii) presented with
  real-time buffer stamps, so no clock ever qualified (PS2 run ps2-b30, 1.6 %
  RMS period jitter). `lucent_android_vulkan_backend.c` now enables
  `VK_GOOGLE_display_timing` and stamps every present with the same ideal
  lattice as the GLES backend (desiredPresentTime = sequence / synchronized
  Hz), and the host treats both hardware runtimes as stamped producers.
- Load-hold downgrade probe (`InWindowGameHost.applyTierPacing`): a core
  called at its full clock whose game delivers 42-56 unique frames under
  load (Flycast attract, run dreamcast-b30) is paced at the measured lower
  tier after 75 s of unqualified evidence on an irregular stream, kept only
  if that lattice is delivered cleanly within 45 s, otherwise lifted with
  backoff. "Irregular" means the ratio of the submission clock to the
  MEASURED unique-image rate (not the previously qualified clock, which a
  30-fps section of a PSP title still reported as 60 in run psp-b52b) is
  not within 6 % of an integer of at least two: melonDS's exact 2:1 schedule measured 2.03
  on one-second buckets and the 2 % test paced a DS game down to 20 (run
  nds-b50b), while genuinely dropping cores sit at 1.04-1.13. The probe
  also gathers no evidence while the timing authority reports a canonical
  clock acquisition in progress, so a core whose full lattice will fund
  through the 30-second held-frame proof (Metroid Prime on Dolphin, run
  gc-b50b) is never paced down first, and a core submitting on its 60-Hz
  lattice with at least 55 unique frames per second is never treated as
  irregular at all: pacing such a game to 40 only trades a bridged 60 -> 120
  for a 37.5-unique 40 lattice (run gc-b52), while a 54-unique game (PS2
  GTA III) still takes the downgrade.
- Native-adapter engines (Cemu for Wii U, Eden for Switch) present through
  their own Vulkan swapchains, so their SurfaceTexture stamps were real-time
  queue times and no clock could qualify (run wiiu-b32). Both vendored trees
  now load `VK_GOOGLE_display_timing` and chain `VkPresentTimesInfoGOOGLE`
  with an exact 60-Hz lattice stamp that follows real time (nearest slot
  after the previous one; a dropped guest frame skips a slot, which the
  generator treats as a held frame). The host also declares a trusted 60-Hz
  producer timeline for adapter sessions: with it the timing authority reads
  a dropped guest frame (a doubled span with one submission) as a
  transport-loss slot instead of an anomaly, so the clock qualifies. In
  slot-lattice producer mode (set by the host for adapter sessions) that
  span is further credited with the lattice-implied ordinal, so it is an
  ordinal-proven held frame for clock proof and is bridged by interpolation
  instead of cutting the pair (Switch run switch-b36 had logged 1005 such
  cuts in five minutes; the generator's own pair checks carry the same flag,
  since Wii U run wiiu-b38 still cut ~5 pairs per second there). A canonical clock proven by the 90-period bootstrap
  but never funded now funds generation after thirty seconds of retained
  evidence. Because a slot-lattice producer submits only the frames its
  guest presented, the trusted lattice itself vouches for the 60 tier and the
  held-slot budgets are 75 % (acquisition) / 65 % (retention) there; Cemu
  titles on the Thor drop 10-25 % of slots under load. A genuine 50-59 -> 40
  downgrade for the adapters would need adapter-side pacing, which does not
  exist yet. Adapter artifacts and their source-lock pins were rebuilt
  accordingly. aPS3e still presents with real-time stamps (no local source
  tree to rebuild).
- Harness (runtime-acceptance) fixes landed alongside, none of them
  protocol changes: the PS2 title-cadence regexes accept the split
  "Presentation health base" record; an accent-colour system-label OCR
  fallback proves the platform label under wallpaper-accent theming (3DS);
  the Wii Galaxy A+B prompt wait is 90 s so the strap warning and space intro
  fit, and its OCR scans three vertical strips because today's letterboxing
  put "Press A and B." above the historical strip (run wii-b50b read only
  the copyright line for 64 probes with the prompt on screen); the Alpha-index title resolver prefers a verbatim title over a fuzzy
  sibling (DS Castlevania rows). Wii U joins DS in the either-stream steady-tier rule, since the GamePad
  stream on the 60-Hz secondary panel runs direct by protocol while the TV
  stream generates (run wiiu-b48 held a 94-second qualified 60->120 segment
  that the both-streams gate never captured).
- Output-credit ledger: a bridged held or dropped frame spans two or three
  source periods and owns that many times the output slots, but the buffered
  scheduler credited it like an ordinary endpoint, so the pair ran out of
  credits before its selected slot reached the right timestamp and stalled
  until the endpoint FIFO coalesced into a reset (once per second on Cemu,
  run wiiu-b39). Credits are now granted per bridged span period.
- Physical cadence proof: the EGL frame-timestamp query keeps only eight
  frames of driver history, and the in-process Cemu/Eden adapters delayed
  the poll past it on most frames (Wii U: 12239 expiries, zero compositor
  drops). An expired query is now an unverifiable frame bridged by the next
  verified present with exact scan accounting, at most a quarter of the
  window may be unverifiable, and compositor drops remain fail-closed. The
  per-scan interval tolerance is 3 % (250 us at 120 Hz): the Thor's
  reported present times jitter by ~0.17 ms on single scans, while a missed
  scan is +100 %.
- Adapter look-ahead: Cemu and Eden deliver through their own swapchains
  with a few milliseconds of arrival jitter, and the remaining physical
  rejections on Wii U (run wiiu-b42) were real missed scans when a pair
  rotated before its successor was retained. Slot-lattice producers now
  prime deeper (six retained endpoints, three more than the libretro path),
  which costs three source periods of latency on those systems only; heavy
  Cemu scenes deliver a slow guest frame after its interior 120-Hz slot
  every few seconds otherwise (run wiiu-b49: a 196-second physically
  qualified stretch that the harness still cut on those "due but no
  endpoint" bursts). They also bridge up to two
  consecutive dropped frames (a three-period span) by interpolation, since
  cutting the pair there cost a four-endpoint re-prime of 6-13 empty scans
  each time (571 cuts in run wiiu-b45); longer gaps remain cuts.
- Adapter stamp quantization: Cemu and Eden stamp each present on the
  nearest real-time lattice slot, so a stamp can lead real time by up to half
  a source period. Against the scheduler's display anchor that read as a
  material reversal ("left-endpoint-lead-too-large") and then tripped the
  duplicate-synthetic-target guard while the display caught up, about 700
  epoch resets per half hour on Wii U (run wiiu-b43), each costing 6-10
  scans. For slot-lattice producers both cases are now a one-scan wait
  (which presents nothing and therefore is not counted as a repeated
  producer-clock sample in the health evidence), and
  the adapter stamps themselves moved to floor quantization (the slot at or
  before the present, never ahead of real time) so the waits disappear at
  the source.
- Harness timing for the native-adapter systems: the TV stream's steady
  segment on Wii U first formed about four minutes after generation began
  (30-second canonical funding plus the title's opening scenes), so Wii U
  and Switch get a 480-second steady wait and a 720-second capture cap, and
  the either-stream wait now reports the primary stream's own reason. The
  evidence verifier bounds a bridged window by the output lattice (output
  rate x elapsed plus the retained-endpoint allowance) as well as by the
  contract factor of consumed endpoints, since bridged dropped frames
  legitimately present more outputs than twice the unique endpoints. Its
  proof-arm check requires every arm to precede the selected segment rather
  than exactly one arm in the whole log, because the downgrade probe arms
  the proof at the full tier first and again after pacing (GameCube run
  gc-b54: 40 real + 80 generated at 120 with on-time 1.0 once scoped).

## Superseded 2026-08-26 contract (historical)

For measured source `S`, measured panel refresh `P`, and selected output `D`,
the 2026-08-26 contract required `S <= D <= min(2S, P)` with `P / D` an
integer, giving 20→40, 24→40, 25→40, 30→60, 40→60, 50→60 and 60→120 on a
120 Hz panel. Its uniform-divisor rule survives; its 2× ceiling does not.

Frame generation is enabled by default for every internal system and can be
turned off from **Settings → Frame Generation**; the next internal game then
receives the real display surface directly. External emulator applications
own their process and surface; EmuFusion does not intercept their frames.

During gameplay, the upper-left badge reports four independent facts:

```
S<stable source> T<selected target> A<actual physical presentation rate> <backend>
```

`S`, `T`, and `A` are never aliases. `T` is a plan; `A` is derived only from
successful physical-present evidence. SurfaceFlinger/present-fence timestamps,
not submissions or the badge itself, remain the certification authority. A
presentation miss never rewrites a proven source clock. Backend is reported as
`LSFG`, `Built-in`/the qualified independent backend label, or `Direct`.

The user setting exposes only `Frame Generation: Off / On`. With On, the
session policy is automatically LSFG when legally usable and fully qualified,
then a qualified independent/built-in backend, then Direct. There is no
backend selector. LSFG remains unavailable for product selection until THS
provides written integration, local-extraction, distribution, automatic-use,
and naming permission. `Lossless.dll` and extracted proprietary shaders are
never bundled without explicit redistribution permission.

## Synthetic phase (fixed 2026-08-15 afternoon)

Decoded 120 Hz recordings proved that generated frames were sitting far off
their temporal midpoint: motion regions advanced only ~9% (Kingdom Hearts
platform) to ~28% (Metroid Prime) of the source step — perceptually
near-duplicates, which presented as judder despite perfect present pacing.
On-device phase telemetry showed the scheduler's synthetic phase sweeping a
slow sawtooth (0.58→0.84 over twenty seconds): the wall-clock playhead was
anchored once at prime, so clock skew between Choreographer callbacks and
producer timestamps accumulated without bound.

The fix computes each synthetic frame's phase from its physical display
slot: the offset since the committed real present divided by the true
producer span. Content then matches the instant it is shown; skew can only
act within a single pair, where it is negligible. The current uniform-divisor
planner replaces the superseded 80/100 rational lattices. Historical device
evidence found phaseMean
0.4996–0.5001 in every window on both Dolphin and ARMSX2, and decoded
recordings show generated frames at visibly intermediate positions with
sharp single edges (no crossfade double-exposure). A dedicated host test
(`bufferedSyntheticPhaseStaysCenteredUnderClockSkew`) replays a 59.94-Hz
producer against exact 120-Hz callbacks for sixty seconds and requires every
synthetic phase to stay centered.

## Presentation pacing

`DisplayFrameGenerator` calls `EGLExt.eglPresentationTimeANDROID(...)`
immediately before every visible `eglSwapBuffers`, targeting the next
physical display tick (`presentationTimingMode=egl-android-next-vsync`).
Stale target times are advanced rather than submitted in the past. The
helper is `FrameGenerationCadence.nextPresentationTimeNs`.

Non-divisor output rates are rejected. Every qualified output occupies an
integer number of measured panel scans, with no catch-up burst. Timestamp
resampling decides which exact adjacent endpoint pair and interpolation phase
owns each uniform output slot; it does not authorize a nonuniform scan pattern.

## Architecture

`DisplayFrameGenerator` is inserted at EmuFusion's Android `Surface`
boundary, not inside any individual emulator. Each internal engine renders
into a private `SurfaceTexture`; a Choreographer-driven EGL/GLES compositor
presents real and generated frames to the actual display surface. This
single boundary covers:

- software-rendered libretro engines through `GameSurface`;
- GLES/Vulkan libretro engines through `GameSurface`;
- phase-2 engines (ARMSX2, Dolphin, PPSSPP, Flycast, Azahar) and native
  adapters (Eden, Cemu, aPS3e) through `GameSurfaceView`;
- the Thor lower display, including the clockwise-rotated 3DS lower-screen
  path in `PreviewActivity`.

Every synthetic sample is bound to its exact adjacent retained endpoints and
a monotonic source target. The dense optical-flow path is an independent
implementation; no external frame-generation model or shaders are bundled.

Fixed-rate legacy systems (NES, SNES, GB/GBC, GBA, Mega Drive and peers) use
the core-declared authoritative cadence rather than image-uniqueness
measurement; the NES authoritative cadence and dual-screen proof routing
remain isolated from the adaptive path.

## Historical evidence contract (schema 39; superseded)

The schema-39 producer emitted:

- contract `dense-fragment-128x72-v39-present-timed-vector-trajectory-qualification-x2-presented`;
- variant `fragment-128x72-v39-present-timed-vector-trajectory`;
- `proofSchemaVersion=39`;
- `presentationTimingMode=egl-android-next-vsync`;
- `cadenceRejectConsecutiveWindows=3`.

Schema 38 and earlier grammars (22 through 38) remain parseable without
reinterpretation; schema 38 itself is immutable. Missing or mixed schema-39
fields reject. Dense cadence rejection requires three consecutive eligible
under-target HEALTH windows at the unchanged 96% presented-output threshold;
any ineligible or source-starved window clears the consecutive count. The
analysis grid is 128x72 (the device switch name `emufusion_framegen_dense_v28_160`
is historical). Any timer, GL, atlas, tag, context, discontinuity, or proof
error fails closed to safe direct presentation.

## Safety properties

- Frame generation never invokes an emulator's run-frame function.
- Audio is untouched and remains synchronized to the original emulator clock.
- Pauses longer than 100 ms are ignored by tier measurement so menus,
  loading, and app suspension do not look like a performance collapse.
- Generator creation failure is explicit in logs and falls back to the
  direct surface; qualification treats this fallback as a failure.
- Both display generators are detached during the ordered game-exit
  checkpoint, after the library is revealed.
- The 50% dense validity/content gates are fixed and are never weakened to
  pass a particular scene.

## Qualification evidence (AYN Thor, 2026-08-15)

Historical qualification APKs (debug-signed, not public releases and not
current product qualification):

- schema-39 checkpoint: `fc87b82d3ff1d34a58700652bf67b688b0e8db66416567cd40e943304aab0189`
- full-flag build (all phase-1 cores + Eden/Cemu adapters, `autoSelect=true`):
  `85675ab23404fbabe2ded242d9a7489ec304e6e1be1634661509e24dd53f0910`

The tested Thor top panel exposes physical 60 and 120 Hz modes. The former
80/100 schedules were balanced subsets rather than uniform divisors and are
therefore historical rejected behavior, not current support.

Verified on device with the schema-39 builds:

- Smoke: first live dense HEALTH pair carried the exact schema-39 contract,
  timing mode, and three-window cadence-rejection value; proof off/on cycling
  advanced the presentation epoch, re-reached `denseProofAtlasCapability=63`,
  and restarted atlas enqueue/complete progress with zero atlas, tag, ring,
  or fallback errors.
- PS2 tier 30 (Kingdom Hearts, Dive to the Heart, player-controlled motion,
  64 s): locked `30 / 60` in every reporting window; producerHz stable
  29.52–30.15; exactly 30 real plus 30 generated per second; zero counter
  movement (FIFO coalescing, timestamp corrections, atlas errors); zero dense
  rejections. SurfaceFlinger showed a 99.87%-clean 16.67 ms every-other-vsync
  lattice on the gameplay layer. Decoded 120 Hz screen recording showed
  ~58.5 unique presents per second alternating half-step (generated) and
  full-step (real) frame differences — generated frames are new content, not
  duplicates.
- PS2 tier 60 pacing (Shadow of the Colossus attract, schema-38 build,
  2026-08-15 handover): 2398 frames / 19.978 s = 120.03 fps recording;
  125 consecutive SurfaceFlinger intervals averaging 8.332 ms with zero
  above 12.5 ms; 120 successful presents per second as exactly 60 real plus
  60 generated; dense GPU pair-plus-warp ≈5.2 ms against the 7.333 ms gate.
- GameCube tier 60 (Metroid Prime through Dolphin, Quick-Resume frigate
  gameplay, 58 s player-controlled Morph Ball traversal, schema-39 proof
  on): locked `60 / 120` in 105 reporting windows with exactly 60 real plus
  60 generated presents per second; zero dense rejections; atlas progressed
  62→221 with zero errors at capability 63. During room-load transitions the
  old implementation emitted 40→80 and 50→100 balanced-average lattices.
  Those transitions are now explicitly rejected because their scan spacing
  is nonuniform. One layer's SurfaceFlinger stream showed zero intervals above
  12.5 ms across 3125 samples. Endpoint timestamp corrections advanced
  (+30) at Dolphin's room-streaming hitches — a title characteristic, like
  God of War's combat and Half-Life's zone loads (see below). A decoded
  frame extract suggests slight HUD-text doubling on generated frames
  during fast scene motion; visual-quality review of screen-fixed HUD
  elements is still owed before any release claim.
- Variable-rate robustness (Half-Life PAL, 64 s controlled camera pan):
  output pacing held 98.5% clean 8.33 ms intervals and the badge stayed
  truthful while the engine oscillated between ~60 and ~30; the recorded
  timestamp corrections at zone-load hitches make variable-rate titles
  unsuitable as formal tier-qualification scenes, which must hold a stable
  source tier.

## Qualification-scene characteristics (physically measured 2026-08-15)

The steady-tier gate (>=11 s stable tier, zero endpoint corrections, >=30
proof samples) and the dense content gates (changing pixels, confident
motion vectors, non-crossfade correlation) constrain which scenes can
qualify:

- God of War: mandatory-combat opening; corrections accumulate continuously
  under combat load and the character dies without attack input. Cannot
  hold a correction-free window there.
- Kingdom Hearts: Dive-platform scene holds a pristine tier-30 window
  (zero corrections over 58 s) with player-driven motion, but the intro is
  cutscene-dense and menu automation is racy; content gates need coherent
  held-direction traversal, not oscillation.
- Shadow of the Colossus: attract cinematic has ideal full-screen motion
  for the content gates but scene cuts break the 11-second steady window.
- Metroid Prime: Quick Resume into gameplay bypasses navigation entirely;
  corrections cluster only at room loads.

Physical qualification still outstanding: a full runner PASS manifest for
PS2 (see runtime-acceptance notes), the 20 tier and sustained 40/50 tiers
on 120 Hz, all mappings on a 60 Hz panel, HUD visual-quality acceptance,
and the remaining internally routed newer systems.
