package com.thorium.lucent.video;

/** First fatal display failure, delivered once outside the latch monitor. */
public final class RuntimePresentationFailure {
    public interface Listener {
        void onRuntimeError(String message, Throwable cause);
    }

    /** Distinguishes a running display failure from startup/prerequisite fallback. */
    public static final class Failure extends IllegalStateException {
        private Failure(String message, Throwable cause) { super(message, cause); }
    }

    private Listener listener;
    private Failure failure;
    private boolean delivered;
    private boolean closed;

    /** May attach after the renderer failed but before the engine was handed its Surface. */
    public void setListener(Listener value) {
        final Listener notify;
        final Failure problem;
        synchronized (this) {
            if (closed) return;
            listener = value;
            notify = takeListener();
            problem = failure;
        }
        if (notify != null) notify.onRuntimeError(problem.getMessage(), problem);
    }

    public void report(String message, Throwable cause) {
        final Listener notify;
        final Failure problem;
        synchronized (this) {
            if (closed || failure != null) return;
            failure = new Failure(message, cause);
            notify = takeListener();
            problem = failure;
        }
        if (notify != null) notify.onRuntimeError(problem.getMessage(), problem);
    }

    /** Cancels undelivered failures; surface-generation guards reject callbacks already queued. */
    public synchronized void close() { closed = true; listener = null; }

    private Listener takeListener() {
        if (failure == null || listener == null || delivered) return null;
        delivered = true;
        return listener;
    }
}
