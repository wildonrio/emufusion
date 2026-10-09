"""Run the production listener against an ImageReader with Android's quota rule."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]


class RifeImageAcquisitionTest(unittest.TestCase):
    def test_full_pool_callback_and_release(self):
        production = ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java'
        body = method(production.read_text(),
                      '    @Override public void onImageAvailable(ImageReader source)')
        body += method(production.read_text(),
                       '    @Override public boolean canAcceptEndpoint()')
        source = '''
import java.util.*;
public class AcquisitionTest {
 static class android {static class os {static class Trace {
  static int depth;
  static void beginSection(String name){depth++;}
  static void endSection(){if(--depth<0)throw new AssertionError("unbalanced trace");}
 }}}
 static final int MAX_IMAGES=8; static final String TAG="test";
 static class Log {static void w(String a,String b){}}
 static class HardwareBuffer {
  static final int RGBA_8888=1,USAGE_GPU_SAMPLED_IMAGE=2;
  boolean isClosed(){return false;} int getWidth(){return 256;}
  int getHeight(){return 240;} int getLayers(){return 1;}
  int getFormat(){return 1;} long getUsage(){return 2;} void close(){}
 }
 static class Image {
  ImageReader owner;long timestamp;boolean closed;
  Image(ImageReader o,long t){owner=o;timestamp=t;}
  long getTimestamp(){return timestamp;}
  HardwareBuffer getHardwareBuffer(){return new HardwareBuffer();}
  void close(){if(closed)throw new AssertionError("double close");closed=true;owner.acquired--;}
 }
 static class ImageReader {
  int acquired,calls;ArrayDeque<Long> queued=new ArrayDeque<>();
  Image acquireNextImage(){calls++;if(acquired>=8)throw new IllegalStateException("maxImages");
   Long t=queued.poll();if(t==null)return null;acquired++;return new Image(this,t);}
 }
 static class ExpectedEndpoint {long sequence,timestampNs;boolean discard;
  ExpectedEndpoint(long s){sequence=s;timestampNs=s*1000;}}
 static class RetainedEndpoint {Image image;
  RetainedEndpoint(long s,long t,Image i){image=i;}}
 ArrayDeque<ExpectedEndpoint> expected=new ArrayDeque<>();
 Map<Long,RetainedEndpoint> retained=new HashMap<>();
 boolean closed;int width=256,height=240;long endpointDiscontinuities;
 RuntimeException fatalFailure;
 ImageReader reader;
 void requireOpen(){if(closed||fatalFailure!=null)throw new IllegalStateException();}
 void requireOwner(){} void scheduleEndpointPreparation(){}
 // This harness tests owner-side identity/quota handling. Worker handoff is
 // requires separate tests; make completed acquisition immediately available here.
 Image pollAcquiredEndpoint(ImageReader source){return source.acquireNextImage();}
 BODY
 void enqueue(ImageReader r,long s){expected.add(new ExpectedEndpoint(s));r.queued.add(s*1000);}
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  AcquisitionTest t=new AcquisitionTest();ImageReader r=new ImageReader();
  for(long s=1;s<=8;s++)t.enqueue(r,s);
  t.onImageAvailable(r);
  check(t.fatalFailure==null&&r.acquired==8&&r.calls==8&&t.expected.isEmpty());
  t.onImageAvailable(r);check(r.calls==8&&t.fatalFailure==null);
  t.retained.remove(1L).image.close();t.enqueue(r,9);
  t.onImageAvailable(r);check(r.calls==9&&r.acquired==8&&t.retained.containsKey(9L));
  t.retained.remove(2L).image.close();t.enqueue(r,10);t.expected.peek().discard=true;
  t.onImageAvailable(r);check(r.acquired==7&&t.fatalFailure==null&&t.expected.isEmpty());
  // Unannounced/mismatched images still fail closed and release their image.
  r.queued.add(999999L);t.onImageAvailable(r);
  check(t.fatalFailure!=null&&r.acquired==7);
  // Upload tasks run before queued listener notifications. Admission must
  // acquire each preceding swap without waiting for a listener callback.
  AcquisitionTest batch=new AcquisitionTest();batch.reader=new ImageReader();
  for(long s=1;s<=8;s++) {
   check(batch.canAcceptEndpoint());batch.enqueue(batch.reader,s);
  }
  check(!batch.canAcceptEndpoint());
  check(batch.retained.size()==8&&batch.expected.isEmpty()&&
        batch.endpointDiscontinuities==0&&batch.fatalFailure==null);
  batch.retained.remove(1L).image.close();
  check(batch.canAcceptEndpoint());batch.enqueue(batch.reader,9);
  batch.onImageAvailable(batch.reader);
  check(batch.retained.size()==8&&batch.retained.containsKey(9L));
  check(android.os.Trace.depth==0);
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'AcquisitionTest.java'
            path.write_text(source)
            result = subprocess.run([str(JAVA / 'javac'), str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(JAVA / 'java'), '-cp', directory, 'AcquisitionTest'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
