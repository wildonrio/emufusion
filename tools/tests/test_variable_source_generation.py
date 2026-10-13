"""A source the controller does not plan still generates on the timeline's own lattice.

Star Fox dips between 27 and 30 FPS, NDS and PS1 deliver irregular rates, and
an N64 20-FPS game waits ~40 s for the controller to qualify its clock. The
timeline places every output at its own source time, so it owns a fixed panel
divisor near maxMultiplier x the measured rate for these sources.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")
GENERATOR = (ROOT / "unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java").read_text()


def method(signature):
    start = GENERATOR.index(signature)
    brace = GENERATOR.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (GENERATOR[end] == "{") - (GENERATOR[end] == "}")
        end += 1
    return GENERATOR[start:end]


class VariableSourceGenerationTest(unittest.TestCase):
    def test_lattice_for_measured_rates(self):
        body = (method("private int variableSourceScans()") + "\n" +
                method("private static int freshVariableSourceScans("))
        harness = r'''
public class VariableProbe {
  static final double VARIABLE_SOURCE_MIN_HZ = 19.5;
  static final double VARIABLE_SOURCE_MIN_GAIN = 1.25;
  boolean timelineMode = true; int timelineScansPerOutput;
  static final long TIMELINE_LATTICE_RETAIN_NS = 10_000_000_000L;
  int timelineReleasedScans; long timelineReleasedAtNs;
  static int multiplier = 2;
  static class TimelineSchedulerSwitch { static int maxMultiplier() { return multiplier; } }
  static double panelHz = 119.95;
  static class Rate { boolean available = true; double panel = panelHz, source;
    boolean generationAvailable() { return available; } double panelHz() { return panel; }
    double sustainedMeasuredSourceHz() { return source; } }
  final Rate frameRate = new Rate();
''' + body + r'''
  static int scans(double source, int previous) {
    VariableProbe p = new VariableProbe(); p.frameRate.source = source; p.timelineScansPerOutput = previous;
    return p.variableSourceScans();
  }
  static int afterRelease(double source, int released, long agoNs) {
    VariableProbe p = new VariableProbe(); p.frameRate.source = source;
    p.timelineReleasedScans = released; p.timelineReleasedAtNs = System.nanoTime() - agoNs;
    return p.variableSourceScans();
  }
  static void check(boolean ok, String why) { if (!ok) throw new AssertionError(why); }
  public static void main(String[] a) {
    check(scans(27.0, 0) == 2, "27 FPS -> 60");
    check(scans(29.99, 0) == 2, "30 FPS -> 60");
    check(scans(19.99, 0) == 3, "20 FPS -> 40");
    check(scans(21.4, 0) == 3, "PS1 21 FPS -> 40");
    check(scans(25.0, 0) == 3, "25 FPS -> 40 (60 would be 2.4x)");
    check(scans(55.0, 0) == 1, "55 FPS -> 120");
    check(scans(19.0, 0) == 0, "below the floor: no generation");
    check(scans(60.5, 0) == 1, "an unqualified ~60-FPS source (SM3DW 55-60) still doubles to 120");
    check(scans(59.9, 2) == 1, "and leaves a 60 lattice for 120 when it rises to 60");
    check(scans(64.0, 0) == 1, "a 64-FPS source the controller does not plan still gains 1.9x at 120");
    check(scans(97.0, 0) == 0, "within 1.25x of the panel: not worth generating");
    check(scans(26.0, 2) == 2, "hysteresis keeps 60 for a dip to 26");
    check(scans(23.0, 2) == 3, "a sustained 23 leaves 60");
    check(scans(50.0, 0) == 1, "50 FPS -> 120 (60 gains too little; there was no generation)");
    check(scans(47.0, 0) == 2, "47 FPS -> 60 while 60 still adds a quarter");
    check(scans(49.0, 0) == 1, "49 FPS -> 120");
    check(scans(47.0, 1) == 1, "hysteresis keeps 120 for a dip to 47");
    check(scans(45.0, 1) == 2, "a sustained 45 leaves 120");
    check(scans(49.5, 2) == 2, "hysteresis keeps 60 up to 50");
    check(scans(52.0, 2) == 1, "a sustained 52 leaves 60 for 120");
    check(scans(29.0, 3) == 2, "a 30-FPS game back from a dip leaves 40 for 60");
    check(scans(27.5, 3) == 2, "27.5 FPS is comfortably 60");
    check(scans(27.0, 3) == 3, "hysteresis keeps 40 near the 60 boundary");
    check(scans(21.0, 3) == 3, "a sustained low rate keeps 40");
    multiplier = 3;
    check(scans(20.0, 0) == 2, "triple: 20 FPS -> 60");
    multiplier = 4;
    check(scans(24.0, 0) == 2, "4x: a fresh 24-FPS source takes 60 (120 would be 5x)");
    check(scans(24.0, 1) == 1, "4x: hysteresis keeps 120 when a 30-FPS source dips to 24");
    check(afterRelease(24.0, 1, 600_000_000L) == 1,
          "a transient release does not reset the lattice: Sonic at 24 keeps 120");
    check(afterRelease(24.0, 1, 11_000_000_000L) == 2, "a long release starts fresh");
    check(afterRelease(20.0, 1, 600_000_000L) == 2,
          "a retained lattice still has to fit the source (120 is 6x at 20)");
    multiplier = 3; panelHz = 90.0;
    check(scans(57.0, 0) == 1, "90 Hz phone: a 55-60 FPS game fills 90 (was ungenerated)");
    check(scans(30.0, 0) == 1, "90 Hz: 30 FPS triples to 90");
    check(scans(73.0, 0) == 0, "90 Hz: 73 FPS gains too little");
    panelHz = 144.0;
    check(scans(50.0, 0) == 1, "144 Hz: a 50-FPS Switch game fills 144");
    check(scans(90.0, 0) == 1, "144 Hz: a 90-FPS source fills 144 (1.6x)");
    check(scans(115.0, 0) == 1, "144 Hz: up to 115 FPS");
    check(scans(116.0, 0) == 0, "144 Hz: above 115 gains too little");
    check(scans(30.0, 0) == 2, "144 Hz: 30 FPS at On takes 72 (144 would be 4.8x)");
    multiplier = 4;
    check(scans(36.0, 0) == 1, "144 Hz with Allow 4x: 36 FPS reaches 144");
    panelHz = 119.95; multiplier = 3;
    VariableProbe off = new VariableProbe(); off.frameRate.source = 30; off.frameRate.available = false;
    check(off.variableSourceScans() == 0, "generation unavailable");
    System.out.println("VARIABLE_OK");
  }
}
'''
        with tempfile.TemporaryDirectory(prefix="variable-source-") as tmp:
            path = Path(tmp, "VariableProbe.java")
            path.write_text(harness)
            built = subprocess.run([str(JAVA / "javac"), "-d", tmp, str(path)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            run = subprocess.run([str(JAVA / "java"), "-cp", tmp, "VariableProbe"],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("VARIABLE_OK", run.stdout)

    def test_direct_passthrough_bridges_one_dropped_frame(self):
        body = method("private boolean presentationEndpointContinuous(")
        harness = r'''
import com.thorium.emufusion.video.AdaptiveFrameRateController;
public class ContinuityProbe {
  boolean timelineActive;
  static class Timeline { boolean pairSpanAllowed(long a, long b) { return b - a < 100_000_000L; } }
  final Timeline timeline = new Timeline();
  static class Rate { boolean generating; double presentationSourceHz() { return 60.0; }
    boolean generatesIntermediateFrames() { return generating; } }
  final Rate frameRate = new Rate();
''' + body + r'''
  static void check(boolean ok, String why) { if (!ok) throw new AssertionError(why); }
  public static void main(String[] a) {
    ContinuityProbe p = new ContinuityProbe();
    long t = 1_000_000_000L, period = 16_666_667L;
    check(p.presentationEndpointContinuous(t, t + period), "one period continues");
    check(p.presentationEndpointContinuous(t, t + 2 * period), "Direct bridges one dropped frame");
    check(!p.presentationEndpointContinuous(t, t + 3 * period), "two dropped frames still cut");
    p.frameRate.generating = true;
    check(!p.presentationEndpointContinuous(t, t + 2 * period), "generated output never spans a gap");
    p.timelineActive = true;
    check(p.presentationEndpointContinuous(t, t + 5 * period), "the timeline applies its own limit");
    System.out.println("CONTINUITY_OK");
  }
}
'''
        with tempfile.TemporaryDirectory(prefix="continuity-") as tmp:
            path = Path(tmp, "ContinuityProbe.java")
            path.write_text(harness)
            built = subprocess.run([str(JAVA / "javac"), "-sourcepath",
                                    str(ROOT / "unified-android/src"), "-d", tmp, str(path)],
                                   capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            run = subprocess.run([str(JAVA / "java"), "-cp", tmp, "ContinuityProbe"],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("CONTINUITY_OK", run.stdout)

    def test_timeline_uses_owned_lattice_when_the_controller_is_direct(self):
        planned = method("private boolean builtinGenerationPlanned()")
        self.assertLess(planned.index("frameRate.generatesIntermediateFrames()"),
                        planned.index("int ownedScans = variableSourceScans();"))
        select = method("private int selectTimelinePresentation(long callbackNs)")
        self.assertIn("int planned = frameRate.generatesIntermediateFrames() ?\n"
                      "                frameRate.panelScansPerOutput() : 0;", select)
        scans = method("private int presentationScansPerOutput()")
        self.assertIn("planned > 0 && frameRate.generatesIntermediateFrames() ? planned :", scans)


if __name__ == "__main__":
    unittest.main()
