"""Planning-clock invariant regression; synthetic, not a Thor trace replay."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PhysicalClockEpochDriftTest(unittest.TestCase):
    def test_thor_startup_fractional_clock_with_missing_generated_slots(self):
        """Isolate frequency/phase math; deliberately excludes GPU/queue latency."""
        jdk = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
        source = ROOT / 'unified-android/src/com/thorium/lucent/video/PhysicalPresentationClock.java'
        harness = '''
import com.thorium.lucent.video.PhysicalPresentationClock;
public class ThorStartupClockProbe {
 public static void main(String[] args) {
  PhysicalPresentationClock c=new PhysicalPresentationClock();
  long nominal=8333333L, actual=8334855L, now=1000000000L;
  c.record(now,nominal);
  long max=0, scans=0;
  for(int i=0;i<1200;i++) {
   // Mostly REAL-only delivery, with occasional adjacent synthetic scans.
   long step=i%11==0?1:2;
   now+=step*actual;scans+=step;
   if(!c.record(now,nominal)) throw new AssertionError("valid scan rejected");
   if(scans>=30) {
    long forecast=c.trackedPlanningAnchorNs()+(c.observedScans()+5)*c.planningPeriodNs();
    max=Math.max(max,Math.abs(forecast-(now+5*actual)));
   }
  }
  System.out.println("startupSparseMaxForecastErrorNs="+max);
  if(max>150000L) throw new AssertionError("fractional startup alone loses slot");
 }
}'''
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'ThorStartupClockProbe.java'
            path.write_text(harness)
            subprocess.run([str(jdk/'javac'), '-d', temporary, str(source), str(path)],
                           check=True, capture_output=True, text=True)
            result = subprocess.run([str(jdk/'java'), '-cp', temporary, 'ThorStartupClockProbe'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

    def test_phase_tracking_preserves_output_slots_and_committed_deadlines(self):
        jdk = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
        javac = str(jdk / 'javac') if (jdk / 'javac').exists() else shutil.which('javac')
        java = str(jdk / 'java') if (jdk / 'java').exists() else shutil.which('java')
        if not javac or not java:
            self.skipTest('JDK unavailable')
        production = ROOT / 'unified-android/src/com/thorium/lucent/video'
        test = ROOT / 'unified-android/test/com/thorium/lucent/video'
        with tempfile.TemporaryDirectory() as temporary:
            sources = [production / 'PhysicalPresentationClock.java',
                       production / 'PhysicalPresentationDeadline.java',
                       production / 'CompositorFrameTimeline.java',
                       test / 'PhysicalPresentationClockTest.java',
                       test / 'PhysicalPresentationDeadlineTest.java',
                       test / 'PhysicalPlanningPhaseTest.java']
            compiled = subprocess.run([javac, '-d', temporary, *map(str, sources)],
                                      capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            for name in ('PhysicalPresentationClockTest', 'PhysicalPresentationDeadlineTest',
                         'PhysicalPlanningPhaseTest'):
                result = subprocess.run([java, '-cp', temporary, 'com.thorium.lucent.video.' + name],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        renderer = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        app_owned_planning = renderer.split('PhysicalPresentationDeadline deadline = appOwnedExternal ?', 1)[1].split(
            ': externalClockAvailable ?', 1)[0]
        self.assertEqual(app_owned_planning.count('externalPhysicalClock.trackedPlanningAnchorNs()'), 2)
        self.assertNotIn('externalPhysicalClock.anchorNs()', app_owned_planning)

    def test_recent_epoch_prediction_stays_within_physical_slot_tolerance(self):
        jdk = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
        javac = str(jdk / 'javac') if (jdk / 'javac').exists() else shutil.which('javac')
        java = str(jdk / 'java') if (jdk / 'java').exists() else shutil.which('java')
        if not javac or not java:
            self.skipTest('JDK unavailable')
        source = ROOT / 'unified-android/src/com/thorium/lucent/video/PhysicalPresentationClock.java'
        harness = '''
import com.thorium.lucent.video.PhysicalPresentationClock;
public class EpochDriftProbe {
    public static void main(String[] args) {
        PhysicalPresentationClock c = new PhysicalPresentationClock();
        long nominal=8333333L, oldPeriod=8337256L, recentPeriod=8334884L;
        long now=1000000000L;
        c.record(now, nominal);
        for(int i=0;i<7200;i++) {
            now+=oldPeriod;
            if(!c.record(now,nominal)) throw new IllegalStateException("warmup rejected");
        }
        c.beginPresentationEpoch();
        now+=recentPeriod;
        if(!c.record(now,nominal)) throw new IllegalStateException("epoch rejected");
        long maxError=0;
        for(int i=1;i<=600;i++) {
            now+=recentPeriod;
            if(!c.record(now,nominal)) throw new IllegalStateException("row rejected");
            // Forecast five scans ahead using the same anchor/period consumed
            // by production planning. All actual observations are perfectly
            // periodic: no drops, callback noise, or inference work involved.
            long forecast=c.trackedPlanningAnchorNs()+(c.observedScans()+5)*c.planningPeriodNs();
            maxError=Math.max(maxError,Math.abs(forecast-(now+5*recentPeriod)));
        }
        long tolerance=Math.max(150000L,Math.round(recentPeriod*0.02));
        System.out.println("maxForecastErrorNs="+maxError+" toleranceNs="+tolerance);
        if(maxError>tolerance) throw new AssertionError("epoch forecast drift");
    }
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'EpochDriftProbe.java'
            path.write_text(harness)
            subprocess.run([javac, '-d', temporary, str(source), str(path)],
                           check=True, capture_output=True, text=True)
            result = subprocess.run([java, '-cp', temporary, 'EpochDriftProbe'],
                                    capture_output=True, text=True)
            # Compilation/setup errors must not count as the known regression.
            self.assertIn('maxForecastErrorNs=', result.stdout)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
