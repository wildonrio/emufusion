package com.thorium.lucent.audio;

/**
 * Allocation-free-per-sample signal measurements for interleaved stereo PCM.
 *
 * <p>This analyzer sits before the Android audio sink. Its measurements can
 * prove that a core produced a non-silent, tone-like PCM signal; they cannot
 * prove that AudioTrack, the mixer, an amplifier, or a speaker made it audible.
 * Sink evidence must be evaluated separately.
 *
 * <p>The frequency indicator counts positive-going crossings after a one-pole
 * DC blocker and fixed hysteresis. It is defensible for the qualification
 * fixture's isolated tone, including a DC-biased tone, but is not a pitch
 * detector for arbitrary game audio.
 */
public final class PcmSignalTelemetry {
    private static final double DC_BLOCK_POLE = 0.995;
    private static final double CROSSING_THRESHOLD = 64.0;

    public static final class ChannelSnapshot {
        public final int min;
        public final int max;
        public final int peak;
        public final double rms;
        /** Positive-going, DC-blocked crossing estimate; -1 when unavailable. */
        public final double toneHz;
        public final long positiveCrossings;

        private ChannelSnapshot(int min, int max, int peak, double rms,
                double toneHz, long positiveCrossings) {
            this.min = min;
            this.max = max;
            this.peak = peak;
            this.rms = rms;
            this.toneHz = toneHz;
            this.positiveCrossings = positiveCrossings;
        }
    }

    public static final class Snapshot {
        public final int sampleRate;
        public final long frames;
        public final long interleavedSamples;
        /** One-crossing resolution across this observation window, in Hz. */
        public final double frequencyResolutionHz;
        public final boolean overflowed;
        public final ChannelSnapshot left;
        public final ChannelSnapshot right;

        private Snapshot(int sampleRate, long frames, boolean overflowed,
                ChannelSnapshot left, ChannelSnapshot right) {
            this.sampleRate = sampleRate;
            this.frames = frames;
            this.interleavedSamples = multiplyTwoSaturated(frames);
            this.frequencyResolutionHz = frames > 1L
                    ? sampleRate / (double) (frames - 1L) : -1.0;
            this.overflowed = overflowed;
            this.left = left;
            this.right = right;
        }
    }

    private final int sampleRate;
    private final long counterLimit;
    private final ChannelAnalyzer left;
    private final ChannelAnalyzer right;
    private long streamFrame;
    private boolean streamOverflowed;

    public PcmSignalTelemetry(int sampleRate) {
        this(sampleRate, Long.MAX_VALUE);
    }

    /** Small counter limits let host tests exercise saturation without days of PCM. */
    PcmSignalTelemetry(int sampleRate, long counterLimit) {
        if (sampleRate < 8_000 || sampleRate > 384_000)
            throw new IllegalArgumentException("sampleRate is outside the PCM contract");
        if (counterLimit < 1L)
            throw new IllegalArgumentException("counterLimit must be positive");
        this.sampleRate = sampleRate;
        this.counterLimit = counterLimit;
        this.left = new ChannelAnalyzer(counterLimit);
        this.right = new ChannelAnalyzer(counterLimit);
    }

    /** Accepts complete interleaved stereo frames at the configured sample rate. */
    public synchronized void accept(short[] interleavedStereo) {
        if (interleavedStereo == null || interleavedStereo.length == 0) return;
        if ((interleavedStereo.length & 1) != 0)
            throw new IllegalArgumentException("stereo PCM must contain complete frames");
        for (int sample = 0; sample < interleavedStereo.length; sample += 2) {
            long position = streamFrame;
            left.accept(interleavedStereo[sample], position);
            right.accept(interleavedStereo[sample + 1], position);
            if (streamFrame < counterLimit) ++streamFrame;
            else streamOverflowed = true;
        }
    }

    /** Returns and clears the current rolling window without resetting filters. */
    public synchronized Snapshot snapshotWindowAndReset() {
        Snapshot result = snapshot(left.window, right.window,
                left.window.overflowed || right.window.overflowed || streamOverflowed);
        left.window.reset();
        right.window.reset();
        return result;
    }

    /** Returns cumulative measurements since construction or {@link #resetAll()}. */
    public synchronized Snapshot snapshotCumulative() {
        return snapshot(left.cumulative, right.cumulative,
                left.cumulative.overflowed || right.cumulative.overflowed || streamOverflowed);
    }

    /** Clears only rolling aggregates; DC/crossing continuity is preserved. */
    public synchronized void resetWindow() {
        left.window.reset();
        right.window.reset();
    }

    /** Clears all aggregates and filter history for a new game session. */
    public synchronized void resetAll() {
        streamFrame = 0L;
        streamOverflowed = false;
        left.resetAll();
        right.resetAll();
    }

    private Snapshot snapshot(Stats leftStats, Stats rightStats, boolean overflowed) {
        long frames = Math.min(leftStats.frames, rightStats.frames);
        return new Snapshot(sampleRate, frames, overflowed,
                leftStats.snapshot(sampleRate), rightStats.snapshot(sampleRate));
    }

    static long multiplyTwoSaturated(long value) {
        return value > Long.MAX_VALUE / 2L ? Long.MAX_VALUE : value * 2L;
    }

    private static final class ChannelAnalyzer {
        final Stats cumulative;
        final Stats window;
        double previousInput;
        double previousFiltered;
        int crossingSign;

        ChannelAnalyzer(long counterLimit) {
            cumulative = new Stats(counterLimit);
            window = new Stats(counterLimit);
        }

        void accept(short sample, long frame) {
            double filtered = sample - previousInput + DC_BLOCK_POLE * previousFiltered;
            previousInput = sample;
            previousFiltered = filtered;
            int nextSign = crossingSign;
            if (filtered >= CROSSING_THRESHOLD) nextSign = 1;
            else if (filtered <= -CROSSING_THRESHOLD) nextSign = -1;
            boolean positiveCrossing = crossingSign < 0 && nextSign > 0;
            crossingSign = nextSign;
            cumulative.accept(sample, frame, positiveCrossing);
            window.accept(sample, frame, positiveCrossing);
        }

        void resetAll() {
            previousInput = 0.0;
            previousFiltered = 0.0;
            crossingSign = 0;
            cumulative.reset();
            window.reset();
        }
    }

    private static final class Stats {
        final long counterLimit;
        long frames;
        int min;
        int max;
        int peak;
        double sumSquares;
        long positiveCrossings;
        long firstCrossingFrame;
        long lastCrossingFrame;
        boolean overflowed;

        Stats(long counterLimit) {
            this.counterLimit = counterLimit;
            reset();
        }

        void accept(short value, long frame, boolean positiveCrossing) {
            if (frames >= counterLimit) {
                overflowed = true;
                return;
            }
            int integer = value;
            if (integer < min) min = integer;
            if (integer > max) max = integer;
            int magnitude = integer == Short.MIN_VALUE ? 32_768 : Math.abs(integer);
            if (magnitude > peak) peak = magnitude;
            double nextSquares = sumSquares + (double) integer * (double) integer;
            sumSquares = Double.isFinite(nextSquares) ? nextSquares : Double.MAX_VALUE;
            if (positiveCrossing) {
                if (positiveCrossings == 0L) firstCrossingFrame = frame;
                lastCrossingFrame = frame;
                if (positiveCrossings < counterLimit) ++positiveCrossings;
                else overflowed = true;
            }
            ++frames;
        }

        ChannelSnapshot snapshot(int sampleRate) {
            if (frames == 0L) return new ChannelSnapshot(0, 0, 0, 0.0, -1.0, 0L);
            double rms = Math.sqrt(sumSquares / (double) frames);
            double toneHz = -1.0;
            long span = lastCrossingFrame - firstCrossingFrame;
            if (positiveCrossings >= 2L && span > 0L)
                toneHz = (positiveCrossings - 1L) * (double) sampleRate / (double) span;
            return new ChannelSnapshot(min, max, peak, rms, toneHz,
                    positiveCrossings);
        }

        void reset() {
            frames = 0L;
            min = Integer.MAX_VALUE;
            max = Integer.MIN_VALUE;
            peak = 0;
            sumSquares = 0.0;
            positiveCrossings = 0L;
            firstCrossingFrame = -1L;
            lastCrossingFrame = -1L;
            overflowed = false;
        }
    }
}
