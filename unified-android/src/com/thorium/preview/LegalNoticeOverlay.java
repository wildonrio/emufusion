package com.thorium.preview;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.thorium.lucent.legal.LegalNotice;

/**
 * The first-launch legal notice.
 *
 * <p>It is drawn in Java, over Qt's surface, for the same reason
 * {@link BootVideoOverlay} is: it has to be able to appear before, and
 * independently of, whatever the theme is doing. A notice that only exists once
 * the QML theme has loaded would be skippable by any path that fails to reach
 * the theme.
 *
 * <p>Two rules the user asked for specifically, both enforced here rather than
 * left to the layout:
 * <ul>
 *   <li>Confirm cannot be pressed until the body has been scrolled to its end,
 *       so the notice cannot be dismissed unread.</li>
 *   <li>"Don't show this again" starts CHECKED. Confirming with it checked is
 *       what suppresses future launches; unchecking it is a deliberate request
 *       to see the notice again.</li>
 * </ul>
 */
public final class LegalNoticeOverlay {

    private static final String TAG = "EmuFusionLegal";
    private static final String PREFS = "lucent-legal";
    private static final String KEY_ACKNOWLEDGED = "acknowledgedWithSuppression";

    /**
     * Shown once the frontend reports itself ready, so it lands on a drawn
     * library rather than over a boot video. The short delay lets
     * {@link BootVideoOverlay}'s fade finish first.
     */
    private static final long AFTER_READY_MS = 500L;
    /**
     * If the ready signal never arrives the notice must still appear -- it is
     * a first-launch obligation, not a nicety. Sits beyond BootVideoOverlay's
     * own 20s failsafe so the two never overlap.
     */
    private static final long FAILSAFE_MS = 24_000L;

    private static final Handler HANDLER = new Handler(Looper.getMainLooper());

    private static Activity host;
    private static FrameLayout overlay;
    private static BroadcastReceiver readyReceiver;
    private static Runnable showTask;
    private static Runnable failsafeTask;
    private static boolean shown;

    private LegalNoticeOverlay() {}

    /** Called from MainActivity.onStart, alongside the boot overlay. */
    public static synchronized void begin(Activity activity) {
        if (activity == null || host != null || shown) return;
        if (!LegalNotice.shouldShow(acknowledged(activity))) return;
        host = activity;

        readyReceiver = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                scheduleShow(AFTER_READY_MS);
            }
        };
        try {
            // Not exported: only this app's own PreviewService sends it.
            activity.registerReceiver(readyReceiver,
                    new IntentFilter(BootVideoOverlay.ACTION_FRONTEND_READY),
                    Context.RECEIVER_NOT_EXPORTED);
        } catch (RuntimeException unsupported) {
            try {
                activity.registerReceiver(readyReceiver,
                        new IntentFilter(BootVideoOverlay.ACTION_FRONTEND_READY));
            } catch (RuntimeException ignored) {
                // The failsafe below still gets it on screen.
            }
        }
        failsafeTask = new Runnable() {
            @Override public void run() { scheduleShow(0L); }
        };
        HANDLER.postDelayed(failsafeTask, FAILSAFE_MS);
    }

    private static synchronized void scheduleShow(long delay) {
        if (shown || host == null) return;
        if (showTask != null) return;
        showTask = new Runnable() {
            @Override public void run() { show(); }
        };
        HANDLER.postDelayed(showTask, delay);
    }

    private static boolean acknowledged(Context context) {
        try {
            return prefs(context).getBoolean(KEY_ACKNOWLEDGED, false);
        } catch (RuntimeException unavailable) {
            // Fail towards showing it: a notice shown twice is a nuisance, a
            // notice never shown is the thing it exists to prevent.
            return false;
        }
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static synchronized void show() {
        showTask = null;
        if (shown || host == null) return;
        View decor = host.getWindow().getDecorView();
        if (!(decor instanceof ViewGroup)) return;
        shown = true;

        final Activity activity = host;
        final float density = activity.getResources().getDisplayMetrics().density;

        FrameLayout scrim = new FrameLayout(activity);
        // Nearly opaque rather than fully: the library stays faintly visible
        // behind, which reads as a dialog over the app instead of a new screen.
        scrim.setBackgroundColor(Color.parseColor("#f2070910"));
        scrim.setClickable(true);
        scrim.setFocusable(true);

        LinearLayout card = new LinearLayout(activity);
        card.setOrientation(LinearLayout.VERTICAL);
        int pad = Math.round(34 * density);
        card.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(activity);
        title.setText(LegalNotice.TITLE);
        title.setTextColor(Color.parseColor("#f2f5fa"));
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        card.addView(title);

        final ScrollView scroller = new ScrollView(activity);
        scroller.setFocusable(true);
        // The pad drives this UI, so the scroll view itself has to take focus
        // and respond to up/down; without this the text cannot be read at all
        // on a controller, and Confirm could never unlock.
        scroller.setFocusableInTouchMode(true);
        final TextView body = new TextView(activity);
        body.setText(LegalNotice.body());
        body.setTextColor(Color.parseColor("#c2cad8"));
        body.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        body.setLineSpacing(Math.round(5 * density), 1f);
        int bodyPad = Math.round(14 * density);
        body.setPadding(0, bodyPad, 0, bodyPad);
        scroller.addView(body);
        LinearLayout.LayoutParams scrollParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        card.addView(scroller, scrollParams);

        final CheckBox suppress = new CheckBox(activity);
        suppress.setText(LegalNotice.SUPPRESS_LABEL);
        suppress.setTextColor(Color.parseColor("#c2cad8"));
        suppress.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        // Checked by default, as asked: the common case is acknowledging once.
        suppress.setChecked(true);
        card.addView(suppress);

        final Button confirm = new Button(activity);
        confirm.setText(LegalNotice.CONFIRM_LABEL);
        confirm.setEnabled(false);
        confirm.setAlpha(0.4f);
        LinearLayout.LayoutParams confirmParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        confirmParams.gravity = Gravity.END;
        confirmParams.topMargin = Math.round(10 * density);
        card.addView(confirm, confirmParams);

        final Runnable refresh = new Runnable() {
            @Override public void run() {
                View child = scroller.getChildCount() > 0
                        ? scroller.getChildAt(0) : null;
                int content = child == null ? 0 : child.getHeight();
                boolean unlocked = LegalNotice.canConfirm(
                        scroller.getScrollY(), scroller.getHeight(), content);
                if (unlocked == confirm.isEnabled()) return;
                confirm.setEnabled(unlocked);
                confirm.setAlpha(unlocked ? 1f : 0.4f);
                if (unlocked) confirm.requestFocus();
            }
        };
        scroller.getViewTreeObserver().addOnScrollChangedListener(
                new android.view.ViewTreeObserver.OnScrollChangedListener() {
                    @Override public void onScrollChanged() { refresh.run(); }
                });
        // Also evaluate once laid out, for the case where the notice already
        // fits without scrolling.
        scroller.post(refresh);

        confirm.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                if (suppress.isChecked()) {
                    try {
                        prefs(activity).edit()
                                .putBoolean(KEY_ACKNOWLEDGED, true).apply();
                    } catch (RuntimeException failure) {
                        Log.w(TAG, "Could not persist acknowledgement", failure);
                    }
                }
                dismiss();
            }
        });

        FrameLayout.LayoutParams cardParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT);
        int inset = Math.round(90 * density);
        int vertical = Math.round(46 * density);
        cardParams.setMargins(inset, vertical, inset, vertical);
        scrim.addView(card, cardParams);

        ((ViewGroup) decor).addView(scrim, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        scrim.bringToFront();
        scroller.requestFocus();
        overlay = scrim;
    }

    private static synchronized void dismiss() {
        if (host != null && readyReceiver != null) {
            try { host.unregisterReceiver(readyReceiver); } catch (RuntimeException ignored) {}
        }
        readyReceiver = null;
        if (failsafeTask != null) { HANDLER.removeCallbacks(failsafeTask); failsafeTask = null; }
        final FrameLayout showing = overlay;
        overlay = null;
        host = null;
        if (showing == null) return;
        ViewGroup parent = (ViewGroup) showing.getParent();
        if (parent != null) parent.removeView(showing);
    }
}
