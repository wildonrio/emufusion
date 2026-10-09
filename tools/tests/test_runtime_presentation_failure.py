"""Execute actual error latch/UI guard bodies; no Android or device qualification."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / "unified-android/src/com/thorium/preview/game"
VIDEO = ROOT / "unified-android/src/com/thorium/lucent/video"
PREVIEW = ROOT / "android-companion/src/com/thorium/preview/PreviewActivity.java"
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


def method(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class RuntimePresentationFailureTest(unittest.TestCase):
    def compile_run(self, source):
        with tempfile.TemporaryDirectory(prefix="runtime-display-error-") as temporary:
            output = Path(temporary)
            fixture = output / "RuntimeFailureTest.java"
            fixture.write_text(source)
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", str(output),
                                       str(VIDEO / "RuntimePresentationFailure.java"), str(fixture)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(JAVA / "java"), "-ea", "-cp", str(output), "RuntimeFailureTest"],
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)

    def test_actual_latch_once_late_listener_close_race_and_no_monitor_callback(self):
        self.compile_run(r'''
import com.thorium.lucent.video.RuntimePresentationFailure;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
public class RuntimeFailureTest {
    public static void main(String[] args) throws Exception {
        RuntimePresentationFailure latch = new RuntimePresentationFailure();
        Throwable original = new IllegalStateException("driver failure");
        AtomicInteger calls = new AtomicInteger();
        latch.report("display stopped", original); // renderer can fail before owner listener binds
        latch.setListener((message, cause) -> {
            assert !Thread.holdsLock(latch);
            assert message.equals("display stopped");
            assert cause instanceof RuntimePresentationFailure.Failure && cause.getCause() == original;
            calls.incrementAndGet();
            latch.report("reentrant", null); // no duplicate/reentrant callback
            latch.setListener((m,c) -> {throw new AssertionError("second delivery");});
        });
        latch.report("another failure", null);
        assert calls.get() == 1;
        RuntimePresentationFailure closed = new RuntimePresentationFailure();
        closed.report("pending", null); closed.close();
        closed.setListener((m,c) -> {throw new AssertionError("closed owner notified");});
        closed.report("after close", null);
        RuntimePresentationFailure raced = new RuntimePresentationFailure();
        AtomicInteger won = new AtomicInteger();
        raced.setListener((m,c) -> {assert !Thread.holdsLock(raced); won.incrementAndGet();});
        ExecutorService pool = Executors.newFixedThreadPool(4);
        for (int n=0; n<64; ++n) pool.execute(() -> raced.report("failure", null));
        pool.shutdown(); assert pool.awaitTermination(2, TimeUnit.SECONDS);
        assert won.get() == 1;
        RuntimePresentationFailure throwsOnce = new RuntimePresentationFailure();
        throwsOnce.setListener((m,c) -> {throw new IllegalStateException("owner callback");});
        try {throwsOnce.report("fatal", original); throw new AssertionError();}
        catch(IllegalStateException expected) {assert expected.getMessage().equals("owner callback");}
        throwsOnce.setListener((m,c) -> {throw new AssertionError("redelivered callback exception");});
    }
}
''')

    def test_actual_primary_secondary_generation_guards_and_owner_pause(self):
        view = method((GAME / "GameSurfaceView.java").read_text(), "    private void bindRuntimeErrorListener(")
        legacy = method((GAME / "GameSurface.java").read_text(), "    private void bindRuntimeErrorListener(")
        secondary = method(PREVIEW.read_text(), "    private void bindGameplayRuntimeErrorListener(")
        host = method((GAME / "InWindowGameHost.java").read_text(), "public void onSurfaceRuntimeError(")
        self.compile_run(r'''
import com.thorium.lucent.video.RuntimePresentationFailure;
import java.util.*;
import java.util.concurrent.atomic.*;
public class RuntimeFailureTest {
    static class Ui {
        final ArrayDeque<Runnable> queued=new ArrayDeque<>();
        boolean post(Runnable work){queued.add(work);return true;}
        void runOnUiThread(Runnable work){post(work);}
        void flush(){while(!queued.isEmpty()) queued.remove().run();}
    }
    static class FrameGenerationRenderer {
        final RuntimePresentationFailure failure=new RuntimePresentationFailure();
        int closes;
        void setRuntimeErrorListener(RuntimePresentationFailure.Listener value){failure.setListener(value);}
        void fail(){failure.report("display stopped", new IllegalStateException("driver"));}
        void close(){closes++;}
    }
    static class GameSurface {interface Listener {void onSurfaceRuntimeError(String m,Throwable c);}}
    static class Owner implements GameSurface.Listener, Legacy.Listener {
        int calls; public void onSurfaceRuntimeError(String m,Throwable c){calls++;}
    }
    static class Primary {
        Ui mainHandler=new Ui(); boolean surfaceLive=true;
        boolean runtimePresentationFailed;
        int surfaceGeneration=1,quarantinedSurfaceGeneration=-1;
        FrameGenerationRenderer frameGenerator=new FrameGenerationRenderer();
        GameSurface.Listener listener=new Owner();
''' + view + r'''
    }
    static class Legacy {
        interface Listener extends GameSurface.Listener {}
        Ui ui=new Ui(); int surfaceGeneration=1,runtimeFailedGeneration=-1;
        boolean runtimePresentationFailed;
        Object texture=new Object(),quarantinedTexture;
        FrameGenerationRenderer frameGenerator=new FrameGenerationRenderer();
        Listener listener=new Owner();
        boolean post(Runnable work){return ui.post(work);}
        Object getSurfaceTexture(){return texture;}
''' + legacy + r'''
    }
    static class Log {static void e(String a,String b,Throwable c){}}
    static class SecondaryGameplaySurfaceRouter {
        static int calls; static long generation=1;
        static void surfaceFailed(long g,Throwable c){if(g==generation) calls++;}
    }
    static class Secondary {
        Ui ui=new Ui(); long gameplayGeneration=1,gameplayGeneratorGeneration=1,gameplayQuarantinedGeneration=-1;
        FrameGenerationRenderer gameplayFrameGenerator=new FrameGenerationRenderer();
        void runOnUiThread(Runnable work){ui.post(work);}
''' + secondary + r'''
    }
    static class EngineSession {
        enum PauseReason {ANDROID_BACKGROUND}
        int pauses; boolean throwsPause;
        void pause(PauseReason reason){pauses++;if(throwsPause)throw new IllegalStateException("pause");}
    }
    static class Host {
        static final String TAG="fixture";
        Ui activity=new Ui(); boolean libraryReturned,fatalErrorVisible;
        boolean prepared=true,surfaceAvailable=true;
        AtomicBoolean exitStarted=new AtomicBoolean();
        EngineSession session=new EngineSession(); int fatalCalls;
        boolean presentationRecoveryPending;
        boolean tryStartRuntimeDirectRecovery(String m,Throwable c){return false;}
        void updateGameplayScreenOn(){}
        void showFatalError(String message,boolean runtime){assert runtime;fatalErrorVisible=true;fatalCalls++;}
''' + host + r'''
    }
    public static void main(String[] args) {
        Primary p=new Primary(); FrameGenerationRenderer renderer=p.frameGenerator; Owner owner=(Owner)p.listener;
        p.bindRuntimeErrorListener(1); renderer.fail();
        assert owner.calls==0; // callback marshalled to UI, not renderer owner
        p.mainHandler.flush(); assert owner.calls==1 && p.quarantinedSurfaceGeneration==1;
        assert p.runtimePresentationFailed;
        assert p.frameGenerator==renderer && renderer.closes==0; // normal retirement retains ownership
        renderer.fail(); p.mainHandler.flush(); assert owner.calls==1;
        for(int stale=0;stale<4;stale++) {
            p=new Primary();owner=(Owner)p.listener;p.bindRuntimeErrorListener(1);p.frameGenerator.fail();
            if(stale==0)p.surfaceGeneration++;
            if(stale==1)p.frameGenerator=new FrameGenerationRenderer();
            if(stale==2)p.listener=new Owner();
            if(stale==3)p.surfaceLive=false;
            p.mainHandler.flush();assert owner.calls==0;
        }
        Legacy l=new Legacy();owner=(Owner)l.listener;renderer=l.frameGenerator;
        l.bindRuntimeErrorListener();renderer.fail();l.ui.flush();
        assert owner.calls==1 && l.runtimeFailedGeneration==1 && l.quarantinedTexture==l.texture;
        assert l.runtimePresentationFailed;
        assert l.frameGenerator==renderer && renderer.closes==0;
        l=new Legacy();owner=(Owner)l.listener;l.bindRuntimeErrorListener();l.frameGenerator.fail();
        l.surfaceGeneration++;l.ui.flush();assert owner.calls==0;
        Secondary s=new Secondary();renderer=s.gameplayFrameGenerator;
        s.bindGameplayRuntimeErrorListener(renderer,1);renderer.fail();assert SecondaryGameplaySurfaceRouter.calls==0;
        s.ui.flush();assert SecondaryGameplaySurfaceRouter.calls==1 && s.gameplayQuarantinedGeneration==1;
        assert renderer.closes==0 && s.gameplayFrameGenerator==renderer;
        s=new Secondary();s.bindGameplayRuntimeErrorListener(s.gameplayFrameGenerator,1);s.gameplayFrameGenerator.fail();
        s.gameplayGeneration=2;s.ui.flush();assert SecondaryGameplaySurfaceRouter.calls==1;
        s=new Secondary();s.bindGameplayRuntimeErrorListener(s.gameplayFrameGenerator,1);s.gameplayFrameGenerator.fail();
        s.gameplayFrameGenerator=new FrameGenerationRenderer();s.ui.flush();assert SecondaryGameplaySurfaceRouter.calls==1;
        Host h=new Host();h.onSurfaceRuntimeError("display stopped",null);h.onSurfaceRuntimeError("duplicate",null);
        assert h.session.pauses==0;h.activity.flush();
        assert h.session.pauses==1 && h.fatalCalls==1 && !h.prepared && !h.surfaceAvailable;
        h=new Host();h.session.throwsPause=true;h.onSurfaceRuntimeError("display stopped",null);h.activity.flush();
        assert h.fatalCalls==1 && !h.prepared; // pause failure still reaches UI and blocks resume
        h=new Host();h.libraryReturned=true;h.onSurfaceRuntimeError("old game",null);h.activity.flush();
        assert h.fatalCalls==0 && h.session.pauses==0;
    }
}
''')

    def test_actual_surface_callbacks_cannot_restart_a_failed_game_after_sleep(self):
        view = (GAME / "GameSurfaceView.java").read_text()
        legacy = (GAME / "GameSurface.java").read_text()
        primary_changed = method(view, "public void surfaceChanged(")
        primary_listener = method(view, "    public void setListener(")
        legacy_available = method(legacy, "public void onSurfaceTextureAvailable(")
        legacy_changed = method(legacy, "public void onSurfaceTextureSizeChanged(")
        legacy_listener = method(legacy, "    public void setListener(")
        # Run the production entrypoints against Android leaves that count any
        # allocation/bind/resize. Generation changes model sleep/wake; only a new
        # game view is allowed to recover from an already-delivered fatal error.
        self.compile_run(r'''
public class RuntimeFailureTest {
    static class Surface { boolean isValid(){return true;} }
    static class SurfaceTexture {}
    static class SurfaceHolder { Surface getSurface(){return new Surface();} }
    static class FrameGenerationSettings { enum Mode {OFF, LSFG} }
    static class FrameGenerationRenderer {int resizes; void resize(int a,int b,int c,int d,float e){resizes++;}}
    static class GameSurface {
        interface Listener {
            void onSurfaceAvailable(Surface s,int w,int h);
            void onSurfaceSizeChanged(int w,int h);
        }
    }
    static class Owner implements GameSurface.Listener {
        int available,resized;
        public void onSurfaceAvailable(Surface s,int w,int h){available++;}
        public void onSurfaceSizeChanged(int w,int h){resized++;}
    }
    static class Log {static void i(String a,String b){}}
    static class Primary {
        static final String TAG="fixture";
        boolean runtimePresentationFailed,surfaceLive,generatorStartupPending,startupFellBackToDirect;
        int surfaceGeneration=1,quarantinedSurfaceGeneration=-1,pendingWidth,pendingHeight;
        int starts,creates,binds; float lastReportedPanelHz;
        Surface engineSurface; FrameGenerationRenderer frameGenerator;
        GameSurface.Listener listener;
        FrameGenerationSettings.Mode launchMode=FrameGenerationSettings.Mode.LSFG;
        int getWidth(){return 1920;} int getHeight(){return 1080;}
        float rendererRefreshRate(){return 120f;}
        void bindRuntimeErrorListener(int generation){binds++;}
        void startGeneratorAsync(Surface s,int w,int h){starts++;}
        void createGenerator(Surface s,int w,int h){creates++;engineSurface=s;}
        void propagatePanelRefresh(String reason){}
''' + primary_changed + primary_listener + r'''
    }
    static class Legacy {
        interface Listener extends GameSurface.Listener {}
        boolean runtimePresentationFailed;
        int surfaceGeneration=1,runtimeFailedGeneration=-1,ensures,binds;
        Listener listener; Surface renderSurface;
        FrameGenerationRenderer frameGenerator;
        SurfaceTexture texture=new SurfaceTexture();
        boolean isAvailable(){return true;}
        SurfaceTexture getSurfaceTexture(){return texture;}
        int getWidth(){return 1920;} int getHeight(){return 1080;}
        float refreshRate(){return 120f;}
        void bindRuntimeErrorListener(){binds++;}
        void ensureSurface(SurfaceTexture t,int w,int h){ensures++;renderSurface=new Surface();}
''' + legacy_available + legacy_changed + legacy_listener + r'''
    }
    static class LegacyOwner extends Owner implements Legacy.Listener {}
    public static void main(String[] args) {
        Primary p=new Primary();Owner owner=new Owner();p.listener=owner;
        p.runtimePresentationFailed=true;p.quarantinedSurfaceGeneration=1;
        for(int generation=2;generation<100;generation++) {
            p.surfaceGeneration=generation;
            p.surfaceChanged(new SurfaceHolder(),0,1920,1080);
            p.setListener(owner);
        }
        assert p.starts==0 && p.creates==0 && p.binds==0;
        assert owner.available==0 && owner.resized==0;
        p=new Primary();p.listener=owner;p.surfaceChanged(new SurfaceHolder(),0,1920,1080);
        assert p.starts==1; // explicit reopen/new view can start normally
        p=new Primary();p.launchMode=FrameGenerationSettings.Mode.OFF;p.listener=owner;
        p.surfaceChanged(new SurfaceHolder(),0,1920,1080);
        assert p.starts==0 && p.creates==1 && owner.available==1;
        Legacy l=new Legacy();LegacyOwner lo=new LegacyOwner();l.listener=lo;
        l.runtimePresentationFailed=true;l.runtimeFailedGeneration=1;
        l.frameGenerator=new FrameGenerationRenderer();
        for(int generation=2;generation<100;generation++) {
            l.surfaceGeneration=generation;l.texture=new SurfaceTexture();
            l.onSurfaceTextureAvailable(l.texture,1920,1080);
            l.onSurfaceTextureSizeChanged(l.texture,1920,1080);l.setListener(lo);
        }
        assert l.ensures==0 && l.binds==0 && l.frameGenerator.resizes==0;
        assert lo.available==0 && lo.resized==0;
        l=new Legacy();l.listener=lo;l.onSurfaceTextureAvailable(l.texture,1920,1080);
        assert l.ensures==1 && lo.available==1;
    }
}
''')
        ensure = method(legacy, "    private void ensureSurface(")
        self.assertLess(ensure.index("if (runtimePresentationFailed) return;"),
                        ensure.index("releaseSurfaces();"))
        finish = method(view, "    private void finishGeneratorStartup(")
        self.assertLess(finish.index("|| runtimePresentationFailed"),
                        finish.index("listener.onSurfaceAvailable"))

    def test_runtime_wiring_never_hands_failed_output_to_direct(self):
        renderer = (GAME / "DisplayFrameGenerator.java").read_text()
        self.assertIn("renderTracedFrame(frameTimeNanos);",
                      method(renderer, "    private void renderFrame("))
        body = method(renderer, "    private void renderTracedFrame(")
        self.assertIn("consumeAvailableFrame(ignored);",
                      method(renderer, "    @Override public void onFrameAvailable("))
        consume = method(renderer, "    private void consumeAvailableFrame(")
        failure = method(renderer, "    private void failRuntimePresentation(")
        for path in (body, consume):
            self.assertIn("failRuntimePresentation(", path)
            self.assertRegex(path, r"if \((?:closed\.get\(\) \|\| )?externalPresentationFailed\)")
        self.assertIn("runtimeFailure.report(", failure)
        self.assertNotIn("close(", failure)
        self.assertNotRegex(failure, r"(?<![=!])=\s*null\s*;")
        self.assertIn("handler.post(() -> uploadSoftwareFrameSafely(", renderer)
        upload = method(renderer, "    private void uploadSoftwareFrame(")
        self.assertIn("if (closed.get() || externalPresentationFailed) return;", upload)
        self.assertIn("runtimeFailure.close();", method(renderer, "    private void closeAfterStartupFailure("))
        for path, sig in ((GAME / "GameSurfaceView.java", "    private void bindRuntimeErrorListener("),
                          (GAME / "GameSurface.java", "    private void bindRuntimeErrorListener("),
                          (PREVIEW, "    private void bindGameplayRuntimeErrorListener(")):
            source = path.read_text()
            callback = method(source, sig)
            self.assertIn("setRuntimeErrorListener", callback)
            self.assertNotIn(".close()", callback)
            self.assertNotRegex(callback, r"(?<![=!])=\s*null\s*;")
            self.assertNotIn("Backend.DIRECT", callback)
        view = (GAME / "GameSurfaceView.java").read_text()
        finish = method(view, "    private void finishGeneratorStartup(")
        self.assertLess(finish.index("bindRuntimeErrorListener(generation)"),
                        finish.index("listener.onSurfaceAvailable"))
        preview = PREVIEW.read_text()
        self.assertEqual(preview.count("gameplayQuarantinedGeneration == surfaceGeneration) return;"), 4)
        for name in ("InWindowGameHost.java", "LucentGameActivity.java"):
            source = (GAME / name).read_text()
            error = method(source, "public void onSessionError(")
            self.assertIn("RuntimePresentationFailure.Failure", error)
            self.assertIn("onSurfaceRuntimeError(cause.getMessage(), cause)", error)
            runtime = method(source, "public void onSurfaceRuntimeError(")
            self.assertIn("prepared = false", runtime)
            self.assertIn("pause(EngineSession.PauseReason.ANDROID_BACKGROUND)", runtime)
            self.assertNotIn("release(", runtime)
            self.assertNotIn("detach", runtime)


    def test_actual_consume_and_present_catches_fail_once_and_keep_producer_drain(self):
        source = (GAME / "DisplayFrameGenerator.java").read_text()
        consume = method(source, "    @Override public void onFrameAvailable(") + '\n' + method(
            source, "    private void consumeAvailableFrame(")
        fail = method(source, "    private void failRuntimePresentation(")
        software = method(source, "    private void uploadSoftwareFrameSafely(")
        render = method(source, "    private void renderTracedFrame(")
        # Execute the actual outer presentation catch, not a fixture's substitute.
        render_catch = method(render[render.rindex("} catch (RuntimeException failure)") + 2:],
                              "catch (RuntimeException failure)")
        self.compile_run(r'''
import com.thorium.lucent.video.RuntimePresentationFailure;
import java.util.concurrent.atomic.*;
public class RuntimeFailureTest {
    static class android {static class os {static class Trace {
        static void beginSection(String name){} static void endSection(){}
    }}}
    static class Log {static int errors; static void e(String t,String m,Throwable c){errors++;}}
    static class SurfaceTexture {
        int updates; boolean failUpdate;
        void updateTexImage(){updates++;if(failUpdate)throw new IllegalStateException("acquire");}
        long getTimestamp(){return 123L;}
        void getTransformMatrix(float[] transform){}
    }
    interface SurfaceListener {void onFrameAvailable(SurfaceTexture ignored);}
    static class FrameRate {boolean authoritative;
        boolean usesAuthoritativeSourceRate(){return authoritative;}}
    static class SourceObserver {int calls;void observeLatest(long raw){assert raw==123;calls++;}}
    static class Renderer implements SurfaceListener {
        static final String TAG="fixture";
        AtomicBoolean closed=new AtomicBoolean(); boolean externalPresentationFailed;
        RuntimePresentationFailure runtimeFailure=new RuntimePresentationFailure();
        SurfaceTexture inputTexture=new SurfaceTexture();
        float[] textureTransform=new float[16]; FrameRate frameRate=new FrameRate();
        Object externalTransport=new Object();
        int latestTexture=7,classifiedUniqueTexture,consumes,copies,firstFrames,uploads;
        long endpointTimestampCorrections,submittedFrameCount,diagHardwareSubmits;
        long classifiedUniqueTimestampNs,classifiedUniqueSubmission;
        boolean classifiedFrameReady,failExport;
        SourceObserver nativeSourceImageObserver=new SourceObserver();
        int nativeClassificationFinishes;
        void clearNativeClassifiedObservation(){}
        void classifyLatestNativeObservation(){}
        void finishNativeClassifiedObservation(boolean unique){nativeClassificationFinishes++;}
        void copyExternalTo(int texture){copies++;}
        void notifyFirstSubmittedFrame(){firstFrames++;}
        boolean latestImageIsUnique(long timestamp){return true;}
        void consumeClassifiedFrame(boolean unique){consumes++;
            if(failExport)throw new IllegalStateException("exact endpoint export");}
        void uploadSoftwareFrame(int[] colors,int w,int h,float aspect,long timestamp){
            uploads++;consumeClassifiedFrame(true);
        }
''' + consume + fail + software + r'''
        void presentFailure(){
            try {throw new IllegalStateException("physical present");}
''' + render_catch + r'''
        }
    }
    public static void main(String[] args) {
        for(boolean authoritative: new boolean[]{false,true}) {
            Renderer r=new Renderer();r.frameRate.authoritative=authoritative;r.failExport=true;
            AtomicInteger calls=new AtomicInteger();
            r.runtimeFailure.setListener((message,cause)->{
                assert r.externalPresentationFailed;
                assert cause.getCause().getMessage().equals("exact endpoint export");calls.incrementAndGet();});
            int errors=Log.errors;r.onFrameAvailable(null);
            assert calls.get()==1 && r.externalPresentationFailed && Log.errors==errors+1;
            assert r.copies==1 && r.consumes==1 && r.inputTexture.updates==1;
            assert r.nativeSourceImageObserver.calls==1 && r.nativeClassificationFinishes==1;
            r.onFrameAvailable(null);assert r.inputTexture.updates==2;
            assert r.copies==1 && r.consumes==1; // failed endpoint never re-enters classify/export
            assert r.nativeSourceImageObserver.calls==1 && r.nativeClassificationFinishes==1;
            r.inputTexture.failUpdate=true;r.onFrameAvailable(null); // drain may itself fail safely
            r.presentFailure();assert calls.get()==1 && Log.errors==errors+1;
        }
        for(boolean external: new boolean[]{false,true}) {
            Renderer r=new Renderer();r.externalTransport=external?new Object():null;
            AtomicInteger calls=new AtomicInteger();
            r.runtimeFailure.setListener((m,c)->{assert c.getCause().getMessage().equals("physical present");
                calls.incrementAndGet();});
            r.presentFailure();assert calls.get()==1 && r.externalPresentationFailed;
            r.onFrameAvailable(null);assert r.inputTexture.updates==1 && r.copies==0 && r.consumes==0;
            r.presentFailure();assert calls.get()==1;
        }
        Renderer r=new Renderer();r.inputTexture.failUpdate=true;r.onFrameAvailable(null);
        assert r.externalPresentationFailed && r.copies==0; // late owner still receives consume failure
        AtomicInteger late=new AtomicInteger();r.runtimeFailure.setListener((m,c)->late.incrementAndGet());
        assert late.get()==1;
        r=new Renderer();r.failExport=true;
        AtomicInteger softwareCalls=new AtomicInteger();
        r.runtimeFailure.setListener((m,c)->softwareCalls.incrementAndGet());
        int[] copy=new int[]{1};r.uploadSoftwareFrameSafely(copy,1,1,1f,123L);
        assert r.externalPresentationFailed && softwareCalls.get()==1 && r.uploads==1 && r.consumes==1;
        r.uploadSoftwareFrameSafely(copy,1,1,1f,124L);r.presentFailure();
        assert softwareCalls.get()==1 && r.uploads==1 && r.consumes==1;
        r=new Renderer();r.closed.set(true);r.onFrameAvailable(null);r.presentFailure();
        r.uploadSoftwareFrameSafely(copy,1,1,1f,125L);
        assert !r.externalPresentationFailed && r.inputTexture.updates==0 && r.uploads==0;
    }
}
''')


if __name__ == "__main__":
    unittest.main()
