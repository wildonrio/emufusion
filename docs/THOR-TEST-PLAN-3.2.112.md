# Thor test plan: 3.2.112 to 3.2.116

Written 2026-10-26 while the Thor was away from the Mac. 3.2.112 (186) was
built and host-verified only. 3.2.111 was never installed, so this plan covers
it too. Follow the safety rules in `AGENTS.md`:

- Install only with `thor_install.py` or `install --no-incremental -r`.
- Verify the package path, APK hash, UID and first-install time before and after.
- Keep both panels off between runs.
- Keep runs short (fan noise).

## 0. Before anything

1. Check that the installed version is what the in-app updater fetched. If the
   updater already installed 3.2.112 from GitHub, verify its identity and hash
   against the release. Do not reinstall.
2. Note stock Eden's own settings on this Thor, for comparison:
   - Eden version (Settings → About).
   - The GPU driver chosen in its driver manager (system or a custom one).
   - Resolution, accuracy and async shaders.
   - Write them down before changing anything in EmuFusion.

## 1. Switch: system driver and display (owner's report)

The question is whether Switch now looks like stock Eden.

1. Check the logs for these lines:
   - `EmuFusionGpuDriver: System driver selected`
   - `Switch GPU driver=system`
   - Eden's own device line, which should name the Qualcomm driver (512.676.53 on this Thor), not Turnip.
   - Also confirm that `files/gpu-drivers/turnip-mrpurple-t23` was removed.
2. Play Metroid Dread, two runs, each up to about 60 s:
   - title → load save → gameplay in a dark area with particles;
   - once with frame generation On and once Off.
   - Screenshot both. With FG Off it should look identical to stock Eden.
3. Play Super Mario 3D World 1-1 the same way.
4. The first run after the update may stutter while Eden rebuilds its pipeline
   cache for the new driver. Run it twice before judging stutter.
5. If shader corruption remains with FG Off on the system driver:
   - A/B with `adb shell settings put global emufusion_switch_gpu_driver auto` (Turnip). Delete the setting afterward.
   - Compare against stock Eden's version. Ours is pinned at Eden commit `c0ffc900c` (August 2026).

## 2. "Android reports 60 Hz" notice

1. On Switch, NES and one 3-D system, check:
   - whether the toast still appears;
   - the log for `Per-app frame-rate override` (modeHz vs compositorHz);
   - the log for `Panel mode held`.
2. During a session where the old toast used to appear, capture:
   - `adb shell dumpsys display | grep -A3 mFrameRateOverrides`
   - `adb shell dumpsys SurfaceFlinger | grep -i -A3 "frame rate override\|overrides"`
3. Expected: no toast at 120 Hz. Turn the panel to 60 Hz in Android settings
   and the notice should appear after about 3 s with the correct rate.
4. If a per-app override is active (60 for our uid with the panel at 120):
   - Find which layer votes 60. Check `dumpsys SurfaceFlinger` for layer frame-rate votes.
   - Our generator votes the planned rate (`Requested game display cadence`).
   - Callbacks throttled to 60 would cap generation. The shown-rate badge tells you this.

## 3. Clock lock with frame generation Off

For each case below, run 60 s with FG Off and grep the log:

| System | Log line to find | What it should show |
| --- | --- | --- |
| Switch (Eden) | `Direct panel clock lock engine=eden` | pacedHz ≈ panel / 2 |
| Wii U (Cemu) | `Direct panel clock lock engine=cemu` | accepted at the fractional rate (new native `42aa96b8`) |
| PS3 (aPS3e) | `Direct panel clock lock engine=aps3e` | pacedHz ≈ panel / 2 (3.2.113 hook; FG On: `Clock correction adapter engine=aps3e`) |
| Dreamcast (Flycast) | `Tier pacing hardware core ... pacedHz=59.9x` | from `trimAudioPacedToDisplay` |
| Neo Geo (e.g. Metal Slug) | — | core runs at panel / 2 (59.95), not 59.19 |
| Arcade, about 57.5 Hz (if available) | — | same |

1. Listen for audio pitch. Neo Geo +1.3% is expected; it should not be obviously wrong.
2. Judder: record 30 s with the QA physical trace (no screen recorder). Expect no
   periodic two-scan holds (before, about one every 20 s on native adapters and
   about one a second on Neo Geo).

## 4. Clock lock with frame generation On (Cemu)

1. Wii U (Super Mario 3D World, Wind Waker HD), 60 s.
2. Check `Clock correction adapter engine=cemu pacedHz=59.9...`. It used to be
   refused silently every second.
3. In the Cemu log, check `source stamp lattice re-based stampHz=59.9...`.
4. pace_card on-interval share against 3.2.110 (SM3DW 94.6%, WWHD 87–97%).

## 5. Take-up lattice (micro stutters)

1. `pace_card.py … auto` on these cases:
   - nsmbud (3.2.110: 98.8% on interval, intervals {1: 1910, 2: 17, 3: 3, 8: 1});
   - Metroid Dread gameplay;
   - SM3DW;
   - gc (Double Dash);
   - snes;
   - oot.
2. Record: on-interval %, the interval histogram, firstGen / real latency, and
   the diagnostics fields `timelineLattice*` (Holds / Follows / Earlier /
   CatchUps / Window).
3. A/B on the same APK with `emufusion_framegen_takeup_lattice=0`, then delete the setting.
4. Expected:
   - two- and three-scan intervals down sharply on Switch;
   - latency at most a scan higher (8.3 ms) on jittery sources, unchanged on paced libretro cores (SNES).
5. If Follows keeps growing in a steady session, the window doubling or the drop
   rule needs work. Send the `Arrival trace` lines (`emufusion_framegen_arrival_trace`).

## 6. Backlog skip

1. On Double Dash and Wind Waker HD, count `Compositor backlog skip` lines in
   60 s. Expected: at most a few, at least 16 s apart.
2. Record the "shown late" share against 3.2.110 (it may rise: backlogs now last
   longer before a skip).

## 7. Artifacts (LATE_NEAR)

1. Device replay bench, paired against 3.2.111's generator:
   - Sets: lt-full, lt-eval, lt-train, lt-small3d (dumps in the session scratchpad's `occl/`, or re-capture).
   - Expected: invented area down about 60% on frames at a share of 0.10 or more, and the reference mismatch up on those frames.
2. Capture Metroid Dread gameplay triplets for the train set. The current Dread
   captures are title-screen only.
3. Visual check with FG On:
   - Sonic Adventure and NSMBU Deluxe menu transitions;
   - Mario Kart Wii item boxes and the start cut.
   - Look for one-scan steps where garbage used to be.

## 7b. 3.2.113 additions

1. PS3 (aPS3e): run a 60 s game with FG Off and FG On; check the clock lines
   above. Also check for normal pacing and audio (RPCS3's VBlank group period
   now follows the host rate; the automatic frame limiter follows it too).
2. Pixel art: run Game Gear (Sonic) and Mega Drive. Count gated frames
   (frames identical to the next real one) against 3.2.112 on the device
   replay bench (2-D sets). Visually check that smooth scrolls stay smooth on
   SNES/NES, where no frame should be gated.

## 7c. 3.2.114 addition

1. Device replay bench, paired against 3.2.113, on the 3-D sets: invented area
   should fall about 20-30% (PICK_3D) with error within a few thousandths.
   Look at Double Dash kart outlines and Wind Waker HD's title logo.
2. GPU time per pair (dense GPU timer) unchanged within noise (one mix per pixel).
3. Device-bench candidate: `propagate_ca` 8/16 in the per-phase search
   (offline -4 to -14% invented area, Star Fox 64 worse); measure its GPU
   cost on Wind Waker HD before considering it.

## 7d. 3.2.115: update check on every open

The updater on the Thor delivers 3.2.115 itself, so step 0's identity check
covers the first part. Then:

1. Open EmuFusion from the Android launcher. Expect no update screen when up to
   date (the check finishes in under 0.8 s), and the log line
   `EmuFusionUpdater` with no "Update check failed".
2. Press A on a game during the first second after opening. It should start as
   soon as the check finishes, not be dropped.
3. When 3.2.116 exists: open EmuFusion. Expect "UPDATING EMUFUSION" with a
   percentage, then Android's installer. Cancel it: the library shows
   INSTALL / LATER, and the installer is not reopened by itself for 10 minutes.
   LATER starts any game that was waiting.
4. Offline (Wi-Fi off): open EmuFusion. The check fails and games start at once.
5. B on the update screen skips it; the download continues and installs on the
   next return to the library.

## 7e. 3.2.116: random hitches on any Android

3.2.116 removes causes of random one-frame hitches that do not depend on the
Thor, and fixes places where pacing assumed the Thor. Measure first, then
compare with 3.2.115 where a QA switch exists.

1. **The app's own count.** Every 30 s of frame generation the log has
   `Present rhythm ... hitches=N usualScans=U onIntendedPct=P` (frames shown
   longer than the usual interval, from the display's present times; no
   marker file needed). Run 60 s each of SNES, NES, Mega Drive, GBA (software
   cores), Ocarina, Double Dash, NSMBU Deluxe, Metroid Dread, SM3DW and God of
   War II. Record hitches per 30 s. Target: 0, at most 1 on heavy Wii U and
   Switch scenes. Cross-check one case with `pace_card.py` (`onIntended`).
2. **CPU work hints** (ADPF). Check the log for `Work hint session
   thread=frame-generator` and `thread=libretro-<core>`. "Work hint
   unavailable" means the device offers none, which is fine. A/B on SNES and
   Double Dash with `settings put global emufusion_work_hint 0` (delete it
   afterwards): hitches per 30 s, `callbackLate`, and fan noise. The hint
   should never raise heat.
3. **Once-a-second snapshot after the present.** `pace_card.py`,
   `lag_series.py` and `hi_summary.py` must still parse the CadenceSnapshot
   lines (they are now written by a background thread).
4. **Software frame buffers recycled.** On SNES and Mega Drive with frame
   generation On, run `adb shell dumpsys meminfo com.thorium.preview` twice,
   30 s apart: the Java heap should stay flat. Check `logcat -b main | grep
   -c "concurrent copying GC"` over 60 s.
5. **Timer glitches.** The Thor (Adreno) should keep `Dense GPU timing ...
   source=timer-queries`. If `Dense GPU timer disjoint; fence timing for this
   session` appears, note how often it happens.
6. **Earliest-latch fallback.** Grep every run for `Earliest-latch planning
   refuted`. It should not appear on the Thor. If it does (heavy Cemu or Eden
   scenes), compare arrival-to-screen latency before and after that line. If
   latency rises without fewer hitches, raise the threshold from two
   ineffective skips or drop the rule.
7. **Passthrough while generation is suspended.** With dense generation off
   (startup, a rejection, or a `Dense GPU overload: generation suspended`
   stretch on Wind Waker HD), each 3-D arrival classifies itself with a
   synchronous `glFinish` + `glReadPixels` (`latestImageIsUnique`; the
   asynchronous query path exists only while dense generation runs). Use the
   QA physical trace through a suspension to see whether real frames hitch
   there. If they do, give passthrough its own PBO and fence readback.
8. **Frame generation Off.** SNES and NES: `Direct display tick clock
   active=true`, and no hitch every ~17 s (QA physical trace, or a 240 fps
   recording).
9. **Bench candidate (no install).** Replay bench, paired, with the C-flow
   propagation shader:
   `python3 tools/learned_framegen/dis_gles.py OUT/DenseInverseSearchShaders.java --propagate-ca`,
   then `sh tools/qa/build_replay_dex.sh OUT.dex OUT/DenseInverseSearchShaders.java`.
   Record invented area and the error against 3.2.116 on all four sets, and
   GPU time per pair. Adopt it only if Star Fox 64 does not get worse and the
   GPU time per pair rises by 0.3 ms or less.

On another Android (the Mac's phone emulator `emufusion_clean_phone_20261007`,
or a phone), with `hw.lcd.vsync` set to 60, then 90, then 144:
- NES and SNES generate.
- `Requested native gameplay panel mode` picks 120 for 60 fps on 144.
- A variable 3-D game at a steady 60 fps moves from 144 to 120 after about
  8 s (`PanelModeReplanner`).
- Nothing crashes on launch. Android 10 used to crash on `Context#getDisplay`.

## 8. After the run

1. Verify both panels are OFF, actual brightness 0/0, no game process, and the
   idle timeout restored.
2. Retire trial APKs per the build-retention policy.
3. Pin the release.
4. Record results under 3.2.112 in the goal doc.
