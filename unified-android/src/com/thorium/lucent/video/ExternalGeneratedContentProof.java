package com.thorium.lucent.video;

/**
 * Immutable, asynchronous content proof for one external-backend output.
 * Its sequence is bound to the native submission/presentation identity by the
 * transport before the row may enter physical-presentation accounting.
 */
public final class ExternalGeneratedContentProof {
    public final long leftChecksum;
    public final long rightChecksum;
    public final long outputChecksum;
    public final long endpointMadPpm;
    public final long outputLeftMadPpm;
    public final long outputRightMadPpm;
    public final long endpointHistogramDistancePpm;
    public final int outputMin;
    public final int outputMax;
    public final boolean sceneCutRisk;
    public final long analysisWallNs;
    public final int width;
    public final int height;
    public final long sampleCount;
    public final long sequence;
    public final long byteCount;

    public ExternalGeneratedContentProof(
            long leftChecksum, long rightChecksum, long outputChecksum,
            long endpointMadPpm, long outputLeftMadPpm,
            long outputRightMadPpm, long endpointHistogramDistancePpm,
            int outputMin, int outputMax, boolean sceneCutRisk,
            long analysisWallNs, int width, int height,
            long sampleCount, long sequence, long byteCount) {
        if (!ppm(endpointMadPpm) || !ppm(outputLeftMadPpm) ||
                !ppm(outputRightMadPpm) ||
                !ppm(endpointHistogramDistancePpm) || outputMin < 0 ||
                outputMax < outputMin || outputMax > 255 ||
                analysisWallNs <= 0L || width != 48 || height != 27 ||
                sampleCount != 1296L || sequence <= 0L ||
                byteCount != 11664L)
            throw new IllegalArgumentException("content proof is invalid");
        this.leftChecksum = leftChecksum;
        this.rightChecksum = rightChecksum;
        this.outputChecksum = outputChecksum;
        this.endpointMadPpm = endpointMadPpm;
        this.outputLeftMadPpm = outputLeftMadPpm;
        this.outputRightMadPpm = outputRightMadPpm;
        this.endpointHistogramDistancePpm = endpointHistogramDistancePpm;
        this.outputMin = outputMin;
        this.outputMax = outputMax;
        this.sceneCutRisk = sceneCutRisk;
        this.analysisWallNs = analysisWallNs;
        this.width = width;
        this.height = height;
        this.sampleCount = sampleCount;
        this.sequence = sequence;
        this.byteCount = byteCount;
    }

    private static boolean ppm(long value) {
        return value >= 0L && value <= 1_000_000L;
    }
}
