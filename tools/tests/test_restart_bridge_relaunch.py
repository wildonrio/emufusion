"""The frontend restart bridge always starts the fresh frontend it promised.

Thor, 2026-10-11: a game launch intent arrived while the bridge was restarting
the Qt frontend (after a 3DS exit). It landed on the dying process and was
lost, and it finished the bridge as the task was reorganized; the bridge then
bailed out of launchFreshFrontend on isFinishing() after it had already killed
the old process, leaving only the companion service and a black screen.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = (ROOT / 'android-companion/src/com/thorium/preview/FrontendRestartActivity.java').read_text()


class RestartBridgeRelaunchTest(unittest.TestCase):
    def test_finishing_bridge_still_relaunches(self):
        launch = BRIDGE[BRIDGE.index('    private void launchFreshFrontend() {'):]
        launch = launch[:launch.index('\n    }\n')]
        self.assertIn('if (relaunchStarted || isDestroyed()) return;', launch)
        guards = [line for line in launch.splitlines() if line.strip().startswith('if (relaunchStarted')]
        self.assertEqual(len(guards), 1)
        self.assertNotIn('isFinishing()', guards[0])
        self.assertIn('startActivity(frontend);', launch)


if __name__ == '__main__':
    unittest.main()
