# EmuFusion frame generation — handover D (2026-08-20, ~06:30)

Continuation of `HANDOVER-2026-08-16-EMUFUSION-FRAMEGEN-C.md` after the
2026-08-19→20 overnight era sweep on the corrected (post-audit) stack.
Everything ran physically on the Thor (serial `427c87b2`, adb at
`/Users/tyleryoung/.codex/tools/android-platform-tools/adb`).

## Scoreboard (honest, schema-39 evidence + list-view relaunch smoke)

| System | Status | Evidence |
|---|---|---|
| GameCube | **PASS** 60→120 | run gc5 (08-17 series) |
| PS2 | **PASS** 60→120 (God of War) | ps2 run series |
| PSP | **PASS** 60→120 | `…-psp3` (bounded jitter tolerance) |
| Wii U | **PASS** (SM3DW; Cemu quit-relaunch fixed) | wiiu series |
| Wii | **PASS** 50→100 BOTH Galaxy titles | `…-wii5` — first genuine Wii pass ever; the old "wii11 pass" in handover C was FALSE (it failed on the quick-tap flake) |
| Switch | **PASS** 20→40 (Metroid Dread) + relaunch smoke | `…-switch1`. 20 is Eden's honest rate for the sampled scene; raising it is Eden perf work |
| DS | **BLOCKED** | lower-display present break, below |
| 3DS | **BLOCKED** | same lower-display break (`…-n3ds1`) |
| Dreamcast | close — 2 fixes landed, scene choreography left | below |
| PS3 | **BLOCKED** on aPS3e pacing | ICO locks 20→40 then 15 fps bursts break every steady segment (`…-ps3-1`) |

Also FALSE in handover C: the nds13 "DS 20→40 pass" — its report used the
fabricated `primaryTwoXAnySegment` soft path the audit removed.

## Engine changes (all UNCOMMITTED, in the working tree)

1. `AdaptiveFrameRateController`: re-climb evidence rule — after a
   starvation demotion an upgrade needs the MINIMUM worst-second across the
   whole hold (+3 allowance), with hold restart when unfunded. Kills the
   SMG2 climb/starve/demote churn (42 round trips in wii1). Regression test
   `recurringDipsCannotRoundTripTheStarvedTier` added.
2. `DisplayFrameGenerator.uploadSoftwareFrame`: GPU (async ES3) uniqueness
   classifier for software streams **only while densePyramidEnabled**
   (proof armed) — produces the v31 signature evidence software streams
   never had; CPU compare otherwise. The first version ran the GL path
   unconditionally and **deterministically froze Flycast at the SEGA boot
   logo** (per-frame sync glFinish/readback) — proof-scoped now, Flycast
   boots (dreamcast5+).
3. `LibretroEngineSession` + `StateVault.discardQuickResume`: Quick Resume
   liveness watch — 2 s luminance samples of the dual-screen crops; 6
   consecutive identical samples in the first minute = wedged snapshot →
   discard the resume pointer + `retro_reset` in place. (The Thor's PoR
   snapshot resumed a lit-but-frozen, input-dead zombie on EVERY launch.)
   No early disarm: the zombie flickers two changing samples first.
4. Diag logs (temporary, keep until DS closes): `Tier acquisition diag`,
   `DS crop luminance`.

## Runner/verifier changes (uncommitted)

- Steady-segment: correction/coalesce BURSTS (≥3/window) advance the
  baseline; drip ≤2/segment tolerated (psp2 fix). v37 record-level output
  accepts truthful 1x passthrough; segment validation stays strict 2x.
- Scene-advance presses between content-starved retries (per-system accept
  key); retry classifier is per-candidate; static-scene classes added.
- Wii: lateral probe pulse. DS: HAT probes/motion (melonDS ignores analog),
  4 s corridor legs, B-then-A in-proof presses, PoR pinned, motion floor
  0.5, any-stream steady wait/coverage/window counter, gate falls back to a
  fully-passing secondary (DS games pick their gameplay screen).
- `logcat -G 16M` per run (Flycast audio-drop spam rotated the route
  record out of the default ring → identity binding failed).
- Matrix: nds pinned to `Castlevania: Portrait of Ruin`.

## Open blockers, in priority order

1. **Thor lower display presents black in-game** (DS + 3DS): core outputs
   lit content on both screens, SurfaceFlinger latches 120 Hz buffers on
   the PreviewActivity SurfaceView, screencap of display 4 is pure black.
   Began 08-19 ~23:35 right after a single-screen GBC game ran (its flow
   blanks the lower display); survives reinstalls and a reboot. FIRST STEP:
   have Tyler LOOK at the physical lower panel during a DS game — physical
   black = P0 present bug; visible game = only screencap broke (QA-only).
   Then: `dumpsys activity top` during a black session (is `blackout`
   VISIBLE over the surface?); consider making ACTION_BLANK and
   showGameplaySurface mutually exclusive instead of relying on the
   SurfaceView hole. `SYSTEM_ALERT_WINDOW` appop reverted to default at
   some point — re-grant with
   `appops set com.thorium.preview SYSTEM_ALERT_WINDOW allow`.
2. **Dreamcast scene choreography**: proof samples Crazy Taxi's attract
   cards ('synthesized frames repeat a real endpoint' / steady-tier
   timeouts). Thread into CONTROLLED driving (START → driver select →
   drive) like the PS2/GTA3 flow. The 50/100 lock during attract is
   correct (real 37–42 Hz dips); steady driving should climb to 60.
3. **PS3 / aPS3e pacing**: ICO's 15 fps bursts break the 20-tier segments.
   Engine-level delivery pacing work.
4. Eden/Dread base rate (20): perf work if a higher base is wanted.

## Device settings that MUST stay

- `emufusion_framegen_dense_pyramid=1`, `emufusion_framegen_dense_v28_160=1`
  (global settings): REQUIRED persistent dense-pipeline config. Deleting
  them (mistaken as leaks, 08-20 01:03) silently downgraded every
  generator to v22-only evidence. Restored; never delete.
- Logcat ring: runner sets 16M per run (not reboot-persistent).

## Build

From `unified-android/`: the full flag set now includes
`LUCENT_INCLUDE_PHASE3_APS3E=1` (a stale seven-flag recall silently dropped
the aPS3e adapter — memory `lucent-build-flags` updated). Verify with
`unzip -l <apk> | grep liblucent_native_adapter` → aps3e, cemu, eden, host.
