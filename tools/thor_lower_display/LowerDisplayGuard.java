import android.hardware.display.DisplayManager;
import android.net.LocalServerSocket;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;
import android.view.Display;
import android.view.DisplayEventReceiver;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Long-lived shell-uid daemon that undoes the Thor firmware's squeezed lower screen.
 *
 * The firmware SurfaceFlinger mirrors each upper-panel mode change onto the lower display,
 * leaving the upper mode in the lower DisplayDevice's "upcoming mode". If the lower panel
 * is SurfaceFlinger's active display when that change completes (it powered on first), the
 * display is recreated with the upper panel's 1080x1920 framebuffer on its 1080x1240 panel.
 * See tools/thor_lower_display_guard.py.
 *
 * Asleep until something changes: a display power-state change (DisplayManager) or a
 * display recreation (SurfaceFlinger's hotplug event). There is no polling; each event
 * costs a few dumpsys reads, and the framebuffer is repaired only if it is wrong. Touches
 * neither panel power nor brightness. A second copy exits with EXIT_ALREADY_RUNNING.
 */
public final class LowerDisplayGuard {
    static final String TAG = "EmuFusionLowerGuard";
    static final int EXIT_ALREADY_RUNNING = 3;
    private static final String SOCKET = "emufusion-lower-display-guard";
    private static final String LOG_PATH = "/data/local/tmp/emufusion-lower-display-guard.log";
    private static final long LOG_LIMIT_BYTES = 256 * 1024;
    /** SurfaceFlinger finishes a panel power change about 200 ms after DisplayManager reports it. */
    private static final long[] CHECK_DELAYS_MS = {50, 400, 1500};
    private static final long RETRY_DELAY_MS = 2000;
    private static final int MAX_RETRIES = 5;
    private static final int FIRMWARE_LOG_LINES = 40;
    private static final long EVENT_FLAG_ADDED_REMOVED_CHANGED = 1 | 2 | 4;

    // Strong references for the life of the process.
    private static LocalServerSocket instanceLock;
    private static HotplugWatcher hotplugWatcher;
    private static DisplayManager.DisplayListener displayListener;
    private static IBinder.DeathRecipient deathRecipient;

    private static Handler worker;
    private static volatile int retries;
    private static boolean loggedAsleepMismatch;
    private static final Map<Integer, Integer> displayStates = new HashMap<>();

    public static void main(String[] args) throws Exception {
        Looper.prepareMainLooper();
        try {
            instanceLock = new LocalServerSocket(SOCKET);
        } catch (IOException running) {
            System.exit(EXIT_ALREADY_RUNNING);
        }
        HandlerThread thread = new HandlerThread("lower-guard");
        thread.start();
        worker = new Handler(thread.getLooper());
        exitWhenServicesDie();
        Handler main = new Handler(Looper.getMainLooper());
        registerDisplayListener(main);
        try {
            hotplugWatcher = new HotplugWatcher(Looper.getMainLooper());
        } catch (Throwable unavailable) {
            log("hotplug events unavailable, display power events only: " + unavailable);
        }
        log("started pid " + android.os.Process.myPid());
        trigger("start");
        Looper.loop();
    }

    /** Fired for every display recreation, including the bad one. */
    private static final class HotplugWatcher extends DisplayEventReceiver {
        HotplugWatcher(Looper looper) {
            super(looper);
        }

        @Override
        public void onHotplug(long timestampNanos, long physicalDisplayId, boolean connected) {
            trigger("hotplug " + Long.toUnsignedString(physicalDisplayId));
        }
    }

    private static void registerDisplayListener(Handler handler) throws Exception {
        displayListener = new DisplayManager.DisplayListener() {
            @Override
            public void onDisplayAdded(int displayId) {
                trigger("display added " + displayId);
            }

            @Override
            public void onDisplayRemoved(int displayId) {
                displayStates.remove(displayId);
            }

            @Override
            public void onDisplayChanged(int displayId) {
                // Not for mode changes: games change the refresh rate, and a dump can cost a frame.
                int state = displayState(displayId);
                Integer previous = displayStates.put(displayId, state);
                if (previous == null || previous != state) {
                    trigger("display " + displayId + " state " + state);
                }
            }
        };
        Class<?> global = Class.forName("android.hardware.display.DisplayManagerGlobal");
        Object manager = global.getMethod("getInstance").invoke(null);
        for (Method method : global.getMethods()) {
            if (!method.getName().equals("registerDisplayListener")) continue;
            if (method.getParameterCount() == 3) {
                method.invoke(manager, displayListener, handler, EVENT_FLAG_ADDED_REMOVED_CHANGED);
                return;
            }
            if (method.getParameterCount() == 2) {
                method.invoke(manager, displayListener, handler);
                return;
            }
        }
        throw new NoSuchMethodException("registerDisplayListener");
    }

    private static int displayState(int displayId) {
        try {
            Class<?> global = Class.forName("android.hardware.display.DisplayManagerGlobal");
            Object manager = global.getMethod("getInstance").invoke(null);
            Display display = (Display) global.getMethod("getRealDisplay", int.class)
                    .invoke(manager, displayId);
            return display == null ? Display.STATE_UNKNOWN : display.getState();
        } catch (ReflectiveOperationException e) {
            return Display.STATE_UNKNOWN;
        }
    }

    /** The supervising script restarts this process when SurfaceFlinger or system_server die. */
    private static void exitWhenServicesDie() throws Exception {
        deathRecipient = () -> {
            log("display services died, restarting");
            System.exit(1);
        };
        Method getService = Class.forName("android.os.ServiceManager")
                .getMethod("getService", String.class);
        for (String name : new String[] {"SurfaceFlinger", "display"}) {
            IBinder service = (IBinder) getService.invoke(null, name);
            if (service == null) throw new IllegalStateException("no service " + name);
            service.linkToDeath(deathRecipient, 0);
        }
    }

    private static void trigger(String reason) {
        Log.d(TAG, "event: " + reason);
        worker.removeCallbacksAndMessages(null);
        retries = 0;
        for (long delay : CHECK_DELAYS_MS) {
            worker.postDelayed(() -> check(reason), delay);
        }
    }

    private static void check(String reason) {
        LowerDisplayState lower = LowerDisplayState.parse(
                capture("dumpsys", "SurfaceFlinger", "--displays") + "\n"
                        + capture("dumpsys", "SurfaceFlinger", "--comp-displays"));
        if (lower == null) {
            log("no secondary internal display in dumpsys");
            return;
        }
        List<String> problems = lower.problems();
        if (problems.isEmpty()) {
            loggedAsleepMismatch = false;
            return;
        }
        if (lower.asleep()) {
            // Nothing can be composed. The next wake is a display state event.
            if (!loggedAsleepMismatch) {
                log("mismatch while the panel is off, waiting for wake (" + reason + "): " + lower);
                logFirmwareLines();
            }
            loggedAsleepMismatch = true;
            return;
        }
        log("mismatch (" + reason + "): " + problems + "; " + lower);
        if (!loggedAsleepMismatch) logFirmwareLines();
        loggedAsleepMismatch = false;
        repair(lower);
        LowerDisplayState after = LowerDisplayState.parse(
                capture("dumpsys", "SurfaceFlinger", "--displays") + "\n"
                        + capture("dumpsys", "SurfaceFlinger", "--comp-displays"));
        if (after != null && after.problems().isEmpty()) {
            log("repaired: " + after);
            return;
        }
        log("still mismatched: " + after);
        if (retries++ < MAX_RETRIES) worker.postDelayed(() -> check("retry"), RETRY_DELAY_MS);
    }

    /** One row short and back: SurfaceFlinger resizes only on a changed size. */
    private static void repair(LowerDisplayState lower) {
        try {
            String[] size = lower.mode.split("x");
            int width = Integer.parseInt(size[0]);
            int height = Integer.parseInt(size[1]);
            long id = Long.parseUnsignedLong(lower.id);
            int stack = lower.layerStack.intValue();
            SfLowerDisplay.setSize(id, width, height - 1);
            SfLowerDisplay.clientFrame(stack, 200);
            SfLowerDisplay.setSize(id, width, height);
            SfLowerDisplay.clientFrame(stack, 600);
        } catch (Exception failed) {
            log("repair failed: " + failed);
        }
    }

    /** What the firmware did just before, so the next natural occurrence documents its trigger. */
    private static void logFirmwareLines() {
        String[] lines = capture("logcat", "-d", "-v", "time",
                "-s", "SurfaceFlinger:I", "DisplayDevice:E").split("\n");
        int from = Math.max(0, lines.length - FIRMWARE_LOG_LINES);
        log("firmware log:\n" + String.join("\n",
                java.util.Arrays.copyOfRange(lines, from, lines.length)));
    }

    private static String capture(String... command) {
        Process process = null;
        try {
            process = new ProcessBuilder(command).redirectErrorStream(true).start();
            process.getOutputStream().close();
            InputStream in = process.getInputStream();
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] chunk = new byte[16384];
            for (int n; (n = in.read(chunk)) > 0; ) out.write(chunk, 0, n);
            process.waitFor();
            return out.toString("UTF-8");
        } catch (IOException | InterruptedException failed) {
            log("cannot run " + command[0] + ": " + failed);
            return "";
        } finally {
            if (process != null) process.destroy();
        }
    }

    private static synchronized void log(String message) {
        Log.i(TAG, message);
        try {
            File file = new File(LOG_PATH);
            if (file.length() > LOG_LIMIT_BYTES) file.renameTo(new File(LOG_PATH + ".1"));
            try (FileWriter writer = new FileWriter(file, true)) {
                writer.write(new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US).format(new Date())
                        + " " + message + "\n");
            }
        } catch (IOException ignored) {
            // logcat has the line.
        }
    }
}
