"""The small cores are kept full during Cemu's held output (3.2.159).

Checks the QA switch, that the occupancy starts and stops with the frame thread and only that output
keeps it going, that its threads stay at the lowest priority on one small core each without executing,
and that the native mask is the lowest-clocked cluster and empty on uniform CPUs."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / 'unified-android/src/com/thorium/preview/game'
NATIVE = ROOT / 'unified-android/native/emufusion_framegen_timer_jni.c'


class SmallCoreOccupancyTest(unittest.TestCase):
    def test_switch_defaults_on(self):
        switch = (GAME / 'TimelineSchedulerSwitch.java').read_text()
        self.assertIn('SMALL_CORES_GLOBAL = "emufusion_framegen_small_cores"', switch)
        self.assertIn('private static volatile boolean smallCores = true;', switch)
        self.assertIn('context.getContentResolver(), SMALL_CORES_GLOBAL, 1) != 0;', switch)
        occupancy = (GAME / 'SmallCoreOccupancy.java').read_text()
        self.assertIn('if (!TimelineSchedulerSwitch.smallCores()) return NONE;', occupancy)

    def test_lifetime_follows_the_frame_thread(self):
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        self.assertIn('if (externalTransport == null) smallCoreOccupancy = SmallCoreOccupancy.start();', generator)
        self.assertIn('smallCoreOccupancy.close();\n'
                      '                    smallCoreOccupancy = SmallCoreOccupancy.NONE;', generator)
        self.assertIn('private SmallCoreOccupancy smallCoreOccupancy = SmallCoreOccupancy.NONE;', generator)

    def test_only_the_held_output_keeps_it_going(self):
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        self.assertIn('if (timelineActive && heldSwapOutput()) smallCoreOccupancy.frame();', generator)
        self.assertEqual(generator.count('smallCoreOccupancy.frame()'), 1)

    def test_threads_give_way_and_stop_when_nothing_is_planned(self):
        occupancy = (GAME / 'SmallCoreOccupancy.java').read_text()
        self.assertIn('thread.setDaemon(true);', occupancy)
        self.assertIn('System.nanoTime() - lastFrameNs > STALE_NS', occupancy)
        self.assertIn('LockSupport.parkNanos(IDLE_LOOK_NS);', occupancy)
        # Re-pinned after an idle stretch: Android resets the mask with the app's CPU set.
        self.assertIn('pinned = false;', occupancy)
        self.assertIn('DenseGpuTimer.occupyCurrentThread(one) <= 0L', occupancy)
        self.assertIn('DenseGpuTimer.waitOccupied(OCCUPIED_SLICE_NS);', occupancy)
        source = NATIVE.read_text()
        body = source[source.index('Java_com_thorium_preview_game_DenseGpuTimer_nativeOccupy'):]
        self.assertIn('syscall(__NR_setpriority, 0 /* PRIO_PROCESS */, 0, 19)', body)
        self.assertIn('syscall(__NR_sched_setaffinity, 0, sizeof wanted, &wanted)', body)
        self.assertIn('__asm__ volatile("wfe");', source)

    def test_mask_is_the_slowest_cluster_or_nothing(self):
        source = NATIVE.read_text()
        body = source[source.index('Java_com_thorium_preview_game_DenseGpuTimer_nativeSmallCoreMask'):]
        self.assertIn('unsigned long long fast = fast_cpu_mask();', body)
        self.assertIn('if (fast == 0) return 0;', body)
        self.assertIn('return (jlong) (known & ~fast);', body)
        timer = (GAME / 'DenseGpuTimer.java').read_text()
        self.assertIn('private static native long nativeSmallCoreMask();', timer)
        self.assertIn('private static native long nativeOccupy(long mask);', timer)


if __name__ == '__main__':
    unittest.main()
