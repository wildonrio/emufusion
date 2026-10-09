import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" \
    / "LucentApplication.java"
PREVIEW_ACTIVITY = ROOT / "android-companion" / "src" / "com" / "thorium" \
    / "preview" / "PreviewActivity.java"
BROWSER_ACTIVITY = ROOT / "android-companion" / "src" / "com" / "thorium" \
    / "preview" / "BrowserActivity.java"
BOOT_VIDEO = ROOT / "unified-android" / "src" / "com" / "thorium" \
    / "preview" / "BootVideoOverlay.java"
THEME = ROOT / "theme" / "theme.qml"
LIBRETRO_SESSION = ROOT / "unified-android" / "src" / "com" / "thorium" \
    / "preview" / "game" / "LibretroEngineSession.java"
PPSSPP_SESSION = ROOT / "unified-android" / "src" / "com" / "thorium" \
    / "preview" / "game" / "PpssppGlesEngineSession.java"
AUDIO_LOG = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" \
    / "game" / "EngineAudioLog.java"
AUDIO_FOCUS = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" \
    / "game" / "EngineAudioFocus.java"
MENU_SOUNDS = ROOT / "android-companion" / "src" / "com" / "thorium" \
    / "preview" / "MenuSoundPlayer.java"
VOLUME_CONTROLLER = ROOT / "unified-android" / "src" / "com" / "thorium" \
    / "preview" / "AppVolumeController.java"
IN_WINDOW = ROOT / "unified-android" / "src" / "com" / "thorium" \
    / "preview" / "game" / "InWindowGameHost.java"

PHASE3_SESSION = ROOT / "unified-android" / "src" / "com" / "thorium" \
    / "preview" / "game" / "NativeAdapterEngineSession.java"
# Every in-process path that can make a sound. Phase 3 belongs here as much as
# the other two: Switch is the system the volume complaints came from.
ENGINE_SESSIONS = (LIBRETRO_SESSION, PPSSPP_SESSION, PHASE3_SESSION)

CALL = "setVolumeControlStream(AudioManager.STREAM_MUSIC)"


class VolumeStreamRoutingTest(unittest.TestCase):
    """The hardware volume keys must drive the stream EmuFusion plays on.

    Without setVolumeControlStream an Activity hands the keys to the platform
    default rather than STREAM_MUSIC, so they move a stream nothing plays on
    while gameplay and preview audio keep whatever level STREAM_MUSIC was left
    at. That is the reported drift, and these tests keep the fix in place.
    """

    def test_application_binds_every_activity_to_the_music_stream(self):
        source = APPLICATION.read_text(encoding="utf-8")
        self.assertIn("import android.media.AudioManager;", source)
        self.assertIn(CALL, source)
        # The Qt MainActivity's Java class belongs to Pegasus and is only
        # reachable through smali patching, so the process-wide lifecycle
        # callback is what covers it. Both entry points matter: created covers
        # the first window, resumed covers a restored or recreated one.
        created = source.split("onActivityCreated", 1)[1].split("}", 1)[0]
        self.assertIn("routeVolumeKeysToMusicStream(activity)", created)
        resumed = source.split("onActivityResumed", 1)[1].split("}", 1)[0]
        self.assertIn("routeVolumeKeysToMusicStream(activity)", resumed)
        self.assertIn("AppVolumeController.apply(activity)", resumed)
        self.assertLess(resumed.index("routeVolumeKeysToMusicStream(activity)"),
                        resumed.index("AppVolumeController.apply(activity)"))

    def test_preview_and_browser_activities_bind_it_directly(self):
        for path in (PREVIEW_ACTIVITY, BROWSER_ACTIVITY):
            source = path.read_text(encoding="utf-8")
            self.assertIn("import android.media.AudioManager;", source,
                          f"{path.name} does not import AudioManager")
            body = source.split("onCreate(Bundle", 1)[1]
            self.assertIn(CALL, body,
                          f"{path.name} does not bind the volume keys in onCreate")

    def test_every_audible_path_stays_on_one_stream(self):
        # A second stream would resurrect the same bug from the other side:
        # the keys would move STREAM_MUSIC while part of the app plays
        # somewhere else.
        preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")
        self.assertIn("AudioAttributes.USAGE_MEDIA", preview)
        self.assertNotIn("setAudioStreamType", preview)
        for path in ENGINE_SESSIONS:
            source = path.read_text(encoding="utf-8")
            # Built through AudioTrack.Builder with attributes stated outright
            # rather than the deprecated stream-type constructor, which left
            # the stream mapping for the platform to infer.
            #
            # USAGE_GAME resolves to STREAM_MUSIC, so this is the same stream
            # the keys move -- but now it is asserted by the app instead of
            # assumed.
            #
            # This pins the usage but deliberately does NOT claim the system
            # volume reaches the track. Measured on the AYN Thor it does not:
            # the mixer gain stays at -13 dB across index 15, 12, 8, 4, 1 and
            # 0, so a muted system still produces -41 dB of real HAL output.
            # Swapping this constant to USAGE_MEDIA was measured and changed
            # nothing, so the usage is not the variable and swapping it back
            # would only churn the attribute. See the engine sessions for the
            # full list of ruled-out causes.
            self.assertIn("AudioAttributes.USAGE_GAME", source,
                          f"{path.name} does not declare a game/media usage")
            self.assertIn("new AudioTrack.Builder()", source,
                          f"{path.name} still uses the deprecated constructor")
            self.assertNotIn("new AudioTrack(AudioManager", source,
                             f"{path.name} still infers its stream")
        sounds = MENU_SOUNDS.read_text(encoding="utf-8")
        self.assertIn("AudioAttributes.USAGE_MEDIA", sounds)

    def test_audio_sink_constructor_inventory_is_exhaustive(self):
        """A newly added sink must be classified instead of silently skipped."""
        java_roots = (ROOT / "unified-android" / "src",
                      ROOT / "android-companion" / "src")
        java = [path for root in java_roots for path in root.rglob("*.java")]
        audio_tracks = {path for path in java
                        if "new AudioTrack.Builder()" in path.read_text(
                            encoding="utf-8")}
        media_players = {path for path in java
                         if "new MediaPlayer()" in path.read_text(encoding="utf-8")}
        sound_pools = {path for path in java
                       if "new SoundPool.Builder()" in path.read_text(encoding="utf-8")}
        web_views = {path for path in java
                     if "new WebView(" in path.read_text(encoding="utf-8")}
        self.assertEqual(audio_tracks, set(ENGINE_SESSIONS))
        self.assertEqual(media_players, {PREVIEW_ACTIVITY, BOOT_VIDEO})
        self.assertEqual(sound_pools, {MENU_SOUNDS})
        self.assertEqual(web_views, {BROWSER_ACTIVITY})
        # Boot video is deliberately and permanently silent, so it is not an
        # active sink family in the empirical mute matrix.
        self.assertIn("created.setVolume(0f, 0f)",
                      BOOT_VIDEO.read_text(encoding="utf-8"))
        # QML owns the three single-screen PIP slots plus two always-muted
        # upper-display screensaver decoders. The pair overlaps only for the
        # crossfade. Thor's normal lower preview still routes to PreviewActivity;
        # the screensaver's sound remains there so the synchronized upper copy
        # cannot double the audio.
        theme = THEME.read_text(encoding="utf-8")
        self.assertEqual(theme.count("        Video {"), 5)
        screensaver = theme.split("id: screensaverVideo", 1)[1].split(
            "        MouseArea {", 1
        )[0]
        self.assertEqual(screensaver.count("muted: true"), 2)
        pip = theme.split("id: singleScreenPip", 1)[1].split(
            "    Item {\n        id: chrome", 1
        )[0]
        self.assertIn("!root.useBottomPreview()", pip)

    def test_webview_is_explicitly_a_platform_stream_empirical_gate(self):
        browser = BROWSER_ACTIVITY.read_text(encoding="utf-8")
        self.assertIn(CALL, browser)
        self.assertIn("new WebView(this)", browser)
        # Android WebView exposes no public AudioTrack/MediaPlayer gain handle.
        # The Activity still routes keys through AppVolumeController so other
        # process sinks cannot retain a stale gain while the browser has focus,
        # but final Thor qualification must bind the live Chromium track to
        # AudioFlinger -inf at mute rather than pretending it is app-local.
        self.assertNotIn("AppVolumeController.register", browser)
        dispatch = browser.split(
            "@Override public boolean dispatchKeyEvent(KeyEvent event)", 1
        )[1].split("@Override protected void onPause", 1)[0]
        self.assertIn("AppVolumeController.handleKeyEvent(this, event)", dispatch)
        self.assertIn("return true", dispatch)
        self.assertIn("return super.dispatchKeyEvent(event)", dispatch)
        # A direct second adjustment here would make one quick tap move twice.
        self.assertNotIn("adjustStreamVolume", dispatch)

    def test_thor_local_gain_fallback_reaches_every_engine(self):
        """Thor's mixer can publish index zero while leaving tracks audible."""
        controller = VOLUME_CONTROLLER.read_text(encoding="utf-8")
        self.assertIn('"AYN".equalsIgnoreCase(Build.MANUFACTURER)', controller)
        self.assertIn("getStreamVolumeDb", controller)
        self.assertIn("isStreamMute", controller)
        self.assertIn("if (!needsLocalGain()) return 1f", controller)
        for path in ENGINE_SESSIONS:
            source = path.read_text(encoding="utf-8")
            self.assertIn("AppVolumeController.registerTrack(appContext, track)", source)
            self.assertIn("AppVolumeController.unregisterTrack", source)

    def test_every_discrete_volume_down_is_handled_before_qt(self):
        controller = VOLUME_CONTROLLER.read_text(encoding="utf-8")
        host = IN_WINDOW.read_text(encoding="utf-8")
        self.assertIn("event.getAction() == KeyEvent.ACTION_DOWN", controller)
        self.assertIn("adjustStreamVolume(AudioManager.STREAM_MUSIC", controller)
        self.assertIn("ACTION_UP is consumed", controller)
        self.assertIn("AppVolumeController.handleKeyEvent(activity, event)", host)
        self.assertIn("return true", host.split(
            "AppVolumeController.handleKeyEvent(activity, event)", 1)[1][:80])

    def test_menu_and_preview_use_the_same_local_gain(self):
        sounds = MENU_SOUNDS.read_text(encoding="utf-8")
        preview = PREVIEW_ACTIVITY.read_text(encoding="utf-8")
        self.assertIn("AppVolumeController.gain(context)", sounds)
        self.assertIn("AppVolumeController.registerListener", sounds)
        self.assertIn("soundPool.setVolume(streamId, gain, gain)", sounds)
        self.assertIn("RECENT_STREAM_LIMIT", sounds)
        self.assertIn("AppVolumeController.registerListener", preview)
        self.assertIn("? appVolumeGain : 0f", preview)

    def test_volume_controller_never_calls_foreign_sinks_under_its_lock(self):
        """First SoundPool warmup and a volume tap take opposite locks."""
        source = VOLUME_CONTROLLER.read_text(encoding="utf-8")
        apply = source.split("public static void apply(Context context)", 1)[1]
        apply = apply.split("private static boolean isVolumeKey", 1)[0]
        locked = apply.split("synchronized (LOCK)", 1)[1].split(
            "// Never call an Android audio object", 1
        )[0]
        self.assertNotIn("setTrackGain", locked)
        self.assertNotIn("onAppVolumeChanged", locked)
        callbacks = apply.split("// Never call an Android audio object", 1)[1]
        self.assertIn("setTrackGain(track, value)", callbacks)
        self.assertIn("listener.onAppVolumeChanged(value)", callbacks)

    def test_soundpool_listener_is_singleton_and_tracks_active_stream_ids(self):
        source = MENU_SOUNDS.read_text(encoding="utf-8")
        self.assertIn("static final AppVolumeController.Listener VOLUME_LISTENER", source)
        self.assertIn("if (!volumeListenerRegistered)", source)
        self.assertIn("RECENT_STREAM_IDS.addLast(streamId)", source)
        self.assertIn("soundPool.setVolume(streamId, gain, gain)", source)
        # Releasing and reopening the pool must not append a second copy of the
        # process-lifetime listener. The listener safely no-ops while pool=null.
        release = source.split("public static void release()", 1)[1].split(
            "private static boolean openPool", 1
        )[0]
        self.assertNotIn("volumeListenerRegistered = false", release)

    def test_volume_callbacks_run_outside_the_controller_lock(self):
        controller = VOLUME_CONTROLLER.read_text(encoding="utf-8")
        apply = controller.split("public static void apply(Context context)", 1)[1]
        apply = apply.split("private static boolean isVolumeKey", 1)[0]
        lock_end = apply.index("\n        }", apply.index("synchronized (LOCK)"))
        self.assertGreater(apply.index("listener.onAppVolumeChanged(value)"), lock_end)
        self.assertGreater(apply.index("setTrackGain(track, value)"), lock_end)
        sounds = MENU_SOUNDS.read_text(encoding="utf-8")
        self.assertIn("SoundPool sink gain stream=", sounds)

    def test_session_start_logs_the_resolved_stream_and_level(self):
        # A future "no sound anywhere" report has to be diagnosable from a
        # logcat capture alone, without asking the user to reproduce it.
        audit = AUDIO_LOG.read_text(encoding="utf-8")
        self.assertIn("track.getStreamType()", audit)
        self.assertIn("getStreamVolume(stream)", audit)
        self.assertIn("getStreamMaxVolume(stream)", audit)
        self.assertIn('MARKER = "audio-stream"', audit)
        for path in ENGINE_SESSIONS:
            source = path.read_text(encoding="utf-8")
            self.assertIn("EngineAudioLog.logResolvedStream", source,
                          f"{path.name} never logs its resolved audio stream")


class EngineAudioFocusTest(unittest.TestCase):
    """A game that never asks for focus plays over everything else.

    EmuFusion requested none at all, so gameplay talked over calls, navigation
    prompts and every other app's playback, and was never told to stop.
    """

    def test_focus_is_requested_with_the_attributes_the_track_uses(self):
        source = AUDIO_FOCUS.read_text(encoding="utf-8")
        self.assertIn("AudioFocusRequest.Builder(", source)
        self.assertIn("AudioManager.AUDIOFOCUS_GAIN", source)
        # Asking about a different kind of playback than the one that happens
        # would make the answer meaningless, so these must match the track's.
        self.assertIn("AudioAttributes.USAGE_GAME", source)
        self.assertIn("AudioAttributes.CONTENT_TYPE_MUSIC", source)
        # API 21 is still the floor; AudioFocusRequest arrived in API 26.
        self.assertIn("Build.VERSION.SDK_INT >= 26", source)
        self.assertIn("manager.requestAudioFocus(changes", source)

    def test_a_duck_is_left_to_the_platform(self):
        # Ducking with setVolume would be exactly the app-side gain the tests
        # above forbid, so the request opts into the platform's own ducking.
        source = AUDIO_FOCUS.read_text(encoding="utf-8")
        self.assertIn("setWillPauseWhenDucked(false)", source)
        self.assertNotIn("setVolume(", source)

    def test_every_engine_takes_focus_and_gives_it_back(self):
        for path in ENGINE_SESSIONS:
            source = path.read_text(encoding="utf-8")
            self.assertIn("new EngineAudioFocus(", source,
                          f"{path.name} never holds audio focus")
            self.assertIn("audioFocus.request()", source,
                          f"{path.name} never requests audio focus")
            # Focus kept after a session ends leaves every other app ducked, so
            # the definitive teardown has to give it back.
            release = source.split("public void release()", 1)[1]
            self.assertIn("audioFocus.abandon()", release.split("\n    }", 1)[0],
                          f"{path.name} leaks audio focus on release")

    def test_lost_focus_produces_silence_rather_than_attenuation(self):
        # Honest handling: the engines stop making sound instead of pretending
        # to hold focus they lost. They must not lower their own gain to do it.
        for path in ENGINE_SESSIONS:
            source = path.read_text(encoding="utf-8")
            self.assertIn("audioFocus.isSuppressed()", source,
                          f"{path.name} keeps playing after it loses focus")
            self.assertIn("silenceForAudioFocusLoss", source,
                          f"{path.name} has no focus-loss handler")
            self.assertIn("resumeAfterAudioFocusGain", source,
                          f"{path.name} never restores sound after a regain")


if __name__ == "__main__":
    unittest.main()
