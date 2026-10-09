package com.thorium.preview;

import android.app.ActivityOptions;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;

import com.thorium.lucent.cheats.CheatPanelSnapshot;

/**
 * Puts the running game's cheat list on EmuFusion's physical lower display.
 *
 * <p>Deliberately shaped like {@link SecondaryGameplaySurfaceRouter}, which is
 * the only proven way to get a window onto display 4 on the Thor: the same
 * generation counter, the same overlay-permission fork between
 * {@code startActivity} and a {@link PendingIntent}, and the same rule that a
 * stale callback is dropped rather than acted on. Two different ways of
 * addressing one display would drift, and the failure mode of the wrong one is
 * a lower screen that is simply black with nothing in any log to say why.
 *
 * <p>Content flows one way and input flows the other. The game host on the
 * primary display owns the truth — which cheats exist and which the engine has
 * accepted — and publishes an immutable snapshot; the lower display draws it,
 * and reports back only that a row was touched. The lower-display window is
 * {@code FLAG_NOT_FOCUSABLE} and must stay that way, so it can never receive a
 * key event: the pad is read by the game host, which moves the selection and
 * publishes again.
 */
public final class SecondaryCheatPanelRouter {
    public static final String ACTION_SECONDARY_CHEATS =
            "com.thorium.preview.SECONDARY_CHEATS";
    static final String EXTRA_GENERATION = "secondary_cheats_generation";
    private static final String TAG = "LucentCheatPanel";

    /** The game host, which owns the cheats and the pad. */
    public interface Controller {
        /** A row on the lower display was touched. */
        void onSecondaryCheatToggled(int index);
        /** The panel was closed from the lower display rather than the pad. */
        void onSecondaryCheatPanelClosed();
    }

    /** The lower-display Activity, which only draws. */
    interface Panel {
        void showCheatPanel(CheatPanelSnapshot snapshot);
        void hideCheatPanel();
    }

    private static Controller controller;
    private static Panel panel;
    private static long generation;
    /**
     * The last published snapshot, kept because the Activity attaches some
     * frames after the launch. Without it the panel would come up empty and
     * stay empty until the user happened to move the selection.
     */
    private static CheatPanelSnapshot pending;

    private SecondaryCheatPanelRouter() {}

    /**
     * Whether a cheat panel could be shown below right now.
     *
     * <p>False while a DS/3DS/Wii U session is rendering its second screen
     * there: that Surface is the game, and replacing it with a menu would take
     * half the console away to show a list.
     */
    public static boolean available(Context context) {
        return context != null && BootReceiver.secondaryDisplayId(context) >= 0 &&
                !PreviewActivity.isGameplaySurfaceActive();
    }

    /**
     * Opens the panel on the lower display.
     *
     * @return false when there is no lower display to use, or it is busy being
     *         a game's second screen — the caller then falls back to its own
     *         in-window sheet rather than losing the feature
     */
    public static synchronized boolean request(
            Context context, Controller next, CheatPanelSnapshot snapshot) {
        if (context == null || next == null || !available(context)) {
            Log.i(TAG, "request rejected returned=false secondaryDisplayId=" +
                    (context == null ? -1 : BootReceiver.secondaryDisplayId(context)) +
                    " gameplaySurfaceActive=" + PreviewActivity.isGameplaySurfaceActive());
            return false;
        }
        controller = next;
        pending = snapshot;
        long requestedGeneration = ++generation;
        // Already on display 4 and already drawing: hand it the snapshot
        // directly. Re-launching would take the Activity through onNewIntent
        // for no reason and can flash the blanked preview underneath.
        if (panel != null) {
            panel.showCheatPanel(snapshot);
            Log.i(TAG, "request served by the attached panel generation=" +
                    requestedGeneration);
            return true;
        }
        Intent activity = new Intent(context, PreviewActivity.class)
                .setAction(ACTION_SECONDARY_CHEATS)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                        Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
                .putExtra(EXTRA_GENERATION, requestedGeneration);
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
                PendingIntent sent = PendingIntent.getActivity(
                        context, 43823, activity,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE,
                        options.toBundle());
                sent.send(context, 0, null, null, null, null, options.toBundle());
            }
            Log.i(TAG, "request launched the cheat panel generation=" +
                    requestedGeneration + " rows=" +
                    (snapshot == null ? -1 : snapshot.rows.size()));
            return true;
        } catch (PendingIntent.CanceledException | RuntimeException failure) {
            if (controller == next && generation == requestedGeneration) {
                controller = null;
                pending = null;
            }
            Log.e(TAG, "Unable to open the cheat panel on the lower display", failure);
            return false;
        }
    }

    /** Redraws the lower display after a selection move or a toggle. */
    public static synchronized void publish(
            Controller owner, CheatPanelSnapshot snapshot) {
        if (owner == null || controller != owner) return;
        pending = snapshot;
        if (panel != null) panel.showCheatPanel(snapshot);
    }

    /**
     * Takes the panel down and gives the lower display back to the preview.
     *
     * <p>Retiring the generation is what makes a late attach from an Activity
     * that was still starting up land on nothing instead of resurrecting a
     * panel the user has already closed.
     */
    public static synchronized void release(Context context, Controller owner) {
        if (owner == null || controller != owner) return;
        controller = null;
        pending = null;
        ++generation;
        if (panel != null) panel.hideCheatPanel();
        else if (context != null)
            context.sendBroadcast(new Intent(PreviewService.ACTION_BLANK)
                    .setPackage(context.getPackageName()));
    }

    /**
     * Registered by the lower-display Activity for as long as it is resumed,
     * so {@link #request} can hand it the panel in-process.
     *
     * <p>Without this the first open of a session had to start an Activity on
     * display 4, which moves that display to the top of Android's display
     * order. Since the panel is navigated with the pad — read by the game host
     * on display 0 and published back down here — losing top focus at exactly
     * that moment produced a panel that could not be moved through, and left
     * Android with a top-focused display holding no focusable window.
     */
    static synchronized void attachPanel(Panel next) {
        panel = next;
    }

    static synchronized void attach(long candidate, Panel next) {
        panel = next;
        if (generation != candidate || controller == null) {
            // The panel was closed while its Activity was still starting.
            next.hideCheatPanel();
            return;
        }
        if (pending != null) next.showCheatPanel(pending);
    }

    static synchronized void detach(Panel leaving) {
        if (panel == leaving) panel = null;
    }

    static synchronized void toggled(int index) {
        Controller current = controller;
        // CheatPanelView already translates its bounded page to this global
        // catalogue index at the moment of the touch.
        if (current != null) current.onSecondaryCheatToggled(index);
    }

    static synchronized void closedFromPanel() {
        Controller current = controller;
        if (current != null) current.onSecondaryCheatPanelClosed();
    }
}
