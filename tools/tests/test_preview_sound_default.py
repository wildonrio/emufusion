from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
THEME = (ROOT / "theme" / "theme.qml").read_text(encoding="utf-8")
SERVICE = (ROOT / "android-companion" / "src" / "com" / "thorium" /
           "preview" / "PreviewService.java").read_text(encoding="utf-8")
INSTALLER = (ROOT / "android-companion" / "src" / "com" / "thorium" /
             "preview" / "ThemeInstaller.java").read_text(encoding="utf-8")
ACTIVITY = (ROOT / "android-companion" / "src" / "com" / "thorium" /
            "preview" / "PreviewActivity.java").read_text(encoding="utf-8")


class PreviewSoundDefaultTest(unittest.TestCase):
    def test_theme_defaults_and_migrates_preview_sound_off_once(self):
        self.assertIn("property bool previewSoundEnabled: false", THEME)
        completed = THEME.split("Component.onCompleted: {", 1)[1]
        migration = completed.split(
            'if (!api.memory.has("emufusionPreviewSoundDefaultOffV2")) {', 1
        )[1].split("requestPreviewEndpoint", 1)[0]
        self.assertIn("previewSoundEnabled = false", migration)
        self.assertIn('api.memory.set("thoriumPreviewSound", false)', migration)
        self.assertIn(
            'api.memory.set("emufusionPreviewSoundDefaultOffV2", true)', migration)
        self.assertIn(
            'Boolean(api.memory.get("thoriumPreviewSound")) : false', migration)

    def test_settings_toggle_remains_visible_and_persistent(self):
        self.assertIn('"PREVIEW VIDEO SOUND"', THEME)
        self.assertIn(
            'if (index === 2) return previewSoundEnabled ? "ON" : "OFF"', THEME)
        setter = THEME.split("function setPreviewSoundEnabled", 1)[1].split(
            "function applyWidescreenStatus", 1)[0]
        self.assertIn('api.memory.set("thoriumPreviewSound", previewSoundEnabled)',
                      setter)
        self.assertIn('requestPreviewEndpoint("settings/sound?enabled=" +', setter)
        self.assertIn("setPreviewSoundEnabled(!previewSoundEnabled)", THEME)

    def test_both_preview_playback_paths_fail_silent(self):
        self.assertGreaterEqual(
            THEME.count("muted: !root.previewSoundEnabled"), 3,
            "every single-screen preview decoder must follow the setting")
        self.assertGreaterEqual(
            SERVICE.count(".getBoolean(EXTRA_SOUND_ENABLED, false)"), 1)
        self.assertIn(
            ".getBoolean(PreviewService.EXTRA_SOUND_ENABLED, false);", ACTIVITY)
        endpoint = SERVICE.split(
            '} else if ("/settings/sound".equals(path)) {', 1
        )[1].split('} else if ("/settings/sfx".equals(path)) {', 1)[0]
        self.assertIn(".putBoolean(EXTRA_SOUND_ENABLED, enabled)", endpoint)
        self.assertIn("ACTION_AUDIO", endpoint)

    def test_changed_theme_is_reloaded_on_its_first_updated_launch(self):
        self.assertIn("Runnable installedCompletion", INSTALLER)
        self.assertIn("installed = installBundledBlocking(context, force);",
                      INSTALLER)
        self.assertIn("if (installed && installedCompletion != null)", INSTALLER)
        startup = SERVICE.split("public void onCreate()", 1)[1].split(
            "public int onStartCommand", 1)[0]
        self.assertIn("ThemeInstaller.installBundledIfNeeded(", startup)
        self.assertIn("() -> launchRouteReloadPending.set(true)", startup)
        heartbeat = SERVICE.split('} else if ("/heartbeat".equals(path)) {', 1)[1]
        self.assertIn("maybeReloadMigratedLaunchRoutes();", heartbeat)


if __name__ == "__main__":
    unittest.main()
