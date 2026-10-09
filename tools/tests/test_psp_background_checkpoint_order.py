"""Focused source wiring for capture-before-detach PSP background checkpoints.

The real render-loop/fake-backend tests cover execution; these checks prevent
the session from moving native capture back onto its delayed disk worker.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PREVIEW = ROOT / "unified-android/src/com/thorium/preview"


def section(source, start, end):
    return source.split(start, 1)[1].split(end, 1)[0]


class PspBackgroundCheckpointOrderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = (PREVIEW / "game/PpssppGlesEngineSession.java").read_text()
        cls.loop = (PREVIEW / "ExperimentalGlesRenderLoop.java").read_text()

    def test_background_capture_is_submitted_before_lifecycle_dispatch(self):
        pause = section(self.session, "@Override public void pause(PauseReason reason)",
                        "private void silenceForAudioFocusLoss()")
        self.assertIn("reason == PauseReason.ANDROID_BACKGROUND", pause)
        self.assertIn("prepared && active != null", pause)
        self.assertIn("!stopping.get()", pause)
        self.assertIn("Future<ExperimentalGlesRenderLoop.PausedState> capture", pause)
        self.assertIn("QuickResumePolicy.allowsRuntimeRestore(entry.id)", pause)
        self.assertLess(pause.index("active.pauseAndCaptureState("),
                        pause.index("lifecycle.execute("))
        self.assertLess(pause.index("currentActivePlayMillis()"),
                        pause.index("lifecycle.execute("))
        self.assertIn("lifecycle.execute(() -> commitBackgroundCapture(capture, "
                      "capturedActiveMillis));", pause)
        self.assertNotIn("saveQuickResume(false)", pause)
        self.assertNotIn("capture.get(", pause)

    def test_render_owner_captures_in_one_nonblocking_submission(self):
        capture = section(self.loop,
                          "public Future<PausedState> pauseAndCaptureState(boolean includeRuntimeState)",
                          "public void pauseAndWait()")
        self.assertIn("FutureTask<PausedState> capture = new FutureTask<>(() -> {", capture)
        self.assertEqual(1, capture.count("executor.execute(capture);"))
        self.assertLess(capture.index("executor.execute(capture);"),
                        capture.index("return capture;"))
        self.assertNotIn(".get(", capture)
        self.assertNotIn("call(()", capture)
        self.assertLess(capture.index("resumeRequested = false;"),
                        capture.index("host.pause();"))
        self.assertLess(capture.index("host.pause();"),
                        capture.index("host.readSaveRam();"))
        self.assertLess(capture.index("!surfaceAttached || awaitingRecreate"),
                        capture.index("host.readSaveRam();"))
        self.assertIn("!attachedSurface.isValid()) return null;", capture)
        self.assertLess(capture.index("host.readSaveRam();"),
                        capture.index("if (!includeRuntimeState)"))
        self.assertLess(capture.index("if (!includeRuntimeState)"),
                        capture.index("host.serialize();"))
        self.assertIn("return new PausedState(saveRam, null, failure);", capture)

    def test_background_worker_only_commits_captured_bytes(self):
        worker = section(self.session, "private void commitBackgroundCapture(",
                         "private void commitQuickResume(")
        self.assertIn("capture.get(10, TimeUnit.SECONDS)", worker)
        self.assertIn("if (snapshot == null)", worker)
        self.assertIn("persistSaveRam(snapshot.saveRam);", worker)
        self.assertLess(worker.index("persistSaveRam(snapshot.saveRam);"),
                        worker.index("if (snapshot.stateFailure != null)"))
        self.assertIn("if (snapshot.state == null) return;", worker)
        self.assertIn("commitQuickResume(snapshot.state, capturedActiveMillis, false);", worker)
        self.assertIn("Thread.currentThread().interrupt();", worker)
        for forbidden in ("renderLoop", ".serialize(", ".readSaveRam(",
                          "persistSaveRam(active)", "saveQuickResume(false)"):
            self.assertNotIn(forbidden, worker)
        disk = section(self.session, "private void persistSaveRam(byte[] value)",
                       "private synchronized void finishActiveInterval()")
        self.assertIn("DurableBlobStore.write(saveRamFile, value, MAX_SAVE_RAM_BYTES);", disk)
        self.assertNotIn("readSaveRam", disk)
        self.assertNotIn("serialize", disk)

    def test_duplicate_background_capture_latch_is_reset_on_resume(self):
        self.assertIn("private final AtomicBoolean backgroundCaptureRequested = "
                      "new AtomicBoolean(false);", self.session)
        pause = section(self.session, "@Override public void pause(PauseReason reason)",
                        "private void silenceForAudioFocusLoss()")
        self.assertEqual(1, pause.count("backgroundCaptureRequested.compareAndSet(false, true)"))
        self.assertLess(pause.index("backgroundCaptureRequested.compareAndSet(false, true)"),
                        pause.index("active.pauseAndCaptureState("))
        resume = section(self.session, "@Override public void resume()",
                         "@Override public void pause(PauseReason reason)")
        self.assertLess(resume.index("backgroundCaptureRequested.set(false);"),
                        resume.index("active.resume();"))

    def test_direct_and_automatic_checkpoint_paths_remain(self):
        direct = section(self.session, "private Throwable saveQuickResume(boolean requireCommit)",
                         "private void commitBackgroundCapture(")
        self.assertIn("persistSaveRam(active);", direct)
        self.assertIn("QuickResumePolicy.allowsRuntimeRestore(entry.id)", direct)
        self.assertIn("byte[] state = active.serialize();", direct)
        self.assertIn("commitQuickResume(state, currentActivePlayMillis(), requireCommit);", direct)
        automatic = section(self.session, "private void saveAutomatic()",
                            "private List<StateSnapshot> restorableHistory()")
        self.assertIn("checkpointPending.compareAndSet(false, true)", automatic)
        self.assertIn("persistSaveRam(active);", automatic)
        self.assertIn("QuickResumePolicy.allowsRuntimeRestore(entry.id)", automatic)
        self.assertIn("vault.saveAutomatic(identity, active.serialize(), null,", automatic)
        self.assertIn("checkpointPending.set(false);", automatic)
        commit = section(self.session, "private void commitQuickResume(",
                         "private void recordActiveProgress(")
        self.assertIn("QuickResumePolicy.shouldCopyPreviousToRecovery(state.length)", commit)
        self.assertIn("vault.saveRecovery(identity, previous.state, null,", commit)
        self.assertIn("vault.saveQuickResume(identity, state, null, capturedActiveMillis);", commit)
        self.assertIn("notifyRestoreAvailability();", commit)
        self.assertIn('"Quick Resume committed engine="', commit)
        self.assertNotIn(".serialize(", commit)
        self.assertNotIn(".readSaveRam(", commit)


if __name__ == "__main__":
    unittest.main()
