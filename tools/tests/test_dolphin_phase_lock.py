"""Dolphin's images are held to the phase lock and stamped ahead by default (2026-11-06).

Double Dash ranged from 0 to 168 hitches per 30 s by where its phase landed; with
the lock and the stamp, 0 to 20. Ocarina of Time, on the same render loop, is no
better held, so other hardware cores stay on the advisor unless QA asks."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PREVIEW = ROOT / 'unified-android/src/com/thorium/preview'
GAME = PREVIEW / 'game'


class DolphinPhaseLockTest(unittest.TestCase):
    def test_only_dolphin_is_locked_by_default(self):
        loop = (PREVIEW / 'ExperimentalGlesRenderLoop.java').read_text()
        host = (PREVIEW / 'ExperimentalGlesLibretroHost.java').read_text()
        self.assertIn('static boolean phaseLockedByDefault(String coreFileName) {', host)
        self.assertIn('return "libemufusion_core_dolphin.so".equals(coreFileName);', host)
        self.assertIn('return ExperimentalGlesLibretroHost.phaseLockedByDefault(core.getName());', loop)
        self.assertIn('default boolean phaseLockedByDefault() { return false; }', loop)

    def test_the_lock_and_the_stamp_share_one_decision(self):
        loop = (PREVIEW / 'ExperimentalGlesRenderLoop.java').read_text()
        self.assertIn('takeHardwareSourcePhaseNudgeNs(attachedSurface,\n'
                      '                                host.phaseLockedByDefault())', loop)
        host = (PREVIEW / 'ExperimentalGlesLibretroHost.java').read_text()
        self.assertIn('phaseLockedByDefault = phaseLockedByDefault(core.getName());', host)
        self.assertEqual(host.count('hardwareStampAheadNs(surface,\n                phaseLockedByDefault)'), 2)
        generator = (GAME / 'DisplayFrameGenerator.java').read_text()
        self.assertIn('TimelineSchedulerSwitch.hardwarePhaseLock(lockedByDefault) ? 10_000_000L : 0L', generator)
        self.assertIn('if (!TimelineSchedulerSwitch.hardwarePhaseLock(lockedByDefault)) return 0L;', generator)

    def test_qa_reaches_every_hardware_core_or_none(self):
        switch = (GAME / 'TimelineSchedulerSwitch.java').read_text()
        self.assertIn('HARDWARE_PHASE_LOCK_GLOBAL = "emufusion_framegen_hardware_phase_lock"', switch)
        self.assertIn('private static volatile int hardwarePhaseLock = -1;', switch)
        self.assertIn('return level > 0 || (level < 0 && lockedByDefault);', switch)


if __name__ == '__main__':
    unittest.main()
