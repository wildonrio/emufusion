"""Run actual recovery/acknowledgement methods with deterministic ownership leaves."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT / 'unified-android/src/com/thorium/preview/game'
JAVA = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'), 'bin')
HOST_ERROR_SOURCE = GAME / 'InWindowGameHost.java'


def method(path, signature):
    source = path.read_text()
    start = source.index(signature)
    brace = source.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end].replace('@Override ', '')


class RuntimeDirectRecoveryTest(unittest.TestCase):
    def test_every_concrete_game_session_owns_an_acknowledged_off_barrier(self):
        # The common host can retire FG only after the actual engine producer
        # acknowledges quiescence. A newly added session must not silently
        # inherit EngineSession's unsupported (false) default.
        import re
        implementations = []
        for path in GAME.glob('*.java'):
            source = path.read_text()
            if re.search(r'class\s+\w+\s+implements\s+EngineSession\b', source):
                if path.name == 'EngineSessionRegistry.java':
                    continue  # UnavailableEngineSession never starts a producer.
                implementations.append(path.name)
                self.assertIn('boolean quiesceForPresentationRecovery(', source,
                              path.name + ' has no acknowledged live-Off barrier')
        self.assertEqual(set(implementations), {
            'LibretroEngineSession.java', 'PpssppGlesEngineSession.java',
            'NativeAdapterEngineSession.java'})

    def run_java(self, body):
        with tempfile.TemporaryDirectory(prefix='runtime-direct-recovery-') as folder:
            out = Path(folder)
            source = out / 'RecoveryTest.java'
            source.write_text('import java.util.*; import java.util.concurrent.*; '
                              'import java.util.concurrent.atomic.*;\n'
                              'public class RecoveryTest {\n' + body + '\n}\n')
            compile = subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', folder,
                                      str(source)], text=True, capture_output=True, timeout=30)
            self.assertEqual(compile.returncode, 0, compile.stdout + compile.stderr)
            run = subprocess.run([str(JAVA / 'java'), '-ea', '-cp', folder, 'RecoveryTest'],
                                 text=True, capture_output=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_native_ack_requires_executed_success_not_timeout_failure_or_abandon(self):
        path = GAME / 'NativeAdapterEngineSession.java'
        task = method(path, '    private static final class RenderTask')
        recovery = method(path, '    @Override public boolean quiesceForPresentationRecovery(')
        self.run_java(r'''
    static class Log {static void w(String a,String b,Throwable c){}}
    static final String TAG="test";
    static class AudioTrack {int pauses; void pause(){pauses++;}}
    static class NativeAdapterHost {int pauses;boolean fail;void pause(){pauses++;if(fail)throw new IllegalStateException();}}
''' + task + r'''
    static class Session {
        boolean prepared=true,started=true,resumeRequested=true;
        AtomicBoolean stopping=new AtomicBoolean(),released=new AtomicBoolean();
        AudioTrack audioTrack=new AudioTrack(); NativeAdapterHost host=new NativeAdapterHost();
        Thread renderThread; Object surface=new Object();
        LinkedBlockingQueue<RenderTask> renderTasks=new LinkedBlockingQueue<>();
        static final long RENDER_TASK_TIMEOUT_MS=25;
''' + recovery + r'''
    }
    public static void main(String[] args)throws Exception {
        RenderTask bad=new RenderTask(()->{throw new IllegalStateException();});bad.run();
        assert bad.await(1)&&!bad.completedSuccessfully();
        RenderTask abandoned=new RenderTask(()->{throw new AssertionError();});abandoned.abandon();
        assert abandoned.await(1)&&!abandoned.completedSuccessfully();
        RenderTask pending=new RenderTask(()->{});assert !pending.await(1)&&!pending.completedSuccessfully();
        for(int mode=0;mode<3;mode++) {
            Session s=new Session();s.host.fail=mode==1;
            CountDownLatch ready=new CountDownLatch(1),release=new CountDownLatch(1);
            final int which=mode;
            s.renderThread=new Thread(()->{ready.countDown();try {
                RenderTask t=s.renderTasks.take();
                if(which==2)release.await();
                t.run();release.await();
            }catch(InterruptedException e){throw new AssertionError(e);}});
            s.renderThread.start();ready.await();
            boolean acknowledged=s.quiesceForPresentationRecovery();
            assert acknowledged==(mode==0):"incorrect owner acknowledgement";
            if(mode!=0)assert s.surface!=null;
            else assert s.surface==null&&s.host.pauses==1;
            assert !s.resumeRequested&&s.audioTrack.pauses==1;
            release.countDown();s.renderThread.join(1000);assert !s.renderThread.isAlive();
        }
        Session missing=new Session();assert !missing.quiesceForPresentationRecovery();
    }
''')

    def test_off_dispatch_does_not_take_host_lock_inside_settings_transaction(self):
        body = method(GAME / 'InWindowGameHost.java',
                      '    public static void requestFrameGenerationOff(')
        self.run_java(r'''
    static class Looper {static Object getMainLooper(){return null;}}
    static class Handler {
        static final ArrayDeque<Runnable> tasks=new ArrayDeque<>();
        Handler(Object looper){}void post(Runnable r){tasks.add(r);}
        static void flush(){while(!tasks.isEmpty())tasks.remove().run();}
    }
    static class InWindowGameHost {
        static InWindowGameHost active;boolean ownerRequestedDirect;int applies;
        void applyOwnerRequestedDirect(){assert ownerRequestedDirect;applies++;}
''' + body + r'''
    }
    public static void main(String[] args)throws Exception {
        InWindowGameHost host=new InWindowGameHost();InWindowGameHost.active=host;
        Thread writer=new Thread(InWindowGameHost::requestFrameGenerationOff);
        writer.setDaemon(true);
        synchronized(InWindowGameHost.class) {
            writer.start();writer.join(500);
            assert !writer.isAlive():"settings writer waited for host lock";
        }
        assert host.applies==0&&!host.ownerRequestedDirect;
        Handler.flush();assert host.applies==1&&host.ownerRequestedDirect;
        InWindowGameHost.active=null;InWindowGameHost.requestFrameGenerationOff();
        Handler.flush();assert host.applies==1;
    }
''')
        self.assertIn('if (safe == Mode.OFF) InWindowGameHost.requestFrameGenerationOff();',
                      method(GAME / 'FrameGenerationSettings.java',
                             '    public static synchronized void setMode('))

    def test_view_retirement_survives_destroy_but_never_rebinds_before_ack(self):
        path = GAME / 'GameSurfaceView.java'
        bodies = '\n'.join(method(path, s) for s in [
            '    private void releaseGenerator(',
            '    FrameGenerationRenderer beginOwnerDirectRecovery(',
            '    FrameGenerationRenderer beginRuntimeDirectRecovery(',
            '    boolean finishRuntimeDirectRecovery('])
        self.run_java(r'''
    static class FrameGenerationRenderer {int closes;void close(){closes++;}}
    static class FrameGenerationBackendPolicy {enum Backend {DIRECT,LSFG}}
    static class View {
        boolean runtimePresentationFailed=true,runtimeRecoveryPending,surfaceLive=true,startupFellBackToDirect,generatorStartupPending;
        FrameGenerationRenderer frameGenerator=new FrameGenerationRenderer();
        Object engineSurface=new Object(),outputSurface=new Object();int quarantinedSurfaceGeneration=1,bindings;
        FrameGenerationBackendPolicy.Backend activeBackend=FrameGenerationBackendPolicy.Backend.LSFG;
        Object getHolder(){return this;}int getWidth(){return 1920;}int getHeight(){return 1080;}
        void surfaceChanged(Object h,int f,int w,int z){assert !runtimePresentationFailed;bindings++;}
''' + bodies + r'''
    }
    public static void main(String[] args) {
        View owner=new View();owner.runtimePresentationFailed=false;
        owner.generatorStartupPending=true;
        assert owner.beginOwnerDirectRecovery()==null&&!owner.runtimeRecoveryPending;
        owner.generatorStartupPending=false;
        FrameGenerationRenderer owned=owner.beginOwnerDirectRecovery();
        assert owned==owner.frameGenerator&&!owner.runtimePresentationFailed;
        assert owner.beginOwnerDirectRecovery()==null&&owned.closes==0;
        owned.close();assert owner.finishRuntimeDirectRecovery(owned,true,true);
        assert owner.startupFellBackToDirect&&owner.bindings==1&&owner.frameGenerator==null;
        View v=new View();FrameGenerationRenderer r=v.beginRuntimeDirectRecovery();
        assert r==v.frameGenerator&&v.beginRuntimeDirectRecovery()==null;
        v.releaseGenerator();assert r.closes==0&&v.frameGenerator==r&&v.engineSurface==null;
        assert !v.finishRuntimeDirectRecovery(new FrameGenerationRenderer(),true,true);
        assert !v.finishRuntimeDirectRecovery(r,false,true)&&v.bindings==0&&v.runtimePresentationFailed;
        v.releaseGenerator();assert r.closes==1; // normal exit retains failed ownership
        for(boolean live:new boolean[]{true,false})for(boolean current:new boolean[]{true,false}) {
            v=new View();v.surfaceLive=live;r=v.beginRuntimeDirectRecovery();r.close();
            assert v.finishRuntimeDirectRecovery(r,true,current)&&v.frameGenerator==null;
            assert v.bindings==(live&&current?1:0);
            assert v.startupFellBackToDirect==current;
            assert v.runtimePresentationFailed!=current;
            v.releaseGenerator();assert r.closes==1;
        }
    }
''')

    def test_host_orders_producer_generator_ui_and_rejects_late_or_failed_recovery(self):
        path = GAME / 'InWindowGameHost.java'
        bodies = method(path, '    private void applyOwnerRequestedDirect(') + '\n' + method(path, '    private boolean startRuntimeDirectRecovery(') + '\n' + method(path, '    private boolean tryStartRuntimeDirectRecovery(') + '\n' + method(
            HOST_ERROR_SOURCE, '    @Override public void onSurfaceRuntimeError(')
        self.run_java(r'''
    static class Queue {ArrayDeque<Runnable> q=new ArrayDeque<>();void execute(Runnable r){q.add(r);}
        void post(Runnable r){q.add(r);}void runOnUiThread(Runnable r){q.add(r);}
        void flush(){while(!q.isEmpty())q.remove().run();}}
    static class Log {static void w(String a,String b,Throwable c){}static void i(String a,String b){}
        static void e(String a,String b,Throwable c){}}
    static class Toast {static final int LENGTH_LONG=1;static int shown;
        static Toast makeText(Object a,String b,int c){return new Toast();}void show(){shown++;}}
    static class EngineSession {
        enum PauseReason {ANDROID_BACKGROUND}
        int barriers,pauses;boolean ack=true;
        boolean quiesceForPresentationRecovery(){barriers++;return ack;}
        void pause(PauseReason r){pauses++;}
    }
    static class FrameGenerationRenderer {int closes;boolean fail;EngineSession producer;
        void close(){assert producer.barriers==1&&producer.ack;closes++;if(fail)throw new IllegalStateException();}}
    static class GameSurfaceView {
        FrameGenerationRenderer renderer=new FrameGenerationRenderer();boolean failed=true;int binds,finishes;
        FrameGenerationRenderer beginRuntimeDirectRecovery(){return failed?renderer:null;}
        FrameGenerationRenderer beginOwnerDirectRecovery(){return renderer;}
        boolean ownerDirect;void requestOwnerDirect(){ownerDirect=true;}
        boolean finishRuntimeDirectRecovery(FrameGenerationRenderer r,boolean retired,boolean rebind){
            assert r==renderer;finishes++;if(retired&&rebind)binds++;return retired;}
    }
    static class Request {String engineId="test",systemId="test";}
    static class View {static final int GONE=8;}
    static class TextView {void setVisibility(int value){assert value==View.GONE;}}
    static class Host {
        static final String TAG="test";Queue RETIREMENT_RELEASES=new Queue(),activity=new Queue(),mainHandler=activity;
        boolean prepared=true,presentationRecoveryAttempted,presentationRecoveryPending,surfaceAvailable=true,ownerRequestedDirect;
        boolean libraryReturned,fatalErrorVisible;AtomicBoolean exitStarted=new AtomicBoolean();
        EngineSession session=new EngineSession();Object gameSurface=new GameSurfaceView();Request request=new Request();
        TextView frameRateBadge=new TextView();
        int fatal;void updateGameplayScreenOn(){}void showFatalError(String m,boolean r){fatal++;fatalErrorVisible=true;}
        Host(){((GameSurfaceView)gameSurface).renderer.producer=session;}
''' + bodies + r'''
    }
    public static void main(String[] args) {
        Host owner=new Host();owner.prepared=false;owner.ownerRequestedDirect=true;
        GameSurfaceView owned=(GameSurfaceView)owner.gameSurface;owned.failed=false;
        owner.applyOwnerRequestedDirect();assert owner.RETIREMENT_RELEASES.q.isEmpty();
        assert owned.ownerDirect : "loading Off was not forwarded to the surface";
        owner.prepared=true;owner.applyOwnerRequestedDirect();owner.applyOwnerRequestedDirect();
        assert owner.RETIREMENT_RELEASES.q.size()==1&&!owner.prepared;
        assert owned.renderer.closes==0&&!owned.failed;
        owner.RETIREMENT_RELEASES.flush();owner.activity.flush();
        assert owned.renderer.closes==1&&owned.binds==1&&owner.fatal==0&&owner.prepared;
        for(int mode=0;mode<5;mode++) {
            Host h=new Host();EngineSession e=h.session;GameSurfaceView v=(GameSurfaceView)h.gameSurface;
            if(mode==1)e.ack=false;if(mode==2)v.renderer.fail=true;
            h.onSurfaceRuntimeError("failed",null);h.activity.flush();
            assert !h.prepared&&!h.surfaceAvailable&&h.presentationRecoveryPending;
            assert e.barriers==0&&v.renderer.closes==0; // no blocking work on UI
            h.onSurfaceRuntimeError("duplicate",null);h.activity.flush();
            assert h.RETIREMENT_RELEASES.q.size()==1;
            h.RETIREMENT_RELEASES.flush();assert e.barriers==1;
            if(mode==3){h.session=null;h.libraryReturned=true;}
            if(mode==4)h.exitStarted.set(true);
            assert v.binds==0;
            h.activity.flush();assert !h.presentationRecoveryPending;
            assert v.binds==(mode==0?1:0);
            assert h.fatal==((mode==1||mode==2)?1:0);
            assert v.renderer.closes==(mode==1?0:1);
            assert v.finishes==1;
            if(mode==0)assert h.prepared&&h.fatal==0;
        }
        Host direct=new Host();((GameSurfaceView)direct.gameSurface).failed=false;
        direct.onSurfaceRuntimeError("engine failure",null);direct.activity.flush();
        assert direct.fatal==1&&direct.RETIREMENT_RELEASES.q.isEmpty();
    }
''')

    def test_software_barrier_waits_for_actual_independent_presenter(self):
        path = GAME / 'LibretroEngineSession.java'
        bodies = '\n'.join(method(path, s) for s in [
            '    @Override public boolean quiesceForPresentationRecovery(',
            '    private void presentVideoWithSurfaceLock('])
        self.run_java(r'''
    static class LibretroHost {static class VideoFrame{}}
    enum PauseReason {LUCENT_MENU}
    static class Session {
        boolean prepared=true,running=true,primaryRecoverySurfaceCanvas;int canvasCloses;
        AtomicBoolean stopping=new AtomicBoolean(),released=new AtomicBoolean();
        java.util.concurrent.locks.ReentrantLock presentationLock=new java.util.concurrent.locks.ReentrantLock();
        Object surface=new Object();CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        void pause(PauseReason p){running=false;}
        void closeDirectCanvases(){canvasCloses++;}
        void presentVideo(LibretroHost.VideoFrame f){entered.countDown();try{release.await();}
            catch(InterruptedException e){throw new AssertionError(e);}}
''' + bodies + r'''
    }
    public static void main(String[] args)throws Exception {
        Session s=new Session();Object original=s.surface;
        Thread render=new Thread(()->s.presentVideoWithSurfaceLock(new LibretroHost.VideoFrame()));
        render.start();s.entered.await();
        assert !s.quiesceForPresentationRecovery()&&s.surface==original&&s.canvasCloses==0;
        assert !s.primaryRecoverySurfaceCanvas : "fallback activated before acknowledgement";
        s.release.countDown();render.join(1000);assert !render.isAlive();
        assert s.quiesceForPresentationRecovery()&&s.surface==null&&s.canvasCloses==1;
        assert s.primaryRecoverySurfaceCanvas : "recovered primary reused failing custom renderer";
        s.stopping.set(true);assert !s.quiesceForPresentationRecovery();
    }
''')

    def test_surface_canvas_fallback_is_primary_recovery_only(self):
        path = GAME / 'LibretroEngineSession.java'
        body = method(path, '    private boolean useTimestampedDirectCanvas(')
        self.run_java('static class Session { boolean primaryRecoverySurfaceCanvas;\n' + body + r'''
    }
    public static void main(String[] args) {
        Session fresh = new Session();
        assert fresh.useTimestampedDirectCanvas(false);
        assert fresh.useTimestampedDirectCanvas(true);
        fresh.primaryRecoverySurfaceCanvas = true;
        assert !fresh.useTimestampedDirectCanvas(false);
        assert fresh.useTimestampedDirectCanvas(true);
        assert new Session().useTimestampedDirectCanvas(false);
    }
''')
        self.assertIn('if (useTimestampedDirectCanvas(preserveWholePicture) &&',
                      method(path, '    private boolean drawFrame('))

    def test_gles_recovery_completes_pause_and_detach_or_propagates_error(self):
        path = ROOT / 'unified-android/src/com/thorium/preview/ExperimentalGlesRenderLoop.java'
        body = method(path, '    public void pauseAndDetachForPresentationRecovery(')
        self.run_java(r'''
    static class NativeHost {
        int paused,detached,lowerDetached;boolean fail;
        void pause(){paused++;}void detachSecondary(){lowerDetached++;}
        void detach(){if(fail)throw new IllegalStateException("detach");detached++;}
    }
    static class Loop {
        NativeHost host=new NativeHost();boolean resumeRequested=true,secondarySurfaceAttached=true,surfaceAttached=true,awaitingRecreate=true;
        Object attachedSurface=new Object();int surfaceGeneration=3,clockSuspends;long nextFrameDeadlineNanos=22;
        void suspendDisplayClock(){clockSuspends++;}
        <T>T call(Callable<T> c){try{return c.call();}catch(RuntimeException e){throw e;}catch(Exception e){throw new AssertionError(e);}}
''' + body + r'''
    }
    public static void main(String[] args) {
        Loop l=new Loop();l.pauseAndDetachForPresentationRecovery();
        assert !l.resumeRequested&&!l.surfaceAttached&&!l.secondarySurfaceAttached&&!l.awaitingRecreate;
        assert l.attachedSurface==null&&l.surfaceGeneration==4&&l.nextFrameDeadlineNanos==0;
        assert l.host.paused==1&&l.host.detached==1&&l.host.lowerDetached==1&&l.clockSuspends==1;
        l=new Loop();l.host.fail=true;
        try{l.pauseAndDetachForPresentationRecovery();throw new AssertionError("false detach acknowledgement");}
        catch(IllegalStateException expected){assert l.surfaceAttached&&l.attachedSurface!=null;}
    }
''')

    def test_stop_ordering_and_stale_badge_after_recovery(self):
        path = GAME / 'InWindowGameHost.java'
        bodies = method(path, '    private void runAfterPresentationRecovery(') + '\n' + method(
            path, '    private void updateFrameRateBadge(')
        self.run_java(r'''
    static class Queue {ArrayDeque<Runnable> q=new ArrayDeque<>();void execute(Runnable r){q.add(r);}}
    static class View {static final int GONE=8,VISIBLE=0;}
    static class TextView {int visibility=0;void setVisibility(int v){visibility=v;}void setText(String s){}}
    static class FrameGenerationSettings {enum Mode {OFF,BUILT_IN_ALPHA}}
    static class Request {FrameGenerationSettings.Mode frameGenerationMode=FrameGenerationSettings.Mode.BUILT_IN_ALPHA;}
    static class GameSurfaceView {String activeFrameGenerationBackend(){return "Direct";}}
    static class Host {
        boolean presentationRecoveryPending,presentationRecoveryAttempted,ownerRequestedDirect;
        Queue RETIREMENT_RELEASES=new Queue();TextView frameRateBadge=new TextView();
        Request request=new Request();Object gameSurface=new GameSurfaceView();
''' + bodies + r'''
    }
    public static void main(String[] args) {
        Host h=new Host();List<Integer> order=new ArrayList<>();h.presentationRecoveryPending=true;
        h.RETIREMENT_RELEASES.execute(()->order.add(1));h.runAfterPresentationRecovery(()->order.add(2));
        assert order.isEmpty();while(!h.RETIREMENT_RELEASES.q.isEmpty())h.RETIREMENT_RELEASES.q.remove().run();
        assert order.equals(Arrays.asList(1,2));h.presentationRecoveryPending=false;
        h.runAfterPresentationRecovery(()->order.add(3));assert order.equals(Arrays.asList(1,2,3));
        h.presentationRecoveryAttempted=true;h.updateFrameRateBadge(60,120,120,true);
        assert h.frameRateBadge.visibility==View.GONE;
        h.presentationRecoveryAttempted=false;h.updateFrameRateBadge(60,120,120,true);
        assert h.frameRateBadge.visibility==View.VISIBLE;
        h.ownerRequestedDirect=true;h.updateFrameRateBadge(60,120,120,true);
        assert h.frameRateBadge.visibility==View.GONE : "loading Off resurrected a retired badge";
    }
''')
