"""Execute production render/lifecycle methods against a deliberately slow start."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_native_adapter_retirement_completion import member

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'unified-android/src/com/thorium/preview/game/NativeAdapterEngineSession.java'
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
ENV = dict(os.environ, JAVA_TOOL_OPTIONS='-Djava.awt.headless=true -Dapple.awt.UIElement=true')
SIGNATURES = ['private void renderLoop()', '@Override public void resume()',
    '@Override public void pause(PauseReason reason)', '@Override public void quiesceForExit()',
    'private void runOnRenderThread(Runnable action)', 'private void drainRenderTasks()',
    'private void abandonRenderTasks()', 'private static void runQuietly(Runnable action)',
    'private static final class RenderTask']

HARNESS = r'''
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.BooleanSupplier;
interface EngineSession {
    enum PauseReason { USER, ANDROID_BACKGROUND }
    void resume(); void pause(PauseReason reason); void quiesceForExit();
}
class Surface { boolean isValid(){return true;} }
class SystemClock { static long uptimeMillis(){return System.nanoTime()/1000000;} }
class Log {
    static void i(String t,String m){} static void w(String t,String m){}
    static void w(String t,String m,Throwable e){} static void e(String t,String m,Throwable e){}
}
class AudioTrack {
    boolean playing;
    void play(){playing=true;} void pause(){playing=false;}
}
class NativeAdapterHost {
    final CountDownLatch entered=new CountDownLatch(1), allowed=new CountDownLatch(1);
    final AtomicInteger pauses=new AtomicInteger(), resumes=new AtomicInteger(), frames=new AtomicInteger();
    volatile boolean paused, failStart;
    volatile Thread owner;
    void start(Surface s,Surface lower) {
        owner=Thread.currentThread(); entered.countDown();
        try { if(!allowed.await(3,TimeUnit.SECONDS))throw new AssertionError("start not released"); }
        catch(InterruptedException e){throw new AssertionError(e);}
        if(failStart)throw new IllegalStateException("startup failure");
        paused=false;
    }
    void checkOwner(){NativeAdapterEngineSession.check(Thread.currentThread()==owner,"native call off owner");}
    void pause(){checkOwner();paused=true;pauses.incrementAndGet();}
    void resume(){checkOwner();paused=false;resumes.incrementAndGet();}
    void runFrame(){checkOwner();if(!paused)frames.incrementAndGet();}
}
public class NativeAdapterEngineSession implements EngineSession {
    static final String TAG="test";
    static final long IDLE_TICK_MS=8,RENDER_TICK_MS=4,RENDER_TASK_TIMEOUT_MS=250;
    static class Entry { String id; }
    static class Request { String systemId="fixture"; }
    static class Focus { int abandons; void request(){} void abandon(){abandons++;} }
    interface Listener {void onSessionError(String message,Throwable failure);}
    final Entry entry=new Entry(); final Request request=new Request(); final Focus audioFocus=new Focus();
    final AtomicBoolean released=new AtomicBoolean(),stopping=new AtomicBoolean();
    final BlockingQueue<RenderTask> renderTasks=new LinkedBlockingQueue<>();
    final AtomicInteger idleAfterStart=new AtomicInteger(),errors=new AtomicInteger();
    volatile boolean prepared=true,started,resumeRequested=true,audioStartedOnce;
    volatile Surface surface=new Surface(),secondarySurface;
    volatile AudioTrack audioTrack;
    NativeAdapterHost host=new NativeAdapterHost(); Thread renderThread;
    Runnable firstFrameCallback=()->{};
    Listener listener=(message,failure)->errors.incrementAndGet();
    boolean secondaryReadyToStart(){return true;}
    void configureNativePresentation(NativeAdapterHost h,Surface s){}
    void logLaunchPhase(String p,long t){}
    void publishProducerTiming(NativeAdapterHost h){}
    void restoreQuickResume(NativeAdapterHost h){}
    void ensureAudioTrack(){audioTrack=new AudioTrack();}
    String describeSecondary(Surface s){return "fixture";}
    void rebindNativeSurface(NativeAdapterHost h,Surface s,Surface lower){}
    void probeAps3eFirstSubmittedFrame(Surface s){}
    void drainAudioToTrack(NativeAdapterHost h){}
    void reportEngineSpeed(NativeAdapterHost h){}
    void releaseSecondaryDisplay(){}
    void releasePhoneTouch(){}
    String sessionFailureMessage(Throwable failure){return "failure";}
    void sleepQuietly(long millis){
        if(millis==IDLE_TICK_MS&&started)idleAfterStart.incrementAndGet();
        try{Thread.sleep(1);}catch(InterruptedException e){Thread.currentThread().interrupt();}
    }
    // PRODUCTION_METHODS
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static void await(BooleanSupplier condition,String message)throws Exception{
        long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while(!condition.getAsBoolean()&&System.nanoTime()<until)Thread.sleep(1);
        check(condition.getAsBoolean(),message);
    }
    static NativeAdapterEngineSession starting(String engine)throws Exception{
        NativeAdapterEngineSession s=new NativeAdapterEngineSession();s.entry.id=engine;
        s.renderThread=new Thread(s::renderLoop,"test-native-owner");s.renderThread.start();
        check(s.host.entered.await(3,TimeUnit.SECONDS),"start not entered");return s;
    }
    static void cleanup(NativeAdapterEngineSession s)throws Exception{
        s.prepared=false;s.host.allowed.countDown();s.renderThread.join(4000);
        check(!s.renderThread.isAlive(),"render owner leaked");
    }
    static void pauseDuringStart(String engine,int kind)throws Exception{
        NativeAdapterEngineSession s=starting(engine);
        try{
            if(kind==2)s.quiesceForExit();
            else s.pause(kind==1?PauseReason.ANDROID_BACKGROUND:PauseReason.USER);
            check(!s.started&&!s.resumeRequested,"fixture did not pause during blocked start");
            s.host.allowed.countDown();await(()->s.idleAfterStart.get()>0,"owner did not park");
            check(s.host.paused&&s.host.pauses.get()>=1,"guest kept running while startup owner parked");
            check(s.host.frames.get()==0,"frame pumped after a startup pause");
            check(s.errors.get()==0,"pause caused session error");
            check(s.audioTrack!=null&&!s.audioTrack.playing,"startup pause played audio");
            if(kind==1)check(s.audioFocus.abandons==1,"background did not abandon focus");
            s.resume();await(()->s.host.frames.get()>0,"resume did not restart frame pump");
            check(!s.host.paused&&s.host.resumes.get()==1,"resume did not reach native engine");
        }finally{cleanup(s);}
    }
    static void rapidPauseResume(String engine)throws Exception{
        NativeAdapterEngineSession s=starting(engine);
        try{
            s.pause(PauseReason.USER);s.resume();s.host.allowed.countDown();
            await(()->s.host.frames.get()>0,"early resume left engine parked");
            check(s.host.pauses.get()==0&&!s.host.paused,"stale pause applied after early resume");
        }finally{cleanup(s);}
    }
    static void ordinaryStart(String engine)throws Exception{
        NativeAdapterEngineSession s=starting(engine);
        try{
            s.host.allowed.countDown();await(()->s.host.frames.get()>0,"ordinary start failed");
            s.pause(PauseReason.USER);check(s.host.paused,"ordinary pause failed");
            s.resume();check(!s.host.paused,"ordinary resume failed");
        }finally{cleanup(s);}
    }
    static void failedStart()throws Exception{
        NativeAdapterEngineSession s=starting("eden");
        try{
            s.pause(PauseReason.USER);s.host.failStart=true;s.host.allowed.countDown();
            await(()->s.errors.get()==1,"startup failure not surfaced");
            check(s.host.pauses.get()==0&&!s.started,"failed start was treated as live engine");
        }finally{cleanup(s);}
    }
    public static void main(String[]args)throws Exception{
        for(String engine:new String[]{"cemu","eden","aps3e"}){
            for(int kind=0;kind<3;kind++)pauseDuringStart(engine,kind);
            rapidPauseResume(engine);ordinaryStart(engine);
        }
        failedStart();System.out.println("16 production startup/lifecycle scenarios passed");
    }
}
'''


class NativeAdapterStartPauseTests(unittest.TestCase):
    def execute(self, source):
        code = HARNESS.replace('// PRODUCTION_METHODS', '\n'.join(member(source, s) for s in SIGNATURES))
        with tempfile.TemporaryDirectory(prefix='emufusion-start-pause-') as temporary:
            file = Path(temporary) / 'NativeAdapterEngineSession.java'
            file.write_text(code)
            subprocess.run([str(JAVA / 'javac'), str(file)], env=ENV, check=True, capture_output=True, timeout=60)
            result = subprocess.run([str(JAVA / 'java'), '-ea', '-cp', temporary,
                                     'NativeAdapterEngineSession'], env=ENV, capture_output=True, text=True, timeout=30)
            return result

    def test_slow_start_respects_pause_background_exit_and_resume(self):
        result = self.execute(SOURCE.read_text())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('16 production startup/lifecycle scenarios passed', result.stdout)

    def test_pre_fix_startup_reproduces_unpaused_guest(self):
        source = SOURCE.read_text()
        start = source.index('                    // pause()/quiesceForExit() can arrive inside')
        end = source.index('\n                }\n                active.runFrame();', start)
        result = self.execute(source[:start] + source[end:])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('guest kept running while startup owner parked', result.stderr)


if __name__ == '__main__':
    unittest.main()
