package com.thorium.preview.game;

import android.graphics.Canvas;
import android.graphics.HardwareRenderer;
import android.graphics.RenderNode;
import android.util.Log;
import android.view.Surface;

/** API 29+ direct blit to the existing display Surface, with its source vsync.
 * Drawn by the software render worker. Lifecycle retirement/close is serialized
 * with recording by the session's presentation lock (or follows the worker join).
 * No intermediate Surface, generated image, frame queue or guest-clock change.
 */
final class DirectHardwareCanvas implements AutoCloseable {
    private final String name;
    private HardwareRenderer renderer;
    private RenderNode node;
    private Surface surface;
    private long epoch;
    private boolean recording;
    private int lastReportedSyncResult = Integer.MIN_VALUE;
    private long lastSyncReportNs;

    DirectHardwareCanvas(String name) { this.name = name; }

    Canvas begin(Surface target, int width, int height, long surfaceEpoch) {
        if (recording) throw new IllegalStateException("Direct canvas already recording");
        if (width <= 0 || height <= 0 || !target.isValid())
            throw new IllegalArgumentException("Invalid direct display surface");
        if (renderer == null || target != surface || surfaceEpoch != epoch) {
            close();
            renderer = new HardwareRenderer();
            renderer.setName(name);
            node = new RenderNode(name);
            node.setClipToBounds(false);
            node.setForceDarkAllowed(false);
            renderer.setLightSourceAlpha(0f, 0f);
            renderer.setContentRoot(node);
            renderer.setSurface(target);
            surface = target;
            epoch = surfaceEpoch;
        }
        node.setPosition(0, 0, width, height);
        Canvas canvas = node.beginRecording(width, height);
        recording = true;
        return canvas;
    }

    boolean post(long sourceVsyncNs) {
        if (!recording) throw new IllegalStateException("No direct canvas recording");
        node.endRecording();
        recording = false;
        // Surface.unlockCanvasAndPost supplies nanoTime at post. Preserve the
        // tick that started this frame instead, independent of core/blit work.
        int result = renderer.createRenderRequest()
                .setVsyncTime(sourceVsyncNs > 0 ? sourceVsyncNs : System.nanoTime())
                .syncAndDraw();
        // Preserve the actual HWUI reason: deferred, stopped and lost-surface
        // results have different recovery semantics. Bound transition logging
        // to once per second per owner; never log every dropped frame.
        long nowNs = System.nanoTime();
        if (result != lastReportedSyncResult &&
                (lastReportedSyncResult == Integer.MIN_VALUE ||
                        nowNs - lastSyncReportNs >= 1_000_000_000L)) {
            Log.i("LucentDirectCanvas", "HWUI sync owner=" + name +
                    " result=" + result + " epoch=" + epoch +
                    " sourceAgeUs=" + (sourceVsyncNs > 0
                            ? (nowNs - sourceVsyncNs) / 1000L : -1L));
            lastReportedSyncResult = result;
            lastSyncReportNs = nowNs;
        }
        if ((result & HardwareRenderer.SYNC_LOST_SURFACE_REWARD_IF_FOUND) != 0) {
            close();
            return false;
        }
        // A successful sync is not physical-presentation proof. In particular,
        // HWUI can defer a dropped frame internally; do not count it as a post.
        return (result & (HardwareRenderer.SYNC_CONTEXT_IS_STOPPED |
                HardwareRenderer.SYNC_FRAME_DROPPED)) == 0;
    }

    @Override public void close() {
        if (recording) {
            node.endRecording();
            recording = false;
        }
        if (renderer != null) {
            renderer.destroy();
            renderer = null;
        }
        if (node != null) node.discardDisplayList();
        node = null;
        // The Surface belongs to the view/router, not to this renderer.
        surface = null;
    }
}
