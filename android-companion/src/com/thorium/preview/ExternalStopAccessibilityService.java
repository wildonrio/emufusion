package com.thorium.preview;

import android.accessibilityservice.AccessibilityService;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Display;
import android.view.KeyEvent;
import android.view.accessibility.AccessibilityEvent;

/**
 * Observes the Thor Stop key while an explicitly launched standalone emulator
 * owns the foreground, then performs a bounded natural return.
 *
 * <p>This service is part of the EmuFusion APK and process identity; Android
 * nevertheless requires the owner to enable its accessibility capability once.
 * It never reads view text or traverses another app's UI.  Key filtering is
 * used only for a one-second Stop hold tied to the exact package/session that
 * {@link RomLaunchActivity} launched.</p>
 */
public final class ExternalStopAccessibilityService extends AccessibilityService {
    private static final String TAG = "EmuFusionExternalStop";
    private static final long STOP_HOLD_MS = 1000L;
    private static final long SECOND_BACK_DELAY_MS = 180L;
    private static final long RETURN_DELAY_MS = 420L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean stopPressed;
    private String armedToken = "";
    private String foregroundPackage = "";

    private final Runnable heldStop = () -> {
        if (!stopPressed || armedToken.isEmpty()) return;
        ExternalEmulationSession.Snapshot session =
                ExternalEmulationSession.snapshot(this);
        if (!session.active || !armedToken.equals(session.token) ||
                !session.packageName.equals(foregroundPackage)) {
            Log.w(TAG, "Held Stop ignored: foreground does not match tracked session");
            return;
        }
        final String token = session.token;
        ExternalEmulationSession.markNaturalReturnAttempt(this, token);
        // There is no portable Android API that proves a third-party emulator
        // saved or closed. Issue a bounded natural Back sequence only. Never
        // force-stop and never label this as a save/close success.
        boolean first = performGlobalAction(GLOBAL_ACTION_BACK);
        handler.postDelayed(() -> performGlobalAction(GLOBAL_ACTION_BACK),
                SECOND_BACK_DELAY_MS);
        handler.postDelayed(() -> {
            ExternalEmulationSession.Snapshot afterBack =
                    ExternalEmulationSession.snapshot(this);
            if (token.equals(afterBack.token) && !afterBack.active &&
                    afterBack.libraryForegroundProven &&
                    afterBack.externalClosedProven) {
                Log.i(TAG, "Natural external window return proven package=" +
                        session.packageName +
                        " saveProven=false externalClosedProven=true");
                return;
            }
            boolean requested = ExternalEmulationSession.returnToLibrary(this, token);
            Log.i(TAG, "Held Stop return requested package=" + session.packageName +
                    " firstBack=" + first + " libraryIntent=" + requested +
                    " saveProven=false externalClosedProven=false");
        }, RETURN_DELAY_MS);
    };

    @Override protected void onServiceConnected() {
        super.onServiceConnected();
        Log.i(TAG, "External Stop key filter enabled");
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null || event.getPackageName() == null) return;
        // PreviewActivity lives on the Thor's lower display. Treating that
        // resident EmuFusion window as display-0 foreground would immediately
        // retire every external session while Eden/Cemu was still playing.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
                event.getDisplayId() != Display.DEFAULT_DISPLAY) return;
        String observed = event.getPackageName().toString();
        ExternalEmulationSession.Snapshot session =
                ExternalEmulationSession.snapshot(this);
        if (!session.active || session.token.isEmpty()) return;
        if (session.packageName.equals(observed)) {
            foregroundPackage = observed;
            return;
        }
        if (getPackageName().equals(observed)) {
            // RomLaunchActivity may emit its own final display-0 event after
            // the target start has been requested. Ignore that trampoline race
            // until a held-Stop return is actually in progress.
            if (!session.returnRequested) return;
            foregroundPackage = observed;
            ExternalEmulationSession.markLibraryForeground(this, session.token);
            ExternalEmulationSession.Snapshot proof =
                    ExternalEmulationSession.snapshot(this);
            Log.i(TAG, "Existing EmuFusion task returned on display 0 token=" +
                    session.token + " naturalExternalClose=" +
                    proof.externalClosedProven);
            return;
        }
        // A transient volume/notification overlay must not steal the tracked
        // display-0 owner. Any other real app does disarm the session.
        if (!"com.android.systemui".equals(observed)) foregroundPackage = observed;
    }

    @Override public void onInterrupt() {
        cancelHold();
    }

    @Override protected boolean onKeyEvent(KeyEvent event) {
        if (event == null || !isStop(event.getKeyCode())) return false;
        ExternalEmulationSession.Snapshot session =
                ExternalEmulationSession.snapshot(this);
        if (!session.active || !session.packageName.equals(foregroundPackage)) return false;
        if (event.getAction() == KeyEvent.ACTION_DOWN && event.getRepeatCount() == 0) {
            stopPressed = true;
            armedToken = session.token;
            handler.removeCallbacks(heldStop);
            handler.postDelayed(heldStop, STOP_HOLD_MS);
        } else if (event.getAction() == KeyEvent.ACTION_UP) {
            cancelHold();
        }
        // Let short presses continue to the emulator. A hold is observed, not
        // stolen; this preserves games that use the same physical Select key.
        return false;
    }

    @Override public void onDestroy() {
        cancelHold();
        super.onDestroy();
    }

    private void cancelHold() {
        stopPressed = false;
        armedToken = "";
        handler.removeCallbacks(heldStop);
    }

    private static boolean isStop(int keyCode) {
        return keyCode == KeyEvent.KEYCODE_BUTTON_SELECT ||
                keyCode == KeyEvent.KEYCODE_MEDIA_STOP;
    }

}
