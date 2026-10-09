"""Exercise the production port setup and its pre-render placement."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_in_window_activity_recreation import java_block

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'unified-android/src/com/thorium/preview/game/PpssppGlesEngineSession.java'
JDK = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'), 'bin')


class FlycastControllerPortsTest(unittest.TestCase):
    def test_actual_setup_completes_all_ports_without_extra_controllers(self):
        method = java_block(SOURCE.read_text(),
                            'private void configureInitialControllerPorts(')
        fixture = r'''
public class PortSetup {
    static final String TAG="test";
    static class Log { static void i(String t, String m) {} }
    static class Entry { String id; Entry(String id) { this.id=id; } }
    Entry entry;
    PortSetup(String id) { entry=new Entry(id); }
    static class ExperimentalGlesRenderLoop {
        // Native load already sets port zero. Flycast's first-run gate
        // requires every slot to stop being -1 before expansion setup.
        int[] devices={1,-1,-1,-1}; int next=1, updates; int failAt=-1;
        void setControllerPortDevice(int port, int device) {
            if(port==failAt) throw new IllegalStateException("port failure");
            if(port!=next++ || device!=0) throw new AssertionError("port order/type");
            devices[port]=device;
            boolean complete=true;
            for(int value:devices) complete &= value!=-1;
            if(complete) ++updates;
        }
    }
    static void check(boolean value) { if(!value) throw new AssertionError(); }
    public static void main(String[] args) {
        PortSetup host=new PortSetup("flycast");
        ExperimentalGlesRenderLoop loop=new ExperimentalGlesRenderLoop();
        host.configureInitialControllerPorts(loop);
        check(loop.next==4 && loop.updates==1 && loop.devices[0]==1);
        // Each new session must initialize again; no process-wide latch.
        loop=new ExperimentalGlesRenderLoop();
        host.configureInitialControllerPorts(loop);
        check(loop.updates==1);
        for(String id:new String[]{"dolphin","ppsspp","azahar","armsx2","mupen64plus-next",null}) {
            loop=new ExperimentalGlesRenderLoop();
            new PortSetup(id).configureInitialControllerPorts(loop);
            check(loop.next==1 && loop.updates==0);
        }
        loop=new ExperimentalGlesRenderLoop(); loop.failAt=2;
        try { host.configureInitialControllerPorts(loop); throw new AssertionError(); }
        catch(IllegalStateException expected) { check(loop.next==2 && loop.updates==0); }
    }
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            java = path / 'PortSetup.java'
            java.write_text(fixture + method + '\n}\n')
            subprocess.run([str(JDK/'javac'), '--release', '8', str(java)], check=True)
            subprocess.run([str(JDK/'java'), '-cp', str(path), 'PortSetup'], check=True)

    def test_setup_precedes_publication_and_uses_existing_failure_cleanup(self):
        source = SOURCE.read_text()
        call = source.index('configureInitialControllerPorts(loop);')
        info = source.index('loop.avInfo();', call)
        cleanup = source.index('loop.close();', call)
        publish = source.index('renderLoop = loop;', call)
        self.assertLess(call, info)
        self.assertLess(info, cleanup)
        self.assertLess(cleanup, publish)
        # Display-clock setup may precede port setup in the same cleanup
        # scope. Require both setup and AV publication to remain protected,
        # without assuming the controller call is the first statement.
        guarded = java_block(source[source.rfind('try {', 0, call):], 'try {')
        self.assertIn('configureInitialControllerPorts(loop);', guarded)
        self.assertIn('loop.avInfo();', guarded)
        self.assertNotIn('renderLoop = loop;', guarded)
        tail = source[source.rfind('try {', 0, call) + len(guarded):]
        self.assertTrue(tail.lstrip().startswith('catch (Throwable failure)'))
        self.assertIn('loop.close();', java_block(tail, 'catch (Throwable failure)'))


if __name__ == '__main__':
    unittest.main()
