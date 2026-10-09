package com.thorium.preview;

import android.app.ActivityManager;
import android.content.ComponentName;
import android.content.Context;
import android.os.PowerManager;
import android.util.Log;

import java.util.List;

/**
 * Keeps display 0 the top-focused display on the Thor.
 *
 * <p>Android picks the top-focused display in {@code
 * RootWindowContainer.updateFocusedWindowLocked} by walking the displays from
 * the top of the display order down and taking the first one that has either a
 * focused window <em>or</em> a focused app. EmuFusion's lower display always
 * satisfies the second half of that test and never the first: {@link
 * PreviewActivity} is a permanent resident of display 4, so that display always
 * has an {@code mFocusedApp}, and its window carries {@code
 * FLAG_NOT_FOCUSABLE}, so {@code mCurrentFocus} there is always null.
 *
 * <p>The flag is deliberate and must stay — a focusable lower window would let
 * every GamePad touch pull focus off the game through {@code
 * pointerDownOutsideFocusLocked}. What it cannot do is stop the display itself
 * being chosen. Whenever anything starts an Activity on display 4 — the initial
 * preview, the dual-screen gameplay surface, the cheat panel, the service
 * watchdog — that start also moves display 4 to the top of the display order,
 * and display 4 then claims top focus with no window to give it to. The
 * controller reports no display of its own, so its key events are routed to the
 * top-focused display, find nothing focusable there, and after five seconds
 * Android files "Input dispatching timed out (Application does not have a
 * focused window)" against PreviewActivity while the running game never sees
 * the press.
 *
 * <p>Moving a task to the front is the only lever an app has on the display
 * order: {@code Task.moveToFront} positions the task at the top of its display
 * area <em>including parents</em>, which walks up to {@code RootWindowContainer}
 * and re-tops the display. So handing display 0's task back to the front puts
 * display 0 back above display 4 and top focus returns to the window the game
 * actually renders into. This is the same recovery a user performs by hand when
 * they tap the upper screen.
 *
 * <p>{@link ActivityManager.AppTask#moveToFront()} is used rather than a
 * {@code startActivity} with {@code FLAG_ACTIVITY_REORDER_TO_FRONT} because it
 * delivers no Intent. The frontend Activity's {@code onNewIntent} hook calls
 * {@code setIntent}, and while a game is running that retained Intent is the
 * {@code LAUNCH_INTERNAL_GAME} one that restores the session if Android
 * recreates the process. Re-topping display 0 must not cost the player that.
 */
public final class PrimaryDisplayFocusGuard {
    /** The frontend Activity, which owns display 0 and hosts every game. */
    static final String PRIMARY_ACTIVITY = "org.pegasus_frontend.android.MainActivity";
    private static final String TAG = "LucentFocusGuard";

    private PrimaryDisplayFocusGuard() {}

    /** Unknown power state is not permission to launch or reorder a window. */
    static boolean isInteractive(Context context) {
        if (context == null) return false;
        try {
            PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
            return power != null && power.isInteractive();
        } catch (RuntimeException failure) {
            return false;
        }
    }

    /**
     * Hands the top-focused display back to display 0.
     *
     * @return true when a primary-display task was found and moved
     */
    public static boolean restorePrimaryTopFocus(Context context) {
        if (!isInteractive(context)) return false;
        ActivityManager manager;
        List<ActivityManager.AppTask> tasks;
        try {
            manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            if (manager == null) return false;
            tasks = manager.getAppTasks();
        } catch (RuntimeException failure) {
            Log.e(TAG, "Unable to enumerate EmuFusion's tasks", failure);
            return false;
        }
        if (tasks == null || tasks.isEmpty()) {
            Log.w(TAG, "No EmuFusion task to hand top focus back to");
            return false;
        }
        for (ActivityManager.AppTask task : tasks) {
            if (!isPrimaryTask(task)) continue;
            try {
                // Task enumeration can span a screen-off transition. The
                // delayed retry must also fail closed at the actual reorder.
                if (!isInteractive(context)) return false;
                task.moveToFront();
                Log.i(TAG, "Restored top focus to the primary display");
                return true;
            } catch (RuntimeException failure) {
                Log.e(TAG, "Unable to move the primary-display task to front", failure);
                return false;
            }
        }
        // Reachable before the frontend has been created (a boot-time preview
        // launch) and after the user has left it. Neither is a state where the
        // lower display can steal input from a game, so it is not an error.
        Log.i(TAG, "No primary-display task is present; leaving the display order alone");
        return false;
    }

    private static boolean isPrimaryTask(ActivityManager.AppTask task) {
        if (task == null) return false;
        ActivityManager.RecentTaskInfo info;
        try {
            info = task.getTaskInfo();
        } catch (RuntimeException failure) {
            return false;
        }
        if (info == null) return false;
        return isPrimaryActivity(info.topActivity) ||
                isPrimaryActivity(info.baseActivity) ||
                isPrimaryActivity(info.origActivity);
    }

    private static boolean isPrimaryActivity(ComponentName component) {
        return component != null && PRIMARY_ACTIVITY.equals(component.getClassName());
    }
}
