from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA

ROOT=Path(__file__).resolve().parents[2]


class ExternalTimingCompletenessTest(unittest.TestCase):
    def test_production_gate_rejects_unsubmitted_slots(self):
        source=(ROOT/'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        expression=source.split('boolean externalTimingPassed =',1)[1].split(';',1)[0]
        code='''
class Probe {
 static class Rate {long missing;long bufferedUnderrunCount(){return missing;}}
 static class Evidence {boolean passed=true;boolean timingQualified(){return passed;}}
 Rate frameRate=new Rate();Evidence externalPresentationEvidence=new Evidence();
 Evidence appOwnedExternalPresentationEvidence=new Evidence();
 boolean externalBackendOwnsPresentation,externalAppOwnsPresentation;
 boolean qualified(){return EXPRESSION;}
 public static void main(String[] args){
  for(boolean backend:new boolean[]{false,true}){
   Probe p=new Probe();p.externalBackendOwnsPresentation=backend;p.externalAppOwnsPresentation=!backend;
   if(!p.qualified())throw new AssertionError("clean timing rejected");
   for(long missing:new long[]{1,299}){
    p.frameRate.missing=missing;
    if(p.qualified())throw new AssertionError("missing output qualified");
   }
   p.frameRate.missing=0;p.externalPresentationEvidence.passed=false;
   p.appOwnedExternalPresentationEvidence.passed=false;
   if(p.qualified())throw new AssertionError("bad physical timing qualified");
  }
 }
}
'''.replace('EXPRESSION',expression)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Probe.java';path.write_text(code)
            for cmd in ([str(JAVA/'javac'),str(path)],[str(JAVA/'java'),'-cp',directory,'Probe']):
                result=subprocess.run(cmd,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
