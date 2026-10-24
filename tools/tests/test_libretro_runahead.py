"""Run-ahead for software-rendered libretro cores, wired end to end.

Each image shown is the game one frame further on with the input already
held, so a press shows one frame (16.7 ms at 60 Hz) sooner than on the console
(owner, October 2026: latency first, beyond what Lossless Scaling can reach
from outside the emulator). The behaviour itself is exercised against the mock
core by unified-android/native/tests/runahead_host_test.c (run_tests.sh, also
under ASan/UBSan); these checks pin the links that test cannot see.
"""
import unittest

from tools.tests.test_native_reset_and_port_device import (
    HOST_C, HOST_H, JNI_C, LIBRETRO_HOST, LIBRETRO_SESSION, NATIVE, body_after)


class LibretroRunAheadTest(unittest.TestCase):
    def setUp(self):
        self.host = HOST_C.read_text(encoding='utf-8')

    def test_native_frames_run_ahead_only_when_it_is_safe(self):
        run = body_after(self.host, 'bool emufusion_retro_run_frame(emufusion_retro_host')
        self.assertIn('if (!runahead_run(host)) host->run();', run)
        gate = body_after(self.host, 'static bool runahead_run(emufusion_retro_host')
        # A hardware core's GPU state is not in its savestate.
        self.assertIn('host->hw_negotiated', gate)
        self.assertIn('!runahead_check(host)', gate)
        self.assertIn('RUNAHEAD_MAX_COST_SHARE * period_ms', gate)
        # Later divergence is caught without another replay pause.
        self.assertIn('"predicted frame differs from the true frame"', gate)
        self.assertIn('"predicted image differs from the true image"', gate)
        self.assertNotIn('runahead_check(host)', gate.split('start = monotonic_ns();', 1)[1])
        check = body_after(self.host, 'static bool runahead_check(emufusion_retro_host')
        self.assertIn('RUNAHEAD_UNSAFE_QUIRKS', check)
        self.assertIn('first.state != second.state && first.video != second.video', check)
        # Quirks are only read: the answer every core already got is unchanged.
        quirks = self.host[self.host.index('case RETRO_ENVIRONMENT_SET_SERIALIZATION_QUIRKS:'):][:400]
        self.assertIn('return false;', quirks)
        self.assertIn('void emufusion_retro_set_runahead(emufusion_retro_host *host, unsigned frames);',
                      HOST_H.read_text(encoding='utf-8'))
        self.assertIn('Java_com_thorium_preview_LibretroHost_nativeSetRunAhead',
                      JNI_C.read_text(encoding='utf-8'))

    def test_hidden_frames_are_neither_shown_nor_heard(self):
        video = body_after(self.host, 'static void video_callback(const void *data')
        self.assertLess(video.index('suppress_video'), video.index('memcpy(active_host->video_bytes'))
        for callback in ('static void audio_sample_callback(', 'static size_t audio_batch_callback('):
            body = body_after(self.host, callback)
            self.assertLess(body.index('suppress_audio'), body.index('push_audio_frame'))

    def test_sessions_request_one_frame_except_in_netplay(self):
        session = LIBRETRO_SESSION.read_text(encoding='utf-8')
        self.assertIn('opened.loadGame(game);\n                    opened.setRunAheadFrames(runAheadFrames());',
                      session)
        attach = body_after(session, 'public void attachNetplayRelay(')
        self.assertIn('setRunAheadFrames(0)', attach)
        self.assertIn('setRunAheadFrames(runAheadFrames())',
                      body_after(session, 'public void detachNetplayRelay()'))
        self.assertIn('/data/local/tmp/emufusion-no-runahead', session)
        host = LIBRETRO_HOST.read_text(encoding='utf-8')
        run = body_after(host, 'public synchronized void runFrame()')
        self.assertLess(run.index('nativeSetRunAhead(handle, runAhead)'), run.index('nativeRunFrame(handle)'))

    def test_the_native_suite_runs_the_mock_core_test(self):
        runner = (NATIVE / 'run_tests.sh').read_text(encoding='utf-8')
        self.assertEqual(runner.count('runahead_host_test" "$TEST_DIR/mock_core.so"'), 1)
        self.assertEqual(runner.count('runahead_host_test" "$SANITIZED/mock_core.so"'), 1)


if __name__ == '__main__':
    unittest.main()
