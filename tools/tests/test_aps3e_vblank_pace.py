"""aPS3e's VBlank clock can be trimmed to the measured panel (2026-10-26)."""
from pathlib import Path
import subprocess
import unittest

from tools.tests import aps3e_locked_source as L

ROOT = Path(__file__).resolve().parents[2]
PATCH = 'engines/patches/aps3e-vblank-pace.patch'
ADAPTER = ROOT / 'engines/patches/aps3e-emufusion-adapter.cpp'
RSX = 'app/src/main/cpp/rpcs3/rpcs3/Emu/RSX/RSXThread.cpp'


class Aps3eVblankPaceTest(unittest.TestCase):
    def test_patch_is_locked_last_and_paces_every_period(self):
        self.assertEqual(PATCH, L.locked_patches()[-1])
        if not L.available():
            self.skipTest('pinned aPS3e archive absent')
        root = L.state_before(PATCH, extra=(RSX,))
        before = (root / RSX).read_text()
        self.assertEqual(2, before.count("1'000'000 + u64{g_cfg.video.vblank_ntsc.get()} * 1000;"))
        subprocess.run(['git', 'apply', '--unsafe-paths', str(ROOT / PATCH)], cwd=root,
                       check=True, capture_output=True)
        after = (root / RSX).read_text()
        self.assertIn('std::atomic<double> g_emufusion_vblank_hz{0.0};', after)
        # Both the thread's first period and its once-a-second refresh follow the trim...
        self.assertEqual(2, after.count('vblank_period = emufusion_vblank_period(vblank_rate);'))
        # ...and the untrimmed period is still the configured one, NTSC fixup included.
        self.assertEqual(1, after.count("1'000'000 + u64{g_cfg.video.vblank_ntsc.get()} * 1000;"))
        self.assertIn('1\'000\'000.0 * static_cast<double>(vblank_rate) / hz + 0.5', after)
        # The automatic frame limiter follows the same clock.
        self.assertIn('case frame_limit_type::_auto:\n\t\t\tlimit = g_emufusion_vblank_hz', after)
        self.assertLess(after.index('g_emufusion_vblank_hz{0.0}'), after.index('namespace rsx'))

    def test_adapter_exports_bounded_hooks_and_resets_per_session(self):
        source = ADAPTER.read_text()
        self.assertIn('double emufusion_native_adapter_declared_video_hz(void) {\n'
                      '    return kEmuFusionDeclaredVblankHz;', source)
        self.assertIn('bool emufusion_native_adapter_set_paced_video_hz(double hz) {', source)
        self.assertIn('std::fabs(hz / kEmuFusionDeclaredVblankHz - 1.0) > 0.0075 + 1.0e-12', source)
        self.assertIn('extern std::atomic<double> g_emufusion_vblank_hz;', source)
        load = source[source.index('static bool adapter_load('):source.index('static bool adapter_start(')]
        self.assertIn('g_emufusion_vblank_hz.store(0.0, std::memory_order_relaxed);', load)


if __name__ == '__main__':
    unittest.main()
