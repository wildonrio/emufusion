package com.thorium.preview;

import android.app.Activity;
import android.os.Build;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowManager;

/**
 * Gives the frontend the whole panel.
 *
 * <p>The Activity window is already the full 1920x1080, but Android insets the
 * content view by the system bars underneath it. Measured on the Thor that is
 * 55px at the bottom, so the theme was laid out into 1920x1025 and the last 55
 * rows stayed black -- a dead strip under every menu, and the bottom of a game
 * clipped away. Hiding the bars is not enough on its own: the inset survives
 * immersive mode, which is why {@code InWindowGameHost} works around it by
 * taking the decor view rather than the content view.
 *
 * <p>This removes the cause instead of working around it: the window stops
 * fitting its content to the bars, and the content view consumes the insets so
 * nothing downstream re-applies them.
 */
public final class FullDisplayWindow {

    private static final String TAG = "EmuFusionDisplay";

    private FullDisplayWindow() {}

    public static void apply(final Activity activity) {
        if (activity == null) return;
        applyOnce(activity);
        // Qt installs its own system-UI flags while it brings the window up and
        // wins any race with this, so the claim is re-asserted after it has
        // settled. Without the repeat the bar comes back and takes the 55px
        // with it. These are cheap, idempotent calls.
        final android.os.Handler handler =
                new android.os.Handler(android.os.Looper.getMainLooper());
        for (long delay : new long[]{400L, 1200L, 3000L, 8000L}) {
            handler.postDelayed(new Runnable() {
                @Override public void run() { applyOnce(activity); }
            }, delay);
        }
    }

    /**
     * Lets a landscape window run under a display cutout. By default Android
     * keeps it clear of the camera cutout, which on a phone such as a Pixel 6
     * held sideways left a 128px black band down one side of the library and of
     * every game. Devices without a cutout, such as the Thor, are unaffected.
     */
    public static void extendIntoCutout(Window window) {
        if (window == null || Build.VERSION.SDK_INT < 28) return;
        WindowManager.LayoutParams attributes = window.getAttributes();
        int shortEdges = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        if (attributes.layoutInDisplayCutoutMode == shortEdges) return;
        attributes.layoutInDisplayCutoutMode = shortEdges;
        window.setAttributes(attributes);
    }

    private static void applyOnce(Activity activity) {
        try {
            extendIntoCutout(activity.getWindow());
            // Hiding the bars is the part that actually frees the strip: the
            // window reserves space for the navigation bar even when the
            // content view is told not to fit system windows.
            View decor = activity.getWindow().getDecorView();
            decor.setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
            if (Build.VERSION.SDK_INT >= 30) {
                activity.getWindow().setDecorFitsSystemWindows(false);
            }
            View content = activity.findViewById(android.R.id.content);
            if (content == null) return;
            content.setPadding(0, 0, 0, 0);
            // Returning CONSUMED stops the framework re-inseting this view on
            // every configuration change, rotation and bar visibility flip;
            // clearing padding once is not durable on its own.
            content.setOnApplyWindowInsetsListener((view, insets) -> {
                view.setPadding(0, 0, 0, 0);
                return Build.VERSION.SDK_INT >= 30
                        ? WindowInsets.CONSUMED : insets.consumeSystemWindowInsets();
            });
            content.requestApplyInsets();
            if (content instanceof ViewGroup) {
                ((ViewGroup) content).setClipToPadding(false);
            }
        } catch (RuntimeException failure) {
            // A frontend that renders slightly short is far better than one
            // that will not start.
            Log.w(TAG, "Could not claim the full display", failure);
        }
    }
}
