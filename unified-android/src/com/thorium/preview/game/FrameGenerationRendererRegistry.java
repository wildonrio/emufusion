package com.thorium.preview.game;

import android.view.Surface;

import java.lang.ref.WeakReference;
import java.util.IdentityHashMap;
import java.util.Map;

/** Identity registry for producers that are handed a renderer Surface. */
public final class FrameGenerationRendererRegistry {
    private static final Map<Surface, WeakReference<FrameGenerationRenderer>> RENDERERS =
            new IdentityHashMap<>();

    private FrameGenerationRendererRegistry() {}

    /** Physical display surfaces must not receive FG-specific source stamps. */
    public static boolean isFrameGenerationInput(Surface surface) {
        return surface != null && surface.isValid() && find(surface) != null;
    }

    /** The renderer's one-time phase delay for a paced source feeding this Surface, or zero. */
    public static long takeSourcePhaseDelayNs(Surface surface) {
        FrameGenerationRenderer renderer = surface != null && surface.isValid() ? find(surface) : null;
        return renderer == null ? 0L : renderer.takeSourcePhaseDelayNs();
    }

    /**
     * Whether this core's stamps start behind the clock unless QA says otherwise, so the firmware
     * always paces it. Double Dash swings from clean to over 100 hitches per 30 s by where its
     * stamps fall. Ocarina too (2026-11-07, same hour, turn about): 99.4% and 99.3% on cadence
     * with its arrival held 11.2 ms before the slot throughout, against 98.7% and 95.9% when a
     * burst left its stamps ahead and its phase wandered for 10-20 s.
     */
    public static boolean stampBehindByDefault(String coreFileName) {
        return "libemufusion_core_dolphin.so".equals(coreFileName) ||
                "libemufusion_core_mupen64plus_next.so".equals(coreFileName);
    }

    /** How far ahead a hardware core feeding this Surface should stamp its images, or zero. */
    public static long hardwareStampAheadNs(Surface surface, boolean pinnedByDefault) {
        FrameGenerationRenderer renderer = surface != null && surface.isValid() ? find(surface) : null;
        return renderer == null ? 0L : renderer.hardwareStampAheadNs(pinnedByDefault);
    }

    /** The renderer's phase-lock step for a hardware core feeding this Surface, or zero. */
    public static long takeHardwareSourcePhaseNudgeNs(Surface surface) {
        FrameGenerationRenderer renderer = surface != null && surface.isValid() ? find(surface) : null;
        return renderer == null ? 0L : renderer.takeHardwareSourcePhaseNudgeNs();
    }

    /** How long a paced hardware core feeding this Surface should hold after presenting, or zero. */
    public static long coreHoldAfterPresentNs(Surface surface) {
        FrameGenerationRenderer renderer = surface != null && surface.isValid() ? find(surface) : null;
        return renderer == null ? 0L : renderer.coreHoldAfterPresentNs();
    }

    static void register(FrameGenerationRenderer renderer) {
        if (renderer == null) throw new NullPointerException("renderer");
        Surface surface = renderer.inputSurface();
        if (surface == null || !surface.isValid())
            throw new IllegalArgumentException("renderer input Surface must be valid");
        synchronized (RENDERERS) {
            WeakReference<FrameGenerationRenderer> reference = RENDERERS.get(surface);
            FrameGenerationRenderer existing = reference == null ? null : reference.get();
            if (existing != null && existing != renderer)
                throw new IllegalStateException("input Surface already has a renderer owner");
            RENDERERS.put(surface, new WeakReference<>(renderer));
        }
    }

    static FrameGenerationRenderer find(Surface surface) {
        if (surface == null) return null;
        synchronized (RENDERERS) {
            WeakReference<FrameGenerationRenderer> reference = RENDERERS.get(surface);
            FrameGenerationRenderer renderer = reference == null ? null : reference.get();
            if (renderer == null && reference != null) RENDERERS.remove(surface);
            return renderer;
        }
    }

    static void unregister(Surface surface, FrameGenerationRenderer renderer) {
        if (surface == null || renderer == null) return;
        synchronized (RENDERERS) {
            WeakReference<FrameGenerationRenderer> reference = RENDERERS.get(surface);
            FrameGenerationRenderer existing = reference == null ? null : reference.get();
            if (existing == null || existing == renderer) RENDERERS.remove(surface);
        }
    }

    /** Number of live input-Surface owners after pruning collected entries. */
    static int liveCount() {
        synchronized (RENDERERS) {
            java.util.Iterator<Map.Entry<Surface, WeakReference<FrameGenerationRenderer>>>
                    iterator = RENDERERS.entrySet().iterator();
            while (iterator.hasNext()) {
                Map.Entry<Surface, WeakReference<FrameGenerationRenderer>> entry =
                        iterator.next();
                if (entry.getValue().get() == null) iterator.remove();
            }
            return RENDERERS.size();
        }
    }
}
