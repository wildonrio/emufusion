"""Exercise exact deferred identity, epoch and consumed-pair retirement."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class DeferredPreparationTest(unittest.TestCase):
    def test_identity_and_retirement(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, 'private boolean retryDeferredExternalPreparation()')
        java = '''
class DeferredProbe {
 static class FrameGenerationPreparationRequest {
  long epoch=1,left=10;
  long presentationEpoch(){return epoch;}long leftSequence(){return left;}
 }
 FrameGenerationPreparationRequest deferredExternalPreparation,submitted;
 long epoch=1,activeLeftSequence=10;boolean activePairSyntheticCommitted;
 long schedulerPresentationEpoch(){return epoch;}
 void submitExternalGeneratedPreparation(FrameGenerationPreparationRequest r){submitted=r;}
 BODY
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  for(int scenario=0;scenario<5;scenario++){
   var p=new DeferredProbe();var original=new FrameGenerationPreparationRequest();
   p.deferredExternalPreparation=original;
   if(scenario==1)p.epoch++;
   if(scenario==2)p.activeLeftSequence++;
   if(scenario==3)p.activePairSyntheticCommitted=true;
   if(scenario==4){original.left++;p.activePairSyntheticCommitted=true;}
   boolean valid=scenario==0||scenario==4;
   check(p.retryDeferredExternalPreparation()==valid);
   check(p.submitted==(valid?original:null));
   check(p.deferredExternalPreparation==(valid?original:null));
  }
  check(!new DeferredProbe().retryDeferredExternalPreparation());
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'DeferredProbe.java'; unit.write_text(java)
            for command in ([str(JAVA / 'javac'), '-d', directory, str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'DeferredProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
