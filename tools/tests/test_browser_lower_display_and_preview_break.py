"""Lucent's in-app browser lives on the Thor's lower display.

Three behaviours are pinned here, all of them reported from the device:

1. the browser opens on the physical secondary display when the device has
   one, on the main display when it does not, and yields the lower display to
   a dual-screen (DS/3DS/Wii U) session that is already rendering there;
2. video previews take a "break" while the browser is open — they stop, and
   the selection the user is on resumes when the browser closes — without the
   750 ms preview watchdog or the Pegasus heartbeat resurrecting a player
   underneath the browser;
3. a download started in the browser keeps running after the browser closes,
   because it belongs to Android's DownloadManager from enqueue onward.
"""

import re
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPANION = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview"
BROWSER = COMPANION / "BrowserActivity.java"
PREVIEW_ACTIVITY = COMPANION / "PreviewActivity.java"
PREVIEW_SERVICE = COMPANION / "PreviewService.java"
ROUTER = COMPANION / "SecondaryGameplaySurfaceRouter.java"
MANIFEST = ROOT / "android-companion" / "AndroidManifest.xml"
BUILD = ROOT / "unified-android" / "build.sh"
ANDROID = "http://schemas.android.com/apk/res/android"


def body(source: str, start: str, end: str) -> str:
    """The text between two anchors, so a test reads one method, not a file."""
    assert start in source, f"missing anchor {start!r}"
    remainder = source.split(start, 1)[1]
    assert end in remainder, f"missing anchor {end!r} after {start!r}"
    return remainder.split(end, 1)[0]


def code(source: str) -> str:
    """The source without comments.

    Every "this call must not appear" assertion below runs on this, because
    the comments deliberately name the forbidden calls (manager.remove(id),
    the request codes owned by other components) to explain why they are
    forbidden — and a prose mention must not fail the test that bans them.
    """
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", " ", source, flags=re.S))


class BrowserDisplayRoutingTest(unittest.TestCase):
    """Requirement 1: the browser window belongs on the bottom screen."""

    @classmethod
    def setUpClass(cls):
        cls.browser = BROWSER.read_text(encoding="utf-8")
        cls.service = PREVIEW_SERVICE.read_text(encoding="utf-8")
        cls.preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")

    def test_secondary_display_is_resolved_the_same_way_gameplay_resolves_it(self):
        # One resolver for every cross-display launch in the app. A second
        # opinion about which display is "the lower one" is how the preview
        # and the browser end up on different screens.
        target = body(self.browser, "static int targetDisplayId(Context context)",
                      "@Override public void onCreate")
        self.assertIn("BootReceiver.secondaryDisplayId(context)", target)
        self.assertIn("return secondary;", target)
        router = ROUTER.read_text(encoding="utf-8")
        self.assertIn("BootReceiver.secondaryDisplayId(context)", router)

    def test_browser_launches_on_the_secondary_display_when_one_exists(self):
        opener = body(self.browser, "static int open(Context context, String requestedUrl)",
                      "/** The lower display whenever")
        self.assertIn("int displayId = targetDisplayId(context);", opener)
        self.assertIn("options.setLaunchDisplayId(displayId);", opener)
        self.assertIn("context.startActivity(browser, options.toBundle());", opener)
        self.assertIn("return displayId;", opener)
        # Launched from a background Service, so it needs the same
        # background-activity-start handling as the preview surface.
        self.assertIn("ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED", opener)
        self.assertIn("setPendingIntentCreatorBackgroundActivityStartMode", opener)
        self.assertIn("setPendingIntentBackgroundActivityStartMode", opener)
        self.assertIn("Settings.canDrawOverlays(context)", opener)
        self.assertIn("PendingIntent.getActivity(", opener)
        self.assertIn("FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE", opener)

    def test_single_screen_devices_keep_the_main_display_launch(self):
        target = body(self.browser, "static int targetDisplayId(Context context)",
                      "@Override public void onCreate")
        self.assertIn("if (secondary < 0) {", target)
        self.assertIn("reason=no-secondary-display", target)
        opener = body(self.browser, "static int open(Context context, String requestedUrl)",
                      "/** The lower display whenever")
        # No ActivityOptions at all on the default-display path: passing a
        # launch display id of 0 is not the same thing as not asking.
        default_path = body(opener, "if (displayId < 0) {", "ActivityOptions options")
        self.assertIn("context.startActivity(browser);", default_path)
        self.assertNotIn("setLaunchDisplayId", default_path)
        self.assertIn("return Display.DEFAULT_DISPLAY;", default_path)

    def test_dual_screen_gameplay_keeps_the_browser_off_the_lower_display(self):
        # A DS/3DS/Wii U session owns PreviewActivity's SurfaceView on the
        # lower display. Opening over it stops that Activity and destroys the
        # gameplay Surface, so the browser yields to the main display instead.
        target = body(self.browser, "static int targetDisplayId(Context context)",
                      "@Override public void onCreate")
        self.assertIn("PreviewActivity.isGameplaySurfaceActive()", target)
        gameplay_branch = body(target, "if (PreviewActivity.isGameplaySurfaceActive()) {",
                               "return -1;")
        self.assertIn("reason=dual-screen-gameplay-owns-display-", gameplay_branch)
        # The exception must be evaluated before the display is returned.
        self.assertLess(target.index("isGameplaySurfaceActive"),
                        target.index("return secondary;"))

    def test_preview_activity_publishes_a_truthful_gameplay_surface_flag(self):
        self.assertIn("private static volatile boolean gameplaySurfaceActive;", self.preview)
        self.assertIn("static boolean isGameplaySurfaceActive() {", self.preview)
        self.assertIn("return running && gameplaySurfaceActive;", self.preview)
        show = body(self.preview, "private void showGameplaySurface(long generation)",
                    "private void leaveGameplaySurface")
        self.assertIn("gameplaySurfaceActive = true;", show)
        leave = body(self.preview, "private void leaveGameplaySurface(boolean restorePreviewViews)",
                     "private static String safe(String value)")
        self.assertIn("gameplaySurfaceActive = false;", leave)
        # Only an instance that actually held the Surface may clear the flag;
        # the primary-display reject path also reaches leaveGameplaySurface.
        self.assertLess(leave.index("SurfaceView existing = gameplaySurface;"),
                        leave.index("gameplaySurfaceActive = false;"))
        self.assertIn("gameplaySurfaceActive = false;",
                      body(self.preview, "if (ownsVisibilityFlags) {", "}"))

    def test_service_opens_the_browser_through_the_display_router(self):
        endpoint = body(self.service, '} else if ("/browser/open".equals(path)) {',
                        '} else if ("/import/initial".equals(path)) {')
        self.assertIn("BrowserActivity.open(this, requestedUrl)", endpoint)
        self.assertIn("BrowserActivity.LAUNCH_FAILED", endpoint)
        # The old bare primary-display launch must be gone.
        self.assertNotIn("new Intent(this, BrowserActivity.class)", endpoint)
        self.assertNotIn("startActivity(browser)", endpoint)
        self.assertNotIn("new Intent(this, BrowserActivity.class)", self.service)

    def test_browser_task_is_separate_so_it_stacks_over_the_preview(self):
        opener = body(self.browser, "static int open(Context context, String requestedUrl)",
                      "/** The lower display whenever")
        self.assertIn("Intent.FLAG_ACTIVITY_NEW_TASK", opener)
        self.assertIn("Intent.FLAG_ACTIVITY_REORDER_TO_FRONT", opener)
        # A distinct PendingIntent request code: 43821 is the preview service's
        # and 43822 the secondary gameplay router's. Sharing one would let
        # FLAG_UPDATE_CURRENT rewrite another component's pending launch.
        self.assertIn("PENDING_INTENT_REQUEST = 43823", self.browser)
        self.assertNotIn("43821", code(self.browser))
        self.assertNotIn("43822", code(self.browser))


class BrowserManifestTest(unittest.TestCase):
    """The browser must be a private, recents-free, own-task window."""

    @classmethod
    def setUpClass(cls):
        cls.tree = ElementTree.parse(MANIFEST)
        cls.build = BUILD.read_text(encoding="utf-8")

    def browser_element(self):
        for activity in self.tree.getroot().iter("activity"):
            if activity.get(f"{{{ANDROID}}}name") == ".BrowserActivity":
                return activity
        self.fail("android-companion manifest declares no BrowserActivity")

    def packaged_declaration(self) -> str:
        for line in self.build.splitlines():
            if 'android:name="com.thorium.preview.BrowserActivity"' in line:
                return line
        self.fail("unified-android/build.sh no longer declares BrowserActivity")

    def test_companion_manifest_pins_the_browser_window_attributes(self):
        activity = self.browser_element()
        self.assertEqual("false", activity.get(f"{{{ANDROID}}}exported"))
        self.assertEqual("true", activity.get(f"{{{ANDROID}}}excludeFromRecents"))
        self.assertEqual("com.thorium.preview.browser",
                         activity.get(f"{{{ANDROID}}}taskAffinity"))
        self.assertEqual("singleTask", activity.get(f"{{{ANDROID}}}launchMode"))
        self.assertEqual("true", activity.get(f"{{{ANDROID}}}resizeableActivity"))
        # Moving between displays changes the density; without it the WebView
        # is recreated on every hop.
        self.assertIn("density", activity.get(f"{{{ANDROID}}}configChanges"))

    def test_browser_is_never_a_second_launcher_or_an_exported_surface(self):
        # verify_one_app_apk.py enforces the same two properties on the built
        # APK. Breaking either here breaks that release gate.
        activity = self.browser_element()
        self.assertEqual("false", activity.get(f"{{{ANDROID}}}exported"))
        categories = [category.get(f"{{{ANDROID}}}name")
                      for category in activity.iter("category")]
        self.assertNotIn("android.intent.category.LAUNCHER", categories)
        self.assertNotIn("android.intent.category.HOME", categories)
        packaged = self.packaged_declaration()
        self.assertIn('android:exported="false"', packaged)
        self.assertNotIn("android.intent.category.LAUNCHER", packaged)

    def test_the_packaged_manifest_matches_the_companion_manifest(self):
        # The APK's manifest is generated by build.sh, not read from
        # android-companion/AndroidManifest.xml, so the two have to agree or
        # the shipped browser silently keeps the old task behaviour.
        packaged = self.packaged_declaration()
        activity = self.browser_element()
        for attribute in ("excludeFromRecents", "launchMode", "taskAffinity",
                          "resizeableActivity", "exported", "configChanges"):
            expected = activity.get(f"{{{ANDROID}}}{attribute}")
            self.assertIsNotNone(
                expected, f"companion manifest lost android:{attribute}")
            self.assertIn(f'android:{attribute}="{expected}"', packaged,
                          f"build.sh disagrees about android:{attribute}")

    def test_the_preview_surface_keeps_its_own_task_affinity(self):
        # The browser gets a different affinity on purpose: same affinity
        # would replace the preview surface in its task instead of stacking
        # over it, and the lower display would be handed to the launcher when
        # the browser closed.
        affinities = {
            activity.get(f"{{{ANDROID}}}name"):
                activity.get(f"{{{ANDROID}}}taskAffinity")
            for activity in self.tree.getroot().iter("activity")
        }
        self.assertEqual("com.thorium.preview.preview", affinities[".PreviewActivity"])
        self.assertNotEqual(affinities[".PreviewActivity"], affinities[".BrowserActivity"])


class PreviewBreakTest(unittest.TestCase):
    """Requirement 2: previews stop while browsing and resume on exit."""

    @classmethod
    def setUpClass(cls):
        cls.service = PREVIEW_SERVICE.read_text(encoding="utf-8")
        cls.preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")
        cls.browser = BROWSER.read_text(encoding="utf-8")

    def test_opening_the_browser_starts_the_break(self):
        endpoint = body(self.service, '} else if ("/browser/open".equals(path)) {',
                        '} else if ("/import/initial".equals(path)) {')
        # Break first, window second: a movie must never be audible under the
        # browser, not even for the length of an Activity launch.
        self.assertLess(endpoint.index("beginBrowserBreak();"),
                        endpoint.index("BrowserActivity.open(this, requestedUrl)"))
        begin = body(self.service, "private synchronized void beginBrowserBreak() {",
                     "/** Ends the break")
        self.assertIn("browserActive = true;", begin)
        self.assertIn("resumePreviewAfterBrowser = previewActive;", begin)
        self.assertIn("previewActive = false;", begin)
        self.assertIn("sendBroadcast(new Intent(ACTION_PAUSE)", begin)

    def test_a_refused_browser_window_never_leaves_previews_stopped(self):
        endpoint = body(self.service, '} else if ("/browser/open".equals(path)) {',
                        '} else if ("/import/initial".equals(path)) {')
        self.assertIn("if (!opened) endBrowserBreak();", endpoint)

    def test_the_watchdog_cannot_resurrect_a_player_mid_break(self):
        # The 750 ms watchdog re-shows the last player whenever the lower
        # display is not visible — which is exactly what the browser causes.
        begin = body(self.service, "private synchronized void beginBrowserBreak() {",
                     "/** Ends the break")
        self.assertIn("mainHandler.removeCallbacks(pegasusWatchdog);", begin)
        watchdog = body(self.service, "private final Runnable pegasusWatchdog",
                        "private ServerSocket server;")
        # Removing the callback alone loses a run already queued on the main
        # looper; previewActive false makes that run a no-op too.
        self.assertIn("if (!previewActive) return;", watchdog)
        self.assertLess(begin.index("previewActive = false;"),
                        begin.index("sendBroadcast(new Intent(ACTION_PAUSE)"))

    def test_the_heartbeat_cannot_resurrect_a_player_mid_break(self):
        heartbeat = body(self.service, '} else if ("/heartbeat".equals(path)) {',
                         '} else if ("/hide".equals(path)) {')
        guard = body(heartbeat, "if (browserActive) {", "if (placementBlank) {")
        self.assertIn("respond(writer", guard)
        self.assertIn("return;", guard)
        # The guard has to precede both resurrection paths.
        self.assertLess(heartbeat.index("if (browserActive)"),
                        heartbeat.index("showLastPlayer()"))

    def test_navigation_during_a_break_is_recorded_but_never_shown(self):
        # Pegasus stays usable on the upper display while the browser is on
        # the lower one, so the resume must land on the newest selection.
        play = body(self.service, 'if ("/play".equals(path)) {',
                    '} else if ("/launch/status".equals(path)) {')
        guard = body(play, "if (browserActive) {", "previewActive = true;")
        self.assertIn("resumePreviewAfterBrowser = true;", guard)
        self.assertIn("return;", guard)
        # The selection is persisted before the guard returns, and no decoder
        # is started after it.
        self.assertLess(play.index(".putLong(EXTRA_SEQUENCE, sequence)"),
                        play.index("if (browserActive) {"))
        self.assertLess(play.index("if (browserActive) {"), play.index("showPlayer("))
        transition = body(self.service, '} else if ("/transition".equals(path)) {',
                          '} else if ("/capabilities".equals(path)) {')
        self.assertIn("resumePreviewAfterBrowser = true;",
                      body(transition, "if (browserActive) {", "previewActive = true;"))
        self.assertLess(transition.index("if (browserActive) {"),
                        transition.index("previewActive = true;"))

    def test_closing_the_browser_resumes_the_previous_selection(self):
        end = body(self.service, "private synchronized void endBrowserBreak() {",
                   "private void reloadLucentFrontend()")
        self.assertIn("browserActive = false;", end)
        self.assertIn("sendBroadcast(new Intent(ACTION_RESUME)", end)
        self.assertIn("showLastPlayer();", end)
        self.assertIn("mainHandler.postDelayed(pegasusWatchdog, 750L);", end)
        # Unpause reaches the decoders before the new selection does.
        self.assertLess(end.index("sendBroadcast(new Intent(ACTION_RESUME)"),
                        end.index("showLastPlayer();"))
        # A game or an explicit blank that happened during the break wins.
        self.assertIn(
            "boolean resume = resumePreviewAfterBrowser && !gameplayActive && !placementBlank;",
            end)

    def test_closing_the_browser_never_exposes_the_android_launcher(self):
        end = body(self.service, "private synchronized void endBrowserBreak() {",
                   "private void reloadLucentFrontend()")
        fallback = body(end, "} else if (!PreviewActivity.isGameplaySurfaceActive()) {",
                        "Log.i(BROWSER_TAG")
        self.assertIn("launchPlayerOnSecondary(", fallback)
        self.assertIn("setAction(ACTION_BLANK)", fallback)
        # ...except when a dual-screen game already owns that display.
        self.assertIn("!PreviewActivity.isGameplaySurfaceActive()", end)

    def test_a_game_or_a_blank_during_the_break_cancels_the_resume(self):
        for anchor, terminator in (
                ("if (intent != null && ACTION_GAMEPLAY.equals(intent.getAction())) {",
                 "} else if (intent != null && ACTION_LIBRARY"),
                ('} else if ("/hide".equals(path)) {', '} else if ("/transition"'),
                ('} else if ("/blank".equals(path)) {', '} else if ("/import/scan"'),
                ("} else if (intent != null && ACTION_SUSPEND.equals(intent.getAction())) {",
                 "} else if (intent != null && ACTION_LAUNCH")):
            self.assertIn("resumePreviewAfterBrowser = false;",
                          body(self.service, anchor, terminator),
                          f"{anchor} does not cancel the pending browser resume")

    def test_the_browser_reports_its_own_lifecycle_to_the_service(self):
        # A broadcast, not startService: onDestroy can run after the process
        # has left the foreground, where a background service start is refused.
        start = body(self.browser, "@Override protected void onStart() {",
                     "@Override protected void onNewIntent")
        self.assertIn("notifyPreviewService(PreviewService.ACTION_BROWSER_OPENED);", start)
        destroy = body(self.browser, "@Override protected void onDestroy() {",
                       "private void notifyPreviewService(String action) {")
        self.assertIn("if (!isChangingConfigurations())", destroy)
        self.assertIn("notifyPreviewService(PreviewService.ACTION_BROWSER_CLOSED);", destroy)
        notify = body(self.browser, "private void notifyPreviewService(String action) {",
                      "private int dp(int value)")
        self.assertIn("sendBroadcast(new Intent(action).setPackage(getPackageName()));", notify)
        self.assertNotIn("startService(", notify)
        # ...and the service listens for exactly those two.
        self.assertIn("ACTION_BROWSER_OPENED.equals(intent.getAction())) beginBrowserBreak();",
                      self.service)
        self.assertIn("ACTION_BROWSER_CLOSED.equals(intent.getAction())) endBrowserBreak();",
                      self.service)
        self.assertIn("registerReceiver(browserReceiver, browserFilter);", self.service)
        self.assertIn("if (browserReceiverRegistered) unregisterReceiver(browserReceiver);",
                      self.service)

    def test_the_lower_display_pauses_instead_of_tearing_players_down(self):
        # Releasing would drop the decoded frame (black lower screen) and make
        # the return a cold prepareAsync. Pausing keeps the frame and resumes
        # with one start().
        self.assertIn("PreviewService.ACTION_PAUSE.equals(intent.getAction())", self.preview)
        self.assertIn("PreviewService.ACTION_RESUME.equals(intent.getAction())", self.preview)
        self.assertIn("registerReceiver(receiver, new IntentFilter(PreviewService.ACTION_PAUSE));",
                      self.preview)
        self.assertIn("registerReceiver(receiver, new IntentFilter(PreviewService.ACTION_RESUME));",
                      self.preview)
        pause = body(self.preview, "private void pausePlayers() {",
                     "private void resumePlayers() {")
        self.assertIn("playersPaused = true;", pause)
        self.assertIn("for (PlayerSlot slot : slots) slot.pause();", pause)
        self.assertNotIn("stopPlayers()", pause)
        self.assertNotIn("release()", pause)
        self.assertNotIn("blankScreen()", pause)
        self.assertNotIn("setVisibility", pause)
        slot_pause = body(self.preview, "void pause() {", "void resume() {")
        self.assertIn("player.pause();", slot_pause)
        self.assertNotIn("player.release()", slot_pause)

    def test_paused_players_are_silent_and_do_not_start_themselves(self):
        pause = body(self.preview, "private void pausePlayers() {",
                     "private void resumePlayers() {")
        # Mute before pausing: a decoder that refuses pause() must still be
        # inaudible under the browser.
        self.assertLess(pause.index("applyPlayerVolumes();"),
                        pause.index("for (PlayerSlot slot : slots) slot.pause();"))
        volumes = body(self.preview, "private void applyPlayerVolumes() {",
                       "private void blankScreen()")
        self.assertIn(
            "float volume = soundEnabled && !playersPaused && index == activeSlot ? 1f : 0f;",
            volumes)
        prepared = body(self.preview, "player.setOnPreparedListener(", "});")
        self.assertIn("if (!playersPaused) mediaPlayer.start();", prepared)

    def test_resume_starts_the_paused_decoders_again(self):
        resume = body(self.preview, "private void resumePlayers() {",
                      "private void applyPlayerVolumes() {")
        self.assertIn("playersPaused = false;", resume)
        self.assertIn("for (PlayerSlot slot : slots) slot.resume();", resume)
        self.assertLess(resume.index("playersPaused = false;"),
                        resume.index("applyPlayerVolumes();"))
        slot_resume = body(self.preview, "void resume() {", "private void open() {")
        self.assertIn("player.start();", slot_resume)

    def test_a_break_survives_a_preview_activity_rebuild(self):
        # If Android destroys and recreates the lower display window during a
        # break, it must come back silent rather than playing under the
        # browser.
        self.assertIn('EXTRA_BROWSER_ACTIVE = "browser_active"', self.service)
        create = body(self.preview, "protected void onCreate(Bundle savedInstanceState) {",
                      "requestWindowFeature(Window.FEATURE_NO_TITLE);")
        self.assertIn(".getBoolean(PreviewService.EXTRA_BROWSER_ACTIVE, false);", create)
        self.assertIn("playersPaused =", create)
        begin = body(self.service, "private synchronized void beginBrowserBreak() {",
                     "/** Ends the break")
        self.assertIn(".putBoolean(EXTRA_BROWSER_ACTIVE, true)", begin)
        end = body(self.service, "private synchronized void endBrowserBreak() {",
                   "private void reloadLucentFrontend()")
        self.assertIn(".putBoolean(EXTRA_BROWSER_ACTIVE, false)", end)
        # A restarted service is never mid-break: no browser window of ours
        # can already be open.
        self.assertIn(".putBoolean(EXTRA_BROWSER_ACTIVE, false)",
                      body(self.service, "public void onCreate() {",
                           "importManager = new ImportManager(this);"))

    def test_the_break_is_idempotent_from_both_reporters(self):
        # The service arms the break at /browser/open and BrowserActivity
        # re-asserts it in onStart; neither may double-apply.
        begin = body(self.service, "private synchronized void beginBrowserBreak() {",
                     "/** Ends the break")
        self.assertIn("if (browserActive) return;", begin)
        end = body(self.service, "private synchronized void endBrowserBreak() {",
                   "private void reloadLucentFrontend()")
        self.assertIn("if (!browserActive) return;", end)
        pause = body(self.preview, "private void pausePlayers() {",
                     "private void resumePlayers() {")
        self.assertIn("if (playersPaused) return;", pause)
        resume = body(self.preview, "private void resumePlayers() {",
                      "private void applyPlayerVolumes() {")
        self.assertIn("if (!playersPaused) return;", resume)


class BackgroundDownloadSurvivalTest(unittest.TestCase):
    """Requirement 3: a download outlives the browser window."""

    @classmethod
    def setUpClass(cls):
        cls.browser = BROWSER.read_text(encoding="utf-8")
        cls.service = PREVIEW_SERVICE.read_text(encoding="utf-8")

    def test_downloads_are_handed_to_the_system_download_manager(self):
        listener = body(self.browser, "private final class BrowserDownloadListener",
                        "private static boolean sameHost(")
        self.assertIn("DownloadManager.Request request = new DownloadManager.Request(", listener)
        self.assertIn("long downloadId = manager.enqueue(request);", listener)
        self.assertIn("HANDED_OFF_DOWNLOADS.incrementAndGet();", listener)
        # The counter is static, so it is not lost when the Activity dies.
        self.assertIn("private static final AtomicInteger HANDED_OFF_DOWNLOADS", self.browser)

    def test_nothing_in_the_browser_can_cancel_an_enqueued_download(self):
        # DownloadManager.remove(id) is the only way to cancel one, and it
        # must never appear here. This is the pin for "downloads continue in
        # the background".
        self.assertIsNone(
            re.search(r"\bremove\s*\(", code(self.browser)),
            "BrowserActivity must never call remove() on a DownloadManager request")
        self.assertNotIn("DownloadManager.STATUS_", code(self.browser))

    def test_browser_teardown_only_touches_the_web_view(self):
        destroy = code(body(self.browser, "@Override protected void onDestroy() {",
                            "private void notifyPreviewService(String action) {"))
        self.assertIn("webView.stopLoading();", destroy)
        self.assertIn("webView.destroy();", destroy)
        self.assertIsNone(re.search(r"\bremove\s*\(", destroy))
        self.assertNotIn("enqueue", destroy)
        self.assertNotIn("getSystemService", destroy)
        # ...and it says how many transfers it just left running, which is the
        # evidence a device check reads out of logcat.
        self.assertIn("HANDED_OFF_DOWNLOADS.get()", destroy)
        self.assertIn("keep running in the background", destroy)

    def test_a_display_driven_relaunch_cannot_interrupt_a_download(self):
        # Requirement 1 can have Android destroy and recreate this Activity.
        # Nothing download-related is bound to the Activity instance: the
        # request is enqueued and forgotten, and the id lives only in a log.
        self.assertNotIn("private long downloadId", code(self.browser))
        self.assertNotIn("private DownloadManager", code(self.browser))
        listener = body(self.browser, "private final class BrowserDownloadListener",
                        "private static boolean sameHost(")
        self.assertIn("DownloadManager manager = (DownloadManager)", listener)
        self.assertIn("getSystemService(Context.DOWNLOAD_SERVICE);", listener)

    def test_the_preview_service_never_obtains_a_download_handle(self):
        # The service outlives the browser; if it could reach the download
        # queue, its teardown could cancel a transfer.
        self.assertNotIn("DOWNLOAD_SERVICE", code(self.service))
        self.assertNotIn("DownloadManager", code(self.service))


if __name__ == "__main__":
    unittest.main()
