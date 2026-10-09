package com.thorium.preview;

import android.app.ActivityOptions;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.hardware.display.DisplayManager;
import android.view.Display;

public final class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        Intent service = new Intent(context, PreviewService.class);
        context.startForegroundService(service);

        // Boot delivery bypasses PreviewService's launch gateway. Keep its
        // background work alive, but never open a window while the panels sleep.
        if (!PrimaryDisplayFocusGuard.isInteractive(context)) return;
        Intent activity = new Intent(context, PreviewActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        ActivityOptions options = ActivityOptions.makeBasic();
        int displayId = secondaryDisplayId(context);
        // A single-screen device renders its preview inside Pegasus as an
        // upper-right PIP. Never let the boot receiver open this native
        // secondary-display activity on the primary panel.
        if (displayId < 0) return;
        options.setLaunchDisplayId(displayId);
        try {
            if (!PrimaryDisplayFocusGuard.isInteractive(context)) return;
            context.startActivity(activity, options.toBundle());
        } catch (RuntimeException ignored) {
            // ADB or the next Pegasus selection will restore the activity if
            // this Android build blocks a boot-time background launch.
        }
    }

    static int secondaryDisplayId(Context context) {
        DisplayManager manager = (DisplayManager) context.getSystemService(Context.DISPLAY_SERVICE);
        for (Display display : manager.getDisplays()) {
            if (display.getDisplayId() != Display.DEFAULT_DISPLAY) return display.getDisplayId();
        }
        return -1;
    }
}
