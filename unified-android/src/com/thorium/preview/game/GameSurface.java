package com.thorium.preview.game;

import android.content.Context;
import android.graphics.SurfaceTexture;
import android.os.Build;
import android.util.Log;
import android.view.Display;
import android.view.Surface;
import android.view.TextureView;

import com.thorium.lucent.video.PresentationGeometry;
import com.thorium.lucent.video.FrameGenerationBackendPolicy;

/** Engine-neutral, Lucent-owned video surface. */
public final class GameSurface extends TextureView
        implements TextureView.SurfaceTextureListener {
    private static final String TAG = "EmuFusionGameSurface";
    public interface RetirementCompletion { void complete(Throwable failure); }
    public interface Listener {
        void onSurfaceAvailable(Surface surface, int width, int height);
        void onSurfaceSizeChanged(int width, int height);
        void onSurfaceDestroyed();
        /** Called on UI; retirement must wait off UI for the producer's acknowledgement. */
        default void retireSurfaceRenderer(FrameGenerationRenderer renderer,
                RetirementCompletion completion) {
            completion.complete(new IllegalStateException("No producer retirement owner"));
        }
        default void onSurfaceStartupError(String message, Throwable cause) {}
        default void onSurfaceRuntimeError(String message, Throwable cause) {}
    }

    private Listener listener;
    private Surface outputSurface;
    private Surface renderSurface;
    private SurfaceTexture quarantinedTexture;
    private FrameGenerationRenderer frameGenerator;
    private int surfaceGeneration;
    private int runtimeFailedGeneration = -1;
    // SurfaceTexture replacement is not a new game session. A new view after
    // explicit game reopen is the only reset for a delivered runtime failure.
    private boolean runtimePresentationFailed;
    /** Startup fallback lasts for this game view, not just one SurfaceTexture. */
    private boolean startupFellBackToDirect;
    private FrameGenerationRenderer.StatsListener frameRateListener;
    private Runnable firstSubmittedFrameListener;
    private float directPresentationHz = 60.0f;
    private boolean firstFrameSubmitted;
    private FrameGenerationBackendPolicy.Backend activeBackend =
            FrameGenerationBackendPolicy.Backend.DIRECT;
    /** Immutable owner choice for this Surface generation. */
    private final FrameGenerationSettings.Mode launchMode;
    /** The system's hardware display aspect, or 0 to fill the parent. */
    private float displayAspect;

    public GameSurface(Context context) {
        this(context, FrameGenerationSettings.mode(context));
    }

    public GameSurface(Context context, FrameGenerationSettings.Mode launchMode) {
        super(context);
        this.launchMode = launchMode == null ? FrameGenerationSettings.Mode.OFF :
                launchMode;
        setFocusable(false);
        // A TextureView marked opaque is composited with SkBlendMode.SRC, so
        // the engine buffer's alpha channel becomes the gameplay window's
        // alpha and SurfaceFlinger blends the EmuFusion library through it.
        // Hardware cores legitimately publish RGB with non-opaque alpha (the
        // PS2 GS marks a fully opaque pixel 0x80, and untouched swapchain rows
        // are zero), so an opaque layer published the library at 50% over
        // ARMSX2 gameplay. Compositing over the gameplay root's opaque black
        // background instead keeps premultiplied RGB and forces the published
        // window alpha to one, which is exactly what the GLES backend's
        // force_opaque_surface_alpha() does inside its own context.
        setOpaque(false);
        setSurfaceTextureListener(this);
    }

    /**
     * Shapes the video surface itself to the system's display aspect.
     *
     * <p>This is the one place that makes proportional scaling true for every
     * engine rather than for the ones that happen to implement it. An engine
     * that renders straight into its Android window -- Eden, Cemu, and any
     * hardware core presenting to the whole surface -- has no frontend blit to
     * correct, so the only way to stop it filling a 16:9 panel with a 4:3
     * picture is to hand it a window that is already 4:3. The frontend-blitting
     * engines then find their own fit is an exact one and the two mechanisms
     * agree instead of fighting.
     *
     * <p>The pillars at the sides are the gameplay root's black background
     * showing through, so nothing has to draw them. A source wider than the
     * device is contained inside the parent rather than clipped.
     *
     * <p>Set before the surface exists, from the launch request's system id. A
     * live engine is never resized behind its back: a system whose aspect is
     * not fixed keeps a full-parent surface and is fitted by the engine.
     *
     * @param aspect display aspect (width / height), or 0 to fill the parent
     */
    public void setDisplayAspect(float aspect) {
        float sanitized = aspect > 0f && !Float.isNaN(aspect) &&
                !Float.isInfinite(aspect) ? aspect : 0f;
        if (sanitized == displayAspect) return;
        displayAspect = sanitized;
        requestLayout();
    }

    public float displayAspect() { return displayAspect; }

    public void setFrameRateListener(FrameGenerationRenderer.StatsListener value) {
        frameRateListener = value;
        if (frameGenerator != null) frameGenerator.setStatsListener(value);
    }

    public void setDirectPresentationHz(float value) {
        if (Float.isFinite(value) && value >= 20.0f && value <= 120.0f) {
            directPresentationHz = value;
            if (activeBackend == FrameGenerationBackendPolicy.Backend.DIRECT &&
                    outputSurface != null && outputSurface.isValid())
                requestDirectFrameRate(outputSurface);
        }
    }

    /** Runs once after TextureView observes the engine's first posted buffer. */
    public void setFirstSubmittedFrameListener(Runnable value) {
        firstSubmittedFrameListener = value;
        if (value != null && firstFrameSubmitted) {
            firstSubmittedFrameListener = null;
            value.run();
        }
    }

    /** Status only; backend choice is automatic and is never a user setting. */
    public String activeFrameGenerationBackend() {
        FrameGenerationRenderer renderer = frameGenerator;
        return renderer == null ? activeBackend.label() :
                renderer.activeBackendLabel();
    }

    @Override protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        super.onMeasure(widthMeasureSpec, heightMeasureSpec);
        if (displayAspect <= 0f) return;
        int available = getMeasuredWidth();
        int availableHeight = getMeasuredHeight();
        if (available < 1 || availableHeight < 1) return;
        PresentationGeometry.Rectangle box =
                PresentationGeometry.fit(available, availableHeight, displayAspect);
        setMeasuredDimension(box.width(), box.height());
    }

    public void setListener(Listener listener) {
        this.listener = listener;
        if (runtimePresentationFailed) return;
        bindRuntimeErrorListener();
        if (runtimeFailedGeneration == surfaceGeneration) return;
        if (listener != null && isAvailable() && getSurfaceTexture() != null) {
            ensureSurface(getSurfaceTexture(), getWidth(), getHeight());
            if (renderSurface != null)
                listener.onSurfaceAvailable(renderSurface, getWidth(), getHeight());
        }
    }

    @Override public void onSurfaceTextureAvailable(SurfaceTexture texture,
                                                     int width, int height) {
        if (runtimePresentationFailed) return;
        ensureSurface(texture, width, height);
        if (runtimeFailedGeneration == surfaceGeneration) return;
        if (listener != null && renderSurface != null)
            listener.onSurfaceAvailable(renderSurface, width, height);
    }

    @Override public void onSurfaceTextureSizeChanged(SurfaceTexture texture,
                                                       int width, int height) {
        if (runtimePresentationFailed) return;
        if (runtimeFailedGeneration == surfaceGeneration) return;
        if (frameGenerator != null)
            frameGenerator.resize(width, height, width, height, refreshRate());
        if (listener != null) listener.onSurfaceSizeChanged(width, height);
    }

    @Override public boolean onSurfaceTextureDestroyed(SurfaceTexture texture) {
        // The listener must finish (or abandon within a short bound) any
        // render-thread detach before this returns: the Surface below is
        // released immediately, and a swap still queued against it raises
        // EGL_BAD_SURFACE on GLES sessions.
        if (listener != null) listener.onSurfaceDestroyed();
        releaseSurfaces();
        return true;
    }

    @Override public void onSurfaceTextureUpdated(SurfaceTexture texture) {
        if (firstFrameSubmitted) return;
        firstFrameSubmitted = true;
        Runnable callback = firstSubmittedFrameListener;
        firstSubmittedFrameListener = null;
        if (callback != null) callback.run();
    }

    private void ensureSurface(SurfaceTexture texture, int width, int height) {
        if (runtimePresentationFailed) return;
        if (quarantinedTexture == texture) return;
        quarantinedTexture = null; // A genuinely different texture can retry.
        if (renderSurface != null && renderSurface.isValid()) return;
        releaseSurfaces();
        outputSurface = new Surface(texture);
        // Keep OFF mechanically separate from every generator decision. The
        // exact TextureView Surface becomes the engine Surface; no intermediate
        // EGL context, input Surface, cadence controller, or external runtime
        // is constructed.
        if (launchMode == FrameGenerationSettings.Mode.OFF) {
            requestDirectFrameRate(outputSurface);
            activeBackend = FrameGenerationBackendPolicy.Backend.DIRECT;
            renderSurface = outputSurface;
            Log.i(TAG, "Strict Off uses the selected native panel mode " +
                    "without an intermediate renderer");
            Log.i(TAG, "Frame generation Off; engine owns the display Surface directly " +
                    "surfaceIdentity=true rendererCreated=" +
                    FrameGenerationRendererFactory.createdCount() +
                    " liveRenderers=" + FrameGenerationRendererRegistry.liveCount());
            return;
        }
        if (startupFellBackToDirect) {
            requestDirectFrameRate(outputSurface);
            activeBackend = FrameGenerationBackendPolicy.Backend.DIRECT;
            renderSurface = outputSurface;
            Log.i(TAG, "Retaining Direct after unavailable frame generation " +
                    "surfaceIdentity=true liveRenderers=" +
                    FrameGenerationRendererRegistry.liveCount());
            return;
        }
        FrameGenerationBackendPolicy.Selection selection =
                FrameGenerationSettings.selectBackendForSession(
                        getContext(), launchMode);
        activeBackend = selection.backend;
        if (activeBackend == FrameGenerationBackendPolicy.Backend.DIRECT) {
            startupFellBackToDirect = true;
            Log.i(TAG, "Frame generation disabled by owner; using direct presentation");
            requestDirectFrameRate(outputSurface);
            renderSurface = outputSurface;
            return;
        }
        try {
            frameGenerator = FrameGenerationRendererFactory.create(selection, outputSurface,
                    width, height, width, height, refreshRate(), "primary-legacy",
                    displayId());
            frameGenerator.setStatsListener(frameRateListener);
            bindRuntimeErrorListener();
            renderSurface = frameGenerator.inputSurface();
        } catch (RuntimeException failure) {
            FrameGenerationRenderer partial = frameGenerator;
            frameGenerator = null;
            if (partial != null) {
                try { partial.close(); }
                catch (RuntimeException cleanup) {
                    failure.addSuppressed(new SurfaceOwnershipException(
                            "Partial renderer cleanup failed", cleanup));
                }
            }
            if (SurfaceOwnershipException.isUnsafe(failure)) {
                quarantinedTexture = texture;
                renderSurface = null;
                Log.e(TAG, "Output ownership unresolved; gameplay surface quarantined", failure);
                if (listener != null) listener.onSurfaceStartupError(
                        "The frame generator could not release the display. " +
                        "Return to EmuFusion and reopen the game.", failure);
                return;
            }
            // A compositor failure must not turn a playable game into a black
            // screen. Keep the exact output Surface as a diagnostic bypass;
            // device QA treats this explicit log as a failed frame-gen gate.
            Log.e(TAG, "Frame generation unavailable; using direct presentation", failure);
            startupFellBackToDirect = true;
            activeBackend = FrameGenerationBackendPolicy.Backend.DIRECT;
            frameGenerator = null;
            requestDirectFrameRate(outputSurface);
            renderSurface = outputSurface;
        }
    }

    private void requestDirectFrameRate(Surface surface) {
        if (surface == null || Build.VERSION.SDK_INT < 30) return;
        try {
            int compatibility = directPresentationHz >= 119.5f
                    ? Surface.FRAME_RATE_COMPATIBILITY_DEFAULT
                    : Surface.FRAME_RATE_COMPATIBILITY_FIXED_SOURCE;
            if (Build.VERSION.SDK_INT >= 31)
                surface.setFrameRate(directPresentationHz,
                        compatibility,
                        Surface.CHANGE_FRAME_RATE_ALWAYS);
            else
                surface.setFrameRate(directPresentationHz,
                        compatibility);
            Log.i(TAG, "Requested direct Surface cadence hz=" +
                    directPresentationHz + " compatibility=" + compatibility);
        } catch (RuntimeException failure) {
            Log.w(TAG, "Could not request direct Surface cadence hz=" +
                    directPresentationHz, failure);
        }
    }

    private float refreshRate() {
        Display display = getDisplay();
        return display == null ? 60f : display.getRefreshRate();
    }

    private int displayId() {
        Display display = getDisplay();
        return display == null ? Display.DEFAULT_DISPLAY : display.getDisplayId();
    }

    private void releaseSurfaces() {
        ++surfaceGeneration;
        firstFrameSubmitted = false;
        FrameGenerationRenderer generator = frameGenerator;
        frameGenerator = null;
        if (generator != null) generator.close();
        // The generator owns and releases its input Surface. In direct-bypass
        // mode renderSurface and outputSurface are the same object.
        renderSurface = null;
        Surface output = outputSurface;
        outputSurface = null;
        if (output != null) output.release();
    }

    private void bindRuntimeErrorListener() {
        final FrameGenerationRenderer renderer = frameGenerator;
        final Listener owner = listener;
        final int generation = surfaceGeneration;
        if (renderer == null || owner == null) return;
        renderer.setRuntimeErrorListener((message, cause) -> post(() -> {
            if (renderer != frameGenerator || owner != listener || generation != surfaceGeneration ||
                    runtimePresentationFailed || runtimeFailedGeneration == generation) return;
            runtimePresentationFailed = true;
            runtimeFailedGeneration = generation;
            quarantinedTexture = getSurfaceTexture();
            // Retain renderer/Surface ownership for the normal pause/exit path.
            // A fatal live backend must never become a Direct handoff here.
            owner.onSurfaceRuntimeError(message, cause);
        }));
    }
}
