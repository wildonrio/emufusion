"""Execute real source-clock publication and system policy with renderer leaves."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.tests.test_framegen_startup_fallback import method, JAVA, GAME


class PrimaryPacedAuthorityTest(unittest.TestCase):
    def test_effective_rate_and_variable_source_exclusion(self):
        session = (GAME / 'LibretroEngineSession.java').read_text()
        host = (GAME / 'InWindowGameHost.java').read_text()
        bodies = '\n'.join(method(session, signature) for signature in (
            '    public double effectiveVideoHz()',
            '    private void publishPrimarySourceCadence()'))
        policy = method(host, '    static double authoritativeVideoHz(')
        source = '''
import java.util.Locale;
public class PrimaryClockTest {
 static class GameLaunchRequest {String systemId;}
 static class FrameGenerationRenderer {int calls;double hz;void setAuthoritativeSourceHz(double v){calls++;hz=v;}}
 static class FrameGenerationRendererRegistry {
   static FrameGenerationRenderer renderer;
   static FrameGenerationRenderer find(Object surface){return renderer;}
 }
 static class InWindowGameHost {POLICY}
 GameLaunchRequest request;Object surface=new Object();double pacedCoreHz,synchronizedCoreHz;
 BODIES
 static void check(boolean value){if(!value)throw new AssertionError();}
 public static void main(String[] args){
   PrimaryClockTest t=new PrimaryClockTest();
   FrameGenerationRenderer r=new FrameGenerationRenderer();
   FrameGenerationRendererRegistry.renderer=r;
   t.publishPrimarySourceCadence();check(r.calls==0);
   t.request=new GameLaunchRequest();t.request.systemId="nes";
   t.synchronizedCoreHz=60;t.publishPrimarySourceCadence();check(r.calls==1&&r.hz==60);
   t.pacedCoreHz=59.975269;t.publishPrimarySourceCadence();check(r.calls==2&&r.hz==59.975269);
   for(String s:new String[]{"n64","nds","psx","gamecube","wii",null,"unknown"}){
     t.request.systemId=s;t.publishPrimarySourceCadence();check(r.calls==2);
   }
   t.request.systemId="snes";t.pacedCoreHz=0;t.publishPrimarySourceCadence();check(r.calls==3&&r.hz==60);
   FrameGenerationRendererRegistry.renderer=null;t.publishPrimarySourceCadence();check(r.calls==3);
   FrameGenerationRendererRegistry.renderer=r;t.synchronizedCoreHz=0;t.publishPrimarySourceCadence();check(r.calls==3);
 }
}
'''.replace('POLICY', policy).replace('BODIES', bodies)
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'PrimaryClockTest.java';p.write_text(source)
            subprocess.run([str(JAVA/'javac'),str(p)],check=True,capture_output=True)
            subprocess.run([str(JAVA/'java'),'-cp',directory,'PrimaryClockTest'],check=True,capture_output=True)
