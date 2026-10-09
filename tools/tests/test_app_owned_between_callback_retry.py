"""Exercise owner-handler retry identity, lifecycle, and unchanged slot planning."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class BetweenCallbackRetryTest(unittest.TestCase):
    def test_owner_task_identity_and_next_physical_slot(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, 'private void scheduleAppOwnedRetry()')
        clock = ROOT / 'unified-android/src/com/thorium/lucent/video/PhysicalPresentationDeadline.java'
        code = '''
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import com.thorium.lucent.video.PhysicalPresentationDeadline;
public class OwnerRetryProbe {
 static class FrameGenerationPresentationRequest {}
 class Handler {
  ArrayDeque<Runnable> tasks=new ArrayDeque<>(); boolean reject;
  boolean postDelayed(Runnable task,long delay){check(delay==1);if(reject)return false;tasks.add(task);return true;}
  void run(){tasks.remove().run();}
 }
 Handler handler=new Handler(); AtomicBoolean closed=new AtomicBoolean();
 boolean externalPresentationFailed, fail; int attempts, failures;
 FrameGenerationPresentationRequest pendingAppOwnedRequest, scheduledAppOwnedRetry;
 void retryPendingAppOwnedPresentation(){attempts++;if(fail)throw new IllegalStateException();}
 void failRuntimePresentation(String message,RuntimeException failure){failures++;externalPresentationFailed=true;}
 BODY
 static void check(boolean value){if(!value)throw new AssertionError();}
 public static void main(String[] args){
  OwnerRetryProbe p=new OwnerRetryProbe();
  p.scheduleAppOwnedRetry();check(p.handler.tasks.isEmpty());
  var a=new FrameGenerationPresentationRequest();var b=new FrameGenerationPresentationRequest();
  p.pendingAppOwnedRequest=a;p.scheduleAppOwnedRetry();p.scheduleAppOwnedRetry();
  check(p.handler.tasks.size()==1);p.handler.run();check(p.attempts==1 && p.scheduledAppOwnedRetry==null);
  p.scheduleAppOwnedRetry();p.pendingAppOwnedRequest=b;p.scheduleAppOwnedRetry();
  p.handler.run();check(p.attempts==1 && p.scheduledAppOwnedRetry==b);
  p.handler.run();check(p.attempts==2);
  p.scheduleAppOwnedRetry();p.closed.set(true);p.handler.run();check(p.attempts==2);
  p.closed.set(false);p.scheduleAppOwnedRetry();p.pendingAppOwnedRequest=null;p.handler.run();check(p.attempts==2);
  p.pendingAppOwnedRequest=b;p.fail=true;p.scheduleAppOwnedRetry();p.handler.run();check(p.failures==1);
  p.externalPresentationFailed=false;p.handler.reject=true;
  try{p.scheduleAppOwnedRetry();throw new AssertionError();}catch(IllegalStateException expected){}
  check(p.scheduledAppOwnedRetry==null);
  // Completing between callbacks leaves the next normal callback available.
  long period=8333333L, anchor=1000000000L;
  var first=PhysicalPresentationDeadline.nextAlignedAppOwnedGenerated(anchor,anchor,period,1,anchor,0);
  long nextCallback=anchor+period;
  var next=PhysicalPresentationDeadline.nextAlignedAppOwnedGenerated(nextCallback,anchor,period,1,nextCallback,first.contentPresentationTimeNs());
  check(next.contentPresentationTimeNs()-first.contentPresentationTimeNs()==period);
  // Negative control: consuming a callback really does introduce the observed gap.
  var late=PhysicalPresentationDeadline.nextAlignedAppOwnedGenerated(nextCallback+period,anchor,period,1,nextCallback+period,first.contentPresentationTimeNs());
  check(late.contentPresentationTimeNs()-first.contentPresentationTimeNs()==2*period);
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'OwnerRetryProbe.java'
            unit.write_text(code)
            for command in ([str(JAVA / 'javac'), '-d', directory, str(clock), str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'OwnerRetryProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
