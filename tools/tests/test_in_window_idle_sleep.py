"""Execute the actual host idle-sleep policy, then check lifecycle wiring."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_in_window_activity_recreation import java_block

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / 'unified-android/src/com/thorium/preview/game/InWindowGameHost.java'
JDK = Path(os.environ.get('JAVA_HOME', '/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home'), 'bin')


class InWindowIdleSleepTest(unittest.TestCase):
    def test_actual_policy_all_states_and_ui_dispatch(self):
        source = HOST.read_text()
        policy = java_block(source, 'private boolean shouldKeepGameplayScreenOn()')
        update = java_block(source, 'private void updateGameplayScreenOn()')
        fixture = r'''
import java.util.concurrent.atomic.AtomicBoolean;
public class IdleScreenHost {
    static class Root { boolean kept; int writes;
        boolean getKeepScreenOn() { return kept; }
        void setKeepScreenOn(boolean value) { kept=value; ++writes; }
    }
    static class Looper {
        static final Object MAIN = new Object(); static boolean onMain = true;
        static Object myLooper() { return onMain ? MAIN : null; }
        static Object getMainLooper() { return MAIN; }
    }
    static class Handler { Runnable pending; void post(Runnable work) { pending=work; } }
    static class Log { static void i(String tag, String text) {} }
    static class Request { String engineId="fake", systemId="fake"; }
    static final String TAG="test";
    Root root; Object session, oledGuard; Request request=new Request();
    boolean prepared, gameplayPresented, resumed, surfaceAvailable, menuVisible;
    boolean fatalErrorVisible, libraryReturned;
    AtomicBoolean exitStarted=new AtomicBoolean(); Handler mainHandler=new Handler();
    void set(int mask) {
        root=(mask&1)!=0 ? new Root() : null;
        session=(mask&2)!=0 ? new Object() : null;
        prepared=(mask&4)!=0; gameplayPresented=(mask&8)!=0;
        resumed=(mask&16)!=0; surfaceAvailable=(mask&32)!=0;
        menuVisible=(mask&64)!=0; fatalErrorVisible=(mask&128)!=0;
        exitStarted.set((mask&256)!=0); libraryReturned=(mask&512)!=0;
        oledGuard=(mask&1024)!=0 ? new Object() : null;
    }
    static void require(boolean value) { if(!value) throw new AssertionError(); }
    public static void main(String[] args) {
        IdleScreenHost host=new IdleScreenHost();
        for(int state=0;state<2048;++state) {
            host.set(state);
            require(host.shouldKeepGameplayScreenOn()==(state==63));
            host.updateGameplayScreenOn();
            if(host.root!=null) require(host.root.kept==(state==63));
        }
        host.set(63); host.updateGameplayScreenOn(); host.updateGameplayScreenOn();
        require(host.root.kept && host.root.writes==1);
        host.menuVisible=true; host.updateGameplayScreenOn();
        require(!host.root.kept && host.root.writes==2);
        host.menuVisible=false; Looper.onMain=false; host.updateGameplayScreenOn();
        require(!host.root.kept && host.mainHandler.pending!=null);
        // A background transition before dispatch must defeat the stale request.
        host.resumed=false; Looper.onMain=true; host.mainHandler.pending.run();
        require(!host.root.kept);
        host.resumed=true; host.updateGameplayScreenOn(); require(host.root.kept);
        host.exitStarted.set(true); host.updateGameplayScreenOn(); require(!host.root.kept);
    }
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            java = path / 'IdleScreenHost.java'
            java.write_text(fixture + policy + '\n' + update + '\n}\n')
            subprocess.run([str(JDK/'javac'), '--release', '8', str(java)], check=True)
            subprocess.run([str(JDK/'java'), '-cp', str(path), 'IdleScreenHost'], check=True)

    def test_lifecycle_transitions_update_request(self):
        source = HOST.read_text()
        signatures = [
            'public static synchronized void onResume(Activity activity)',
            'public static synchronized void onPause(Activity activity)',
            'private void replaceWith(GameLaunchRequest next)',
            'private void dismissLaunchCurtain()', 'private void showPauseMenu()',
            'private void hidePauseMenu()', 'private void exitToLibrary(String reason)',
            'private void destroyNow()',
            'public void onSurfaceAvailable(Surface surface, int width, int height)',
            'public void onSurfaceDestroyed()',
            'public void onSurfaceStartupError(String message, Throwable cause)',
            'public void onSurfaceRuntimeError(String message, Throwable cause)',
            'public void onSessionReady()',
            'public void onSessionStopRejected(String message, Throwable cause)',
            'private void showFatalError(String message, boolean runtimeFailure)',
            'private void observeReportedOutput(double output)',
            'private void clearOledGuard()',
        ]
        for signature in signatures:
            with self.subTest(signature=signature):
                self.assertIn('updateGameplayScreenOn();', java_block(source, signature))
        detach = java_block(source, 'private void detachViews()')
        self.assertLess(detach.index('root.setKeepScreenOn(false)'), detach.index('content.removeView(root)'))
        pause = java_block(source, signatures[1])
        self.assertLess(pause.index('active.resumed = false'), pause.index('active.updateGameplayScreenOn()'))
        self.assertLess(pause.index('active.updateGameplayScreenOn()'), pause.index('current.pause('))
        shown = java_block(source, 'private void dismissLaunchCurtain()')
        self.assertLess(shown.index('if (curtain == null) return'), shown.index('gameplayPresented = true'))

    def test_policy_does_not_change_system_settings_or_other_window_owners(self):
        source = HOST.read_text()
        update = java_block(source, 'private void updateGameplayScreenOn()')
        self.assertIn('root.setKeepScreenOn(keepOn)', update)
        for forbidden in ['Settings.', 'WakeLock', 'getWindow()', 'FLAG_TURN_SCREEN_ON', 'wakeUp(']:
            self.assertNotIn(forbidden, update)


if __name__ == '__main__':
    unittest.main()
