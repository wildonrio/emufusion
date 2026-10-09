import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPANION = ROOT / "android-companion"
THEME = (ROOT / "theme" / "theme.qml").read_text(encoding="utf-8")
SERVICE = (COMPANION / "src/com/thorium/preview/PreviewService.java").read_text(
    encoding="utf-8"
)
MANAGER = (COMPANION / "src/com/thorium/preview/VoiceFeedbackManager.java").read_text(
    encoding="utf-8"
)
ACTIVITY = (COMPANION / "src/com/thorium/preview/VoiceFeedbackActivity.java").read_text(
    encoding="utf-8"
)
MANIFEST = (COMPANION / "AndroidManifest.xml").read_text(encoding="utf-8")
BUILD = (ROOT / "unified-android/build.sh").read_text(encoding="utf-8")


class VoiceFeedbackIntegrationTest(unittest.TestCase):
    def test_toolbar_places_raised_hand_immediately_left_of_update_control(self):
        self.assertIn("id: voiceFeedbackButton", THEME)
        self.assertIn("anchors.right: lucentRescanButton.left", THEME)
        self.assertIn('source: Qt.resolvedUrl("assets/raised-hand-white.svg")', THEME)
        icon = (ROOT / "theme" / "assets" / "raised-hand-white.svg").read_text(
            encoding="utf-8"
        )
        self.assertIn('stroke="#fff"', icon)
        self.assertIn('fill="none"', icon)
        self.assertIn('M34 40l10-8V16', icon)
        self.assertNotIn('V12c0-2.8', icon,
                         "the old full-height raised arm was disproportionate")

    def test_review_sheet_shows_transcript_and_exact_send_redo_actions(self):
        self.assertIn("id: voiceFeedbackOverlay", THEME)
        self.assertIn("root.voiceFeedbackTranscript", THEME)
        self.assertIn("id: voiceFeedbackEditor", THEME)
        self.assertIn("activeFocusOnPress: true", THEME)
        self.assertIn("Qt.inputMethod.show()", THEME)
        self.assertIn("VoiceFeedbackManager.replaceTranscript", SERVICE)
        self.assertIn("encodeURIComponent(root.voiceFeedbackTranscript)", THEME)
        self.assertIn('model: ["SEND", "REDO"]', THEME)
        self.assertIn("root.sendVoiceFeedback()", THEME)
        self.assertIn("root.startVoiceFeedback()", THEME)
        self.assertIn("Only the transcription is kept", THEME)

    def test_permission_and_speech_recognition_are_user_visible_and_nonpersistent(self):
        self.assertIn('android.permission.RECORD_AUDIO', MANIFEST)
        self.assertIn('android:name=".VoiceFeedbackActivity"', MANIFEST)
        self.assertIn("requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}", ACTIVITY)
        self.assertIn("SpeechRecognizer.createSpeechRecognizer", ACTIVITY)
        self.assertIn("SpeechRecognizer.createOnDeviceSpeechRecognizer", ACTIVITY)
        self.assertIn("SpeechRecognizer.isOnDeviceRecognitionAvailable", ACTIVITY)
        self.assertIn("RecognizerIntent.EXTRA_PREFER_OFFLINE, true", ACTIVITY)
        self.assertIn("EXTRA_PARTIAL_RESULTS, true", ACTIVITY)
        self.assertIn("Android's built-in transcription rejected microphone", ACTIVITY)
        self.assertIn("checkSelfPermission(Manifest.permission.RECORD_AUDIO)", ACTIVITY)
        self.assertNotIn("AudioRecord", ACTIVITY)
        self.assertNotIn("MediaRecorder", ACTIVITY)
        self.assertIn('.put("audioStored", false)', MANAGER)

    def test_endpoints_are_atomic_and_browser_csrf_protected(self):
        for endpoint in ("/feedback/record", "/feedback/cancel", "/feedback/send"):
            self.assertIn(endpoint, SERVICE)
        self.assertIn('"/feedback/status".equals(path)', SERVICE)
        self.assertIn("VoiceFeedbackManager.begin", SERVICE)
        self.assertIn("VoiceFeedbackManager.openGithubComposer", SERVICE)
        self.assertIn("appIsVisible", MANAGER)
        self.assertIn("origin != null || referer != null", SERVICE)

    def test_github_credentials_are_not_embedded(self):
        combined = MANAGER + ACTIVITY + SERVICE + THEME
        self.assertIn('REPOSITORY = "wildonrio/emufusion"', MANAGER)
        self.assertIn("issues/new?title=", MANAGER)
        self.assertIn("requiresGithubConfirmation", MANAGER)
        for secret_marker in ("ghp_", "github_pat_", "client_secret", "Authorization: token"):
            self.assertNotIn(secret_marker, combined)

    def test_automatic_diagnostics_use_an_allowlist_not_raw_log_redaction(self):
        self.assertIn("FeedbackDiagnostics.markdown(version, code, system)", MANAGER)
        self.assertIn("systemContext = FeedbackDiagnostics.systemCode(system)", MANAGER)
        self.assertIn("GitHub issues are public and identify your GitHub account", THEME)
        for forbidden in ("Build.SERIAL", "ANDROID_ID", "getMacAddress", "getImei",
                          "ProcessBuilder", "logcat", "collectOwnLogs", "redact(",
                          "Build.MANUFACTURER", "Build.MODEL", "Build.DEVICE",
                          "Build.VERSION.RELEASE", "DisplayManager", "titleContext",
                          "pageContext", "captureStartedAtMs", "ThemeInstaller"):
            self.assertNotIn(forbidden, MANAGER)

    def test_execute_actual_diagnostic_field_boundary(self):
        java = pathlib.Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")
        if not (java / "javac").is_file():
            self.skipTest("JDK 17 is required for the executable field-boundary check")
        with tempfile.TemporaryDirectory(prefix="emufusion-feedback-fields-") as work:
            subprocess.run([str(java / "javac"), "-d", work,
                            str(COMPANION / "src/com/thorium/preview/FeedbackDiagnostics.java"),
                            str(COMPANION / "tests/com/thorium/preview/FeedbackDiagnosticsTest.java")],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(java / "java"), "-ea", "-cp", work,
                            "com.thorium.preview.FeedbackDiagnosticsTest"],
                           check=True, capture_output=True, timeout=30)

    def test_unified_apk_injects_permission_and_activity(self):
        self.assertIn('android.permission.RECORD_AUDIO', BUILD)
        self.assertIn('com.thorium.preview.VoiceFeedbackActivity', BUILD)
        self.assertIn('@android:style/Theme.Translucent.NoTitleBar', BUILD)


class VoiceFeedbackBacklogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "tools/update_voice_feedback_backlog.py"
        spec = importlib.util.spec_from_file_location("voice_feedback_backlog", path)
        cls.module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.module)

    def test_backlog_categorizes_and_does_not_duplicate_issue_bodies(self):
        issues = [
            {
                "number": 4,
                "title": "[Device feedback] Game crashes when returning",
                "body": "PRIVATE TRANSCRIPT",
                "html_url": "https://example.invalid/4",
                "updated_at": "2026-08-30T12:00:00Z",
                "labels": [],
            },
            {
                "number": 5,
                "title": "[Device feedback] Please add a favorites filter",
                "body": "PRIVATE FEATURE TRANSCRIPT",
                "html_url": "https://example.invalid/5",
                "updated_at": "2026-08-30T13:00:00Z",
                "labels": [],
            },
            {
                "number": 6,
                "title": "[Device feedback] Something about the menu",
                "body": "PRIVATE UNCLEAR TRANSCRIPT",
                "html_url": "https://example.invalid/6",
                "updated_at": "2026-08-30T14:00:00Z",
                "labels": [],
            },
        ]
        rendered = self.module.render("wildonrio/emufusion", issues)
        self.assertIn("## Bugs", rendered)
        self.assertIn("#4 — Game crashes when returning", rendered)
        self.assertIn("## Feature requests", rendered)
        self.assertIn("#5 — Please add a favorites filter", rendered)
        self.assertIn("## Needs review", rendered)
        self.assertIn("#6 — Something about the menu", rendered)
        self.assertNotIn("PRIVATE", rendered)

    def test_script_is_stable_when_input_has_not_changed(self):
        issues = [{
            "number": 1,
            "title": "[Device feedback] Crash",
            "html_url": "https://example.invalid/1",
            "updated_at": "2026-08-30T00:00:00Z",
            "labels": [{"name": "bug"}],
        }]
        self.assertEqual(
            self.module.render("wildonrio/emufusion", issues),
            self.module.render("wildonrio/emufusion", json.loads(json.dumps(issues))),
        )


if __name__ == "__main__":
    unittest.main()
