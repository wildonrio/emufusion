"""Execute production resume/handoff methods with a small Java lifecycle harness."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.tests.test_secondary_display_focus import method, COMPANION


class SecondaryResumeHandoffTests(unittest.TestCase):
    def test_posted_transform_does_not_outlive_its_surface(self):
        preview = (COMPANION / "PreviewActivity.java").read_text()
        transform = method(preview,
                           "private void postClockwiseSurfaceTransform(SurfaceView owner, long generation)")
        harness = """
import java.util.ArrayList;
public class TransformHarness {
  static class SurfaceControl {
    static final int BUFFER_TRANSFORM_ROTATE_90 = 4;
    boolean valid = true;
    int applied;
    boolean isValid() { return valid; }
    static class Transaction implements AutoCloseable {
      static int closed;
      SurfaceControl target;
      Transaction setBufferTransform(SurfaceControl control, int rotation) {
        if (control == null || !control.valid || rotation != 4) throw new AssertionError();
        target = control; return this;
      }
      void apply() { target.applied++; }
      public void close() { closed++; }
    }
  }
  static class SurfaceView {
    SurfaceControl control = new SurfaceControl();
    boolean attached = true;
    ArrayList<Runnable> pending = new ArrayList<>();
    void post(Runnable callback) { pending.add(callback); }
    void drain() { for (Runnable callback : pending) callback.run(); pending.clear(); }
    boolean isAttachedToWindow() { return attached; }
    SurfaceControl getSurfaceControl() { return control; }
  }
  static class SecondaryGameplaySurfaceRouter {
    static boolean live = true;
    static boolean isCurrent(long generation) { return live && generation == 7; }
  }
  static class Preview {
    SurfaceView gameplaySurface;
    long gameplayGeneration = 7, gameplayQuarantinedGeneration = -1;
    __PRODUCTION_METHOD__
  }
  static void check(boolean ok) { if (!ok) throw new AssertionError(); }
  public static void main(String[] args) {
    Preview p = new Preview();
    SurfaceView old = p.gameplaySurface = new SurfaceView();
    p.postClockwiseSurfaceTransform(old, 7);
    p.gameplaySurface = null; // exact on-device wake NPE, before dispatch
    old.drain(); check(old.control.applied == 0);
    p.gameplaySurface = old;
    p.postClockwiseSurfaceTransform(old, 7);
    SurfaceView replacement = p.gameplaySurface = new SurfaceView();
    old.drain(); check(replacement.control.applied == 0 && old.control.applied == 0);
    p.postClockwiseSurfaceTransform(replacement, 7);
    p.gameplayGeneration = 8;
    replacement.drain(); check(replacement.control.applied == 0);
    p.gameplayGeneration = 7;
    for (int failure = 0; failure < 5; failure++) {
      p.postClockwiseSurfaceTransform(replacement, 7);
      if (failure == 0) p.gameplayQuarantinedGeneration = 7;
      if (failure == 1) SecondaryGameplaySurfaceRouter.live = false;
      if (failure == 2) replacement.attached = false;
      if (failure == 3) replacement.control.valid = false;
      SurfaceControl control = replacement.control;
      if (failure == 4) replacement.control = null;
      replacement.drain(); check(control.applied == 0);
      p.gameplayQuarantinedGeneration = -1;
      SecondaryGameplaySurfaceRouter.live = true;
      replacement.attached = true;
      replacement.control = control; control.valid = true;
    }
    p.postClockwiseSurfaceTransform(replacement, 7);
    replacement.drain();
    check(replacement.control.applied == 1 && SurfaceControl.Transaction.closed == 1);
  }
}
""".replace("__PRODUCTION_METHOD__", transform)
        java_home = Path(os.environ.get(
            "JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"))
        with tempfile.TemporaryDirectory(prefix="emufusion-transform-") as folder:
            source = Path(folder) / "TransformHarness.java"
            source.write_text(harness)
            result = subprocess.run([str(java_home / "bin/javac"), str(source)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(java_home / "bin/java"), "-cp", folder,
                                     "TransformHarness"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_recreated_host_reconnects_without_replacing_live_or_stale_routes(self):
        router = (COMPANION / "SecondaryGameplaySurfaceRouter.java").read_text()
        preview = (COMPANION / "PreviewActivity.java").read_text()
        methods = "\n".join(method(router, signature) for signature in (
            "public static synchronized void attachHost(Host candidate)",
            "public static synchronized void detachHost(Host candidate)",
            "static synchronized boolean isCurrent(long candidate)",
        ))
        handoff = method(preview,
                         "public void showSecondaryGameplaySurface(long generation)")
        harness = """
import java.util.ArrayList;
public class ResumeHarness {
  interface Host { void showSecondaryGameplaySurface(long generation); }
  static class SecondaryGameplaySurfaceRouter {
    static Host host;
    static Object listener;
    static long generation;
    ROUTER_METHODS
  }
  static class Preview implements Host {
    Object gameplaySurface;
    long gameplayGeneration;
    int allocations;
    ArrayList<Runnable> ui = new ArrayList<>();
    void runOnUiThread(Runnable callback) { ui.add(callback); }
    void drain() { for (Runnable callback : ui) callback.run(); ui.clear(); }
    void showGameplaySurface(long generation) {
      allocations++; gameplayGeneration = generation; gameplaySurface = new Object();
    }
    HANDOFF
  }
  static void check(boolean ok) { if (!ok) throw new AssertionError(); }
  public static void main(String[] args) {
    Preview first = new Preview();
    SecondaryGameplaySurfaceRouter.attachHost(first);
    first.drain(); check(first.allocations == 0); // no running game
    SecondaryGameplaySurfaceRouter.listener = new Object();
    SecondaryGameplaySurfaceRouter.generation = 7;
    SecondaryGameplaySurfaceRouter.attachHost(first);
    first.drain(); check(first.allocations == 1);
    Object holder = first.gameplaySurface;
    SecondaryGameplaySurfaceRouter.detachHost(first);
    SecondaryGameplaySurfaceRouter.attachHost(first);
    first.drain(); check(first.allocations == 1 && first.gameplaySurface == holder);
    // Recreated Activity has no surface and a stale BLANK Intent: the live
    // route must reconnect it without requiring another game launch.
    Preview replacement = new Preview();
    SecondaryGameplaySurfaceRouter.attachHost(replacement);
    replacement.drain(); check(replacement.allocations == 1);
    SecondaryGameplaySurfaceRouter.detachHost(first);
    check(SecondaryGameplaySurfaceRouter.host == replacement);
    SecondaryGameplaySurfaceRouter.generation = 8;
    SecondaryGameplaySurfaceRouter.attachHost(replacement);
    replacement.drain(); check(replacement.allocations == 2);
    Preview stale = new Preview();
    SecondaryGameplaySurfaceRouter.attachHost(stale);
    SecondaryGameplaySurfaceRouter.generation = 9;
    stale.drain(); check(stale.allocations == 0); // replaced before UI dispatch
    SecondaryGameplaySurfaceRouter.attachHost(stale);
    SecondaryGameplaySurfaceRouter.listener = null;
    stale.drain(); check(stale.allocations == 0); // exited before UI dispatch
  }
}
""".replace("ROUTER_METHODS", methods).replace("HANDOFF", handoff)
        java_home = Path(os.environ.get(
            "JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"))
        javac = str(java_home / "bin/javac") if (java_home / "bin/javac").is_file() else shutil.which("javac")
        java = str(java_home / "bin/java") if (java_home / "bin/java").is_file() else shutil.which("java")
        self.assertIsNotNone(javac, "JDK required for lifecycle regression")
        self.assertIsNotNone(java, "JDK required for lifecycle regression")
        with tempfile.TemporaryDirectory(prefix="emufusion-resume-") as folder:
            source = Path(folder) / "ResumeHarness.java"
            source.write_text(harness)
            result = subprocess.run([javac, str(source)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([java, "-cp", folder, "ResumeHarness"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
