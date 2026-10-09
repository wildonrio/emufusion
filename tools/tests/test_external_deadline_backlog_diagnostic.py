"""Characterize future-slot debt; passing is NOT frame-pacing acceptance."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_framegen_startup_fallback import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class ExternalDeadlineBacklogDiagnostic(unittest.TestCase):
    def test_renderer_waits_without_committing_future_slot_debt(self):
        renderer = ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java'
        body = method(renderer.read_text(),
                      '    private static boolean directExternalSubmissionWindowOpen(')
        production = ROOT / 'unified-android/src/com/thorium/lucent/video/PhysicalPresentationDeadline.java'
        harness = '''
import com.thorium.lucent.video.PhysicalPresentationDeadline;
public class WindowTest {
 BODY
 public static void main(String[] args) {
  long p=8333333L, now=1000000000L, last=0, anchor=now;
  int accepted=0,waited=0;
  for(int i=0;i<1200;i++,now+=p) {
   var d=PhysicalPresentationDeadline.nextAlignedOutputDirect(now,anchor,p,2,now,last);
   if(!d.valid())throw new AssertionError();
   if(!directExternalSubmissionWindowOpen(d.contentPresentationTimeNs(),now,p,2)) {
    waited++; continue; // Same as renderer: no selector/commit/endpoint advance.
   }
   last=d.contentPresentationTimeNs();accepted++;
   if(last-now>8000000L+2*p)throw new AssertionError("future debt");
  }
  if(accepted<599||accepted>602||waited<598)throw new AssertionError("not source paced");
  if(directExternalSubmissionWindowOpen(now,now,p,2)||
     directExternalSubmissionWindowOpen(now+1,now,Long.MAX_VALUE,2)||
     directExternalSubmissionWindowOpen(now+1,now,p,0))throw new AssertionError("invalid accepted");
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'WindowTest.java'
            source.write_text(harness)
            subprocess.run([str(JAVA / 'javac'), '-d', directory,
                            str(production), str(source)], check=True, capture_output=True)
            subprocess.run([str(JAVA / 'java'), '-cp', directory, 'WindowTest'],
                           check=True, capture_output=True)

    def test_startup_burst_debt_survives_normal_source_rate(self):
        production = ROOT / ('unified-android/src/com/thorium/lucent/video/'
                             'PhysicalPresentationDeadline.java')
        harness = '''
import com.thorium.lucent.video.PhysicalPresentationDeadline;
public class BacklogDiagnostic {
 public static void main(String[] args) {
  long period=8333333L, anchor=1000000000L, now=anchor, last=0;
  // Model ten startup callbacks with a queued endpoint on every callback.
  // A 60-Hz output reserves two scans per accepted submission on 120 Hz.
  for(int i=0;i<10;i++) {
   var d=PhysicalPresentationDeadline.nextAlignedOutputDirect(
       now,anchor,period,2,now,last);
   if(!d.valid()) throw new AssertionError("invalid burst target");
   last=d.contentPresentationTimeNs(); now+=period;
  }
  long initialDebt=last-now;
  long minimumLead=Long.MAX_VALUE,maximumLead=0;
  // Return to exactly one source endpoint every two scans for ten seconds.
  for(int i=0;i<600;i++) {
   var d=PhysicalPresentationDeadline.nextAlignedOutputDirect(
       now,anchor,period,2,now,last);
   if(!d.valid()) throw new AssertionError("invalid steady target");
   last=d.contentPresentationTimeNs();
   minimumLead=Math.min(minimumLead,last-now);
   maximumLead=Math.max(maximumLead,last-now);
   now+=2*period;
  }
  if(initialDebt<8*period || minimumLead<initialDebt)
   throw new AssertionError("diagnostic no longer reproduces backlog");
  System.out.println("initialDebtNs="+initialDebt+" steadyMinLeadNs="+
      minimumLead+" steadyMaxLeadNs="+maximumLead);
 }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'BacklogDiagnostic.java'
            source.write_text(harness)
            subprocess.run([str(JAVA / 'javac'), '-d', directory,
                            str(production), str(source)], check=True,
                           capture_output=True, text=True)
            result = subprocess.run([str(JAVA / 'java'), '-cp', directory,
                                     'BacklogDiagnostic'], check=True,
                                    capture_output=True, text=True)
            print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
