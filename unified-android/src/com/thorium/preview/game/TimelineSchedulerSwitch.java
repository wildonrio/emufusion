package com.thorium.preview.game;

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
    }

    static boolean enabled() { return enabled; }

    static boolean defaultFor(FrameGenerationSettings.Mode mode) {
        return mode == FrameGenerationSettings.Mode.AUTO ||
                mode == FrameGenerationSettings.Mode.AUTO_TRIPLE;
    }

    /** Generation ceiling for a timeline generator built after the last refresh. */
    static int maxMultiplier() { return maxMultiplier; }
}
