package com.thorium.emufusion.video;

/**
 * When to skip one built-in present so the compositor's queue catches up.
 *
 * <p>The compositor takes one buffer per composition and never drops a queued
 * one, so after a single frame is shown a scan late (its rendering finished
 * after its slot) every later frame is shown a scan after the slot it asked
 * for, evenly, for as long as frames keep coming: Double Dash on the 3.2.108
 * trial, 820 frames in a row at 19.6 ms from arrival to screen against 11.2 ms
 * before the late frame. Not presenting at one callback empties the queue, and
 * the next frame lands in its own slot (the viewer sees one intermediate
 * skipped, like a missed callback).</p>
 *
 * <p>Asked after {@link #BACKLOG_FRAMES} frames in a row shown one scan late;
 * then not again for {@link #MIN_HOLDOFF_NS}. A skip that does not clear the
 * backlog within {@link #JUDGE_FRAMES} frames means the compositor is holding
 * frames to the later scan itself, and a backlog that forms again within
 * {@link #REFORM_NS} of a skip means renders keep finishing after their slot
 * at this lead (Double Dash: a skip every 2 s, 45% of frames late): either
 * doubles the hold-off, up to {@link #MAX_HOLDOFF_NS}, so the session settles
 * a scan behind -- the latency it had before, but smooth. A backlog more than
 * four hold-offs after the last skip starts again from the minimum.</p>
 *
 * <p>The skip is itself a visible hitch (a frame shown two scans), so since
 * 3.2.112 (owner, 2026-10-26: "these micro stutters have got to go") a
 * backlog must last a second before it is skipped, and skips are at least
 * 16 s apart (was 0.2 s and 2 s: three skips in 16 s in a Double Dash
 * session). A shorter backlog is a scan of latency, shown evenly.</p>
 *
 * <p>Since 3.2.151 a skip is also timed by what it would repeat. Each pair's
 * changed share ({@link #observeChange}: samples of a 160x90 grid where the
 * two real frames differ by 8 grey levels or more) says whether the picture
 * is quiet. A skip in a quiet moment repeats a picture in which almost
 * nothing moves, so it is not seen: a backlog of {@link #QUIET_BACKLOG_FRAMES}
 * is skipped there without waiting for the hold-off, at most every
 * {@link #QUIET_HOLDOFF_NS}, and a due skip waits up to {@link #QUIET_WAIT_NS}
 * for such a moment. NSMBU Deluxe, 3.2.149: one late render left 676 frames
 * in a row (5.6 s) a scan behind; on its recorded captures 22% of level
 * pairs and 59% of world-map pairs change less than 1% of the grid.</p>
 */
public final class CompositorBacklogCatchUp {
    public static final int BACKLOG_FRAMES = 120;
    public static final int JUDGE_FRAMES = 24;
    public static final long MIN_HOLDOFF_NS = 16_000_000_000L;
    public static final long MAX_HOLDOFF_NS = 256_000_000_000L;
    public static final long REFORM_NS = 30_000_000_000L;
    /** Changed share of a quiet pair, and the consecutive quiet pairs a quiet skip needs. */
    public static final double QUIET_SHARE = 0.005;
    public static final int QUIET_PAIRS = 2;
    public static final int QUIET_BACKLOG_FRAMES = 24;
    public static final long QUIET_HOLDOFF_NS = 2_000_000_000L;
    public static final long QUIET_WAIT_NS = 4_000_000_000L;
    /** A change measurement older than this is not known. */
    public static final long CHANGE_FRESH_NS = 1_000_000_000L;

    private int lateRun;
    private boolean pending;
    private long skippedAtNs = -1L, holdoffNs = MIN_HOLDOFF_NS;
    private int judged, judgedLate;
    private long skips, ineffective, reformed;
    private int quietRun;
    private long changeAtNs = -1L, pendingSinceNs = -1L, quietSkippedAtNs = -1L;
    private long quietHoldoffNs = QUIET_HOLDOFF_NS, quietSkips, quietIneffective;
    private int quietJudged = JUDGE_FRAMES, quietJudgedLate;
    private boolean quietEnabled = true;

    /**
     * One present with a known display time; nowNs is its present time (the
     * monotonic clock the skip is stamped with). Returns true when the next
     * built-in callback should present nothing.
     */
    public boolean observe(long desiredNs, long actualNs, long periodNs, long nowNs) {
        if (periodNs <= 0L || desiredNs <= 0L || actualNs <= 0L) return pending;
        long off = actualNs - desiredNs;
        boolean late = off > periodNs / 2L && off < periodNs + periodNs / 2L;
        if (quietSkippedAtNs >= 0L && quietJudged < JUDGE_FRAMES &&
                desiredNs > quietSkippedAtNs + 2L * periodNs) {
            ++quietJudged;
            if (late) ++quietJudgedLate;
            if (quietJudged == JUDGE_FRAMES && quietJudgedLate > JUDGE_FRAMES / 2) {
                ++quietIneffective;
                quietHoldoffNs = Math.min(MAX_HOLDOFF_NS, quietHoldoffNs * 2L);
            }
        }
        if (skippedAtNs >= 0L && judged < JUDGE_FRAMES) {
            // Frames planned before the skip were already queued behind it.
            if (desiredNs > skippedAtNs + 2L * periodNs) {
                ++judged;
                if (late) ++judgedLate;
                if (judged == JUDGE_FRAMES && judgedLate > JUDGE_FRAMES / 2) {
                    ++ineffective;
                    holdoffNs = Math.min(MAX_HOLDOFF_NS, holdoffNs * 2L);
                }
            }
        }
        lateRun = late ? lateRun + 1 : 0;
        // Only after a skip that cleared its backlog (an ineffective one has
        // already doubled the hold-off).
        if (!pending && lateRun == BACKLOG_FRAMES && skippedAtNs >= 0L &&
                judged >= JUDGE_FRAMES && judgedLate <= JUDGE_FRAMES / 2) {
            long since = nowNs - skippedAtNs;
            if (since < REFORM_NS) {
                ++reformed;
                holdoffNs = Math.min(MAX_HOLDOFF_NS, holdoffNs * 2L);
            } else if (since > 4L * holdoffNs) {
                holdoffNs = MIN_HOLDOFF_NS;
            }
        }
        if (!pending && lateRun >= BACKLOG_FRAMES &&
                (skippedAtNs < 0L || nowNs - skippedAtNs >= holdoffNs) &&
                (skippedAtNs < 0L || judged >= JUDGE_FRAMES)) {
            pending = true;
            pendingSinceNs = nowNs;
        }
        return pending;
    }

    /**
     * The changed share of the newest pair (0..1), measured at nowNs; a
     * negative share is unknown.
     */
    public void observeChange(double changedShare, long nowNs) {
        if (changedShare < 0.0) return;
        changeAtNs = nowNs;
        quietRun = changedShare <= QUIET_SHARE ? quietRun + 1 : 0;
    }

    /** QA: false keeps the 3.2.150 behaviour (no quiet timing). */
    public void setQuietEnabled(boolean enabled) { quietEnabled = enabled; }

    private boolean changeKnown(long nowNs) {
        return quietEnabled && changeAtNs >= 0L && nowNs - changeAtNs <= CHANGE_FRESH_NS;
    }

    private boolean quiet(long nowNs) {
        return changeKnown(nowNs) && quietRun >= QUIET_PAIRS;
    }

    /** The callback that presents nothing; true once per request. */
    public boolean takeSkip(long nowNs) {
        if (!pending) return takeQuietSkip(nowNs);
        // A due skip waits for a quiet moment while the picture is measured.
        if (changeKnown(nowNs) && !quiet(nowNs) && nowNs - pendingSinceNs < QUIET_WAIT_NS)
            return false;
        pending = false;
        lateRun = 0;
        skippedAtNs = nowNs;
        judged = judgedLate = 0;
        ++skips;
        return true;
    }

    private boolean takeQuietSkip(long nowNs) {
        if (lateRun < QUIET_BACKLOG_FRAMES || !quiet(nowNs)) return false;
        if (quietSkippedAtNs >= 0L && (nowNs - quietSkippedAtNs < quietHoldoffNs ||
                quietJudged < JUDGE_FRAMES)) return false;
        if (skippedAtNs >= 0L && judged < JUDGE_FRAMES) return false;
        lateRun = 0;
        quietRun = 0;
        quietSkippedAtNs = nowNs;
        quietJudged = quietJudgedLate = 0;
        ++quietSkips;
        return true;
    }

    public void reset() {
        lateRun = 0;
        pending = false;
        quietRun = 0;
    }

    public long skips() { return skips; }
    /** Skips taken in quiet moments, outside the hold-off. */
    public long quietSkips() { return quietSkips; }
    public long quietIneffective() { return quietIneffective; }
    public long ineffective() { return ineffective; }
    /** Backlogs that formed again within {@link #REFORM_NS} of a skip. */
    public long reformed() { return reformed; }
    public long holdoffNs() { return holdoffNs; }
}
