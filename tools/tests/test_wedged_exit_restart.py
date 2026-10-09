"""Exit from a wedged core must not leave its last frame covering the library.

October 8 clean-phone run: BlastEm stopped returning from retro_run; Exit
returned to the library over the retained Surface ('Core frame still running at
exit'), but the checkpoint could never finish, so the frozen frame stayed on top
until the app was force-stopped.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
HOST = ROOT / 'unified-android/src/com/thorium/preview/game/InWindowGameHost.java'


def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


PROBE = r'''
import java.util.concurrent.atomic.AtomicBoolean;
public class WedgedExitProbe {
  static final String TAG = "test";
  static boolean qtTerminalShutdownRequested;
  interface EngineSession {}
  static class Request { String engineId = "blastem", systemId = "megadrive"; }
  static class Activity {
    boolean finishing, destroyed, throwOnStart; int starts;
    boolean isFinishing() { return finishing; }
    boolean isDestroyed() { return destroyed; }
    void startActivity(Object intent) {
      if (throwOnStart) throw new RuntimeException("no bridge");
      starts++;
    }
  }
  static class FrontendRestartActivity { static Object createIntent(Activity a) { return new Object(); } }
  static class Log {
    static void w(String t, String m) {}
    static void e(String t, String m, Throwable f) {}
  }
  static int kills;
  static class Process { static int myPid() { return 1; } static void killProcess(int pid) { kills++; } }
  static class android { static class os { static class Process {
    static int myPid() { return 1; } static void killProcess(int pid) { kills++; } } } }
  final Activity activity = new Activity();
  final Request request = new Request();
  final AtomicBoolean cleanFrontendRestartStarted = new AtomicBoolean(false);
  volatile EngineSession retiringSession;
  METHOD
  static void check(boolean ok, String what) { if (!ok) throw new AssertionError(what); }
  public static void main(String[] args) {
    EngineSession ending = new EngineSession() {};
    WedgedExitProbe h = new WedgedExitProbe();
    h.retiringSession = ending;
    h.restartFrontendIfExitWedged(ending);
    check(h.activity.starts == 1, "wedged retirement restarts the frontend");
    h.restartFrontendIfExitWedged(ending);
    check(h.activity.starts == 1, "restart bridge is started at most once");

    h = new WedgedExitProbe();
    h.retiringSession = null;
    h.restartFrontendIfExitWedged(ending);
    check(h.activity.starts == 0, "finished checkpoint does not restart");

    h = new WedgedExitProbe();
    h.retiringSession = new EngineSession() {};
    h.restartFrontendIfExitWedged(ending);
    check(h.activity.starts == 0, "a later session is not restarted for an older exit");

    h = new WedgedExitProbe();
    h.retiringSession = ending; h.activity.finishing = true;
    h.restartFrontendIfExitWedged(ending);
    check(h.activity.starts == 0, "finishing activity is left alone");

    h = new WedgedExitProbe();
    h.retiringSession = ending; qtTerminalShutdownRequested = true;
    h.restartFrontendIfExitWedged(ending);
    check(h.activity.starts == 0, "terminal shutdown already owns the process");
    qtTerminalShutdownRequested = false;

    h = new WedgedExitProbe();
    h.retiringSession = ending; h.activity.throwOnStart = true;
    h.restartFrontendIfExitWedged(ending);
    check(kills == 1, "unstartable bridge terminates the wedged process");
    System.out.println("wedged exit probe passed");
  }
}
'''


class WedgedExitRestartTest(unittest.TestCase):
    def test_actual_watchdog_method(self):
        source = HOST.read_text()
        body = method(source, 'private void restartFrontendIfExitWedged(')
        with tempfile.TemporaryDirectory(prefix='wedged-exit-') as temporary:
            path = Path(temporary) / 'WedgedExitProbe.java'
            path.write_text(PROBE.replace('METHOD', body))
            compiled = subprocess.run([str(JAVA / 'javac'), '-d', temporary, str(path)],
                                      capture_output=True, text=True)
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            ran = subprocess.run([str(JAVA / 'java'), '-cp', temporary, 'WedgedExitProbe'],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
            self.assertIn('wedged exit probe passed', ran.stdout)

    def test_watchdog_is_armed_only_for_unquiesced_exit(self):
        source = HOST.read_text()
        exit_body = method(source, 'private void exitToLibrary(String reason)')
        arm = 'if (ending != null && !renderQuiesced)'
        self.assertIn(arm, exit_body)
        self.assertIn('restartFrontendIfExitWedged(ending)', exit_body)
        self.assertIn('WEDGED_EXIT_RESTART_MS', exit_body)
        self.assertLess(exit_body.index('returnToLibraryUi('), exit_body.index(arm))
        self.assertIn('private static final long WEDGED_EXIT_RESTART_MS = 15_000L;', source)


if __name__ == '__main__':
    unittest.main()
