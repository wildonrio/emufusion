"""Exercise the production EGL priority block with a deterministic fake driver."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class ExternalGpuPriorityTest(unittest.TestCase):
    def test_driver_accept_ignore_refuse_and_unsupported(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        block = source.split('        int[] contextAttributes =', 1)[1].split('        int[] surfaceAttributes =', 1)[0]
        java = '''class PriorityProbe {
 static class EGL14 {
  static final int EGL_CONTEXT_CLIENT_VERSION=1,EGL_NONE=2,EGL_EXTENSIONS=3,EGL_NO_CONTEXT=0;
  static String extensions="EGL_IMG_context_priority";
  static int calls, hints, mode, error, queries;
  static String eglQueryString(int d,int n){return extensions;}
  static int eglCreateContext(int d,int c,int share,int[] a,int offset){
   calls++; boolean hint=a.length==5;if(hint)hints++;
   if(hint&&mode==1){error=123;return 0;}return 7;
  }
  static int eglGetError(){int e=error;error=0;return e;}
  static boolean eglQueryContext(int d,int c,int n,int[] out,int offset){queries++;out[0]=mode==2?0x3102:0x3101;return true;}
 }
 static class Log {static void w(String t,String s){}static void i(String t,String s){}}
 int eglDisplay=1,eglContext,requestedEglContextMajor=3;
 Object externalTransport=new Object();boolean appOwnedPresentation=true;
 static final String TAG="probe";
 void fail(String s){throw new AssertionError(s);}
 void run(){int[] configs={1};int[] contextAttributes =''' + block + '''}
 static void check(boolean value){if(!value)throw new AssertionError();}
 static void reset(){EGL14.calls=EGL14.hints=EGL14.queries=EGL14.error=0;}
 public static void main(String[] args){
  for(int mode=0;mode<3;mode++){
   reset();EGL14.mode=mode;PriorityProbe p=new PriorityProbe();p.run();
   check(p.eglContext==7&&EGL14.hints==1&&EGL14.queries==1&&EGL14.error==0);
   check(EGL14.calls==(mode==1?2:1));
  }
  for(String ext:new String[]{null,"","EGL_IMG_context_priority_other"}){
   reset();EGL14.extensions=ext;new PriorityProbe().run();check(EGL14.calls==1&&EGL14.hints==0&&EGL14.queries==0);
  }
  EGL14.extensions="EGL_IMG_context_priority";
  reset();PriorityProbe off=new PriorityProbe();off.externalTransport=null;off.run();check(EGL14.hints==0);
  reset();PriorityProbe other=new PriorityProbe();other.appOwnedPresentation=false;other.run();check(EGL14.hints==0);
 }
}'''
        jdk=Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'PriorityProbe.java'
            path.write_text(java)
            subprocess.run([str(jdk/'javac'),str(path)],check=True,capture_output=True)
            subprocess.run([str(jdk/'java'),'-cp',directory,'PriorityProbe'],check=True,capture_output=True)

if __name__ == '__main__':
    unittest.main()
