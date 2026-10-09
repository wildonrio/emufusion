package com.thorium.lucent.video;

import java.util.Arrays;

/**
 * Bounded, submission-ordered join of shader pairs and exact EGL frame events.
 * Ready times are driver-returned timestamps for that frame, never the time a
 * polling thread happened to observe completion. Endpoint rows carry continuity
 * evidence but cannot earn generation recovery credit.
 */
public final class GpuPhysicalHeadroomLedger {
    public static final int RENDER_COMPLETE = 1;
    public static final int COMPOSITION_LATCH = 2;
    public static final int COMPOSITION_START = 4;
    public static final int COMPOSITION_GPU_FINISHED = 8;
    public static final int ALL_TIMESTAMPS = 15;
    public static final int PRESENTED = 1;
    public static final int DROPPED = 2;
    public static final int UNAVAILABLE = 3;

    public enum Outcome { VERIFIED_HEADROOM, MARGINAL_HEADROOM, UNKNOWN, DEADLINE_MISS }

    public static final class Result {
        public final long epoch, presentationEpoch, frameId, pairSequence, warpSequence;
        public final long shaderCostUs, shaderBudgetUs, appMarginNs, compositorMarginNs;
        public final long desiredNs, actualNs, deadlineNs, renderCompleteNs, panelPeriodNs;
        public final long latchNs, startNs, gpuFinishedNs;
        public final int supportedMask;
        public final Outcome outcome;
        public final String reason;

        private Result(Row row, long shaderCostUs, long shaderBudgetUs,
                       Outcome outcome, String reason, long appMarginNs,
                       long compositorMarginNs) {
            epoch = row.epoch;
            presentationEpoch = row.presentationEpoch;
            frameId = row.frameId;
            pairSequence = row.pairSequence;
            warpSequence = row.warpSequence;
            desiredNs = row.desiredNs;
            actualNs = row.actualNs;
            deadlineNs = row.deadlineNs;
            renderCompleteNs = row.renderCompleteNs;
            panelPeriodNs = row.panelPeriodNs;
            latchNs = row.latchNs;
            startNs = row.startNs;
            gpuFinishedNs = row.gpuFinishedNs;
            supportedMask = row.supportedMask;
            this.shaderCostUs = shaderCostUs;
            this.shaderBudgetUs = shaderBudgetUs;
            this.outcome = outcome;
            this.reason = reason;
            this.appMarginNs = appMarginNs;
            this.compositorMarginNs = compositorMarginNs;
        }

        public boolean generated() { return pairSequence > 0L; }
    }

    private static final class Row {
        long epoch, presentationEpoch, frameId, pairSequence, warpSequence, desiredNs, deadlineNs;
        long panelPeriodNs, actualNs, renderCompleteNs, latchNs, startNs, gpuFinishedNs;
        int scans, status, supportedMask;
    }

    private final Row[] rows;
    private final long[] shaderPairs, shaderCostsUs, shaderBudgetsUs;
    private final boolean[] shaderConsumed;
    private int head, count;
    private long epoch, lastFrameId, lastPairSequence, lastWarpSequence, lastDesiredNs;

    public GpuPhysicalHeadroomLedger(int capacity) {
        if (capacity < 1) throw new IllegalArgumentException("invalid headroom capacity");
        rows = new Row[capacity];
        shaderPairs = new long[capacity];
        shaderCostsUs = new long[capacity];
        shaderBudgetsUs = new long[capacity];
        shaderConsumed = new boolean[capacity];
    }

    public void beginEvidenceEpoch(long epoch) {
        if (epoch <= this.epoch) throw new IllegalArgumentException("headroom epoch did not advance");
        this.epoch = epoch;
        Arrays.fill(rows, null);
        Arrays.fill(shaderPairs, 0L);
        Arrays.fill(shaderCostsUs, 0L);
        Arrays.fill(shaderBudgetsUs, 0L);
        Arrays.fill(shaderConsumed, false);
        head = count = 0;
        lastFrameId = lastPairSequence = lastWarpSequence = lastDesiredNs = 0L;
    }

    /** Called only after the EGL ID's corresponding swap successfully commits. */
    public boolean bindSwap(long epoch, long presentationEpoch,
                            long frameId, long pairSequence, long warpSequence,
                            long desiredNs, long deadlineNs, int scans, long panelPeriodNs) {
        if (epoch != this.epoch || epoch <= 0L || presentationEpoch <= 0L || frameId <= lastFrameId ||
                frameId <= 0L || desiredNs <= lastDesiredNs || desiredNs <= 0L || deadlineNs <= 0L ||
                deadlineNs >= desiredNs || scans <= 0 || panelPeriodNs <= 0L ||
                pairSequence < 0L || warpSequence < 0L ||
                ((pairSequence == 0L) != (warpSequence == 0L)) || count == rows.length)
            return false;
        if (pairSequence > 0L && (pairSequence <= lastPairSequence ||
                warpSequence <= lastWarpSequence)) return false;
        Row row = new Row();
        row.epoch = epoch;
        row.presentationEpoch = presentationEpoch;
        row.frameId = frameId;
        row.pairSequence = pairSequence;
        row.warpSequence = warpSequence;
        row.desiredNs = desiredNs;
        row.deadlineNs = deadlineNs;
        row.scans = scans;
        row.panelPeriodNs = panelPeriodNs;
        rows[(head + count++) % rows.length] = row;
        lastFrameId = frameId;
        lastDesiredNs = desiredNs;
        if (pairSequence > 0L) {
            lastPairSequence = pairSequence;
            lastWarpSequence = warpSequence;
        }
        return true;
    }

    /** The caller has already joined every estimator stage and its own warp. */
    public boolean recordShader(long epoch, long pairSequence, long costUs, long budgetUs) {
        if (epoch != this.epoch || epoch <= 0L || pairSequence <= 0L ||
                costUs <= 0L || budgetUs <= 0L) return false;
        int slot = (int) (pairSequence % shaderPairs.length);
        if (shaderPairs[slot] >= pairSequence ||
                (shaderPairs[slot] != 0L && !shaderConsumed[slot])) return false;
        shaderPairs[slot] = pairSequence;
        shaderCostsUs[slot] = costUs;
        shaderBudgetsUs[slot] = budgetUs;
        shaderConsumed[slot] = false;
        return true;
    }

    /** Unknown, negative, or unsupported optional timestamps are retained as unknown. */
    public boolean recordPhysical(long epoch, long frameId, int status, long actualNs,
                                  int scans, long panelPeriodNs, int supportedMask,
                                  long renderCompleteNs, long latchNs,
                                  long startNs, long gpuFinishedNs) {
        if (epoch != this.epoch || epoch <= 0L || frameId <= 0L ||
                status < PRESENTED || status > UNAVAILABLE) return false;
        for (int offset = 0; offset < count; ++offset) {
            Row row = rows[(head + offset) % rows.length];
            if (row.frameId != frameId) continue;
            if (row.status != 0 || row.scans != scans || row.panelPeriodNs != panelPeriodNs)
                return false;
            row.status = status;
            row.actualNs = actualNs;
            row.supportedMask = supportedMask;
            row.renderCompleteNs = renderCompleteNs;
            row.latchNs = latchNs;
            row.startNs = startNs;
            row.gpuFinishedNs = gpuFinishedNs;
            return true;
        }
        return false;
    }

    /** Never skips an unresolved earlier swap to credit a later healthy pair. */
    public Result takeCompleted() {
        if (count == 0) return null;
        Row row = rows[head];
        if (row.status == 0) return null;
        long shaderCostUs = 0L, shaderBudgetUs = 0L;
        if (row.pairSequence > 0L) {
            int slot = (int) (row.pairSequence % shaderPairs.length);
            if (shaderPairs[slot] != row.pairSequence || shaderConsumed[slot]) return null;
            shaderCostUs = shaderCostsUs[slot];
            shaderBudgetUs = shaderBudgetsUs[slot];
            shaderConsumed[slot] = true;
        }
        rows[head] = null;
        head = (head + 1) % rows.length;
        --count;
        return evaluate(row, shaderCostUs, shaderBudgetUs);
    }

    private static Result evaluate(Row row, long costUs, long budgetUs) {
        Outcome outcome;
        String reason;
        long appMargin = 0L, compositorMargin = 0L;
        long slotToleranceNs = Math.max(1L, Math.min(row.panelPeriodNs / 4L,
                Math.max(150_000L, row.panelPeriodNs / 50L)));
        if (row.status == DROPPED) {
            outcome = Outcome.DEADLINE_MISS;
            reason = "compositor-dropped";
        } else if (row.status == UNAVAILABLE || row.actualNs <= 0L) {
            outcome = Outcome.UNKNOWN;
            reason = "physical-timestamp-unavailable";
        } else if (Math.abs(row.actualNs - row.desiredNs) > slotToleranceNs) {
            outcome = Outcome.DEADLINE_MISS;
            reason = "wrong-physical-slot";
        } else if (row.supportedMask >= 0 && (row.supportedMask & ~ALL_TIMESTAMPS) == 0 &&
                (row.supportedMask & RENDER_COMPLETE) != 0 &&
                row.renderCompleteNs > row.deadlineNs && row.renderCompleteNs <= row.actualNs) {
            outcome = Outcome.DEADLINE_MISS;
            reason = "application-rendering-completed-after-deadline";
            appMargin = row.deadlineNs - row.renderCompleteNs;
        } else if (row.supportedMask != ALL_TIMESTAMPS ||
                row.renderCompleteNs <= 0L || row.latchNs <= 0L || row.startNs <= 0L ||
                row.gpuFinishedNs < 0L || row.renderCompleteNs > row.actualNs ||
                row.latchNs > row.actualNs || row.startNs > row.actualNs ||
                row.gpuFinishedNs > row.actualNs ||
                (row.gpuFinishedNs > 0L && row.gpuFinishedNs < row.startNs)) {
            outcome = Outcome.UNKNOWN;
            reason = "optional-ready-timestamps-unavailable-or-inconsistent";
        } else {
            // All source-texture dependencies and generation draws must finish
            // before this same surface's rendering-complete timestamp. The
            // compositor timestamp adds its own work to the critical path.
            // A supported GPU-finished value of zero means display composition;
            // use its actual latch/start, never pretend a zero was a timestamp.
            long compositorReadyNs = Math.max(row.renderCompleteNs,
                    Math.max(row.latchNs, Math.max(row.startNs, row.gpuFinishedNs)));
            appMargin = row.deadlineNs - row.renderCompleteNs;
            compositorMargin = row.desiredNs - compositorReadyNs;
            long recoveryReserveNs = Math.max(1_000_000L, row.panelPeriodNs / 10L);
            if (appMargin < 0L) {
                outcome = Outcome.DEADLINE_MISS;
                reason = "application-rendering-completed-after-deadline";
            } else if (appMargin < recoveryReserveNs || compositorMargin < recoveryReserveNs) {
                outcome = Outcome.MARGINAL_HEADROOM;
                reason = "insufficient-verified-ready-margin";
            } else {
                outcome = Outcome.VERIFIED_HEADROOM;
                reason = row.gpuFinishedNs == 0L ?
                        "exact-frame-display-composition-margin" : "exact-frame-gpu-composition-margin";
            }
        }
        return new Result(row, costUs, budgetUs, outcome, reason, appMargin, compositorMargin);
    }

    public int pendingCount() { return count; }
    /** Failure-only snapshot; never use diagnostic state as admission evidence. */
    public String bindingState() {
        return "epoch=" + epoch + " lastFrameId=" + lastFrameId +
                " lastPair=" + lastPairSequence + " lastWarp=" + lastWarpSequence +
                " lastDesiredNs=" + lastDesiredNs + " pending=" + count +
                " capacity=" + rows.length;
    }
    public long evidenceEpoch() { return epoch; }
    public boolean ownsFrame(long frameId) {
        for (int offset = 0; offset < count; ++offset)
            if (rows[(head + offset) % rows.length].frameId == frameId) return true;
        return false;
    }
}
