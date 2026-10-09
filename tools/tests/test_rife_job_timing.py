"""Check exact-job diagnostics without treating missing timestamps as durations."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class RifeJobTimingTest(unittest.TestCase):
    def test_stage_durations_and_missing_stages(self):
        source = (ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        methods = (method(source, 'String timingDiagnostic(') +
                   method(source, 'private static long stageDuration(') +
                   method(source, 'private static boolean samplePreparationReady('))
        poll = method(source, 'private void pollPreparedPresentation(')
        self.assertLess(poll.index('current.ready = true'), poll.index('"RIFE preparation ready"'))
        self.assertIn('" readinessTiming="', poll)
        self.assertNotIn('" jobTiming="', poll)
        start = method(source, 'private PreparationResult startPreparation(')
        self.assertLess(start.index('pending.dispatchedNs ='), start.index('preparationWorker.execute('))
        self.assertLess(start.index('pending.workerStartedNs ='), start.index('displayDependency.awaitOnWorker()'))
        self.assertLess(start.index('displayDependency.awaitOnWorker()'), start.index('pending.dependencyReadyNs ='))
        self.assertLess(start.index('pending.dependencyReadyNs ='), start.index('jobBridge.prepareHardwareBufferRifeOutput('))
        self.assertLess(start.index('jobBridge.prepareHardwareBufferRifeOutput('), start.index('pending.nativeReturnedNs ='))
        code = '''
public class TimingProbe {
 long proofSequence=7, dispatchedNs;
 volatile long workerStartedNs, dependencyReadyNs, nativeReturnedNs;
 METHODS
 static void check(boolean ok) { if(!ok)throw new AssertionError(); }
 public static void main(String[] args) {
  TimingProbe p=new TimingProbe();
  check(!samplePreparationReady(0) && !samplePreparationReady(-1));
  check(samplePreparationReady(1) && samplePreparationReady(16));
  check(!samplePreparationReady(17) && samplePreparationReady(64));
  check(!samplePreparationReady(65) && samplePreparationReady(128));
  String absent=p.timingDiagnostic(900,1000);
  check(absent.contains("queueNs:-1") && absent.contains("nativeCallNs:-1"));
  p.dispatchedNs=100; p.workerStartedNs=130; p.dependencyReadyNs=200; p.nativeReturnedNs=500;
  String full=p.timingDiagnostic(900,1000);
  check(full.contains("proof:7,observedNs:900,deadlineNs:1000"));
  check(full.contains("queueNs:30") && full.contains("dependencyWaitNs:70"));
  check(full.contains("nativeCallNs:300") && full.contains("sinceNativeReturnNs:400"));
  check(stageDuration(500,400)==-1 && stageDuration(500,500)==0);
  p.nativeReturnedNs=0;
  check(p.timingDiagnostic(900,1000).contains("sinceNativeReturnNs:-1"));
 }
}
'''.replace(' METHODS', methods)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'TimingProbe.java'
            unit.write_text(code)
            for command in ([str(JAVA / 'javac'), str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'TimingProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
