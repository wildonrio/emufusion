"""Execute actual Built-in planner against physical-clock and deadline classes."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]


class BuiltInDeadlineTest(unittest.TestCase):
    def test_thor_5639_gap_is_late_admission_not_late_swap(self):
        """Replay measured inputs; do not loosen reserve to manufacture a pass."""
        src = ROOT / 'unified-android/src'
        fixture = '''
import com.thorium.lucent.video.PhysicalPresentationDeadline;
public class RecordedGapTest {
    public static void main(String[] args) {
        long previous=9332086973665L, interval=8333333L;
        long composite=9332084973665L, latency=10333333L;
        long now=9332084288729L, reserve=1000000L;
        PhysicalPresentationDeadline late=PhysicalPresentationDeadline.nextEgl(
            composite, interval, latency, now, previous, reserve);
        assert late.valid();
        assert late.contentPresentationTimeNs()==9332103640331L;
        assert late.contentPresentationTimeNs()-previous==2*interval;
        assert late.skippedPanelScans()==1;
        assert late.hardCompletionDeadlineNs()==9332092306998L;
        // Swap was on time for the selected later slot, not for the skipped one.
        assert 9332084744459L < late.hardCompletionDeadlineNs();
        assert now > composite-reserve;
        // Same timeline is continuous when admitted before its actual cutoff.
        PhysicalPresentationDeadline early=PhysicalPresentationDeadline.nextEgl(
            composite, interval, latency, composite-reserve-1, previous, reserve);
        assert early.valid();
        assert early.contentPresentationTimeNs()==previous+interval;
        assert early.skippedPanelScans()==0;
        // Exact boundary is deliberately exclusive; preserve safety semantics.
        PhysicalPresentationDeadline boundary=PhysicalPresentationDeadline.nextEgl(
            composite, interval, latency, composite-reserve, previous, reserve);
        assert boundary.contentPresentationTimeNs()==late.contentPresentationTimeNs();
    }
}'''
        with tempfile.TemporaryDirectory(prefix='recorded-gap-') as directory:
            out = Path(directory)
            java = out / 'RecordedGapTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '-d', str(out),
                            str(src / 'com/thorium/lucent/video/PhysicalPresentationDeadline.java'),
                            str(java)], check=True)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out),
                            'RecordedGapTest'], check=True)

    def test_compositor_sampling_is_bounded_and_builtin_only(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, '    private static boolean sampleBuiltinCompositorTiming(')
        fixture = 'public class SamplingTest {\n' + body + '''
            public static void main(String[] args) {
                assert sampleBuiltinCompositorTiming(true,true,false,true,0);
                assert sampleBuiltinCompositorTiming(true,true,false,true,63);
                assert !sampleBuiltinCompositorTiming(true,true,false,true,64);
                assert !sampleBuiltinCompositorTiming(true,true,false,true,-1);
                assert !sampleBuiltinCompositorTiming(false,true,false,true,0);
                assert !sampleBuiltinCompositorTiming(true,false,false,true,0);
                assert !sampleBuiltinCompositorTiming(true,true,true,true,0);
                assert !sampleBuiltinCompositorTiming(true,true,false,false,0);
            }
        }'''
        with tempfile.TemporaryDirectory(prefix='builtin-sampling-') as directory:
            out = Path(directory)
            java = out / 'SamplingTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '-d', str(out), str(java)], check=True)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'SamplingTest'], check=True)

    def test_normal_builtin_has_no_second_egl_pacer(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, '    private static boolean requiresNonblockingBuiltinSwap(')
        fixture = 'public class SwapPolicyTest {\n' + body + '''
            public static void main(String[] args) {
                assert requiresNonblockingBuiltinSwap(false);
                assert !requiresNonblockingBuiltinSwap(true);
            }
        }'''
        self.assertIn('requiresNonblockingBuiltinSwap(externalTransport != null)', source)
        with tempfile.TemporaryDirectory(prefix='builtin-swap-') as directory:
            out = Path(directory)
            java = out / 'SwapPolicyTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '-d', str(out), str(java)], check=True)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'SwapPolicyTest'], check=True)

    def test_physical_phase_and_committed_target_win(self):
        src = ROOT / 'unified-android/src'
        source = (src / 'com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, '    private PhysicalPresentationDeadline nextBuiltInDeadline(')
        fixture = '''
import com.thorium.lucent.video.*;
public class BuiltInDeadlineTest {
    static class PhysicalPresentationTracker {
        boolean available(){return true;}
        boolean compositorTiming(long[] row){return false;}
    }
    PhysicalPresentationTracker physicalPresentationTracker;
    Object externalTransport;
    boolean densePyramidEnabled;
    long[] builtinCompositorTiming=new long[3];
    static class Rate {long period=8333333L; long panelPeriodNs(){return period;} double declaredPanelHz(){return 1e9/period;}}
    Rate frameRate=new Rate();
    PhysicalPresentationClock builtInPhysicalClock=new PhysicalPresentationClock();
    long builtInLastCommittedTargetNs;
    long builtinPlanCallbackNs,builtinPlanNowNs,builtinPlanCompositeDeadlineNs,
         builtinPlanIntervalNs,builtinPlanLatencyNs;
''' + body + '''
    public static void main(String[] args) {
        BuiltInDeadlineTest t=new BuiltInDeadlineTest();
        long callback=186183590208666L, now=callback+1000000L;
        long anchor=186183597549025L, period=t.frameRate.period;
        PhysicalPresentationDeadline bootstrap=t.nextBuiltInDeadline(callback,now);
        assert bootstrap.valid();
        assert t.builtInPhysicalClock.record(anchor,period);
        PhysicalPresentationDeadline aligned=t.nextBuiltInDeadline(callback,now);
        assert aligned.valid();
        assert (aligned.contentPresentationTimeNs()-anchor)%period==0;
        assert aligned.contentPresentationTimeNs()!=bootstrap.contentPresentationTimeNs();
        t.builtInLastCommittedTargetNs=aligned.contentPresentationTimeNs();
        PhysicalPresentationDeadline next=t.nextBuiltInDeadline(callback,now);
        assert next.contentPresentationTimeNs()>t.builtInLastCommittedTargetNs;
        assert next.hardCompletionDeadlineNs()>now;
        // Same-mode scheduler epochs retain frequency, not a permanently
        // accurate phase anchor when the oscillator estimate evolves.
        t=new BuiltInDeadlineTest();
        for(int i=0;i<=4000;i++) t.builtInPhysicalClock.record(anchor+i*period,period);
        t.builtInPhysicalClock.beginPresentationEpoch();
        long epoch=anchor+4001*period, actualPeriod=period+1000;
        for(int i=0;i<=4000;i++)
            t.builtInPhysicalClock.record(epoch+i*actualPeriod,period);
        long latest=epoch+4000*actualPeriod;
        PhysicalPresentationDeadline tracking=t.nextBuiltInDeadline(latest,latest+1000000);
        assert Math.abs(tracking.contentPresentationTimeNs()-(latest+actualPeriod))<10000
            : "epoch phase error="+(tracking.contentPresentationTimeNs()-(latest+actualPeriod));
        t.frameRate.period=16666667L;
        PhysicalPresentationDeadline changed=t.nextBuiltInDeadline(callback,now);
        assert changed.contentPresentationTimeNs()==callback+t.frameRate.period;
        t=new BuiltInDeadlineTest();
        final long eglQueue=System.nanoTime()+100000000L;
        t.physicalPresentationTracker=new PhysicalPresentationTracker(){
            boolean compositorTiming(long[] row){
                row[0]=eglQueue; row[1]=8333333L; row[2]=10333333L; return true;
            }
        };
        t.densePyramidEnabled=true;
        PhysicalPresentationDeadline egl=t.nextBuiltInDeadline(System.nanoTime(),System.nanoTime());
        assert egl.contentPresentationTimeNs()==eglQueue+10333333L;
        assert egl.hardCompletionDeadlineNs()==eglQueue-1000000L;
        t.externalTransport=new Object();
        PhysicalPresentationDeadline external=t.nextBuiltInDeadline(callback,now);
        assert external.contentPresentationTimeNs()==callback+t.frameRate.period;
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='builtin-deadline-') as directory:
            out = Path(directory)
            java = out / 'BuiltInDeadlineTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '-d', str(out), '-sourcepath', str(src), str(java)], check=True)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'BuiltInDeadlineTest'], check=True)
