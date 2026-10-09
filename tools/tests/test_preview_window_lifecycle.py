"""Execute preview lifecycle/launch guards with a tiny fake Android boundary.

The lifecycle callbacks, watchdog and final launch method are read verbatim
from production. The real owner ledger, focus guard and boot receiver compile
alongside them. No device, emulator core, application build or sleep is used.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "android-companion/src/com/thorium/preview"
JAVA = Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home/bin")


def member(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("Unterminated Java member: " + signature)


STUBS = {
    "android/content/Context.java": """
package android.content;
import android.app.ActivityManager;
import android.hardware.display.DisplayManager;
import android.os.PowerManager;
public class Context {
    public static final String POWER_SERVICE = "power", ACTIVITY_SERVICE = "activity",
            DISPLAY_SERVICE = "display";
    public PowerManager power = new PowerManager();
    public ActivityManager manager = new ActivityManager();
    public DisplayManager displays = new DisplayManager();
    public boolean throwPower, wrongPower, overlays = true, sleepOnOverlay, sleepOnPending;
    public int starts, pendingStarts, broadcasts, serviceStarts;
    public Intent lastBroadcast;
    public Runnable onLaunch;
    public Object getSystemService(String name) {
        if (POWER_SERVICE.equals(name)) {
            if (throwPower) throw new IllegalStateException("power unavailable");
            return wrongPower ? new Object() : power;
        }
        if (ACTIVITY_SERVICE.equals(name)) return manager;
        if (DISPLAY_SERVICE.equals(name)) return displays;
        return null;
    }
    public String getPackageName() { return "com.thorium.preview"; }
    public void startActivity(Intent intent, Object options) {
        starts++;
        if (onLaunch != null) onLaunch.run();
    }
    public void startForegroundService(Intent intent) { serviceStarts++; }
    public void sendBroadcast(Intent intent) { broadcasts++; lastBroadcast = intent; }
}
""",
    "android/os/PowerManager.java": """
package android.os;
public class PowerManager {
    public boolean interactive = true, fail;
    public boolean isInteractive() {
        if (fail) throw new IllegalStateException("power read failed");
        return interactive;
    }
}
""",
    "android/os/Build.java": """
package android.os;
public class Build { public static class VERSION { public static int SDK_INT = 34; } }
""",
    "android/content/Intent.java": """
package android.content;
import java.util.HashMap;
public class Intent {
    public static final int FLAG_ACTIVITY_NEW_TASK = 1, FLAG_ACTIVITY_REORDER_TO_FRONT = 2;
    private String action;
    private final HashMap<String, String> extras = new HashMap<>();
    public Intent() {}
    public Intent(String action) { this.action = action; }
    public Intent(Context context, Class<?> target) {}
    public String getAction() { return action; }
    public Intent setAction(String action) { this.action = action; return this; }
    public Intent addFlags(int flags) { return this; }
    public Intent setPackage(String name) { return this; }
    public Intent putExtras(Intent other) { extras.putAll(other.extras); return this; }
    public Intent putExtra(String key, String value) { extras.put(key, value); return this; }
    public String getStringExtra(String key) { return extras.get(key); }
}
""",
    "android/content/BroadcastReceiver.java": """
package android.content;
public abstract class BroadcastReceiver {
    public abstract void onReceive(Context context, Intent intent);
}
""",
    "android/content/ComponentName.java": """
package android.content;
public class ComponentName {
    private final String name;
    public ComponentName(String name) { this.name = name; }
    public String getClassName() { return name; }
}
""",
    "android/app/Activity.java": """
package android.app;
public class Activity extends android.content.Context {
    protected void onStart() {}
    protected void onStop() {}
    protected void onPause() {}
}
""",
    "android/app/ActivityManager.java": """
package android.app;
import android.content.ComponentName;
import java.util.ArrayList;
import java.util.List;
public class ActivityManager {
    public final List<AppTask> tasks = new ArrayList<>();
    public Runnable onGetTasks;
    public ActivityManager() { tasks.add(new AppTask()); }
    public List<AppTask> getAppTasks() {
        if (onGetTasks != null) onGetTasks.run();
        return tasks;
    }
    public static class AppTask {
        public int moves;
        public RecentTaskInfo getTaskInfo() { return new RecentTaskInfo(); }
        public void moveToFront() { moves++; }
    }
    public static class RecentTaskInfo {
        public ComponentName topActivity = new ComponentName(
                "org.pegasus_frontend.android.MainActivity");
        public ComponentName baseActivity, origActivity;
    }
}
""",
    "android/app/ActivityOptions.java": """
package android.app;
public class ActivityOptions {
    public static final int MODE_BACKGROUND_ACTIVITY_START_ALLOWED = 1;
    public static ActivityOptions makeBasic() { return new ActivityOptions(); }
    public void setLaunchDisplayId(int id) {}
    public void setPendingIntentCreatorBackgroundActivityStartMode(int mode) {}
    public void setPendingIntentBackgroundActivityStartMode(int mode) {}
    public Object toBundle() { return null; }
}
""",
    "android/app/PendingIntent.java": """
package android.app;
import android.content.Context;
import android.content.Intent;
public class PendingIntent {
    public static final int FLAG_UPDATE_CURRENT = 1, FLAG_IMMUTABLE = 2;
    public static class CanceledException extends Exception {}
    public static PendingIntent getActivity(Context context, int request, Intent intent,
                                            int flags, Object options) {
        if (context.sleepOnPending) context.power.interactive = false;
        return new PendingIntent();
    }
    public void send(Context context, int code, Object intent, Object callback,
                     Object handler, Object permission, Object options) throws CanceledException {
        context.pendingStarts++;
        if (context.onLaunch != null) context.onLaunch.run();
    }
}
""",
    "android/provider/Settings.java": """
package android.provider;
import android.content.Context;
public class Settings {
    public static boolean canDrawOverlays(Context context) {
        if (context.sleepOnOverlay) context.power.interactive = false;
        return context.overlays;
    }
}
""",
    "android/hardware/display/DisplayManager.java": """
package android.hardware.display;
import android.view.Display;
public class DisplayManager {
    public Display[] values = {new Display(0), new Display(4)};
    public Display[] getDisplays() { return values; }
}
""",
    "android/view/Display.java": """
package android.view;
public class Display {
    public static final int DEFAULT_DISPLAY = 0;
    private final int id;
    public Display(int id) { this.id = id; }
    public int getDisplayId() { return id; }
}
""",
    "android/util/Log.java": """
package android.util;
public class Log {
    public static int i(String tag, String message) { return 0; }
    public static int w(String tag, String message) { return 0; }
    public static int e(String tag, String message, Throwable error) { return 0; }
}
""",
    "com/thorium/preview/SecondaryGameplaySurfaceRouter.java": """
package com.thorium.preview;
class SecondaryGameplaySurfaceRouter {
    static int detaches;
    static void detachHost(Object owner) { detaches++; }
}
""",
    "com/thorium/preview/SecondaryCheatPanelRouter.java": """
package com.thorium.preview;
class SecondaryCheatPanelRouter {
    static int detaches;
    static void detach(Object owner) { detaches++; }
}
""",
}


HARNESS = """
package com.thorium.preview;
import android.content.Context;
import android.content.Intent;
import android.view.Display;

public final class PreviewLifecycleHarness {
    static void check(boolean value, String label) {
        if (!value) throw new AssertionError(label);
    }
    static void noLaunch(Context context, String label) {
        check(context.starts == 0 && context.pendingStarts == 0, label);
    }
    public static void main(String[] args) {
        switch (args[0]) {
            case "focus-yield": {
                PreviewActivity activity = new PreviewActivity(true);
                activity.onStart();
                activity.onPause();
                check(!PreviewActivity.resumed, "router resumed flag still clears");
                check(SecondaryGameplaySurfaceRouter.detaches == 1, "gameplay detach");
                check(SecondaryCheatPanelRouter.detaches == 1, "cheat detach");
                check(PreviewActivity.isVisible(), "pause must keep window present");
                PreviewService service = new PreviewService();
                for (int i = 0; i < 36; i++) service.tick();
                noLaunch(service, "36 focus-yield watchdog ticks must not relaunch");
                check(service.mainHandler.posts == 36, "watchdog stays armed");
                service.request(new Intent().putExtra("title", "preserved"));
                check(service.broadcasts == 1, "existing window receives update");
                check("preserved".equals(service.lastBroadcast.getStringExtra("title")),
                      "update keeps extras");
                service.request(new Intent(PreviewService.ACTION_BLANK));
                check(PreviewService.ACTION_BLANK.equals(service.lastBroadcast.getAction()),
                      "existing blackout remains a blackout");
                noLaunch(service, "direct gateway also reuses existing window");
                activity.onStop();
                check(!PreviewActivity.isVisible(), "stopped window can recover");
                service.onLaunch = activity::onStart;
                service.tick();
                for (int i = 0; i < 36; i++) service.tick();
                check(service.starts == 1, "wake/covered-window recovery launches once");
                new PreviewActivity(false).onStart();
                check(PreviewActivity.isVisible(), "rejected instance cannot claim presence");
                break;
            }
            case "sleep": {
                PreviewActivity activity = new PreviewActivity(true);
                PreviewService service = new PreviewService();
                service.power.interactive = false;
                for (int visible = 0; visible < 2; visible++) {
                    if (visible == 1) activity.onStart();
                    for (int i = 0; i < 36; i++) service.tick();
                    service.request(new Intent());
                    service.overlays = false;
                    service.request(new Intent(PreviewService.ACTION_BLANK));
                    noLaunch(service, "noninteractive must never launch");
                }
                check(service.broadcasts == 0, "sleep gateway does not update decoders");
                check(!PrimaryDisplayFocusGuard.restorePrimaryTopFocus(service),
                      "sleep must not reorder primary task");
                check(service.manager.tasks.get(0).moves == 0, "no sleeping task move");
                new BootReceiver().onReceive(service, new Intent());
                check(service.serviceStarts == 1, "boot service work remains allowed");
                noLaunch(service, "boot must not launch asleep");
                activity.onStop();
                service.power.interactive = true;
                service.onLaunch = activity::onStart;
                service.tick();
                service.tick();
                check(service.pendingStarts == 1, "wake recovers absent preview once");
                break;
            }
            case "owner": {
                PreviewWindowState state = new PreviewWindowState();
                Object old = new Object(), replacement = new Object(), unknown = new Object();
                check(!state.isVisible(), "initially absent");
                state.created(old);
                check(!state.isVisible(), "creation is not visibility");
                state.started(old);
                check(state.isVisible(), "start makes visible");
                state.created(replacement);
                state.started(replacement);
                state.stopped(old);
                state.destroyed(old);
                state.stopped(unknown);
                state.destroyed(unknown);
                state.created(null);
                check(state.isVisible(), "stale callbacks must not clear replacement");
                state.stopped(replacement);
                state.started(old);
                check(!state.isVisible(), "stale start must not resurrect previous owner");
                state.started(replacement);
                check(state.isVisible(), "current owner restarts");
                state.destroyed(replacement);
                check(!state.isVisible(), "destroy retires current owner");
                break;
            }
            case "unknown-power": {
                check(!PrimaryDisplayFocusGuard.isInteractive(null), "null context");
                for (int fault = 0; fault < 4; fault++) {
                    PreviewService service = new PreviewService();
                    if (fault == 0) service.power = null;
                    if (fault == 1) service.throwPower = true;
                    if (fault == 2) service.power.fail = true;
                    if (fault == 3) service.wrongPower = true;
                    service.tick();
                    service.request(new Intent());
                    check(!PrimaryDisplayFocusGuard.restorePrimaryTopFocus(service),
                          "unavailable power must not reorder tasks");
                    new BootReceiver().onReceive(service, new Intent());
                    noLaunch(service, "unknown power is fail-closed");
                }
                break;
            }
            case "late-sleep": {
                PreviewService direct = new PreviewService();
                direct.sleepOnOverlay = true;
                direct.request(new Intent());
                noLaunch(direct, "sleep during launch setup cancels direct start");
                PreviewService pending = new PreviewService();
                pending.overlays = false;
                pending.sleepOnPending = true;
                pending.request(new Intent());
                noLaunch(pending, "sleep during PendingIntent creation cancels send");
                Context focus = new Context();
                focus.manager.onGetTasks = () -> focus.power.interactive = false;
                check(!PrimaryDisplayFocusGuard.restorePrimaryTopFocus(focus),
                      "sleep during task enumeration cancels reorder");
                check(focus.manager.tasks.get(0).moves == 0, "no late task move");
                break;
            }
            case "awake-paths": {
                PreviewService direct = new PreviewService();
                direct.request(new Intent());
                check(direct.starts == 1, "awake direct launch remains available");
                PreviewService pending = new PreviewService();
                pending.overlays = false;
                pending.request(new Intent());
                check(pending.pendingStarts == 1, "awake PendingIntent path remains available");
                Context boot = new Context();
                new BootReceiver().onReceive(boot, new Intent());
                check(boot.starts == 1 && boot.serviceStarts == 1, "awake boot preserved");
                Context single = new Context();
                single.displays.values = new Display[] {new Display(0)};
                new BootReceiver().onReceive(single, new Intent());
                noLaunch(single, "single-screen boot stays primary-free");
                check(PrimaryDisplayFocusGuard.restorePrimaryTopFocus(direct),
                      "awake primary focus can still recover");
                check(direct.manager.tasks.get(0).moves == 1, "exactly one task move");
                break;
            }
            default: throw new AssertionError(args[0]);
        }
    }
}
"""


class PreviewWindowLifecycleTest(unittest.TestCase):
    def test_real_lifecycle_and_launch_decisions(self):
        activity = (SOURCE / "PreviewActivity.java").read_text()
        service = (SOURCE / "PreviewService.java").read_text()
        callbacks = "\n".join(member(activity, signature) for signature in (
            "protected void onStart()", "protected void onStop()",
            "protected void onPause()", "static boolean isVisible()"))
        activity_fixture = """
package com.thorium.preview;
public class PreviewActivity extends android.app.Activity {
    static boolean resumed = true;
    static final PreviewWindowState windowState = new PreviewWindowState();
    final boolean ownsVisibilityFlags;
    PreviewActivity(boolean valid) {
        ownsVisibilityFlags = valid;
        if (valid) windowState.created(this);
    }
""" + callbacks + "\n}"
        service_fixture = """
package com.thorium.preview;
import android.content.*;
import android.app.*;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;
public class PreviewService extends Context {
    static final String ACTION_BLANK = "blank", ACTION_UPDATE = "update";
    boolean previewActive = true, screensaverActive;
    final FakeHandler mainHandler = new FakeHandler();
    static class FakeHandler {
        int posts;
        void postDelayed(Runnable task, long millis) { posts++; }
    }
    void tick() { pegasusWatchdog.run(); }
    void request(Intent intent) { launchPlayerOnSecondary(intent); }
    void showLastPlayer() { launchPlayerOnSecondary(new Intent()); }
    void showScreensaverBlackout() { launchPlayerOnSecondary(new Intent(ACTION_BLANK)); }
""" + member(service, "private final Runnable pegasusWatchdog = new Runnable()") + ";\n" + member(
            service, "private void launchPlayerOnSecondary(Intent activity)") + "\n}"
        sources = dict(STUBS)
        sources["com/thorium/preview/PreviewActivity.java"] = activity_fixture
        sources["com/thorium/preview/PreviewService.java"] = service_fixture
        sources["com/thorium/preview/PreviewLifecycleHarness.java"] = HARNESS
        javac = str(JAVA / "javac") if JAVA.exists() else shutil.which("javac")
        java = str(JAVA / "java") if JAVA.exists() else shutil.which("java")
        self.assertIsNotNone(javac, "A JDK is required for executable regressions")
        self.assertIsNotNone(java)
        with tempfile.TemporaryDirectory(prefix="preview-window-lifecycle-") as temporary:
            directory = Path(temporary)
            paths = []
            for relative, contents in sources.items():
                path = directory / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)
                paths.append(str(path))
            paths.extend(str(SOURCE / name) for name in (
                "PreviewWindowState.java", "PrimaryDisplayFocusGuard.java", "BootReceiver.java"))
            compiled = subprocess.run(
                [javac, "--release", "8", "-d", str(directory), *paths],
                text=True, capture_output=True, timeout=30)
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            for scenario in ("focus-yield", "sleep", "owner", "unknown-power",
                             "late-sleep", "awake-paths"):
                with self.subTest(scenario=scenario):
                    result = subprocess.run(
                        [java, "-ea", "-cp", str(directory),
                         "com.thorium.preview.PreviewLifecycleHarness", scenario],
                        text=True, capture_output=True, timeout=10)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_lifecycle_ownership_and_heartbeat_wiring(self):
        activity = (SOURCE / "PreviewActivity.java").read_text()
        create = member(activity, "protected void onCreate(Bundle savedInstanceState)")
        self.assertLess(create.index("finishAndRemoveTask();"),
                        create.index("windowState.created(this);"))
        destroy = member(activity, "protected void onDestroy()")
        self.assertIn("windowState.destroyed(this);", destroy)
        self.assertLess(destroy.index("if (visibleInstance == this)"),
                        destroy.index("running = false;"))
        self.assertNotIn("windowState.stopped", member(activity, "protected void onPause()"))
        service = (SOURCE / "PreviewService.java").read_text()
        heartbeat = service.split('} else if ("/heartbeat".equals(path)) {', 1)[1].split(
            '} else if ("/hide".equals(path)) {', 1)[0]
        self.assertLess(heartbeat.index("!PrimaryDisplayFocusGuard.isInteractive(this)"),
                        heartbeat.index("if (previewActive)"))


if __name__ == "__main__":
    unittest.main()
