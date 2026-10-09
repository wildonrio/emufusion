package com.thorium.preview;

/** Per-launch deduplication. A ready callback is not a gameplay or smoothness pass. */
public final class PrivateDiagnosticsSession {
    public interface Sink { void record(String event, String bucket); }
    private final Sink sink;
    private final Runnable onClose;
    private boolean ready, failed, closed;

    public PrivateDiagnosticsSession(Sink sink) { this(sink, () -> {}); }

    PrivateDiagnosticsSession(Sink sink, Runnable onClose) {
        this.sink = sink;
        this.onClose = onClose;
    }

    public synchronized void ready() {
        if (ready || failed || closed) return;
        ready = true;
        sink.record("engine_ready", "ok");
    }

    public synchronized void failed(boolean outOfMemory) {
        if (failed || closed) return;
        failed = true;
        sink.record(ready ? "runtime_failed" : "launch_failed",
                outOfMemory ? "out_of_memory" : "unknown");
    }

    public synchronized void close() {
        if (closed) return;
        closed = true;
        onClose.run();
    }
}
