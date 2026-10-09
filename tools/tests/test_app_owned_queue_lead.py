"""Production admission guard: physical late-frame replay and cutoff boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class AppOwnedQueueLeadTest(unittest.TestCase):
    def test_real_bootstrap_and_generated_use_production_branch(self):
        renderer = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(renderer, 'private void presentAppOwnedExternalBuffered(')
        expression = body.split('if (System.nanoTime() >= request.hardCompletionDeadlineNs()', 1)[1].split(' {', 1)[0]
        expression = ('System.nanoTime() >= request.hardCompletionDeadlineNs()' + expression)[:-1]
        expression = expression.replace('System.nanoTime()', 'now')
        source = ROOT / 'unified-android/src/com/thorium/lucent/video/PhysicalPresentationDeadline.java'
        java = '''
import com.thorium.lucent.video.PhysicalPresentationDeadline;
class BootstrapAdmissionProbe {
 static class Request {
  long hardCompletionDeadlineNs(){return 100000000L;}
  long desiredPhysicalPresentTimeNs(){return 102000000L;}
 }
 static class Rate {long panelPeriodNs(){return 8333333L;}}
 static boolean rejected(boolean generated,long now){
  Request request=new Request();Rate frameRate=new Rate();
  return EXPRESSION;
 }
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  // Direct bootstrap: eight ms until target is valid; generated is too late.
  check(!rejected(false,94000000L));check(rejected(true,94000000L));
  // Neither kind can cross the original hard deadline.
  check(rejected(false,100000000L));check(rejected(true,100000000L));
  // A genuinely early generated request can still proceed.
  check(!rejected(true,85000000L));
 }
}
'''.replace('EXPRESSION', expression)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'BootstrapAdmissionProbe.java'
            unit.write_text(java)
            for command in ([str(JAVA / 'javac'), '-d', directory, str(source), str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'BootstrapAdmissionProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_measured_failure_and_boundaries(self):
        source = ROOT / 'unified-android/src/com/thorium/lucent/video/PhysicalPresentationDeadline.java'
        code = '''
import com.thorium.lucent.video.PhysicalPresentationDeadline;
class QueueLeadProbe {
 static void check(boolean value) { if (!value) throw new AssertionError(); }
 static boolean admit(long target,long period,long now) {
  return PhysicalPresentationDeadline.appOwnedSubmissionHasQueueLead(target,period,now);
 }
 public static void main(String[] args) {
  long p=8333333L, target=97826065393139L;
  // Real Thor frame 1340: both bind start and swap completion were too late.
  check(!admit(target,p,97826058176794L));
  check(!admit(target,p,97826059211065L));
  for(long period:new long[]{8333333L,16666667L}) {
   long cutoff=target-period-PhysicalPresentationDeadline.THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS;
   check(admit(target,period,cutoff));
   check(admit(target,period,cutoff-1));
   check(!admit(target,period,cutoff+1));
   check(!admit(target,period,target));
   check(!admit(target,period,target+1));
  }
  check(!admit(target,0,1)); check(!admit(target,p,0));
  check(!admit(Long.MAX_VALUE,Long.MAX_VALUE,1));
 }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'QueueLeadProbe.java'
            unit.write_text(code)
            for command in ([str(JAVA / 'javac'), '-d', directory, str(source), str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'QueueLeadProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_guard_before_and_after_bind(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, 'private void presentAppOwnedExternalBuffered(')
        guard = 'PhysicalPresentationDeadline.appOwnedSubmissionHasQueueLead('
        self.assertEqual(body.count(guard), 2)
        self.assertEqual(body.count('generated && !' + guard), 2)
        self.assertLess(body.index(guard), body.index('transport.bindAppOwnedOutput('))
        self.assertLess(body.index('transport.bindAppOwnedOutput('), body.rindex(guard))
        self.assertLess(body.rindex(guard), body.index('GLES20.glBindFramebuffer('))
        after = body[body.rindex(guard):body.index('boolean swapSucceeded')]
        self.assertIn('transport.releaseAppOwnedOutput(generatedOutput, false)', after)
        self.assertIn('frameRate.dropBufferedPresentationSlot()', after)
