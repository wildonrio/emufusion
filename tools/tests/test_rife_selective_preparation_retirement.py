"""Execute selective obsolete-job retirement without global cache invalidation."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import method as extract_method

ROOT = Path(__file__).resolve().parents[2]


class SelectivePreparationRetirementTest(unittest.TestCase):
    def test_valid_jobs_survive_obsolete_sibling(self):
        source = (ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        method = source.split('private void retireDiscardedPreparations()', 1)[1].split('private void discardPreparedPresentation()', 1)[0]
        discard = extract_method(source, 'private void discardCurrentPreparation()').split('private void discardCurrentPreparation()', 1)[1]
        discard = discard.replace('PreparedPresentation', 'Job')
        stale = source.split('private boolean retireStalePreparation(', 1)[1].split('PreparedPresentation current = preparedPresentation;', 1)[0]
        self.assertIn('retireDiscardedPreparations();', stale)
        self.assertNotIn('discardPreparedPresentation();', stale)
        completion = source.split('private void finishOutputPreparation(', 1)[1].split('@Override public PreparationReadiness', 1)[0]
        self.assertIn('retireDiscardedPreparations();', completion)
        self.assertNotIn('discardPreparedPresentation();', completion)
        polling = source.split('private void pollPreparedPresentation()', 1)[1].split('if (current.ready)', 1)[0]
        self.assertIn('retireDiscardedPreparations();', polling)
        self.assertNotIn('discardPreparedPresentation();', polling)
        scene_cut = source.split('        if (proof.sceneCutRisk) {', 1)[1].split('        current.gpuWorkNs', 1)[0]
        java = '''class RetirementProbe {
 class Bridge {
  boolean discardPreparedHardwareBufferRifeOutput(long proof){retires++;return !nativeBusy;}
 }
 class Job { boolean discardRequested; long proofSequence=1;
  Bridge jobBridge=new Bridge(); Job(boolean old){discardRequested=old;} }
 Job preparedPresentation,queuedPreparation;
 boolean preparationInFlight, nativeBusy;
 int retires;
 void retireDiscardedEndpoints(){}
 private void discardCurrentPreparation()''' + discard + '''
 void swapPreparations(){Job old=preparedPresentation;preparedPresentation=queuedPreparation;queuedPreparation=old;}
 private void retireDiscardedPreparations()''' + method + '''
 void rejectSceneCut(Job current) { if(true) {''' + scene_cut + '''}
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] args){
  for(int mask=0;mask<4;mask++)for(boolean busy:new boolean[]{false,true}){
   RetirementProbe p=new RetirementProbe();p.nativeBusy=busy;
   Job a=p.new Job((mask&1)!=0),b=p.new Job((mask&2)!=0);
   p.preparedPresentation=a;p.queuedPreparation=b;p.retireDiscardedPreparations();
   check(p.preparedPresentation==((a.discardRequested&&!busy)?null:a));
   check(p.queuedPreparation==((b.discardRequested&&!busy)?null:b));
   check(p.retires==Integer.bitCount(mask));
  }
  RetirementProbe p=new RetirementProbe();p.preparationInFlight=true;
  Job a=p.new Job(true);p.preparedPresentation=a;p.retireDiscardedPreparations();
  check(p.preparedPresentation==a&&p.retires==0);
  p=new RetirementProbe();p.retireDiscardedPreparations();check(p.retires==0);
  p=new RetirementProbe();Job cut=p.new Job(false),valid=p.new Job(false);
  p.preparedPresentation=cut;p.queuedPreparation=valid;
  p.rejectSceneCut(cut);
  check(p.preparedPresentation==null&&p.queuedPreparation==valid);
  check(!valid.discardRequested&&p.retires==1);
 }
}'''
        jdk = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'RetirementProbe.java'
            path.write_text(java)
            subprocess.run([str(jdk / 'javac'), str(path)], check=True, capture_output=True)
            subprocess.run([str(jdk / 'java'), '-cp', directory, 'RetirementProbe'], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
