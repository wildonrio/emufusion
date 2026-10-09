"""A durable local scan must reach the menu before optional online enrichment."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.tests.test_first_install_startup import JAVA, ROOT, method

IMPORTER = ROOT / "android-companion/src/com/thorium/preview/ImportManager.java"
APP = ROOT / "unified-android/src/com/thorium/preview/LucentApplication.java"


class OfflineRescanRefreshTest(unittest.TestCase):
    def test_request_follows_durable_local_publication_and_precedes_network(self):
        scan = method(IMPORTER.read_text(), "private void runScan(boolean fullDiscovery)")
        self.assertIn("boolean localIndexChanged = false;", scan)
        changed = scan.index("localIndexChanged = true;")
        self.assertLess(scan.index("writeJsonAtomic(REGISTRY, registry);"), changed)
        self.assertLess(scan.index("writeMetadata(registry);"), changed)
        self.assertEqual(scan.count("localIndexChanged = true;"), 1)
        self.assertIn("localIndexChanged |= writeMetadata(registry);", scan)
        request = scan.index("((LucentApplication) app).onLibraryIndexChanged();")
        self.assertLess(scan.index("LaunchMetadataRouter.normalize(context);"), request)
        self.assertLess(request, scan.index("!enrichMediaQueue("))
        self.assertIn("if (localIndexChanged || prerequisiteRoutesChanged)", scan)

    def test_callback_uses_existing_guarded_restart_on_ui_thread(self):
        source = APP.read_text()
        callback = method(source, "void onLibraryIndexChanged()")
        harness = r'''
import java.util.*;
public class RefreshProbe {
  static class Handler {
    final ArrayDeque<Runnable> queued = new ArrayDeque<>();
    void post(Runnable work) { queued.add(work); }
  }
  final Handler serviceStartHandler = new Handler();
  boolean firstSetupRestartReady;
  int firstSetupFocusAttempts = 149;
  int scheduled;
  void scheduleFirstSetupRestart() { scheduled++; }
  CALLBACK
  static void check(boolean value) { if (!value) throw new AssertionError(); }
  public static void main(String[] args) {
    RefreshProbe probe = new RefreshProbe();
    probe.onLibraryIndexChanged();
    check(!probe.firstSetupRestartReady && probe.scheduled == 0);
    probe.serviceStartHandler.queued.remove().run();
    check(probe.firstSetupRestartReady && probe.firstSetupFocusAttempts == 0);
    check(probe.scheduled == 1);
  }
}
'''.replace("CALLBACK", callback)
        with tempfile.TemporaryDirectory(prefix="emufusion-offline-refresh-") as temp:
            java = Path(temp) / "RefreshProbe.java"
            java.write_text(harness)
            subprocess.run([str(JAVA / "javac"), str(java)], check=True,
                           capture_output=True, text=True)
            subprocess.run([str(JAVA / "java"), "-cp", temp, "RefreshProbe"],
                           check=True, capture_output=True, text=True)
        guarded = method(source, "private final Runnable firstSetupRestart = new Runnable()")
        self.assertLess(guarded.index("InWindowGameHost.tryBeginImportFrontendRestart()"),
                        guarded.index("owner.startActivity("))
        self.assertIn("owner.hasWindowFocus()", guarded)


if __name__ == "__main__":
    unittest.main()
