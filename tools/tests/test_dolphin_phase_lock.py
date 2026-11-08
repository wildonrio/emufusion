"""Dolphin's stamps start behind the clock, so the firmware always paces it (2026-11-06).

A hardware core's stamps follow its run sequence: a burst leaves them ahead of the
clock, a stall behind it. Only stamps behind it get the firmware's pacing. Double
Dash ranged from 1.8 to 168 hitches per 30 s by that alone. Other hardware cores
stay as they are unless QA asks; the phase lock is QA only."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PREVIEW = ROOT / 'unified-android/src/com/thorium/preview'
GAME = PREVIEW / 'game'


class DolphinStampTest(unittest.TestCase):
    def test_only_dolphin_starts_behind_by_default(self):
        registry = (GAME / 'FrameGenerationRendererRegistry.java').read_text()
        self.assertIn('public static boolean stampBehindByDefault(String coreFileName) {', registry)
        self.assertIn('return "libemufusion_core_dolphin.so".equals(coreFileName) ||\n                "libemufusion_core_mupen64plus_next.so".equals(coreFileName);', registry)

    def test_both_hosts_ask_for_it(self):
        # Both runtimes: Dolphin on GameCube and Wii runs the Vulkan host.
        for name in ('ExperimentalGlesLibretroHost.java', 'ExperimentalVulkanLibretroHost.java'):
            host = (PREVIEW / name).read_text()
            self.assertIn('stampBehindByDefault = FrameGenerationRendererRegistry.stampBehindByDefault(core.getName());',
                          host)
            self.assertIn('stampBehindByDefault)', host)
            self.assertIn('hardwareStampAheadNs(surface,', host)

    def test_the_generator_chooses_the_stamp_and_drains_a_pinned_core(self):
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        self.assertIn('if (TimelineSchedulerSwitch.hardwarePhaseLock()) return 10_000_000L;', generator)
        self.assertIn('firmwarePacedSource = TimelineSchedulerSwitch.hardwareStampBehind(pinnedByDefault);', generator)
        self.assertIn('-1_000_000_000L', generator)
        self.assertIn('TimelineSchedulerSwitch.compositorDrainAllSources() || firmwarePacedSource ||', generator)

    def test_qa_chooses_the_lock_or_neither(self):
        switch = (GAME / 'TimelineSchedulerSwitch.java').read_text()
        self.assertIn('HARDWARE_PHASE_LOCK_GLOBAL = "emufusion_framegen_hardware_phase_lock"', switch)
        self.assertIn('private static volatile int hardwarePhaseLock = -1;', switch)
        self.assertIn('static boolean hardwarePhaseLock() { return hardwarePhaseLock > 0; }', switch)
        self.assertIn('return hardwarePhaseLock < 0 && pinnedByDefault;', switch)

    def test_native_stamps_take_a_lead_or_a_lag(self):
        for name in ('emufusion_android_vulkan_backend.c', 'emufusion_android_gles_backend.c'):
            native = (ROOT / 'unified-android/native' / name).read_text()
            self.assertIn('backend->stamp_ahead_ns = ahead_ns;', native)
            self.assertIn('backend->timestamp_lead_ns = emufusion_stamp_ahead_ns(backend->stamp_ahead_ns);', native)
            # A lead survives a stall; a lag has no floor to hold.
            self.assertIn('if (backend->timestamp_lead_ns > 0) {', native)
            self.assertIn('backend->timestamp_base_ns += floor_ns - timestamp;', native)


if __name__ == '__main__':
    unittest.main()
