"""The app update comes first at startup, and an update offers "Restart app?".

Owner, 2026-10-10: "when I first opened the app, the first thing it should do
before it starts searching for box art ... is look for an update to the app.
And then after the app updates, there should be a pop-up that says restart
app?"
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SERVICE = (ROOT / 'android-companion/src/com/thorium/preview/PreviewService.java').read_text()
UPDATE = (ROOT / 'android-companion/src/com/thorium/preview/UpdateManager.java').read_text()
RECEIVER = (ROOT / 'android-companion/src/com/thorium/preview/BootReceiver.java').read_text()
PROMPT = (ROOT / 'android-companion/src/com/thorium/preview/UpdateCompleteActivity.java').read_text()
BUILD = (ROOT / 'unified-android/build.sh').read_text()


class UpdateFirstTest(unittest.TestCase):
    def test_library_scan_waits_for_the_first_update_check(self):
        create = SERVICE.split('startServer();', 1)[1].split('private static final long STARTUP_UPDATE_GATE_MS', 1)[0]
        self.assertIn('updateManager.awaitFirstCheck(STARTUP_UPDATE_GATE_MS)', create)
        self.assertIn('importManager.startInitialScan()', create)
        self.assertLess(create.index('awaitFirstCheck'), create.index('importManager.startInitialScan()'))
        self.assertIn('STARTUP_UPDATE_GATE_MS = 5L * 60L * 1000L', SERVICE)

    def test_every_check_releases_the_gate(self):
        worker = UPDATE.split('void checkAsync(boolean userInitiated) {', 1)[1].split('worker.start();', 1)[0]
        finally_block = worker.split('} finally {', 1)[1]
        self.assertIn('firstCheck.countDown();', finally_block)
        self.assertIn('boolean awaitFirstCheck(long timeoutMs)', UPDATE)


class RestartPromptTest(unittest.TestCase):
    def test_package_replaced_offers_a_restart_while_the_screen_is_on(self):
        self.assertIn('Intent.ACTION_MY_PACKAGE_REPLACED.equals(intent.getAction())', RECEIVER)
        self.assertIn('PrimaryDisplayFocusGuard.isInteractive(context)', RECEIVER)
        self.assertIn('UpdateCompleteActivity.announce(context);', RECEIVER)

    def test_prompt_restarts_the_frontend_or_falls_back_to_a_notification(self):
        self.assertIn('.setMessage("Restart app?")', PROMPT)
        self.assertIn('.setPositiveButton("Restart"', PROMPT)
        self.assertIn('.setNegativeButton("Later"', PROMPT)
        self.assertIn('Settings.canDrawOverlays(context)', PROMPT)
        self.assertIn('"Restart app? Tap to restart EmuFusion"', PROMPT)
        self.assertIn('"org.pegasus_frontend.android.MainActivity"', PROMPT)

    def test_unified_manifest_declares_the_prompt(self):
        self.assertIn('android:name="com.thorium.preview.UpdateCompleteActivity"', BUILD)


if __name__ == '__main__':
    unittest.main()
