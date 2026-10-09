package com.thorium.lucent.video;

/**
 * Selects the platform frame-timeline token for an EmuFusion-owned physical
 * presentation target.
 *
 * <p>Android's desired-present timestamp is only a not-before hint. API 33's
 * frame-timeline token additionally tells SurfaceFlinger which compositor
 * scan the transaction belongs to. Selection remains fail-closed: an absent,
 * expired, ambiguous, or materially different timeline never gets relabelled
 * as the requested output slot.</p>
 */
public final class CompositorFrameTimeline {
    /** Thor's proven physical clock/Choreographer phase error is below 30 us. */
    public static final long MAX_TARGET_ERROR_NS = 250_000L;

    public static final class Selection {
        private final long vsyncId;
        private final long expectedPresentationTimeNs;
        private final long deadlineNs;
        private final long signedTargetErrorNs;
        private final long tokenExpectedPresentationTimeNs;
        private final long targetDeadlineNs;

        private Selection(long vsyncId, long expectedPresentationTimeNs,
                          long deadlineNs, long signedTargetErrorNs) {
            this(vsyncId, expectedPresentationTimeNs, deadlineNs,
                    signedTargetErrorNs, expectedPresentationTimeNs,
                    deadlineNs);
        }

        private Selection(long vsyncId, long expectedPresentationTimeNs,
                          long deadlineNs, long signedTargetErrorNs,
                          long tokenExpectedPresentationTimeNs,
                          long targetDeadlineNs) {
            this.vsyncId = vsyncId;
            this.expectedPresentationTimeNs = expectedPresentationTimeNs;
            this.deadlineNs = deadlineNs;
            this.signedTargetErrorNs = signedTargetErrorNs;
            this.tokenExpectedPresentationTimeNs =
                    tokenExpectedPresentationTimeNs;
            this.targetDeadlineNs = targetDeadlineNs;
        }

        public long vsyncId() { return vsyncId; }
        public long expectedPresentationTimeNs() {
            return expectedPresentationTimeNs;
        }
        public long deadlineNs() { return deadlineNs; }
        public long signedTargetErrorNs() { return signedTargetErrorNs; }
    /** Expected scan owned by the token. */
        public long tokenExpectedPresentationTimeNs() {
            return tokenExpectedPresentationTimeNs;
        }
    /** Deadline carried by the target row. */
        public long targetDeadlineNs() { return targetDeadlineNs; }
    }

    /** Read-only description of the closest live candidate, even when it is
     * too far from the requested target to be selected. This is diagnostic
     * only and never relaxes {@link #MAX_TARGET_ERROR_NS}. */
    public static final class Probe {
        private final int suppliedCount;
        private final int liveCount;
        private final long vsyncId;
        private final long expectedPresentationTimeNs;
        private final long deadlineNs;
        private final long signedTargetErrorNs;

        private Probe(int suppliedCount, int liveCount, long vsyncId,
                      long expectedPresentationTimeNs, long deadlineNs,
                      long signedTargetErrorNs) {
            this.suppliedCount = suppliedCount;
            this.liveCount = liveCount;
            this.vsyncId = vsyncId;
            this.expectedPresentationTimeNs = expectedPresentationTimeNs;
            this.deadlineNs = deadlineNs;
            this.signedTargetErrorNs = signedTargetErrorNs;
        }

        public int suppliedCount() { return suppliedCount; }
        public int liveCount() { return liveCount; }
        public boolean hasLiveTimeline() { return liveCount > 0; }
        public long vsyncId() { return vsyncId; }
        public long expectedPresentationTimeNs() {
            return expectedPresentationTimeNs;
        }
        public long deadlineNs() { return deadlineNs; }
        public long signedTargetErrorNs() { return signedTargetErrorNs; }
    }

    private CompositorFrameTimeline() {}

    /**
     * Selects the exact target row only when its immutable compositor deadline
     * still retains one complete measured refresh plus the transaction handoff
     * reserve. No desired-time hint may relabel the exact target token.
     */
    public static Selection selectRefreshSafeTarget(
            long targetPresentationTimeNs, long panelPeriodNs, long nowNs,
            long[] vsyncIds, long[] expectedPresentationTimesNs,
            long[] deadlinesNs, int count) {
        if (!validArrays(targetPresentationTimeNs, panelPeriodNs, nowNs,
                vsyncIds, expectedPresentationTimesNs, deadlinesNs, count))
            return null;
        int target = closestUnique(targetPresentationTimeNs, nowNs, false,
                vsyncIds, expectedPresentationTimesNs, deadlinesNs, count);
        if (target < 0 || !hasRefreshDerivedSubmissionReserve(
                deadlinesNs[target], nowNs, panelPeriodNs)) return null;
        long expectedNs = expectedPresentationTimesNs[target];
        return new Selection(vsyncIds[target], expectedNs,
                deadlinesNs[target], expectedNs - targetPresentationTimeNs);
    }

    /**
     * Bootstrap equivalent of {@link #selectRefreshSafeTarget}: the earliest
     * unique target row with a complete refresh-safe native apply window.
     */
    public static Selection selectEarliestRefreshSafeTarget(
            long panelPeriodNs, long nowNs, long[] vsyncIds,
            long[] expectedPresentationTimesNs, long[] deadlinesNs,
            int count) {
        if (!validArrays(1L, panelPeriodNs, nowNs, vsyncIds,
                expectedPresentationTimesNs, deadlinesNs, count)) return null;
        int selected = -1;
        long earliestExpectedNs = Long.MAX_VALUE;
        boolean ambiguous = false;
        for (int index = 0; index < count; ++index) {
            if (!validRow(index, nowNs, false, vsyncIds,
                    expectedPresentationTimesNs, deadlinesNs) ||
                    !hasRefreshDerivedSubmissionReserve(
                            deadlinesNs[index], nowNs, panelPeriodNs))
                continue;
            long expectedNs = expectedPresentationTimesNs[index];
            if (expectedNs < earliestExpectedNs) {
                earliestExpectedNs = expectedNs;
                selected = index;
                ambiguous = false;
            } else if (expectedNs == earliestExpectedNs) {
                ambiguous = true;
            }
        }
        if (selected < 0 || ambiguous) return null;
        return new Selection(vsyncIds[selected],
                expectedPresentationTimesNs[selected],
                deadlinesNs[selected], 0L);
    }

    /**
     * Selects an exact target row and its immediately preceding panel row.
     *
     * <p>The preceding row is the transaction token and therefore supplies a
     * complete extra scan of compositor work. The target row remains the
     * immutable content identity. Native presentation pairs that early token
     * with the target's separate not-before timestamp, so the predecessor can
     * prepare the transaction but cannot authorize early visibility.</p>
     */
    public static Selection selectPreceding(
            long targetPresentationTimeNs, long panelPeriodNs, long nowNs,
            long[] vsyncIds, long[] expectedPresentationTimesNs,
            long[] deadlinesNs, int count) {
        if (!validArrays(targetPresentationTimeNs, panelPeriodNs, nowNs,
                vsyncIds, expectedPresentationTimesNs, deadlinesNs, count))
            return null;
        long predecessorTargetNs = targetPresentationTimeNs - panelPeriodNs;
        if (predecessorTargetNs <= 0L) return null;
        int target = closestUnique(targetPresentationTimeNs, nowNs, false,
                vsyncIds, expectedPresentationTimesNs, deadlinesNs, count);
        int predecessor = closestUnique(predecessorTargetNs, nowNs, true,
                vsyncIds, expectedPresentationTimesNs, deadlinesNs, count);
        if (target < 0 || predecessor < 0 || target == predecessor ||
                vsyncIds[target] == vsyncIds[predecessor]) return null;
        long actualPeriodNs = expectedPresentationTimesNs[target] -
                expectedPresentationTimesNs[predecessor];
        if (actualPeriodNs <= 0L ||
                absoluteDifference(actualPeriodNs, panelPeriodNs) >
                        MAX_TARGET_ERROR_NS)
            return null;
        return new Selection(vsyncIds[predecessor],
                expectedPresentationTimesNs[target],
                deadlinesNs[predecessor],
                expectedPresentationTimesNs[target] -
                        targetPresentationTimeNs,
                expectedPresentationTimesNs[predecessor],
                deadlinesNs[target]);
    }

    /**
     * Bootstrap equivalent of {@link #selectPreceding}: earliest safely
     * submittable pair.
     *
     * <p>Before the first physical-present timestamp exists, this selector
     * temporarily owns the target instead of the calibrated Java planner.
     * Physical r109 proved that accepting a predecessor with only the ordinary
     * two-millisecond handoff reserve deadlocks bootstrap: native correctly
     * rejects it because no complete refresh remains, so a physical clock can
     * never be established. Bootstrap therefore requires one measured panel
     * period plus the same handoff reserve before the predecessor deadline.</p>
     */
    public static Selection selectEarliestPreceding(
            long panelPeriodNs, long nowNs, long[] vsyncIds,
            long[] expectedPresentationTimesNs, long[] deadlinesNs,
            int count) {
        if (!validArrays(1L, panelPeriodNs, nowNs, vsyncIds,
                expectedPresentationTimesNs, deadlinesNs, count)) return null;
        int selectedPredecessor = -1;
        int selectedTarget = -1;
        long earliestTargetNs = Long.MAX_VALUE;
        boolean ambiguous = false;
        for (int predecessor = 0; predecessor < count; ++predecessor) {
            if (!validRow(predecessor, nowNs, true, vsyncIds,
                    expectedPresentationTimesNs, deadlinesNs) ||
                    !hasRefreshDerivedSubmissionReserve(
                            deadlinesNs[predecessor], nowNs, panelPeriodNs))
                continue;
            for (int target = 0; target < count; ++target) {
                if (target == predecessor ||
                        !validRow(target, nowNs, false, vsyncIds,
                                expectedPresentationTimesNs, deadlinesNs) ||
                        vsyncIds[target] == vsyncIds[predecessor]) continue;
                long periodNs = expectedPresentationTimesNs[target] -
                        expectedPresentationTimesNs[predecessor];
                if (periodNs <= 0L ||
                        absoluteDifference(periodNs, panelPeriodNs) >
                                MAX_TARGET_ERROR_NS) continue;
                long targetNs = expectedPresentationTimesNs[target];
                if (targetNs < earliestTargetNs) {
                    earliestTargetNs = targetNs;
                    selectedPredecessor = predecessor;
                    selectedTarget = target;
                    ambiguous = false;
                } else if (targetNs == earliestTargetNs) {
                    ambiguous = true;
                }
            }
        }
        if (selectedTarget < 0 || ambiguous) return null;
        return new Selection(vsyncIds[selectedPredecessor],
                expectedPresentationTimesNs[selectedTarget],
                deadlinesNs[selectedPredecessor], 0L,
                expectedPresentationTimesNs[selectedPredecessor],
                deadlinesNs[selectedTarget]);
    }

    /**
     * Returns exactly one closest live timeline within the immutable target
     * tolerance. Duplicate equally-close timelines are rejected as ambiguous.
     */
    public static Selection select(
            long targetPresentationTimeNs, long nowNs,
            long[] vsyncIds, long[] expectedPresentationTimesNs,
            long[] deadlinesNs, int count) {
        if (targetPresentationTimeNs <= 0L || nowNs < 0L ||
                vsyncIds == null || expectedPresentationTimesNs == null ||
                deadlinesNs == null || count < 1 ||
                count > vsyncIds.length ||
                count > expectedPresentationTimesNs.length ||
                count > deadlinesNs.length)
            return null;
        int selected = -1;
        long selectedError = Long.MAX_VALUE;
        boolean ambiguous = false;
        for (int index = 0; index < count; ++index) {
            long vsyncId = vsyncIds[index];
            long expectedNs = expectedPresentationTimesNs[index];
            long deadlineNs = deadlinesNs[index];
            if (vsyncId <= 0L || expectedNs <= 0L ||
                    !hasSubmissionReserve(deadlineNs, nowNs) ||
                    deadlineNs >= expectedNs)
                continue;
            long errorNs = absoluteDifference(
                    expectedNs, targetPresentationTimeNs);
            if (errorNs > MAX_TARGET_ERROR_NS) continue;
            if (errorNs < selectedError) {
                selected = index;
                selectedError = errorNs;
                ambiguous = false;
            } else if (errorNs == selectedError) {
                ambiguous = true;
            }
        }
        if (selected < 0 || ambiguous) return null;
        long expectedNs = expectedPresentationTimesNs[selected];
        return new Selection(vsyncIds[selected], expectedNs,
                deadlinesNs[selected], expectedNs - targetPresentationTimeNs);
    }

    /**
     * Selects the earliest structurally valid timeline whose compositor
     * deadline is still live.
     *
     * <p>This is deliberately separate from {@link #select}. It is used only
     * to bootstrap an external physical clock before EmuFusion owns a measured
     * display-phase anchor. The selected expected-present time becomes that
     * first physical target; it is never used to relabel an independently
     * planned target. Once the clock exists, callers must return to the strict
     * bounded selector above.</p>
     */
    public static Selection selectEarliestLive(
            long nowNs, long[] vsyncIds,
            long[] expectedPresentationTimesNs, long[] deadlinesNs,
            int count) {
        if (nowNs < 0L || vsyncIds == null ||
                expectedPresentationTimesNs == null || deadlinesNs == null ||
                count < 1 || count > vsyncIds.length ||
                count > expectedPresentationTimesNs.length ||
                count > deadlinesNs.length)
            return null;
        int selected = -1;
        long earliestExpectedNs = Long.MAX_VALUE;
        boolean ambiguous = false;
        for (int index = 0; index < count; ++index) {
            long vsyncId = vsyncIds[index];
            long expectedNs = expectedPresentationTimesNs[index];
            long deadlineNs = deadlinesNs[index];
            if (vsyncId <= 0L || expectedNs <= 0L ||
                    !hasSubmissionReserve(deadlineNs, nowNs) ||
                    deadlineNs >= expectedNs)
                continue;
            if (expectedNs < earliestExpectedNs) {
                selected = index;
                earliestExpectedNs = expectedNs;
                ambiguous = false;
            } else if (expectedNs == earliestExpectedNs) {
                ambiguous = true;
            }
        }
        if (selected < 0 || ambiguous) return null;
        return new Selection(vsyncIds[selected],
                expectedPresentationTimesNs[selected],
                deadlinesNs[selected], 0L);
    }

    /**
     * Finds the closest structurally valid, unexpired candidate without
     * applying the selection tolerance. Callers may log the result, but must
     * still use {@link #select} to authorize a presentation.
     */
    public static Probe probe(
            long targetPresentationTimeNs, long nowNs,
            long[] vsyncIds, long[] expectedPresentationTimesNs,
            long[] deadlinesNs, int count) {
        if (targetPresentationTimeNs <= 0L || nowNs < 0L ||
                vsyncIds == null || expectedPresentationTimesNs == null ||
                deadlinesNs == null || count < 0 ||
                count > vsyncIds.length ||
                count > expectedPresentationTimesNs.length ||
                count > deadlinesNs.length)
            return new Probe(0, 0, 0L, 0L, 0L, 0L);
        int selected = -1;
        int liveCount = 0;
        long selectedError = Long.MAX_VALUE;
        for (int index = 0; index < count; ++index) {
            long vsyncId = vsyncIds[index];
            long expectedNs = expectedPresentationTimesNs[index];
            long deadlineNs = deadlinesNs[index];
            if (vsyncId <= 0L || expectedNs <= 0L || deadlineNs <= nowNs ||
                    deadlineNs >= expectedNs)
                continue;
            ++liveCount;
            long errorNs = absoluteDifference(
                    expectedNs, targetPresentationTimeNs);
            if (errorNs < selectedError) {
                selected = index;
                selectedError = errorNs;
            }
        }
        if (selected < 0) return new Probe(count, liveCount,
                0L, 0L, 0L, 0L);
        long expectedNs = expectedPresentationTimesNs[selected];
        return new Probe(count, liveCount, vsyncIds[selected], expectedNs,
                deadlinesNs[selected], expectedNs - targetPresentationTimeNs);
    }

    private static long absoluteDifference(long left, long right) {
        if (left >= right) return left - right;
        return right - left;
    }

    private static boolean validArrays(
            long targetNs, long panelPeriodNs, long nowNs,
            long[] vsyncIds, long[] expectedNs, long[] deadlinesNs,
            int count) {
        return targetNs > 0L && panelPeriodNs > 0L && nowNs >= 0L &&
                vsyncIds != null && expectedNs != null &&
                deadlinesNs != null && count >= 2 &&
                count <= vsyncIds.length && count <= expectedNs.length &&
                count <= deadlinesNs.length;
    }

    private static boolean validRow(
            int index, long nowNs, boolean needsSubmissionReserve,
            long[] vsyncIds, long[] expectedNs, long[] deadlinesNs) {
        if (vsyncIds[index] <= 0L || expectedNs[index] <= 0L ||
                deadlinesNs[index] <= nowNs ||
                deadlinesNs[index] >= expectedNs[index]) return false;
        return !needsSubmissionReserve ||
                hasSubmissionReserve(deadlinesNs[index], nowNs);
    }

    /** Returns -1 for absent and -2 for an equally-close ambiguity. */
    private static int closestUnique(
            long targetNs, long nowNs, boolean needsSubmissionReserve,
            long[] vsyncIds, long[] expectedNs, long[] deadlinesNs,
            int count) {
        int selected = -1;
        long selectedError = Long.MAX_VALUE;
        boolean ambiguous = false;
        for (int index = 0; index < count; ++index) {
            if (!validRow(index, nowNs, needsSubmissionReserve, vsyncIds,
                    expectedNs, deadlinesNs)) continue;
            long errorNs = absoluteDifference(expectedNs[index], targetNs);
            if (errorNs > MAX_TARGET_ERROR_NS) continue;
            if (errorNs < selectedError) {
                selected = index;
                selectedError = errorNs;
                ambiguous = false;
            } else if (errorNs == selectedError) {
                ambiguous = true;
            }
        }
        return ambiguous ? -2 : selected;
    }

    private static boolean hasSubmissionReserve(long deadlineNs, long nowNs) {
        return deadlineNs > nowNs &&
                deadlineNs - nowNs >=
                        PhysicalPresentationDeadline.
                                THOR_COMPOSITOR_SUBMISSION_RESERVE_NS;
    }

    private static boolean hasRefreshDerivedSubmissionReserve(
            long deadlineNs, long nowNs, long panelPeriodNs) {
        if (deadlineNs <= nowNs || panelPeriodNs <= 0L ||
                panelPeriodNs > Long.MAX_VALUE -
                        PhysicalPresentationDeadline.
                                THOR_COMPOSITOR_SUBMISSION_RESERVE_NS)
            return false;
        return deadlineNs - nowNs >= panelPeriodNs +
                PhysicalPresentationDeadline.
                        THOR_COMPOSITOR_SUBMISSION_RESERVE_NS;
    }
}
