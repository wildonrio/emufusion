"""Execute immediate-preparation result handling before speculative lookahead."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class PreparationPriorityTest(unittest.TestCase):
    def test_not_ready_cannot_authorize_farther_future_work(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, 'private void submitExternalGeneratedPreparation(')
        java = '''
class PriorityProbe {
 static class FrameGenerationPreparationRequest {
  long epoch=1,left=10;long presentationEpoch(){return epoch;}long leftSequence(){return left;}
 }
 static class ExternalFrameGenerationTransport {
  enum PreparationResult { SUBMITTED, ALREADY_READY, NOT_READY, UNKNOWN }
  PreparationResult result; int calls;FrameGenerationPreparationRequest last;
  PreparationResult prepare(FrameGenerationPreparationRequest r){calls++;last=r;return result;}
 }
 ExternalFrameGenerationTransport externalTransport=new ExternalFrameGenerationTransport();
 FrameGenerationPreparationRequest deferredExternalPreparation;
 long activeLeftSequence=10;boolean activePairSyntheticCommitted;
 long schedulerPresentationEpoch(){return 1;}
 int future;void prepareExternalLookahead(){future++;}
 BODY
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  for(var result:ExternalFrameGenerationTransport.PreparationResult.values()){
   var p=new PriorityProbe();p.externalTransport.result=result;
   boolean failed=false;
   try{p.submitExternalGeneratedPreparation(new FrameGenerationPreparationRequest());}
   catch(IllegalStateException expected){failed=true;}
   check(p.externalTransport.calls==1);
   check(failed==(result==ExternalFrameGenerationTransport.PreparationResult.UNKNOWN));
   boolean admitted=result==ExternalFrameGenerationTransport.PreparationResult.SUBMITTED ||
                    result==ExternalFrameGenerationTransport.PreparationResult.ALREADY_READY;
   check(p.future==(admitted?1:0));
   check((p.deferredExternalPreparation!=null)==(result==ExternalFrameGenerationTransport.PreparationResult.NOT_READY));
  }
  var p=new PriorityProbe();p.submitExternalGeneratedPreparation(null);
  check(p.future==0&&p.externalTransport.calls==0);
  for(int scenario=0;scenario<4;scenario++){
   p=new PriorityProbe();var old=new FrameGenerationPreparationRequest();
   var later=new FrameGenerationPreparationRequest();later.left=11;
   p.externalTransport.result=ExternalFrameGenerationTransport.PreparationResult.NOT_READY;
   p.submitExternalGeneratedPreparation(old);
   if(scenario==1)old.epoch=2;
   if(scenario==2)p.activeLeftSequence=11;
   if(scenario==3)p.activePairSyntheticCommitted=true;
   p.submitExternalGeneratedPreparation(later);
   check(p.externalTransport.last==(scenario==0?old:later));
   check(p.deferredExternalPreparation==(scenario==0?old:later));
   check(p.future==0);
  }
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'PriorityProbe.java'; unit.write_text(java)
            for command in ([str(JAVA / 'javac'), '-d', directory, str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'PriorityProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
