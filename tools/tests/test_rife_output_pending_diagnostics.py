"""Verify diagnostic pending statuses preserve Java output ownership semantics."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_native_source_image_renderer_wiring import JAVA, method

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / 'experiments/rife-ncnn-vulkan-android/android-benchmark/app/src/main/java/com/emufusion/rifebenchmark/NativeRifeBridge.java'


class OutputPendingDiagnosticsTest(unittest.TestCase):
    def test_exact_proof_pending_and_errors(self):
        source = BRIDGE.read_text()
        methods = '\n'.join(method(source, signature) for signature in (
            'private static boolean outputAccessPending(',
            'public String outputAccessDiagnostic(',
            'public PreparedOutput pollPreparedHardwareBufferRifeOutput(',
            'public boolean bindPreparedHardwareBufferRifeOutput('))
        code = '''
public class PendingProbe {
 long handle=1, lastOutputAccessProof;
 int result, lastOutputAccessStatus=-2;
 boolean lastOutputAccessWasBind;
 static class PreparedOutput { PreparedOutput(long time, Object proof) {} }
 void requireOpen() {} Object validatedContentProof(long[] proof) { return proof; }
 String nativeLastError() { return "native failure"; }
 int nativePollPreparedHardwareBufferRifeOutput(long h,long p,long[] row) {
  row[0]=123; return result;
 }
 int nativeBindPreparedHardwareBufferRifeOutput(long h,long p,int texture) { return result; }
 METHODS
 static void check(boolean ok) { if(!ok)throw new AssertionError(); }
 public static void main(String[] args) {
  PendingProbe p=new PendingProbe();
  for(int status:new int[]{0,2,3,4}) {
   p.result=status;
   check(p.pollPreparedHardwareBufferRifeOutput(17)==null);
   check(p.outputAccessDiagnostic(17).equals("poll:"+status));
   check(p.outputAccessDiagnostic(18).equals("not-observed-for-proof"));
   check(!p.bindPreparedHardwareBufferRifeOutput(17,5));
   check(p.outputAccessDiagnostic(17).equals("bind:"+status));
  }
  p.result=1; check(p.pollPreparedHardwareBufferRifeOutput(17)!=null);
  check(p.bindPreparedHardwareBufferRifeOutput(17,5));
  for(int error:new int[]{-1,-2,5,99}) {
   p.result=error;
   try { p.pollPreparedHardwareBufferRifeOutput(17); throw new AssertionError(); }
   catch(IllegalStateException expected) {}
   try { p.bindPreparedHardwareBufferRifeOutput(17,5); throw new AssertionError(); }
   catch(IllegalStateException expected) {}
  }
 }
}
'''.replace(' METHODS', methods)
        with tempfile.TemporaryDirectory() as directory:
            unit = Path(directory) / 'PendingProbe.java'
            unit.write_text(code)
            for command in ([str(JAVA / 'javac'), str(unit)],
                            [str(JAVA / 'java'), '-cp', directory, 'PendingProbe']):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
