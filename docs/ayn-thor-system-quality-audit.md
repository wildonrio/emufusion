# AYN Thor system quality audit

Status date: 2026-08-11

This is a fail-closed physical acceptance campaign. A system is `PASS` only
when multiple representative titles satisfy every gate below on one immutable,
hash-bound APK. A title or system that has not produced the raw artifacts is
`NOT TESTED`, never an inferred pass from source or an older APK.

## Per-title gates

1. **Identity and route** — exact APK, packaged engine/core, ROM, device,
   controller mode, display and audio-route identities; library-menu launch;
   one EmuFusion task/process and no intermediary emulator UI.
2. **Launch** — continuous screen video and physical input timestamps from the
   launch edge to the first visible guest frame. Warm and cold limits are
   reported separately; neither may silently consume input.
3. **Geometry** — the aspect-preserving game viewport is maximized to the
   panel: it touches the top and bottom edges, has no horizontal letterbox,
   has equal side pillars when the game is narrower than 16:9, and preserves
   the system/game display aspect without non-uniform stretching.
4. **Frame generation** — unique real game images select the correct
   30/40/50/60 tier from elapsed throughput and generated frames fill the exact
   gap to the 120 Hz panel. Raw content proof must distinguish generated output
   from endpoints, fixed-position crossfade, inverse motion and unrelated
   pixels; SurfaceFlinger must bind those frames to the visible gameplay layer.
   Every tier transition is a separate, temporally overlapping evidence
   segment.
5. **Controls** — every original-system control has the most natural Thor
   binding and produces an observed guest response. Down/up, holds, rapid taps,
   combinations, diagonals, analog aliases and focus changes must not stick,
   repeat, leak into menus or collide with Stop/Reset/Cheats chords.
6. **Audio** — non-silent output, correct format/rate, continuously advancing
   playback, and zero post-warmup underruns, dropped PCM blocks, lost partial
   writes or swallowed write errors during gameplay, overlays, pause/resume,
   volume changes and state operations.
7. **Cheats** — an exact-ROM compatible code is offered, toggled from physical
   controls while gameplay continues, produces its documented observable
   effect immediately, reverses when disabled when the code permits it, and
   persists correctly. A callback invocation alone is not proof.
8. **Stop and resume** — physical held Stop visibly returns to the library
   within 500 ms, no foreign/intermediate screen appears, the state commits
   atomically, the internal engine session and its GPU/audio resources retire,
   and a normal library relaunch restores the same semantic guest state. An
   external route must additionally close its external task/process. A fixed
   continuation must match a no-exit reference. Save failure is a failure and
   must be reported to the user.
9. **Stability** — no visual stutter, audio discontinuity, crash/ANR, renderer
   fallback, forbidden external Activity, stale evidence, unexplained active
   sink, or missing/duplicate artifact.

Every raw screenshot, video, log, input trace, SurfaceFlinger trace, audio
series, state digest and report is recorded with SHA-256, byte count and record
count. An offline verifier recomputes the acceptance fields.

## Campaign inventory

The current Thor library exposes ROM-backed entries for 20 systems. The
installed qualification artifact is intentionally allowed to expose the
research Cemu/Eden routes for audit, without upgrading their release status.

| Order | System | Current route | Status |
|---:|---|---|---|
| 1 | NES | Mesen | **FAIL — remediation in progress** |
| 2 | Mega Drive / Genesis | BlastEm | NOT TESTED |
| 3 | Game Boy | SameBoy | NOT TESTED |
| 4 | Game Gear | Gearsystem | NOT TESTED |
| 5 | SNES | Mesen-S | NOT TESTED |
| 6 | PlayStation | SwanStation | NOT TESTED |
| 7 | Nintendo 64 | Mupen64Plus-Next | NOT TESTED |
| 8 | Dreamcast | Flycast | NOT TESTED |
| 9 | Game Boy Color | SameBoy | NOT TESTED |
| 10 | PlayStation 2 | ARMSX2 | NOT TESTED |
| 11 | Game Boy Advance | mGBA | NOT TESTED |
| 12 | GameCube | Dolphin | NOT TESTED in this campaign |
| 13 | Nintendo DS | melonDS DS | NOT TESTED |
| 14 | PSP | PPSSPP | NOT TESTED |
| 15 | PlayStation 3 | external only | OUTSIDE INTERNAL AUDIT |
| 16 | Wii | Dolphin | NOT TESTED |
| 17 | Nintendo 3DS | Azahar | NOT TESTED |
| 18 | Wii U | Cemu research adapter | NOT TESTED |
| 19 | Windows | DOSBox Pure | NOT TESTED |
| 20 | Switch | Eden research adapter | NOT TESTED |

## NES round 1 — immutable APK `8d8a4489…`

- Device baseline: AYN Thor, QCS8550, firmware fingerprint
  `qti/kalama/kalama:13/TKQ1.231222.001/eng.Thor.20260206.163241:user/release-keys`,
  performance mode 2, fan mode 4, AC powered at 100%, battery 27.0 C,
  Android thermal status 0. Both physical displays reported 120 Hz.
- Exact install and Mesen route closure: PASS.
- 10-Yard Fight produced a visible 256x240 source inside a 1440x1080 4:3
  destination; the destination touched y=0 and y=1079: preliminary geometry
  PASS, awaiting deterministic border-fixture proof.
- Physical held Stop: library visible in 14 ms; Quick Resume commit logged 25 ms
  later: latency PASS, semantic restoration NOT TESTED.
- Frame generation: FAIL. The badge showed 60/120, but the first health window
  promoted only 24 unique images and generated 94 classified images; later the
  controller dropped to 30. Final proof had too few samples, too little
  non-crossfade output, insufficient selected motion, and no matching
  real/generated cadence window.
- Controls: only physical launch/action and motion-worker inputs were exercised;
  complete mapping NOT TESTED.
- Controller identity was captured rather than inferred: event device
  `Odin Controller`, VID:PID `2020:0111`, vendor key-layout
  `Vendor_2020_Product_0111.kl` (SHA-256
  `b00d7b3523a0d390b14082b4db1c925c449115baba94841029e62a3a3638eee8`),
  and Odin Settings values
  `flip_button_layout=0`, `no_create_gamepad_button_layout=0`. Inspection of
  the exact installed Odin Settings APK (SHA-256
  `2bbdf769410a7d96c2a8de6181eda381724fa64b88cab4ed0c1ce3d165139964`)
  maps that pair to controller-style
  index 1 (`Odin Style`); index 0 is `XBox Style` and index 2 disables the
  gamepad layout. The eventual control proof must bind this mode because the
  printed A/B labels and positional Android button codes differ by mode.
- Audio continuity: NOT TESTED. The round launched with `STREAM_MUSIC=0/15`,
  so its advancing AudioTrack head is not audible-output evidence. The fixture
  run must snapshot the owner's index, use a controlled audible index, and
  restore the original value in `finally`.
- Live cheat effect: NOT TESTED.

The round is therefore `FAIL`. No later system starts qualification until NES
passes a new immutable build after the evidence-backed fixes.

## NES remediation checkpoint

- Adaptive tier selection now measures exact elapsed throughput across a
  bounded ten-period rolling window instead of averaging instantaneous
  `1/delta` rates. This fixed both ordinary alternating 55/45 Hz jitter and a
  second real defect where native-60 five-of-six and four-of-six unique-image
  schedules repeatedly crossed a threshold and reset consecutive votes,
  leaving the generator stuck at 60. Exact 5/6→50, 4/6→40, 3/6→30 and the
  complete 60->50->40->30->40->50->60 production-path sequence are tested.
- Frame-generation verification now requires a SHA-bound identity manifest and
  explicit steady/transition segments tied to the exact system, game, ROM,
  core, APK, process, session, generator, display and SurfaceFlinger layer.
  Proof counters are rebased after the target tier settles, so content from an
  earlier tier/title cannot qualify a later one. Classified promoted/generated
  frames and any bounded fallback are reported separately.
- Runtime audio now drains into a bounded FIFO. Partial writes retain their
  exact tail; PCM loss, focus loss, zero/partial writes, sink errors, underruns,
  queue depth and native-drain saturation are explicit counters. No new PCM is
  silently discarded behind an old partial block.
- A bounded, allocation-free-per-sample signal analyzer now measures the PCM
  before `AudioTrack`. Its rolling and cumulative stereo records include the
  exact sample rate/counts, min/max, peak, RMS, DC-blocked positive crossings,
  tone estimate, frequency resolution and saturation state. This can prove
  that the deterministic NES tone reached the Android sink boundary; it does
  **not** prove physical-speaker audibility, so playback-head/queue/error data,
  a controlled nonzero `STREAM_MUSIC` index and external capture where
  available remain separate gates.
- A late background Quick Resume failure now posts a nonblocking library
  notification after the immediate return. Cheat attempts carry identities and
  explicitly report that the void libretro callback is not semantic
  acknowledgement; only observed fixture pixels may prove the effect.
- Controller normalization now has exact AYN profiles before the wildcard:
  PID `2020:0111` maps Odin-style Android emissions back to the Thor's physical
  Nintendo positions, while `2020:0112` keeps Xbox-style emissions. Unknown
  `2020:*` styles omit the four ambiguous face buttons until explicitly
  remapped. End-to-end tests bind each physical slot through Android key,
  canonical position and the NES RetroPad ID; this fixes the round-1 Odin-style
  A/B and X/Y inversion without changing the curated NES layout.
- The new original NROM-128 qualification ROM is 24,592 bytes with SHA-256
  `42019e9ca4a3a11815a9e13b7c60734a73fb7ae3cb06a140915daa4605ee8508`.
  It authors a four-edge geometry marker, a nonperiodic moving field, unique
  visible responses for all eight NES controls, a freeze/resume oracle, a
  reversible exact Mesen cheat effect, and a nominal 440.4 Hz stereo PCM
  source. Its real guest images follow deterministic 60/50/40/30 schedules
  while the core keeps its native callback cadence; the production
  `latestImageIsUnique()` path—not a test timestamp override—selects the tier.
- Its reversible `6000:3F` code is now discoverable through the ordinary
  packaged Cheat catalog as `Qualification red border`, under the exact
  `Lucent Callback Test` title. The visible row carries the fixture SHA and is
  covered by normalised-title, exact-code and packaging tests; the device
  runner is forbidden from bypassing the panel with a native cheat injection.
- The NES offline verifier is being made artifact-driven: it must reopen and
  recompute launch and Stop video timing, geometry, motion, controls, semantic
  resume, two-way cheat pixels, PCM signal/sink continuity, all four steady
  frame-generation tiers and all six adjacent tier transitions. No saved
  summary boolean is an acceptance result.
