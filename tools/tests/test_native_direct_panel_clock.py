"""Native adapters with frame generation Off lock to the measured panel."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "unified-android/src/com/thorium/preview/game/NativeAdapterEngineSession.java"


class NativeDirectPanelClockTest(unittest.TestCase):
    def test_direct_measurement_trims_and_ignores_jitter(self):
        source = SESSION.read_text()
        body = (method(source, "    private void updateDirectPanelClock(double declared)") + "\n" +
                method(source, "    private void closeDirectPanelClock()"))
        fixture = r'''
import com.thorium.emufusion.timing.DisplaySyncPolicy;
public class DirectClockProbe {
    static class Log { static void i(String t, String m) {} }
    static class Entry { String id = "eden"; }
    static class DirectDisplayVsync {
        static int created, closed; double measured; double declared;
        DirectDisplayVsync(Object context) { ++created; }
        void configure(double d, double s, boolean on) { declared = d; }
        double measuredSourceHz() { return measured; }
        void close() { ++closed; }
    }
    static final String TAG = "t";
    Object context = new Object();
    Entry entry = new Entry();
    double pacedVideoHz; int sets; boolean accepts = true;
    DirectDisplayVsync directPanelClock; long directPanelClockLogs;
    boolean setPacedVideoHz(double hz) { ++sets; if (accepts) pacedVideoHz = hz; return accepts; }
''' + body + r'''
    public static void main(String[] args) {
        DirectClockProbe t = new DirectClockProbe();
        t.updateDirectPanelClock(0.0);
        assert DirectDisplayVsync.created == 0 : "no declared clock (aPS3e): nothing to trim";
        t.updateDirectPanelClock(60.0);
        assert DirectDisplayVsync.created == 1 && t.sets == 0 : "warming up: no trim yet";
        t.directPanelClock.measured = 119.945005 / 2;
        t.updateDirectPanelClock(60.0);
        assert t.sets == 1 && t.pacedVideoHz == 119.945005 / 2;
        t.directPanelClock.measured = 119.945005 / 2 * (1 + 5e-5);
        t.updateDirectPanelClock(60.0);
        assert t.sets == 1 : "window jitter under 100 ppm does not re-trim";
        t.directPanelClock.measured = 119.93 / 2;
        t.updateDirectPanelClock(60.0);
        assert t.sets == 2 && t.pacedVideoHz == 119.93 / 2;
        t.accepts = false; t.directPanelClock.measured = 119.80 / 2;
        t.updateDirectPanelClock(60.0);
        t.updateDirectPanelClock(60.0);
        assert t.sets == 4 : "a declined trim (old Cemu) is retried, not recorded";
        assert DirectDisplayVsync.created == 1 : "one clock per session";
        t.closeDirectPanelClock();
        assert DirectDisplayVsync.closed == 1 && t.directPanelClock == null;
        t.closeDirectPanelClock();
        assert DirectDisplayVsync.closed == 1;
    }
}'''
        with tempfile.TemporaryDirectory(prefix="native-direct-clock-") as directory:
            out = Path(directory)
            (out / "DirectClockProbe.java").write_text(fixture)
            src = ROOT / "unified-android/src"
            subprocess.run([str(JAVA / "javac"), "-d", str(out), "-sourcepath", str(src),
                            str(out / "DirectClockProbe.java")], check=True)
            subprocess.run([str(JAVA / "java"), "-ea", "-cp", str(out), "DirectClockProbe"],
                           check=True)

    def test_off_route_measures_and_loop_closes_it(self):
        source = SESSION.read_text()
        fg = method(source, "    private void updatePhysicalFgClock(NativeAdapterHost active)")
        self.assertIn("if (renderer == null && current != null && !physicalFgClockApplied) {", fg)
        self.assertLess(fg.index("updateDirectPanelClock(declared);"),
                        fg.index("closeDirectPanelClock();"))
        loop_end = source[source.index("updatePhysicalFgClock(active);"):]
        self.assertIn("closeDirectPanelClock();", loop_end[:loop_end.index("abandonRenderTasks();")])


if __name__ == "__main__":
    unittest.main()
