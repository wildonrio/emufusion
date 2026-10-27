"""Passthrough on a device where generation is unavailable for good never waits on the GPU."""
from pathlib import Path
import unittest

from tools.tests.test_framegen_startup_fallback import method

SOURCE = (Path(__file__).resolve().parents[2] /
          'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java')


class PassthroughSignatureTest(unittest.TestCase):
    def test_permanent_unavailability_skips_the_synchronous_readback(self):
        body = method(SOURCE.read_text(), '    private boolean latestImageIsUnique(')
        gate = body.split('GLES20.glFinish();', 1)[0]
        early = gate.split('long denseWallStart', 1)[0]
        self.assertIn('densePyramidUnavailable && externalTransport == null && !holdoutMode', early)
        self.assertIn('return true;', early)
        # Recoverable states (startup, a transient rejection, an overload
        # suspension) still classify: a re-arm plans on the unique rate.
        self.assertNotIn('denseOverloadSuspended', early)


if __name__ == '__main__':
    unittest.main()
