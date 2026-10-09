"""Execute the production route body with deterministic Android/loader leaves."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_framegen_startup_fallback import method

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')


class RifeModeRouteTest(unittest.TestCase):
    def test_mode_display_flag_and_payload_matrix(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/FrameGenerationSettings.java').read_text()
        body = method(source, '    static QualificationTransport qualificationTransport(\n            Context context, int displayId, Mode launchMode)')
        harness = '''
public class RouteTest {
 enum Mode {OFF, BUILT_IN_ALPHA, LSFG}
 static class Context {Object getContentResolver(){return this;}}
 static class Display {static final int DEFAULT_DISPLAY=0;}
 static class Settings {static class Global {
   static int flag, reads;
   static int getInt(Object c,String k,int d){reads++;return flag;}
 }}
 static class ExternalFrameGenerationTransport {interface Factory {}}
 static class FrameGenerationBackendPolicy {enum Backend {BUILT_IN,LSFG}}
 static class QualificationTransport {
   final FrameGenerationBackendPolicy.Backend backend;
   QualificationTransport(FrameGenerationBackendPolicy.Backend b,String l,ExternalFrameGenerationTransport.Factory f){backend=b;}
 }
 static class ExternalFrameGenerationTransportLoader {
   static boolean present; static int rifeCalls,lsfgCalls;
   static final ExternalFrameGenerationTransport.Factory FACTORY=new ExternalFrameGenerationTransport.Factory(){};
   static ExternalFrameGenerationTransport.Factory rifeQualification(Context c){rifeCalls++;return present?FACTORY:null;}
   static ExternalFrameGenerationTransport.Factory lsfgQualification(Context c){lsfgCalls++;return present?FACTORY:null;}
 }
 BODY
 public static void main(String[] args){
   int cases=0;
   for(Mode m:new Mode[]{null,Mode.OFF,Mode.BUILT_IN_ALPHA,Mode.LSFG})
   for(int display:new int[]{0,4}) for(int flag:new int[]{0,1,2})
   for(boolean present:new boolean[]{false,true}) for(boolean context:new boolean[]{false,true}){
     Settings.Global.flag=flag; Settings.Global.reads=0;
     ExternalFrameGenerationTransportLoader.present=present;
     ExternalFrameGenerationTransportLoader.rifeCalls=0; ExternalFrameGenerationTransportLoader.lsfgCalls=0;
     QualificationTransport r=qualificationTransport(context?new Context():null,display,m);
     boolean eligible=context&&display==0;
     boolean rife=eligible&&m==Mode.BUILT_IN_ALPHA&&flag==1;
     boolean lsfg=eligible&&m==Mode.LSFG;
     if((r!=null)!=(present&&(rife||lsfg)))throw new AssertionError("route mismatch");
     if(r!=null && r.backend!=(rife?FrameGenerationBackendPolicy.Backend.BUILT_IN:FrameGenerationBackendPolicy.Backend.LSFG))throw new AssertionError("wrong backend");
     if(ExternalFrameGenerationTransportLoader.rifeCalls!=(rife?1:0)||ExternalFrameGenerationTransportLoader.lsfgCalls!=(lsfg?1:0))throw new AssertionError("wrong loader");
     if(Settings.Global.reads!=((eligible&&m==Mode.BUILT_IN_ALPHA)?1:0))throw new AssertionError("Off/LSFG consulted flag");
     cases++;
   }
   System.out.println("PASS "+cases+" route cases");
 }
}
'''.replace(' BODY', body)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p / 'RouteTest.java').write_text(harness)
            subprocess.run([str(JAVA / 'javac'), str(p / 'RouteTest.java')], check=True, capture_output=True)
            result = subprocess.run([str(JAVA / 'java'), '-cp', directory, 'RouteTest'], check=True, capture_output=True, text=True)
            self.assertIn('PASS 96 route cases', result.stdout)
