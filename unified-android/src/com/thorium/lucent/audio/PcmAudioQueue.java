package com.thorium.lucent.audio;

import java.util.ArrayDeque;

/**
 * Bounded FIFO for interleaved PCM blocks waiting for a non-blocking audio sink.
 *
 * <p>The queue owns the arrays offered to it. A full queue rejects the newest
 * block and returns its exact size; callers must count and report that loss.
 * Replacing an older block would hide a discontinuity in audio already accepted
 * for playback, while growing without a bound turns a slow sink into seconds of
 * latency.
 */
public final class PcmAudioQueue {
    private final int capacitySamples;
    private final ArrayDeque<short[]> blocks = new ArrayDeque<>();
    private int headOffset;
    private int queuedSamples;

    public PcmAudioQueue(int capacitySamples) {
        if (capacitySamples < 2)
            throw new IllegalArgumentException("capacitySamples must hold stereo PCM");
        this.capacitySamples = capacitySamples;
    }

    /** Returns zero when accepted, otherwise the number of rejected samples. */
    public synchronized int offer(short[] samples) {
        if (samples == null || samples.length == 0) return 0;
        if ((samples.length & 1) != 0)
            throw new IllegalArgumentException("stereo PCM must contain complete frames");
        if (samples.length > capacitySamples - queuedSamples) return samples.length;
        blocks.addLast(samples);
        queuedSamples += samples.length;
        return 0;
    }

    public synchronized short[] head() { return blocks.peekFirst(); }

    public synchronized int headOffset() {
        return blocks.isEmpty() ? 0 : headOffset;
    }

    /** Removes samples successfully accepted by the audio sink. */
    public synchronized void consume(int samples) {
        short[] head = blocks.peekFirst();
        int remaining = head == null ? 0 : head.length - headOffset;
        if (samples < 0 || samples > remaining)
            throw new IllegalArgumentException("consume exceeds the pending block");
        headOffset += samples;
        queuedSamples -= samples;
        if (headOffset == head.length) {
            blocks.removeFirst();
            headOffset = 0;
        }
    }

    /** Clears pending PCM and returns the exact number of discarded samples. */
    public synchronized int clear() {
        int discarded = queuedSamples;
        blocks.clear();
        headOffset = 0;
        queuedSamples = 0;
        return discarded;
    }

    public synchronized int queuedSamples() { return queuedSamples; }

    public int capacitySamples() { return capacitySamples; }
}
