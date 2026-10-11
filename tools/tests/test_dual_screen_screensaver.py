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

    def test_idle_means_no_user_input_not_a_still_lower_video(self):
        # October 10: the looping (and auto-advancing) lower preview redrew
        # every frame, so a frame-based idle clock never reached two minutes
        # and the screensaver could not start on the Thor.
        self.assertIn('result.put("visualIdleMs", Math.max(0L, now - activity.lastLowerInteractionMs));',
                      ACTIVITY)
        for hook in ('public boolean dispatchTouchEvent(', 'public boolean dispatchKeyEvent('):
            body = ACTIVITY.split(hook, 1)[1].split('}', 1)[0]
            self.assertIn('lastLowerInteractionMs = SystemClock.elapsedRealtime();', body)
        frame = ACTIVITY.split('public void onSurfaceTextureUpdated(SurfaceTexture surface)', 1)[1][:600]
        self.assertNotIn('lastLowerInteractionMs', frame)
        # A started lower Activity is available even while the Thor has paused
        # it for top-screen focus.
        self.assertIn('result.put("available", activity != null && running);', ACTIVITY)

    def test_screen_stays_awake_long_enough_for_the_screensaver(self):
        # The Thor and most phones sleep after 30-60 s; the screensaver needs
        # two idle minutes. Polls (only sent while enabled in the library) and
        # an active screensaver hold a bounded screen wake lock.
        self.assertIn('lastScreensaverPollMs = SystemClock.elapsedRealtime();', SERVICE)
        self.assertIn('PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ON_AFTER_RELEASE', SERVICE)
        self.assertIn('SCREENSAVER_START_WINDOW_MS = 150_000L', SERVICE)
        self.assertIn('SCREENSAVER_MAX_AWAKE_MS = 30L * 60L * 1000L', SERVICE)
        update = SERVICE.split('private void updateScreensaverWakeLock() {', 1)[1].split('\n    }\n', 1)[0]
        self.assertIn('!gameplayActive', update)
        self.assertIn('releaseScreensaverWakeLock();', update)
        self.assertEqual(SERVICE.count('screensaverActive = false;'),
                         SERVICE.count('screensaverActive = false;\n                screensaverStateChanged();'))

    def test_single_screen_devices_are_idle_by_top_input_alone(self):
        status = SERVICE.split('} else if ("/screensaver/status".equals(path)) {', 1)[1][:1600]
        self.assertIn('BootReceiver.secondaryDisplayId(this) < 0', status)
        self.assertIn('status.put("available", true);', status)
        self.assertIn('status.put("visualIdleMs", Long.MAX_VALUE / 4);', status)

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
