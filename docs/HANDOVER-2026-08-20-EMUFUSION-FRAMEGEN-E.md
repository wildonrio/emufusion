# EmuFusion frame generation — HANDOVER E (2026-08-20 ~09:00, for AI switch)

Read this FIRST. Supersedes handover D (same day). The goal (user's words):
rock-solid buttery-smooth frame generation for every internally emulated
system from GC/PS2 era and newer **plus N64** — base rate locked at the
HIGHEST rate the game can sustain (never over-demote), filled to the
panel's refresh with generated frames (2x cap: 20/30/40/50/60 →
40/60/80/100/120 on the 120 Hz panel; nothing above 60 on a 60 Hz panel),
only truly presented output reported, all proven physically on the Thor.

Everything below ran on the Thor: serial `427c87b2`, adb
`/Users/tyleryoung/.codex/tools/android-platform-tools/adb`. zsh doesn't
word-split — use `export ANDROID_SERIAL=427c87b2` or `-s`.

## Scoreboard (genuine passes: full schema-39 evidence + relaunch smoke)

| System | Tier | Run directory (unified-android/build/) |
|---|---|---|
| GameCube | 60→120 | runtime-acceptance-qa-2026-08-17-gc* |
| PS2 (God of War) | 60→120 | …-ps2* |
| PSP | 60→120 | …-psp3 |
| Wii (BOTH Galaxys) | 50→100 | …-wii5 |
| Wii U (SM3DW) | 30-50 lattice | …-wiiu series (Cemu relaunch fixed) |
| Switch (Dread) | 20→40 | …-switch1 |
| **N64 (F-Zero X)** | **60→120** | **…-2026-08-20-n64-8** |

Dreamcast: main qualification passed ONCE at 30→60 (…-dreamcast8) but not
yet with the smoke in one run. DS/3DS/PS3: blocked (below).

Two historic claims in handover C were FALSE, discovered by audit:
- "Wii PASS run wii11" — wii11 actually FAILED (quick-tap flake).
- "DS pass nds13 20→40" — used the fabricated `primaryTwoXAnySegment`
  soft path (since removed). DS has never passed honestly.

## The standard run command

```sh
cd /Users/tyleryoung/Code/emufusion
ADB=/Users/tyleryoung/.codex/tools/android-platform-tools/adb
APK=$(ls -t unified-android/build/lucent-3.2.16-phase2-phase3-qualification-*.apk | head -1)
HASH=$(basename $APK | grep -oE "[0-9a-f]{64}")
$ADB -s 427c87b2 shell am force-stop com.thorium.preview
sleep 3
$ADB -s 427c87b2 shell am start --display 0 -f 0x18000000 -n com.thorium.preview/org.pegasus_frontend.android.MainActivity
sleep 25
python3 unified-android/tools/run_runtime_acceptance_qa.py \
  --serial 427c87b2 --apk "$APK" --expected-sha256 $HASH \
  --output unified-android/build/runtime-acceptance-qa-<name> \
  --system <system> --titles-per-system 1 --allow-physical-thor \
  --already-installed --allow-research-phase3 --adb $ADB
```

## Build (from `unified-android/`, NOT repo root)

```sh
LUCENT_INCLUDE_EXPERIMENTAL_CORES=1 LUCENT_AUTOSELECT_EXPERIMENTAL_CORES=1 \
LUCENT_REUSE_QUALIFICATION_CORES=1 LUCENT_INCLUDE_PHASE2_PPSSPP=1 \
LUCENT_REUSE_PHASE2_PPSSPP=1 LUCENT_INCLUDE_PHASE3_EDEN=1 \
LUCENT_INCLUDE_PHASE3_CEMU=1 LUCENT_INCLUDE_PHASE3_APS3E=1 ./build.sh
```
Omitting APS3E silently drops internal PS3 (hit 08-19). Verify with
`unzip -l <apk> | grep liblucent_native_adapter` → aps3e+cemu+eden+host,
and `unzip -p <apk> assets/engine-qualification-opt-in.json | grep autoSelect`
→ true. Output is `build/lucent-3.2.16-phase2-phase3-qualification.apk`
(hash-suffix copies are made manually; runner needs the hash-named file).
Java tests: `cd unified-android && sh test.sh` (all 22 must pass).
Python: `python3 -m unittest tools.tests.test_runtime_acceptance_qa
tools.tests.test_systemwide_frame_generation`.

## DEVICE SETTINGS THAT MUST STAY

- `settings put global emufusion_framegen_dense_pyramid 1` and
  `emufusion_framegen_dense_v28_160 1` — REQUIRED persistent
  dense-pipeline config. Deleting them (mistaken for leaks once) silently
  downgrades every generator to v22-only and every run fails with
  "no health records". NEVER delete.
- Runner sets `logcat -G 16M` per run (route-record identity binding
  needs it; not reboot-persistent).
- After APK installs check
  `appops set com.thorium.preview SYSTEM_ALERT_WINDOW allow`
  (it reverted to default/reject at least once; lower-display routing
  logs `path=startActivity(canDrawOverlays)`).
- Screensaver stays ENABLED (OLED); host-side guard triggers only on true
  staticness. NES Remix stays banned for Wii U (SM3DW pinned); Dread
  pinned for Switch; F-Zero X pinned for N64; Crazy Taxi for Dreamcast;
  Castlevania: Portrait of Ruin for DS (matrix
  `unified-android/tools/runtime-acceptance-matrix.json`).

## All changes are UNCOMMITTED (user hasn't asked to commit)

`git status` shows the working tree. Key files:
- `unified-android/src/com/thorium/lucent/video/AdaptiveFrameRateController.java`
  (untracked): goal-map outputFps, worst-second ring, starvation demotion
  + chronic horizon, capped re-climb backoff, and the re-climb EVIDENCE
  rule (min worst-second across the whole hold, +3 allowance, hold restart
  when unfunded — killed SMG2's 42 climb/starve/demote round trips).
- `DisplayFrameGenerator.java`: software-stream GPU uniqueness ONLY while
  proof armed (unconditional version froze Flycast at the SEGA logo);
  acquisition + crop-luminance diag logs (keep until DS closes).
- `LibretroEngineSession.java` + `StateVault.java`: Quick Resume liveness
  watch (2 s crop-luminance samples; 6 identical in first minute →
  `discardQuickResume` + retro_reset; NO early disarm — the zombie
  flickers two changes first). PoR's snapshot resumed a lit-but-frozen
  input-dead zombie on every launch.
- `unified-android/tools/run_runtime_acceptance_qa.py`: many gate/flow
  fixes — see git diff; notable: per-candidate content-starved retry
  classifier, scene-advance presses between retries, DS any-stream
  semantics (steady wait / latency coverage / window counter / gate
  fallback to a fully-passing secondary — DS games choose their gameplay
  screen: Hunters=top, Castlevania=touch/lower), n64 flow (START entry, A
  loop, motion floor 0.5, patient attract wait in n64_gameplay_evidence —
  do NOT press START between its attempts, that resets F-Zero's demo
  timer), dreamcast flow (B-only loop + use_best_windows), single-word
  title matcher fix (F-Zero X).
- `unified-android/tools/verify_frame_generation_evidence.py`: v37
  record-level output accepts truthful 1x passthrough; per-(pid,generator)
  split-health pairing. Segment validation stays strict 2x.
- Tests updated alongside; matrix pins above.

## Remaining work, in order

1. **Thor lower display presents black in-game (DS + 3DS)** — the core
   outputs lit content on both screens ("DS crop luminance topMean=112
   bottomMean=109"), SF latches 120 Hz buffers on the PreviewActivity
   SurfaceView layer, but display-4 screencap is black. Began 08-19 23:35
   right after a single-screen GBC game ran (its flow sends ACTION_BLANK;
   PreviewActivity `blackout` view). Survives reinstall AND reboot.
   FIRST: ask Tyler to LOOK at the physical lower panel during a DS game
   (physically black = P0 present bug; visible = only screencap broke and
   the QA needs a different capture path). Next diagnostic: `dumpsys
   activity top` during a black session — blackout visibility vs the
   gameplaySurface; consider making ACTION_BLANK and showGameplaySurface
   mutually exclusive. DS harness work is otherwise DONE (30 runs of
   navigation/choreography fixes all landed; PoR reaches controllable
   gameplay reliably).
2. **Dreamcast full pass** — evidence passed once (30→60). Boot is
   lottery-ish even after the Flycast fix (dark-screen hang variant, run
   11), and the attract's static cards starve some proof windows. Either
   retry until a clean run (it does pass), or thread into controlled
   driving (START → driver select → drive; A is throttle — the motion
   worker's generic branch already presses A).
3. **PS3 / aPS3e pacing** — ICO locks 20→40 then 15 fps delivery bursts
   break every steady segment. Engine-level pacing work
   (`engines/patches/…aps3e…` + adapter). See runs …-ps3-1 and the 08-16
   ps3 series.
4. Optional polish: Eden/Dread base rate (20 → higher is Eden perf);
   60 Hz-panel tier matrix (task #4) never physically exercised.

## Where the deep history lives

- Memory: `lucent-era-sweep-2026-08-19.md` (this sweep, most detailed),
  `lucent-framegen-*` (phase-drift judder root cause + empirical
  frame-proof method, qualification scenes, engine fixes),
  `lucent-build-flags.md` (build traps), `lucent-thor-device-testing.md`
  (adb/sendevent techniques — adb `input` cannot reach a running game;
  use `sendevent /dev/input/event9`; menu accepts `input -d 0`).
- Handovers B/C/D in docs/ for earlier context.
- Every run's artifacts: `unified-android/build/runtime-acceptance-qa-*`
  (results.json + screenshots + bounded logcats — the failure forensics
  pattern is: read results.json reason → health-record timeline → probe
  screenshots).
