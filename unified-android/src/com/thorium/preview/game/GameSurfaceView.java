package com.thorium.preview.game;

import android.content.Context;
import android.hardware.display.DisplayManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.view.Display;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;

import com.thorium.lucent.video.PresentationGeometry;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import com.thorium.lucent.video.FrameGenerationBackendPolicy;

/**
 * A real SurfaceFlinger layer for gameplay video, used by the in-process
 * Phase 3 native adapters (Switch/Eden, Wii U/Cemu).
 *
 * <p>{@link GameSurface} publishes frames through a {@link android.view.TextureView}:
 * the engine's buffer becomes a texture that HWUI composites into the Qt
 * window's own surface, and because that TextureView is deliberately
 * non-opaque, every published game frame dirties the whole window. Qt Quick's
 * scene graph is therefore asked to re-render underneath live gameplay for the
 * entire session. On this Adreno driver that ended in a deterministic null
 * dereference inside {@code QSGBatchRenderer::renderBatches()} a few minutes
 * into every Switch run, register-identical across two unrelated Eden builds --
 * a compositing conflict, not anything wrong with the emulator core.
 *
 * <p>A SurfaceView gives the engine its own layer instead, so a published game
 * frame never touches the Qt window at all. The engines that need this are
 * exactly the ones that present from their own GPU thread at their own rate;
 * the libretro and GLES sessions keep the TextureView, whose alpha behaviour
 * their hardware backends depend on.
 *
 * <p>Z order is {@code setZOrderMediaOverlay(true)}, i.e. sublayer -1. Qt's own
 * {@code QtSurface} is a SurfaceView constructed with
 * {@code setZOrderMediaOverlay(false)} (sublayer -2), so gameplay composites
 * above the library and still below this window -- which is what keeps the
 * pause menu, the cheats sheet and the on-screen controls drawable over the
 * game. {@code setZOrderOnTop} would lift the layer above the window and hide
 * all three.
 *
 * <p>No View background is ever set here. A background clears
 * {@code PFLAG_SKIP_DRAW}, which moves the transparent hole punch out of
 * {@code dispatchDraw()} and into {@code draw()}; {@code draw()} punches the
 * hole and then immediately repaints the same rectangle with the background,
 * leaving an opaque window directly over the layer. The gameplay root's own
 * black background is safe because a parent's background is drawn before its
 * children, so the punch still lands on top of it.
 */
public final class GameSurfaceView extends SurfaceView
        implements SurfaceHolder.Callback {
    private static final String TAG = "LucentGameLayer";

    private GameSurface.Listener listener;
    private boolean surfaceLive;
    private volatile Surface outputSurface;
    private volatile Surface engineSurface;
    private volatile FrameGenerationRenderer frameGenerator;
    // Generator startup (EGL context, the dense shader set, and for LSFG a
    // Vulkan transport plus its bounded startup-proof retry) took 3-9 s on
    // the Thor.  surfaceChanged runs inside the window's pre-draw traversal
    // on the UI thread, so a synchronous createGenerator there froze the
    // frontend for that long and any key arriving meanwhile raised
    // "Input dispatching timed out" (ANR dialog over live gameplay,
    // 2026-09-03 17:59 and 18:00, 2026-09-04 03:19).  Startup now runs on
    // this single worker; the engine receives its Surface from the UI
    // thread once the generator exists.  Off keeps its synchronous direct
    // bypass because it constructs nothing.
    private static final ExecutorService GENERATOR_STARTUP =
            Executors.newSingleThreadExecutor(runnable -> {
                Thread thread = new Thread(runnable, "emufusion-generator-startup");
                thread.setDaemon(true);
                return thread;
            });
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    /** Bumped on every surface destroy so a late startup cannot resurrect it. */
    private int surfaceGeneration;
    private int quarantinedSurfaceGeneration = -1;
    // A live presentation failure terminates this game-view session, not just
    // its current Android Surface. Sleep/wake must not allocate a fresh LSFG
    // host while the owning game remains paused behind its fatal-error UI.
    private boolean runtimePresentationFailed;
    private boolean runtimeRecoveryPending;
    private boolean ownerRequestedDirect;
    // A safely retired startup failure selects Direct for this game view,
    // including later Android Surface generations. Re-probing on every wake
    // repeats the same multi-second failure and can strand a resumed game.
    // A new game view may retry the saved owner choice; preferences are untouched.
    private volatile boolean startupFellBackToDirect;
    private volatile boolean generatorStartupPending;
    private boolean lsfgUnavailableNotified;
    private int pendingWidth, pendingHeight;
    private FrameGenerationRenderer.StatsListener frameRateListener;
    private float lastReportedPanelHz;
    private DisplayManager panelDisplayManager;
    private final DisplayManager.DisplayListener panelModeListener =
            new DisplayManager.DisplayListener() {
                @Override public void onDisplayAdded(int id) {}
                @Override public void onDisplayRemoved(int id) {}
                @Override public void onDisplayChanged(int id) {
                    if (id != displayId()) return;
                    propagatePanelRefresh("display-changed");
                }
            };
    private Runnable firstSubmittedFrameListener;
    private double authoritativeSourceHz;
    private double producerTimelineHz;
    private float directPresentationHz = 60.0f;
    private volatile FrameGenerationBackendPolicy.Backend activeBackend =
            FrameGenerationBackendPolicy.Backend.DIRECT;
    /** Immutable owner choice for this Surface generation. */
    private final FrameGenerationSettings.Mode launchMode;
    /** The system's hardware display aspect, or 0 to fill the parent. */
    private float displayAspect;

    public GameSurfaceView(Context context) {
        this(context, FrameGenerationSettings.mode(context));
    }

    public GameSurfaceView(Context context, FrameGenerationSettings.Mode launchMode) {
        super(context);
        this.launchMode = launchMode == null ? FrameGenerationSettings.Mode.OFF :
                launchMode;
        setFocusable(false);
        setZOrderMediaOverlay(true);
        getHolder().addCallback(this);
    }

    /**
     * Shapes the layer to the system's display aspect, exactly as
     * {@link GameSurface#setDisplayAspect(float)} shapes the TextureView.
     *
     * <p>These engines render straight into the Android window they are handed
     * and have no frontend blit to correct, so a window that is already the
     * right shape is the only thing that stops them filling the panel with a
     * stretched picture. The pillars at the sides are the gameplay root's black
     * background, which this layer's hole punch leaves untouched because the
     * punch covers only the layer's own bounds. A wider-than-device source is
     * contained and centred so Android never clips the picture.
     *
     * <p>Set before the surface exists; a live engine is never reshaped behind
     * its back.
     */
    public void setDisplayAspect(float aspect) {
        float sanitized = aspect > 0f && !Float.isNaN(aspect) &&
                !Float.isInfinite(aspect) ? aspect : 0f;
        if (sanitized == displayAspect) return;
        displayAspect = sanitized;
        requestLayout();
    }

    public float displayAspect() { return displayAspect; }

    public int measuredSourceTier() {
        FrameGenerationRenderer generator = frameGenerator;
        return generator != null ? generator.measuredSourceTier() : 0;
    }

    public boolean sourceStreamIrregular() {
        FrameGenerationRenderer generator = frameGenerator;
        return generator != null && generator.sourceStreamIrregular();
    }

    public boolean sourceStreamLightlyHeld() {
        FrameGenerationRenderer generator = frameGenerator;
        return generator != null && generator.sourceStreamLightlyHeld();
    }

    public double sourceUniqueHz() {
        FrameGenerationRenderer generator = frameGenerator;
        return generator != null ? generator.sourceUniqueHz() : 0.0;
    }

    public double panelClockRatio() {
        FrameGenerationRenderer generator = frameGenerator;
        return generator != null ? generator.panelClockRatio() : 1.0;
    }

    public double endpointDriftUsPerSecond() {
        FrameGenerationRenderer generator = frameGenerator;
        return generator != null ? generator.endpointDriftUsPerSecond() : 0.0;
    }

    public long endpointOffsetNs() {
        FrameGenerationRenderer generator = frameGenerator;
        return generator != null ? generator.endpointOffsetNs() : 0L;
    }

    private boolean slotLatticeProducer;

    public void setSlotLatticeProducer(boolean value) {
        slotLatticeProducer = value;
        FrameGenerationRenderer generator = frameGenerator;
        if (generator != null) generator.setSlotLatticeProducer(value);
    }

    public boolean clockAcquisitionInProgress() {
        FrameGenerationRenderer generator = frameGenerator;
        return generator != null && generator.clockAcquisitionInProgress();
    }

    public void onCoreClockLocked() {
        FrameGenerationRenderer generator = frameGenerator;
        if (generator != null) generator.onCoreClockLocked();
    }

    public void setFrameRateListener(FrameGenerationRenderer.StatsListener value) {
        frameRateListener = value;
        if (frameGenerator != null) frameGenerator.setStatsListener(value);
    }

    public void setFirstSubmittedFrameListener(Runnable value) {
        firstSubmittedFrameListener = value;
        if (frameGenerator != null) frameGenerator.setFirstSubmittedFrameListener(value);
    }

    public void setAuthoritativeSourceHz(double value) {
        authoritativeSourceHz = value;
        if (frameGenerator != null) frameGenerator.setAuthoritativeSourceHz(value);
    }

    public void setDirectPresentationHz(float value) {
        if (Float.isFinite(value) && value >= 20.0f && value <= 120.0f) {
            directPresentationHz = value;
            if (activeBackend == FrameGenerationBackendPolicy.Backend.DIRECT &&
                    outputSurface != null && outputSurface.isValid())
                requestDirectFrameRate(outputSurface);
        }
    }

    /** Hardware-core PTS clock; transport provenance, never source authority. */
    public void setProducerTimelineHz(double value) {
        producerTimelineHz = value;
        if (frameGenerator != null) frameGenerator.setProducerTimelineHz(value);
    }

    /** Status only; backend choice is automatic and is never a user setting. */
    public String activeFrameGenerationBackend() {
        FrameGenerationRenderer renderer = frameGenerator;
        return renderer == null ? activeBackend.label() :
                renderer.activeBackendLabel();
    }

    /** True when the producer owns the panel Surface without an intermediary. */
    public boolean usesDirectPresentation() {
        return !generatorStartupPending &&
                activeBackend == FrameGenerationBackendPolicy.Backend.DIRECT &&
                frameGenerator == null;
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

    public void setListener(GameSurface.Listener value) {
        listener = value;
        if (runtimePresentationFailed || generatorStartupPending) return;
        bindRuntimeErrorListener(surfaceGeneration);
        if (quarantinedSurfaceGeneration == surfaceGeneration) return;
        if (value == null || !surfaceLive) return;
        if (engineSurface != null && engineSurface.isValid())
            value.onSurfaceAvailable(engineSurface, getWidth(), getHeight());
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {
        // Deliberately silent. surfaceChanged always follows immediately with
        // the real geometry, and an engine handed a 0x0 window configures a
        // 0x0 swapchain it never recovers from.
    }

    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        try {
            panelDisplayManager = (DisplayManager)
                    getContext().getSystemService(Context.DISPLAY_SERVICE);
            if (panelDisplayManager != null)
                panelDisplayManager.registerDisplayListener(
                        panelModeListener, getHandler());
        } catch (RuntimeException failure) {
            Log.w(TAG, "Panel mode listener unavailable", failure);
            panelDisplayManager = null;
        }
    }

    @Override protected void onDetachedFromWindow() {
        if (panelDisplayManager != null) {
            try { panelDisplayManager.unregisterDisplayListener(panelModeListener); }
            catch (RuntimeException ignored) {}
            panelDisplayManager = null;
        }
        super.onDetachedFromWindow();
    }

    /**
     * Pushes the panel's current refresh rate to the renderer when it moves
     * by a whole mode (60 <-> 120).  The window's 120-Hz request lands after
     * the Surface exists on the Thor, so the generator must follow the real
     * panel rather than the rate it happened to read at creation.
     */
    private void propagatePanelRefresh(String reason) {
        FrameGenerationRenderer generator = frameGenerator;
        if (generator == null) return;
        float hz = rendererRefreshRate();
        if (!(hz > 0f) || Math.abs(hz - lastReportedPanelHz) < 0.5f) return;
        Log.i(TAG, "Panel refresh changed reason=" + reason +
                " previousHz=" + lastReportedPanelHz + " hz=" + hz);
        lastReportedPanelHz = hz;
        generator.setPanelRefreshHz(hz);
    }

    @Override public void surfaceChanged(SurfaceHolder holder, int format,
                                          int width, int height) {
        surfaceLive = true;
        if (runtimePresentationFailed) return;
        if (quarantinedSurfaceGeneration == surfaceGeneration) return;
        Log.i(TAG, "Gameplay layer ready " + width + "x" + height);
        if (generatorStartupPending) {
            // The Surface was re-sized while its generator is still starting;
            // the completion below hands the engine the latest geometry.
            pendingWidth = width;
            pendingHeight = height;
            return;
        }
        boolean first = engineSurface == null || !engineSurface.isValid();
        if (first && launchMode != FrameGenerationSettings.Mode.OFF &&
                !startupFellBackToDirect) {
            startGeneratorAsync(holder.getSurface(), width, height);
            return;
        }
        if (first) {
            lastReportedPanelHz = rendererRefreshRate();
            createGenerator(holder.getSurface(), width, height);
            // The mode switch may already have completed between the
            // creation read and now; reconcile once immediately.
            propagatePanelRefresh("surface-changed");
        } else if (frameGenerator != null) {
            float hz = rendererRefreshRate();
            lastReportedPanelHz = hz;
            frameGenerator.resize(width, height, width, height, hz);
        }
        if (listener != null) {
            if (first) listener.onSurfaceAvailable(engineSurface, width, height);
            else listener.onSurfaceSizeChanged(width, height);
        }
    }

    /**
     * Constructs the frame generator off the UI thread, then publishes the
     * engine Surface from the UI thread.  A destroy that lands while the
     * startup is still running invalidates the generation; the finished
     * generator is then closed instead of being handed to an engine whose
     * window is gone.
     */
    private void startGeneratorAsync(Surface output, int width, int height) {
        final int generation = surfaceGeneration;
        generatorStartupPending = true;
        pendingWidth = width;
        pendingHeight = height;
        lastReportedPanelHz = rendererRefreshRate();
        final long startedMs = android.os.SystemClock.elapsedRealtime();
        GENERATOR_STARTUP.execute(() -> {
            RuntimeException problem = null;
            try {
                createGenerator(output, width, height);
            } catch (RuntimeException failure) {
                problem = failure;
            }
            final RuntimeException startupProblem = problem;
            mainHandler.post(() -> finishGeneratorStartup(generation, output,
                    width, height, startupProblem, startedMs));
        });
    }

    private void finishGeneratorStartup(int generation, Surface output,
                                        int createdWidth, int createdHeight,
                                        RuntimeException problem, long startedMs) {
        long elapsedMs = android.os.SystemClock.elapsedRealtime() - startedMs;
        if (generation != surfaceGeneration || !surfaceLive || runtimePresentationFailed ||
                ownerRequestedDirect) {
            Log.w(TAG, "Generator startup finished after cancellation;" +
                    " discarding elapsedMs=" + elapsedMs);
            retireCancelledStartup(problem);
            return;
        }
        generatorStartupPending = false;
        if (problem != null) {
            if (SurfaceOwnershipException.isUnsafe(problem)) {
                // A cancelled native initializer may still be unwinding on its
                // owner. Never hand this Surface to an engine or retry on resize.
                quarantinedSurfaceGeneration = generation;
                engineSurface = null;
                frameGenerator = null;
                Log.e(TAG, "Output ownership unresolved; gameplay surface quarantined", problem);
                if (listener != null) listener.onSurfaceStartupError(
                        "The frame generator could not release the display. " +
                        "Return to EmuFusion and reopen the game.", problem);
                return;
            }
            // createGenerator already falls open to the direct Surface on
            // every failure it anticipates; this is the unanticipated case.
            Log.e(TAG, "Generator startup failed; using direct presentation", problem);
            startupFellBackToDirect = true;
            activeBackend = FrameGenerationBackendPolicy.Backend.DIRECT;
            frameGenerator = null;
            outputSurface = output;
            requestDirectFrameRate(output);
            engineSurface = output;
        }
        Log.i(TAG, "Generator startup completed off the UI thread elapsedMs=" +
                elapsedMs + " backend=" + activeFrameGenerationBackend());
        // The mode switch may already have completed between the creation
        // read and now; reconcile once immediately.
        propagatePanelRefresh("surface-changed");
        FrameGenerationRenderer generator = frameGenerator;
        if (generator != null) {
            // Setters that arrived while the generator did not exist yet.
            bindRuntimeErrorListener(generation);
            generator.setAuthoritativeSourceHz(authoritativeSourceHz);
            generator.setProducerTimelineHz(producerTimelineHz);
            generator.setStatsListener(frameRateListener);
            generator.setFirstSubmittedFrameListener(firstSubmittedFrameListener);
            if (slotLatticeProducer) generator.setSlotLatticeProducer(true);
            if (pendingWidth != createdWidth || pendingHeight != createdHeight)
                generator.resize(pendingWidth, pendingHeight, pendingWidth,
                        pendingHeight, lastReportedPanelHz);
        }
        if (listener != null)
            listener.onSurfaceAvailable(engineSurface, pendingWidth, pendingHeight);
    }

    /** No engine has received this startup's input Surface yet. */
    private void retireCancelledStartup(RuntimeException problem) {
        final FrameGenerationRenderer cancelled = frameGenerator;
        frameGenerator = null;
        engineSurface = null;
        outputSurface = null;
        // Keep startup admission closed until THIS result has retired. A
        // wake/resize may update the desired Surface while cleanup runs, but
        // must not publish another generator into these shared owner fields.
        GENERATOR_STARTUP.execute(() -> {
            RuntimeException retirementProblem =
                    SurfaceOwnershipException.isUnsafe(problem) ? problem : null;
            try {
                if (cancelled != null) cancelled.close();
            } catch (RuntimeException failure) {
                if (retirementProblem == null)
                    retirementProblem = new SurfaceOwnershipException(
                            "Cancelled frame generator did not release its output", failure);
                else retirementProblem.addSuppressed(failure);
            }
            final RuntimeException failure = retirementProblem;
            mainHandler.post(() -> {
                generatorStartupPending = false;
                if (failure != null) {
                    // The original initializer/close may still own the native
                    // output. Do not retry or hand it to a Direct producer.
                    runtimePresentationFailed = true;
                    quarantinedSurfaceGeneration = surfaceGeneration;
                    Log.e(TAG, "Cancelled startup ownership unresolved", failure);
                    if (listener != null) listener.onSurfaceStartupError(
                            "The frame generator could not release the display. " +
                            "Return to EmuFusion and reopen the game.", failure);
                    return;
                }
                if (surfaceLive && !runtimePresentationFailed)
                    surfaceChanged(getHolder(), 0, pendingWidth, pendingHeight);
            });
        });
    }

    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        surfaceLive = false;
        ++surfaceGeneration;
        if (!generatorStartupPending && !runtimeRecoveryPending &&
                frameGenerator != null && listener != null) {
            final FrameGenerationRenderer retiring = frameGenerator;
            generatorStartupPending = true;
            frameGenerator = null;
            engineSurface = null;
            outputSurface = null;
            // Native startup can still be using this input after Android's
            // short detach wait expires. Keep it alive until actual producer
            // acknowledgement, and block a quick wake from replacing it.
            listener.retireSurfaceRenderer(retiring, failure -> mainHandler.post(() -> {
                generatorStartupPending = false;
                if (failure != null) {
                    frameGenerator = retiring; // retain ownership for normal exit
                    runtimePresentationFailed = true;
                    quarantinedSurfaceGeneration = surfaceGeneration;
                    if (listener != null) listener.onSurfaceStartupError(
                            "The game could not release its display. Return to EmuFusion.", failure);
                    return;
                }
                if (surfaceLive && !runtimePresentationFailed)
                    surfaceChanged(getHolder(), 0, pendingWidth, pendingHeight);
            }));
            return;
        }
        // The Surface is disconnected the moment this returns, so the listener
        // has to have parked the engine's render owner before it does.
        if (listener != null) listener.onSurfaceDestroyed();
        // An in-flight factory still writes its result on the startup worker.
        // Its completion owns cancellation/retirement, including a quick wake.
        // Clearing admission here let an old completion close a newer renderer.
        if (!generatorStartupPending) releaseGenerator();
    }

    private void createGenerator(Surface output, int width, int height) {
        releaseGenerator();
        outputSurface = output;
        // OFF is an unconditional transport bypass. Resolve it before looking
        // for optional payloads, qualification switches, or renderer policy so
        // none of those mechanisms can put a producer Surface in the path.
        if (launchMode == FrameGenerationSettings.Mode.OFF) {
            requestDirectFrameRate(output);
            activeBackend = FrameGenerationBackendPolicy.Backend.DIRECT;
            engineSurface = output;
            Log.i(TAG, "Strict Off uses the selected native panel mode " +
                    "without an intermediate renderer");
            Log.i(TAG, "Frame generation Off; engine owns the display Surface directly " +
                    "surfaceIdentity=true rendererCreated=" +
                    FrameGenerationRendererFactory.createdCount() +
                    " liveRenderers=" + FrameGenerationRendererRegistry.liveCount());
            return;
        }
        if (startupFellBackToDirect) {
            requestDirectFrameRate(output);
            activeBackend = FrameGenerationBackendPolicy.Backend.DIRECT;
            engineSurface = output;
            Log.i(TAG, "Retaining Direct after unavailable frame generation " +
                    "surfaceIdentity=true liveRenderers=" +
                    FrameGenerationRendererRegistry.liveCount());
            return;
        }
        FrameGenerationSettings.QualificationTransport qualification =
                FrameGenerationSettings.qualificationTransport(
                        getContext(), displayId(), launchMode);
        // Explicit LSFG selection authorizes that transport, not a different
        // experimental generator. Its capability/deadline checks remain
        // mandatory; failure must hand back the exact engine-owned Surface.
        if (qualification != null && !qualificationProofEnabled())
            Log.i(TAG, qualification.label +
                    " requested without shell proof mode; attaching on the" +
                    " owner's explicit selection");
        if (qualification != null) {
            activeBackend = qualification.backend;
            RuntimeException lastFailure = null;
            // SurfaceControl occasionally reports the just-replaced endpoint
            // during LSFG's startup proof even though the next clean instance
            // passes immediately. Recreate the whole transport once so no
            // rejected Vulkan/SurfaceControl state is reused. This remains
            // strictly bounded: two failures fall open to the direct Surface.
            for (int attempt = 1; attempt <= 2; ++attempt) {
                try {
                    frameGenerator =
                            FrameGenerationRendererFactory.createExternalQualification(
                                    qualification.factory, output,
                                    width, height, width, height,
                                    rendererRefreshRate(),
                                    "primary", displayId(),
                                    // The user has explicitly selected LSFG in the
                                    // three-way setting. Do not require a hidden
                                    // shell qualification switch on top of that
                                    // visible consent; transport capability and
                                    // deadline failures still fall closed.
                                    () -> true);
                    frameGenerator.setAuthoritativeSourceHz(authoritativeSourceHz);
                    frameGenerator.setProducerTimelineHz(producerTimelineHz);
                    frameGenerator.setStatsListener(frameRateListener);
                    if (slotLatticeProducer) frameGenerator.setSlotLatticeProducer(true);
                    frameGenerator.setFirstSubmittedFrameListener(
                            firstSubmittedFrameListener);
                    Surface input = frameGenerator.inputSurface();
                    if (input == null || !input.isValid())
                        throw new IllegalStateException("Frame generator input Surface is unavailable");
                    engineSurface = input;
                    Log.w(TAG, qualification.label +
                            " qualification transport active attempt=" + attempt + "; " +
                            "product backend assessment remains unqualified");
                    return;
                } catch (RuntimeException failure) {
                    retireFailedGenerator(failure);
                    if (SurfaceOwnershipException.isUnsafe(failure)) throw failure;
                    lastFailure = failure;
                    if (attempt == 1) {
                        Log.w(TAG, qualification.label +
                                " startup proof failed; retrying with a clean transport",
                                failure);
                    }
                }
            }
            Log.e(TAG, qualification.label +
                    " qualification unavailable after bounded retry; using exact direct Surface",
                    lastFailure);
            useDirectAfterUnavailableLsfg(output);
            return;
        }
        if (launchMode == FrameGenerationSettings.Mode.LSFG) {
            Log.e(TAG, "Selected LSFG transport is unavailable; using exact direct Surface");
            useDirectAfterUnavailableLsfg(output);
            return;
        }
        FrameGenerationBackendPolicy.Selection selection =
                FrameGenerationSettings.selectBackendForSession(
                        getContext(), launchMode);
        activeBackend = selection.backend;
        if (activeBackend == FrameGenerationBackendPolicy.Backend.DIRECT) {
            startupFellBackToDirect = true;
            Log.i(TAG, "Frame generation disabled by owner; using direct presentation");
            requestDirectFrameRate(output);
            engineSurface = output;
            return;
        }
        try {
            frameGenerator = FrameGenerationRendererFactory.create(selection, output,
                    width, height, width, height, refreshRate(), "primary", displayId(),
                    this::qualificationProofEnabled, this::densePyramidEnabled,
                    this::denseV27ReducedAnalysisEnabled,
                    this::denseV28ReducedAnalysisEnabled);
            frameGenerator.setAuthoritativeSourceHz(authoritativeSourceHz);
            frameGenerator.setProducerTimelineHz(producerTimelineHz);
            frameGenerator.setStatsListener(frameRateListener);
            frameGenerator.setFirstSubmittedFrameListener(firstSubmittedFrameListener);
            Surface input = frameGenerator.inputSurface();
            if (input == null || !input.isValid())
                throw new IllegalStateException("Frame generator input Surface is unavailable");
            engineSurface = input;
        } catch (RuntimeException failure) {
            retireFailedGenerator(failure);
            if (SurfaceOwnershipException.isUnsafe(failure)) throw failure;
            Log.e(TAG, "Frame generation unavailable; using direct presentation", failure);
            startupFellBackToDirect = true;
            activeBackend = FrameGenerationBackendPolicy.Backend.DIRECT;
            frameGenerator = null;
            requestDirectFrameRate(output);
            engineSurface = output;
        }
    }

    private void retireFailedGenerator(RuntimeException originalFailure) {
        FrameGenerationRenderer partial = frameGenerator;
        frameGenerator = null;
        if (partial == null) return;
        try { partial.close(); }
        catch (RuntimeException cleanup) {
            originalFailure.addSuppressed(new SurfaceOwnershipException(
                    "Partial renderer cleanup failed", cleanup));
        }
    }

    private void useDirectAfterUnavailableLsfg(Surface output) {
        startupFellBackToDirect = true;
        frameGenerator = null;
        activeBackend = FrameGenerationBackendPolicy.Backend.DIRECT;
        requestDirectFrameRate(output);
        engineSurface = output;
        Log.i(TAG, "LSFG fallback surfaceIdentity=true liveRenderers=" +
                FrameGenerationRendererRegistry.liveCount());
        if (!lsfgUnavailableNotified) {
            lsfgUnavailableNotified = true;
            mainHandler.post(() -> android.widget.Toast.makeText(getContext(),
                    "LSFG could not start. Using direct playback with frame generation off.",
                    android.widget.Toast.LENGTH_LONG).show());
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

    /** LSFG's qualified 20->40 path needs a 120-Hz three-scan lattice. */
    private float rendererRefreshRate() {
        Display display = getDisplay();
        if (launchMode != FrameGenerationSettings.Mode.LSFG || display == null)
            return refreshRate();
        float maximum = display.getRefreshRate();
        for (Display.Mode mode : display.getSupportedModes()) {
            float candidate = mode.getRefreshRate();
            if (Float.isFinite(candidate) && candidate <= 120.5f)
                maximum = Math.max(maximum, candidate);
        }
        return maximum;
    }

    private int displayId() {
        Display display = getDisplay();
        return display == null ? Display.DEFAULT_DISPLAY : display.getDisplayId();
    }

    /** Shell-only qualification instrumentation; never a user-facing option. */
    private boolean qualificationProofEnabled() {
        try {
            return Settings.Global.getInt(getContext().getContentResolver(),
                    "emufusion_framegen_proof", 0) == 1;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    /**
     * The dense optical-flow pyramid is the product generator for the top
     * panel, not a proof-only experiment.
     *
     * <p>Every physically qualified pass on this device (GC/PS2/PSP/Wii/Wii U
     * /Switch/N64, 2026-08) ran the dense pipeline, while owner launches were
     * silently routed to the legacy v22 estimator the code itself documents
     * as producing doubled/ghosted imagery. The path that is qualified is the
     * path the owner gets. Proof mode still governs evidence capture only.
     * The lower panel remains direct; a shell opt-out global keeps the legacy
     * estimator reachable for diagnostics.</p>
     */
    private boolean densePyramidEnabled() {
        if (displayId() != Display.DEFAULT_DISPLAY) return false;
        try {
            if (Settings.Global.getInt(getContext().getContentResolver(),
                    "emufusion_framegen_dense_pyramid", 1) == 0)
                return false;
        } catch (RuntimeException ignored) {}
        return true;
    }

    /** Raw shell preselection used only before the generator allocates resources. */
    private boolean rawDensePyramidRequested() {
        // The physical top panel owns the interpolation budget. Dual-screen
        // cores may continue presenting their lower endpoint stream, but the
        // secondary display must not run another 38-pass dense solve that
        // generates no visible intermediates and steals the top panel's GPU
        // deadline (physically observed on ALBW, 2026-08-20).
        if (displayId() != Display.DEFAULT_DISPLAY) return false;
        try {
            return Settings.Global.getInt(getContext().getContentResolver(),
                    "emufusion_framegen_dense_pyramid", 0) == 1;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    /** Pre-launch-only v27 qualification arm; default and v26 stay unchanged. */
    private boolean denseV27ReducedAnalysisEnabled() {
        // Proof is intentionally not consulted here: the physical harness
        // clears proof until gameplay is ready, but allocation identity is
        // immutable and must be selected when the generator is constructed.
        // Actual activation still requires the separately gated live switch.
        if (!rawDensePyramidRequested()) return false;
        try {
            return Settings.Global.getInt(getContext().getContentResolver(),
                    "emufusion_framegen_dense_v27_192", 0) == 1;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    /**
     * The v28 128x72 reduced-analysis variant is the product dense variant:
     * it is the variant every 2026-08 physical pass ran. A shell v27 arm still
     * preselects v27 for diagnostics; an explicit v28 opt-out global falls
     * back to the base v26 analysis.
     */
    private boolean denseV28ReducedAnalysisEnabled() {
        if (!densePyramidEnabled()) return false;
        if (denseV27ReducedAnalysisEnabled()) return false;
        try {
            return Settings.Global.getInt(getContext().getContentResolver(),
                    "emufusion_framegen_dense_v28_160", 1) == 1;
        } catch (RuntimeException ignored) {
            return true;
        }
    }

    private void releaseGenerator() {
        if (runtimeRecoveryPending) {
            // Recovery owns retirement only after its producer barrier succeeds.
            // Android may destroy the output while that worker is waiting; do
            // not close the still-live input queue from the UI thread as well.
            engineSurface = null;
            outputSurface = null;
            return;
        }
        FrameGenerationRenderer generator = frameGenerator;
        frameGenerator = null;
        if (generator != null) generator.close();
        engineSurface = null;
        // SurfaceHolder owns outputSurface; retaining the reference only keeps
        // direct-bypass identity explicit and it must never be released here.
        outputSurface = null;
    }

    /** Latch Off for this view, including constructors not yet published. */
    void requestOwnerDirect() {
        ownerRequestedDirect = true;
        startupFellBackToDirect = true;
    }

    /** Owner-requested Off uses the same acknowledged retirement as recovery. */
    FrameGenerationRenderer beginOwnerDirectRecovery() {
        if (generatorStartupPending || runtimeRecoveryPending || frameGenerator == null)
            return null;
        runtimeRecoveryPending = true;
        return frameGenerator;
    }

    /** UI owner claims exactly the renderer whose live failure was delivered. */
    FrameGenerationRenderer beginRuntimeDirectRecovery() {
        if (!runtimePresentationFailed || runtimeRecoveryPending || frameGenerator == null)
            return null;
        runtimeRecoveryPending = true;
        return frameGenerator;
    }

    /** Called on UI only after the worker completed (or refused) retirement. */
    boolean finishRuntimeDirectRecovery(FrameGenerationRenderer renderer,
            boolean retired, boolean rebind) {
        if (!runtimeRecoveryPending || frameGenerator != renderer) return false;
        runtimeRecoveryPending = false;
        if (!retired) return false; // keep ownership reachable for normal exit
        frameGenerator = null;
        engineSurface = null;
        outputSurface = null;
        if (!rebind) return true;
        startupFellBackToDirect = true;
        runtimePresentationFailed = false;
        quarantinedSurfaceGeneration = -1;
        activeBackend = FrameGenerationBackendPolicy.Backend.DIRECT;
        if (surfaceLive)
            surfaceChanged(getHolder(), 0, getWidth(), getHeight());
        return true;
    }

    private void bindRuntimeErrorListener(int generation) {
        final FrameGenerationRenderer renderer = frameGenerator;
        final GameSurface.Listener owner = listener;
        if (renderer == null || owner == null) return;
        renderer.setRuntimeErrorListener((message, cause) -> mainHandler.post(() -> {
            if (!surfaceLive || generation != surfaceGeneration || renderer != frameGenerator ||
                    owner != listener || runtimePresentationFailed ||
                    quarantinedSurfaceGeneration == generation) return;
            runtimePresentationFailed = true;
            quarantinedSurfaceGeneration = generation;
            // No close, Surface release, or Direct rebinding from the render
            // owner. Keep the failed generator reachable for normal retirement.
            owner.onSurfaceRuntimeError(message, cause);
        }));
    }
}
