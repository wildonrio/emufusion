"""Execute production acquisition/handoff and shutdown with controlled queues."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]


class AsyncAcquisitionTest(unittest.TestCase):
    def test_queued_handoff_and_shutdown(self):
        text = (ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        poll = method(text, '    private Image pollAcquiredEndpoint(ImageReader source)')
        result_class = method(text, '    private static final class AcquiredEndpoint')
        close = method(text, '    @Override public void close()')
        drain = close[close.index('        acquisitionWorker.shutdown();'):close.index('        preparationWorker.shutdown();')]
        source = r'''
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
public class AsyncTest {
 static class android {static class os {static class Trace {
  static int depth;static void beginSection(String n){depth++;}
  static void endSection(){if(--depth<0)throw new AssertionError();}
 }}}
 static class Image {int closes;void close(){if(++closes!=1)throw new AssertionError();}}
 static class ImageReader {
  Image next; RuntimeException error; int calls;
  Image acquireNextImage(){calls++;if(error!=null)throw error;Image i=next;next=null;return i;}
 }
 static class Worker {
  ArrayDeque<Runnable> jobs=new ArrayDeque<>(); boolean reject,stopped,terminated=true,interrupted;
  void execute(Runnable r){if(reject)throw new RejectedExecutionException();jobs.add(r);}
  void run(){jobs.remove().run();}
  void shutdown(){stopped=true;}
  boolean awaitTermination(long n,TimeUnit u)throws InterruptedException{return terminated;}
  void shutdownNow(){interrupted=true;}
 }
 static class Owner {ArrayDeque<Runnable> jobs=new ArrayDeque<>();boolean post(Runnable r){jobs.add(r);return true;}}
 static final int MAX_IMAGES=8;
 Worker acquisitionWorker=new Worker();Owner owner=new Owner();
 ArrayDeque<Integer> expected=new ArrayDeque<>();Map<Integer,Image> retained=new HashMap<>();
 AtomicReference<AcquiredEndpoint> acquiredEndpoint=new AtomicReference<>();
 boolean acquisitionInFlight,closed;
 Image delivered;int callbacks;
 void onImageAvailable(ImageReader reader){if(closed)return;callbacks++;delivered=pollAcquiredEndpoint(reader);}
 RESULT
 POLL
 void drain(){DRAIN}
 static void check(boolean v){if(!v)throw new AssertionError();}
 public static void main(String[] args){
  AsyncTest t=new AsyncTest();ImageReader r=new ImageReader();Image first=new Image();r.next=first;
  check(t.pollAcquiredEndpoint(r)==null&&r.calls==0&&t.acquisitionWorker.jobs.isEmpty());
  t.expected.add(1);
  check(t.pollAcquiredEndpoint(r)==null&&r.calls==0&&t.acquisitionInFlight);
  for(int i=0;i<20;i++)check(t.pollAcquiredEndpoint(r)==null);
  check(t.acquisitionWorker.jobs.size()==1); // owner never executes blocking acquisition
  t.acquisitionWorker.run();check(r.calls==1&&t.delivered==null);
  t.owner.jobs.remove().run();check(t.delivered==first&&!t.acquisitionInFlight);
  check(t.acquiredEndpoint.get()==null&&first.closes==0);
  // Null completion clears in-flight without spinning; later admission retries.
  t.pollAcquiredEndpoint(r);t.acquisitionWorker.run();t.owner.jobs.remove().run();
  check(!t.acquisitionInFlight&&t.acquisitionWorker.jobs.isEmpty());
  Image second=new Image();r.next=second;t.pollAcquiredEndpoint(r);t.acquisitionWorker.run();
  check(t.pollAcquiredEndpoint(r)==second); // admission can consume before posted callback
  check(first!=second&&second.closes==0);
  t.owner.jobs.remove().run();check(t.acquisitionWorker.jobs.size()==1);
  r.error=new IllegalStateException("acquire failed");t.acquisitionWorker.run();
  try{t.pollAcquiredEndpoint(r);throw new AssertionError();}catch(IllegalStateException e){check(e==r.error);}
  check(!t.acquisitionInFlight);
  AsyncTest rejected=new AsyncTest();rejected.expected.add(1);rejected.acquisitionWorker.reject=true;
  try{rejected.pollAcquiredEndpoint(r);throw new AssertionError();}catch(RejectedExecutionException ok){}
  check(!rejected.acquisitionInFlight);
  AsyncTest full=new AsyncTest();full.expected.add(1);
  for(int i=0;i<8;i++)full.retained.put(i,new Image());
  check(full.pollAcquiredEndpoint(r)==null&&full.acquisitionWorker.jobs.isEmpty());
  AsyncTest stopped=new AsyncTest();Image pending=new Image();
  stopped.acquiredEndpoint.set(new AcquiredEndpoint(pending,null));stopped.acquisitionInFlight=true;
  stopped.closed=true;stopped.drain();stopped.onImageAvailable(r);
  check(pending.closes==1&&stopped.callbacks==0&&!stopped.acquisitionInFlight);
  stopped.drain();check(pending.closes==1);
  AsyncTest timeout=new AsyncTest();Image live=new Image();
  timeout.acquiredEndpoint.set(new AcquiredEndpoint(live,null));timeout.acquisitionWorker.terminated=false;
  try{timeout.drain();throw new AssertionError();}catch(IllegalStateException ok){}
  check(live.closes==0&&timeout.acquiredEndpoint.get()!=null&&timeout.acquisitionWorker.interrupted);
  check(android.os.Trace.depth==0);
 }
}
'''.replace(' RESULT', result_class).replace(' POLL', poll).replace('DRAIN', drain)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'AsyncTest.java'
            path.write_text(source)
            built = subprocess.run([str(JAVA / 'javac'), str(path)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(JAVA / 'java'), '-cp', directory, 'AsyncTest'], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
