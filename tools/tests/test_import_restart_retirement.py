"""Import restart must not terminate a guest or an unfinished exit checkpoint."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.tests.test_secondary_display_focus import method

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / "unified-android/src/com/thorium/preview/game/InWindowGameHost.java"
SERVICE = ROOT / "android-companion/src/com/thorium/preview/PreviewService.java"


class ImportRestartRetirementTests(unittest.TestCase):
    def test_actual_atomic_reservation_waits_for_all_sessions_and_prevents_duplicates(self):
        source = HOST.read_text()
        methods = "\n".join(method(source, signature) for signature in (
            "public static synchronized boolean tryBeginImportFrontendRestart()",
            "public static synchronized void cancelImportFrontendRestart()",
        ))
        java = """
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
public class RestartHarness {
  static Object active;
  static Set<Object> RETIRING_SESSIONS = Collections.synchronizedSet(new HashSet<>());
  static int destroyedSessionsRetiring;
  static boolean cleanFrontendRestartPending, importFrontendRestartPending;
  static boolean qtTerminalShutdownRequested;
  METHODS
  static void check(boolean ok) { if (!ok) throw new AssertionError(); }
  public static void main(String[] args) throws Exception {
    active = new Object(); check(!tryBeginImportFrontendRestart());
    Object first = active, second = new Object();
    RETIRING_SESSIONS.add(first); active = null;
    // The library is visible, but the first save has not finished.
    for (int retry = 0; retry < 1000; retry++) check(!tryBeginImportFrontendRestart());
    RETIRING_SESSIONS.add(second);
    RETIRING_SESSIONS.remove(first); check(!tryBeginImportFrontendRestart());
    RETIRING_SESSIONS.remove(second);
    // Activity destruction has unpublished the guest, but native release
    // still owns it. Import restart must wait even with the ordinary set empty.
    destroyedSessionsRetiring = 1;
    check(!tryBeginImportFrontendRestart());
    check(!importFrontendRestartPending);
    destroyedSessionsRetiring = 0;
    qtTerminalShutdownRequested = true; check(!tryBeginImportFrontendRestart());
    qtTerminalShutdownRequested = false;
    cleanFrontendRestartPending = true; check(!tryBeginImportFrontendRestart());
    cleanFrontendRestartPending = false;
    AtomicInteger winners = new AtomicInteger();
    Runnable attempt = () -> { if (tryBeginImportFrontendRestart()) winners.incrementAndGet(); };
    Thread a = new Thread(attempt), b = new Thread(attempt);
    a.start(); b.start(); a.join(); b.join(); check(winners.get() == 1);
    check(importFrontendRestartPending && !tryBeginImportFrontendRestart());
    cancelImportFrontendRestart(); check(!importFrontendRestartPending);
    check(tryBeginImportFrontendRestart()); // bridge launch failure is retryable
  }
}
""".replace("METHODS", methods)
        jdk = Path(os.environ.get("JAVA_HOME",
            "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home")) / "bin"
        with tempfile.TemporaryDirectory(prefix="emufusion-restart-") as folder:
            target = Path(folder) / "RestartHarness.java"
            target.write_text(java)
            for command in ([str(jdk / "javac"), str(target)],
                            [str(jdk / "java"), "-cp", folder, "RestartHarness"]):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_restart_checks_before_blanking_or_starting_bridge_and_rearms(self):
        source = SERVICE.read_text()
        reload = method(source, "private void reloadEmuFusionFrontend()")
        guard = reload.index("InWindowGameHost.tryBeginImportFrontendRestart()")
        self.assertLess(guard, reload.index("placementBlank = true"))
        self.assertLess(guard, reload.index("frontendOwner.startActivity(restart)"))
        deferred = reload[guard:reload.index("importReloadWaitLogged = false")]
        self.assertIn("launchRouteReloadPending.set(true)", deferred)
        self.assertIn("return;", deferred)
        failed = reload.split("catch (RuntimeException error)", 1)[1]
        self.assertIn("cancelImportFrontendRestart()", failed)
        self.assertIn("launchRouteReloadPending.set(true)", failed)
        self.assertIn("!frontendOwner.hasWindowFocus()", reload)
        self.assertIn("gameplayActive || browserActive || screensaverActive", reload)

    def test_new_game_cannot_start_between_reservation_and_process_restart(self):
        host = HOST.read_text()
        launch = method(host, "public static synchronized boolean handleIntent(")
        self.assertLess(launch.index("cleanFrontendRestartPending || importFrontendRestartPending"),
                        launch.index("new InWindowGameHost"))
        retirement = method(host, "private void exitToLibrary(")
        self.assertLess(retirement.index("RETIRING_SESSIONS.add(ending)"),
                        retirement.index("returnToLibraryUi("))


if __name__ == "__main__":
    unittest.main()
