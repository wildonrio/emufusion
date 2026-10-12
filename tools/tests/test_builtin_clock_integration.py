"""Exercise the actual software-session correction/restoration branch."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]


class BuiltinClockIntegrationTest(unittest.TestCase):
    def test_startup_waits_for_physical_evidence(self):
        src = ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java'
        body = method(src.read_text(), '    private static boolean builtinClockAdmissionReady(')
        fixture = 'public class AdmissionTest {\n' + body + '''
            public static void main(String[] args) {
                assert !builtinClockAdmissionReady(true,false,0,0);
                assert !builtinClockAdmissionReady(true,false,0,Double.NaN);
                assert !builtinClockAdmissionReady(true,true,0,120);
                assert !builtinClockAdmissionReady(false,false,0,120);
                assert !builtinClockAdmissionReady(true,false,4,120);
                assert builtinClockAdmissionReady(true,false,0,119.945005);
            }
        }'''
        with tempfile.TemporaryDirectory(prefix='builtin-admission-') as directory:
            out = Path(directory)
            java = out / 'AdmissionTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '-d', str(out), str(java)], check=True)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'AdmissionTest'], check=True)

    def test_admission_uses_remembered_rate_only_while_presenting(self):
        # A near-60 source kept the live clock unqualified for 10-19 s (Wii U
        # SM3DW, 2026-10-12): admission may use this mode's remembered rate,
        # but only while this generator's own presents are being observed.
        src = ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java'
        body = method(src.read_text(), '    private double admissionPanelHz()')
        fixture = r'''
public class RememberedAdmissionTest {
    static class PhysicalPresentationClock { static final long SUSTAINED_GAP_BRIDGE_NS=1_000_000_000L;
        long last; long lastActualNs(){return last;} }
    static class PanelClockMemory { static double value; static double lookup(int d,double hz){return value;} }
    static class Closed { boolean v; boolean get(){return v;} }
    final Closed closed=new Closed();
    final PhysicalPresentationClock builtInPhysicalClock=new PhysicalPresentationClock();
    int displayId; float refreshHz=120f; double live;
    double physicalPanelHz(){return live;}
''' + body + r'''
    public static void main(String[] args){
        RememberedAdmissionTest t=new RememberedAdmissionTest();
        PanelClockMemory.value=119.93;
        assert t.admissionPanelHz()==0.0 : "no presents observed yet";
        t.builtInPhysicalClock.last=System.nanoTime();
        assert t.admissionPanelHz()==119.93 : "presenting: the remembered rate admits";
        t.builtInPhysicalClock.last=System.nanoTime()-2_000_000_000L;
        assert t.admissionPanelHz()==0.0 : "a stale present does not";
        t.live=119.95; assert t.admissionPanelHz()==119.95 : "the live clock wins";
        t.live=0; t.builtInPhysicalClock.last=System.nanoTime(); PanelClockMemory.value=0;
        assert t.admissionPanelHz()==0.0 : "nothing remembered: wait for the live clock";
        PanelClockMemory.value=119.93; t.closed.v=true;
        assert t.admissionPanelHz()==0.0 : "closed generator";
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='remembered-admission-') as directory:
            out = Path(directory)
            java = out / 'RememberedAdmissionTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '-d', str(out), str(java)], check=True)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'RememberedAdmissionTest'], check=True)

    def test_owner_loss_off_and_rejection(self):
        src = ROOT / 'unified-android/src'
        body = method((src / 'com/thorium/preview/game/LibretroEngineSession.java').read_text(),
                      '    private void updatePhysicalFgClock(')
        fixture = '''
import com.thorium.emufusion.timing.DisplaySyncPolicy;
public class ClockIntegrationTest {
    interface FrameGenerationRenderer { double physicalPanelHz(); }
    static class FrameGenerationRendererRegistry {
        static FrameGenerationRenderer renderer;
        static FrameGenerationRenderer find(Object surface) { return renderer; }
    }
    static class Panel implements FrameGenerationRenderer {
        double hz; Panel(double hz) { this.hz=hz; }
        public double physicalPanelHz() { return hz; }
    }
    Object surface=new Object(), netplayRelay;
    double declaredVideoHz=60.0, last=-1, physicalFgClockDeclaration;
    boolean physicalFgClockApplied, accepts=true;
    FrameGenerationRenderer physicalFgClockOwner;
    int calls;
    boolean setPacedVideoHz(double hz) { ++calls; last=hz; return accepts; }
''' + body + '''
    public static void main(String[] args) {
        ClockIntegrationTest t=new ClockIntegrationTest();
        t.updatePhysicalFgClock();
        assert t.calls==0 : "Off must not introduce a correction";
        FrameGenerationRendererRegistry.renderer=()->119.945005;
        t.updatePhysicalFgClock();
        assert t.physicalFgClockApplied && t.last==119.945005/2;
        FrameGenerationRendererRegistry.renderer=()->0.0;
        t.updatePhysicalFgClock();
        assert !t.physicalFgClockApplied && t.last==0.0;
        int restored=t.calls; t.updatePhysicalFgClock();
        assert t.calls==restored : "do not repeatedly reset unowned clock";
        FrameGenerationRendererRegistry.renderer=()->119.945005;
        t.accepts=false; t.updatePhysicalFgClock();
        assert !t.physicalFgClockApplied : "failed setter cannot establish ownership";
        t.accepts=true; t.updatePhysicalFgClock();
        t.netplayRelay=new Object(); t.updatePhysicalFgClock();
        assert !t.physicalFgClockApplied && t.last==0.0;
        t.netplayRelay=null;
        FrameGenerationRendererRegistry.renderer=()->80.0;
        int before=t.calls; t.updatePhysicalFgClock();
        assert t.calls==before : "no large guest slowdown";
        Panel panel=new Panel(119.945005);
        FrameGenerationRendererRegistry.renderer=panel; t.updatePhysicalFgClock();
        assert t.physicalFgClockApplied && t.physicalFgClockOwner==panel && t.last==119.945005/2;
        panel.hz=0.0; before=t.calls; t.updatePhysicalFgClock();
        assert t.physicalFgClockApplied && t.calls==before :
                "the owner's unavailable measurement retains the trim during priming";
        t.declaredVideoHz=59.73; t.updatePhysicalFgClock();
        assert !t.physicalFgClockApplied && t.physicalFgClockOwner==null && t.last==0.0 :
                "a core declaration change releases the retained trim";
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='builtin-clock-test-') as directory:
            out = Path(directory)
            java = out / 'ClockIntegrationTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '-d', str(out), '-sourcepath', str(src), str(java)], check=True)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'ClockIntegrationTest'], check=True)
