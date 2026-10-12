"""Host lifecycle/fault injection only; does not certify Android display timing."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android/src/com/thorium/preview/game"
TRANSPORT = ROOT / "unified-android/qualification-src/com/thorium/preview/game/LsfgPresentationTransport.java"
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


class FramegenStartupLifecycleTest(unittest.TestCase):
    def compile_run(self, name, source, scenarios=((),)):
        javac = str(JAVA / "javac") if JAVA.exists() else shutil.which("javac")
        java = str(JAVA / "java") if JAVA.exists() else shutil.which("java")
        self.assertIsNotNone(javac)
        with tempfile.TemporaryDirectory(prefix="framegen-startup-lifecycle-") as temporary:
            directory = Path(temporary)
            fixture = directory / (name + ".java")
            fixture.write_text(source)
            command = [javac, "--release", "8", "-d", str(directory),
                       str(GAME / "SurfaceOwnershipException.java"),
                       str(GAME / "SurfaceRetirement.java"), str(fixture)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for scenario in scenarios:
                with self.subTest(scenario=scenario):
                    result = subprocess.run([java, "-ea", "-cp", str(directory),
                                             "com.thorium.preview.game." + name, *scenario],
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_serial_owner_retirement_never_confuses_cancel_or_timeout_with_release(self):
        self.compile_run("RetirementTest", r'''
package com.thorium.preview.game;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
public class RetirementTest {
    public static void main(String[] args) throws Exception {
        SurfaceRetirement retirement = new SurfaceRetirement();
        ExecutorService owner = Executors.newSingleThreadExecutor();
        CountDownLatch entered = new CountDownLatch(1), releaseNative = new CountDownLatch(1);
        AtomicBoolean outputOwned = new AtomicBoolean(), cancelled = new AtomicBoolean();
        AtomicBoolean renderedAfterCancel = new AtomicBoolean();
        RuntimeException original = new IllegalStateException("original startup timeout");
        owner.submit(() -> {
            outputOwned.set(true); entered.countDown();
            try { releaseNative.await(); } catch (InterruptedException e) { throw new RuntimeException(e); }
            if (!cancelled.get()) renderedAfterCancel.set(true);
        });
        assert entered.await(1, TimeUnit.SECONDS);
        cancelled.set(true);
        owner.submit(() -> { outputOwned.set(false); retirement.complete(null); });
        try { retirement.await(1, original); throw new AssertionError("unsafe Direct handoff"); }
        catch (SurfaceOwnershipException expected) {
            assert expected.getCause() == original;
            assert outputOwned.get();
        }
        releaseNative.countDown();
        retirement.await(1000, original);
        assert !outputOwned.get() && !renderedAfterCancel.get();
        owner.shutdown(); assert owner.awaitTermination(1, TimeUnit.SECONDS);
        retirement.await(0, null); // Repeated close still checks the same completion.
        SurfaceRetirement broken = new SurfaceRetirement();
        RuntimeException cleanup = new IllegalStateException("cleanup failure");
        broken.complete(cleanup);
        try { broken.await(0, original); throw new AssertionError(); }
        catch (SurfaceOwnershipException expected) {
            assert expected.getCause() == original;
            assert original.getSuppressed()[0] == cleanup;
        }
        assert SurfaceOwnershipException.isUnsafe(new IllegalStateException("wrapper",
                new SurfaceOwnershipException("unsafe", original)));
        RuntimeException suppressed = new RuntimeException();
        suppressed.addSuppressed(new SurfaceOwnershipException("unsafe", null));
        assert SurfaceOwnershipException.isUnsafe(suppressed);
        assert !SurfaceOwnershipException.isUnsafe(new IllegalStateException("ordinary failure"));
        Thread.currentThread().interrupt();
        try { new SurfaceRetirement().await(1, null); throw new AssertionError(); }
        catch (SurfaceOwnershipException expected) { assert Thread.interrupted(); }
    }
}
''')

    def test_output_quarantine_precedes_all_primary_direct_handoffs(self):
        source = (GAME / "GameSurfaceView.java").read_text()
        self.assertIn("if (quarantinedSurfaceGeneration == surfaceGeneration) return;", source)
        finish = source.split("private void finishGeneratorStartup(", 1)[1].split(
            "@Override public void surfaceDestroyed", 1)[0]
        self.assertLess(finish.index("SurfaceOwnershipException.isUnsafe(problem)"),
                        finish.index("engineSurface = output;"))
        self.assertIn("listener.onSurfaceStartupError(", finish)
        self.assertIn("retireFailedGenerator(failure);", source)
        self.assertEqual(source.count("if (SurfaceOwnershipException.isUnsafe(failure)) throw failure;"), 1)
        legacy = (GAME / "GameSurface.java").read_text()
        self.assertIn("if (quarantinedTexture == texture) return;", legacy)
        catch = legacy.split("} catch (RuntimeException failure) {", 1)[1].split(
            "private void requestDirectFrameRate", 1)[0]
        self.assertLess(catch.index("SurfaceOwnershipException.isUnsafe(failure)"),
                        catch.index("renderSurface = outputSurface;"))
        self.assertIn("partial.close();", catch)
        host = (GAME / "InWindowGameHost.java").read_text()
        error = host.split("onSurfaceStartupError(String", 1)[1].split(
            "private void detachCurrentSurface", 1)[0]
        self.assertIn("removeCallbacks(revealLaunchSpinner)", error)
        self.assertIn("launchSpinner.setVisibility(View.GONE)", error)
        self.assertIn("showFatalError(message)", error)
        self.assertNotIn("dismissLaunchCurtain()", error)

    def test_renderer_cancellation_retires_once_after_the_initializer_on_its_owner(self):
        source = (GAME / "DisplayFrameGenerator.java").read_text()
        constructor = source.split("handler.post(this::initialize);", 1)[1].split(
            "FrameGenerationRendererRegistry.register(this)", 1)[0]
        self.assertEqual(constructor.count("closeAfterStartupFailure(failure);"), 4)
        close = source.split("private void closeAfterStartupFailure(", 1)[1].split(
            "private void initialize()", 1)[0]
        self.assertIn("closed.compareAndSet(false, true)", close)
        self.assertIn("if (!handler.post(() -> {", close)
        self.assertIn("try { releaseGl(); }", close)
        self.assertIn("surfaceRetirement.complete(cleanupFailure);", close)
        self.assertIn("surfaceRetirement.await(timeoutMs, originalFailure);", close)
        self.assertLess(close.index("releaseGl();"), close.index("surfaceRetirement.complete(cleanupFailure);"))
        initialize = source.split("private void initialize()", 1)[1].split(
            "private void throwIfStartupCancelled()", 1)[0]
        self.assertEqual(initialize.count("throwIfStartupCancelled();"), 5)
        self.assertNotIn("releaseGl();", initialize)  # One serialized retirement only.
        host = (GAME / "InWindowGameHost.java").read_text()
        fatal = host.split("private void showFatalError(String message)", 1)[1].split(
            "private void explainUnavailable", 1)[0]
        self.assertIn("removeCallbacks(revealLaunchSpinner)", fatal)
        self.assertIn("root.removeView(failedSpinner)", fatal)
        self.assertIn("root.removeView(failedCurtain)", fatal)


if __name__ == "__main__":
    unittest.main()
