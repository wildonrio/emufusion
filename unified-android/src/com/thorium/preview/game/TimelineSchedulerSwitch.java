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
        boolean rateHold = false;
        try {
            if (context != null) rateHold = Settings.Global.getInt(
                    context.getContentResolver(), RATE_LOCK_GLOBAL, 0) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        rateLock = rateHold;
        boolean fade = true;
        try {
            if (context != null) fade = Settings.Global.getInt(
                    context.getContentResolver(), PIXEL_FADE_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        pixelFade = fade;
        int overlayFrames = 0;
        try {
            if (context != null) overlayFrames = Settings.Global.getInt(
                    context.getContentResolver(), STATIC_OVERLAY_GLOBAL, 0);
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        staticOverlayFrames = Math.max(0, Math.min(255, overlayFrames));
        int stride = DenseInverseSearchFlow.PHASE_DISCRETE_STRIDE;
        try {
            if (context != null) stride = Settings.Global.getInt(
                    context.getContentResolver(), PIXEL_STRIDE_GLOBAL, stride);
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        pixelStride = stride == 3 ? 3 : DenseInverseSearchFlow.PHASE_DISCRETE_STRIDE;
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
        boolean sourceSize = true;
        try {
            if (context != null) sourceSize = Settings.Global.getInt(
                    context.getContentResolver(), ENGINE_SOURCE_SIZE_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        engineSourceSize = sourceSize;
        boolean asap = false;
        try {
            if (context != null) asap = Settings.Global.getInt(
                    context.getContentResolver(), PRESENT_ASAP_GLOBAL, 0) == 1;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep requested present times.
        }
        presentAsap = asap;
        boolean verdict = true;
        try {
            if (context != null) verdict = Settings.Global.getInt(
                    context.getContentResolver(), VERDICT_WAIT_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        verdictWait = verdict;
        boolean pixel = false;
        try {
            if (context != null) pixel = Settings.Global.getInt(
                    context.getContentResolver(), PIXEL_MODE_GLOBAL, 0) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        pixelMode = pixel;
        boolean mode3 = false;
        float lead = 12f;
        try {
            if (context != null) {
                mode3 = Settings.Global.getInt(context.getContentResolver(), MODE_3D_GLOBAL, 0) != 0;
                lead = Settings.Global.getFloat(context.getContentResolver(), PIXEL_MODE_LEAD_GLOBAL, 12f);
            }
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the defaults.
        }
        mode3d = mode3;
        boolean pixelInput = false;
        try {
            if (context != null) pixelInput = Settings.Global.getInt(
                    context.getContentResolver(), PIXEL_INPUT_SIZE_GLOBAL, 0) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        pixelInputSize = pixelInput;
        boolean flush = false;
        try {
            if (context != null) flush = Settings.Global.getInt(
                    context.getContentResolver(), MID_FLUSH_GLOBAL, 0) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        midFlush = flush;
        boolean handOver = false;
        try {
            if (context != null) handOver = Settings.Global.getInt(
                    context.getContentResolver(), FAST_PATH_GLOBAL, 0) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        fastPath = handOver;
        int stateDrain = 1;
        try {
            if (context != null) stateDrain = Settings.Global.getInt(
                    context.getContentResolver(), COMPOSITOR_DRAIN_GLOBAL, 1);
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        compositorDrain = stateDrain != 0;
        compositorDrainAllSources = stateDrain >= 2;
        int hardwareLock = -1;
        try {
            if (context != null) hardwareLock = Settings.Global.getInt(
                    context.getContentResolver(), HARDWARE_PHASE_LOCK_GLOBAL, hardwareLock);
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        hardwarePhaseLock = hardwareLock;
        boolean steadyCemu = true;
        try {
            if (context != null) steadyCemu = Settings.Global.getInt(
                    context.getContentResolver(), STEADY_CEMU_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        steadyCemuOutput = steadyCemu;
        boolean pairArrivalSpan = true;
        try {
            if (context != null) pairArrivalSpan = Settings.Global.getInt(
                    context.getContentResolver(), ARRIVAL_SPAN_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        arrivalSpan = pairArrivalSpan;
        boolean predraw = true;
        try {
            if (context != null) predraw = Settings.Global.getInt(
                    context.getContentResolver(), REAL_PREDRAW_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        realPredraw = predraw;
        int check = 0;
        try {
            if (context != null) check = Settings.Global.getInt(
                    context.getContentResolver(), IMAGE_CHECK_GLOBAL, check);
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        imageCheck = check;
        long phaseWaitUs = 3250L;
        try {
            if (context != null) phaseWaitUs = Settings.Global.getLong(
                    context.getContentResolver(), SWITCH_PHASE_WAIT_GLOBAL, phaseWaitUs);
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        switchPhaseWaitNs = phaseWaitUs * 1000L;
        pixelModeLead = lead;
        boolean fast = true;
        try {
            if (context != null) fast = Settings.Global.getInt(
                    context.getContentResolver(), FAST_CORES_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        fastCores = fast;
        boolean quiet = false;
        try {
            if (context != null) quiet = Settings.Global.getInt(
                    context.getContentResolver(), QUIET_SKIP_GLOBAL, 0) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        quietSkip = quiet;
        boolean reverse = true;
        try {
            if (context != null) reverse = Settings.Global.getInt(
                    context.getContentResolver(), SWITCH_REVERSE_GLOBAL, 1) != 0;
        } catch (RuntimeException ignored) {
            // Unreadable settings keep the default.
        }
        switchReverseCandidates = reverse;
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
     * Synthesis 26 (QA hold-out level): 24 with the static-overlay rule
     * (pixels unchanged for {@link #OVERLAY_LEVEL_FRAMES} real frames shown
     * unwarped), so a hold-out capture with levels 24,26,x scores both on the
     * same pairs.
     */
    static final int DIS_PHASE_OVERLAY_SYNTHESIS_LEVEL = 26;
    static final int OVERLAY_LEVEL_FRAMES = 60;

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
     * Rate lock (QA only, off by default): native engines' paced video rate
     * is trimmed to hold their images a short wait before the callback
     * (SourceRateLock). Thor, 2026-10-27: Dolphin and ARMSX2 took no trim,
     * Eden's trim saturated (its frames follow its rendering) and Cemu's
     * jitter set a near-scan target, so latency did not fall. QA:
     * emufusion_framegen_rate_lock=1.
     */
    static final String RATE_LOCK_GLOBAL = "emufusion_framegen_rate_lock";
    private static volatile boolean rateLock;

    static boolean rateLock() { return rateLock; }

    /**
     * Pixel-art motion fade: on the whole-pixel path, the per-phase motion
     * fades to zero where no covering patch explains a pixel's 3x3
     * neighbourhood (a whole-pixel copy of a real frame invents nothing).
     * Active only in a build whose densify shader has the fade
     * (dis_gles.py PHASE_DENSIFY_DISCRETE_FADE). QA:
     * emufusion_framegen_pixel_fade=0.
     */
    static final String PIXEL_FADE_GLOBAL = "emufusion_framegen_pixel_fade";
    private static volatile boolean pixelFade = true;

    static boolean pixelFade() { return pixelFade; }

    /**
     * Static overlays (QA, off by default): a pixel unchanged for this many
     * real frames in a row is shown unwarped (a HUD over a scroll;
     * dis_gles.py STATIC_OVERLAY). QA: emufusion_framegen_static_overlay=60.
     */
    static final String STATIC_OVERLAY_GLOBAL = "emufusion_framegen_static_overlay";
    private static volatile int staticOverlayFrames;

    static int staticOverlayFrames() { return staticOverlayFrames; }

    /**
     * Pixel art's per-phase patch stride (3.2.124): 4, cheaper and with less
     * invented content, at a few more whole-frame holds on Game Gear and
     * NES. QA: emufusion_framegen_pixel_stride=3 restores 3.2.123's grid.
     */
    static final String PIXEL_STRIDE_GLOBAL = "emufusion_framegen_pixel_stride";
    private static volatile int pixelStride = DenseInverseSearchFlow.PHASE_DISCRETE_STRIDE;

    static int pixelStride() { return pixelStride; }

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

    /**
     * An engine that renders a fixed picture smaller than the panel gets an
     * input Surface of that size (GameSurfaceView.setSourceSize; default,
     * 3.2.136). QA: emufusion_framegen_engine_source_size=0 gives it the
     * panel size as before, for paired comparisons.
     */
    static final String ENGINE_SOURCE_SIZE_GLOBAL = "emufusion_framegen_engine_source_size";
    private static volatile boolean engineSourceSize = true;

    static boolean engineSourceSize() { return engineSourceSize; }

    /**
     * QA only: emufusion_framegen_present_asap=1 queues built-in frames with
     * no requested present time (as stock LSFG-Android), so the compositor
     * shows each at the first scan it can, for comparison with planned slots.
     */
    static final String PRESENT_ASAP_GLOBAL = "emufusion_framegen_present_asap";
    private static volatile boolean presentAsap;

    static boolean presentAsap() { return presentAsap; }

    /**
     * An arriving image's uniqueness check is waited for on a GPU fence, at
     * most until shortly before the next callback, instead of polled 1 ms
     * later (default, 3.2.141). QA: emufusion_framegen_verdict_wait=0 keeps
     * the 1-ms poll only, for paired comparisons.
     */
    static final String VERDICT_WAIT_GLOBAL = "emufusion_framegen_verdict_wait";
    private static volatile boolean verdictWait = true;

    static boolean verdictWait() { return verdictWait; }




    /**
     * Pixel art's generate pass reads a field chosen per pixel from the local
     * mode of the whole-pixel motion, the pixel's own vector and zero (dis_gles.py
     * PHASE_MODE). QA: emufusion_framegen_pixel_mode=0 reads the field directly.
     */
    static final String PIXEL_MODE_GLOBAL = "emufusion_framegen_pixel_mode";
    private static volatile boolean pixelMode = false;

    static boolean pixelMode() { return pixelMode; }

    static final String PIXEL_MODE_LEAD_GLOBAL = "emufusion_framegen_pixel_mode_lead";
    private static volatile float pixelModeLead = 12f;

    /** Grey levels the pixel's own vector or zero motion must win by (dis_gles.py PHASE_MODE). */
    static float pixelModeLead() { return pixelModeLead; }

    /**
     * QA (emufusion_framegen_mode_3d=1): the local mode as a candidate on the
     * 3-D path too, per field pixel.
     */
    static final String MODE_3D_GLOBAL = "emufusion_framegen_mode_3d";
    private static volatile boolean mode3d = false;

    static boolean mode3d() { return mode3d; }

    static final String PIXEL_INPUT_SIZE_GLOBAL = "emufusion_framegen_pixel_input_size";
    private static volatile boolean pixelInputSize = false;

    /** QA: pixel art's prepared generated image at the source's size (preparedAtInputSize). */
    static boolean pixelInputSize() { return pixelInputSize; }

    static final String MID_FLUSH_GLOBAL = "emufusion_framegen_mid_flush";
    private static volatile boolean midFlush = false;

    /** QA: the pair solve's GPU work starts while the CPU still encodes the rest. */
    static boolean midFlush() { return midFlush; }

    /**
     * QA (emufusion_framegen_fast_path=1): each image's textures change hands
     * instead of being copied three times on their way from the input to the
     * pair's history, and the motion passes keep one framebuffer per target and
     * tell the GPU their targets' old contents are not needed.
     */
    static final String FAST_PATH_GLOBAL = "emufusion_framegen_fast_path";
    private static volatile boolean fastPath = false;

    static boolean fastPath() { return fastPath; }

    /**
     * A generated frame is left out when that ends the compositor's pipelined
     * state for long enough (CompositorStateDrain). Thor, 2026-11-06: NES and Mega
     * Drive no longer sit 8 ms late for a whole run; NSMBU Deluxe backs off after
     * two tries. QA: emufusion_framegen_compositor_drain=0.
     */
    static final String COMPOSITOR_DRAIN_GLOBAL = "emufusion_framegen_compositor_drain";
    private static volatile boolean compositorDrain = true;

    static boolean compositorDrain() { return compositorDrain; }

    /** QA emufusion_framegen_compositor_drain=2: not only the sources the phase lock holds. */
    private static volatile boolean compositorDrainAllSources = false;

    static boolean compositorDrainAllSources() { return compositorDrainAllSources; }

    /**
     * A hardware core's stamps follow its run sequence, so a burst leaves them
     * ahead of the clock and a stall behind it. Only stamps behind it get the
     * firmware's pacing, which pins arrival before the panel callback; ahead, the
     * core runs free. Double Dash ranged from 1.8 to 168 hitches per 30 s by that
     * alone (Thor, 2026-11-06). So the host's named cores (Dolphin) start their
     * stamps a second behind (stampBehindByDefault).
     * QA emufusion_framegen_hardware_phase_lock: 0 stamps as they fall, 1 every
     * hardware core held by the phase lock instead, with its stamps kept ahead.
     */
    static final String HARDWARE_PHASE_LOCK_GLOBAL = "emufusion_framegen_hardware_phase_lock";
    private static volatile int hardwarePhaseLock = -1;

    static boolean hardwarePhaseLock() { return hardwarePhaseLock > 0; }

    static boolean hardwareStampBehind(boolean pinnedByDefault) {
        return hardwarePhaseLock < 0 && pinnedByDefault;
    }

    /**
     * Cemu at a multi-scan output (a 30 fps game): a pair does not wait for its uniqueness
     * check after a long run of unique verdicts, and the queue keeps a scan or more back with the
     * early guard on. Wind Waker HD's arrival sits 3.6 ms before the callback and the check
     * finishes around it, behind Cemu's GPU work, so its generated image toggled between 11 and
     * 19 ms, 87-92% on cadence. With this 98.9%, at 27.6 / 44.3 ms against about 17 / 33 ms: a
     * steady rhythm first (Thor, 2026-11-06). QA emufusion_framegen_steady_cemu=0 turns it off.
     */
    static final String STEADY_CEMU_GLOBAL = "emufusion_framegen_steady_cemu";
    private static volatile boolean steadyCemuOutput = true;

    static boolean steadyCemuOutput() { return steadyCemuOutput; }

    /**
     * Arrival pacing places a pair's real image by the time between its images'
     * arrivals, not their timestamps (QA emufusion_framegen_arrival_span=0 for those).
     * Wind Waker HD's images arrive an even 33.3 ms apart, but Cemu's 60 Hz stamp
     * lattice reads some 16.7 and 50 ms apart near a slot boundary, so real images
     * come one or three scans after the generated image (Thor, 2026-11-06).
     */
    static final String ARRIVAL_SPAN_GLOBAL = "emufusion_framegen_arrival_span";
    private static volatile boolean arrivalSpan = true;

    static boolean arrivalSpan() { return arrivalSpan; }

    /**
     * A pair's real image is drawn into the back buffer right after its
     * generated image's swap, so its own callback only swaps it (QA
     * emufusion_framegen_real_predraw=0 turns this off). Wind Waker HD's real images finish 3 ms after
     * their scan behind Cemu's GPU work, one scan late every time (Thor, 2026-11-06).
     */
    static final String REAL_PREDRAW_GLOBAL = "emufusion_framegen_real_predraw";
    private static volatile boolean realPredraw = true;

    static boolean realPredraw() { return realPredraw; }

    /**
     * QA emufusion_framegen_image_check: a preview of each generated image is
     * compared with the real frames, and what is in neither shows the nearer
     * real frame (dis_gles.py IMAGE_CHECK). 0 off, 1 3-D, 2 pixel art as well:
     * a held patch of a large 2-D move can be a second copy of its object
     * (Sonic 2's flippers).
     */
    static final String IMAGE_CHECK_GLOBAL = "emufusion_framegen_image_check";
    private static volatile int imageCheck = 0;

    static boolean imageCheck(boolean discrete) { return imageCheck >= (discrete ? 2 : 1); }


    static final String SWITCH_PHASE_WAIT_GLOBAL = "emufusion_framegen_switch_phase_wait_us";
    private static volatile long switchPhaseWaitNs = 3_250_000L;

    /** QA: the source phase lock's wait before Eden's images reach a callback, before jitter. */
    static long switchPhaseWaitNs() { return switchPhaseWaitNs; }


    /**
     * The frame thread runs only on CPUs outside the lowest-clocked cluster
     * (default, 3.2.143). QA: emufusion_framegen_fast_cores=0 leaves its
     * placement to the scheduler, for paired comparisons.
     */
    static final String FAST_CORES_GLOBAL = "emufusion_framegen_fast_cores";
    private static volatile boolean fastCores = true;

    static boolean fastCores() { return fastCores; }

    /**
     * QA opt-in (emufusion_framegen_quiet_skip=1, 2026-11-04): compositor
     * catch-up skips timed by how much the picture changes
     * (CompositorBacklogCatchUp), and the GPU measurement that feeds them.
     * Off by default: NSMBU Deluxe in play went from 72% to 35% of frames
     * shown a scan late, but each quiet skip is one more two-scan interval
     * (21 against 12 in 16 s) and its world has no fully still pairs.
     */
    static final String QUIET_SKIP_GLOBAL = "emufusion_framegen_quiet_skip";
    private static volatile boolean quietSkip = false;

    static boolean quietSkip() { return quietSkip; }

    /**
     * Switch (Eden) sessions: the per-phase search also starts from C's flow
     * (default, dis_gles.py PHASE_PROPAGATE_CA_SWITCH). QA:
     * emufusion_framegen_switch_reverse_candidates=0 leaves it out, for
     * paired comparisons.
     */
    static final String SWITCH_REVERSE_GLOBAL = "emufusion_framegen_switch_reverse_candidates";
    private static volatile boolean switchReverseCandidates = true;

    static boolean switchReverseCandidates() { return switchReverseCandidates; }
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
                        ids[i] == LEARNED_SELECTOR_SYNTHESIS_LEVEL ||
                        ids[i] == DIS_PHASE_OVERLAY_SYNTHESIS_LEVEL) continue;
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
