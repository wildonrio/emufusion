"""Run production software-render handoff methods against a delayed renderer.

Only Android/core and drawing boundaries are fakes. The actual locking and
eligibility code runs on real Java threads; no source-string assertions stand
in for ownership/timeout behavior.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_libretro_release_completion import method

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / 'unified-android/src/com/thorium/preview/game/LibretroEngineSession.java'
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')

SHELL = r'''
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.concurrent.locks.*;
public class SoftwareExitBarrier {
    enum PauseReason {LUCENT_MENU}
    final ReentrantLock presentationLock=new ReentrantLock();
    final AtomicBoolean released=new AtomicBoolean();
    volatile boolean running=true;
    final CountDownLatch paused=new CountDownLatch(1),drawing=new CountDownLatch(1),
        drawPermit=new CountDownLatch(1);
    final AtomicInteger draws=new AtomicInteger();
    static class LibretroHost {static class VideoFrame {}
        volatile boolean frameIdle=true;
        boolean awaitFrameBoundary(long millis)throws InterruptedException{return frameIdle;}}
    volatile LibretroHost host=new LibretroHost();
    int closes;
    void pause(PauseReason reason){running=false;paused.countDown();}
    void closeDirectCanvases(){closes++;}
    void presentVideo(LibretroHost.VideoFrame frame){
        draws.incrementAndGet();drawing.countDown();await(drawPermit);
    }
    QUIESCE
    PRESENT
    static void check(boolean value,String why){if(!value)throw new AssertionError(why);}
    static void await(CountDownLatch latch){
        try{check(latch.await(2,TimeUnit.SECONDS),"fixture deadline");}
        catch(InterruptedException e){throw new AssertionError(e);}
    }
    static Thread start(Runnable action){
        Thread t=new Thread(action);t.setDaemon(true);t.start();return t;
    }
    static void join(Thread t)throws Exception{t.join(2000);check(!t.isAlive(),"owner did not finish");}
    void draw(){presentVideoWithSurfaceLock(new LibretroHost.VideoFrame());}
    static void inFlight()throws Exception{
        SoftwareExitBarrier s=new SoftwareExitBarrier();
        Thread render=start(s::draw);await(s.drawing);
        AtomicReference<Throwable> error=new AtomicReference<>();
        CountDownLatch finished=new CountDownLatch(1);
        Thread exit=start(()->{try{s.quiesceForExit();}catch(Throwable e){error.set(e);}
                              finally{finished.countDown();}});
        await(s.paused);
        check(!finished.await(50,TimeUnit.MILLISECONDS),"Exit acknowledged a live draw");
        s.drawPermit.countDown();join(render);join(exit);
        check(error.get()==null,"ordinary completed draw failed Exit");
        s.draw();check(s.draws.get()==1,"queued frame drew after quiescent Exit");
    }
    static void lateFrame()throws Exception{
        SoftwareExitBarrier s=new SoftwareExitBarrier();s.drawPermit.countDown();
        s.quiesceForExit();s.draw();
        check(s.draws.get()==0,"post-Exit mailbox frame touched retired surface");
        s.running=true;s.draw();check(s.draws.get()==1,"resume/rejected stop cannot render");
        s.released.set(true);s.draw();check(s.draws.get()==1,"released owner rendered");
    }
    static void queued()throws Exception{
        SoftwareExitBarrier s=new SoftwareExitBarrier();s.drawPermit.countDown();
        s.presentationLock.lock();
        Thread render=start(s::draw);
        long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(1);
        while(!s.presentationLock.hasQueuedThread(render) && System.nanoTime()<until)Thread.yield();
        check(s.presentationLock.hasQueuedThread(render),"fixture renderer not queued");
        s.pause(PauseReason.LUCENT_MENU);s.presentationLock.unlock();join(render);
        check(s.draws.get()==0,"queued draw tested running outside presentation lock");
    }
    static void timeout()throws Exception{
        SoftwareExitBarrier s=new SoftwareExitBarrier();
        Thread render=start(s::draw);await(s.drawing);
        long begin=System.nanoTime();boolean rejected=false;
        try{s.quiesceForExit();}catch(IllegalStateException expected){rejected=true;}
        long elapsed=System.nanoTime()-begin;
        s.drawPermit.countDown();join(render);
        check(rejected,"busy renderer falsely permitted Surface detachment");
        check(elapsed<TimeUnit.SECONDS.toNanos(1),"UI render barrier unbounded");
        s.quiesceForExit();check(!s.running,"quiescence restarted gameplay");
    }
    static void interrupted()throws Exception{
        SoftwareExitBarrier s=new SoftwareExitBarrier();
        Thread render=start(s::draw);await(s.drawing);
        AtomicBoolean rejected=new AtomicBoolean(),restored=new AtomicBoolean();
        Thread exit=start(()->{
            Thread.currentThread().interrupt();
            try{s.quiesceForExit();}catch(IllegalStateException expected){rejected.set(true);}
            restored.set(Thread.currentThread().isInterrupted());
        });join(exit);s.drawPermit.countDown();join(render);
        check(rejected.get(),"interrupted barrier falsely acknowledged draw completion");
        check(restored.get(),"barrier swallowed interrupt");
    }
    static void coreFrame()throws Exception{
        // pause() only records the request; a frame still inside the core
        // must fail closed instead of detaching the Surface under it.
        SoftwareExitBarrier s=new SoftwareExitBarrier();s.drawPermit.countDown();
        s.host.frameIdle=false;boolean rejected=false;
        try{s.quiesceForExit();}catch(IllegalStateException expected){rejected=true;}
        check(rejected,"running core frame falsely permitted Surface detachment");
        check(!s.running,"core-frame rejection left gameplay running");
        check(s.closes==0,"canvases closed while the core frame was running");
        s.host.frameIdle=true;s.quiesceForExit();check(s.closes==1,"idle core did not quiesce");
        s.host=null;s.quiesceForExit();check(s.closes==2,"unprepared session did not quiesce");
    }
    public static void main(String[] args)throws Exception{
        switch(args[0]){
            case "coreframe":coreFrame();break;
            case "inflight":inFlight();break;
            case "late":lateFrame();break;
            case "queued":queued();break;
            case "timeout":timeout();break;
            case "interrupt":interrupted();break;
            default:throw new AssertionError(args[0]);
        }
        System.out.println(args[0]+" passed");
    }
}
'''


class SoftwareExitRenderBarrierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='software-exit-barrier-')
        cls.directory = Path(cls.temp.name)
        source = SESSION.read_text()
        harness = SHELL.replace('QUIESCE', method(source, 'quiesceForExit'))
        harness = harness.replace('PRESENT', method(source, 'presentVideoWithSurfaceLock'))
        path = cls.directory / 'SoftwareExitBarrier.java'
        path.write_text(harness)
        subprocess.run([str(JAVA / 'javac'), '-d', str(cls.directory), str(path)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_actual_handoff_methods(self):
        for scenario in ('inflight', 'late', 'queued', 'timeout', 'interrupt', 'coreframe'):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(JAVA / 'java'), '-cp', str(self.directory),
                                         'SoftwareExitBarrier', scenario],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
