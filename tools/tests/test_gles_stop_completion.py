"""Execute the real GLES stop methods against a manually acknowledged native close."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java"
JAVA = Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")


def java_method(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    masked = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                    lambda match: " " * len(match.group()), source, flags=re.DOTALL)
    depth = 0
    for end in range(opening, len(source)):
        depth += (masked[end] == "{") - (masked[end] == "}")
        if not depth:
            return source[start:end + 1]
    raise AssertionError("Unclosed Java method: " + signature)


HARNESS = r'''
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import com.thorium.lucent.state.QuickResumePolicy;

interface EngineSession {
    enum StopReason { EXIT_TO_LUCENT, ACTIVITY_DESTROYED }
    interface Completion { void complete(); }
    interface Listener { void onSessionStopRejected(String message, Throwable failure); }
    void stop(StopReason reason, Completion completion);
    void release();
}
final class ManualExecutor {
    final ArrayDeque<Runnable> queue = new ArrayDeque<>();
    void execute(Runnable action) { queue.add(action); }
    void drain() { while (!queue.isEmpty()) queue.remove().run(); }
    void shutdown() {}
}
final class ExperimentalGlesRenderLoop {
    final List<Runnable> callbacks = new ArrayList<>();
    boolean pauseFailure, registrationFailure, closed;
    int closeRequests;
    void pauseAndWait() {
        if (pauseFailure) throw new IllegalStateException("pause timed out");
    }
    void closeWhenComplete(Runnable callback) {
        closeRequests++;
        if (registrationFailure) throw new IllegalStateException("close not scheduled");
        if (closed) callback.run();
        else callbacks.add(callback);
    }
    void acknowledge() {
        closed = true;
        for (Runnable callback : new ArrayList<>(callbacks)) callback.run();
    }
}
final class Log { static void e(String tag, String text, Throwable failure) {} }
final class AudioFocus { void abandon() {} }
public class PpssppGlesEngineSession implements EngineSession {
    static final String TAG = "test";
    static final class Entry { String id = "dolphin"; }
    final Entry entry = new Entry();
    final ManualExecutor lifecycle = new ManualExecutor();
    final AudioFocus audioFocus = new AudioFocus();
    ExperimentalGlesRenderLoop renderLoop = new ExperimentalGlesRenderLoop();
    boolean resumeRequested = true, prepared = true, audioFailure, saveThrows;
    Throwable saveFailure;
    int rejected, audioReleases;
    Listener listener = (message, failure) -> rejected++;
    Throwable saveQuickResume(boolean finalStop) {
        if (saveThrows) throw new IllegalStateException("save threw");
        return saveFailure;
    }
    void finishActiveInterval() {}
    // This harness isolates native close acknowledgement; stylus dispatch is
    // covered by the phone-input tests, not modeled as a native owner here.
    void releasePhoneStylus() {}
    void detachSecondaryBeforeBlank(ExperimentalGlesRenderLoop loop) {}
    void releaseAudio() {
        audioReleases++;
        if (audioFailure) throw new IllegalStateException("audio release failed");
    }
    // ACTUAL_FIELDS
    // ACTUAL_METHODS
    static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    static void duplicateStopWaitsForNativeReturn() {
        PpssppGlesEngineSession session = new PpssppGlesEngineSession();
        ExperimentalGlesRenderLoop loop = session.renderLoop;
        int[] completed = {0};
        session.stop(StopReason.EXIT_TO_LUCENT, () -> completed[0]++);
        session.stop(StopReason.ACTIVITY_DESTROYED, () -> completed[0]++);
        check(completed[0] == 0, "duplicate stop completed before lifecycle task");
        session.lifecycle.drain();
        check(completed[0] == 0 && loop.closeRequests == 1 && session.renderLoop == loop,
                "stop completed before actual native close acknowledgement");
        session.stop(StopReason.ACTIVITY_DESTROYED, () -> completed[0]++);
        check(completed[0] == 0, "late duplicate bypassed pending native close");
        loop.acknowledge();
        loop.acknowledge();
        check(completed[0] == 3 && session.renderLoop == null && !session.prepared,
                "actual native return lost or duplicated completion");
        session.stop(StopReason.ACTIVITY_DESTROYED, () -> completed[0]++);
        check(completed[0] == 4 && loop.closeRequests == 1, "completed stop was restarted");
    }
    static void rejectedSaveRemainsPlayableAndRetryDoesNotCompleteRejectedCallbacks() {
        PpssppGlesEngineSession session = new PpssppGlesEngineSession();
        ExperimentalGlesRenderLoop loop = session.renderLoop;
        int[] rejectedCallbacks = {0}, retried = {0};
        session.saveFailure = new IllegalStateException("disk commit rejected");
        session.listener = (message, failure) -> {
            session.rejected++;
            throw new IllegalStateException("UI callback rejected");
        };
        session.stop(StopReason.EXIT_TO_LUCENT, () -> rejectedCallbacks[0]++);
        session.stop(StopReason.EXIT_TO_LUCENT, () -> rejectedCallbacks[0]++);
        session.lifecycle.drain();
        check(session.rejected == 1 && !session.stopping.get() && session.prepared &&
                session.renderLoop == loop && loop.closeRequests == 0 && rejectedCallbacks[0] == 0,
                "save rejection closed or completed the retained session");
        session.saveFailure = null;
        session.stop(StopReason.EXIT_TO_LUCENT, () -> retried[0]++);
        session.lifecycle.drain();
        check(retried[0] == 0, "retry completed before native close");
        loop.acknowledge();
        check(retried[0] == 1 && rejectedCallbacks[0] == 0,
                "retry revived callbacks from a rejected normal Exit");
    }
    static void pendingDestroyUpgradesSaveRejection() {
        PpssppGlesEngineSession session = new PpssppGlesEngineSession();
        ExperimentalGlesRenderLoop loop = session.renderLoop;
        session.saveFailure = new IllegalStateException("disk commit rejected");
        int[] completed = {0};
        session.stop(StopReason.EXIT_TO_LUCENT, () -> completed[0]++);
        session.stop(StopReason.ACTIVITY_DESTROYED, () -> completed[0]++);
        session.lifecycle.drain();
        check(session.rejected == 0 && loop.closeRequests == 1 && completed[0] == 0,
                "destroy either bypassed native close or was stranded by save rejection");
        loop.acknowledge();
        check(completed[0] == 2, "destroy upgrade lost stop completions");
    }
    static void errorsStillWaitForNativeClose() {
        for (int mode = 0; mode < 3; mode++) {
            PpssppGlesEngineSession session = new PpssppGlesEngineSession();
            ExperimentalGlesRenderLoop loop = session.renderLoop;
            loop.pauseFailure = mode == 0;
            session.audioFailure = mode == 1;
            loop.registrationFailure = mode == 2;
            int[] completed = {0};
            session.stop(StopReason.ACTIVITY_DESTROYED, () -> completed[0]++);
            session.lifecycle.drain();
            session.stop(StopReason.ACTIVITY_DESTROYED, () -> completed[0]++);
            check(completed[0] == 0 && session.renderLoop == loop && loop.closeRequests == 1,
                    "error path falsely acknowledged native close mode=" + mode);
            if (mode != 2) {
                loop.acknowledge();
                check(completed[0] == 2, "late real close did not finish error path");
            }
        }
    }
    static void callbackFailureCannotLoseOtherWaiters() {
        PpssppGlesEngineSession session = new PpssppGlesEngineSession();
        ExperimentalGlesRenderLoop loop = session.renderLoop;
        int[] completed = {0};
        session.stop(StopReason.ACTIVITY_DESTROYED, () -> { throw new RuntimeException("callback"); });
        session.stop(StopReason.ACTIVITY_DESTROYED, () -> completed[0]++);
        session.lifecycle.drain();
        loop.acknowledge();
        check(completed[0] == 1, "one callback failure lost another native-close waiter");
    }
    static void noNativeOwnerStillRequiresLifecycleTurn() {
        PpssppGlesEngineSession session = new PpssppGlesEngineSession();
        session.renderLoop = null;
        int[] completed = {0};
        session.stop(StopReason.ACTIVITY_DESTROYED, () -> completed[0]++);
        check(completed[0] == 0, "empty owner completed before stop task");
        session.lifecycle.drain();
        check(completed[0] == 1, "empty owner never completed");
    }
    static void releaseWithoutStopAndDuplicatesWaitForNativeReturn() {
        PpssppGlesEngineSession session = new PpssppGlesEngineSession();
        ExperimentalGlesRenderLoop loop = session.renderLoop;
        int[] completed = {0};
        session.release(); // Legacy callers still start asynchronous retirement.
        session.releaseWhenComplete(() -> completed[0]++);
        session.releaseWhenComplete(() -> completed[0]++);
        check(completed[0] == 0, "duplicate release acknowledged before cleanup ran");
        session.lifecycle.drain();
        session.releaseWhenComplete(() -> completed[0]++);
        check(completed[0] == 0 && loop.closeRequests == 1 && session.renderLoop == loop,
                "release-return bypassed actual native closure");
        loop.acknowledge();
        loop.acknowledge();
        check(completed[0] == 3 && session.renderLoop == null && !session.prepared,
                "late actual release lost or duplicated acknowledgements");
        session.releaseWhenComplete(() -> completed[0]++);
        check(completed[0] == 4 && loop.closeRequests == 1,
                "completed release restarted native destruction");
    }
    static void releaseErrorsCannotFakeNativeCompletion() {
        for (int mode = 0; mode < 3; mode++) {
            PpssppGlesEngineSession session = new PpssppGlesEngineSession();
            ExperimentalGlesRenderLoop loop = session.renderLoop;
            session.saveThrows = mode == 0;
            session.audioFailure = mode == 1;
            loop.registrationFailure = mode == 2;
            int[] completed = {0};
            session.releaseWhenComplete(() -> completed[0]++);
            session.lifecycle.drain();
            session.releaseWhenComplete(() -> completed[0]++);
            check(completed[0] == 0 && loop.closeRequests == 1 && session.renderLoop == loop,
                    "release error acknowledged native closure mode=" + mode);
            if (mode != 2) {
                loop.acknowledge();
                check(completed[0] == 2, "real close did not complete release after cleanup error");
            }
        }
    }
    static void stopThenReleaseSharesRealNativeAcknowledgement() {
        for (boolean releaseAfterClose : new boolean[] {false, true}) {
            PpssppGlesEngineSession session = new PpssppGlesEngineSession();
            ExperimentalGlesRenderLoop loop = session.renderLoop;
            int[] stopped = {0}, released = {0};
            session.stop(StopReason.ACTIVITY_DESTROYED, () -> stopped[0]++);
            session.lifecycle.drain();
            if (releaseAfterClose) loop.acknowledge();
            session.releaseWhenComplete(() -> released[0]++);
            session.lifecycle.drain();
            if (!releaseAfterClose) {
                check(stopped[0] == 0 && released[0] == 0,
                        "stop/release completed while native close remained pending");
                loop.acknowledge();
            }
            check(stopped[0] == 1 && released[0] == 1 && session.renderLoop == null,
                    "stop to release lost native-close acknowledgement");
        }
    }
    static void emptyReleaseAndFailingCallbackAreSafe() {
        PpssppGlesEngineSession session = new PpssppGlesEngineSession();
        session.renderLoop = null;
        int[] completed = {0};
        session.releaseWhenComplete(() -> { throw new IllegalStateException("callback"); });
        session.releaseWhenComplete(() -> completed[0]++);
        check(completed[0] == 0, "release was not asynchronous");
        session.lifecycle.drain();
        check(completed[0] == 1, "empty release or callback error lost another waiter");
    }
    public static void main(String[] args) {
        duplicateStopWaitsForNativeReturn();
        rejectedSaveRemainsPlayableAndRetryDoesNotCompleteRejectedCallbacks();
        pendingDestroyUpgradesSaveRejection();
        errorsStillWaitForNativeClose();
        callbackFailureCannotLoseOtherWaiters();
        noNativeOwnerStillRequiresLifecycleTurn();
        releaseWithoutStopAndDuplicatesWaitForNativeReturn();
        releaseErrorsCannotFakeNativeCompletion();
        stopThenReleaseSharesRealNativeAcknowledgement();
        emptyReleaseAndFailingCallbackAreSafe();
        System.out.println("Real GLES stop/release methods: ten close-acknowledgement scenarios passed");
    }
}
'''


class GlesStopCompletionTest(unittest.TestCase):
    def test_real_render_loop_close_acknowledgement(self):
        project = ROOT / "unified-android"
        sources = [project / path for path in (
            "native/tests/java/android/view/Surface.java",
            "native/tests/java/android/util/Log.java",
            "native/tests/java/android/os/Build.java",
            "src/com/thorium/lucent/video/NativeSourceImageProvider.java",
            "src/com/thorium/lucent/video/RuntimePresentationFailure.java",
            "src/com/thorium/preview/game/FrameGenerationRenderer.java",
            "src/com/thorium/preview/game/FrameGenerationRendererRegistry.java",
            "src/com/thorium/lucent/timing/DisplaySyncPolicy.java",
            "src/com/thorium/preview/LibretroHost.java",
            "src/com/thorium/preview/PendingHostInput.java",
            "src/com/thorium/preview/ExperimentalGlesLibretroHost.java",
            "src/com/thorium/preview/ExperimentalVulkanLibretroHost.java",
            "src/com/thorium/preview/ExperimentalGlesRenderLoop.java",
            "native/tests/java/com/thorium/preview/ExperimentalGlesRenderLoopTest.java")]
        with tempfile.TemporaryDirectory(prefix="lucent-gles-close-") as temporary:
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", temporary,
                                       *map(str, sources)], capture_output=True, text=True)
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(JAVA / "java"), "-cp", temporary,
                                  "com.thorium.preview.ExperimentalGlesRenderLoopTest"],
                                 capture_output=True, text=True, timeout=20)
            self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
            self.assertIn("dedicated render-loop probe passed", ran.stdout)

    def test_real_stop_methods_wait_for_actual_native_completion(self):
        source = SESSION.read_text(encoding="utf-8")
        methods = [java_method(source, signature) for signature in (
            "@Override public void stop(StopReason reason, Completion completion)",
            "private void closeForStop(", "private void completeStop(",
            "@Override public void release()", "public void releaseWhenComplete(",
            "private void completeRelease(")]
        fields = []
        for name in ("stopping", "stopLock", "stopCompletions", "stopCompleted",
                     "destroyStopRequested", "released", "releaseLock",
                     "releaseCompletions", "releaseCompleted"):
            match = re.search(r"^    private [^\n;]*\b" + name + r"\b[^\n;]*;", source, re.M)
            self.assertIsNotNone(match, name)
            fields.append(match.group())
        harness = HARNESS.replace("// ACTUAL_FIELDS", "\n".join(fields))
        harness = harness.replace("// ACTUAL_METHODS", "\n".join(methods))
        with tempfile.TemporaryDirectory(prefix="lucent-gles-stop-") as temporary:
            target = Path(temporary) / "PpssppGlesEngineSession.java"
            target.write_text(harness, encoding="utf-8")
            policy = ROOT / "unified-android/src/com/thorium/lucent/state/QuickResumePolicy.java"
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", temporary,
                                       str(policy), str(target)], capture_output=True, text=True)
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(JAVA / "java"), "-cp", temporary,
                                  "PpssppGlesEngineSession"], capture_output=True, text=True,
                                 timeout=15)
            self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
            self.assertIn("ten close-acknowledgement scenarios passed", ran.stdout)


if __name__ == "__main__":
    unittest.main()
