"""Regression coverage for clean Android storage/theme setup and Qt restart."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path('/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin')
INSTALLER = ROOT / 'android-companion/src/com/thorium/preview/ThemeInstaller.java'
APPLICATION = ROOT / 'unified-android/src/com/thorium/preview/LucentApplication.java'


def method(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class FirstInstallStartupTest(unittest.TestCase):
    def test_focus_return_recovers_after_dialog_outlasts_poll_limit(self):
        source = APPLICATION.read_text()
        created = method(source, 'public void onActivityCreated(')
        self.assertIn('installFirstSetupFocusListener(activity)', created)
        extracted = '\n'.join(method(source, sig) for sig in (
            'private void installFirstSetupFocusListener(',
            'private void scheduleFirstSetupRestart(',
            'private final Runnable firstSetupRestart = new Runnable()')) + ';'
        harness = r'''
import java.lang.ref.WeakReference;
import java.util.ArrayDeque;
public class StartupFocusProbe {
  static final String LUCENT_ACTIVITY="StartupFocusProbe$Activity", TAG="test";
  static class Observer {
    interface Listener { void changed(boolean focus); }
    Listener listener;
    void addOnWindowFocusChangeListener(Listener value) { listener=value; }
  }
  static class Decor {
    final Observer observer=new Observer();
    Observer getViewTreeObserver() { return observer; }
  }
  static class Window {
    final Decor decor=new Decor();
    Decor getDecorView() { return decor; }
  }
  static class Activity {
    final Window window=new Window();
    boolean focus=false, finishing=false, destroyed=false;
    int starts=0;
    Window getWindow() { return window; }
    boolean hasWindowFocus() { return focus; }
    boolean isFinishing() { return finishing; }
    boolean isDestroyed() { return destroyed; }
    void startActivity(Object intent) { starts++; }
    void focus(boolean value) {
      focus=value;
      if (window.decor.observer.listener!=null) window.decor.observer.listener.changed(value);
    }
  }
  static class OtherActivity extends Activity {}
  static class Handler {
    final ArrayDeque<Runnable> tasks=new ArrayDeque<>();
    void removeCallbacks(Runnable r) { tasks.removeIf(v -> v==r); }
    void post(Runnable r) { tasks.add(r); }
    void postDelayed(Runnable r,long delay) { tasks.add(r); }
    void drain() {
      int count=0;
      while(!tasks.isEmpty()) {
        if (++count>500) throw new AssertionError("unbounded poll");
        tasks.remove().run();
      }
    }
  }
  static class ThemeInstaller { static boolean configured=true; static boolean isFrontendConfigured() { return configured; } }
  static class FrontendRestartActivity { static Object createIntent(Activity a) { return new Object(); } }
  static class InWindowGameHost {
    static boolean busy=false;
    static boolean tryBeginImportFrontendRestart() { return !busy; }
    static void cancelImportFrontendRestart() {}
  }
  static class Log {
    static void i(String tag,String msg) {}
    static void e(String tag,String msg,RuntimeException e) {}
  }
  final Handler serviceStartHandler=new Handler();
  WeakReference<Activity> resumedFrontend=new WeakReference<>(null);
  boolean initialLibraryScanFinished=true, firstSetupRestartReady=true;
  int firstSetupFocusAttempts=0;
  static void check(boolean ok,String text) { if(!ok) throw new AssertionError(text); }
  public static void main(String[] args) {
    StartupFocusProbe app=new StartupFocusProbe();
    Activity activity=new Activity();
    app.resumedFrontend=new WeakReference<>(activity);
    if (!args[0].equals("old")) app.installFirstSetupFocusListener(activity);
    app.scheduleFirstSetupRestart();
    app.serviceStartHandler.drain();
    check(app.firstSetupFocusAttempts==150 && activity.starts==0,"retry boundary");
    activity.focus(true); // No Activity.onResume: same activity, dialog dismissed.
    app.serviceStartHandler.drain();
    check(activity.starts==1 && !app.firstSetupRestartReady,"focus recovery");
    activity.focus(false); activity.focus(true); app.serviceStartHandler.drain();
    check(activity.starts==1,"duplicate restart");
    app.firstSetupRestartReady=true; InWindowGameHost.busy=true;
    activity.focus(true); app.serviceStartHandler.drain();
    check(activity.starts==1,"active game interrupted");
    InWindowGameHost.busy=false;
    app.resumedFrontend=new WeakReference<>(null);
    activity.focus(true); app.serviceStartHandler.drain();
    check(activity.starts==1,"paused activity restarted");
    app.resumedFrontend=new WeakReference<>(activity); activity.destroyed=true;
    activity.focus(true); app.serviceStartHandler.drain();
    check(activity.starts==1,"destroyed activity restarted");
    activity.destroyed=false; app.initialLibraryScanFinished=false;
    activity.focus(true); app.serviceStartHandler.drain();
    check(activity.starts==1,"unfinished scan restarted");
    app.initialLibraryScanFinished=true; ThemeInstaller.configured=false;
    activity.focus(true); app.serviceStartHandler.drain();
    check(activity.starts==1,"unfinished setup restarted");
    OtherActivity other=new OtherActivity(); app.installFirstSetupFocusListener(other);
    check(other.window.decor.observer.listener==null,"unrelated Activity observed");
    System.out.println("focus recovery PASS");
  }
''' + extracted + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='emufusion-focus-return-') as temp:
            unit = Path(temp) / 'StartupFocusProbe.java'
            unit.write_text(harness)
            subprocess.run([str(JAVA/'javac'), str(unit)], check=True,
                           capture_output=True, text=True)
            for variant in ('old', 'fixed'):
                result = subprocess.run([str(JAVA/'java'), '-Djava.awt.headless=true',
                    '-cp', temp, 'StartupFocusProbe', variant], capture_output=True, text=True)
                if variant == 'old':
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('focus recovery', result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('focus recovery PASS', result.stdout)

    def test_settings_creation_repair_and_custom_theme_preservation(self):
        source = INSTALLER.read_text()
        methods = '\n'.join(method(source, sig) for sig in (
            'private static void updatePegasusSettings(',
            'private static void updateSettings(',
            'private static String readText(',
            'static String installedVersion(',
            'static boolean isFrontendConfigured('))
        harness = r'''
import java.io.*;
import java.nio.file.*;
import java.util.*;
public final class ThemeSetupProbe {
  static File PEGASUS, PEGASUS_CONFIG, LUCENT_CONFIG, THEME, VERSION;
  static void check(boolean ok, String why) { if (!ok) throw new AssertionError(why); }
  public static void main(String[] args) throws Exception {
    File root = new File(args[0]);
    PEGASUS = new File(root, "shared/pegasus-frontend");
    // A deliberately unwritable legacy subtree models Android's absent,
    // inaccessible OTHER package. No current setup may depend on writing it.
    File blocked = new File(root, "foreign-package");
    Files.write(blocked.toPath(), new byte[]{1});
    PEGASUS_CONFIG = new File(blocked, "files/pegasus-frontend");
    LUCENT_CONFIG = new File(root, "our-package/files/pegasus-frontend");
    THEME = new File(PEGASUS, "themes/lucent");
    VERSION = new File(THEME, ".lucent-version");
    THEME.mkdirs();
    Files.write(VERSION.toPath(), "3.2.16".getBytes());
    Files.write(new File(THEME,"theme.qml").toPath(), "import QtQuick 2.0".getBytes());
    Files.write(new File(THEME,"theme.cfg").toPath(), "name: EmuFusion".getBytes());
    check(!isFrontendConfigured(), "version marker incorrectly means setup complete");
    updatePegasusSettings(false); // Repair the partial install, not a first install.
    File settings = new File(LUCENT_CONFIG, "settings.txt");
    String value = readText(settings);
    check(value.contains("general.theme: " + THEME.getAbsolutePath() + "/"), "missing default theme");
    check(value.contains("providers.androidapps.enabled: false"), "provider not configured");
    check(isFrontendConfigured(), "repaired setup not ready");
    Files.write(settings.toPath(), "general.theme: /custom/theme/\ncustom.option: keep\nproviders.androidapps.enabled: true\n".getBytes());
    updatePegasusSettings(false);
    value = readText(settings);
    check(value.contains("general.theme: /custom/theme/"), "custom theme overwritten");
    check(value.contains("custom.option: keep"), "unrelated setting lost");
    check(!value.contains("providers.androidapps.enabled: true"), "apps provider enabled");
    String once = value;
    updatePegasusSettings(false);
    check(once.equals(readText(settings)), "repair not idempotent");
    Files.write(settings.toPath(), "general.theme:   \ncustom.option: keep\n".getBytes());
    check(!isFrontendConfigured(), "blank theme accepted");
    updatePegasusSettings(false);
    check(isFrontendConfigured(), "blank theme not repaired");
    System.out.println("first-install settings PASS");
  }
''' + methods + '\n}\n'
        with tempfile.TemporaryDirectory(prefix='emufusion-first-setup-') as temp:
            unit = Path(temp) / 'ThemeSetupProbe.java'
            unit.write_text(harness)
            subprocess.run([str(JAVA/'javac'), str(unit)], check=True,
                           capture_output=True, text=True)
            run = subprocess.run([str(JAVA/'java'), '-cp', temp, 'ThemeSetupProbe', temp],
                                 check=True, capture_output=True, text=True)
            self.assertIn('first-install settings PASS', run.stdout)

    def test_setup_uses_process_bridge_and_does_not_recreate_live_qt(self):
        source = APPLICATION.read_text()
        setup = source[source.index('private void completeFirstSetupIfNeeded('):]
        self.assertIn('boolean ready = ThemeInstaller.installBundledNow(this)', setup)
        self.assertIn('if (!ready)', setup)
        self.assertIn('FrontendRestartActivity.createIntent(owner)', setup)
        self.assertIn('owner.hasWindowFocus()', setup)
        self.assertIn('InWindowGameHost.tryBeginImportFrontendRestart()', setup)
        self.assertIn('InWindowGameHost.cancelImportFrontendRestart()', setup)
        self.assertNotIn('FLAG_ACTIVITY_CLEAR_TASK', setup)
        self.assertNotIn('finishAffinity()', setup)
        self.assertIn('firstSetupRequired = !ThemeInstaller.isFrontendConfigured()', source)
        self.assertIn('resumedFrontend = new WeakReference<>(null)', source)

    def test_setup_file_failures_are_not_mistaken_for_optional_assets(self):
        source = INSTALLER.read_text()
        self.assertNotIn('catch (java.io.FileNotFoundException missingOptionalAsset)', source)
        prepare = method(source, 'static boolean installBundledNow(')
        self.assertIn('return isFrontendConfigured()', prepare)
        self.assertIn('return false', prepare)


if __name__ == '__main__':
    unittest.main()
