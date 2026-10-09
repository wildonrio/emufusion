"""Execute the production pair-availability predicate during async work."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class PairWorkerReadinessTest(unittest.TestCase):
    def test_retained_pair_is_not_hidden_by_successor_work(self):
        source = (ROOT / 'unified-android/qualification-src/com/thorium/preview/game/RifePresentationTransport.java').read_text()
        method = source.split('@Override public boolean hasAdjacentPair', 1)[1].split('@Override public long consumeEndpointDiscontinuities', 1)[0]
        code = '''import java.util.*;
class PairProbe {
 static class RetainedEndpoint { boolean prepared=true, preparing; }
 boolean appOwnedPresentation=true, preparationInFlight=true;
 Map<Long,RetainedEndpoint> retained=new HashMap<>();
 void requireOwner(){} void requireOpen(){}
 public boolean hasAdjacentPair''' + method + '''
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] a){
  PairProbe p=new PairProbe();p.retained.put(1L,new RetainedEndpoint());p.retained.put(2L,new RetainedEndpoint());
  check(p.hasAdjacentPair(1,2));
  p.retained.get(2L).preparing=true;check(!p.hasAdjacentPair(1,2));
  p.retained.get(2L).preparing=false;p.retained.get(2L).prepared=false;check(!p.hasAdjacentPair(1,2));
  p.retained.get(2L).prepared=true;check(!p.hasAdjacentPair(1,3));
  p.appOwnedPresentation=false;check(!p.hasAdjacentPair(1,2));
  p.preparationInFlight=false;check(p.hasAdjacentPair(1,2));
  p.retained.remove(2L);check(!p.hasAdjacentPair(1,2));
 }
}'''
        jdk=Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'PairProbe.java'
            path.write_text(code)
            subprocess.run([str(jdk/'javac'),str(path)],check=True,capture_output=True)
            subprocess.run([str(jdk/'java'),'-cp',directory,'PairProbe'],check=True,capture_output=True)
        bind=source.split('@Override public AppOwnedOutput bindAppOwnedOutput',1)[1].split('@Override public void releaseAppOwnedOutput',1)[0]
        self.assertLess(bind.index('if (cached != null) return cached;'),bind.index('if (outputAccessBlocked(current)) return missingAppOwnedOutput(1, request);'))
        self.assertLess(bind.index('if (outputAccessBlocked(current)) return missingAppOwnedOutput(1, request);'),bind.index('bindPreparedHardwareBufferRifeOutput('))

if __name__ == '__main__':
    unittest.main()
