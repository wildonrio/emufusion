# Thor test plan: 3.2.112

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
| PS3 (aPS3e) | — | no hook; expect no line |
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

## 8. After the run

1. Verify both panels are OFF, actual brightness 0/0, no game process, and the
   idle timeout restored.
2. Retire trial APKs per the build-retention policy.
3. Pin the release.
4. Record results under 3.2.112 in the goal doc.
