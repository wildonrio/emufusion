"""Execute the production clock-owner decision with fake clock observations."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PhysicalClockRetentionTest(unittest.TestCase):
    def test_measurement_gap_does_not_reset_guest_clock(self):
        java_home = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
        javac = str(java_home / 'javac') if (java_home / 'javac').exists() else shutil.which('javac')
        java = str(java_home / 'java') if (java_home / 'java').exists() else shutil.which('java')
        if not javac or not java:
            self.skipTest('JDK unavailable')
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/LibretroEngineSession.java').read_text()
        method = source.split('    private void updatePhysicalFgClock() {', 1)[1].split(
            '    private void updateDisplayAudioClock(', 1)[0]
        harness = '''
public class ClockRetentionProbe {
    interface FrameGenerationRenderer { double physicalPanelHz(); }
    static class Renderer implements FrameGenerationRenderer {
        double hz=119.937434; public double physicalPanelHz() { return hz; }
    }
    static class FrameGenerationRendererRegistry {
        static FrameGenerationRenderer current;
        static FrameGenerationRenderer find(Object surface) { return current; }
    }
    static class DisplaySyncPolicy {
        static double physicalSourceHz(double declared, double panel) { return panel>0 ? panel/2 : 0; }
    }
    Object netplayRelay, surface;
    double declaredVideoHz=60.099827, physicalFgClockDeclaration, paced;
    boolean physicalFgClockApplied, reject;
    FrameGenerationRenderer physicalFgClockOwner;
    int writes;
    boolean setPacedVideoHz(double hz) { if(reject) return false; paced=hz; writes++; return true; }
    private void updatePhysicalFgClock() {
''' + method + '''
    static void check(boolean value) { if(!value) throw new AssertionError(); }
    public static void main(String[] args) {
        ClockRetentionProbe p=new ClockRetentionProbe(); Renderer first=new Renderer();
        FrameGenerationRendererRegistry.current=first;
        p.updatePhysicalFgClock(); check(p.writes==1 && p.physicalFgClockApplied);
        double locked=p.paced; first.hz=0;
        for(int i=0;i<100;i++) p.updatePhysicalFgClock();
        check(p.writes==1 && p.paced==locked);
        first.hz=120; p.updatePhysicalFgClock(); check(p.paced==60 && p.writes==2);
        Renderer replacement=new Renderer(); replacement.hz=0;
        FrameGenerationRendererRegistry.current=replacement; p.updatePhysicalFgClock();
        check(p.paced==0 && !p.physicalFgClockApplied && p.physicalFgClockOwner==null);
        replacement.hz=120; p.updatePhysicalFgClock();
        p.netplayRelay=new Object(); p.updatePhysicalFgClock(); check(p.paced==0);
        p.netplayRelay=null; p.updatePhysicalFgClock();
        FrameGenerationRendererRegistry.current=null; p.updatePhysicalFgClock(); check(p.paced==0);
        FrameGenerationRendererRegistry.current=replacement; p.updatePhysicalFgClock();
        replacement.hz=0; p.declaredVideoHz=30; p.updatePhysicalFgClock();
        check(p.paced==0 && !p.physicalFgClockApplied);
        replacement.hz=120; p.reject=true; p.updatePhysicalFgClock();
        check(!p.physicalFgClockApplied);
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ClockRetentionProbe.java'
            path.write_text(harness)
            subprocess.run([javac, str(path)], check=True, capture_output=True, text=True)
            subprocess.run([java, '-cp', directory, 'ClockRetentionProbe'], check=True,
                           capture_output=True, text=True)
