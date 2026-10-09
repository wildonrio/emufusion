package com.thorium.lucent.timing;

import java.util.function.Consumer;

/**
 * A bounded one-value handoff for real-time producers.
 *
 * Offering a newer value replaces an unconsumed older value. This keeps a
 * presentation consumer from ever back-pressuring the emulation clock.
 */
public final class LatestValueMailbox<T> {
    public enum OfferResult { REJECTED, ACCEPTED, REPLACED }

    private T latest;
    private boolean closed;

    public synchronized boolean offer(T value) {
        return offerLatest(value) != OfferResult.REJECTED;
    }

    /** Atomically publishes and reports whether an older unconsumed value was replaced. */
    public synchronized OfferResult offerLatest(T value) {
        return offerLatest(value, ignored -> {});
    }

    /**
     * Atomically publishes a value and returns an overwritten value to its
     * owner before the method returns. Real-time video uses this overload so a
     * replaced pooled frame is recycled exactly once instead of leaking a
     * buffer or allocating a replacement on the next core callback.
     */
    public synchronized OfferResult offerLatest(T value, Consumer<T> onDiscarded) {
        if (value == null) throw new IllegalArgumentException("value required");
        if (onDiscarded == null)
            throw new IllegalArgumentException("discard callback required");
        if (closed) return OfferResult.REJECTED;
        T replacedValue = latest;
        latest = value;
        if (replacedValue != null) onDiscarded.accept(replacedValue);
        notifyAll();
        return replacedValue != null ? OfferResult.REPLACED : OfferResult.ACCEPTED;
    }

    public synchronized boolean isEmpty() {
        return latest == null;
    }

    /** Returns null only after the mailbox has been closed. */
    public synchronized T take() throws InterruptedException {
        while (latest == null && !closed) wait();
        if (closed) return null;
        T value = latest;
        latest = null;
        return value;
    }

    public synchronized void close() {
        close(ignored -> {});
    }

    /** Closes the mailbox and returns an unconsumed value to its owner. */
    public synchronized void close(Consumer<T> onDiscarded) {
        if (onDiscarded == null)
            throw new IllegalArgumentException("discard callback required");
        closed = true;
        T discarded = latest;
        latest = null;
        if (discarded != null) onDiscarded.accept(discarded);
        notifyAll();
    }
}
