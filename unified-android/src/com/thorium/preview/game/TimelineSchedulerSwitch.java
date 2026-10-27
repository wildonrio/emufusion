package com.thorium.preview.game;

import com.thorium.emufusion.video.GpuWorkAdaptationPolicy;

import android.content.Context;
import android.provider.Settings;

/**
 * Selects the built-in generator's presentation scheduler for the next
 * generator. AUTO and AUTO (TRIPLE) use the timeline scheduler, which bridges
 * held source frames and supports any multiplier (Thor A/B, 2026-10-11: 3DS
 * 92% even 30->60 vs 71%, GBA 78% generated cadence vs 47%, Wii equal).
 * Built-in (Alpha) keeps the exact one-midpoint lattice. The shell global
 * {@code emufusion_framegen_timeline} overrides for diagnostics: 0 forces the
 * lattice (except AUTO (TRIPLE), which needs the timeline), 1 forces the
 * timeline. Read once before each generator is built so a session never
 * changes schedulers mid-stream.
 */
public final class TimelineSchedulerSwitch {
    static final String GLOBAL = "emufusion_framegen_timeline";
    private static volatile boolean enabled;
    private static volatile int maxMultiplier = FrameGenerationSettings.MAX_MULTIPLIER;
    // QA only (emufusion_framegen_holdout=1): every other real frame is
    // withheld from generation and used to score the generated frame at its
    // time -- the quality measurement for generator changes.
    static final String HOLDOUT_GLOBAL = "emufusion_framegen_holdout";
    private static volatile boolean holdout;
    // QA only: emufusion_framegen_synth selects the synthesis for hold-out
    // comparisons: 0 the earlier two-sample combination, 1 the phase-field
    // candidates, 2 those with per-pixel selection among neighbouring cell
    // vectors, 3 also a coarse-to-fine phase-field search, 4 level 1 with a
    // vector-median phase field (1-2% better than 1 on every hold-out game,
    // Thor 2026-10-12, for a negligible low-resolution pass), 5 (default)
    // level 4 with its match costs on the pyramid's quarter-resolution images:
    // equal or better on all seven hold-out games (SM3DW 0.699 -> 0.695 of a
    // cross-fade, Wind Waker HD 0.523 -> 0.516, Star Fox 64 1.009 -> 0.981)
    // and far cheaper than sampling the full-resolution history (2026-10-13).
    // 8 and 9 (hold-out experiments) are level 5 with a search around the
    // phase winner: 8 reaches 30 px (16, 8, 4, 2), 9 the level-3 7 px,
    // 10 reaches 62 px (32..2), 11 is 8 finished at 1 px (16..1), 12 is 8
    // searching only poorly matched cells, 13 is 12 with a consensus blend
    // (no gain: within 0.006 on five games), 14 is 12 with neighbour selection.
    static final String SYNTH_GLOBAL = "emufusion_framegen_synth";
    // QA only: emufusion_framegen_work_floor 0..5 holds the dense work level
    // at least there, so hold-out and timing runs can measure each level
    // (delete after tests; the product never sets it).
    static final String WORK_FLOOR_GLOBAL = "emufusion_framegen_work_floor";
    // QA only: emufusion_framegen_fence_timing=1 times dense stages with native
    // fences even where EXT_disjoint_timer_query exists, to compare the two.
    static final String FENCE_TIMING_GLOBAL = "emufusion_framegen_fence_timing";
    private static volatile boolean fenceTiming;
    private static volatile int workFloor;
    // The finest motion solve runs on the pyramid's quarter-resolution images
    // instead of the full history (default since 2026-10-13: same hold-out
    // quality, half the solve cost); QA only: emufusion_framegen_solve_quarter=0
    // restores the full-resolution solve for comparisons.
    static final String SOLVE_QUARTER_GLOBAL = "emufusion_framegen_solve_quarter";
    private static volatile boolean solveQuarter = true;
    // The warp's motion logic evaluated per phase-grid cell instead of per
    // output pixel (PREPARED_WARP; default since 2026-10-13: equal or better on
    // the paired hold-out, warp 1.2 -> 0.6 ms on Cemu, Wind Waker HD at 4x
    // 181 -> 46 late callbacks). QA: emufusion_framegen_prepared_warp=0 turns
    // it off for comparisons.
    static final String PREPARED_WARP_GLOBAL = "emufusion_framegen_prepared_warp";
    static final boolean DEFAULT_PREPARED_WARP = true;
    private static volatile boolean preparedWarp = DEFAULT_PREPARED_WARP;
    // QA only: emufusion_framegen_holdout_levels "a,b,c" picks the three
    // synthesis variants the hold-out compares (100+ = with the prepared warp).
    static final String HOLDOUT_LEVELS_GLOBAL = "emufusion_framegen_holdout_levels";
    static final int[] DEFAULT_HOLDOUT_LEVELS = {14, 15, 115};
    private static volatile int[] holdoutLevels = DEFAULT_HOLDOUT_LEVELS.clone();
    // 12 (3.2.65): the phase winner is searched (16, 8, 4, 2 px) where it
    // matches poorly. Hold-out vs 5: SM3DW 0.601 -> 0.530 of a cross-fade,
    // Wind Waker HD 0.523 -> 0.490, God of War II 0.544 -> 0.524, at the same
    // GPU time per pair. 14 (3.2.66) adds per-pixel selection among the four
    // nearest cell vectors: vs 12 SM3DW 0.521 -> 0.510, Wind Waker HD 0.415
    // -> 0.404, Sunshine 0.737 -> 0.708, God of War II equal; same GPU time.
    // 15 (3.2.69) adds the static-structure fallback: fixed text whose
    // highlight changed takes the zero-motion blend instead of a warp that
    // erased it. DS file menu 1.211 -> 1.008 of a cross-fade; SM3DW, Wind
    // Waker HD, God of War II and Star Fox 64 within 0.4%; same GPU time.
    static final int DEFAULT_SYNTHESIS_LEVEL = 15;
    private static volatile int synthesisLevel = DEFAULT_SYNTHESIS_LEVEL;

    private TimelineSchedulerSwitch() {}

    static void refresh(Context context, FrameGenerationSettings.Mode mode) {
        boolean value = defaultFor(mode);
        try {
            int forced = context == null ? -1 : Settings.Global.getInt(
                    context.getContentResolver(), GLOBAL, -1);
            if (forced == 1) value = true;
            else if (forced == 0) value = mode != null && mode.requiresTimelineScheduler();
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the mode's own scheduler.
        }
        maxMultiplier = mode == null ? FrameGenerationSettings.MAX_MULTIPLIER :
                mode.maxMultiplier();
        enabled = value;
        boolean qa = false;
        try {
            qa = context != null && Settings.Global.getInt(
                    context.getContentResolver(), HOLDOUT_GLOBAL, 0) == 1;
        } catch (RuntimeException ignored) {
            // Unreadable settings never enable QA.
        }
        holdout = qa;
        int level = DEFAULT_SYNTHESIS_LEVEL;
        try {
            if (context != null) level = Settings.Global.getInt(
                    context.getContentResolver(), SYNTH_GLOBAL, DEFAULT_SYNTHESIS_LEVEL);
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default synthesis.
        }
        synthesisLevel = level == DIS_SYNTHESIS_LEVEL || level == DIS_MOTION_SYNTHESIS_LEVEL ||
                level == DIS_PHASE_SYNTHESIS_LEVEL || level == LEARNED_SELECTOR_SYNTHESIS_LEVEL ?
                level : Math.max(0, Math.min(15, level));
        boolean dis = true;
        try {
            if (context != null) dis = Settings.Global.getInt(
                    context.getContentResolver(), DIS_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        disDefault = dis;
        boolean low = true;
        try {
            if (context != null) low = Settings.Global.getInt(
                    context.getContentResolver(), LOW_LATENCY_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        lowLatency = low;
        boolean detail = true;
        try {
            if (context != null) detail = Settings.Global.getInt(
                    context.getContentResolver(), FIELD_DETAIL_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        fieldDetail = detail;
        boolean arrival = true;
        try {
            if (context != null) arrival = Settings.Global.getInt(
                    context.getContentResolver(), ARRIVAL_PACING_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        arrivalPacing = arrival;
        boolean guard = true;
        try {
            if (context != null) guard = Settings.Global.getInt(
                    context.getContentResolver(), EARLY_GUARD_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        earlyGuard = guard;
        boolean alive = true;
        try {
            if (context != null) alive = Settings.Global.getInt(
                    context.getContentResolver(), KEEP_ALIVE_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        keepAlive = alive;
        boolean arrivalLock = false;
        try {
            if (context != null) arrivalLock = Settings.Global.getInt(
                    context.getContentResolver(), ARRIVAL_PHASE_LOCK_GLOBAL, 0) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        arrivalPhaseLock = arrivalLock;
        boolean modeTrial = true;
        try {
            if (context != null) modeTrial = Settings.Global.getInt(
                    context.getContentResolver(), PACING_TRIAL_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        pacingTrial = modeTrial;
        boolean lattice = false;
        try {
            if (context != null) lattice = Settings.Global.getInt(
                    context.getContentResolver(), TAKEUP_LATTICE_GLOBAL, 0) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        takeUpLattice = lattice;
        boolean phase = true;
        try {
            if (context != null) phase = Settings.Global.getInt(
                    context.getContentResolver(), SOURCE_PHASE_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        sourcePhase = phase;
        boolean phaseHold = true;
        try {
            if (context != null) phaseHold = Settings.Global.getInt(
                    context.getContentResolver(), SOURCE_PHASE_LOCK_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        sourcePhaseLock = phaseHold;
        boolean deepen = true;
        try {
            if (context != null) deepen = Settings.Global.getInt(
                    context.getContentResolver(), QUEUE_DEEPEN_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        queueDeepen = deepen;
        boolean earliest = true;
        try {
            if (context != null) earliest = Settings.Global.getInt(
                    context.getContentResolver(), EARLIEST_LATCH_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        earliestLatch = earliest;
        boolean preparedImage = true;
        try {
            if (context != null) preparedImage = Settings.Global.getInt(
                    context.getContentResolver(), PREPARED_FRAME_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        preparedFrame = preparedImage;
        int floor = 0;
        try {
            if (context != null) floor = Settings.Global.getInt(
                    context.getContentResolver(), WORK_FLOOR_GLOBAL, 0);
        } catch (RuntimeException ignored) {
            // Unreadable settings never raise the work level.
        }
        workFloor = Math.max(0, Math.min(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL, floor));
        boolean fences = false;
        try {
            if (context != null) fences = Settings.Global.getInt(
                    context.getContentResolver(), FENCE_TIMING_GLOBAL, 0) == 1;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the driver's own timing source.
        }
        fenceTiming = fences;
        boolean quarter = true;
        try {
            if (context != null) quarter = Settings.Global.getInt(
                    context.getContentResolver(), SOLVE_QUARTER_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default quarter-resolution solve.
        }
        solveQuarter = quarter;
        boolean prepared = DEFAULT_PREPARED_WARP;
        try {
            if (context != null) prepared = Settings.Global.getInt(context.getContentResolver(),
                    PREPARED_WARP_GLOBAL, DEFAULT_PREPARED_WARP ? 1 : 0) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default warp.
        }
        preparedWarp = prepared;
        String levels = null;
        try {
            if (context != null) levels = Settings.Global.getString(
                    context.getContentResolver(), HOLDOUT_LEVELS_GLOBAL);
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default comparison.
        }
        holdoutLevels = parseHoldoutLevels(levels);
    }

    /**
     * Synthesis 21: GPU dense inverse search flow (DenseInverseSearchFlow),
     * QA-selectable for normal play and as a hold-out level.
     */
    static final int DIS_SYNTHESIS_LEVEL = 21;

    /** Synthesis 22 (QA): synthesis 15 with DIS motion in place of the block matcher's. */
    static final int DIS_MOTION_SYNTHESIS_LEVEL = 22;

    /** Synthesis 24 (QA): 21 with the motion refined per output phase by symmetric matching. */
    static final int DIS_PHASE_SYNTHESIS_LEVEL = 24;

    /** Synthesis 25 (QA): 24 blended by the learned visibility selector (LearnedSelectorShaders). */
    static final int LEARNED_SELECTOR_SYNTHESIS_LEVEL = 25;

    /**
     * DIS by default. Small (2-D) sources render synthesis 24 (21 with the
     * motion refined per output phase) and larger ones synthesis 15 with DIS
     * motion (22): on paired Thor hold-outs 21 beat synthesis 15 by 15-35% on
     * 2-D games and 24 beat 21 again (NES 0.547 -> 0.457); 22 beat 15 by 4-11%
     * on SM3DW, Ocarina of Time, God of War II and Star Fox 64, equal on
     * Link's Awakening. QA: 0 restores the block matcher and synthesis 15.
     */
    static final String DIS_GLOBAL = "emufusion_framegen_dis";

    /**
     * Low-latency presentation (default): duplicate checks committed on the
     * next vsync, one fewer look-ahead endpoint, trimming at one extra queued
     * image. QA: emufusion_framegen_low_latency=0 restores the previous
     * pipeline for latency comparisons.
     */
    static final String LOW_LATENCY_GLOBAL = "emufusion_framegen_low_latency";
    private static volatile boolean lowLatency = true;

    static boolean lowLatency() { return lowLatency; }

    /**
     * Full-size field detail (default, 3.2.86): each generated pixel picks
     * among the 3x3 neighbouring field vectors where they disagree (a 1080p
     * history's field is 1/8 of it). QA: emufusion_framegen_field_detail=0
     * restores 3.2.85's bilinear field for comparisons and GPU cost.
     */
    static final String FIELD_DETAIL_GLOBAL = "emufusion_framegen_field_detail";
    private static volatile boolean fieldDetail = true;

    static boolean fieldDetail() { return fieldDetail; }

    /**
     * Arrival pacing (default, 3.2.88): LSFG-Android's order of work -- each
     * new image's generated image as soon as it is computed, the real image
     * half the pair's span later -- instead of the content-time lattice. QA:
     * emufusion_framegen_arrival_pacing=0 restores 3.2.87's lattice.
     */
    static final String ARRIVAL_PACING_GLOBAL = "emufusion_framegen_arrival_pacing";
    private static volatile boolean arrivalPacing = true;

    static boolean arrivalPacing() { return arrivalPacing; }

    /**
     * Early-present guard (default, 3.2.101): once frames shown a scan
     * before their slot alternate with frames shown in it, built-in frames
     * ask for half a scan after the slot (CompositorEarlyGuard). QA:
     * emufusion_framegen_early_guard=0 keeps the lead-time request.
     */
    static final String EARLY_GUARD_GLOBAL = "emufusion_framegen_early_guard";
    private static volatile boolean earlyGuard = true;

    static boolean earlyGuard() { return earlyGuard; }

    /**
     * Keep-alive (default, 3.2.102): arrival pacing re-shows the image on
     * screen through a source stall so the compositor never idles
     * (TimelineFrameScheduler.KEEP_ALIVE_NS). QA:
     * emufusion_framegen_keep_alive=0 turns it off for comparisons.
     */
    static final String KEEP_ALIVE_GLOBAL = "emufusion_framegen_keep_alive";

    /**
     * Arrival phase lock (QA only, off by default): arrival-paced outputs that
     * span several scans (30 fps doubled to 60 on a 120 Hz panel) stay a whole
     * number of outputs apart, as the content-time lattice's do. Thor,
     * 2026-10-27: it did not remove Wind Waker HD's 1- and 3-scan intervals
     * (76.0 -> 76.7% on two scans; they are compositor landings, not take-up
     * phase), left Ocarina unchanged and cost latency, so 3.2.88's
     * first-due-scan behaviour stays. QA: emufusion_framegen_arrival_phase_lock=1.
     */
    static final String ARRIVAL_PHASE_LOCK_GLOBAL = "emufusion_framegen_arrival_phase_lock";
    private static volatile boolean arrivalPhaseLock;

    static boolean arrivalPhaseLock() { return arrivalPhaseLock; }

    /**
     * Pacing mode trial (default, 3.2.118): a source whose images arrive
     * unevenly is tried on the content-time timeline and kept there when that
     * holds fewer frames (PacingModeTrial; Super Mario 3D World 122-128 ->
     * 21 frames per 1000 held longer than usual, Thor 2026-10-27). QA:
     * emufusion_framegen_pacing_trial=0 keeps arrival pacing.
     */
    static final String PACING_TRIAL_GLOBAL = "emufusion_framegen_pacing_trial";
    private static volatile boolean pacingTrial = true;

    static boolean pacingTrial() { return pacingTrial; }
    private static volatile boolean keepAlive = true;

    static boolean keepAlive() { return keepAlive; }

    /**
     * Take-up lattice (3.2.112-3.2.116 default; off since 3.2.117): arrival
     * pacing takes a source's pairs up on a lattice of whole callbacks
     * instead of at the first callback after each arrival
     * (TimelineFrameScheduler). On the Thor (2026-10-27) it dropped real
     * images: paced 2-D cores showed only generated images for stretches,
     * each held two scans (NES 840 and Mega Drive 724 two-scan frames per
     * 30 s against 16 and 54 without it; SNES fell back to passthrough), so
     * pairs are taken up on arrival again, as on 3.2.110. QA:
     * emufusion_framegen_takeup_lattice=1 turns it on.
     */
    static final String TAKEUP_LATTICE_GLOBAL = "emufusion_framegen_takeup_lattice";
    private static volatile boolean takeUpLattice;

    static boolean takeUpLattice() { return takeUpLattice; }

    /**
     * Source phase (default, 3.2.103): a core we pace is moved once its clock
     * is locked so its images arrive just before the callback that takes them
     * up (SourcePhaseAdvisor). QA: emufusion_framegen_source_phase=0 keeps
     * the arbitrary phase for comparisons.
     */
    static final String SOURCE_PHASE_GLOBAL = "emufusion_framegen_source_phase";
    private static volatile boolean sourcePhase = true;

    static boolean sourcePhase() { return sourcePhase; }

    /**
     * Source phase lock (default, 3.2.119): a paced libretro core is nudged
     * every frame to hold its images a short wait before their callback
     * (SourcePhaseLock) instead of one-off moves between which the phase
     * drifts (NES, Thor 2026-10-27: 6 moves in 60 s, first generated image
     * 10-15 ms after arrival from run to run). QA:
     * emufusion_framegen_source_phase_lock=0 keeps the one-off moves.
     */
    static final String SOURCE_PHASE_LOCK_GLOBAL = "emufusion_framegen_source_phase_lock";
    private static volatile boolean sourcePhaseLock = true;

    static boolean sourcePhaseLock() { return sourcePhaseLock; }

    /**
     * Queue deepening (default, 3.2.89): late-from-rendering frames buy an
     * extra scan of queue (BuiltinQueueReserve). QA:
     * emufusion_framegen_queue_deepen=0 never deepens, to weigh that scan of
     * latency against the late frames it removes.
     */
    static final String QUEUE_DEEPEN_GLOBAL = "emufusion_framegen_queue_deepen";
    private static volatile boolean queueDeepen = true;

    static boolean queueDeepen() { return queueDeepen; }

    /**
     * The built-in planner targets the earliest composite-to-present latency
     * consistent with the compositor's report (default, 3.2.108;
     * PhysicalPresentationDeadline.earliestCompositeLatencyNs), so a burst of
     * late frames no longer locks every frame a scan later. QA:
     * emufusion_framegen_earliest_latch=0 follows the report as before.
     */
    static final String EARLIEST_LATCH_GLOBAL = "emufusion_framegen_earliest_latch";
    private static volatile boolean earliestLatch = true;

    static boolean earliestLatch() { return earliestLatch; }

    /**
     * The arrival pair's generated image is rendered when the pair forms and
     * only copied at its vsync callback (default, 3.2.109). QA:
     * emufusion_framegen_prepared_frame=0 renders it at the callback as before.
     */
    static final String PREPARED_FRAME_GLOBAL = "emufusion_framegen_prepared_frame";
    private static volatile boolean preparedFrame = true;

    static boolean preparedFrame() { return preparedFrame; }
    private static volatile boolean disDefault = true;

    static boolean disDefault() { return disDefault; }

    /** Three ids in 0..15, 100..115, 21 (DIS) or 22 (DIS motion); anything else falls back to the default. */
    static int[] parseHoldoutLevels(String value) {
        if (value == null) return DEFAULT_HOLDOUT_LEVELS.clone();
        String[] parts = value.split(",");
        if (parts.length != 3) return DEFAULT_HOLDOUT_LEVELS.clone();
        int[] ids = new int[3];
        try {
            for (int i = 0; i < 3; ++i) {
                ids[i] = Integer.parseInt(parts[i].trim());
                int level = ids[i] % 100;
                if (ids[i] == DIS_SYNTHESIS_LEVEL || ids[i] == DIS_MOTION_SYNTHESIS_LEVEL ||
                        ids[i] == DIS_PHASE_SYNTHESIS_LEVEL ||
                        ids[i] == LEARNED_SELECTOR_SYNTHESIS_LEVEL) continue;
                if (ids[i] < 0 || ids[i] > 115 || (ids[i] > 15 && ids[i] < 100) || level > 15)
                    return DEFAULT_HOLDOUT_LEVELS.clone();
            }
        } catch (NumberFormatException invalid) {
            return DEFAULT_HOLDOUT_LEVELS.clone();
        }
        return ids;
    }

    static boolean enabled() { return enabled; }

    static boolean defaultFor(FrameGenerationSettings.Mode mode) {
        return mode == FrameGenerationSettings.Mode.AUTO ||
                mode == FrameGenerationSettings.Mode.AUTO_TRIPLE;
    }

    static boolean holdout() { return holdout; }

    /**
     * QA replay (HoldoutReplay, its own process): production defaults, read
     * without settings, with hold-out scoring on the given three levels.
     */
    static void configureForReplay(int[] levels) {
        refresh(null, FrameGenerationSettings.Mode.AUTO);
        holdout = true;
        holdoutLevels = levels.clone();
    }

    static int synthesisLevel() { return synthesisLevel; }

    static int workFloor() { return workFloor; }

    static boolean fenceTiming() { return fenceTiming; }

    static boolean solveQuarter() { return solveQuarter; }

    static boolean preparedWarp() { return preparedWarp; }

    static int[] holdoutLevels() { return holdoutLevels.clone(); }

    /** Generation ceiling for a timeline generator built after the last refresh. */
    static int maxMultiplier() { return maxMultiplier; }
}
