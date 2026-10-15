package com.thorium.emufusion.video;

/**
 * Chooses, for each panel callback, what the built-in frame generator shows:
 * the retained left image, an image generated between left and right, or the
 * right image (after which the renderer rotates its pair).
 *
 * <p>Output frames sit on a fixed lattice of the output period. Each output
 * slot maps to one source time on a single continuous timeline anchored when
 * the first pair is shown; the generated image's position between its two real
 * images is that source time's fraction of their actual timestamp span. This
 * replaces the exact one-midpoint lattice, which treated any held source frame
 * (a game showing the same image twice) as a break: it dropped the timeline
 * and re-primed, leaving several empty output slots each time -- most of the
 * remaining visible gaps on the Thor (2026-10-11). Here a pair may span up to
 * {@code maxBridgePeriods} source periods and is filled evenly, any multiplier
 * (x2, x3) falls out of the output period, and a late producer only holds the
 * current image instead of restarting.</p>
 *
 * <p>Lateness is judged against the spans the pairs actually have, not the
 * nominal source rate: a 30 fps game delivered in a 60 Hz stream, or one whose
 * tier is not known yet, is not late every frame. When the successor really is
 * overdue the timeline stops just short of it, so it shows the moment it
 * arrives and playback continues at normal speed from there. Latency gained
 * that way is trimmed back gently (a few percent faster for a moment) once
 * frames queue up behind the pair, instead of growing until the queue
 * overflows and forces a restart.</p>
 *
 * <p>Pure Java; the renderer supplies the active pair and commits each
 * decision after its swap. One decision is pending at a time.</p>
 */
public final class TimelineFrameScheduler {
    public static final int NONE = 0;
    public static final int REAL_LEFT = 1;
    public static final int GENERATED = 2;
    public static final int REAL_RIGHT = 3;

    /** Pairs spanning more source periods than this are a pause, not motion. */
    public static final double DEFAULT_MAX_BRIDGE_PERIODS = 4.0;
    /**
     * How far a source clock may sit from an exact panel divisor and still be
     * planned on it. At 0.5% the occasional pair that gets one output more or
     * less comes no more than every couple of seconds.
     */
    public static final double PLAN_RELATIVE_TOLERANCE = 0.005;
    /**
     * When a pair does not span a whole number of outputs (a 55 fps source
     * on a 120 Hz output), a real image is shown only if an output lands
     * within this fraction of an output period of its timestamp. Showing
     * every real image instead puts some of them up to half a period off
     * their time (uneven motion steps of up to +-50%); passing such an image
     * shows its moment of the next pair instead.
     */
    public static final long REAL_SNAP_DIVISOR = 4L;
    /** Frames queued beyond the steady depth before latency is trimmed. */
    public static final int TRIM_EXCESS_QUEUED = 2;
    /**
     * Callbacks the excess must persist for before trimming starts (~0.25 s
     * at 120 Hz). A producer that delivers in bursts (Cemu: two images
     * back to back, then a gap) queues extra images only momentarily; trimming
     * on each burst left the timeline at the newest image, so the next gap
     * made its successor late (Thor, Super Mario 3D World: 154 trims, 119
     * late-successor holds, 59 re-anchors in 20 s).
     */
    public static final int TRIM_PERSISTENCE_CALLBACKS = 30;
    // Each trimmed output advances the timeline this fraction of an output
    // period early: 1/16 = 6% faster, invisible, ~0.5 s per 33 ms excess.
    private static final long TRIM_DIVISOR = 16L;

    private int trimExcessQueued = TRIM_EXCESS_QUEUED;

    /** Queued images beyond the steady depth that start trimming (default {@link #TRIM_EXCESS_QUEUED}). */
    public void setTrimExcessQueued(int images) { trimExcessQueued = Math.max(1, images); }

    private long outputPeriodNs;
    private long sourcePeriodNs;
    private double maxBridgePeriods = DEFAULT_MAX_BRIDGE_PERIODS;

    private boolean primed;
    private long anchorDisplayNs;
    private long anchorSourceNs;
    private long lastSlot = Long.MIN_VALUE;
    // Typical span of a pair as delivered (EWMA of committed pairs).
    private long expectedSpanNs;
    private int consecutiveLongSpans;
    // Midpoints lost because the successor arrived after them but before its
    // own slot: a source drifting late against its timestamps sits there
    // pair after pair without ever forcing a re-anchor.
    private boolean midpointLostThisPair;
    // A real image shown off its time because its successor was not queued
    // yet when this pair could have passed it.
    private boolean passBlockedThisPair;
    private int consecutivePassBlockedPairs;
    private int consecutiveLatePairs;
    private int pairsSinceGenerated = Integer.MAX_VALUE / 2;
    private long slackSteps;
    // What the panel currently shows, so an unchanged hold needs no swap.
    private long shownSequence;
    private long shownTargetNs = Long.MIN_VALUE;

    private int pendingKind = NONE;
    // A generated output after which the pair advances without showing its
    // right image (no output lands near it; the successor is queued).
    private boolean pendingPassRight;
    private long pendingIdealNs;
    private float pendingPhase;
    private long pendingTargetNs;
    private long pendingSlot;
    private long pendingSequence;
    private boolean pendingPrime;
    private long pendingAnchorDisplayNs;
    private long pendingAnchorSourceNs;
    private long pendingSpanNs;

    private long reanchors;
    // Pair readiness (3.2.87; owner 2026-10-15: latency is the biggest
    // problem). For each pair the timeline notes the first callback that
    // wanted its right image (a generated output, or a hold because the image
    // was not there) and compares it with when the renderer admitted that
    // image: positive, the image waited; negative, the pair was late. When
    // every one of the last READY_WINDOW pairs waited, that wait is latency
    // the source does not need and comes off; a late pair puts back what it
    // lacked. Pairs spanning whole outputs move by whole output periods (one
    // generated step skipped once, phases stay k/n; gradual steps held a slot
    // in each pair while trimming); others by small steps. LSFG-Android shows
    // a pair's first generated image as soon as it is computed; this reaches
    // the same and keeps the even steps. Before, slack added for a late or
    // long pair came off only while frames queued up, which a 20 fps game
    // never does: Ocarina of Time showed real frames 74 ms after arrival.
    public static final int READY_WINDOW = 16;
    // Late pairs the window tolerates before it keeps (or puts back) slack:
    // one in sixteen holds a generated step rather than every pair paying
    // the longest span's latency (QA: setReadyToleratedLate).
    public static final int READY_TOLERATED_LATE = 1;
    private int readyToleratedLate = READY_TOLERATED_LATE;
    public static final long READY_TRIM_DIVISOR = 8L;
    private final long[] readySlackNs = new long[READY_WINDOW];
    private int readySlackCount, readySlackNext;
    private boolean readyTrimEnabled = true;
    private long readyTrims, readySlackAdds;
    private long rightReadyNs;
    private long needLeftSequence;
    private long needNs;
    private boolean needReported;
    private long lastReadyWaitNs;
    // Consecutive successor-late callbacks before the image arrived, bucketed
    // 1 / 2 / 3+ callbacks: how late successors are, in output slots.
    private int lateStreak;
    private final long[] lateStreaks = new long[3];
    // Latest admission lag the source has shown (stamp to renderer, same
    // clock offset as the display/target comparison), or MIN_VALUE when the
    // owner does not know it; trims keep the latency above it.
    private long requiredLatencyNs = Long.MIN_VALUE;
    private long trimsHeld;
    private long passedReals;
    private int excessCallbacks;
    private long timingSamples;
    private double timingErrorSquares;
    private long timingErrorMaxNs;
    private long motionNotReadyHolds;
    private long successorLateHolds;
    private long pauseHolds;
    private long trims;
    private long generated;
    private long real;
    private String lastHoldReason = "none";

    /**
     * @param outputPeriodNs time between output frames (panel period x scans
     *        per output); zero disables the scheduler.
     * @param sourcePeriodNs the paced source frame period.
     */
    public void configure(long outputPeriodNs, long sourcePeriodNs) {
        long source = Math.max(0L, sourcePeriodNs);
        if (outputPeriodNs == this.outputPeriodNs) {
            // The measured source clock wobbles (29.98 / 30.04) without
            // changing the output lattice; it only bounds pairs, so follow it
            // without restarting the timeline.
            this.sourcePeriodNs = source;
            return;
        }
        this.outputPeriodNs = Math.max(0L, outputPeriodNs);
        this.sourcePeriodNs = source;
        reset();
    }

    public void setMaxBridgePeriods(double periods) {
        maxBridgePeriods = Double.isFinite(periods) && periods >= 1.0 ? periods : DEFAULT_MAX_BRIDGE_PERIODS;
    }

    /** Drops the timeline (pair invalidated, plan changed); the next pair re-anchors it. */
    public void reset() {
        primed = false;
        lastSlot = Long.MIN_VALUE;
        expectedSpanNs = sourcePeriodNs;
        consecutiveLongSpans = 0;
        midpointLostThisPair = false;
        consecutiveLatePairs = 0;
        passBlockedThisPair = false;
        consecutivePassBlockedPairs = 0;
        excessCallbacks = 0;
        pairsSinceGenerated = Integer.MAX_VALUE / 2;
        if (lateStreak > 0) ++lateStreaks[Math.min(lateStreak, 3) - 1];
        lateStreak = 0;
        shownSequence = 0L;
        shownTargetNs = Long.MIN_VALUE;
        readySlackCount = 0;
        readySlackNext = 0;
        lastReadyWaitNs = 0L;
        needLeftSequence = 0L;
        needNs = 0L;
        needReported = false;
        clearPending();
    }

    /** QA: false keeps added latency until frames queue up (before 3.2.87). */
    public void setReadyTrimEnabled(boolean value) { readyTrimEnabled = value; }

    /** When the renderer admitted the current right image (zero when unknown). */
    public void setRightReadyNs(long admittedNs) { rightReadyNs = admittedNs; }

    private void observeReadySlack(long slackNs) {
        readySlackNs[readySlackNext] = slackNs;
        readySlackNext = (readySlackNext + 1) % READY_WINDOW;
        readySlackCount = Math.min(READY_WINDOW, readySlackCount + 1);
        lastReadyWaitNs = slackNs;
    }

    /** Once per pair, when its right image is known: how long it waited. */
    private void reportPairReadiness() {
        if (needReported || needNs == 0L || rightReadyNs <= 0L) return;
        needReported = true;
        observeReadySlack(needNs - rightReadyNs);
    }

    /** QA: late pairs per window tolerated (0: the longest span sets the latency). */
    public void setReadyToleratedLate(int pairs) {
        readyToleratedLate = Math.max(0, Math.min(READY_WINDOW / 4, pairs));
    }

    /** The recent waits' (tolerated+1)-th smallest: every pair but the tolerated ones waited this long. */
    private long readyQuantileNs() {
        long[] sorted = java.util.Arrays.copyOf(readySlackNs, readySlackCount);
        java.util.Arrays.sort(sorted);
        return sorted[Math.min(readyToleratedLate, readySlackCount - 1)];
    }

    /** The wait recent pairs could do without, or zero while unknown or disabled. */
    private long readyExcessNs() {
        if (!readyTrimEnabled || readySlackCount < READY_WINDOW || outputPeriodNs <= 0L) return 0L;
        return Math.max(0L, readyQuantileNs());
    }

    /** This slot's readiness trim: a whole output, a small step, or none. */
    private long readyTrimStepNs(long leftTimestampNs, long rightTimestampNs) {
        long wait = readyExcessNs();
        if (wait <= 0L) return 0L;
        // The renderer admits images before it selects, so an image admitted at
        // a callback can be that callback's output: a whole period of wait
        // (less the admission's own time in the callback) is removable.
        if (wholeOutputs(rightTimestampNs - leftTimestampNs))
            return wait >= outputPeriodNs - outputPeriodNs / READY_TRIM_DIVISOR ? outputPeriodNs : 0L;
        return Math.min(Math.max(0L, wait - outputPeriodNs / 2L),
                Math.max(1L, outputPeriodNs / READY_TRIM_DIVISOR));
    }

    /** The slack late pairs lacked beyond the tolerated ones (whole outputs where pairs span them). */
    private long readySlackToAddNs(long leftTimestampNs, long rightTimestampNs) {
        if (!readyTrimEnabled || outputPeriodNs <= 0L || lastReadyWaitNs >= 0L || readySlackCount == 0)
            return 0L;
        // Recorded waits shift with every latency change, so a late pair that
        // was already put back no longer counts as late.
        long late = -readyQuantileNs();
        if (late <= outputPeriodNs / READY_TRIM_DIVISOR) return 0L;
        if (wholeOutputs(rightTimestampNs - leftTimestampNs))
            return (late + outputPeriodNs - 1L) / outputPeriodNs * outputPeriodNs;
        return late + outputPeriodNs / READY_TRIM_DIVISOR;
    }

    /** The recorded waits after the timeline's latency changes by deltaNs. */
    private void shiftReadySlack(long deltaNs) {
        for (int i = 0; i < readySlackCount; ++i) readySlackNs[i] += deltaNs;
        lastReadyWaitNs += deltaNs;
        // A pair still waiting for its image needs it that much later too.
        if (needNs != 0L && !needReported) needNs += deltaNs;
    }

    /** Whether two retained images may form one pair for this timeline. */
    public boolean pairSpanAllowed(long leftTimestampNs, long rightTimestampNs) {
        if (leftTimestampNs <= 0L || rightTimestampNs <= leftTimestampNs) return false;
        if (sourcePeriodNs <= 0L) return true;
        return rightTimestampNs - leftTimestampNs <= maxBridgeNs();
    }

    private long maxBridgeNs() {
        return (long) Math.ceil(sourcePeriodNs * (maxBridgePeriods + 0.5));
    }

    /**
     * Decides this callback's output.
     *
     * @param displayNs the physical time this callback's frame will be shown.
     * @param rightSequence zero when the successor image is not retained yet.
     */
    public int select(long displayNs, long leftSequence, long leftTimestampNs,
                      long rightSequence, long rightTimestampNs, boolean motionReady) {
        return select(displayNs, leftSequence, leftTimestampNs, rightSequence,
                rightTimestampNs, motionReady, 0);
    }

    /**
     * @param excessQueued source frames waiting beyond the right image, minus
     *        the renderer's steady queue depth; latency is trimmed while this
     *        is at least {@link #TRIM_EXCESS_QUEUED}.
     */
    public int select(long displayNs, long leftSequence, long leftTimestampNs,
                      long rightSequence, long rightTimestampNs, boolean motionReady,
                      int excessQueued) {
        return decide(displayNs, leftSequence, leftTimestampNs, rightSequence,
                rightTimestampNs, motionReady, excessQueued, false, false);
    }

    /**
     * @param successorQueued whether the image after the right one is
     *        already waiting, so the pair can advance after a generated output
     *        without showing its right image.
     */
    public int select(long displayNs, long leftSequence, long leftTimestampNs,
                      long rightSequence, long rightTimestampNs, boolean motionReady,
                      int excessQueued, boolean successorQueued) {
        return decide(displayNs, leftSequence, leftTimestampNs, rightSequence,
                rightTimestampNs, motionReady, excessQueued, true, successorQueued);
    }

    private int decide(long displayNs, long leftSequence, long leftTimestampNs,
                       long rightSequence, long rightTimestampNs, boolean motionReady,
                       int excessQueued, boolean passing, boolean successorQueued) {
        clearPending();
        if (outputPeriodNs <= 0L || leftSequence <= 0L || leftTimestampNs <= 0L) return NONE;
        boolean hasRight = rightSequence > 0L && rightTimestampNs > leftTimestampNs;
        if (!primed) {
            // Show the real left image now. The timeline starts from it once a
            // successor exists, so generation has a pair to work with; if left
            // is already on screen, showing it once more (identical pixels)
            // anchors the timeline at this callback.
            if (!hasRight && shownSequence == leftSequence && shownTargetNs == leftTimestampNs)
                return NONE;
            return propose(REAL_LEFT, 0f, leftTimestampNs, 0L, leftSequence,
                    hasRight, displayNs, leftTimestampNs);
        }
        // A slot is due once its time has come (a quarter period early covers
        // callback jitter); rounding would show multi-scan outputs a scan early.
        long slot = Math.floorDiv(displayNs - anchorDisplayNs + outputPeriodNs / 4L, outputPeriodNs);
        if (slot <= lastSlot) return NONE;  // this output slot is already shown
        if (leftSequence != needLeftSequence) {
            needLeftSequence = leftSequence;
            needNs = 0L;
            needReported = false;
        }
        if (hasRight) {
            reportPairReadiness();
            long add = readySlackToAddNs(leftTimestampNs, rightTimestampNs);
            if (add > 0L) {
                anchorSourceNs -= add;
                shiftReadySlack(add);
                ++readySlackAdds;
            }
        }
        if (hasRight && lateStreak > 0) {
            ++lateStreaks[Math.min(lateStreak, 3) - 1];
            lateStreak = 0;
        }
        excessCallbacks = hasRight && excessQueued >= trimExcessQueued ? excessCallbacks + 1 : 0;
        if (excessCallbacks >= TRIM_PERSISTENCE_CALLBACKS) {
            // Never trim into the lateness the source has shown: images that
            // reach the renderer 35-90 ms after their stamps (Cemu) queued up
            // between slow ones, trims removed the slack, and the next slow
            // image was late for its slot again (SM3DW, 60 re-anchors in 35 s).
            long latencyNs = displayNs - (anchorSourceNs + slot * outputPeriodNs);
            if (requiredLatencyNs == Long.MIN_VALUE ||
                    latencyNs - outputPeriodNs > requiredLatencyNs) {
                long step = Math.max(1L, outputPeriodNs / TRIM_DIVISOR);
                anchorSourceNs += step;
                shiftReadySlack(-step);
                ++trims;
            } else {
                ++trimsHeld;
            }
        }
        long readyStep = hasRight ? readyTrimStepNs(leftTimestampNs, rightTimestampNs) : 0L;
        if (readyStep > 0L) {
            long step = readyStep;
            anchorSourceNs += step;
            shiftReadySlack(-step);
            ++readyTrims;
        }
        long target = anchorSourceNs + slot * outputPeriodNs;
        long tolerance = outputPeriodNs / 2L;
        // Narrow the snap to real images only where outputs drift across the
        // pair (non-integer cadence) and the pair can advance past an image.
        boolean drifting = passing && hasRight &&
                !wholeOutputs(rightTimestampNs - leftTimestampNs);
        boolean passable = drifting && successorQueued;
        long realTolerance = passable ? outputPeriodNs / REAL_SNAP_DIVISOR : tolerance;
        // Generating a small step into the pair needs only the pair itself.
        long leftTolerance = drifting ? outputPeriodNs / REAL_SNAP_DIVISOR : tolerance;
        pendingIdealNs = target;
        if (hasRight && target >= rightTimestampNs - realTolerance) {
            ++real;
            int kind = propose(REAL_RIGHT, 1f, rightTimestampNs, slot, rightSequence, false, 0L, 0L);
            pendingSpanNs = rightTimestampNs - leftTimestampNs;
            return kind;
        }
        if (target <= leftTimestampNs + leftTolerance) {
            if (shownSequence == leftSequence && shownTargetNs == leftTimestampNs) {
                lastSlot = slot;
                return NONE;
            }
            ++real;
            return propose(REAL_LEFT, 0f, leftTimestampNs, slot, leftSequence, false, 0L, 0L);
        }
        if (!hasRight) {
            if (needNs == 0L) needNs = displayNs;
            ++lateStreak;
            // The next image is not here yet: hold the left one. Once the
            // timeline reaches the point where it would be due, stop just
            // short of it (a re-anchor, never a re-prime) so it shows the
            // moment it arrives and motion resumes at normal speed.
            ++successorLateHolds;
            lastHoldReason = "successor-late";
            long dueNs = leftTimestampNs + Math.max(expectedSpanNs, outputPeriodNs) - tolerance;
            if (target < dueNs) midpointLostThisPair = true;
            if (target >= dueNs) {
                // Stop one output period short of it, not just short: a
                // source whose frames drift later than their timestamps (3DS
                // under load) otherwise arrives exactly on time for its real
                // slot every pair, never in time for the midpoint, and
                // generation stops (2026-10-11). Queued frames trim it back.
                long added = target - dueNs + 1L + outputPeriodNs;
                anchorSourceNs -= added;
                shiftReadySlack(added);
                ++reanchors;
            }
            lastSlot = slot;
            return NONE;
        }
        long span = rightTimestampNs - leftTimestampNs;
        if (sourcePeriodNs > 0L && span > maxBridgeNs()) {
            // A pause or load: show the left image until the right one is due.
            ++pauseHolds;
            lastHoldReason = "pause";
            lastSlot = slot;
            return NONE;
        }
        if (!motionReady) {
            ++motionNotReadyHolds;
            lastHoldReason = "motion-not-ready";
            lastSlot = slot;
            return NONE;
        }
        double fraction = (double) (target - leftTimestampNs) / (double) span;
        // When the pair spans a whole number of output periods the in-between
        // positions are exact k/n by construction; snap measurement noise so
        // motion steps stay even (0.25/0.5/0.75, never 0.27/0.49/0.78).
        double outputs = (double) span / (double) outputPeriodNs;
        long n = Math.round(outputs);
        if (n >= 2L && n <= 12L && Math.abs(outputs - n) <= 0.05 * n) {
            long k = Math.round(fraction * n);
            if (k >= 1L && k <= n - 1L) fraction = (double) k / (double) n;
        }
        if (!(fraction > 0.0 && fraction < 1.0)) return NONE;
        if (needNs == 0L) {
            needNs = displayNs;
            reportPairReadiness();
        }
        long selected = leftTimestampNs + Math.round(fraction * span);
        ++generated;
        int kind = propose(GENERATED, (float) fraction, selected, slot, leftSequence, false, 0L, 0L);
        pendingIdealNs = target;
        if (drifting && !successorQueued &&
                target + outputPeriodNs > rightTimestampNs + outputPeriodNs / REAL_SNAP_DIVISOR)
            passBlockedThisPair = true;
        if (passable && target + outputPeriodNs > rightTimestampNs + realTolerance) {
            // The next output lands past the right image by more than the
            // snap: show its own moment of the next pair rather than this
            // image late.
            pendingPassRight = true;
            pendingSpanNs = span;
        }
        return kind;
    }

    /** Whether a pair spans (within 5%) a whole number of outputs. */
    private boolean wholeOutputs(long spanNs) {
        if (outputPeriodNs <= 0L || spanNs <= 0L) return true;
        double outputs = (double) spanNs / (double) outputPeriodNs;
        long n = Math.round(outputs);
        return n >= 1L && n <= 12L && Math.abs(outputs - n) <= 0.05 * n;
    }

    private int propose(int kind, float phase, long targetNs, long slot, long sequence,
                        boolean prime, long anchorDisplayNs, long anchorSourceNs) {
        pendingKind = kind;
        pendingPhase = phase;
        pendingTargetNs = targetNs;
        pendingSlot = slot;
        pendingSequence = sequence;
        pendingPrime = prime;
        pendingAnchorDisplayNs = anchorDisplayNs;
        pendingAnchorSourceNs = anchorSourceNs;
        pendingSpanNs = 0L;
        pendingPassRight = false;
        return kind;
    }

    /** Applies the pending decision after its swap; a failed swap consumes the slot. */
    public void commit(boolean swapSucceeded) {
        if (pendingKind == NONE) return;
        if (pendingPrime) {
            if (swapSucceeded) {
                primed = true;
                anchorDisplayNs = pendingAnchorDisplayNs;
                anchorSourceNs = pendingAnchorSourceNs;
                lastSlot = 0L;
            }
        } else if (primed) {
            lastSlot = Math.max(lastSlot, pendingSlot);
        }
        if (swapSucceeded) {
            shownSequence = pendingKind == GENERATED ? 0L : pendingSequence;
            shownTargetNs = pendingTargetNs;
            if (primed && !pendingPrime) {
                long error = Math.abs(pendingTargetNs - pendingIdealNs);
                ++timingSamples;
                timingErrorSquares += (double) error * (double) error;
                timingErrorMaxNs = Math.max(timingErrorMaxNs, error);
            }
            if (pendingPassRight) ++passedReals;
        }
        if (swapSucceeded && pendingKind == GENERATED) pairsSinceGenerated = 0;
        if (swapSucceeded && (pendingKind == REAL_RIGHT || pendingPassRight)) {
            consecutiveLatePairs = midpointLostThisPair ? consecutiveLatePairs + 1 : 0;
            midpointLostThisPair = false;
            consecutivePassBlockedPairs = passBlockedThisPair ? consecutivePassBlockedPairs + 1 : 0;
            passBlockedThisPair = false;
            if (consecutivePassBlockedPairs >= 2 && primed && !readyTrimEnabled) {
                // Two pairs in a row could not pass a real image that no
                // output lands near because its successor was not queued yet:
                // one more output period of slack (trimmed later if frames
                // queue up) so the successor is there in time.
                anchorSourceNs -= outputPeriodNs;
                shiftReadySlack(outputPeriodNs);
                consecutivePassBlockedPairs = 0;
                ++slackSteps;
            }
            if (pairsSinceGenerated < Integer.MAX_VALUE / 2) ++pairsSinceGenerated;
            if (consecutiveLatePairs >= 2 && pairsSinceGenerated <= 4 && primed && !readyTrimEnabled) {
                // Generation was running and two pairs in a row lost their
                // midpoint to a late successor: give the timeline one more
                // output period of slack (trimmed later if frames queue up).
                anchorSourceNs -= outputPeriodNs;
                shiftReadySlack(outputPeriodNs);
                consecutiveLatePairs = 0;
                ++slackSteps;
            }
        }
        if (pendingSpanNs > 0L) {
            long span = Math.min(pendingSpanNs, sourcePeriodNs > 0L ? maxBridgeNs() : pendingSpanNs);
            boolean longSpan = expectedSpanNs > 0L &&
                    span > expectedSpanNs + expectedSpanNs * 3L / 4L;
            consecutiveLongSpans = longSpan ? consecutiveLongSpans + 1 : 0;
            if (expectedSpanNs <= 0L) expectedSpanNs = span;
            // One long span is a hitch, not a new rate: let it barely move the
            // estimate, so the pairs after a stall are not judged against an
            // inflated span. Two in a row are a new rate (60 -> 30): follow it.
            else if (longSpan && consecutiveLongSpans < 2)
                expectedSpanNs = (15L * expectedSpanNs + span) / 16L;
            else if (longSpan) expectedSpanNs = (expectedSpanNs + span) / 2L;
            else expectedSpanNs = (3L * expectedSpanNs + span) / 4L;
        }
        clearPending();
    }

    public void abort() { clearPending(); }

    private void clearPending() {
        pendingKind = NONE;
        pendingPhase = 0f;
        pendingTargetNs = 0L;
        pendingSlot = 0L;
        pendingSequence = 0L;
        pendingPrime = false;
        pendingSpanNs = 0L;
        pendingPassRight = false;
        pendingIdealNs = 0L;
    }

    public int pendingKind() { return pendingKind; }
    public float pendingPhase() { return pendingPhase; }
    public long pendingTargetNs() { return pendingTargetNs; }
    /** One when the pending decision shows the right image and rotates the pair. */
    public int pendingAdvance() { return pendingKind == REAL_RIGHT || pendingPassRight ? 1 : 0; }
    public boolean primed() { return primed; }
    public long expectedSpanNs() { return expectedSpanNs; }
    public long outputPeriodNs() { return outputPeriodNs; }

    /**
     * The latency (display time minus shown source time) the source needs so
     * the image after the shown one has arrived by its slot: the recent
     * maximum of (arrival time - stamp). Long.MIN_VALUE when unknown.
     */
    public void setRequiredLatencyNs(long value) { requiredLatencyNs = value; }

    public String diagnostics() {
        return "timelineGenerated=" + generated + " timelineReal=" + real +
                " timelineReanchors=" + reanchors +
                " timelineMotionNotReady=" + motionNotReadyHolds +
                " timelineSuccessorLate=" + successorLateHolds +
                " timelinePauseHolds=" + pauseHolds +
                " timelineTrims=" + trims +
                " timelineTrimsHeld=" + trimsHeld +
                " timelineReadyTrims=" + readyTrims +
                " timelineReadyAdds=" + readySlackAdds +
                " timelineReadyExcessUs=" + readyExcessNs() / 1000L +
                " timelineLastReadyWaitUs=" + lastReadyWaitNs / 1000L +
                " timelineSlackSteps=" + slackSteps +
                " timelineExpectedSpanUs=" + expectedSpanNs / 1000L +
                " timelinePassedReals=" + passedReals +
                " timelineTimingErrRmsUs=" + (timingSamples > 0L ?
                        Math.round(Math.sqrt(timingErrorSquares / timingSamples) / 1000.0) : 0L) +
                " timelineTimingErrMaxUs=" + timingErrorMaxNs / 1000L +
                " timelineLateStreaks=" + lateStreaks[0] + "/" + lateStreaks[1] + "/" + lateStreaks[2] +
                " timelineLastHold=" + lastHoldReason;
    }
}
