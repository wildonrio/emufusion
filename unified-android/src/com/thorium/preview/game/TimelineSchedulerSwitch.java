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
    // searching only poorly matched cells, 13 is 12 with a consensus blend.
    static final String SYNTH_GLOBAL = "emufusion_framegen_synth";
    // QA only: emufusion_framegen_work_floor 0..4 holds the dense work level
    // at least there, so hold-out and timing runs can measure each level
    // (delete after tests; the product never sets it).
    static final String WORK_FLOOR_GLOBAL = "emufusion_framegen_work_floor";
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
    static final int[] DEFAULT_HOLDOUT_LEVELS = {5, 12, 112};
    private static volatile int[] holdoutLevels = DEFAULT_HOLDOUT_LEVELS.clone();
    // 12 since 2026-10-13: the phase winner is searched (16, 8, 4, 2 px)
    // where it matches poorly. Hold-out vs 5: SM3DW 0.601 -> 0.530 of a
    // cross-fade, Wind Waker HD 0.523 -> 0.490, God of War II 0.544 -> 0.524,
    // at the same GPU time per pair (well-matched background skips it).
    static final int DEFAULT_SYNTHESIS_LEVEL = 12;
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
        synthesisLevel = Math.max(0, Math.min(13, level));
        int floor = 0;
        try {
            if (context != null) floor = Settings.Global.getInt(
                    context.getContentResolver(), WORK_FLOOR_GLOBAL, 0);
        } catch (RuntimeException ignored) {
            // Unreadable settings never raise the work level.
        }
        workFloor = Math.max(0, Math.min(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL, floor));
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

    /** Three ids in 0..13 or 100..113; anything else falls back to the default. */
    static int[] parseHoldoutLevels(String value) {
        if (value == null) return DEFAULT_HOLDOUT_LEVELS.clone();
        String[] parts = value.split(",");
        if (parts.length != 3) return DEFAULT_HOLDOUT_LEVELS.clone();
        int[] ids = new int[3];
        try {
            for (int i = 0; i < 3; ++i) {
                ids[i] = Integer.parseInt(parts[i].trim());
                int level = ids[i] % 100;
                if (ids[i] < 0 || ids[i] > 113 || (ids[i] > 13 && ids[i] < 100) || level > 13)
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

    static int synthesisLevel() { return synthesisLevel; }

    static int workFloor() { return workFloor; }

    static boolean solveQuarter() { return solveQuarter; }

    static boolean preparedWarp() { return preparedWarp; }

    static int[] holdoutLevels() { return holdoutLevels.clone(); }

    /** Generation ceiling for a timeline generator built after the last refresh. */
    static int maxMultiplier() { return maxMultiplier; }
}
