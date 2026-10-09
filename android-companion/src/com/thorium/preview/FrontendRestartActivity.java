package com.thorium.preview;

import android.app.Activity;
import android.app.ActivityManager;
import android.content.ComponentName;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.ViewTreeObserver;
import android.view.Window;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;

/**
 * Foreground bridge that restarts the process-lifetime Qt frontend safely.
 *
 * <p>This Activity deliberately runs in {@code :frontend_restart}. Qt 5 cannot
 * initialize a second MainActivity in its existing process, while Android 13
 * rejects an AlarmManager/PendingIntent relaunch after that process dies as a
 * background activity start. Starting this bridge from the focused MainActivity
 * gives the platform one continuous, visible Activity transition.
 */
public final class FrontendRestartActivity extends Activity {
    public static final String EXTRA_OLD_PROCESS_PID =
            "com.thorium.preview.extra.OLD_PROCESS_PID";
    private static final String EXTRA_NEXT_LAUNCH =
            "com.thorium.preview.extra.NEXT_LAUNCH";

    /** Builds the only supported handoff into the black restart bridge. */
    public static Intent createIntent(Activity owner) {
        if (owner == null) throw new IllegalArgumentException("owner required");
        return new Intent(owner, FrontendRestartActivity.class)
                .putExtra(EXTRA_OLD_PROCESS_PID, android.os.Process.myPid())
                .addFlags(Intent.FLAG_ACTIVITY_NO_ANIMATION);
    }

    /** Carry an already normalized in-app game switch across the process boundary. */
    public static Intent createIntent(Activity owner, Intent nextLaunch) {
        Intent restart = createIntent(owner);
        if (nextLaunch != null)
            restart.putExtra(EXTRA_NEXT_LAUNCH, new Intent(nextLaunch));
        return restart;
    }
    private static final String TAG = "LucentImport";
    private static final long OLD_PROCESS_EXIT_TIMEOUT_MS = 3000L;
    private static final int MAX_LAUNCH_ATTEMPTS = 3;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private boolean resumed;
    private boolean focused;
    private boolean firstFrameDrawn;
    private boolean restartBegun;
    private boolean relaunchStarted;
    private int oldPid = -1;
    private long exitDeadline;
    private int launchAttempts;
    private ViewTreeObserver.OnDrawListener firstDrawListener;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        setContentView(root);

        oldPid = getIntent().getIntExtra(EXTRA_OLD_PROCESS_PID, -1);
        if (oldPid <= 0 || oldPid == android.os.Process.myPid()) {
            showFatal("EmuFusion couldn't validate the old frontend process.");
            return;
        }

        firstDrawListener = () -> {
            if (firstFrameDrawn) return;
            firstFrameDrawn = true;
            handler.post(() -> {
                if (root != null && root.getViewTreeObserver().isAlive())
                    root.getViewTreeObserver().removeOnDrawListener(firstDrawListener);
                maybeBeginRestart();
            });
        };
        root.getViewTreeObserver().addOnDrawListener(firstDrawListener);
    }

    @Override protected void onResume() {
        super.onResume();
        resumed = true;
        maybeBeginRestart();
    }

    @Override protected void onPause() {
        resumed = false;
        super.onPause();
    }

    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        focused = hasFocus;
        if (hasFocus) maybeBeginRestart();
    }

    private void maybeBeginRestart() {
        if (restartBegun || !resumed || !focused || !firstFrameDrawn) return;
        String oldProcessName = processNameForPid(oldPid);
        if (!getPackageName().equals(oldProcessName)) {
            showFatal("EmuFusion couldn't identify the old frontend process.");
            return;
        }
        restartBegun = true;
        exitDeadline = SystemClock.elapsedRealtime() + OLD_PROCESS_EXIT_TIMEOUT_MS;
        Log.i(TAG, "Frontend restart bridge ready oldPid=" + oldPid +
                " bridgePid=" + android.os.Process.myPid() +
                " resumed=true focused=true firstFrameDrawn=true");
        android.os.Process.killProcess(oldPid);
        handler.post(this::waitForOldProcessExit);
    }

    private void waitForOldProcessExit() {
        String name = processNameForPid(oldPid);
        if (name == null) {
            Log.i(TAG, "Frontend restart observed old process exit oldPid=" + oldPid);
            launchFreshFrontend();
            return;
        }
        if (!getPackageName().equals(name)) {
            showFatal("EmuFusion detected a stale frontend process identity.");
            return;
        }
        if (SystemClock.elapsedRealtime() >= exitDeadline) {
            showFatal("EmuFusion's old frontend did not close in time.");
            return;
        }
        handler.postDelayed(this::waitForOldProcessExit, 50L);
    }

    private String processNameForPid(int pid) {
        ActivityManager manager = (ActivityManager)getSystemService(ACTIVITY_SERVICE);
        if (manager == null) return null;
        java.util.List<ActivityManager.RunningAppProcessInfo> processes =
                manager.getRunningAppProcesses();
        if (processes == null) return null;
        for (ActivityManager.RunningAppProcessInfo process : processes) {
            if (process != null && process.pid == pid) return process.processName;
        }
        return null;
    }

    private void launchFreshFrontend() {
        if (relaunchStarted || isFinishing() || isDestroyed()) return;
        relaunchStarted = true;
        launchAttempts++;
        Intent next = getIntent().getParcelableExtra(EXTRA_NEXT_LAUNCH);
        Intent frontend = freshFrontendIntent(getPackageName(), next);
        try {
            Log.i(TAG, "Frontend restart bridge launching fresh Qt process attempt=" +
                    launchAttempts);
            startActivity(frontend);
        } catch (RuntimeException failure) {
            relaunchStarted = false;
            Log.e(TAG, "Frontend restart bridge launch attempt failed", failure);
            if (launchAttempts < MAX_LAUNCH_ATTEMPTS) {
                handler.postDelayed(this::launchFreshFrontend, 250L);
            } else {
                showFatal("EmuFusion couldn't reopen after updating the library.");
            }
        }
    }

    private static Intent freshFrontendIntent(String packageName, Intent next) {
        Intent frontend = next == null
                ? new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
                : new Intent(next);
        return frontend.setComponent(new ComponentName(packageName,
                        "org.pegasus_frontend.android.MainActivity"))
                .setFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                        Intent.FLAG_ACTIVITY_CLEAR_TASK |
                        Intent.FLAG_ACTIVITY_NO_ANIMATION);
    }

    private void showFatal(String message) {
        restartBegun = true;
        handler.removeCallbacksAndMessages(null);
        Log.e(TAG, "Frontend restart stopped: " + message);
        if (root == null) return;
        root.removeAllViews();
        TextView error = new TextView(this);
        error.setText(message + "\nPlease reopen EmuFusion.");
        error.setTextColor(Color.WHITE);
        error.setTextSize(20f);
        error.setGravity(Gravity.CENTER);
        root.addView(error, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
    }

    @Override protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (root != null && firstDrawListener != null &&
                root.getViewTreeObserver().isAlive())
            root.getViewTreeObserver().removeOnDrawListener(firstDrawListener);
        super.onDestroy();
    }
}
