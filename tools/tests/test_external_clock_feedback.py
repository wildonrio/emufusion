from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA, GAME


class ExternalClockFeedbackTest(unittest.TestCase):
    def test_production_publication_body(self):
        body = method((GAME / 'DisplayFrameGenerator.java').read_text(),
                      '    private void publishExternalPhysicalClock()')
        source = '''
public class ClockTest {
 static class Clock {double hz; long actual; double sustainedFrequencyHz(long n){return hz;} long lastActualNs(){return actual;}}
 static class Rate {int sets,refines;boolean accept;
   double declaredPanelHz(){return 120;} void setPhysicalDisplayRefreshHz(double h){sets++;}
   boolean refinePhysicalDisplayRefreshHz(double h){refines++;return accept;}}
 Clock externalPhysicalClock=new Clock(); Rate frameRate=new Rate();
 double qualifiedPhysicalPanelHz;long qualifiedPhysicalPanelRefinedNs,qualifiedPhysicalPanelObservedNs;
 BODY
 static void check(boolean b){if(!b)throw new AssertionError();}
 public static void main(String[] a){
   ClockTest t=new ClockTest();
   t.publishExternalPhysicalClock();check(t.frameRate.sets==0);
   t.externalPhysicalClock.hz=100;t.publishExternalPhysicalClock();check(t.frameRate.sets==0);
   t.externalPhysicalClock.hz=119.95;t.externalPhysicalClock.actual=1000000000L;
   t.publishExternalPhysicalClock();check(t.frameRate.sets==1&&t.qualifiedPhysicalPanelHz==119.95);
   t.externalPhysicalClock.hz=119.96;t.externalPhysicalClock.actual=2000000000L;
   t.publishExternalPhysicalClock();check(t.frameRate.refines==0&&t.qualifiedPhysicalPanelObservedNs==2000000000L);
   t.externalPhysicalClock.actual=7000000000L;t.publishExternalPhysicalClock();
   check(t.frameRate.refines==1&&t.qualifiedPhysicalPanelHz==119.95);
   t.frameRate.accept=true;t.publishExternalPhysicalClock();check(t.qualifiedPhysicalPanelHz==119.96);
   t.externalPhysicalClock.hz=0;t.externalPhysicalClock.actual=9000000000L;
   t.publishExternalPhysicalClock();check(t.qualifiedPhysicalPanelObservedNs==7000000000L);
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ClockTest.java';p.write_text(source)
            subprocess.run([str(JAVA/'javac'),str(p)],check=True,capture_output=True)
            subprocess.run([str(JAVA/'java'),'-cp',d,'ClockTest'],check=True,capture_output=True)
