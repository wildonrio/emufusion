"""Host lifecycle/fault injection only; does not certify Android display timing."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android/src/com/thorium/preview/game"
TRANSPORT = ROOT / "unified-android/qualification-src/com/thorium/preview/game/LsfgPresentationTransport.java"
JAVA = Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")


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

    def test_actual_lsfg_constructor_rolls_back_every_partial_stage(self):
        # Compile the verbatim production constructor against fault-injected
        # platform leaves. This tests its actual cleanup/exception structure.
        constructor = TRANSPORT.read_text().split(
            "    private LsfgPresentationTransport(", 1)[1].split(
            "    @Override public Surface endpointSurface()", 1)[0]
        constructor = "    private LsfgPresentationTransport(" + constructor
        source = r'''
package com.thorium.preview.game;
class LsfgPresentationTransport {
    static int mode, readerCreated, readerClosed, nativeOpened, nativeClosed, shutdown;
    private static final Object LIFECYCLE_LOCK = new Object();
    private static LsfgPresentationTransport lifecycleOwner;
    private static SurfaceOwnershipException processCloseFailure;
    private boolean closed, retirementComplete;
    private SurfaceOwnershipException closeFailure;
    static final java.util.concurrent.CountDownLatch opening = new java.util.concurrent.CountDownLatch(1);
    static final java.util.concurrent.CountDownLatch finishOpen = new java.util.concurrent.CountDownLatch(1);
    static final int MAX_IMAGES = 8, VK_PRESENT_MODE_FIFO_KHR = 2;
    final Handler owner; final int width, height; final ImageReader reader;
    final Surface endpointSurface; final long nativeHandle;
    final Worker preparationWorker = new Worker();
    static class Worker { void shutdownNow() { assert !Thread.holdsLock(LIFECYCLE_LOCK);
        shutdown++; if(mode==10) throw new IllegalStateException("worker-shutdown"); } }
    static class Handler {}
    static class Surface {}
    static class Build { static class VERSION { static int SDK_INT = 33; } }
    static class HardwareBuffer { static final long USAGE_GPU_SAMPLED_IMAGE=1, USAGE_GPU_COLOR_OUTPUT=2; }
    static class PixelFormat { static final int RGBA_8888=1; }
    static class ImageReader {
        static ImageReader newInstance(int w,int h,int p,int m,long u) {
            assert !Thread.holdsLock(LIFECYCLE_LOCK);readerCreated++;return new ImageReader(); }
        Surface getSurface() { if(mode==5) throw new IllegalStateException("surface"); return new Surface(); }
        void setOnImageAvailableListener(Object l, Handler h) {
            if(mode==6 && l!=null) throw new IllegalStateException("listener");
            if(mode==9 && l==null) throw new IllegalStateException("detach-listener");
        }
        void close() { assert !Thread.holdsLock(LIFECYCLE_LOCK);
            readerClosed++; if(mode==8) throw new IllegalStateException("reader-close"); }
    }
    static class LsfgQualificationRuntime { static class Prepared {
        java.io.File shaderDirectory = new java.io.File("/unused-fixture");
    } }
    static class NativeLsfgBridge {
        static long open(Surface s,String d,int w,int h) {
            assert !Thread.holdsLock(LIFECYCLE_LOCK);nativeOpened++;
            if(mode==11) { opening.countDown();try{finishOpen.await();}
                catch(InterruptedException e){throw new IllegalStateException(e);} }
            return mode==1 ? 0 : 14;
        }
        static String capabilities(long h) { return "fixture"; }
        static void close(long h) { assert !Thread.holdsLock(LIFECYCLE_LOCK);assert h==14; nativeClosed++;
            if(mode==7) throw new IllegalStateException("native-close"); }
    }
    static class JSONObject {
        JSONObject(String data) { if(mode==2) throw new IllegalStateException("json"); }
        long getLong(String key) {
            if(mode==3) throw new IllegalStateException("field");
            if(key.equals("refreshDurationNs")) return 16666667;
            if(key.equals("selfTestPresentFenceOffsetNs")) return 0;
            if(key.equals("selfTestLiveCadencePresents")) return 240;
            if(key.equals("selfTestLiveCadenceGenerated")) return 120;
            return 16666667;
        }
        int getInt(String key) { return key.equals("generationCount") ? 1 : key.equals("slotCount") ? 3 : 2; }
        boolean getBoolean(String key) {
            if((mode==4 || mode>=7 && mode<=10) && key.equals("selfTestPassed")) return false;
            return !key.equals("ownedWsiImplemented") && !key.equals("liveDeviceWaitIdle") &&
                    !key.equals("liveBlockingFenceWait");
        }
    }
''' + constructor + r'''
    static LsfgPresentationTransport create()throws Exception {
        return new LsfgPresentationTransport(new Surface(),new Handler(),2,2,
                new LsfgQualificationRuntime.Prepared());
    }
    public static void main(String[] args) throws Exception {
        mode=Integer.parseInt(args[0]);
        if(mode==11) {
            java.util.concurrent.atomic.AtomicReference<Throwable> failure=new java.util.concurrent.atomic.AtomicReference<>();
            java.util.concurrent.atomic.AtomicReference<LsfgPresentationTransport> result=new java.util.concurrent.atomic.AtomicReference<>();
            Thread first=new Thread(()->{try{result.set(create());}catch(Throwable e){failure.set(e);}});
            first.start();assert opening.await(1,java.util.concurrent.TimeUnit.SECONDS);
            // The first constructor has not returned and is blocked in fake
            // native open. A second constructor must reject before allocation,
            // without waiting for that native call or acquiring its ownership.
            Thread second=new Thread(()->{
                try{create();failure.set(new AssertionError("second constructor reached native"));}
                catch(UnsupportedOperationException expected){}
                catch(Throwable e){failure.set(e);}
            });second.start();second.join(1000);assert !second.isAlive() && failure.get()==null;
            assert nativeOpened==1 && readerCreated==1 && nativeClosed==0 && shutdown==0;
            finishOpen.countDown();first.join(1000);assert !first.isAlive() && failure.get()==null;
            assert result.get()!=null && lifecycleOwner==result.get();return;
        }
        if(mode==12) {
            Build.VERSION.SDK_INT=32;
            try{create();throw new AssertionError();}
            catch(UnsupportedOperationException expected){
                assert shutdown==1 && readerCreated==0 && readerClosed==0 && nativeOpened==0;
                assert lifecycleOwner==null && processCloseFailure==null;
            }return;
        }
        if(mode==0) {
            LsfgPresentationTransport valid=create();assert lifecycleOwner==valid;
            assert valid.nativeHandle==14 && readerClosed==0 && nativeClosed==0 && shutdown==0;return;
        }
        try {create();throw new AssertionError("partial constructor escaped");}
        catch(Exception expected) {
            assert readerClosed==(mode==7 ? 0 : 1) && shutdown==1 : "reader/worker mode="+mode;
            assert nativeClosed==(mode==1 || mode==5 || mode==6 ? 0 : 1) : "native leak";
            if(mode>=7) {
                assert SurfaceOwnershipException.isUnsafe(expected);
                assert expected.getCause().getSuppressed().length==1;
                assert processCloseFailure==expected && lifecycleOwner!=null;
                assert lifecycleOwner.closeFailure==expected && lifecycleOwner.closed;
                assert lifecycleOwner.reader!=null && lifecycleOwner.preparationWorker!=null;
                int opens=nativeOpened, creates=readerCreated, shutdowns=shutdown;
                try{create();throw new AssertionError("poisoned process readmitted");}
                catch(SurfaceOwnershipException same){assert same==expected;}
                assert opens==nativeOpened && creates==readerCreated && shutdowns==shutdown;
            } else {
                assert !SurfaceOwnershipException.isUnsafe(expected);
                assert lifecycleOwner==null && processCloseFailure==null;
                mode=0;LsfgPresentationTransport valid=create();assert lifecycleOwner==valid;
            }
        }
    }
}
'''
        self.compile_run("LsfgPresentationTransport", source, tuple((str(mode),) for mode in range(13)))
        production = TRANSPORT.read_text()
        open_body = production.split("static LsfgPresentationTransport open(", 1)[1].split(
            "private LsfgPresentationTransport(", 1)[0]
        self.assertLess(open_body.index("requireLifecycleAdmissionAvailable();"),
                        open_body.index("LsfgQualificationRuntime.open(context)"))

    def test_output_quarantine_precedes_all_primary_direct_handoffs(self):
        source = (GAME / "GameSurfaceView.java").read_text()
        self.assertIn("if (quarantinedSurfaceGeneration == surfaceGeneration) return;", source)
        finish = source.split("private void finishGeneratorStartup(", 1)[1].split(
            "@Override public void surfaceDestroyed", 1)[0]
        self.assertLess(finish.index("SurfaceOwnershipException.isUnsafe(problem)"),
                        finish.index("engineSurface = output;"))
        self.assertIn("listener.onSurfaceStartupError(", finish)
        self.assertIn("retireFailedGenerator(failure);", source)
        self.assertEqual(source.count("if (SurfaceOwnershipException.isUnsafe(failure)) throw failure;"), 2)
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
