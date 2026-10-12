package com.thorium.preview;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.provider.Settings;
import android.util.Log;

/**
 * "Restart app?" after an update (owner, 2026-10-10). Android kills the old
 * process when it replaces the package and then leaves the user on the
 * installer's "App installed" screen; this offers to open the new version.
 *
 * <p>Started from {@link BootReceiver} on {@code MY_PACKAGE_REPLACED}. A
 * background activity start is allowed when EmuFusion holds the
 * display-over-other-apps permission (the Thor always does); otherwise a
 * tap-to-restart notification is posted instead.
 */
public final class UpdateCompleteActivity extends Activity {
    private static final String TAG = "EmuFusionUpdater";
    private static final String CHANNEL = "updates";
    private static final int NOTIFICATION_ID = 43822;

    /** Offers the restart; never throws into the broadcast receiver. */
    static void announce(Context context) {
        try {
            if (Settings.canDrawOverlays(context)) {
                context.startActivity(new Intent(context, UpdateCompleteActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                                Intent.FLAG_ACTIVITY_CLEAR_TASK));
                return;
            }
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            if (manager == null) return;
            manager.createNotificationChannel(new NotificationChannel(
                    CHANNEL, "App updates", NotificationManager.IMPORTANCE_HIGH));
            PendingIntent restart = PendingIntent.getActivity(context, 0,
                    frontendIntent(context),
                    PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            manager.notify(NOTIFICATION_ID, new Notification.Builder(context, CHANNEL)
                    .setSmallIcon(android.R.drawable.stat_sys_download_done)
                    .setContentTitle(updatedTitle(context))
                    .setContentText("Restart app? Tap to restart EmuFusion")
                    .setContentIntent(restart)
                    .addAction(new Notification.Action.Builder(null, "Restart", restart).build())
                    .setCategory(Notification.CATEGORY_STATUS)
                    .setAutoCancel(true)
                    .build());
        } catch (RuntimeException failure) {
            Log.w(TAG, "Could not offer a restart after the update", failure);
        }
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        new AlertDialog.Builder(this, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                .setTitle(updatedTitle(this))
                .setMessage("Restart app?")
                .setPositiveButton("Restart", (dialog, which) -> {
                    startActivity(frontendIntent(this));
                    finish();
                })
                .setNegativeButton("Later", (dialog, which) -> finish())
                .setOnCancelListener(dialog -> finish())
                .show();
    }

    private static String updatedTitle(Context context) {
        String version = "";
        try {
            version = context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0).versionName;
        } catch (Exception ignored) {
        }
        return version == null || version.isEmpty() ? "EmuFusion updated" :
                "EmuFusion updated to " + version;
    }

    private static Intent frontendIntent(Context context) {
        return new Intent(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_LAUNCHER)
                .setClassName(context, "org.pegasus_frontend.android.MainActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
    }
}
