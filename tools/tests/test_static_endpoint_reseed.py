"""Execute actual admission code: held pixels must survive a schedule reset."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA

ROOT = Path(__file__).resolve().parents[2]


class StaticEndpointReseedTest(unittest.TestCase):
    def test_static_reseed_does_not_manufacture_unique_clock(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/DisplayFrameGenerator.java').read_text()
        body = method(source, '    private void consumeClassifiedFrame(')
        fixture = r'''
public class StaticEndpointTest {
    static class FrameRate {
        boolean sustainable;
        boolean hasSustainableGenerationRate(){return sustainable;}
        double presentationSourceHz(){return 60;}
    }
    static class AdaptiveFrameRateController {
        static boolean duplicateOccupiesNextSourceSlot(long a,long b,double h,long c,long d){return false;}
    }
    FrameRate frameRate=new FrameRate();
    boolean classifiedFrameReady=true;
    int classifiedUniqueTexture=7,classifiedUniqueSubmission=2;
    long classifiedUniqueTimestampNs=100, lastPresentationEndpointTimestampNs;
    int lastPresentationEndpointSubmission,endpointCandidateUnavailable;
    static final int NATIVE_ADMISSION_SLOT=1;
    int accepted, unique, released;
    void acceptPresentationEndpoint(int texture,long timestamp,int submission){
        assert texture==7 && timestamp==classifiedUniqueTimestampNs;
        lastPresentationEndpointTimestampNs=timestamp;
        lastPresentationEndpointSubmission=submission;accepted++;
    }
    boolean observeUniqueFrame(long time,int submission){unique++;return true;}
    void releaseNativeEndpointProvenance(int slot){released++;}
''' + body + r'''
    public static void main(String[] args){
        StaticEndpointTest t=new StaticEndpointTest();
        t.consumeClassifiedFrame(false);
        assert t.accepted==1 && t.unique==0 : "static image stranded or counted as motion";
        t.classifiedUniqueTimestampNs++;
        t.consumeClassifiedFrame(false);
        assert t.accepted==1 && t.unique==0 : "held image creates repeated endpoint traffic";
        t.lastPresentationEndpointTimestampNs=0; // actual reset boundary
        t.consumeClassifiedFrame(false);
        assert t.accepted==2 && t.unique==0;
        t.lastPresentationEndpointTimestampNs=0;
        t.frameRate.sustainable=true;
        t.consumeClassifiedFrame(false);
        assert t.accepted==2 : "generated schedule bypassed slot ownership";
        t.frameRate.sustainable=false;t.classifiedUniqueTimestampNs=0;
        t.consumeClassifiedFrame(false);
        assert t.accepted==2 && t.endpointCandidateUnavailable==1;
        assert t.released==5;
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='static-endpoint-') as directory:
            out = Path(directory)
            java = out / 'StaticEndpointTest.java'
            java.write_text(fixture)
            subprocess.run([str(JAVA / 'javac'), '--release', '8', '-d', str(out), str(java)],
                           check=True, capture_output=True, text=True, timeout=30)
            subprocess.run([str(JAVA / 'java'), '-ea', '-cp', str(out), 'StaticEndpointTest'],
                           check=True, capture_output=True, text=True, timeout=15)
