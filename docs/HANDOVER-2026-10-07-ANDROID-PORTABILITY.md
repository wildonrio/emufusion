# EmuFusion Android portability handover

Prepared October 7, 2026, approximately 14:15 EDT, for the replacement agent.
The owner explicitly stopped the outgoing agent and requested this handover.
Implementation has stopped. The goal is incomplete; no universal update has
been released. This handover supersedes older notes about the current test APK
and running simulator, not the source changes or historical evidence.

## Objective and acceptance

Deliver one self-contained EmuFusion APK that discovers the owner's games and
launches its built-in emulators internally on a fresh single-screen Android
phone, not only on the already-configured AYN Thor. The owner's concrete
expectation is: install, grant storage access, tap a game, play, exit normally.
No external app chooser or separately installed emulator should be necessary.
Explicitly selected external emulators may remain an optional setting.

Use landscape Android simulator testing with up to two representative owned
games per system. The owner said approximately 19 systems; the evidence matrix
currently has 20 routes, including PC Engine CD. Distinguish library discovery,
boot, responsive gameplay, pause/resume, save/exit, audio/performance, and actual
hardware limits. A packaging pass, attract mode, or loading screen is not a
gameplay pass. Simulator performance is not proof of physical-phone performance.

Prioritize the complete normal install-to-game path over further frame-generation
work, repeated packaging exercises, or open-ended PS3 scheduler investigations.
Frame generation should remain Off for this baseline. Preserve existing feature
work rather than deleting or reworking it without a demonstrated cause.

The owner also previously requested an internet-distributed update and private
diagnostics without personal information or device identifiers. That remains
unfinished downstream work, not a reason to delay internal-launch testing.
Do not publish the debug qualification APK described below.

## Read first and preserve

Repository: `/Users/tyleryoung/Code/emufusion`.
HEAD at handover: `e21215170f5f181e1d4a1f3d4032b2af99ecc003`.
There were 1,381 dirty/untracked status entries before this handover. HEAD is not
the complete implementation. Other agents' edits are mixed into the working tree.
Do not reset, checkout over, clean, or bulk-revert the tree.

Read these selectively rather than replaying the entire history:

- [Project safeguards](../AGENTS.md).
- [Current priority log](FRAME-GENERATION-GOAL-2026-09-04.md), beginning at the top.
- [Per-system evidence matrix](qa/android-portability-2026-10-02/matrix.json).
- [Latest complete package verification](qa/android-portability-2026-10-07-ps3-input-lifetime/retry-1/normal-package-result.json).
- [Clean phone evidence and helpers](qa/android-portability-2026-10-07-clean-phone/).

The matrix is historical and verbose. Its top-level candidate and
`latest_clean_phone` still name the preceding `2d4e` APK; the latest installed
candidate is `21a4`, below. Likewise, numerous fields named `latest_*` describe
different older APKs. Do not silently combine those into a current all-system pass.
Update the selected current fields when resuming qualification.

The goal tool currently reports `blocked`, inherited from an older audit.
The objective is not achieved. That status does not mean every simulator task
requires the Thor. The outgoing agent is stopped at the owner's request.

## Current APK and exact changes

Latest complete normal-source **debug qualification** APK, version 3.2.16,
versionCode 90, package `com.thorium.preview`:

`/Users/tyleryoung/Code/emufusion/unified-android/build/lucent-3.2.16-lsfg-framegen-qualification-21a40411b19a22cc928a5d021e337160f79855837fecc19b4828948868eee301.apk`

SHA-256:
`21a40411b19a22cc928a5d021e337160f79855837fecc19b4828948868eee301`.
The local APK and installed emulator APK were both rehashed to this value during
handover. The package verifier records all 20 internal routes, 88 native
libraries, one-app checks, phase checks, strict 16 KiB ELF alignment, zip alignment
and signature verification passing. These are packaging checks, not gameplay.

Compared with the immediately preceding `2d4e2c1e7f2cd21c9143ba02014bf6232f0d01123d1f7d7ff9d28bb66d404e5f`
APK, only `classes2.dex` changed; all 88 native libraries are identical.
Both are currently pinned in `unified-android/build-retention.json`. Older pins
also serve retained test fixtures; inspect their reasons before retirement.

### Latest first run repair

Source: `unified-android/src/com/thorium/preview/LucentApplication.java`,
`installFirstSetupFocusListener`, registered from `onActivityCreated`.
Regression: `tools/tests/test_first_install_startup.py`.

On the first clean install, ROM discovery succeeded while Android's fullscreen
prompt held focus. The pending frontend restart exhausted 150 polls at 100 ms.
Dismissing the prompt did not necessarily produce another activity resume, so
the app stayed on the stock Android-app grid despite having discovered games.
The repair retries the pending restart when the resumed frontend regains window
focus, while retaining the active-game and lifecycle guards.

The actual-method Java regression reproduces the old failure and passes with
the new listener, including duplicate-focus and guard cases. An empty Android
user profile on `21a4` automatically completed setup and displayed its PS2 game.
That new profile did **not** reproduce the same delayed fullscreen prompt;
therefore the exact delayed-prompt recovery is host-regression verified, while
the new-profile test proves the general setup path and library result.

Important misleading comment: line approximately 303 says the legal notice can
hold focus like a dialog. The legal notice is actually an in-window overlay,
not the separate Android fullscreen prompt. Correct this comment when next
editing the file, but do not rebuild solely for the wording or claim it changes
behavior. The current APK was built before any such comment correction.

Evidence in `qa/android-portability-2026-10-07-clean-phone/`:

- `setup-complete.png`: old first-run stock grid after successful discovery.
- `library-after-restart.png`: old build discovers 13 titles after manual relaunch.
- `fresh-user-before-launch.json`: user 10 initially had no private app files.
- `upgraded.json`: exact `21a4` update preserved UID, original install time and
  all 52 checked existing private/frontend files.
- `runtime-r2.log`: user 10 discovery at 13:37:52, automatic clean restart at
  13:37:54, new frontend process at 13:37:55.
- `fresh10-ready.png` and `ps2-library-game.png`: the new-profile library.
- `handover-stop.png`: fresh 14:11 landscape observation of that same library.

No game was launched on this latest fresh-profile candidate before handover.
The next action was to tap the visible Capcom vs. SNK 2 card, not investigate
another engine or produce another APK first.

### Preceding PS3 repair already included

`2d4e` integrated `engines/patches/aps3e-input-lifetime.patch` and updated
`engines/aps3e-source-lock.json`. It changed only the PS3 native library relative
to the preceding `155` candidate; 87 other natives and Java were unchanged.

The repair synchronizes native pad-handler publication, use and retirement,
retains the handler while dispatching a key, and uses exception-safe locking.
Actual-method failures were reproduced and eight corrected scenarios passed on
host and Android, including live key traffic across 1,000 lifetimes. Bounded
Shadow gameplay, movement, pause/resume and normal exit passed in the diagnostic
trial. This does not repair ICO's separate freeze or qualify every pad-thread mode.

Packaged native SHA-256:
`e9eccc214e3f9a055eec4ba195a87f515b2bdcd21d6d11e11585ec83dce192e0`.
Evidence: `qa/android-portability-2026-10-07-ps3-input-lifetime/verified.json`,
`staged.json`, `normal-package-result.json` and `runtime-finished.json`.
The closed diagnostic APK was retired; its recipes, symbols and evidence remain.
Do not rerun a historical verifier that requires that removed APK without
deliberately reconstructing its inputs.

## Historical per system results

These are prior bounded results on different identified APKs and profiles,
summarized from the matrix. **None is a gameplay pass on the latest fresh `21a4`
profile.** No row establishes every game or every Android device works.

| Route | Representative owned title | Existing result and remaining gap |
| --- | --- | --- |
| switch | Mega Man 11 | Internal menus and opening story; stage gameplay unverified. Software rendering is very slow. Owned input currently unavailable in the retained clean fixture. |
| wiiu | Barbie Dreamhouse Party | Internal lobby, movement, TV/GamePad selection, touch, pause and exits verified. Audio, sustained performance and latest fresh-profile run remain open. |
| ps3 | ICO and Shadow of the Colossus collection | Shadow has bounded movement/resume/exit passes. ICO stalls with a semaphore timeout. Intermittent Shadow loading and rendering quality remain unqualified. |
| wii | New Super Mario Bros. Wii | Normal library boot, World 1-1 movement/jump and exits verified. Audio/speed fail or remain unqualified. |
| gc | Mario Kart Double Dash | Race, acceleration, restore and exits verified historically. Severe simulator performance/audio problems and prior rendering defects remain. |
| ps2 | Capcom vs. SNK 2 | Training movement/attack and exits verified on older 4 KiB and 16 KiB builds. Audio/performance remain unaccepted. Latest clean profile is ready to launch it. |
| psp | Castlevania Dracula X Chronicles | Stage 0 whip, restore and exits verified; bounded counter improvement. No broad smoothness or listening acceptance. |
| psx | Tekken 2 | Fight, jump, restore and exits verified. Owned filename is misleadingly `Tekken (USA).chd`. Performance not fully accepted. |
| dreamcast | Sonic Adventure | Running, jump, resume and exits verified. Current source fixture has an incomplete GDI set; obtain the complete retained copy before testing. |
| n3ds | Star Fox 64 3D | Training, touch/steering/laser and restore/exits verified. Audio and sustained performance incomplete. |
| nds | Castlevania Dawn of Sorrow; Metroid demo | Stylus/gameplay and restore/exits verified historically. Presentation remains incomplete; check top/bottom mapping on a phone. |
| n64 | Super Mario 64; F-Zero X | Movement/jump/camera/crouch and F-Zero acceleration verified. C-arrow routing repaired. Audio and final geometry/presentation acceptance remain open. |
| snes | Super Mario World | Bounded movement/jump, restore and exits verified. No universal judder-free or listening pass. |
| nes | Super Mario Bros. 2 | Bounded gameplay/restore/exits verified; filename lacks the `2`. Lowest priority for further frame-generation work. |
| gb | Super Mario Land | Gameplay, fresh-process resume and exits verified; performance unqualified. |
| gbc | Super Mario Bros. Deluxe | Gameplay, fresh-process resume and exits verified; underruns/presentation counters prevent a smoothness claim. |
| gba | Metroid Fusion | Movement/jump, resume and exits verified; sampled audio counters clean, presentation misses remain. |
| megadrive | Sonic the Hedgehog 2 | Gameplay, fresh-process resume and exits verified; filename lacks the `2`. |
| gamegear | Sonic the Hedgehog | Gameplay, fresh-process resume and exits verified; performance unqualified. |
| pcenginecd | Castlevania Rondo of Blood | Internal route, setup and missing-BIOS negative control verified. Owned disc and System Card input unavailable; no gameplay test. |

Consult the particular system's matrix entry for the exact APK, source patch,
screenshots and limitations. Do not reclassify performance failures as hardware
limitations without comparative evidence. Do not require the Thor for independent
source, packaging or simulator work.

## Simulator and input state at handover

The only running AVD was `emufusion_clean_phone_20261007`, serial
`emulator-5578`, Android 16 ARM64 with 16 KiB pages, host GPU, four cores,
4 GB RAM, 1280 by 720 landscape. It was headless and offline. No physical Thor
was connected or accessed. No subagents were active.

At 14:12 EDT, after observing the library and rechecking the APK hash, EmuFusion
was stopped for users 10 and 0, storage was synced, and the AVD was shut down.
Emulator exit code was 0; both log readers returned 255 because the device
disconnected. `adb devices -l` was empty and the owned emulator/log processes
were absent. No ROM, app data, save, AVD or source was deleted in this handover.
The AVD remains reusable at:
`/Users/tyleryoung/.android/avd/emufusion_clean_phone_20261007.avd`.

Closure receipts: `emulator-exit-r1.json`, `reader-exit-r1.json`,
`reader-exit-r2.json`, and `handover-closure.json` in the clean-phone QA folder.
The earlier `emulator-exit.json` with code -6 belongs to the first failed boot,
not the successful handover shutdown. Its cause was not established.

The AVD retains two Android users:

- User 0: original clean install, 13 games across 12 systems. Public ROM folders
  are `wiiu`, `ps2`, `wii`, `nds`, `n64` (two games), `gba`, `snes`, `nes`, `gb`,
  `gbc`, `megadrive`, `gamegear`. PS2 BIOS and owned Wii U keys were copied with
  full hash checks. No private emulator configuration was copied from the Thor.
- User 10: second empty app profile, only Capcom vs. SNK 2 and its BIOS in public
  storage. Actual storage permission granted; setup completed; notification
  permission denied; legal notice confirmed. Only EmuFusion is installed as a
  third-party app in this profile. Current Android user remains 10.

Installation times were 13:11:04 for user 0 and 13:34:29 for user 10 on October 7.
The original base app UID is 10213; user 10 has Android's derived per-user UID.
Use `upgraded.json` and current package inspection rather than assuming identity.

Other retained fixtures, all stopped by this task before handover:

- `emufusion_portability_large_api36_20261002`, normally port 5586, 4 KiB:
  public source of the 12 copied systems, original `f394` package preserved.
- `emufusion_portable_fresh16k_20261004`, normally port 5582:
  earlier multi-system fixture; inspect its latest closure receipts before reuse.
- Separate PS3 fixture, normally port 5584: latest closure is
  `qa/android-portability-2026-10-07-ps3-input-lifetime/runtime-finished.json`;
  exact `595` baseline and protected files preserved.

Do not assume historical Mac ROM paths still exist. Most files under
`/tmp/emufusion-portability-ZNxIhL/ROMs` were removed before the latest work.
Input receipts in the clean-phone folder have exact public paths and hashes.
Switch and PC Engine CD input gaps do not block testing the other systems.

## ADB restart and immediate next test

Read the Android skill before controlling a device:
`/Users/tyleryoung/.codex/skills/android-device-control/SKILL.md`.
Use explicit serials for every device operation. Do not bring a simulator,
Android Studio, or other window over the owner's Mac desktop.

From the repository, first inspect `adb devices -l` and confirm port 5578 is free.
Start the retained AVD in a long-running execution session:

```sh
python3 docs/qa/android-portability-2026-10-07-clean-phone/fixture.py emulator handover2
```

Use a new suffix if that log already exists. Wait for `sys.boot_completed=1`,
confirm the AVD name, installed APK hash, current user and orientation. Helpers
write exclusive evidence files; do not rerun `create`, `prepare`, `install`,
`copy`, `fresh_profile.py create`, or `upgrade.py` blindly. In particular,
`fixture.py` still binds its install candidate to the **older `2d4e` receipt**.
Its emulator, capture and log commands do not install that candidate.

ADB executable:
`/Users/tyleryoung/.codex/tools/android-platform-tools/adb`.
The launcher is **not** `com.thorium.preview/.MainActivity`. For retained user 10:

```sh
/Users/tyleryoung/.codex/tools/android-platform-tools/adb -s emulator-5578 shell settings --user 10 put system accelerometer_rotation 0
/Users/tyleryoung/.codex/tools/android-platform-tools/adb -s emulator-5578 shell settings --user 10 put system user_rotation 1
/Users/tyleryoung/.codex/tools/android-platform-tools/adb -s emulator-5578 shell wm user-rotation lock 1
/Users/tyleryoung/.codex/tools/android-platform-tools/adb -s emulator-5578 shell am start -W --user 10 -n com.thorium.preview/org.pegasus_frontend.android.MainActivity
python3 docs/qa/android-portability-2026-10-07-clean-phone/fixture.py log handover2
```

Run the log command in its own ongoing session. User switching is asynchronous;
verify the current user before applying settings or launching. Reobserve the UI
after boot; do not blindly reuse screenshot coordinates. Capture with a unique
label using `fixture.py capture LABEL`, then inspect the PNG and XML.

The intended next sequence is:

1. On current user 10, tap Capcom vs. SNK 2 in the **normal library**. Verify
   internal boot, enter Training, demonstrate movement and an attack, then normal
   exit and library return. Verify new-game save/card behavior without replacing
   existing saves. Record the exact installed APK and loaded core.
2. After normal exit, switch to user 0, verify landscape, and test Barbie Wii U
   from the library using public owned-key import. Check movement, pause/resume
   and exit, then proceed through the remaining available systems.
3. Recover missing test games from retained fixtures or owner-authorized Thor
   access only as needed. Keep actual missing inputs as row-specific blockers.
4. Fix a reproducible common launch defect before tuning per-title performance.
   Repeat affected checks and the real library route; reuse the APK if unchanged.
5. Produce one coherent current-build matrix. Only then prepare the signed
   update and test preserving upgrades from the actual existing release.

Do not restart the prolonged ICO/SPURS investigation as the first task. It is a
real unresolved failure, but it already consumed disproportionate time. Do not
repeat interpreter switches, generic fences, arbitrary sleeps, forced signals
or old mask arithmetic experiments without new evidence; the matrix records
why those attempts did not establish a fix.

## Build and focused verification

The latest APK is already built. Do not rebuild merely to resume runtime testing.
The complete entry point is `unified-android/build-portable.sh`; reduced
diagnostic builds must not be mistaken for the full deliverable.

Latest recipe and receipts:
`qa/android-portability-2026-10-07-ps3-input-lifetime/build.py`, its `retry-1/`
directory, and `verify_normal.py`. The wrapper calls the Wii U phone-screen
wrapper, which calls the October 6 normal-candidate recipe. Read these before
running them: they preserve explicit, receipt-checked PS2 qualification inputs
under `qa/android-portability-2026-10-06-normal-candidate/ps2-inputs` rather than
silently promoting old PS2 staging. They also reuse the LSFG wrapper cache,
require strict 16 KiB alignment, build debug, and keep the Mac process headless.
Use a fresh retry suffix and compare source/staging receipts after any rebuild.

Relevant previously passed suites include first-install startup (4 tests),
startup/storage/internal-routing/game-router (19 combined), PS3 packaging plus
input-lifetime (20), and game-router/one-app/streamed-install (50). These overlap;
do not add them into an invented total. One optional real-APK test in another
suite was skipped, while separate actual-APK package verification passed.
No test suite was rerun merely to create this handover.

Example focused checks after editing the startup/routing code:

```sh
python3 -m unittest tools.tests.test_first_install_startup tools.tests.test_frontend_first_run_storage tools.tests.test_portable_internal_routing tools.tests.test_game_launch_router
```

Use the recipe's Java/runtime environment if the default local environment is
missing required dependencies. Keep expected-failure controls and actual-method
tests; don't replace them with string-only assertions to obtain green results.

## Installation privacy and disk safeguards

- Never uninstall or clear EmuFusion data to make a test pass. Never use an
  implicit or explicit incremental install. Use `install --no-incremental -r`
  and verify package path, exact APK hash, UID and first-install times before
  and after. If Android removes the package, stop and preserve evidence.
- Keep Thor OLED panels off except during bounded direct testing; verify both
  physical displays off and brightness 0/0 afterward. The Thor was absent at
  handover. The owner's private phone will not be connected here.
- Preserve native aspect ratio, fit inside the screen, and test only landscape.
  Do not hide frame-generation effects inside the Off mode or weaken unrelated
  screen, input, save, or internal-default behavior.
- Public update publication was previously requested, but this versionCode 90
  debug artifact is not an accepted release. Check signing continuity, a higher
  versionCode, updater compatibility and preserved data before release. No new
  OTA was published during this work.
- Diagnostics must be private and contain no personal information or device
  identifiers. Existing opt-in transport work is recorded under
  `qa/android-portability-2026-10-06-private-diagnostics/` and
  `qa/android-portability-2026-10-06-android-private-https/`. Production endpoint
  is unconfigured; no actual remote-device reports were collected. Do not add
  unrelated cybersecurity projects or public raw-log uploads.
- Approximately 67 GiB was free at handover. Read the build-retention safeguards
  in `AGENTS.md`. Retire exact completed diagnostic APKs through the existing
  hash-checked policy and remove reproducible scratch after builds. Preserve
  source, ROMs, saves, keys, active artifacts and recoverable symbols. The latest
  prior cleanup reclaimed approximately 0.39 GiB from the closed PS3 diagnostic;
  no broad deletion was performed for this handover.

## Prompt for the replacement agent

> Work in /Users/tyleryoung/Code/emufusion. Read AGENTS.md and
> docs/HANDOVER-2026-10-07-ANDROID-PORTABILITY.md first. Take over the unfinished
> EmuFusion clean-phone portability goal. Preserve all existing edits. Start by
> reusing the retained headless landscape Android 16 simulator and the verified
> 21a4 complete APK, then launch Capcom vs. SNK 2 through the normal library.
> Finish the per-system internal tap-to-play checks and fix reproducible failures.
> Do not restart frame-generation work or prolonged PS3 investigations before
> completing that survey. Keep honest current-build evidence, preserve saves,
> avoid taking over my Mac screen, keep Thor OLEDs off when not testing, and clean
> obsolete build output as you go. Do not call packaging checks gameplay passes.
