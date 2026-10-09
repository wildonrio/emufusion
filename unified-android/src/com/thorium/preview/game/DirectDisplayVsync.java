package com.thorium.preview.game;

import android.app.Activity;
import android.content.Context;
import android.hardware.display.DisplayManager;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Process;
import android.view.Choreographer;
import android.view.Display;
import com.thorium.lucent.timing.VsyncCadence;

/** Display-clock input only: owns no rendering Surface, images or FG worker. */
final class DirectDisplayVsync implements AutoCloseable {
    private final Object lock = new Object();
    private final VsyncCadence cadence = new VsyncCadence();
    private final HandlerThread thread = new HandlerThread(
            "emufusion-direct-vsync", Process.THREAD_PRIORITY_DISPLAY);
    private final Handler handler;
    private final Display display;
    private Choreographer choreographer;
    private boolean active, closed;
    private double declaredHz, sourceHz;

    DirectDisplayVsync(Context context) {
        display = context instanceof Activity
                ? ((Activity) context).getWindowManager().getDefaultDisplay()
                : ((DisplayManager) context.getSystemService(Context.DISPLAY_SERVICE))
                        .getDisplay(Display.DEFAULT_DISPLAY);
        thread.start();
        handler = new Handler(thread.getLooper());
        handler.post(() -> {
            try {
                choreographer = Choreographer.getInstance();
                refreshCallback();
            } catch (RuntimeException unavailable) {
                // A display timing service is optional; the existing absolute
                // core clock remains usable if this device cannot supply it.
                thread.quitSafely();
            }
        });
    }

    private final Choreographer.FrameCallback callback = this::onVsync;

    void configure(double declared, double source, boolean enabled) {
        boolean changed;
        synchronized (lock) {
            if (closed) return;
            changed = declaredHz != declared || sourceHz != source || active != enabled;
            if (!changed) return;
            declaredHz = declared;
            sourceHz = source;
            active = enabled;
            cadence.reset();
            lock.notifyAll();
        }
        handler.post(this::refreshCallback);
    }

    void suspend() {
        synchronized (lock) {
            active = false;
            cadence.reset();
            lock.notifyAll();
        }
        handler.post(this::refreshCallback);
    }

    private void refreshCallback() {
        if (choreographer == null) return;
        choreographer.removeFrameCallback(callback);
        synchronized (lock) {
            if (active && !closed && display != null)
                choreographer.postFrameCallback(callback);
        }
    }

    private void onVsync(long timestampNs) {
        synchronized (lock) {
            if (!active || closed || display == null) return;
            cadence.configure(declaredHz, sourceHz, display.getRefreshRate());
            cadence.onVsync(timestampNs);
            lock.notifyAll();
            choreographer.postFrameCallback(callback);
        }
    }

    long awaitDueTimeNs() throws InterruptedException {
        synchronized (lock) {
            if (!active || closed || !cadence.ready()) return 0;
            long deadline = System.nanoTime() +
                    Math.min(120_000_000L, (long) (2_000_000_000.0 / sourceHz));
            while (active && !closed && cadence.ready() && !cadence.hasPending()) {
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0) {
                    // Recover to the existing absolute clock while fresh
                    // display callbacks warm up; never wait indefinitely.
                    cadence.reset();
                    return 0;
                }
                lock.wait(remaining / 1_000_000L, (int) (remaining % 1_000_000L));
            }
            return active && !closed ? cadence.takeDueTimeNs() : 0;
        }
    }

    boolean hasNewerDueFrame() {
        synchronized (lock) { return cadence.hasPending(); }
    }

    boolean coalescingCatchUpPresentation() {
        synchronized (lock) { return cadence.coalescingCatchUpPresentation(); }
    }

    double measuredSourceHz() {
        synchronized (lock) { return cadence.measuredSourceHz(); }
    }

    @Override public void close() {
        synchronized (lock) {
            closed = true;
            active = false;
            cadence.reset();
            lock.notifyAll();
        }
        handler.post(() -> {
            if (choreographer != null) choreographer.removeFrameCallback(callback);
            thread.quitSafely();
        });
        boolean interrupted = false;
        while (thread.isAlive()) {
            try { thread.join(); }
            catch (InterruptedException ignored) { interrupted = true; }
        }
        if (interrupted) Thread.currentThread().interrupt();
    }
}
