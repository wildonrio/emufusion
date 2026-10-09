"""Execute renderer retry orchestration; no device cadence acceptance implied."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class ImmutableRetryTest(unittest.TestCase):
    def test_request_is_not_replanned_and_successor_is_submitted_once(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, 'private boolean retryPendingAppOwnedPresentation()')
        present = method(source, 'private void presentAppOwnedExternalBuffered(')
        pending = present.split('if (generatedOutput == null) {', 1)[1].split('}', 1)[0]
        self.assertNotIn('dropBufferedPresentationSlot', pending)
        self.assertIn('System.nanoTime() >= request.hardCompletionDeadlineNs()', present)
        self.assertIn('pendingAppOwnedRequest = null;', method(source, 'private void invalidateBufferedPairForReprime(boolean'))
        code = '''
public class RetryProbe {
 static class FrameGenerationPresentationRequest {
  long deadline=1000; long presentationEpoch(){return 1;}
 }
 static class FrameGenerationPreparationRequest {}
 static class AdaptiveFrameRateController { static final int PRESENT_SYNTHETIC=2; }
 static class Controller {
  long count; boolean aborted;
  long bufferedPresentationCount(){return count;}
  void abortBufferedPresentation(){aborted=true;}
 }
 Controller frameRate=new Controller(); long epoch=1;
 FrameGenerationPresentationRequest pendingAppOwnedRequest, seen;
 FrameGenerationPreparationRequest pendingAppOwnedPreparation;
 float pendingAppOwnedPhase; boolean ready, fail; int submissions, attempts;
 long schedulerPresentationEpoch(){return epoch;}
 void invalidateBufferedPairForReprime(boolean reset){pendingAppOwnedRequest=null;pendingAppOwnedPreparation=null;}
 void submitExternalGeneratedPreparation(FrameGenerationPreparationRequest request){submissions++;}
 void presentAppOwnedExternalBuffered(FrameGenerationPresentationRequest request,int kind,float phase){
  attempts++; check(kind==2); check(request.deadline==1000); seen=request;
  if(fail)throw new IllegalStateException();
  if(ready){frameRate.count++;pendingAppOwnedRequest=null;pendingAppOwnedPreparation=null;}
 }
 BODY
 static void check(boolean value){if(!value)throw new AssertionError();}
 public static void main(String[] args){
  RetryProbe p=new RetryProbe();
  FrameGenerationPresentationRequest original=new FrameGenerationPresentationRequest();
  p.pendingAppOwnedRequest=original;p.pendingAppOwnedPreparation=new FrameGenerationPreparationRequest();
  check(p.retryPendingAppOwnedPresentation());check(p.seen==original && p.pendingAppOwnedRequest==original);
  check(p.frameRate.count==0 && p.submissions==0);
  p.ready=true;check(p.retryPendingAppOwnedPresentation());
  check(p.seen==original && p.frameRate.count==1 && p.submissions==1);
  check(!p.retryPendingAppOwnedPresentation() && p.attempts==2);
  p.pendingAppOwnedRequest=original;p.epoch=2;
  check(!p.retryPendingAppOwnedPresentation() && p.pendingAppOwnedRequest==null && p.attempts==2);
  p.epoch=1;p.pendingAppOwnedRequest=original;p.fail=true;
  try{p.retryPendingAppOwnedPresentation();throw new AssertionError();}catch(IllegalStateException expected){}
  check(p.frameRate.aborted && p.pendingAppOwnedRequest==null);
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'RetryProbe.java'
            unit.write_text(code)
            for command in ([str(JAVA / 'javac'), str(unit)], [str(JAVA / 'java'), '-cp', directory, 'RetryProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
