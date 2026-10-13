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
    // vector-median phase field (default: 1-2% better than 1 on every hold-out
    // game, Thor 2026-10-12, for a negligible low-resolution pass).
    static final String SYNTH_GLOBAL = "emufusion_framegen_synth";
    // QA only: emufusion_framegen_work_floor 0..4 holds the dense work level
    // at least there, so hold-out and timing runs can measure each level
    // (delete after tests; the product never sets it).
    static final String WORK_FLOOR_GLOBAL = "emufusion_framegen_work_floor";
    private static volatile int workFloor;
    static final int DEFAULT_SYNTHESIS_LEVEL = 4;
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
        synthesisLevel = Math.max(0, Math.min(4, level));
        int floor = 0;
        try {
            if (context != null) floor = Settings.Global.getInt(
                    context.getContentResolver(), WORK_FLOOR_GLOBAL, 0);
        } catch (RuntimeException ignored) {
            // Unreadable settings never raise the work level.
        }
        workFloor = Math.max(0, Math.min(GpuWorkAdaptationPolicy.DEFAULT_MAX_WORK_LEVEL, floor));
    }

    static boolean enabled() { return enabled; }

    static boolean defaultFor(FrameGenerationSettings.Mode mode) {
        return mode == FrameGenerationSettings.Mode.AUTO ||
                mode == FrameGenerationSettings.Mode.AUTO_TRIPLE;
    }

    static boolean holdout() { return holdout; }

    static int synthesisLevel() { return synthesisLevel; }

    static int workFloor() { return workFloor; }

    /** Generation ceiling for a timeline generator built after the last refresh. */
    static int maxMultiplier() { return maxMultiplier; }
}
