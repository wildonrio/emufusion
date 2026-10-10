"""A game that fails to start must not block every game after it.

October 9 3.2.19 runs: on the Thor a truncated GameCube disc was refused
("Invalid RVZ image"), and on the clean phone a slow first load timed out.
Every later launch then logged "Exit save rejected; gameplay retained ...
engine state vault is not ready": stopping the failed session demanded a Quick
Resume save from an engine that never ran, so the dead session was kept and no
other game could open until the app was restarted. Separately, the first call
into the GLES thread queued behind the core/game load with only 10 s to wait;
a slow load timed out, teardown raced the finishing load and crashed (N64).
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SESSION = (ROOT / 'unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java').read_text()
LOOP = (ROOT / 'unified-android/src/com/thorium/preview/ExperimentalGlesRenderLoop.java').read_text()


class FailedLaunchReleasesSessionTest(unittest.TestCase):
    def save_body(self):
        start = SESSION.index('    private Throwable saveQuickResume(boolean requireCommit) {')
        return SESSION[start:SESSION.index('persistSaveRam(active);', start)]

    def test_stop_without_a_running_engine_needs_no_save(self):
        body = self.save_body()
        idle = body.index('if (!prepared || active == null) {')
        vault = body.index('if (vault == null || identity == null) {')
        self.assertLess(idle, vault)
        self.assertIn('return null;', body[idle:vault])
        self.assertIn('marker=unstarted-no-save', body[idle:vault])
        # A running game whose save cannot be written is still retained.
        self.assertIn('new IllegalStateException("engine state vault is not ready")', body[vault:])

    def test_native_adapter_sessions_already_skip_unstarted_saves(self):
        adapter = (ROOT / 'unified-android/src/com/thorium/preview/game/NativeAdapterEngineSession.java').read_text()
        self.assertIn('marker=unstarted-no-save', adapter)

    def test_startup_calls_wait_for_the_load(self):
        call = LOOP[LOOP.index('    private <T> T call(Callable<T> action) {'):]
        self.assertIn('task.get(initializeFinished ? 10 : 60, TimeUnit.SECONDS)', call[:1500])
        init = LOOP[LOOP.index('    private void initialize() {'):LOOP.index('    private void scheduleFrame() {')]
        # Set on success before onReady and on failure before reporting.
        self.assertLess(init.index('initializeFinished = true;'), init.index('listener.onReady();'))
        catch = init[init.index('} catch (Throwable failure) {'):]
        self.assertLess(catch.index('initializeFinished = true;'), catch.index('reportError(failure);'))


if __name__ == '__main__':
    unittest.main()
