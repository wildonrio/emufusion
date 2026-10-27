"""Opening EmuFusion checks for an app update and installs it before anything else.

Owner, 2026-10-27: "when emufusion first opens, it should check for updates to
the app and install, before anything else". The library scan already waited
for the first check of the process (test_update_first_and_restart_prompt);
these tests pin that every open checks, that games wait for the check and a
found update's download, and that a declined install cannot lock the owner out.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
UPDATE = (ROOT / "android-companion/src/com/thorium/preview/UpdateManager.java").read_text()
SERVICE = (ROOT / "android-companion/src/com/thorium/preview/PreviewService.java").read_text()
APPLICATION = (ROOT / "unified-android/src/com/thorium/preview/EmuFusionApplication.java").read_text()
THEME = (ROOT / "theme/theme.qml").read_text()


def function(source, signature):
    body = source.split(signature, 1)[1]
    depth = 0
    for index, char in enumerate(body):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return body[:index + 1]
    raise AssertionError("unbalanced " + signature)


class AppOpenCheckTest(unittest.TestCase):
    def test_frontend_resume_tells_the_updater(self):
        self.assertIn(".setAction(PreviewService.ACTION_APP_OPENED)", APPLICATION)
        self.assertIn("updateManager.onAppOpened();", SERVICE)

    def test_every_open_checks_unless_one_just_finished(self):
        opened = function(UPDATE, "void onAppOpened()")
        self.assertIn("if (gameplayActive()) return;", opened)
        self.assertIn("LAST_CHECK_FINISHED", opened)
        self.assertIn("APP_OPEN_RECHECK_MS) checkAsync(false);", opened)
        self.assertIn("APP_OPEN_RECHECK_MS = 60L * 1000L", UPDATE)
        self.assertNotIn("APP_OPEN_RECHECK_MS = 15L", UPDATE)

    def test_only_a_completed_check_is_reused(self):
        worker = function(UPDATE, "void checkAsync(boolean userInitiated)")
        success = worker.split("check(userInitiated);", 1)[1].split("} catch", 1)[0]
        self.assertIn(".putLong(LAST_CHECK_FINISHED, System.currentTimeMillis())", success)

    def test_declined_install_offers_the_prompt_instead_of_reopening(self):
        install = function(UPDATE, "private void installDownloadedApk(boolean automatic)")
        self.assertIn("AUTO_INSTALLER_REPEAT_MS", install)
        self.assertIn("saved.getLong(AUTO_INSTALLER_CODE, -1L)", install)
        self.assertLess(install.index("AUTO_INSTALLER_REPEAT_MS"),
                        install.index("openInstaller(context)"))
        self.assertIn(".putLong(AUTO_INSTALLER_AT, System.currentTimeMillis())", install)
        self.assertIn("AUTO_INSTALLER_REPEAT_MS = 10L * 60L * 1000L", UPDATE)

    def test_apk_download_reports_progress(self):
        check = function(UPDATE, "private void check(boolean userInitiated)")
        self.assertIn("download(appUrl, apk, MAX_APK, apkSha, (done, total) ->", check)
        self.assertIn('"Downloading " + label + " — " + percent + "%"', check)
        self.assertIn("if (progress != null) progress.update(total, length);", UPDATE)


class LibraryGateTest(unittest.TestCase):
    def test_launch_waits_for_the_update_check(self):
        launch = function(THEME, "function launch(game)")
        self.assertIn("if (updateGateOpen) return", launch)
        self.assertIn("(updateBlocking || !updateStatusKnown)", launch)
        self.assertIn("updatePendingLaunch = game", launch)
        self.assertLess(launch.index("updatePendingLaunch = game"),
                        launch.index("frameGenerationPendingLaunch = game"))

    def test_gate_tracks_checking_and_app_download(self):
        gate = function(THEME, "function applyUpdateGate(payload)")
        self.assertIn('(state === "checking" || state === "software")', gate)
        self.assertIn("Boolean(payload.running)", gate)
        self.assertIn('state === "software" || Date.now() - updateBlockingSince >= 800', gate)
        self.assertIn("releaseUpdatePendingLaunch(state)", gate)

    def test_unreachable_updater_never_holds_a_game(self):
        poll = function(THEME, "function pollUpdateStatus()")
        self.assertIn("root.applyUpdateGate(payload)", poll)
        self.assertNotIn("request.status !== 200)\n                return", poll)

    def test_installer_takeover_drops_the_held_game_only_after_a_seen_check(self):
        release = function(THEME, "function releaseUpdatePendingLaunch(state)")
        self.assertIn("if (updatePromptOpen) return", release)
        self.assertIn('sawCheck && (state === "installing" || state === "permission")', release)
        self.assertIn("launch(game)", release)
        self.assertIn("launchHeldGame()", function(THEME, "function dismissReadyUpdate()"))

    def test_gate_owns_input_and_b_skips(self):
        keys = THEME.split("Keys.onPressed: {", 1)[1]
        self.assertLess(keys.index("if (updateGateOpen) {"),
                        keys.index("} else if (voiceFeedbackOpen) {"))
        gate_keys = keys.split("if (updateGateOpen) {", 1)[1].split("} else if", 1)[0]
        self.assertIn("skipUpdateGate()", gate_keys)
        self.assertIn("event.accepted = true", gate_keys)
        self.assertIn('id: updateGateOverlay', THEME)
        self.assertIn('"GAMES START AFTER THE UPDATE     B  SKIP FOR NOW"', THEME)

    def test_returning_to_the_foreground_polls_at_once(self):
        self.assertIn("if (applicationActive && !root.applicationWasActive) {", THEME)
        resume = THEME.split("if (applicationActive && !root.applicationWasActive) {", 1)[1].split("}", 1)[0]
        self.assertIn("root.updateStatusKnown = false", resume)
        self.assertIn("root.pollUpdateStatus()", resume)
        self.assertIn("interval: root.updateGateOpen || root.updateBlocking || root.updateWatchFast ? 400 : 1800",
                      THEME)


if __name__ == "__main__":
    unittest.main()
