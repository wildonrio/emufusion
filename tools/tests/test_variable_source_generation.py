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
        body = method("private int variableSourceScans()")
        harness = r'''
public class VariableProbe {
  static final double VARIABLE_SOURCE_MIN_HZ = 19.5;
  boolean timelineMode = true; int timelineScansPerOutput;
  static int multiplier = 2;
  static class TimelineSchedulerSwitch { static int maxMultiplier() { return multiplier; } }
  static class Rate { boolean available = true; double panel = 119.95, source;
    boolean generationAvailable() { return available; } double panelHz() { return panel; }
    double sustainedMeasuredSourceHz() { return source; } }
  final Rate frameRate = new Rate();
''' + body + r'''
  static int scans(double source, int previous) {
    VariableProbe p = new VariableProbe(); p.frameRate.source = source; p.timelineScansPerOutput = previous;
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
    check(scans(60.5, 0) == 0, "above half the panel: the controller owns it");
    check(scans(26.0, 2) == 2, "hysteresis keeps 60 for a dip to 26");
    check(scans(23.0, 2) == 3, "a sustained 23 leaves 60");
    multiplier = 3;
    check(scans(20.0, 0) == 2, "triple: 20 FPS -> 60");
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
