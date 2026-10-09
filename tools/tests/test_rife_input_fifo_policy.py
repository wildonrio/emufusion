"""Private input queue policy; device queue latency is a separate acceptance test."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RifeInputFifoPolicyTest(unittest.TestCase):
    def test_only_rife_opts_into_preserving_input_queue(self):
        api = (ROOT / 'unified-android/src/com/thorium/preview/game/ExternalFrameGenerationTransport.java').read_text()
        factory = (ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifeQualificationTransportFactory.java').read_text()
        self.assertIn('default int endpointSwapInterval() { return 0; }', api)
        self.assertIn('public int endpointSwapInterval() { return 1; }', factory)

    def test_initial_and_reopened_input_do_not_change_visible_output_policy(self):
        renderer = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        policy = 'EGL14.eglSwapInterval(eglDisplay, externalTransportFactory.endpointSwapInterval())'
        self.assertEqual(renderer.count(policy), 2)
        initial = renderer.index(policy)
        self.assertIn('eglMakeCurrent(endpoint)', renderer[initial-400:initial])
        self.assertIn('eglMakeCurrent(output)', renderer[initial:initial+400])
        reopen = renderer.index(policy, initial+len(policy))
        self.assertIn('eglEndpointSurface, eglEndpointSurface, eglContext)', renderer[reopen-150:reopen])
        self.assertIn('eglSurface, eglSurface, eglContext)', renderer[reopen:reopen+250])
        output = renderer.index('app compositor requires nonblocking EGL swap')
        self.assertIn('EGL14.eglSwapInterval(eglDisplay, 0)', renderer[output-180:output])
