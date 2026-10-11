"""Execute production rejection logic: permanent rejection retires the transport,
unless an exact Direct lattice lets the passthrough present like Direct."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]


class DensePermanentRecoveryTest(unittest.TestCase):
    def test_unqualified_real_swap_is_not_gpu_failure_or_recovery_credit(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, '    private static boolean requiresDenseGpuHeadroomBinding(')
        fixture = 'public class BindingAdmissionTest {\n' + body + r'''
            public static void main(String[] args) {
                assert !requiresDenseGpuHeadroomBinding(false, 0);
                assert !requiresDenseGpuHeadroomBinding(false, -1);
                for (int scans : new int[] {1, 2, 3, 6}) {
                    assert requiresDenseGpuHeadroomBinding(false, scans);
                    assert requiresDenseGpuHeadroomBinding(true, scans);
                }
                assert requiresDenseGpuHeadroomBinding(true, 0) :
                    "invalid synthetic cadence must still reach strict rejection";
            }
        }'''
        self.assertIn('!requiresDenseGpuHeadroomBinding(renderedSynthetic,', source)
        with tempfile.TemporaryDirectory(prefix='dense-binding-') as directory:
            out = Path(directory)
            java = out / 'BindingAdmissionTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', str(out), str(java)],
                           check=True, capture_output=True, text=True, timeout=30)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'BindingAdmissionTest'],
                           check=True, capture_output=True, text=True, timeout=15)

    def test_permanent_rejection_requests_direct_but_transient_can_rearm(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        # Product behaviour: a failed generator stays on the Direct passthrough.
        self.assertIn('private static final boolean retireOnPermanentRejection = false;', source)
        body = method(source, '    private void rejectDense(')
        fixture = r'''
public class DenseRejectionTest {
    static class Log {static void e(String t,String s){} static void e(String t,String s,Throwable f){}
        static void i(String t,String s){}}
    static class Adaptation {
        boolean disabled;
        boolean generationDisabled(){return disabled;}
        void onFailure(String reason){} void invalidateRecoveryEvidence(){}
        int workLevel(){return 0;}
    }
    static class FrameRate {boolean enabled=true,lattice;void setGenerationAvailable(boolean v){enabled=v;}
        boolean directLatticeActive(){return lattice;}}
    final Adaptation denseGpuAdaptation=new Adaptation();
    final FrameRate frameRate=new FrameRate();
    static final int DENSE_TRANSIENT_REJECT_REARM_LIMIT=2;
    boolean retireOnPermanentRejection=true;  // product default false; tested both ways
    static final String TAG="fixture";
    boolean densePyramidEnabled=true,densePyramidUnavailable,densePerformanceRejected;
    boolean reportedCadenceQualified=true;
    int denseWorkLevel,denseTransientRejections,generatorId;
    int reportedSourceTenths,reportedOutputTenths,reportedTargetTenths;
    String reportedBackendLabel="Built-in";
    int invalidations,teardowns,reports,recoveries;
    RuntimeException cause;
    boolean isOverBudgetDenseRejection(String r){return r.equals("budget");}
    boolean isTransientDenseRejection(String r){return r.equals("transient");}
    String denseGpuFailure(String r){return r;}
    void invalidateBufferedPairForReprime(boolean ignored){invalidations++;}
    void teardownDenseEpoch(String reason){teardowns++;}
    void reportStats(){reports++;}
    void failRuntimePresentation(String diagnostic,RuntimeException failure){
        assert !frameRate.enabled && !densePyramidEnabled && teardowns>0;
        recoveries++;cause=failure;
    }
''' + body + r'''
    public static void main(String[] args){
        DenseRejectionTest permanent=new DenseRejectionTest();
        Throwable underlying=new IllegalStateException("missing GPU binding");
        permanent.rejectDense("gpu-headroom-binding-failure",underlying);
        assert permanent.recoveries==1 : "permanent rejection retained intermediate renderer";
        assert permanent.densePyramidUnavailable && permanent.cause.getCause()==underlying;
        DenseRejectionTest temporary=new DenseRejectionTest();
        temporary.rejectDense("transient",null);
        assert temporary.recoveries==0 && !temporary.densePyramidUnavailable;
        temporary.rejectDense("budget",null);
        assert temporary.recoveries==0;
        temporary.rejectDense("transient",null);
        assert temporary.recoveries==1 && temporary.densePyramidUnavailable;
        // A stamped producer on an exact Direct lattice keeps the endpoint-only
        // passthrough: retiring it destroyed the core's GL context (Thor stalls).
        DenseRejectionTest passthrough=new DenseRejectionTest();
        passthrough.frameRate.lattice=true;
        passthrough.rejectDense("gpu-headroom-binding-failure",null);
        assert passthrough.recoveries==0 && passthrough.densePyramidUnavailable;
        assert !passthrough.frameRate.enabled && passthrough.teardowns==1 && passthrough.reports==1;
        // Product default: no stamped lattice, still never retire (retiring
        // destroyed the core's GL context: 100-430 ms stalls).
        DenseRejectionTest noLattice=new DenseRejectionTest();
        noLattice.retireOnPermanentRejection=false;
        noLattice.rejectDense("gpu-headroom-binding-failure",null);
        assert noLattice.recoveries==0 && noLattice.densePyramidUnavailable && !noLattice.frameRate.enabled;
        DenseRejectionTest exhausted=new DenseRejectionTest();
        exhausted.denseGpuAdaptation.disabled=true;
        exhausted.rejectDense("budget",null);
        assert exhausted.recoveries==1;
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='dense-recovery-') as directory:
            out = Path(directory)
            java = out / 'DenseRejectionTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', str(out), str(java)],
                           check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'DenseRejectionTest'],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
