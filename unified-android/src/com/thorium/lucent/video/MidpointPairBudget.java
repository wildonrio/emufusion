package com.thorium.lucent.video;

/**
 * Lifetime visible-generation admission for one renderer/endpoint sequence.
 * Scheduler epochs deliberately cannot reset this budget. A submitted attempt
 * does not authorize showing another generated image from the same pair.
 * This proves ownership and sample time, not image quality or physical timing.
 */
public final class MidpointPairBudget {
    private long lastRightSequence;
    private long lastRightTimestampNs;
    private long admitted;
    private long rejected;
    private String lastRejection = "none";

    public boolean admit(FrameGenerationPresentationRequest request) {
        if (!canAdmit(request)) return false;
        lastRightSequence = request.rightSequence();
        lastRightTimestampNs = request.rightTimestampNs();
        ++admitted;
        return true;
    }

    /**
     * Serialized preflight before a synchronous transport call. It reserves
     * nothing: DEFERRED/NOT_READY explicitly submit no output. The caller must
     * admit immediately after SUBMITTED, without reentry or another request.
     */
    public boolean canAdmit(FrameGenerationPresentationRequest request) {
        if (request == null || request.leftSequence() <= 0L ||
                request.leftSequence() == Long.MAX_VALUE ||
                request.rightSequence() != request.leftSequence() + 1L)
            return reject("not-adjacent");
        long left = request.leftTimestampNs();
        long right = request.rightTimestampNs();
        if (left <= 0L || right <= left || right - left < 2L ||
                request.presentationTimestampNs() != left + (right - left) / 2L)
            return reject("not-midpoint");
        if (request.rightSequence() <= lastRightSequence ||
                left < lastRightTimestampNs)
            return reject("reused-or-reversed-pair");
        return true;
    }

    private boolean reject(String reason) {
        ++rejected;
        lastRejection = reason;
        return false;
    }

    public long admitted() { return admitted; }
    public long rejected() { return rejected; }
    public String lastRejection() { return lastRejection; }
}
