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
