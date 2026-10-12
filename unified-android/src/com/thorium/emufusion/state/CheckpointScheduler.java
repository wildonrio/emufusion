package com.thorium.emufusion.state;

/** Counts emulated play only; pause/background/menu time is never supplied to this object. */
public final class CheckpointScheduler {
    public static final long DEFAULT_INTERVAL_MILLIS = 10L * 60L * 1000L;
    private final long intervalMillis;
    private long activeSinceCheckpoint;
    private long totalActiveMillis;

    public CheckpointScheduler() {
        this(DEFAULT_INTERVAL_MILLIS, 0L);
    }

    public CheckpointScheduler(long intervalMillis, long previousActiveMillis) {
        if (intervalMillis <= 0) throw new IllegalArgumentException("intervalMillis must be positive");
        if (previousActiveMillis < 0) throw new IllegalArgumentException("active time cannot be negative");
        this.intervalMillis = intervalMillis;
        this.totalActiveMillis = previousActiveMillis;
        this.activeSinceCheckpoint = previousActiveMillis % intervalMillis;
    }

    /** Returns how many intervals became due; normally zero or one. */
    public synchronized int advanceActivePlay(long elapsedMillis) {
        if (elapsedMillis < 0) throw new IllegalArgumentException("elapsedMillis cannot be negative");
        totalActiveMillis = Math.addExact(totalActiveMillis, elapsedMillis);
        activeSinceCheckpoint = Math.addExact(activeSinceCheckpoint, elapsedMillis);
        int due = (int) Math.min(Integer.MAX_VALUE, activeSinceCheckpoint / intervalMillis);
        activeSinceCheckpoint %= intervalMillis;
        return due;
    }

    public synchronized long totalActiveMillis() { return totalActiveMillis; }
    public synchronized long millisUntilNextCheckpoint() {
        return intervalMillis - activeSinceCheckpoint;
    }
}
