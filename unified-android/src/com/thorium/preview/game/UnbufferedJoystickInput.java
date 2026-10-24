package com.thorium.preview.game;

import android.os.Build;
import android.util.Log;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewTreeObserver;

import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Locale;

/**
 * Hands stick and touch motion to a game as it arrives instead of once per
 * display refresh.
 *
 * <p>Stock Android batches MotionEvent moves, joystick axes and finger drags
 * included, and gives them to the window at a later vsync input callback. On
 * the stock phone emulator at 60 Hz a stick change reached the game 15.5 ms
 * after it happened, against 1.5 ms unbatched (2026-10-24); the Thor's system
 * image already delivers joystick events at once (1.3-1.5 ms either way).
 * Buttons are key events and never waited, but the Thor's D-pad reports hat
 * axes and on-screen pads follow the finger. {@link
 * View#requestUnbufferedDispatch(int)} (API 30) turns batching off for a source
 * class, but the window takes its value from the focused view's chain and
 * recomputes it on every focus change, so the request follows focus while a
 * game is attached and is withdrawn when it ends (owner, October 2026: latency
 * first, beyond what Lossless Scaling can reach from outside the emulator).</p>
 */
final class UnbufferedJoystickInput implements ViewTreeObserver.OnGlobalFocusChangeListener {
    private static final String TAG = "EmuFusionInput";
    private static final int SOURCES =
            InputDevice.SOURCE_CLASS_JOYSTICK | InputDevice.SOURCE_CLASS_POINTER;
    // QA: present when a game starts, keeps Android's per-refresh batching (A/B).
    private static final File BUFFERED_MARKER =
            new File("/data/local/tmp/emufusion-buffered-input");
    // QA: present when a game starts, logs how long stick and touch moves took to arrive.
    private static final File TRACE_MARKER = new File("/data/local/tmp/emufusion-input-trace");

    private final View decor;
    private final ArrayList<View> requested = new ArrayList<>();
    private final boolean unbuffered;
    private final Delays stick, touch;
    private ViewTreeObserver observer;

    private UnbufferedJoystickInput(View decor) {
        this.decor = decor;
        unbuffered = Build.VERSION.SDK_INT >= 30 && !BUFFERED_MARKER.exists();
        boolean tracing = TRACE_MARKER.exists();
        String mode = unbuffered ? "unbuffered" : "batched";
        stick = tracing ? new Delays("Stick", mode) : null;
        touch = tracing ? new Delays("Touch", mode) : null;
    }

    /** Starts unbuffered stick and touch delivery for the window that owns {@code decor}. */
    static UnbufferedJoystickInput install(View decor) {
        UnbufferedJoystickInput input = new UnbufferedJoystickInput(decor);
        if (input.unbuffered) {
            input.observer = decor.getViewTreeObserver();
            input.observer.addOnGlobalFocusChangeListener(input);
            View focused = decor.findFocus();
            input.request(focused != null ? focused : decor);
        }
        Log.i(TAG, "Stick and touch input " +
                (input.unbuffered ? "unbuffered" : "batched per refresh") +
                " sdk=" + Build.VERSION.SDK_INT);
        return input;
    }

    /** Restores Android's batching on every view this asked, for the library UI. */
    void release() {
        if (observer != null && observer.isAlive())
            observer.removeOnGlobalFocusChangeListener(this);
        observer = null;
        for (View view : requested) view.requestUnbufferedDispatch(InputDevice.SOURCE_CLASS_NONE);
        requested.clear();
    }

    @Override public void onGlobalFocusChanged(View oldFocus, View newFocus) {
        // Runs before the gaining view's onFocusChanged recomputes the chain,
        // and after it when focus is cleared, so the window keeps the request.
        request(newFocus != null ? newFocus : decor);
    }

    private void request(View view) {
        view.requestUnbufferedDispatch(SOURCES);
        if (!requested.contains(view)) requested.add(view);
    }

    /** QA: records how long a stick or touch move waited before reaching the game. */
    void record(MotionEvent event) {
        if (stick == null || event.getActionMasked() != MotionEvent.ACTION_MOVE) return;
        if (event.isFromSource(InputDevice.SOURCE_CLASS_JOYSTICK)) stick.add(event);
        else if (event.isFromSource(InputDevice.SOURCE_CLASS_POINTER)) touch.add(event);
    }

    private static final class Delays {
        private static final int BATCH = 200;
        private static final int LIMIT = 20;
        private final String name, mode;
        private final long[] delaysUs = new long[BATCH];
        private int count, batched, lines;

        Delays(String name, String mode) {
            this.name = name;
            this.mode = mode;
        }

        void add(MotionEvent event) {
            if (lines >= LIMIT) return;
            // Event times are uptime milliseconds (CLOCK_MONOTONIC, like nanoTime).
            delaysUs[count++] = System.nanoTime() / 1000L - event.getEventTime() * 1000L;
            if (event.getHistorySize() > 0) batched++;
            if (count < BATCH) return;
            long[] sorted = delaysUs.clone();
            Arrays.sort(sorted);
            long sum = 0L;
            for (long delay : sorted) sum += delay;
            Log.i(TAG, String.format(Locale.ROOT,
                    "%s delivery %s n=%d meanMs=%.2f p50Ms=%.2f p90Ms=%.2f maxMs=%.2f " +
                    "withEarlierSamples=%d", name, mode, count, sum / 1000.0 / count,
                    sorted[count / 2] / 1000.0, sorted[count * 9 / 10] / 1000.0,
                    sorted[count - 1] / 1000.0, batched));
            count = 0;
            batched = 0;
            lines++;
        }
    }
}
