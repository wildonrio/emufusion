"""Exercise the production diagnostic window, not physical FPS qualification."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java"
JAVA = Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")


class FramegenHealthWindowTest(unittest.TestCase):
    def test_target_drift_and_mode_changes_cannot_starve_health_reports(self):
        source = SOURCE.read_text()
        start = source.index("    private void reportStats() {")
        # Execute the complete production window/admission calculation. The
        # Android-dependent physical ledgers/logging after it are not modeled.
        end = source.index("        int scansPerOutput =", start)
        window = source[start:end]
        fixture = r'''
public class HealthWindowTest {
    static class System {static long now;static long nanoTime(){return now;}}
    static class FrameRate {
        double target=30;
        int lockedSourceFps(){return (int)target;}
        double sustainedMeasuredSourceHz(){return target;}
        double targetOutputHz(){return target;}
    }
    final FrameRate frameRate=new FrameRate();
    long statsWindowStartNanos,statsWindowStartPresents,presents;
    int admissions,publications,windows;
    long intervalPresents,intervalElapsed;
    void reportSourceAdmissionDiagnostic(long now){admissions++;}
    void publishReportedFrameRate(double a,double b,double c,boolean qualified){
        assert !qualified && b==0;publications++;
    }
''' + window + r'''
        // These assignments are the same production reset after its physical
        // ledger checks. No modeled physical result is promoted to evidence.
        statsWindowStartNanos=now;statsWindowStartPresents=presents;
        windows++;intervalPresents+=committed;intervalElapsed+=elapsedNs;
        assert swapOutput>=0;
    }
    public static void main(String[] args) {
        HealthWindowTest h=new HealthWindowTest();System.now=1_000_000_000L;
        h.reportStats();
        for(int i=1;i<=1000;i++) {
            System.now+=10_000_000L;
            h.frameRate.target=29.9+(i%11)*0.001;
            if(i%37==0)h.frameRate.target=60; // genuine rate transitions too
            h.presents++;h.reportStats();
        }
        assert h.windows==10 && h.intervalPresents==1000;
        assert h.intervalElapsed==10_000_000_000L;
        assert h.admissions==1001 && h.publications==1;
        System.now+=5_000_000_000L;h.frameRate.target=20;h.reportStats();
        assert h.windows==11 && h.intervalPresents==1000;
        assert h.intervalElapsed==15_000_000_000L; // stall duration not erased
        System.now+=1_000_000_000L;h.reportStats();
        assert h.windows==12 && h.intervalElapsed==16_000_000_000L;
    }
}
'''
        with tempfile.TemporaryDirectory(prefix="framegen-health-window-") as temporary:
            output = Path(temporary)
            java = output / "HealthWindowTest.java"
            java.write_text(fixture)
            compiled = subprocess.run([str(JAVA / "javac"), "--release", "8", "-d",
                                       str(output), str(java)], capture_output=True,
                                      text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(JAVA / "java"), "-ea", "-cp", str(output),
                                  "HealthWindowTest"], capture_output=True, text=True, timeout=15)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertNotIn("statsTargetOutputMilliHz", source)


if __name__ == "__main__":
    unittest.main()
