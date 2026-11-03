"""The frame thread stays off the lowest-clocked CPU cluster (3.2.143).

Checks the QA switch, that the mask is applied on the frame thread at start
and again with each once-a-second report, and that the native function
derives the cluster from each CPU's maximum clock within the allowed CPUs."""
from pathlib import Path
import re
import unittest
from tools.tests.test_framegen_startup_fallback import method

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / 'unified-android/src/com/thorium/preview/game'
NATIVE = ROOT / 'unified-android/native/emufusion_framegen_timer_jni.c'


class FrameThreadFastCoresTest(unittest.TestCase):
    def test_switch_defaults_on(self):
        switch = (GAME / 'TimelineSchedulerSwitch.java').read_text()
        self.assertIn('FAST_CORES_GLOBAL = "emufusion_framegen_fast_cores"', switch)
        self.assertIn('private static volatile boolean fastCores = true;', switch)
        self.assertIn('context.getContentResolver(), FAST_CORES_GLOBAL, 1) != 0;', switch)

    def test_applied_on_the_frame_thread_at_start_and_each_report(self):
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        pin = method(generator, '    private void pinFrameThreadToFastCores(')
        self.assertIn('android.os.Looper.myLooper() != handler.getLooper()) return;', pin)
        self.assertIn('catch (UnsatisfiedLinkError | RuntimeException failure)', pin)
        self.assertIn('fastCorePinUnavailable = true;', pin)
        self.assertRegex(generator, r'workHintTargetNs\(refreshHz\)\);\n\s+pinFrameThreadToFastCores\(\);')
        stats = method(generator, '    private void reportStats(')
        self.assertTrue(stats.split('{', 1)[1].lstrip().startswith('pinFrameThreadToFastCores();'))
        self.assertIn('" fastCores=0x" + Long.toHexString(fastCoreMask) +', generator)
        timer = (GAME / 'DenseGpuTimer.java').read_text()
        self.assertIn('private static native long nativePinFastCores();', timer)

    def test_native_mask_excludes_only_the_slowest_cluster(self):
        source = NATIVE.read_text()
        body = source[source.index('Java_com_thorium_preview_game_DenseGpuTimer_nativePinFastCores'):]
        self.assertIn('cpuinfo_max_freq', body)
        self.assertIn('if (freq[cpu] > lowest) fast |= 1ULL << cpu;', body)
        self.assertIn('fast &= allowed;', body)
        self.assertRegex(body, re.escape('if (fast == 0) return 0;'))
        self.assertIn('syscall(__NR_sched_setaffinity, 0, sizeof fast, &fast)', body)


if __name__ == '__main__':
    unittest.main()
