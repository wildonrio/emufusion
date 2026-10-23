package com.thorium.emufusion.video;

/**
 * When an admitted image could first have been taken up: the vsync time of
 * the first callback that ran after its admission.
 *
 * <p>Arrival pacing calls a pair late when the time since its right image was
 * ready exceeds half its span less half a scan (TimelineFrameScheduler): a
 * pair that missed a callback would otherwise start every later pair a scan
 * late. 3.2.89 admits images about 1 ms after they arrive instead of at the
 * next callback, so the time since admission also counted the unavoidable
 * wait for that callback -- uniform over a scan, so at 60 -> 120 it alone
 * passed the 4.2 ms threshold about half the time, depending only on the
 * game's frame phase (Thor, GameCube: the generated image skipped for 500 of
 * 820 pairs, 80-92 fps instead of 120, then generation switched off). Counted
 * from this time, a pair taken up at the first callback that could see it has
 * waited nothing and one that sat through a callback has waited a scan.</p>
 */
public final class CallbackReadyClock {
    private static final int CAPACITY = 16;
    private final long[] vsyncNs = new long[CAPACITY];
    private final long[] runNs = new long[CAPACITY];
    private int head, count;

    /** A callback for vsync {@code frameNs} started running at {@code startedNs}. */
    public void callback(long frameNs, long startedNs) {
        int slot = (head + count) % CAPACITY;
        if (count == CAPACITY) head = (head + 1) % CAPACITY;
        else ++count;
        vsyncNs[slot] = frameNs;
        runNs[slot] = startedNs;
    }

    public void reset() {
        head = 0;
        count = 0;
    }

    /**
     * The vsync time of the first callback that started after {@code admittedNs};
     * {@code currentFrameNs} when the image was admitted during the current
     * callback (or none is known), the oldest recorded callback when it
     * predates them all. 0 stays 0 (unknown).
     */
    public long readyNs(long admittedNs, long currentFrameNs) {
        if (admittedNs <= 0L) return 0L;
        for (int i = 0; i < count; ++i) {
            int slot = (head + i) % CAPACITY;
            if (runNs[slot] > admittedNs) return vsyncNs[slot];
        }
        return currentFrameNs;
    }
}
