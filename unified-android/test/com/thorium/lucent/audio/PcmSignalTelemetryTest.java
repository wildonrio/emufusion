package com.thorium.lucent.audio;

import com.thorium.lucent.TestSupport;

public final class PcmSignalTelemetryTest {
    private static final int RATE = 48_000;

    public static void main(String[] args) {
        silenceHasNoInventedTone();
        sineReportsItsSignalAndFrequency();
        squareToneSurvivesDcBias();
        dcBiasAloneCannotFakeFrequency();
        oneDiscontinuityCannotFakeFrequency();
        callbackChunkBoundariesDoNotChangeTheResult();
        countersAndSampleMultiplicationSaturate();
        malformedStereoFailsClosed();
        System.out.println("PcmSignalTelemetryTest passed");
    }

    private static void silenceHasNoInventedTone() {
        PcmSignalTelemetry analyzer = new PcmSignalTelemetry(RATE);
        analyzer.accept(new short[RATE * 2]);
        PcmSignalTelemetry.Snapshot snapshot = analyzer.snapshotWindowAndReset();
        TestSupport.equal((long) RATE, snapshot.frames, "one second of silent frames counted");
        TestSupport.equal((long) RATE * 2L, snapshot.interleavedSamples,
                "both silent channels counted");
        near(1.0, snapshot.frequencyResolutionHz, 0.001,
                "frequency resolution is bound to rate and window");
        assertSilent(snapshot.left, "left silence");
        assertSilent(snapshot.right, "right silence");
    }

    private static void sineReportsItsSignalAndFrequency() {
        PcmSignalTelemetry analyzer = new PcmSignalTelemetry(RATE);
        analyzer.accept(sine(2 * RATE, 440.0, 12_000, 8_000, 0));
        PcmSignalTelemetry.Snapshot snapshot = analyzer.snapshotWindowAndReset();
        TestSupport.truth(snapshot.left.min < -11_000 && snapshot.left.max > 11_000,
                "left sine spans both polarities");
        TestSupport.truth(snapshot.right.peak >= 7_900, "right peak is measured independently");
        TestSupport.truth(snapshot.left.rms > 8_400 && snapshot.left.rms < 8_600,
                "left sine RMS is physically plausible");
        near(440.0, snapshot.left.toneHz, 1.0, "left sine frequency");
        near(440.0, snapshot.right.toneHz, 1.0, "right sine frequency");
    }

    private static void squareToneSurvivesDcBias() {
        PcmSignalTelemetry analyzer = new PcmSignalTelemetry(RATE);
        short[] pcm = new short[RATE * 4];
        for (int frame = 0; frame < RATE * 2; frame++) {
            int wave = Math.sin(2.0 * Math.PI * 440.0 * frame / RATE) >= 0.0
                    ? 9_000 : -9_000;
            pcm[frame * 2] = (short) (wave + 4_000);
            pcm[frame * 2 + 1] = (short) (-wave - 3_000);
        }
        analyzer.accept(pcm);
        PcmSignalTelemetry.Snapshot snapshot = analyzer.snapshotWindowAndReset();
        near(440.0, snapshot.left.toneHz, 1.0, "DC-biased square left frequency");
        near(440.0, snapshot.right.toneHz, 1.0, "DC-biased square right frequency");
        TestSupport.truth(snapshot.left.min > -6_000 && snapshot.left.max > 12_000,
                "raw min/max retain the DC bias while frequency rejects it");
    }

    private static void dcBiasAloneCannotFakeFrequency() {
        PcmSignalTelemetry analyzer = new PcmSignalTelemetry(RATE);
        short[] pcm = new short[RATE * 2];
        for (int sample = 0; sample < pcm.length; sample += 2) {
            pcm[sample] = 7_000;
            pcm[sample + 1] = -5_000;
        }
        analyzer.accept(pcm);
        PcmSignalTelemetry.Snapshot snapshot = analyzer.snapshotWindowAndReset();
        TestSupport.equal(-1.0, snapshot.left.toneHz, "positive DC has no tone estimate");
        TestSupport.equal(-1.0, snapshot.right.toneHz, "negative DC has no tone estimate");
        TestSupport.truth(snapshot.left.rms == 7_000.0 && snapshot.right.rms == 5_000.0,
                "raw RMS still exposes non-silent DC");
    }

    private static void oneDiscontinuityCannotFakeFrequency() {
        PcmSignalTelemetry analyzer = new PcmSignalTelemetry(RATE);
        short[] pcm = new short[RATE * 2];
        for (int frame = 0; frame < RATE; frame++) {
            pcm[frame * 2] = (short) (frame < RATE / 2 ? -8_000 : 8_000);
            pcm[frame * 2 + 1] = (short) (frame < RATE / 2 ? 8_000 : -8_000);
        }
        analyzer.accept(pcm);
        PcmSignalTelemetry.Snapshot snapshot = analyzer.snapshotWindowAndReset();
        TestSupport.equal(-1.0, snapshot.left.toneHz,
                "one positive discontinuity is insufficient for a frequency");
        TestSupport.equal(-1.0, snapshot.right.toneHz,
                "one negative discontinuity is insufficient for a frequency");
        TestSupport.truth(snapshot.left.positiveCrossings <= 1L &&
                        snapshot.right.positiveCrossings <= 1L,
                "a single step cannot become repeated tone evidence");
    }

    private static void callbackChunkBoundariesDoNotChangeTheResult() {
        short[] pcm = sine(2 * RATE, 440.0, 10_000, 10_000, 1_500);
        PcmSignalTelemetry contiguous = new PcmSignalTelemetry(RATE);
        contiguous.accept(pcm);
        PcmSignalTelemetry.Snapshot expected = contiguous.snapshotCumulative();

        PcmSignalTelemetry chunked = new PcmSignalTelemetry(RATE);
        int frame = 0;
        int[] chunkFrames = {1, 7, 113, 2_003, 5, 4_096, 37};
        int chunk = 0;
        while (frame < pcm.length / 2) {
            int count = Math.min(chunkFrames[chunk++ % chunkFrames.length],
                    pcm.length / 2 - frame);
            short[] part = new short[count * 2];
            System.arraycopy(pcm, frame * 2, part, 0, part.length);
            chunked.accept(part);
            frame += count;
        }
        PcmSignalTelemetry.Snapshot actual = chunked.snapshotCumulative();
        TestSupport.equal(expected.frames, actual.frames, "chunking preserves frame count");
        TestSupport.equal(expected.left.positiveCrossings, actual.left.positiveCrossings,
                "chunking preserves left crossings");
        TestSupport.equal(expected.right.positiveCrossings, actual.right.positiveCrossings,
                "chunking preserves right crossings");
        near(expected.left.toneHz, actual.left.toneHz, 0.000_001,
                "chunking preserves frequency");
        near(expected.left.rms, actual.left.rms, 0.000_001,
                "chunking preserves RMS");

        // A rolling reset is not a signal discontinuity: filter state survives.
        chunked.snapshotWindowAndReset();
        chunked.accept(sine(RATE, 440.0, 10_000, 10_000, 1_500));
        near(440.0, chunked.snapshotWindowAndReset().left.toneHz, 1.0,
                "rolling reset preserves DC-blocker continuity");
    }

    private static void countersAndSampleMultiplicationSaturate() {
        PcmSignalTelemetry analyzer = new PcmSignalTelemetry(RATE, 10L);
        analyzer.accept(sine(100, 440.0, 32_767, 32_767, 0));
        PcmSignalTelemetry.Snapshot cumulative = analyzer.snapshotCumulative();
        TestSupport.equal(10L, cumulative.frames, "bounded cumulative frame counter");
        TestSupport.equal(20L, cumulative.interleavedSamples,
                "bounded stereo sample counter");
        TestSupport.equal(Long.MAX_VALUE,
                PcmSignalTelemetry.multiplyTwoSaturated(Long.MAX_VALUE),
                "stereo sample multiplication saturates instead of wrapping");
        TestSupport.truth(cumulative.overflowed, "counter saturation is explicit");
        TestSupport.truth(Double.isFinite(cumulative.left.rms) && cumulative.left.rms >= 0.0,
                "saturation cannot overflow RMS");
        TestSupport.truth(cumulative.left.peak <= 32_768,
                "signed-short peak stays bounded");
    }

    private static void malformedStereoFailsClosed() {
        PcmSignalTelemetry analyzer = new PcmSignalTelemetry(RATE);
        boolean rejected = false;
        try { analyzer.accept(new short[] {1, 2, 3}); }
        catch (IllegalArgumentException expected) { rejected = true; }
        TestSupport.truth(rejected, "half a stereo frame is rejected");
    }

    private static short[] sine(int frames, double hz, int leftAmplitude,
            int rightAmplitude, int dcBias) {
        short[] pcm = new short[frames * 2];
        for (int frame = 0; frame < frames; frame++) {
            double value = Math.sin(2.0 * Math.PI * hz * frame / RATE);
            pcm[frame * 2] = bounded(value * leftAmplitude + dcBias);
            pcm[frame * 2 + 1] = bounded(value * rightAmplitude - dcBias);
        }
        return pcm;
    }

    private static short bounded(double value) {
        return (short) Math.max(Short.MIN_VALUE,
                Math.min(Short.MAX_VALUE, Math.round(value)));
    }

    private static void assertSilent(PcmSignalTelemetry.ChannelSnapshot channel,
            String label) {
        TestSupport.equal(0, channel.min, label + " minimum");
        TestSupport.equal(0, channel.max, label + " maximum");
        TestSupport.equal(0, channel.peak, label + " peak");
        TestSupport.equal(0.0, channel.rms, label + " RMS");
        TestSupport.equal(-1.0, channel.toneHz, label + " has no fabricated frequency");
        TestSupport.equal(0L, channel.positiveCrossings, label + " has no crossings");
    }

    private static void near(double expected, double actual, double tolerance, String label) {
        TestSupport.truth(Double.isFinite(actual) && Math.abs(expected - actual) <= tolerance,
                label + " expected=" + expected + " actual=" + actual);
    }
}
