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

    def test_owner_loss_off_and_rejection(self):
        src = ROOT / 'unified-android/src'
        body = method((src / 'com/thorium/preview/game/LibretroEngineSession.java').read_text(),
                      '    private void updatePhysicalFgClock(')
        fixture = '''
import com.thorium.lucent.timing.DisplaySyncPolicy;
public class ClockIntegrationTest {
    interface FrameGenerationRenderer { double physicalPanelHz(); }
    static class FrameGenerationRendererRegistry {
        static FrameGenerationRenderer renderer;
        static FrameGenerationRenderer find(Object surface) { return renderer; }
    }
    Object surface=new Object(), netplayRelay;
    double declaredVideoHz=60.0, last=-1;
    boolean physicalFgClockApplied, accepts=true;
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
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='builtin-clock-test-') as directory:
            out = Path(directory)
            java = out / 'ClockIntegrationTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '-d', str(out), '-sourcepath', str(src), str(java)], check=True)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'ClockIntegrationTest'], check=True)
