"""Execute the production first-frame callback against a small view fixture."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_in_window_activity_recreation import java_block

ROOT = Path(__file__).resolve().parents[2]
JDK = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')


class GameplayBootOverlayTest(unittest.TestCase):
    def test_ready_callback_dismisses_boot_once_on_ui_thread(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/game/InWindowGameHost.java').read_text()
        method = java_block(source, 'private void dismissLaunchCurtain()')
        fixture = r'''
public class BootReadyHost {
    static class View { Object parent; Object getParent() { return parent; } }
    static class Root { int removed; void removeView(View v) { v.parent=null; ++removed; } }
    static class Handler {
        Runnable pending;
        void post(Runnable r) { pending=r; }
        void removeCallbacks(Runnable r) {}
        void dispatch() { Runnable r=pending; pending=null; r.run(); }
    }
    static class BootVideoOverlay { static int finishes; static void finish() { ++finishes; } }
    static class Log { static void i(String tag, String value) {} }
    static class Request { String engineId="fake", systemId="fake"; }
    static final String TAG="test";
    Handler mainHandler=new Handler(); Runnable revealLaunchSpinner=()->{};
    Root root=new Root(); View launchCurtain, launchSpinner;
    Request request=new Request(); boolean gameplayPresented; int idleUpdates;
    void updateGameplayScreenOn() { ++idleUpdates; }
    void attach() {
        launchCurtain=new View(); launchCurtain.parent=root;
        launchSpinner=new View(); launchSpinner.parent=root;
    }
    static void require(boolean value) { if(!value) throw new AssertionError(); }
    public static void main(String[] args) {
        BootReadyHost host=new BootReadyHost(); host.attach();
        require(BootVideoOverlay.finishes==0); // Loading alone is not ready.
        host.dismissLaunchCurtain();
        require(BootVideoOverlay.finishes==0 && !host.gameplayPresented);
        host.mainHandler.dispatch();
        require(BootVideoOverlay.finishes==1 && host.gameplayPresented);
        require(host.root.removed==2 && host.idleUpdates==1);
        require(host.launchCurtain==null && host.launchSpinner==null);
        host.dismissLaunchCurtain(); host.mainHandler.dispatch();
        require(BootVideoOverlay.finishes==1 && host.idleUpdates==1);
        // A callback queued before teardown must not dismiss another boot.
        BootReadyHost retired=new BootReadyHost(); retired.attach();
        retired.dismissLaunchCurtain(); retired.launchCurtain=null;
        retired.launchSpinner=null; retired.root=null;
        retired.mainHandler.dispatch();
        require(BootVideoOverlay.finishes==1 && !retired.gameplayPresented);
    }
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            java = path / 'BootReadyHost.java'
            java.write_text(fixture + method + '\n}\n')
            subprocess.run([str(JDK / 'javac'), '--release', '8', str(java)], check=True)
            subprocess.run([str(JDK / 'java'), '-cp', str(path), 'BootReadyHost'], check=True)


if __name__ == '__main__':
    unittest.main()
