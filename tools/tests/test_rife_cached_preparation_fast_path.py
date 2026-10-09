"""Execute production prepare gates: cached identity never touches native pools."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]


class CachedPreparationFastPathTest(unittest.TestCase):
    def test_cached_busy_and_uncached_paths(self):
        source = (ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        body = method(source, '@Override public PreparationResult prepare(').replace('@Override ', '')
        code = '''
class CachedPreparationProbe {
 enum PreparationResult { NOT_READY, ALREADY_READY, SUBMITTED }
 static class FrameGenerationPreparationRequest { boolean generated=true; boolean isGenerated(){return generated;} }
 class Bridge {void pollBoundHardwareBufferRifeOutputs(){polls++;}}
 Bridge bridge=new Bridge(),secondaryBridge=new Bridge();
 boolean generatedRatePathActive=true,preparationInFlight,appOwnedPresentation=true;
 boolean surfaceControlPresentation,nativePending,nativeReleaseScheduled,cached,invalid;
 Object nativeInFlight; int polls,drains,starts,validations;
 void requireOwner(){} void requireOpen(){}
 void validatePreparationIdentity(FrameGenerationPreparationRequest r){validations++;if(invalid)throw new IllegalStateException();}
 boolean hasReadyOutput(FrameGenerationPreparationRequest r){return cached;}
 void drainDeferredOutputReleases(){drains++;}
 PreparationResult startPreparation(FrameGenerationPreparationRequest r){starts++;return PreparationResult.SUBMITTED;}
 BODY
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  var p=new CachedPreparationProbe();var r=new FrameGenerationPreparationRequest();
  p.cached=true;p.preparationInFlight=true;
  check(p.prepare(r)==PreparationResult.ALREADY_READY);
  check(p.polls==0&&p.drains==0&&p.starts==0&&p.validations==1);
  p.invalid=true;try{p.prepare(r);throw new AssertionError();}catch(IllegalStateException expected){}
  p.invalid=false;p.cached=false;
  check(p.prepare(r)==PreparationResult.NOT_READY&&p.polls==0);
  p.preparationInFlight=false;check(p.prepare(r)==PreparationResult.SUBMITTED);
  check(p.polls==2&&p.drains==1&&p.starts==1);
  p.cached=true;p.generatedRatePathActive=false;
  check(p.prepare(r)==PreparationResult.NOT_READY);
  p.generatedRatePathActive=true;r.generated=false;
  check(p.prepare(r)==PreparationResult.NOT_READY);
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'CachedPreparationProbe.java'
            unit.write_text(code)
            for command in ([str(JAVA / 'javac'), '-d', directory, str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'CachedPreparationProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
