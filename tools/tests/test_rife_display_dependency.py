"""Execute the production GL-before-compute fence lifecycle against EGL stubs."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]


class DisplayDependencyTest(unittest.TestCase):
    def test_worker_wait_and_cleanup(self):
        production = (ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        fence = method(production, '    private static final class DisplaySubmissionFence')
        source = '''
public class FenceTest {
 static class EGLDisplay {}
 static class EGLSync {}
 static class EGL14 {
  static final int EGL_NONE=0; static final EGLDisplay EGL_NO_DISPLAY=new EGLDisplay();
  static EGLDisplay current=new EGLDisplay(); static EGLDisplay eglGetCurrentDisplay(){return current;}
 }
 static class EGL15 {
  static final int EGL_SYNC_FENCE=1,EGL_CONDITION_SATISFIED=2;
  static final EGLSync EGL_NO_SYNC=new EGLSync();
  static int waits,destroys,result=2;static boolean reject;
  static EGLSync eglCreateSync(EGLDisplay d,int t,long[] a,int o){return reject?EGL_NO_SYNC:new EGLSync();}
  static int eglClientWaitSync(EGLDisplay d,EGLSync s,int flags,long timeout){
   if(flags!=0||timeout!=100_000_000L)throw new AssertionError();waits++;return result;
  }
  static boolean eglDestroySync(EGLDisplay d,EGLSync s){destroys++;return true;}
 }
 static class GLES20 {static int flushes;static void glFlush(){flushes++;}}
 FENCE
 static void check(boolean b){if(!b)throw new AssertionError();}
 static Throwable waitWorker(DisplaySubmissionFence f)throws Exception {
  Throwable[] caught={null};Thread t=new Thread(()->{try{f.awaitOnWorker();}catch(Throwable e){caught[0]=e;}});
  t.start();t.join();return caught[0];
 }
 public static void main(String[] args)throws Exception {
  DisplaySubmissionFence f=DisplaySubmissionFence.capture();
  check(GLES20.flushes==1&&EGL15.waits==0);
  try{f.awaitOnWorker();throw new AssertionError();}catch(IllegalStateException ok){}
  check(EGL15.waits==0&&EGL15.destroys==0);
  check(waitWorker(f)==null&&EGL15.waits==1&&EGL15.destroys==1);
  f.destroy();check(EGL15.destroys==1);
  EGL15.result=3;DisplaySubmissionFence timeout=DisplaySubmissionFence.capture();
  check(waitWorker(timeout) instanceof IllegalStateException);check(EGL15.destroys==2);
  DisplaySubmissionFence rejected=DisplaySubmissionFence.capture();rejected.destroy();
  check(EGL15.destroys==3); // rejected executor returns ownership to creator
  EGL15.reject=true;
  try{DisplaySubmissionFence.capture();throw new AssertionError();}catch(IllegalStateException ok){}
  check(GLES20.flushes==3);
  EGL14.current=EGL14.EGL_NO_DISPLAY;
  try{DisplaySubmissionFence.capture();throw new AssertionError();}catch(IllegalStateException ok){}
 }
}
'''.replace(' FENCE', fence)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'FenceTest.java'
            path.write_text(source)
            built = subprocess.run([str(JAVA / 'javac'), str(path)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(JAVA / 'java'), '-cp', directory, 'FenceTest'], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
        start = method(production, '    private PreparationResult startPreparation(')
        self.assertLess(start.index('displayDependency.awaitOnWorker()'), start.index('jobBridge.prepareHardwareBufferRifeOutput('))
        self.assertLess(start.index('preparationWorker.execute'), start.index('displayDependency.awaitOnWorker()'))
