package com.thorium.preview;

import android.app.ActivityOptions;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;
import android.view.Surface;

/** Routes one in-process emulator session to EmuFusion's physical lower display. */
public final class SecondaryGameplaySurfaceRouter {
    public static final String ACTION_SECONDARY_GAMEPLAY =
            "com.thorium.preview.SECONDARY_GAMEPLAY";
    static final String EXTRA_GENERATION = "secondary_gameplay_generation";
    static final String EXTRA_SYSTEM = "secondary_gameplay_system";
    private static final String TAG = "LucentSecondary";

    public interface Listener {
        void onSecondarySurfaceAvailable(Surface surface, int width, int height);
        void onSecondarySurfaceDestroyed();
        void onSecondarySurfaceError(Throwable failure);
        void onSecondaryTouch(float normalizedX, float normalizedY, boolean pressed);
    }

    /** The resumed lower-display Activity, when there is one to hand to. */
    public interface Host {
        void showSecondaryGameplaySurface(long generation);
    }

    private static Listener listener;
    private static Host host;
    private static long generation;
    private static String requestedSystem = "";

    private SecondaryGameplaySurfaceRouter() {}

    /** Registered by {@link PreviewActivity} for exactly as long as it is resumed. */
    public static synchronized void attachHost(Host candidate) {
        host = candidate;
        // Android can recreate the lower Activity while the emulator survives
        // sleep. Its last Intent may be a preview BLANK, not the original game
        // request. The live route, not that stale Intent, owns the replacement.
        if (candidate != null && listener != null)
            candidate.showSecondaryGameplaySurface(generation);
    }

    public static synchronized void detachHost(Host candidate) {
        if (host == candidate) host = null;
    }

    public static synchronized boolean request(
            Context context, String systemId, Listener next) {
        int secondaryDisplay = context == null ? -1 : BootReceiver.secondaryDisplayId(context);
        boolean overlays = context != null && Settings.canDrawOverlays(context);
        if (context == null || next == null || !supports(systemId) || secondaryDisplay < 0) {
            Log.i(TAG, "request rejected returned=false system=" + systemId +
                    " supports=" + supports(systemId) +
                    " secondaryDisplayId=" + secondaryDisplay +
                    " canDrawOverlays=" + overlays);
            return false;
        }
        Log.i(TAG, "request accepted system=" + systemId +
                " secondaryDisplayId=" + secondaryDisplay +
                " path=" + (overlays ? "startActivity(canDrawOverlays)" : "PendingIntent") +
                " (SDK=" + Build.VERSION.SDK_INT + ")");
        listener = next;
        requestedSystem = normalize(systemId);
        long requestedGeneration = ++generation;
        // The lower-display Activity is already up and resumed in this very
        // process for all but the first moments after boot, so hand it the
        // surface directly. Starting an Activity on display 4 instead would
        // move display 4 to the top of Android's display order, and because
        // that Activity is deliberately FLAG_NOT_FOCUSABLE the display would
        // then be top-focused with no focusable window in it -- every
        // controller press would be routed there, the game would see none of
        // them, and Android would ANR PreviewActivity five seconds later.
        // PrimaryDisplayFocusGuard repairs that state; not entering it mid-game
        // is better still.
        Host attached = host;
        if (attached != null) {
            Log.i(TAG, "request served by the resumed lower-display activity generation=" +
                    requestedGeneration + " system=" + systemId);
            attached.showSecondaryGameplaySurface(requestedGeneration);
            return true;
        }
        Intent activity = new Intent(context, PreviewActivity.class)
                .setAction(ACTION_SECONDARY_GAMEPLAY)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                        Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
                .putExtra(EXTRA_GENERATION, requestedGeneration)
                .putExtra(EXTRA_SYSTEM, systemId);
        ActivityOptions options = ActivityOptions.makeBasic();
        options.setLaunchDisplayId(BootReceiver.secondaryDisplayId(context));
        if (Build.VERSION.SDK_INT >= 34) {
            options.setPendingIntentCreatorBackgroundActivityStartMode(
                    ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED);
            options.setPendingIntentBackgroundActivityStartMode(
                    ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED);
        }
        try {
            if (Settings.canDrawOverlays(context)) {
                context.startActivity(activity, options.toBundle());
            } else {
                PendingIntent pending = PendingIntent.getActivity(
                        context, 43822, activity,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE,
                        options.toBundle());
                pending.send(context, 0, null, null, null, null, options.toBundle());
            }
            Log.i(TAG, "request launched secondary gameplay activity returned=true system=" +
                    systemId + " generation=" + requestedGeneration +
                    " displayId=" + secondaryDisplay);
            return true;
        } catch (PendingIntent.CanceledException | RuntimeException failure) {
            if (listener == next && generation == requestedGeneration) listener = null;
            Log.e(TAG, "Unable to open the secondary gameplay surface", failure);
            return false;
        }
    }

    public static synchronized void release(Context context, Listener owner) {
        if (owner == null || listener != owner) return;
        listener = null;
        requestedSystem = "";
        ++generation;
        if (context != null) context.sendBroadcast(new Intent(PreviewService.ACTION_BLANK)
                .setPackage(context.getPackageName()));
    }

    static synchronized boolean isCurrent(long candidate) {
        return listener != null && generation == candidate;
    }

    /** Azahar's SideScreen touch crop is portrait in its producer buffer. */
    static synchronized boolean isClockwiseQuarterTurn(long candidate) {
        return listener != null && generation == candidate &&
                ("3ds".equals(requestedSystem) || "n3ds".equals(requestedSystem));
    }

    static synchronized void surfaceAvailable(
            long candidate, Surface surface, int width, int height) {
        boolean matched = listener != null && generation == candidate;
        Log.i(TAG, "surfaceAvailable candidate=" + candidate + " generation=" + generation +
                " match=" + matched + " listener=" + (listener != null) +
                " valid=" + (surface != null && surface.isValid()) +
                " size=" + width + "x" + height);
        if (matched && surface != null && surface.isValid())
            listener.onSecondarySurfaceAvailable(surface, width, height);
    }

    /** An unresolved renderer owner must end loading, never deliver a null or
     * still-owned Surface as Direct. Do not call engine error UI under the
     * router monitor: its normal exit may release this route. */
    static void surfaceFailed(long candidate, Throwable failure) {
        final Listener target;
        synchronized (SecondaryGameplaySurfaceRouter.class) {
            target = generation == candidate ? listener : null;
        }
        if (target != null) target.onSecondarySurfaceError(failure);
    }

    /** Synchronous: returns only after the listener detached from the dying
     * Surface (bounded), so callers may remove the view right after. */
    static synchronized void surfaceDestroyed(long candidate) {
        boolean matched = listener != null && generation == candidate;
        Log.i(TAG, "surfaceDestroyed candidate=" + candidate + " generation=" + generation +
                " match=" + matched + " listener=" + (listener != null));
        if (matched)
            listener.onSecondarySurfaceDestroyed();
    }

    static synchronized void touch(
            long candidate, float normalizedX, float normalizedY, boolean pressed) {
        if (listener != null && generation == candidate) {
            // DS removes its image bars in the session. Preserve an outside
            // drag as release before clamping would turn it into an edge tap.
            // Other engines retain their existing coordinate contract.
            if (("nds".equals(requestedSystem) || "ds".equals(requestedSystem)) &&
                    (!Float.isFinite(normalizedX) || !Float.isFinite(normalizedY) ||
                     normalizedX < 0f || normalizedX >= 1f ||
                     normalizedY < 0f || normalizedY >= 1f)) pressed = false;
            listener.onSecondaryTouch(clamp(normalizedX), clamp(normalizedY), pressed);
        }
    }

    static boolean supports(String systemId) {
        String value = normalize(systemId);
        return "nds".equals(value) || "ds".equals(value) ||
                "3ds".equals(value) || "n3ds".equals(value) ||
                "wiiu".equals(value) || "wii-u".equals(value);
    }

    private static String normalize(String systemId) {
        return systemId == null ? "" : systemId.trim().toLowerCase();
    }

    private static float clamp(float value) {
        if (Float.isNaN(value)) return 0f;
        return Math.max(0f, Math.min(1f, value));
    }
}
