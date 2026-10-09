from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
THEME = (ROOT / "theme" / "theme.qml").read_text(encoding="utf-8")
COMPANION = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview"
ACTIVITY = (COMPANION / "PreviewActivity.java").read_text(encoding="utf-8")
SERVICE = (COMPANION / "PreviewService.java").read_text(encoding="utf-8")


class DualScreenScreensaverTest(unittest.TestCase):
    def test_timeout_is_exactly_two_minutes_and_default_is_on(self):
        self.assertIn("property bool screensaverEnabled: true", THEME)
        self.assertIn("screensaverStillTimeoutMs: 120000", THEME)
        self.assertIn('api.memory.has("lucentScreensaverEnabled")', THEME)
        self.assertIn('Boolean(api.memory.get("lucentScreensaverEnabled")) : true', THEME)
        completed = THEME.split("Component.onCompleted: {", 1)[1]
        self.assertIn('screensaverEnabled = api.memory.has("lucentScreensaverEnabled")',
                      completed)
        sound_setter = THEME.split("function setPreviewSoundEnabled", 1)[1].split(
            "function setScreensaverEnabled", 1)[0]
        self.assertNotIn("screensaverEnabled =", sound_setter)

    def test_settings_exposes_a_persistent_on_off_switch(self):
        self.assertIn('"VIDEO SCREENSAVER"', THEME)
        self.assertIn('if (index === 20) return screensaverEnabled ? "ON" : "OFF"', THEME)
        self.assertIn('api.memory.set("lucentScreensaverEnabled", screensaverEnabled)', THEME)
        self.assertIn("setScreensaverEnabled(!screensaverEnabled)", THEME)

    def test_lower_display_reports_real_surface_frame_progress(self):
        self.assertIn("onSurfaceTextureUpdated(SurfaceTexture surface)", ACTIVITY)
        self.assertIn("lastLowerVisualChangeMs = SystemClock.elapsedRealtime();", ACTIVITY)
        self.assertIn("renderedVideoPositionMs = player.getCurrentPosition();", ACTIVITY)
        self.assertIn("static JSONObject screensaverStatus()", ACTIVITY)
        self.assertIn('result.put("videoAdvancing", advancing)', ACTIVITY)
        self.assertIn('result.put("visualIdleMs", idle)', ACTIVITY)

    def test_status_is_read_only_and_play_is_theme_authorized(self):
        self.assertIn('} else if ("/screensaver/status".equals(path)) {', SERVICE)
        self.assertIn('"/screensaver/play",', SERVICE)
        self.assertGreaterEqual(SERVICE.count('"/screensaver/play",'), 2)
        self.assertIn("PreviewActivity.screensaverStatus()", SERVICE)
        self.assertIn("gameplayActive || browserActive ||", SERVICE)
        self.assertIn("PreviewActivity.isGameplaySurfaceActive()", SERVICE)

    def test_random_nonrepeating_deck_drives_top_player(self):
        self.assertIn("function shuffledScreensaverGames()", THEME)
        picker = THEME.split("function shuffledScreensaverGames()", 1)[1].split(
            "function nextScreensaverGame", 1)[0]
        self.assertIn("api.allGames.count", picker)
        self.assertIn("Math.random() * (remaining + 1)", picker)
        self.assertIn('api.memory.has("lucentScreensaverLastVideo")', picker)
        self.assertIn("videoSource(games[0]) === last", picker)
        self.assertNotIn("payload.videoAdvancing", THEME)
        self.assertNotIn("source = String(payload.video)", THEME)
        self.assertIn("var game = nextScreensaverGame(true)", THEME)
        self.assertIn('encodeURIComponent(source)', THEME)
        self.assertIn('encodeURIComponent(title)', THEME)
        self.assertIn('encodeURIComponent(system)', THEME)
        self.assertIn('encodeURIComponent(score)', THEME)
        self.assertIn('encodeURIComponent(title)', THEME)
        self.assertIn('encodeURIComponent(system)', THEME)
        self.assertIn('encodeURIComponent(score)', THEME)

    def test_completion_crossfades_to_next_random_video(self):
        self.assertIn("id: screensaverVideoA", THEME)
        self.assertIn("id: screensaverVideoB", THEME)
        self.assertGreaterEqual(THEME.count(
            "NumberAnimation { duration: root.screensaverCrossfadeMs }"), 2)
        self.assertIn("function advanceScreensaverVideo()", THEME)
        self.assertGreaterEqual(THEME.count("root.advanceScreensaverVideo()"), 3)
        self.assertIn("onPositionChanged: if (position > 0) "
                      "root.promoteScreensaverSlot(0)", THEME)
        self.assertIn("onPositionChanged: if (position > 0) "
                      "root.promoteScreensaverSlot(1)", THEME)

    def test_completion_watchdog_cannot_hold_the_last_decoded_frame(self):
        self.assertIn("function screensaverPlaybackFinished()", THEME)
        completion = THEME.split("function screensaverPlaybackFinished()", 1)[1]
        completion = completion.split("function beginScreensaver", 1)[0]
        self.assertIn("screensaverRequestPending", completion)
        self.assertIn("screensaverPendingSlot >= 0", completion)
        self.assertIn("player.status === MediaPlayer.EndOfMedia", completion)
        self.assertIn("player.duration > 0", completion)
        self.assertIn("player.position >= player.duration - 250", completion)
        self.assertNotIn("StoppedState", completion)
        self.assertIn("id: screensaverCompletionWatch", THEME)
        watchdog = THEME.split("id: screensaverCompletionWatch", 1)[1]
        watchdog = watchdog.split("Timer {", 1)[0]
        self.assertIn("interval: 500", watchdog)
        self.assertIn("running: root.screensaverActive", watchdog)
        self.assertIn("root.advanceScreensaverVideo()", watchdog)

    def test_metadata_is_visible_but_play_now_is_not(self):
        layer = THEME.split("id: screensaverLayer", 1)[1].split(
            "id: chrome", 1)[0]
        self.assertIn("root.screensaverSystemName(root.screensaverGame)", layer)
        self.assertIn("root.displayTitle(root.screensaverGame)", layer)
        self.assertIn("root.scoreText(root.screensaverGame)", layer)
        self.assertNotIn("PLAY NOW", layer)
        endpoint = SERVICE.split('} else if ("/screensaver/play".equals(path)) {', 1)[1]
        endpoint = endpoint.split('} else if ("/launch/status".equals(path)) {', 1)[0]
        self.assertIn("showScreensaverBlackout();", endpoint)
        self.assertNotIn("showPlayer(", endpoint)

    def test_only_top_display_keeps_aspect_correct_video(self):
        self.assertIn('encodeURIComponent(source)', THEME)
        self.assertGreaterEqual(THEME.count("fillMode: VideoOutput.PreserveAspectCrop"), 2)

    def test_screensaver_blacks_lower_display_without_starting_its_decoder(self):
        endpoint = SERVICE.split('} else if ("/screensaver/play".equals(path)) {', 1)[1]
        endpoint = endpoint.split('} else if ("/launch/status".equals(path)) {', 1)[0]
        self.assertIn("showScreensaverBlackout();", endpoint)
        self.assertIn('"lowerDisplayBlack\\\":true', endpoint)
        self.assertNotIn("showPlayer(", endpoint)
        blackout = SERVICE.split("private void showScreensaverBlackout()", 1)[1]
        blackout = blackout.split("private void launchPlayerOnSecondary", 1)[0]
        self.assertIn("new Intent(ACTION_BLANK)", blackout)
        self.assertIn("sendBroadcast(blank)", blackout)
        self.assertIn("setAction(ACTION_BLANK)", blackout)
        self.assertNotIn("EXTRA_VIDEO", blackout)

    def test_watchdog_and_heartbeat_cannot_resurrect_lower_video(self):
        self.assertGreaterEqual(SERVICE.count(
            "if (screensaverActive) showScreensaverBlackout();"), 1)
        watchdog = SERVICE.split("private final Runnable pegasusWatchdog", 1)[1]
        watchdog = watchdog.split("private final android.content.BroadcastReceiver", 1)[0]
        self.assertIn("showScreensaverBlackout();", watchdog)
        self.assertNotIn("showPlayer(screensaverVideo", watchdog)
        self.assertIn("!placementBlank && !screensaverActive", SERVICE)

    def test_input_dismisses_and_restores_normal_preview_placement(self):
        self.assertIn("if (root.screensaverActive || root.screensaverRequestPending)", THEME)
        self.assertIn("root.stopScreensaver()", THEME)
        self.assertIn("root.refreshCurrentPreview()", THEME)
        self.assertIn("MouseArea {\n            anchors.fill: parent\n"
                      "            onClicked: root.stopScreensaver()", THEME)

    def test_both_panels_must_be_idle_before_screensaver_activation(self):
        begin = THEME.split("function beginScreensaver(payload)", 1)[1].split(
            "function stopScreensaver", 1
        )[0]
        self.assertIn(
            "topStill < screensaverStillTimeoutMs || "
            "lowerStill < screensaverStillTimeoutMs",
            begin,
        )
        self.assertNotIn(
            "topStill < screensaverStillTimeoutMs && "
            "lowerStill < screensaverStillTimeoutMs",
            begin,
        )


if __name__ == "__main__":
    unittest.main()
