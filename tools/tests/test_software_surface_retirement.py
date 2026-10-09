"""Exercise production detach/Exit ownership, not a simulated Android GPU."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_libretro_release_completion import method

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path('/opt/homebrew/opt/openjdk@17/bin')
SOURCE = ROOT / 'unified-android/src/com/thorium/preview/game/LibretroEngineSession.java'


class SoftwareSurfaceRetirementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = SOURCE.read_text()
        names = ['detachSurface', 'quiesceForExit', 'presentVideoWithSurfaceLock',
                 'closeDirectCanvases', 'onSecondarySurfaceDestroyed']
        if 'private void retireDetachedCanvas(' in text:
            names.append('retireDetachedCanvas')
        methods = '\n'.join(method(text, name) for name in names)
        harness = r'''
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.concurrent.locks.*;
public class SoftwareSurfaceRetirement {
    static final String TAG="test";
    static class Log {static int warnings;
        static void i(String t,String s){}
        static void w(String t,String s){warnings++;}
        static void w(String t,String s,Throwable e){warnings++;}}
    static class Entry {String id="mesen-s";}
    static class Request {String systemId="snes";}
    static class Surface {boolean valid=true;}
    static class LibretroHost {static class VideoFrame{}
        boolean awaitFrameBoundary(long millis){return true;}}
    volatile LibretroHost host=new LibretroHost();
    static class DirectHardwareCanvas {
        int closes; boolean alive=true;
        void close(){if(alive){closes++;alive=false;}}
    }
    enum PauseReason {LUCENT_MENU}
    final Entry entry=new Entry();final Request request=new Request();
    final ReentrantLock presentationLock=new ReentrantLock();
    final AtomicBoolean released=new AtomicBoolean();
    volatile boolean running=true;
    volatile Surface surface=new Surface(),secondarySurface=new Surface();
    int secondarySurfaceWidth=640,secondarySurfaceHeight=480;
    boolean secondaryGameplayRequested=true,lowerDrawEvidenceLogged=true;
    DirectHardwareCanvas primaryDirectCanvas=new DirectHardwareCanvas();
    DirectHardwareCanvas secondaryDirectCanvas=new DirectHardwareCanvas();
    final CountDownLatch drawing=new CountDownLatch(1),permit=new CountDownLatch(1);
    int draws;
    void pause(PauseReason reason){running=false;}
    void cancelPendingDisplayResume(){}
    void presentVideo(LibretroHost.VideoFrame frame){
        if(surface==null)return;
        draws++;drawing.countDown();await(permit);
    }
    METHODS
    static void check(boolean b,String why){if(!b)throw new AssertionError(why);}
    static void await(CountDownLatch l){
        try{check(l.await(2,TimeUnit.SECONDS),"fixture timeout");}
        catch(InterruptedException e){throw new AssertionError(e);}
    }
    static Thread start(Runnable r){Thread t=new Thread(r);t.setDaemon(true);t.start();return t;}
    static void join(Thread t)throws Exception{t.join(2000);check(!t.isAlive(),"thread still active");}
    void draw(){presentVideoWithSurfaceLock(new LibretroHost.VideoFrame());}
    public static void main(String[] args)throws Exception{
        SoftwareSurfaceRetirement s=new SoftwareSurfaceRetirement();
        Surface original=s.surface,lower=s.secondarySurface;
        switch(args[0]){
        case "direct":
            s.detachSurface();
            check(s.surface==null,"detach did not close admission");
            check(s.primaryDirectCanvas.closes==1,"HWUI owner survived surface detach");
            check(s.secondaryDirectCanvas.closes==0,"top detach retired live lower owner");
            s.detachSurface();check(s.primaryDirectCanvas.closes==1,"duplicate destruction");
            check(original.valid && lower.valid,"renderer released view-owned Surface");
            break;
        case "inflight":
            Thread render=start(s::draw);await(s.drawing);
            CountDownLatch done=new CountDownLatch(1);
            Thread detach=start(()->{s.detachSurface();done.countDown();});
            check(!done.await(60,TimeUnit.MILLISECONDS),"detach returned while Java draw owned old surface");
            s.permit.countDown();join(render);join(detach);
            check(s.primaryDirectCanvas.closes==1,"completed draw left HWUI owner alive");
            s.draw();check(s.draws==1,"late frame revived detached target");
            break;
        case "exit":
            s.quiesceForExit();
            check(!s.running,"Exit did not stop producer");
            check(s.primaryDirectCanvas.closes==1 && s.secondaryDirectCanvas.closes==1,
                  "Exit only waited Java draw; deferred HWUI work survives");
            check(original.valid && lower.valid,"Exit disposed view-owned surface");
            break;
        case "lower":
            s.onSecondarySurfaceDestroyed();
            check(s.secondarySurface==null && s.secondarySurfaceWidth==0 &&
                  s.secondarySurfaceHeight==0 && !s.lowerDrawEvidenceLogged,"lower cleanup changed");
            check(s.secondaryDirectCanvas.closes==1 && s.primaryDirectCanvas.closes==0,
                  "lower detach must retire only lower HWUI owner");
            break;
        case "timeout":
            Thread busy=start(s::draw);await(s.drawing);
            long began=System.nanoTime();s.detachSurface();long duration=System.nanoTime()-began;
            check(duration<TimeUnit.SECONDS.toNanos(1),"lock acquisition unbounded");
            check(s.surface==null && s.primaryDirectCanvas.closes==0,"busy owner closed concurrently");
            check(Log.warnings>0,"failed retirement silently acknowledged");
            s.permit.countDown();join(busy);s.detachSurface();
            check(s.primaryDirectCanvas.closes==1,"later retirement could not finish");
            break;
        case "interrupt":
            Thread.currentThread().interrupt();s.detachSurface();
            check(Thread.currentThread().isInterrupted(),"lost lifecycle interrupt");
            Thread.interrupted();
            check(s.surface==null && Log.warnings>0,"interrupted retirement falsely acknowledged");
            s.detachSurface();check(s.primaryDirectCanvas.closes==1,"retry after interrupt failed");
            break;
        default:throw new AssertionError(args[0]);
        }
        System.out.println(args[0]+" passed");
    }
}
'''.replace('    METHODS', methods)
        cls.temp = tempfile.TemporaryDirectory(prefix='software-surface-retirement-')
        cls.addClassCleanup(cls.temp.cleanup)
        source = Path(cls.temp.name) / 'SoftwareSurfaceRetirement.java'
        source.write_text(harness)
        subprocess.run([str(JAVA / 'javac'), '-d', cls.temp.name, str(source)], check=True)

    def test_surface_retirement(self):
        for scenario in ('direct', 'inflight', 'exit', 'lower', 'timeout', 'interrupt'):
            with self.subTest(scenario=scenario):
                result = subprocess.run([str(JAVA / 'java'), '-cp', self.temp.name,
                                         'SoftwareSurfaceRetirement', scenario],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
