"""Execute production ownership gate and callback with swapped output slots."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class RecordingOutputOwnershipTest(unittest.TestCase):
    def test_older_output_can_be_consumed_but_recording_job_survives_callback(self):
        source = (ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        methods = '\n'.join(method(source, signature) for signature in (
            'private boolean outputAccessBlocked(', 'private void swapPreparations()',
            'private void finishOutputPreparation(',
            'private boolean completedPreparationGpuReady('))
        code = '''
public class OwnershipProbe {
 static class PreparedPresentation { long timelineEpoch=1; boolean discardRequested,ready; }
 boolean preparationInFlight=true, appOwnedPresentation=true, closed;
 long timelineEpoch=1; Throwable fatalFailure;
 Runnable preparationCapacityListener;
 void schedulePreparationReadyCheck(PreparedPresentation p,int remaining) {}
 boolean gpuReady=true, pollFailure;
 void pollPreparedPresentation(){if(pollFailure)throw new IllegalStateException("poll");preparedPresentation.ready=gpuReady;}
 PreparedPresentation recordingPresentation, preparedPresentation, queuedPreparation;
 void requireOwner() {} void retireDiscardedPreparations() {} void retireDiscardedEndpoints() {}
 METHODS
 static void check(boolean ok) { if(!ok)throw new AssertionError(); }
 public static void main(String[] args) {
  OwnershipProbe p=new OwnershipProbe();
  int[] refills={0};p.preparationCapacityListener=()->{check(!p.preparationInFlight);refills[0]++;};
  PreparedPresentation older=new PreparedPresentation(), recording=new PreparedPresentation();
  p.preparedPresentation=recording; p.recordingPresentation=recording; p.queuedPreparation=older;
  check(p.outputAccessBlocked(recording)); check(!p.outputAccessBlocked(older));
  p.swapPreparations();
  check(p.preparedPresentation==older && p.queuedPreparation==recording);
  // A pending native try-lock leaves both slots intact; successful bind takes only older.
  check(!p.outputAccessBlocked(p.preparedPresentation));
  p.preparedPresentation=null;
  check(p.outputAccessBlocked(p.queuedPreparation));
  p.finishOutputPreparation(recording,1,null);
  check(refills[0]==1);
  p.gpuReady=false;p.finishOutputPreparation(recording,1,null);check(refills[0]==1);p.gpuReady=true;
  check(p.fatalFailure==null && p.queuedPreparation==recording);
  check(!p.preparationInFlight && p.recordingPresentation==null);
  check(!p.outputAccessBlocked(recording));
  p.preparationInFlight=true; p.recordingPresentation=null;
  check(!p.outputAccessBlocked(older)); // Endpoint-import worker: native try-lock protects access.
  p.appOwnedPresentation=false; check(p.outputAccessBlocked(older));
  p.appOwnedPresentation=true; p.recordingPresentation=recording;
  p.finishOutputPreparation(recording,0,null); check(p.queuedPreparation==null);
  check(refills[0]==1);
  p.preparedPresentation=recording; p.preparationInFlight=true;
  p.finishOutputPreparation(recording,-1,new RuntimeException());
  check(p.fatalFailure!=null && p.preparedPresentation==recording);
  p.fatalFailure=null; p.preparedPresentation=null;
  p.finishOutputPreparation(recording,1,null); check(p.fatalFailure!=null);
  check(refills[0]==1);
  p.fatalFailure=null;p.preparedPresentation=recording;recording.timelineEpoch=0;
  p.finishOutputPreparation(recording,1,null);check(refills[0]==1);
  recording.timelineEpoch=1;recording.discardRequested=true;
  p.finishOutputPreparation(recording,1,null);check(refills[0]==1);
  p.closed=true;recording.discardRequested=false;
  p.finishOutputPreparation(recording,1,null);check(refills[0]==1);
  p.closed=false;p.preparedPresentation=older;p.queuedPreparation=recording;p.pollFailure=true;
  p.finishOutputPreparation(recording,1,null);
  check(p.fatalFailure!=null&&refills[0]==1);
  check(p.preparedPresentation==older&&p.queuedPreparation==recording);
 }
}
'''.replace(' METHODS', methods)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'OwnershipProbe.java'
            unit.write_text(code)
            for command in ([str(JAVA / 'javac'), str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'OwnershipProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
