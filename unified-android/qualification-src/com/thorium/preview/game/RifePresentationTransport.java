package com.thorium.preview.game;

import android.content.Context;
import android.graphics.PixelFormat;
import android.hardware.HardwareBuffer;
import android.media.Image;
import android.media.ImageReader;
import android.opengl.EGL14;
import android.opengl.EGL15;
import android.opengl.EGLDisplay;
import android.opengl.EGLSync;
import android.opengl.GLES20;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Surface;

import com.emufusion.rifebenchmark.NativeRifeBridge;
import com.thorium.lucent.video.ExternalGeneratedContentProof;
import com.thorium.lucent.video.FrameGenerationPreparationRequest;
import com.thorium.lucent.video.FrameGenerationPresentationRequest;
import com.thorium.lucent.video.PhysicalPresentationDeadline;

import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Qualification-only nonblocking RIFE endpoint/presentation transport.
 *
 * <p>The caller remains the sole source/cadence authority. It renders each
 * already-classified immutable endpoint into {@link #endpointSurface()} with
 * that endpoint's timestamp, announces the exact sequence/timestamp first,
 * and submits only {@link FrameGenerationPresentationRequest} values selected
 * by EmuFusion's controller. This class never runs a capture loop or chooses a
 * frame rate, endpoint, phase, or retry/catch-up presentation.</p>
 */
public final class RifePresentationTransport
        implements ExternalFrameGenerationTransport, ImageReader.OnImageAvailableListener {
    private static final String TAG = "EmuFusionRifeTransport";
    private static final int MAX_IMAGES = 8;
    private static final int MAX_PENDING_PRESENTATIONS = 16;
    private static final int MIN_TRANSITION_SAFE_SWAPCHAIN_IMAGES = 5;
    private static final int VK_PRESENT_MODE_FIFO_KHR = 2;
    private static final int WSI_ACQUIRE_STARVATION_MIN_ATTEMPTS = 8;
    private static final long WSI_ACQUIRE_STARVATION_MIN_NS = 100_000_000L;
    private static final long STARTUP_SURFACE_DRAIN_SLOW_NS = 2_000_000_000L;
    private static final long STARTUP_SURFACE_DRAIN_TIMEOUT_NS = 8_000_000_000L;
    private final Handler owner;
    private final int width;
    private final int height;
    private final int analysisWidth;
    private final int analysisHeight;
    private final RifeQualificationRuntime.Prepared prepared;
    private final NativeRifeBridge bridge;
    private final NativeRifeBridge secondaryBridge;
    private final ImageReader reader;
    private final Surface endpointSurface;
    private final boolean surfaceControlPresentation;
    private final boolean appOwnedPresentation;
    private final long refreshDurationNs;
    private final int surfaceMinImageCount;
    private final int surfaceMaxImageCount;
    private final int requestedImageCount;
    private final int swapchainImageCount;
    /**
     * Per-AHardwareBuffer Vulkan import creation is driver work that measured
     * tens of milliseconds cold on Thor.  It must never execute on the EGL /
     * Choreographer owner or inside a physical presentation request.
     */
    private final ExecutorService preparationWorker =
            Executors.newSingleThreadExecutor(runnable -> {
                Thread thread = new Thread(
                        () -> NativeRifeBridge.runPreparationWorker(runnable),
                        "EmuFusion-RIFE-prepare");
                thread.setDaemon(true);
                return thread;
            });
    private final ArrayDeque<ExpectedEndpoint> expected = new ArrayDeque<>();
    // ImageReader.acquireNextImage waits on GPU fences on Thor. Never run it
    // on the Choreographer/GL owner. One outstanding acquisition preserves
    // order; its image is still charged to the owner's expected queue.
    private final ExecutorService acquisitionWorker =
            Executors.newSingleThreadExecutor(runnable -> {
                Thread thread = new Thread(runnable, "EmuFusion-RIFE-acquire");
                thread.setDaemon(true);
                return thread;
            });
    private static final class AcquiredEndpoint {
        final Image image;
        final RuntimeException failure;
        AcquiredEndpoint(Image image, RuntimeException failure) {
            this.image = image;
            this.failure = failure;
        }
    }
    private final AtomicReference<AcquiredEndpoint> acquiredEndpoint =
            new AtomicReference<>();
    private boolean acquisitionInFlight;
    /** Explicit GL-before-compute dependency; only the worker may wait. */
    private static final class DisplaySubmissionFence {
        final EGLDisplay display;
        final EGLSync sync;
        final Thread creator;
        boolean destroyed;

        private DisplaySubmissionFence(EGLDisplay display, EGLSync sync) {
            this.display = display;
            this.sync = sync;
            creator = Thread.currentThread();
        }

        static DisplaySubmissionFence capture() {
            EGLDisplay display = EGL14.eglGetCurrentDisplay();
            if (display == EGL14.EGL_NO_DISPLAY)
                throw new IllegalStateException("RIFE display dependency has no EGL owner");
            EGLSync sync = EGL15.eglCreateSync(display, EGL15.EGL_SYNC_FENCE,
                    new long[] { EGL14.EGL_NONE }, 0);
            if (sync == null || sync == EGL15.EGL_NO_SYNC)
                throw new IllegalStateException("RIFE display dependency creation failed");
            // Flush on the context owner; the waiting thread has no GL context.
            GLES20.glFlush();
            return new DisplaySubmissionFence(display, sync);
        }

        void awaitOnWorker() {
            if (Thread.currentThread() == creator)
                throw new IllegalStateException("RIFE display dependency waited on owner");
            try {
                // Bound both failure and teardown latency. Timeout fails the
                // preparation; it never authorizes an unordered GPU submit.
                int result = EGL15.eglClientWaitSync(display, sync, 0, 100_000_000L);
                if (result != EGL15.EGL_CONDITION_SATISFIED)
                    throw new IllegalStateException("RIFE display dependency did not complete: " + result);
            } finally {
                destroy();
            }
        }

        void destroy() {
            if (!destroyed) {
                destroyed = true;
                if (!EGL15.eglDestroySync(display, sync))
                    throw new IllegalStateException("RIFE display dependency release failed");
            }
        }
    }
    private final LinkedHashMap<Long, RetainedEndpoint> retained =
            new LinkedHashMap<>();
    private final ArrayDeque<SubmittedPresentation> submitted = new ArrayDeque<>();
    /** Keyed by the right endpoint; left is always right-1. */
    private final LinkedHashMap<Long, GenerationReadiness> pairReadiness =
            new LinkedHashMap<>();
    private boolean generatedRatePathActive;
    private boolean privateGenerationPipelineWarm;
    private long lookaheadProofSubmittedCount;
    private long lookaheadProofCompletedCount;
    private long lastExpectedSequence;
    private long lastExpectedTimestampNs;
    private long nextPresentId = 1L;
    private long nextProofSequence = 1L;
    private long timelineEpoch = 1L;
    private long requestSessionEpoch;
    private long requestPresentationEpoch;
    private boolean nativePending;
    private SubmittedPresentation nativeInFlight;
    private boolean nativeReleaseScheduled;
    private long nativeReleaseNotBeforeNs;
    private long nativeReleaseDeadlineNs;
    private long nativeReleaseCount;
    private long nativeReleaseLatenessMaxNs;
    private long directLifecycleTimingCount;
    private boolean preparationInFlight;
    private Runnable preparationCapacityListener;

    @Override public void setPreparationCapacityListener(Runnable listener) {
        requireOwner();
        preparationCapacityListener = listener;
    }
    // Owner-thread identity retained until the worker completion callback runs.
    private PreparedPresentation recordingPresentation;
    private PreparedPresentation preparedPresentation;
    private PreparedPresentation queuedPreparation;
    private FrameGenerationPreparationRequest lastStartedPreparationRequest;
    private final LinkedHashMap<Long, PreparedPresentation> readyOutputs = new LinkedHashMap<>();
    private final LinkedHashMap<Long, Boolean> deferredOutputReleases = new LinkedHashMap<>();
    private boolean cachedOutputDiscardPending;
    private long minimumRetainedOutputSequence;
    private final java.util.HashSet<Long> ownedOutputTextures = new java.util.HashSet<>();
    // One bridge has three native output carriers. Keep ownership per proof,
    // not in a single mutable "current output" slot while frames await display.
    private final LinkedHashMap<Long, AppOwnedOutput> boundAppOwnedOutputs =
            new LinkedHashMap<>();
    private final LinkedHashMap<Long, Integer> boundTextureIds = new LinkedHashMap<>();
    private final LinkedHashMap<Long, NativeRifeBridge> boundOutputBridges = new LinkedHashMap<>();
    private long preparedEndpointCount;
    private long preparationWallMaxNs;
    /**
     * A cold AHardwareBuffer import measured 20-36 ms on Thor and therefore
     * cannot occur after a 60->120 path starts. Count only consecutive native
     * cache hits; one full maximum ImageReader rotation proves that every
     * carrier needed by the steady endpoint stream is already imported.
     */
    private int consecutiveCachedEndpointCount;
    private boolean endpointImportCacheWarm;
    private long endpointDiscontinuities;
    private long presentationDiscontinuities;
    private int consecutiveWsiAcquireNotReady;
    private long wsiAcquireStarvationStartNs;
    private boolean wsiAcquireStarvationActive;
    private long nextWsiAcquireProbeNs;
    private int startupSurfaceProbeTarget;
    private int startupSurfaceProbeSubmitted;
    private int startupSurfaceProbeCompleted;
    private int startupSurfaceProbeAcquireNotReady;
    private long startupSurfaceProbeStartNs;
    private boolean startupSurfaceProbePending;
    private boolean startupSurfaceProbeComplete;
    private boolean startupSurfaceProbeSlowLogged;
    private boolean closed;
    private boolean teardownComplete;
    private boolean primaryTransportDrained;
    private boolean secondaryTransportDrained;
    private RuntimeException fatalFailure;

    public static RifePresentationTransport open(
            Context context, Surface outputSurface, Handler owner,
            int width, int height, int analysisWidth,
            int analysisHeight) throws Exception {
        if (outputSurface == null || !outputSurface.isValid())
            throw new IllegalArgumentException("valid RIFE output Surface required");
        if (owner == null || width < 1 || height < 1 ||
                analysisWidth < 1 || analysisHeight < 1 ||
                analysisWidth > width || analysisHeight > height ||
                (long) analysisWidth * height != (long) width * analysisHeight)
            throw new IllegalArgumentException("RIFE transport owner/size is invalid");
        RifeQualificationRuntime.Prepared prepared =
                RifeQualificationRuntime.open(context);
        boolean success = false;
        try {
            RifePresentationTransport transport = new RifePresentationTransport(
                    outputSurface, owner, width, height,
                    analysisWidth, analysisHeight, prepared);
            success = true;
            return transport;
        } finally {
            if (!success) prepared.close();
        }
    }

    private RifePresentationTransport(
            Surface outputSurface, Handler owner, int width, int height,
            int analysisWidth, int analysisHeight,
            RifeQualificationRuntime.Prepared prepared) throws Exception {
        this.owner = owner;
        this.width = width;
        this.height = height;
        this.analysisWidth = analysisWidth;
        this.analysisHeight = analysisHeight;
        this.prepared = prepared;
        this.bridge = prepared.bridge;
        warmPresentationModelBeforeSurface(analysisWidth, analysisHeight);
        long usage = HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE |
                HardwareBuffer.USAGE_GPU_COLOR_OUTPUT;
        reader = ImageReader.newInstance(
                width, height, PixelFormat.RGBA_8888, MAX_IMAGES, usage);
        endpointSurface = reader.getSurface();
        reader.setOnImageAvailableListener(this, owner);
        JSONObject privateOutput = new JSONObject(
                bridge.createPrivateOutputTransport(width, height));
        if (!privateOutput.getBoolean("created") ||
                !privateOutput.getBoolean("appOwnedPresentation") ||
                privateOutput.getBoolean("visibleSurface") ||
                privateOutput.getBoolean("vulkanSwapchain") ||
                privateOutput.getBoolean("surfaceControl") ||
                !privateOutput.getBoolean("zeroWaitReadyPoll") ||
                !privateOutput.getBoolean("eglFenceRecycle") ||
                privateOutput.getInt("outputBufferCount") != 3 ||
                privateOutput.getInt("format") <= 0 ||
                privateOutput.getInt("width") != width ||
                privateOutput.getInt("height") != height)
            throw new UnsupportedOperationException(
                    "RIFE private completed-image self-test failed");
        refreshDurationNs = 0L;
        surfaceMinImageCount = 0;
        surfaceMaxImageCount = 0;
        requestedImageCount = 0;
        swapchainImageCount = 0;
        surfaceControlPresentation = false;
        appOwnedPresentation = true;
        NativeRifeBridge second = new NativeRifeBridge(bridge);
        try {
            JSONObject secondOutput = new JSONObject(second.createPrivateOutputTransport(width, height));
            if (!secondOutput.getBoolean("created") || secondOutput.getInt("outputBufferCount") != 3 ||
                    !secondOutput.getBoolean("appOwnedPresentation"))
                throw new IllegalStateException("RIFE secondary output pool initialization failed");
        } catch (Exception failure) {
            second.close();
            throw failure;
        }
        secondaryBridge = second;
        // No backend-visible Surface exists in this arm. The fixed private
        // AHardwareBuffer pool was allocated above and EmuFusion will prove
        // EGL import on the first READY generated image. There is therefore no
        // WSI drain probe, release worker, or backend physical-present queue.
        startupSurfaceProbeTarget = 0;
        startupSurfaceProbeStartNs = System.nanoTime();
        startupSurfaceProbeComplete = true;
        scheduleEndpointPreparation();
    }

    private void advanceStartupSurfaceDrainProbe() {
        requireOwner();
        if (startupSurfaceProbeComplete) return;
        long nowNs = System.nanoTime();
        long elapsedNs = nowNs - startupSurfaceProbeStartNs;
        if (!startupSurfaceProbeSlowLogged && elapsedNs >=
                STARTUP_SURFACE_DRAIN_SLOW_NS) {
            startupSurfaceProbeSlowLogged = true;
            // A newly attached Android Surface can remain non-composited while
            // the activity transitions between the title and game layers.
            // GPU completion of the first FIFO rotation is not physical image
            // recycling. Keep the transport unavailable and keep probing with
            // zero-wait calls; no endpoint, presentation, or proof is accepted
            // during this bounded grace period.
            Log.w(TAG, "RIFE startup Surface drain delayed" +
                    " submitted=" + startupSurfaceProbeSubmitted +
                    " completed=" + startupSurfaceProbeCompleted +
                    " acquireNotReady=" +
                            startupSurfaceProbeAcquireNotReady +
                    " elapsedNs=" + elapsedNs);
        }
        if (elapsedNs >=
                STARTUP_SURFACE_DRAIN_TIMEOUT_NS)
            throw new IllegalStateException(
                    "RIFE startup Surface did not recycle one swapchain image" +
                    " submitted=" + startupSurfaceProbeSubmitted +
                    " completed=" + startupSurfaceProbeCompleted +
                    " acquireNotReady=" +
                            startupSurfaceProbeAcquireNotReady);
        if (startupSurfaceProbePending) {
            int completion = bridge.pollPresentation();
            if (completion < 0)
                throw new IllegalStateException(
                        "RIFE startup Surface probe completion failed");
            if (completion == 0) return;
            startupSurfaceProbePending = false;
            ++startupSurfaceProbeCompleted;
            if (startupSurfaceProbeCompleted != startupSurfaceProbeSubmitted)
                throw new IllegalStateException(
                        "RIFE startup Surface probe accounting mismatch");
        }
        if (startupSurfaceProbeSubmitted < startupSurfaceProbeTarget) {
            int result = bridge.enqueuePresentationClear(0f, 0f, 0f, 1f);
            if (result < 0)
                throw new IllegalStateException(
                        "RIFE startup Surface probe submission failed");
            if (result == 0) {
                ++startupSurfaceProbeAcquireNotReady;
                return;
            }
            ++startupSurfaceProbeSubmitted;
            startupSurfaceProbePending = true;
            return;
        }
        if (startupSurfaceProbeCompleted != startupSurfaceProbeTarget)
            throw new IllegalStateException(
                    "RIFE startup Surface probe stopped before completion");
        startupSurfaceProbeComplete = true;
        Log.i(TAG, "RIFE startup Surface drain proven" +
                " submitted=" + startupSurfaceProbeSubmitted +
                " completed=" + startupSurfaceProbeCompleted +
                " requestedImages=" + requestedImageCount +
                " actualImages=" + swapchainImageCount +
                " surfaceMinImages=" + surfaceMinImageCount +
                " surfaceMaxImages=" + surfaceMaxImageCount +
                " acquireNotReady=" + startupSurfaceProbeAcquireNotReady +
                " elapsedNs=" +
                        Math.max(1L, System.nanoTime() -
                                startupSurfaceProbeStartNs) +
                " slow=" + (startupSurfaceProbeSlowLogged ? 1 : 0));
        scheduleEndpointPreparation();
    }

    /**
     * Pays the model's one-time Vulkan graph/allocator cost before the game can
     * submit a visible endpoint. The first live generated row must obey the
     * same deadline as every later row; hiding or forgiving a cold miss in the
     * timing evidence would still leave a user-visible hitch.
     */
    private void warmPresentationModelBeforeSurface(int width, int height) {
        final int rowStride;
        final int bytes;
        try {
            rowStride = Math.multiplyExact(width, 4);
            bytes = Math.multiplyExact(rowStride, height);
        } catch (ArithmeticException overflow) {
            throw new IllegalArgumentException(
                    "RIFE warm-up geometry overflows", overflow);
        }
        java.nio.ByteBuffer previous = java.nio.ByteBuffer.allocateDirect(bytes);
        java.nio.ByteBuffer current = java.nio.ByteBuffer.allocateDirect(bytes);
        java.nio.ByteBuffer output = java.nio.ByteBuffer.allocateDirect(bytes);
        NativeRifeBridge.Timing timing = bridge.interpolate(
                previous, current, width, height, rowStride, 0.5f, output);
        if (timing == null || timing.endToEndNs <= 0L ||
                timing.processV4CompositeNs <= 0L)
            throw new IllegalStateException(
                    "RIFE startup model warm-up produced no timing proof");
        Log.i(TAG, "RIFE presentation model warmed before input Surface" +
                " width=" + width +
                " height=" + height +
                " processNs=" + timing.processV4CompositeNs +
                " endToEndNs=" + timing.endToEndNs);
    }

    /** EGL producer target for exact classified endpoint images. */
    @Override public Surface endpointSurface() {
        requireOwner();
        requireOpen();
        return endpointSurface;
    }

    @Override public int endpointWidth() { return width; }

    @Override public int endpointHeight() { return height; }

    @Override public String backendLabel() { return "RIFE"; }

    /**
     * Exact N64 rate paths that have enough isolated Thor headroom to enter
     * moving-game qualification.  This is an admission whitelist, not a
     * certification claim: EmuFusion's unchanged timing/content/manual gates
     * still have to qualify each source/target pair independently.  In
     * The 60->120 entry authorizes only the separately bounded F-Zero X
     * qualification arm; it is not a certification claim. Its tighter
     * one-scan budget must still pass the unchanged physical gates below.
     */
    @Override public boolean supportsRatePath(int sourceFps, int outputFps) {
        return (sourceFps == 20 && outputFps == 40) ||
                (sourceFps == 30 && outputFps == 60) ||
                (sourceFps == 60 && outputFps == 120);
    }

    /** Native open self-tests exact endpoint passthrough independently of RIFE. */
    @Override public boolean supportsEndpointOnlyPresentation() { return true; }

    /** Direct Vulkan WSI owns physical timing; no SurfaceControl token applies. */
    @Override public boolean requiresCompositorFrameTimeline() {
        return false;
    }

    @Override public boolean usesAppOwnedPresentation() {
        return appOwnedPresentation;
    }

    @Override public int copyCompositorFrameTimelines(
            long[] vsyncIds, long[] expectedPresentationTimesNs,
            long[] deadlinesNs, long[] sourceMetadata) {
        requireOwner();
        requireOpen();
        // The preparation worker owns the native context mutex while creating
        // per-buffer Vulkan imports. Never turn a timeline snapshot into a
        // blocking call behind that work; the caller safely skips this output
        // opportunity and does not consume a presentation slot.
        if (preparationInFlight) return 0;
        return bridge.copySurfaceControlFrameTimelines(
                vsyncIds, expectedPresentationTimesNs,
                deadlinesNs, sourceMetadata);
    }

    @Override public void setGeneratedRatePathActive(boolean active) {
        requireOwner();
        requireOpen();
        if (active && !generatedRatePathActive) {
            // Direct presentation may recycle only a small subset of the
            // eight ImageReader carriers. Its cache-hit streak is not proof
            // that the three-endpoint generated pipeline can avoid a cold
            // import. Re-prove the full rotation inside priming.
            consecutiveCachedEndpointCount = 0;
            endpointImportCacheWarm = false;
        }
        generatedRatePathActive = active;
        if (!active) {
            discardPreparedPresentation();
        }
    }

    @Override public boolean canAcceptEndpoint() {
        requireOwner();
        requireOpen();
        // Software uploads and ImageReader notifications share this Handler.
        // A queued batch of uploads can run before the notification for the
        // preceding swap. Acquire available images before exporting another
        // endpoint, rather than depending solely on notification ordering.
        onImageAvailable(reader);
        requireOpen();
        return expected.size() + retained.size() < MAX_IMAGES;
    }

    /** Must be called immediately before rendering this exact endpoint Surface buffer. */
    @Override public void expectEndpoint(long sequence, long timestampNs) {
        requireOwner();
        requireOpen();
        if (sequence <= lastExpectedSequence || timestampNs <= lastExpectedTimestampNs)
            throw new IllegalArgumentException("RIFE endpoint identity is not monotonic");
        if (expected.size() + retained.size() >= MAX_IMAGES)
            throw new IllegalStateException("RIFE endpoint pool is full");
        expected.addLast(new ExpectedEndpoint(sequence, timestampNs));
        lastExpectedSequence = sequence;
        lastExpectedTimestampNs = timestampNs;
    }

    @Override public void cancelExpectedEndpoint(long sequence) {
        requireOwner();
        requireOpen();
        ExpectedEndpoint tail = expected.peekLast();
        if (tail == null || tail.sequence != sequence)
            throw new IllegalStateException(
                    "RIFE expected-endpoint cancellation is not the queue tail");
        expected.removeLast();
    }

    @Override public void onImageAvailable(ImageReader source) {
        requireOwner();
        if (closed) return;
        try {
            // acquireNextImage throws at maxImages, even when the queue is
            // empty. A full retained pool has no outstanding announced image:
            // admission bounds expected + retained to MAX_IMAGES. Stop before
            // the redundant ninth acquisition rather than treating it as a
            // transport failure. A later admitted image triggers a new callback.
            while (retained.size() < MAX_IMAGES) {
                Image image = pollAcquiredEndpoint(source);
                if (image == null) return;
                boolean retainedImage = false;
                try {
                    ExpectedEndpoint identity = expected.peekFirst();
                    long timestampNs = image.getTimestamp();
                    if (identity != null && timestampNs != identity.timestampNs) {
                        long skipped = 0L;
                        ExpectedEndpoint exact = null;
                        for (ExpectedEndpoint candidate : expected) {
                            if (candidate.timestampNs == timestampNs) {
                                exact = candidate;
                                break;
                            }
                            ++skipped;
                        }
                        if (exact != null && skipped > 0L) {
                            for (long index = 0L; index < skipped; ++index)
                                expected.removeFirst();
                            endpointDiscontinuities += skipped;
                            identity = expected.peekFirst();
                            Log.w(TAG, "RIFE endpoint carrier discontinuity" +
                                    " skipped=" + skipped +
                                    " resumedSequence=" + exact.sequence +
                                    " resumedTimestampNs=" + timestampNs +
                                    " expectedDepth=" + expected.size() +
                                    " retainedDepth=" + retained.size());
                        }
                    }
                    if (identity == null || timestampNs != identity.timestampNs)
                        throw new IllegalStateException(
                                "RIFE Image timestamp does not match announced endpoint" +
                                " sequence=" +
                                (identity == null ? 0L : identity.sequence) +
                                " expectedTimestampNs=" +
                                (identity == null ? 0L : identity.timestampNs) +
                                " actualTimestampNs=" + timestampNs +
                                " expectedDepth=" + expected.size() +
                                " retainedDepth=" + retained.size());
                    expected.removeFirst();
                    if (identity.discard) continue;
                    HardwareBuffer buffer = image.getHardwareBuffer();
                    try {
                        if (buffer == null || buffer.isClosed() ||
                                buffer.getWidth() != width ||
                                buffer.getHeight() != height ||
                                buffer.getLayers() != 1 ||
                                buffer.getFormat() != HardwareBuffer.RGBA_8888 ||
                                (buffer.getUsage() &
                                        HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE) == 0L)
                            throw new IllegalStateException(
                                    "RIFE endpoint HardwareBuffer is invalid");
                    } finally {
                        // Image.getHardwareBuffer() returns a distinct
                        // closeable Java handle. The retained Image owns the
                        // carrier lifetime; this temporary validation handle
                        // must be released before that Image is eventually
                        // closed. r93 leaked two wrappers per endpoint until a
                        // Cleaner burst landed on a visible render deadline.
                        if (buffer != null) buffer.close();
                    }
                    if (retained.put(identity.sequence,
                            new RetainedEndpoint(identity.sequence, timestampNs, image)) != null)
                        throw new IllegalStateException("duplicate RIFE endpoint sequence");
                    retainedImage = true;
                    scheduleEndpointPreparation();
                } finally {
                    if (!retainedImage) image.close();
                }
            }
        } catch (RuntimeException failure) {
            // Listener exceptions must not kill the renderer Handler. Record
            // the exact failure and make every subsequent owner call fail
            // closed at its normal session boundary.
            fatalFailure = failure;
        }
    }

    /** Owner-only poll; worker touches neither endpoint identities nor GL. */
    private Image pollAcquiredEndpoint(ImageReader source) {
        AcquiredEndpoint result = acquiredEndpoint.getAndSet(null);
        if (result != null) {
            acquisitionInFlight = false;
            if (result.failure != null) throw result.failure;
            return result.image;
        }
        if (!acquisitionInFlight && !expected.isEmpty() &&
                retained.size() < MAX_IMAGES) {
            acquisitionInFlight = true;
            try {
                acquisitionWorker.execute(() -> {
                    Image image = null;
                    RuntimeException failure = null;
                    android.os.Trace.beginSection("EmuFusion.acquireEndpointImage");
                    try {
                        image = source.acquireNextImage();
                    } catch (RuntimeException caught) {
                        failure = caught;
                    } finally {
                        android.os.Trace.endSection();
                    }
                    acquiredEndpoint.set(new AcquiredEndpoint(image, failure));
                    // If the looper is stopping, close() still owns this result
                    // through the atomic slot after joining the worker.
                    owner.post(() -> onImageAvailable(source));
                });
            } catch (RuntimeException rejected) {
                acquisitionInFlight = false;
                throw rejected;
            }
        }
        return null;
    }

    @Override public boolean hasAdjacentPair(long leftSequence, long rightSequence) {
        requireOwner();
        requireOpen();
        RetainedEndpoint left = retained.get(leftSequence);
        RetainedEndpoint right = retained.get(rightSequence);
        // App-owned presentation reads retained GL endpoints/cached outputs,
        // not the worker's native context. A successor inference must not
        // hide an already-imported pair and stall the visible timeline.
        return (appOwnedPresentation || !preparationInFlight) &&
                rightSequence == leftSequence + 1L &&
                left != null && right != null &&
                left.prepared && right.prepared && !left.preparing && !right.preparing;
    }

    @Override public long consumeEndpointDiscontinuities() {
        requireOwner();
        requireOpen();
        long result = endpointDiscontinuities;
        endpointDiscontinuities = 0L;
        return result;
    }

    @Override public long consumePresentationDiscontinuities() {
        requireOwner();
        requireOpen();
        long result = presentationDiscontinuities;
        presentationDiscontinuities = 0L;
        return result;
    }

    @Override public GenerationReadiness generationReadiness(
            long leftSequence, long rightSequence) {
        requireOwner();
        requireOpen();
        if (!hasAdjacentPair(leftSequence, rightSequence))
            return GenerationReadiness.PENDING;
        PreparedPresentation current = preparedPresentation;
        if (queuedPreparation != null && queuedPreparation.request.leftSequence() == leftSequence &&
                queuedPreparation.request.rightSequence() == rightSequence) {
            swapPreparations();
            current = preparedPresentation;
        }
        if (current != null &&
                current.request.leftSequence() == leftSequence &&
                current.request.rightSequence() == rightSequence) {
            // Private completion is zero-wait and must be observed while this
            // exact pair still owns the next fractional slot. r120 otherwise
            // left every completed image marked PENDING until the following
            // REAL requested N+1/N+2, then discarded N/N+1 as one pair stale.
            // Never poll a different pair here; identity remains immutable.
            pollPreparedPresentation();
        }
        GenerationReadiness result = pairReadiness.get(rightSequence);
        return result == null ? GenerationReadiness.PENDING : result;
    }

    @Override public boolean hasPreparedLookahead(long rightSequence) {
        requireOwner();
        requireOpen();
        if (!generatedRatePathActive || rightSequence <= 0L ||
                rightSequence == Long.MAX_VALUE) return false;
        RetainedEndpoint candidate = retained.get(rightSequence + 1L);
        return candidate != null && candidate.prepared && !candidate.preparing;
    }

    /** Releases only endpoint Images older than the active left endpoint. */
    @Override public void releaseBefore(long minimumSequence) {
        requireOwner();
        requireOpen();
        minimumRetainedOutputSequence = Math.max(minimumRetainedOutputSequence, minimumSequence);
        for (PreparedPresentation output : readyOutputs.values())
            if (output.request.leftSequence() < minimumRetainedOutputSequence)
                output.discardRequested = true;
        retireDiscardedCachedOutputs();
        java.util.Iterator<Map.Entry<Long, RetainedEndpoint>> iterator =
                retained.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<Long, RetainedEndpoint> entry = iterator.next();
            if (entry.getKey() >= minimumSequence) break;
            RetainedEndpoint endpoint = entry.getValue();
            if (nativeReferences(entry.getKey())) {
                endpoint.discardRequested = true;
            } else {
                endpoint.image.close();
                iterator.remove();
            }
        }
        java.util.Iterator<Map.Entry<Long, GenerationReadiness>> assessments =
                pairReadiness.entrySet().iterator();
        while (assessments.hasNext()) {
            long right = assessments.next().getKey();
            if (right < minimumSequence) assessments.remove();
        }
    }

    @Override public void resetEndpointTimeline() {
        requireOwner();
        requireOpen();
        discardPreparedPresentation();
        for (ExpectedEndpoint endpoint : expected) endpoint.discard = true;
        java.util.Iterator<Map.Entry<Long, RetainedEndpoint>> iterator =
                retained.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<Long, RetainedEndpoint> entry = iterator.next();
            RetainedEndpoint endpoint = entry.getValue();
            if (nativeReferences(entry.getKey())) {
                endpoint.discardRequested = true;
            } else {
                endpoint.image.close();
                iterator.remove();
            }
        }
        pairReadiness.clear();
        requestPresentationEpoch = 0L;
        ++timelineEpoch;
    }

    @Override public PreparationResult prepare(
            FrameGenerationPreparationRequest request) {
        requireOwner();
        requireOpen();
        validatePreparationIdentity(request);
        // Ready outputs are owner-owned and immutable. A different recording
        // job must not hide them or force a native pool poll merely to discover
        // that this exact midpoint is already cached. In particular, let the
        // look-ahead walk traverse cached pairs before reaching the busy job.
        if (generatedRatePathActive && request.isGenerated() &&
                hasReadyOutput(request))
            return PreparationResult.ALREADY_READY;
        // Import preparation owns the native context mutex. Do not poll its
        // output pools first: that would block the presentation owner behind
        // cold driver work before reaching the existing nonblocking gate.
        if (!generatedRatePathActive || !request.isGenerated() ||
                preparationInFlight)
            return PreparationResult.NOT_READY;
        if (appOwnedPresentation) {
            drainDeferredOutputReleases();
            bridge.pollBoundHardwareBufferRifeOutputs();
            secondaryBridge.pollBoundHardwareBufferRifeOutputs();
        }
        // Direct Vulkan scheduleNativeRelease() has already called
        // vkQueuePresentKHR on the held presentation queue and left it waiting
        // on the private release-gate semaphore.  Private RIFE runs on ncnn's
        // separate generic compute pool, so it is now safely behind the
        // visible request without waiting for that gate to open.  The old
        // Java deferral waited until the REAL was physically released; r121
        // then started inference only about one callback before its midpoint,
        // consumed the synthetic slot as NOT_READY, and discarded every
        // completed image one pair stale.  Preserve the ownership assertion:
        // never start direct private work unless a visible request is both
        // retained and prequeued under its immutable release window.
        if (!appOwnedPresentation && !surfaceControlPresentation &&
                (!nativePending || nativeInFlight == null ||
                        !nativeReleaseScheduled))
            throw new IllegalStateException(
                    "RIFE private preparation lacks a prequeued visible request");
        return startPreparation(request);
    }

    /** Starts private GPU work only after the preceding WSI call is queued. */
    private PreparationResult startPreparation(
            FrameGenerationPreparationRequest request) {
        if (hasReadyOutput(request)) return PreparationResult.ALREADY_READY;
        if (!retireStalePreparation(request))
            return PreparationResult.NOT_READY;
        if (preparedPresentation != null) {
            pollPreparedPresentation();
            if (hasReadyOutput(request)) return PreparationResult.ALREADY_READY;
            return preparedPresentation != null &&
                    preparedPresentation.ready ?
                    PreparationResult.ALREADY_READY :
                    PreparationResult.SUBMITTED;
        }

        // retireStalePreparation may just have moved the earlier pair into
        // queuedPreparation. Observe its zero-wait GPU completion and bind it
        // into the owner-owned cache BEFORE a future worker closes the native
        // access gate. Otherwise an already-finished due output can be hidden
        // behind an unrelated recording job until its visible slot is lost.
        // Pending work stays pending; never wait or discard it to make room.
        cacheQueuedOutputBeforePreparation();

        RetainedEndpoint left = retained.get(request.leftSequence());
        RetainedEndpoint right = retained.get(request.rightSequence());
        if (left == null || right == null || !left.prepared || !right.prepared)
            return PreparationResult.NOT_READY;
        if (left.timestampNs != request.leftTimestampNs() ||
                right.timestampNs != request.rightTimestampNs())
            throw new IllegalStateException(
                    "RIFE preparation/Image timestamp identity mismatch");
        GenerationReadiness pairState = generationReadiness(
                request.leftSequence(), request.rightSequence());
        // A private output is allowed to establish the assessment for its own
        // exact pair. The native completion returns scene-cut proof before the
        // image can become READY or acquire WSI. An already-UNSAFE pair remains
        // forbidden; PENDING merely means this is the first private assessment
        // of the one-slot look-ahead pair.
        if (pairState == GenerationReadiness.UNSAFE)
            return PreparationResult.NOT_READY;

        RetainedEndpoint lookahead = null;
        long lookaheadSequence = request.rightSequence() + 1L;
        if (lookaheadSequence > 0L &&
                !pairReadiness.containsKey(lookaheadSequence)) {
            RetainedEndpoint candidate = retained.get(lookaheadSequence);
            if (candidate != null && candidate.prepared && !candidate.preparing)
                lookahead = candidate;
        }
        long proofSequence = takeProofSequence();
        NativeRifeBridge jobBridge = availablePreparationBridge();
        if (jobBridge == null) return PreparationResult.NOT_READY;
        final RetainedEndpoint submittedLookahead = lookahead;
        final PreparedPresentation pending = new PreparedPresentation(
                jobBridge,
                request, proofSequence,
                lookahead == null ? 0L : lookahead.sequence,
                lookahead == null ? 0L : lookahead.timestampNs,
                timelineEpoch);
        final DisplaySubmissionFence displayDependency = appOwnedPresentation
                ? DisplaySubmissionFence.capture() : null;
        // Publish ownership before dispatch: reset/releaseBefore must retain
        // every Image while the worker obtains its native buffer/fence refs.
        preparedPresentation = pending;
        recordingPresentation = pending;
        preparationInFlight = true;
        FrameGenerationPreparationRequest preceding = lastStartedPreparationRequest;
        if (preceding != null && preceding.presentationEpoch() == request.presentationEpoch() &&
                preceding.leftSequence() > request.leftSequence()) {
            StringBuilder cached = new StringBuilder();
            for (PreparedPresentation output : readyOutputs.values()) {
                cached.append(output.request.leftSequence()).append(':')
                        .append(output.request.presentationTimestampNs()).append(':')
                        .append(output.discardRequested).append(',');
            }
            Log.w(TAG, "RIFE preparation order inversion" +
                    " epoch=" + request.presentationEpoch() +
                    " left=" + request.leftSequence() +
                    " leftNs=" + request.leftTimestampNs() +
                    " rightNs=" + request.rightTimestampNs() +
                    " targetNs=" + request.presentationTimestampNs() +
                    " precedingLeft=" + preceding.leftSequence() +
                    " precedingTargetNs=" + preceding.presentationTimestampNs() +
                    " queuedLeft=" + (queuedPreparation == null ? 0L :
                            queuedPreparation.request.leftSequence()) +
                    " minimumRetained=" + minimumRetainedOutputSequence +
                    " cached=" + cached);
        }
        lastStartedPreparationRequest = request;
        pending.dispatchedNs = System.nanoTime();
        try {
            preparationWorker.execute(() -> {
                pending.workerStartedNs = System.nanoTime();
                int result = -1;
                Throwable failure = null;
                android.os.Trace.beginSection("EmuFusion.submitRife:" + proofSequence);
                try {
                    if (displayDependency != null) displayDependency.awaitOnWorker();
                    pending.dependencyReadyNs = System.nanoTime();
                    result = jobBridge.prepareHardwareBufferRifeOutput(
                            left.image, right.image,
                            submittedLookahead == null ? null : submittedLookahead.image,
                            width, height, analysisWidth, analysisHeight,
                            request.presentationTimestampNs(), proofSequence);
                } catch (Throwable submissionFailure) {
                    failure = submissionFailure;
                } finally {
                    // This bounds native submission from above, not GPU completion.
                    pending.nativeReturnedNs = System.nanoTime();
                    android.os.Trace.endSection();
                }
                final int completedResult = result;
                final Throwable completedFailure = failure;
                owner.post(() -> finishOutputPreparation(
                        pending, completedResult, completedFailure));
            });
        } catch (RuntimeException rejected) {
            recordingPresentation = null;
            preparationInFlight = false;
            preparedPresentation = null;
            if (displayDependency != null) displayDependency.destroy();
            throw rejected;
        }
        if (lookahead != null && ++lookaheadProofSubmittedCount == 1L)
            Log.i(TAG, "RIFE private look-ahead proof pipeline started" +
                    " current=" + request.leftSequence() + "/" +
                            request.rightSequence() +
                    " lookahead=" + lookahead.sequence);
        return PreparationResult.SUBMITTED;
    }

    private void cacheQueuedOutputBeforePreparation() {
        if (!appOwnedPresentation || preparationInFlight ||
                preparedPresentation != null || queuedPreparation == null) return;
        swapPreparations();
        try {
            pollPreparedPresentation();
        } finally {
            // Restore slot orientation even when completion validation throws.
            // A cached/discarded queued output is now null; a pending one keeps
            // its original identity and reserves its native bridge as before.
            swapPreparations();
        }
    }

    private void finishOutputPreparation(PreparedPresentation pending,
            int result, Throwable failure) {
        requireOwner();
        recordingPresentation = null;
        preparationInFlight = false;
        if (closed) return; // close() drains native work after worker termination.
        if (preparedPresentation != pending && queuedPreparation != pending) {
            fatalFailure = new IllegalStateException("RIFE worker output ownership changed");
            return;
        }
        if (failure != null || (result != 0 && result != 1)) {
            fatalFailure = new IllegalStateException("RIFE private output submission failed", failure);
            return; // Retain images until native teardown proves reads drained.
        }
        if (result == 0) {
            if (preparedPresentation == pending) preparedPresentation = null;
            if (queuedPreparation == pending) queuedPreparation = null;
        } else if (pending.timelineEpoch != timelineEpoch || pending.discardRequested) {
            pending.discardRequested = true;
            retireDiscardedPreparations();
        }
        retireDiscardedEndpoints();
        try {
            if (result == 1 && pending.timelineEpoch == timelineEpoch &&
                    !pending.discardRequested && preparationCapacityListener != null) {
                if (completedPreparationGpuReady(pending))
                    preparationCapacityListener.run();
                else
                    schedulePreparationReadyCheck(pending, 64);
            }
        } catch (RuntimeException readinessFailure) {
            // This callback runs outside the render-loop exception boundary.
            // Preserve failure for requireOpen(), rather than killing the
            // owner Looper and losing orderly transport/resource retirement.
            fatalFailure = readinessFailure;
        }
    }

    private void schedulePreparationReadyCheck(PreparedPresentation pending, int remaining) {
        if (remaining <= 0 || closed || fatalFailure != null ||
                pending.discardRequested || pending.timelineEpoch != timelineEpoch ||
                preparationCapacityListener == null) return;
        if (!owner.postDelayed(() -> {
            if (closed || fatalFailure != null || pending.discardRequested ||
                    pending.timelineEpoch != timelineEpoch || preparationCapacityListener == null ||
                    (preparedPresentation != pending && queuedPreparation != pending &&
                            readyOutputs.get(pending.proofSequence) != pending)) return;
            try {
                // Ordinary display polling can cache this exact output before
                // the delayed check runs. Leaving a preparation slot is not
                // cancellation: that completed job still releases capacity.
                if ((pending.ready && readyOutputs.get(pending.proofSequence) == pending) ||
                        completedPreparationGpuReady(pending))
                    preparationCapacityListener.run();
                else
                    schedulePreparationReadyCheck(pending, remaining - 1);
            } catch (RuntimeException failure) {
                fatalFailure = failure;
            }
        }, 1L)) {
            fatalFailure = new IllegalStateException("RIFE owner rejected readiness check");
        }
    }

    private boolean completedPreparationGpuReady(PreparedPresentation pending) {
        // Recording completion is not GPU capacity. Poll without waiting and
        // preserve slot orientation even if validation throws. A not-yet-ready
        // job is revisited by bounded owner checks or ordinary display polling;
        // never refill merely because its CPU recorder became idle.
        if (preparedPresentation == pending) {
            pollPreparedPresentation();
        } else if (queuedPreparation == pending) {
            swapPreparations();
            try {
                pollPreparedPresentation();
            } finally {
                swapPreparations();
            }
        } else {
            return false;
        }
        return pending.ready && !pending.discardRequested;
    }

    @Override public PreparationReadiness preparationReadiness(
            FrameGenerationPreparationRequest request) {
        requireOwner();
        requireOpen();
        validatePreparationIdentity(request);
        if (hasReadyOutput(request)) return PreparationReadiness.READY;
        if (preparationInFlight) return PreparationReadiness.PENDING;
        if (queuedPreparation != null && queuedPreparation.request.matches(request)) swapPreparations();
        if (preparedPresentation == null) return PreparationReadiness.ABSENT;
        if (!preparedPresentation.request.matches(request))
            return PreparationReadiness.UNSAFE;
        pollPreparedPresentation();
        if (hasReadyOutput(request)) return PreparationReadiness.READY;
        if (preparedPresentation == null) return PreparationReadiness.ABSENT;
        return preparedPresentation.ready ?
                PreparationReadiness.READY : PreparationReadiness.PENDING;
    }

    @Override public boolean privateGenerationPipelineWarm() {
        requireOwner();
        requireOpen();
        // This flag is session-lifetime monotonic. A timeline reset discards
        // the pixels and identity of an obsolete warm-up result, but the
        // native graph/cache cost it proved paid cannot become cold again.
        return privateGenerationPipelineWarm && endpointImportCacheWarm;
    }

    @Override public int preparationLookaheadPairs() { return 4; }

    @Override public boolean visibleSubmissionReady() {
        requireOwner();
        requireOpen();
        return appOwnedPresentation ||
                (startupSurfaceProbeComplete &&
                        !nativePending && !preparationInFlight);
    }

    private void validatePreparationIdentity(
            FrameGenerationPreparationRequest request) {
        if (request == null || !request.hasAdjacentPair() ||
                request.outputWidth() != width ||
                request.outputHeight() != height ||
                request.outputFormat() !=
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM)
            throw new IllegalArgumentException(
                    "RIFE private preparation contract is invalid");
        if (requestSessionEpoch == 0L)
            requestSessionEpoch = request.sessionEpoch();
        if (request.sessionEpoch() != requestSessionEpoch)
            throw new IllegalStateException(
                    "RIFE preparation session identity changed in place");
        if (requestPresentationEpoch == 0L)
            requestPresentationEpoch = request.presentationEpoch();
        if (request.presentationEpoch() != requestPresentationEpoch)
            throw new IllegalStateException(
                    "RIFE preparation epoch changed without a timeline reset");
    }

    /** Returns false only while an obsolete private GPU submission retires. */
    private boolean retireStalePreparation(
            FrameGenerationPreparationRequest requested) {
        if (appOwnedPresentation) {
            retireDiscardedPreparations();
            if (queuedPreparation != null && queuedPreparation.request.matches(requested)) swapPreparations();
            if (preparedPresentation == null || preparedPresentation.request.matches(requested)) return true;
            if (queuedPreparation != null) return false;
            swapPreparations();
            return true;
        }
        PreparedPresentation current = preparedPresentation;
        if (current == null || current.request.matches(requested)) return true;
        Log.w(TAG, "RIFE stale private output discarded" +
                " preparedEpoch=" + current.request.presentationEpoch() +
                " requestedEpoch=" + requested.presentationEpoch() +
                " preparedPair=" + current.request.leftSequence() + "/" +
                        current.request.rightSequence() +
                " requestedPair=" + requested.leftSequence() + "/" +
                        requested.rightSequence() +
                " preparedLeftNs=" + current.request.leftTimestampNs() +
                " requestedLeftNs=" + requested.leftTimestampNs() +
                " preparedRightNs=" + current.request.rightTimestampNs() +
                " requestedRightNs=" + requested.rightTimestampNs() +
                " preparedTargetNs=" +
                        current.request.presentationTimestampNs() +
                " requestedTargetNs=" + requested.presentationTimestampNs() +
                " preparedPhaseBits=" + Long.toUnsignedString(
                        Double.doubleToRawLongBits(current.request.phase())) +
                " requestedPhaseBits=" + Long.toUnsignedString(
                        Double.doubleToRawLongBits(requested.phase())));
        current.discardRequested = true;
        if (!current.jobBridge.discardPreparedHardwareBufferRifeOutput(
                current.proofSequence)) return false;
        preparedPresentation = null;
        retireDiscardedEndpoints();
        return true;
    }

    /** Retire obsolete jobs without invalidating unrelated ready/future pixels. */
    private void retireDiscardedPreparations() {
        if (preparationInFlight) return;
        if (preparedPresentation != null && preparedPresentation.discardRequested)
            discardCurrentPreparation();
        swapPreparations();
        if (preparedPresentation != null && preparedPresentation.discardRequested)
            discardCurrentPreparation();
        swapPreparations();
    }

    private void discardPreparedPresentation() {
        discardCachedOutputs();
        discardCurrentPreparation();
        swapPreparations();
        discardCurrentPreparation();
        swapPreparations();
    }

    private void swapPreparations() {
        PreparedPresentation old = preparedPresentation;
        preparedPresentation = queuedPreparation;
        queuedPreparation = old;
    }

    private NativeRifeBridge availablePreparationBridge() {
        int primaryHeld = 0, secondaryHeld = 0;
        for (NativeRifeBridge owner : boundOutputBridges.values()) {
            if (owner == bridge) primaryHeld++;
            else if (owner == secondaryBridge) secondaryHeld++;
            else throw new IllegalStateException("RIFE output has an unknown owner");
        }
        boolean primaryBusy = queuedPreparation != null && queuedPreparation.jobBridge == bridge;
        boolean secondaryBusy = queuedPreparation != null && queuedPreparation.jobBridge == secondaryBridge;
        int slot = choosePreparationSlot(primaryHeld, secondaryHeld, primaryBusy, secondaryBusy);
        return slot == 0 ? bridge : slot == 1 ? secondaryBridge : null;
    }

    private static int choosePreparationSlot(int primaryHeld, int secondaryHeld,
            boolean primaryBusy, boolean secondaryBusy) {
        if (!primaryBusy && primaryHeld < 3 && (secondaryBusy || primaryHeld <= secondaryHeld)) return 0;
        if (!secondaryBusy && secondaryHeld < 3) return 1;
        if (!primaryBusy && primaryHeld < 3) return 0;
        return -1;
    }

    private void discardCurrentPreparation() {
        PreparedPresentation current = preparedPresentation;
        if (current == null) return;
        current.discardRequested = true;
        if (preparationInFlight) return;
        if (current.jobBridge.discardPreparedHardwareBufferRifeOutput(
                current.proofSequence)) {
            preparedPresentation = null;
            retireDiscardedEndpoints();
        }
    }

    private boolean outputAccessBlocked(PreparedPresentation current) {
        return preparationInFlight &&
                (!appOwnedPresentation || current == recordingPresentation);
    }

    private void pollPreparedPresentation() {
        PreparedPresentation current = preparedPresentation;
        if (current == null || outputAccessBlocked(current)) return;
        if (current.discardRequested) {
            retireDiscardedPreparations();
            return;
        }
        if (current.ready) { cacheReadyOutput(current); return; }
        NativeRifeBridge.PreparedOutput output =
                current.jobBridge.pollPreparedHardwareBufferRifeOutput(
                        current.proofSequence);
        if (output == null) return;
        NativeRifeBridge.ContentProof proof = output.contentProof;
        if (proof.sequence != current.proofSequence ||
                current.timelineEpoch != timelineEpoch)
            throw new IllegalStateException(
                    "RIFE private output completion identity changed");
        privateGenerationPipelineWarm = true;
        recordPairAssessment(current.request.leftSequence(),
                current.request.rightSequence(), proof.sceneCutRisk);
        boolean expectedLookahead = current.lookaheadSequence > 0L;
        if (proof.lookaheadAvailable != expectedLookahead)
            throw new IllegalStateException(
                    "RIFE private look-ahead availability mismatch");
        if (expectedLookahead) {
            RetainedEndpoint lookahead = retained.get(current.lookaheadSequence);
            if (lookahead == null ||
                    lookahead.timestampNs != current.lookaheadTimestampNs ||
                    current.lookaheadSequence !=
                            current.request.rightSequence() + 1L)
                throw new IllegalStateException(
                        "RIFE private look-ahead identity mismatch");
            recordPairAssessment(current.request.rightSequence(),
                    current.lookaheadSequence,
                    proof.lookaheadSceneCutRisk);
            if (++lookaheadProofCompletedCount == 1L)
                Log.i(TAG, "RIFE private look-ahead proof completed" +
                        " left=" + current.request.rightSequence() +
                        " right=" + current.lookaheadSequence);
        }
        if (proof.sceneCutRisk) {
            // A look-ahead private submission may be the first classifier for
            // this exact pair. Its pixels have never acquired WSI and are not
            // visible, so a scene cut is an ordinary UNSAFE result: discard
            // the private image and let exact endpoints continue directly.
            // A contradictory assessment of an already-known immutable pair
            // still throws above in recordPairAssessment().
            current.discardRequested = true;
            // Scene-cut proof applies to this pair only. A future cut must
            // not erase earlier ready midpoints or unrelated queued work.
            discardCurrentPreparation();
            return;
        }
        current.gpuWorkNs = output.gpuWorkNs;
        current.contentProof = externalProof(proof);
        current.ready = true;
        if (samplePreparationReady(current.proofSequence)) {
            long observedNs = System.nanoTime();
            // First owner observation after the native fence signaled, not an
            // exact GPU completion timestamp. Keep distinct from pending-job
            // diagnostics so their parser cannot count a ready row as a wait.
            Log.i(TAG, "RIFE preparation ready" +
                    " epoch=" + current.request.presentationEpoch() +
                    " left=" + current.request.leftSequence() +
                    " right=" + current.request.rightSequence() +
                    " readyCache=" + readyOutputs.size() +
                    " minimumRetained=" + minimumRetainedOutputSequence +
                    " gpuWorkNs=" + current.gpuWorkNs +
                    " readinessTiming=" + current.timingDiagnostic(observedNs, 0L));
        }
        cacheReadyOutput(current);
    }

    private static boolean samplePreparationReady(long proofSequence) {
        return proofSequence > 0L &&
                (proofSequence <= 16L || proofSequence % 64L == 0L);
    }

    private boolean hasReadyOutput(FrameGenerationPreparationRequest request) {
        if (cachedOutputDiscardPending) return false;
        for (PreparedPresentation output : readyOutputs.values())
            if (!output.discardRequested && output.request.matches(request)) return true;
        return false;
    }

    private void cacheReadyOutput(PreparedPresentation current) {
        if (current.request.leftSequence() < minimumRetainedOutputSequence) {
            // The source pair may advance while asynchronous recording runs.
            // Do not occupy a retained texture slot with an already-old result.
            current.discardRequested = true;
            discardCurrentPreparation();
            return;
        }
        if (!appOwnedPresentation || boundOutputBridges.size() >= 6) return;
        int[] texture = new int[1];
        android.opengl.GLES20.glGenTextures(1, texture, 0);
        if (texture[0] <= 0) throw new IllegalStateException("RIFE ready texture allocation failed");
        boolean bound = false;
        try {
            bound = current.jobBridge.bindPreparedHardwareBufferRifeOutput(current.proofSequence, texture[0]);
            if (!bound) return;
            readyOutputs.put(current.proofSequence, current);
            boundTextureIds.put(current.proofSequence, texture[0]);
            boundOutputBridges.put(current.proofSequence, current.jobBridge);
            ownedOutputTextures.add(current.proofSequence);
            preparedPresentation = null;
        } finally {
            if (!bound) android.opengl.GLES20.glDeleteTextures(1, texture, 0);
        }
    }

    private void deleteOwnedTexture(long proof) {
        Integer texture = boundTextureIds.get(proof);
        if (ownedOutputTextures.remove(proof) && texture != null)
            android.opengl.GLES20.glDeleteTextures(1, new int[]{texture}, 0);
    }

    private void discardCachedOutputs() {
        for (PreparedPresentation output : readyOutputs.values()) output.discardRequested = true;
        cachedOutputDiscardPending = true;
        retireDiscardedCachedOutputs();
    }

    private void retireDiscardedCachedOutputs() {
        if (preparationInFlight) return;
        java.util.Iterator<PreparedPresentation> entries = readyOutputs.values().iterator();
        while (entries.hasNext()) {
            PreparedPresentation output = entries.next();
            if (!output.discardRequested) continue;
            output.jobBridge.releaseBoundHardwareBufferRifeOutput(output.proofSequence, false);
            deleteOwnedTexture(output.proofSequence);
            boundTextureIds.remove(output.proofSequence);
            boundOutputBridges.remove(output.proofSequence);
            entries.remove();
        }
        cachedOutputDiscardPending = false;
    }

    private AppOwnedOutput takeReadyOutput(FrameGenerationPresentationRequest request) {
        if (cachedOutputDiscardPending) return null;
        java.util.Iterator<PreparedPresentation> entries = readyOutputs.values().iterator();
        while (entries.hasNext()) {
            PreparedPresentation current = entries.next();
            if (current.discardRequested || !current.request.matches(request)) continue;
            AppOwnedOutput output = new AppOwnedOutput(request, current.proofSequence,
                    current.gpuWorkNs, current.contentProof, boundTextureIds.get(current.proofSequence));
            boundAppOwnedOutputs.put(current.proofSequence, output);
            entries.remove();
            return output;
        }
        return null;
    }

    private static ExternalGeneratedContentProof externalProof(
            NativeRifeBridge.ContentProof proof) {
        return new ExternalGeneratedContentProof(
                proof.leftChecksum, proof.rightChecksum,
                proof.outputChecksum, proof.endpointMadPpm,
                proof.outputLeftMadPpm, proof.outputRightMadPpm,
                proof.endpointHistogramDistancePpm,
                proof.outputMin, proof.outputMax,
                proof.sceneCutRisk, proof.analysisWallNs,
                proof.width, proof.height, proof.sampleCount,
                proof.sequence, proof.byteCount);
    }

    private final long[] bindMissCounts = new long[6];

    private AppOwnedOutput missingAppOwnedOutput(int reason,
            FrameGenerationPresentationRequest request) {
        long count = ++bindMissCounts[reason];
        // Log only powers of two per cause: bounded evidence, no per-frame spam.
        if ((count & (count - 1L)) == 0L) {
            Log.i(TAG, "RIFE output unavailable reason=" + reason +
                    " count=" + count + " left=" + request.leftSequence() +
                    " right=" + request.rightSequence() +
                    " targetNs=" + request.presentationTimestampNs() +
                    " workerBusy=" + preparationInFlight +
                    " nativeAccess=" + (preparedPresentation == null ? "no-job" :
                            preparedPresentation.jobBridge.outputAccessDiagnostic(
                                    preparedPresentation.proofSequence)) +
                    " jobTiming=" + (preparedPresentation == null ? "no-job" :
                            preparedPresentation.timingDiagnostic(System.nanoTime(),
                                    request.hardCompletionDeadlineNs())) +
                    " readyCache=" + readyOutputs.size() +
                    " bound=" + boundAppOwnedOutputs.size() +
                    " cacheDiscardPending=" + cachedOutputDiscardPending +
                    " preparedLeft=" + (preparedPresentation == null ? 0L :
                            preparedPresentation.request.leftSequence()) +
                    " preparedTargetNs=" + (preparedPresentation == null ? 0L :
                            preparedPresentation.request.presentationTimestampNs()) +
                    " queuedLeft=" + (queuedPreparation == null ? 0L :
                            queuedPreparation.request.leftSequence()));
        }
        return null;
    }

    @Override public AppOwnedOutput bindAppOwnedOutput(
            FrameGenerationPresentationRequest request, int textureId) {
        requireOwner();
        requireOpen();
        if (!appOwnedPresentation || request == null ||
                !request.isGenerated() || textureId <= 0)
            throw new IllegalArgumentException(
                    "RIFE app-owned output request is invalid");
        if (boundAppOwnedOutputs.size() >= 6) return missingAppOwnedOutput(0, request);
        AppOwnedOutput cached = takeReadyOutput(request);
        if (cached != null) return cached;
        if (boundTextureIds.containsValue(textureId))
            throw new IllegalStateException("RIFE output texture is still retained");
        if (queuedPreparation != null && queuedPreparation.request.matches(request)) swapPreparations();
        PreparedPresentation current = preparedPresentation;
        if (current == null) return missingAppOwnedOutput(2, request);
        // Older outputs can use native try-lock polling/binding. Never consume
        // the recording job before its completion callback validates ownership.
        if (outputAccessBlocked(current)) return missingAppOwnedOutput(1, request);
        if (!current.request.matches(request)) return missingAppOwnedOutput(3, request);
        pollPreparedPresentation();
        cached = takeReadyOutput(request);
        if (cached != null) return cached;
        current = preparedPresentation;
        if (current == null || !current.ready || current.gpuWorkNs <= 0L ||
                current.contentProof == null) return missingAppOwnedOutput(4, request);
        if (boundAppOwnedOutputs.containsKey(current.proofSequence))
            throw new IllegalStateException("RIFE bound output proof identity repeated");
        if (!current.jobBridge.bindPreparedHardwareBufferRifeOutput(
                    current.proofSequence, textureId)) return missingAppOwnedOutput(5, request);
        AppOwnedOutput output = new AppOwnedOutput(
                request, current.proofSequence,
                current.gpuWorkNs, current.contentProof, textureId);
        boundAppOwnedOutputs.put(current.proofSequence, output);
        boundTextureIds.put(current.proofSequence, textureId);
        boundOutputBridges.put(current.proofSequence, current.jobBridge);
        preparedPresentation = null;
        return output;
    }

    @Override public void releaseAppOwnedOutput(
            AppOwnedOutput output, boolean swapSucceeded) {
        requireOwner();
        requireOpen();
        if (!appOwnedPresentation || output == null ||
                boundAppOwnedOutputs.get(output.proofSequence) != output)
            throw new IllegalStateException(
                    "RIFE app-owned output release identity changed");
        if (deferredOutputReleases.containsKey(output.proofSequence))
            throw new IllegalStateException("RIFE output release repeated");
        if (preparationInFlight) {
            // Keep texture and native slot retained. The next owner-side poll
            // inserts an EGL fence after all prior draw commands; a later
            // fence is conservative, whereas worker-side GL is invalid.
            deferredOutputReleases.put(output.proofSequence, swapSucceeded);
            return;
        }
        releaseAppOwnedOutputNow(output, swapSucceeded);
        scheduleEndpointPreparation();
    }

    private void releaseAppOwnedOutputNow(AppOwnedOutput output, boolean swapSucceeded) {
        NativeRifeBridge outputBridge = boundOutputBridges.get(output.proofSequence);
        outputBridge.releaseBoundHardwareBufferRifeOutput(
                output.proofSequence, swapSucceeded);
        boundAppOwnedOutputs.remove(output.proofSequence);
        deleteOwnedTexture(output.proofSequence);
        boundTextureIds.remove(output.proofSequence);
        boundOutputBridges.remove(output.proofSequence);
        outputBridge.pollBoundHardwareBufferRifeOutputs();
        retireDiscardedEndpoints();
    }

    private void drainDeferredOutputReleases() {
        requireOwner();
        if (preparationInFlight) return;
        java.util.Iterator<Map.Entry<Long, Boolean>> releases =
                deferredOutputReleases.entrySet().iterator();
        while (releases.hasNext()) {
            Map.Entry<Long, Boolean> release = releases.next();
            AppOwnedOutput output = boundAppOwnedOutputs.get(release.getKey());
            if (output == null)
                throw new IllegalStateException("RIFE deferred release lost output");
            releaseAppOwnedOutputNow(output, release.getValue());
            releases.remove();
        }
        retireDiscardedCachedOutputs();
        retireDiscardedEndpoints();
    }

    private long takeProofSequence() {
        if (nextProofSequence <= 0L || nextProofSequence == Long.MAX_VALUE)
            throw new IllegalStateException("RIFE proof sequence exhausted");
        return nextProofSequence++;
    }

    /** One zero-wait submission; NOT_READY is an underrun, never a retry burst. */
    @Override public EnqueueResult enqueue(FrameGenerationPresentationRequest request) {
        requireOwner();
        requireOpen();
        if (appOwnedPresentation)
            throw new UnsupportedOperationException(
                    "app-owned RIFE output cannot submit a visible backend presentation");
        if (request == null || !request.hasAdjacentPair())
            throw new IllegalArgumentException("RIFE presentation requires an adjacent pair");
        if (request.outputWidth() != width || request.outputHeight() != height ||
                request.outputFormat() !=
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM)
            throw new IllegalArgumentException(
                    "RIFE presentation output contract does not match its endpoint pool");
        if (surfaceControlPresentation != request.hasCompositorFrameTimeline())
            throw new IllegalArgumentException(
                    "RIFE presentation timing contract does not match its output path");
        if (requestSessionEpoch == 0L) requestSessionEpoch = request.sessionEpoch();
        if (request.sessionEpoch() != requestSessionEpoch)
            throw new IllegalStateException("RIFE session identity changed in place");
        if (requestPresentationEpoch == 0L)
            requestPresentationEpoch = request.presentationEpoch();
        if (request.presentationEpoch() != requestPresentationEpoch)
            throw new IllegalStateException(
                    "RIFE presentation epoch changed without a timeline reset");
        long enqueueNowNs = System.nanoTime();
        long compositorReserveNs = request.hardCompletionDeadlineNs() -
                enqueueNowNs;
        if (compositorReserveNs <
                PhysicalPresentationDeadline.
                        THOR_COMPOSITOR_SUBMISSION_RESERVE_NS) {
            Log.w(TAG, "RIFE enqueue not ready" +
                    " reason=compositor-reserve" +
                    " nowNs=" + enqueueNowNs +
                    " hardDeadlineNs=" + request.hardCompletionDeadlineNs() +
                    " reserveNs=" + compositorReserveNs);
            return EnqueueResult.NOT_READY;
        }
        // The release worker can cross its gate between the callback's first
        // poll and this later enqueue. Re-poll once without waiting so an
        // already-released row does not look busy for an entire panel scan.
        if (nativePending && nativeReleaseScheduled && pollNativeRelease())
            pollNativePresentationCompletion();
        if (nativePending || preparationInFlight) {
            // The selected midpoint is intentionally planned several callbacks
            // ahead. Physical r142 proved that its preceding REAL can still be
            // exactly one millisecond before the immutable native release gate
            // here even though this midpoint retains about thirty milliseconds
            // of deadline reserve. This is not an underrun. Let the controller
            // reconsider the same future target on the next panel callback;
            // once the gate opens, normal zero-wait poll() retires the REAL.
            // REAL and generated rows share the same single native WSI slot.
            // Physical r193/r196 proved that the first 30->60 rows can reach
            // this point just before the prior release gate, or just after
            // that gate while native completion is still becoming visible.
            // Preserve the exact future target in either case. The controller
            // retries it on the next callback without consuming a divisor
            // slot; once its immutable reserve is too small, normal NOT_READY
            // remains fail closed.
            long priorOperationReadyNs = nativeReleaseScheduled ?
                    Math.max(enqueueNowNs, nativeReleaseNotBeforeNs) :
                    enqueueNowNs;
            if (nativePending && !preparationInFlight &&
                    request.hardCompletionDeadlineNs() -
                            priorOperationReadyNs >=
                            PhysicalPresentationDeadline.
                                    THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS) {
                Log.i(TAG, "RIFE enqueue deferred" +
                        " reason=prior-release-not-before" +
                        " nowNs=" + enqueueNowNs +
                        " releaseNotBeforeNs=" + nativeReleaseNotBeforeNs +
                        " priorCutoffNs=" + nativeReleaseDeadlineNs +
                        " requestedHardDeadlineNs=" +
                                request.hardCompletionDeadlineNs());
                return EnqueueResult.DEFERRED;
            }
            Log.w(TAG, "RIFE enqueue not ready" +
                    " reason=transport-busy" +
                    " nativePending=" + (nativePending ? 1 : 0) +
                    " preparationInFlight=" +
                            (preparationInFlight ? 1 : 0));
            return EnqueueResult.NOT_READY;
        }
        if (submitted.size() >= MAX_PENDING_PRESENTATIONS)
            throw new IllegalStateException(
                    "RIFE physical presentation timing queue did not drain");
        if (!surfaceControlPresentation && wsiAcquireStarvationActive &&
                enqueueNowNs < nextWsiAcquireProbeNs) {
            Log.w(TAG, "RIFE enqueue not ready" +
                    " reason=swapchain-recovery-cooldown" +
                    " nowNs=" + enqueueNowNs +
                    " nextProbeNs=" + nextWsiAcquireProbeNs +
                    " attempts=" + consecutiveWsiAcquireNotReady);
            return EnqueueResult.NOT_READY;
        }
        RetainedEndpoint left = retained.get(request.leftSequence());
        RetainedEndpoint right = retained.get(request.rightSequence());
        if (left == null || right == null) {
            Log.w(TAG, "RIFE enqueue not ready" +
                    " reason=retained-pair-missing" +
                    " left=" + request.leftSequence() +
                    " right=" + request.rightSequence() +
                    " leftPresent=" + (left != null ? 1 : 0) +
                    " rightPresent=" + (right != null ? 1 : 0));
            return EnqueueResult.NOT_READY;
        }
        if (left.timestampNs != request.leftTimestampNs() ||
                right.timestampNs != request.rightTimestampNs())
            throw new IllegalStateException("RIFE request/Image timestamp identity mismatch");
        if (request.isGenerated() && generationReadiness(
                request.leftSequence(), request.rightSequence()) !=
                GenerationReadiness.READY)
            throw new IllegalStateException(
                    "RIFE generated request lacks a completed safe-pair assessment");
        RetainedEndpoint lookahead = null;
        long lookaheadSequence = 0L;
        long lookaheadTimestampNs = 0L;
        long proofSequence;
        PreparedPresentation consumedPreparation = null;
        if (request.isGenerated()) {
            FrameGenerationPreparationRequest preparationIdentity =
                    FrameGenerationPreparationRequest.from(request);
            if (!retireStalePreparation(preparationIdentity))
                return EnqueueResult.NOT_READY;
            pollPreparedPresentation();
            consumedPreparation = preparedPresentation;
            if (consumedPreparation != null &&
                    consumedPreparation.request.matches(request) &&
                    !consumedPreparation.ready &&
                    request.hardCompletionDeadlineNs() - System.nanoTime() >=
                            PhysicalPresentationDeadline.
                                    THOR_DIRECT_OUTPUT_SUBMISSION_LEAD_NS) {
                Log.i(TAG, "RIFE enqueue deferred" +
                        " reason=private-output-pending" +
                        " left=" + request.leftSequence() +
                        " right=" + request.rightSequence() +
                        " targetNs=" + request.presentationTimestampNs());
                return EnqueueResult.DEFERRED;
            }
            if (consumedPreparation == null ||
                    !consumedPreparation.request.matches(request) ||
                    !consumedPreparation.ready) {
                Log.w(TAG, "RIFE enqueue not ready" +
                        " reason=private-output" +
                        " left=" + request.leftSequence() +
                        " right=" + request.rightSequence() +
                        " targetNs=" + request.presentationTimestampNs());
                return EnqueueResult.NOT_READY;
            }
            proofSequence = consumedPreparation.proofSequence;
            lookaheadSequence = consumedPreparation.lookaheadSequence;
            lookaheadTimestampNs = consumedPreparation.lookaheadTimestampNs;
        } else {
            lookaheadSequence = request.rightSequence() + 1L;
            // Endpoint-only rows remain a cheap cached-import passthrough. If
            // a prepared third endpoint exists, its classifier is pipelined
            // without invoking RIFE and without cold-importing on this slot.
            if (generatedRatePathActive &&
                    !pairReadiness.containsKey(lookaheadSequence)) {
                RetainedEndpoint candidate = retained.get(lookaheadSequence);
                if (candidate != null && candidate.prepared && !candidate.preparing)
                    lookahead = candidate;
            }
            if (lookahead != null) {
                lookaheadTimestampNs = lookahead.timestampNs;
                if (++lookaheadProofSubmittedCount == 1L)
                    Log.i(TAG, "RIFE prepared look-ahead proof pipeline started" +
                            " current=" + request.leftSequence() + "/" +
                                    request.rightSequence() +
                            " lookahead=" + lookahead.sequence);
            } else {
                lookaheadSequence = 0L;
            }
            proofSequence = takeProofSequence();
        }
        long presentId = nextPresentId;
        long enqueueStartNs = System.nanoTime();
        // VK_GOOGLE_display_timing and SurfaceControl both define the native
        // timestamp as an earliest/at-or-after request, not as a reservation
        // of an exact scan.  Preserve the shared two-time contract: request
        // the proven Thor driver lead here, but keep the later exact content
        // scan in the immutable request for interpolation and physical
        // acceptance.  r114 passed the exact scan boundary to Vulkan and
        // reproduced one-scan-late results despite 13-29 ms of queue lead.
        long nativeDesiredPresentTimeNs =
                request.driverDesiredPresentTimeNs();
        long nativeFrameTimelineVsyncId = surfaceControlPresentation ?
                request.compositorFrameTimelineVsyncId() : 0L;
        long nativeFrameTimelineExpectedNs = surfaceControlPresentation ?
                request.compositorTokenExpectedPresentationTimeNs() : 0L;
        long nativeFrameTimelineDeadlineNs = surfaceControlPresentation ?
                request.compositorFrameTimelineDeadlineNs() : 0L;
        int result = request.isGenerated() ?
                bridge.enqueuePreparedHardwareBufferRifePresentation(
                        proofSequence,
                        nativeDesiredPresentTimeNs,
                        nativeFrameTimelineVsyncId,
                        nativeFrameTimelineExpectedNs,
                        nativeFrameTimelineDeadlineNs) :
                bridge.enqueueHardwareBufferRifePresentation(
                        left.image, right.image,
                        lookahead == null ? null : lookahead.image,
                        width, height,
                        request.presentationTimestampNs(),
                        nativeDesiredPresentTimeNs, proofSequence,
                        nativeFrameTimelineVsyncId,
                        nativeFrameTimelineExpectedNs,
                        nativeFrameTimelineDeadlineNs);
        long enqueueWallNs = System.nanoTime() - enqueueStartNs;
        if (result == 0) {
            // Native result zero is a bounded transport-capacity miss: the
            // SurfaceControl path has no released output AHardwareBuffer, or
            // the retained legacy WSI instrument has no acquired image.
            // Neither condition authorizes a retry burst.
            if (!surfaceControlPresentation)
                recordWsiAcquireNotReady();
            Log.w(TAG, "RIFE enqueue not ready" +
                    " reason=" + (surfaceControlPresentation ?
                            "surface-control-output" : "swapchain-acquire") +
                    " left=" + request.leftSequence() +
                    " right=" + request.rightSequence() +
                            " generated=" + (request.isGenerated() ? 1 : 0) +
                            " desiredNs=" +
                            request.driverDesiredPresentTimeNs());
            return EnqueueResult.NOT_READY;
        }
        resetWsiAcquireStarvation();
        boolean physicalPresentationSkipped = result == 2;
        if ((result != 1 && !physicalPresentationSkipped) || enqueueWallNs <= 0L)
            throw new IllegalStateException("RIFE native presentation submission failed");
        if (!physicalPresentationSkipped && !scheduleNativeRelease(request))
            physicalPresentationSkipped = true;
        SubmittedPresentation pending =
                new SubmittedPresentation(physicalPresentationSkipped ? 0L :
                                nextPresentId++, proofSequence,
                        request, enqueueWallNs,
                        lookaheadSequence, lookaheadTimestampNs,
                        nativeDesiredPresentTimeNs, timelineEpoch);
        if (!physicalPresentationSkipped) submitted.addLast(pending);
        nativeInFlight = pending;
        nativePending = true;
        if (consumedPreparation != null)
            preparedPresentation = null;
        if (physicalPresentationSkipped) {
            Log.w(TAG, "RIFE enqueue not ready" +
                    " reason=" + (surfaceControlPresentation ?
                            "compositor-reserve-post-work" :
                            "release-window-expired-post-work") +
                    " left=" + request.leftSequence() +
                    " right=" + request.rightSequence() +
                    " generated=" + (request.isGenerated() ? 1 : 0) +
                    " desiredNs=" + request.driverDesiredPresentTimeNs() +
                    " timelineDeadlineNs=" +
                            request.compositorFrameTimelineDeadlineNs() +
                    " enqueueWallNs=" + enqueueWallNs);
            return EnqueueResult.NOT_READY;
        }
        return EnqueueResult.SUBMITTED;
    }

    /**
     * Converts persistent WSI backpressure into one explicit presentation
     * discontinuity, never a fabricated frame or a dead renderer session.
     *
     * <p>A healthy FIFO swapchain may transiently return NOT_READY. Once every
     * image has remained unavailable for four refresh periods and at least
     * eight independently paced attempts, the current generated proof epoch
     * is no longer trustworthy. EmuFusion consumes the discontinuity on its
     * next callback, permanently quarantines generation for this session, and
     * re-primes exact Direct endpoints. Probes are then paced no faster than
     * four refresh periods until WSI recovers; there is no retry burst and no
     * missed slot is counted as presented.</p>
     */
    private void recordWsiAcquireNotReady() {
        long nowNs = System.nanoTime();
        if (consecutiveWsiAcquireNotReady == 0)
            wsiAcquireStarvationStartNs = nowNs;
        ++consecutiveWsiAcquireNotReady;
        long fourRefreshNs = refreshDurationNs > Long.MAX_VALUE / 4L ?
                Long.MAX_VALUE : refreshDurationNs * 4L;
        long minimumElapsedNs = Math.max(
                WSI_ACQUIRE_STARVATION_MIN_NS, fourRefreshNs);
        long elapsedNs = nowNs - wsiAcquireStarvationStartNs;
        if (consecutiveWsiAcquireNotReady >=
                        WSI_ACQUIRE_STARVATION_MIN_ATTEMPTS &&
                elapsedNs >= minimumElapsedNs) {
            if (!wsiAcquireStarvationActive) {
                wsiAcquireStarvationActive = true;
                ++presentationDiscontinuities;
                Log.e(TAG, "RIFE swapchain acquire interruption" +
                        " attempts=" + consecutiveWsiAcquireNotReady +
                        " elapsedNs=" + elapsedNs +
                        " refreshNs=" + refreshDurationNs +
                        " pendingPhysical=" + submitted.size());
            }
            nextWsiAcquireProbeNs = nowNs + minimumElapsedNs;
        }
    }

    private void resetWsiAcquireStarvation() {
        if (wsiAcquireStarvationActive)
            Log.i(TAG, "RIFE swapchain acquire recovered" +
                    " attempts=" + consecutiveWsiAcquireNotReady +
                    " pendingPhysical=" + submitted.size());
        consecutiveWsiAcquireNotReady = 0;
        wsiAcquireStarvationStartNs = 0L;
        wsiAcquireStarvationActive = false;
        nextWsiAcquireProbeNs = 0L;
    }

    /**
     * Arms the persistent native worker with the immutable WSI release window.
     * Java neither sleeps nor spins and never derives a replacement target.
     */
    private boolean scheduleNativeRelease(
            FrameGenerationPresentationRequest request) {
        requireOwner();
        if (surfaceControlPresentation) return true;
        if (nativeReleaseScheduled || request == null ||
                request.queueReleaseNotBeforeNs() <= 0L ||
                request.queueReleaseNotBeforeNs() >=
                        request.hardCompletionDeadlineNs())
            throw new IllegalStateException(
                    "RIFE deferred WSI release contract is invalid");
        if (!bridge.scheduleHardwareBufferRifePresentationRelease(
                request.queueReleaseNotBeforeNs(),
                request.hardCompletionDeadlineNs(),
                request.immediatePriorPhysicalScanRelease()))
            return false;
        nativeReleaseNotBeforeNs = request.queueReleaseNotBeforeNs();
        nativeReleaseDeadlineNs = request.hardCompletionDeadlineNs();
        nativeReleaseScheduled = true;
        return true;
    }

    /** Returns false while the native worker still owns the pending window. */
    private boolean pollNativeRelease() {
        requireOwner();
        if (surfaceControlPresentation) return true;
        if (!nativeReleaseScheduled) return true;
        long releasedNs = bridge.pollHardwareBufferRifePresentationRelease();
        if (releasedNs == 0L) {
            long nowNs = System.nanoTime();
            if (nowNs >= nativeReleaseDeadlineNs) {
                nativeReleaseScheduled = false;
                throw new IllegalStateException(
                        "RIFE native timed release did not finish before cutoff" +
                        " nowNs=" + nowNs +
                        " cutoffNs=" + nativeReleaseDeadlineNs);
            }
            return false;
        }
        if (releasedNs < nativeReleaseNotBeforeNs ||
                releasedNs >= nativeReleaseDeadlineNs) {
            nativeReleaseScheduled = false;
            throw new IllegalStateException(
                    "RIFE native timed release timestamp escaped its window");
        }
        nativeReleaseScheduled = false;
        ++nativeReleaseCount;
        long priorLatenessMaxNs = nativeReleaseLatenessMaxNs;
        nativeReleaseLatenessMaxNs = Math.max(nativeReleaseLatenessMaxNs,
                releasedNs - nativeReleaseNotBeforeNs);
        if (nativeReleaseLatenessMaxNs > 500_000L &&
                nativeReleaseLatenessMaxNs > priorLatenessMaxNs)
            Log.w(TAG, "RIFE native WSI release lateness high" +
                    " count=" + nativeReleaseCount +
                    " latenessNs=" +
                            (releasedNs - nativeReleaseNotBeforeNs) +
                    " maxNs=" + nativeReleaseLatenessMaxNs +
                    " windowNs=" +
                            (nativeReleaseDeadlineNs -
                                    nativeReleaseNotBeforeNs));
        if (nativeReleaseCount == 1L)
            Log.i(TAG, "RIFE native timed WSI release armed" +
                    " releaseNs=" + releasedNs +
                    " notBeforeNs=" + nativeReleaseNotBeforeNs +
                    " cutoffNs=" + nativeReleaseDeadlineNs +
                    " latenessNs=" +
                            (releasedNs - nativeReleaseNotBeforeNs));
        return true;
    }

    private void pollNativePresentationCompletion() {
        if (nativePending) {
            int completion = bridge.pollPresentation();
            if (completion < 0)
                throw new IllegalStateException("RIFE native presentation completion failed");
            if (completion == 1) {
                if (nativeInFlight == null || nativeInFlight.gpuWorkNs != 0L)
                    throw new IllegalStateException(
                            "RIFE native completion identity is invalid");
                nativeInFlight.gpuWorkNs =
                        bridge.takeCompletedPresentationGpuWorkNs();
                NativeRifeBridge.ContentProof nativeProof =
                        bridge.takeCompletedPresentationContentProof();
                if (nativeProof.sequence != nativeInFlight.proofSequence)
                    throw new IllegalStateException(
                            "RIFE content-proof sequence mismatch");
                boolean currentTimeline =
                        nativeInFlight.timelineEpoch == timelineEpoch;
                if (currentTimeline) {
                    recordPairAssessment(
                            nativeInFlight.request.leftSequence(),
                            nativeInFlight.request.rightSequence(),
                            nativeProof.sceneCutRisk);
                }
                boolean expectedLookahead =
                        nativeInFlight.lookaheadSequence > 0L;
                if (nativeProof.lookaheadAvailable != expectedLookahead)
                    throw new IllegalStateException(
                            "RIFE look-ahead proof availability mismatch");
                if (expectedLookahead && currentTimeline) {
                    RetainedEndpoint lookahead = retained.get(
                            nativeInFlight.lookaheadSequence);
                    if (lookahead == null ||
                            lookahead.timestampNs !=
                                    nativeInFlight.lookaheadTimestampNs ||
                            nativeInFlight.lookaheadSequence !=
                                    nativeInFlight.request.rightSequence() + 1L)
                        throw new IllegalStateException(
                                "RIFE look-ahead proof identity mismatch");
                    recordPairAssessment(
                            nativeInFlight.request.rightSequence(),
                            nativeInFlight.lookaheadSequence,
                            nativeProof.lookaheadSceneCutRisk);
                    if (++lookaheadProofCompletedCount == 1L)
                        Log.i(TAG, "RIFE prepared look-ahead proof completed" +
                                " left=" +
                                    nativeInFlight.request.rightSequence() +
                                " right=" +
                                    nativeInFlight.lookaheadSequence);
                }
                if (nativeInFlight.request.isGenerated() &&
                        nativeProof.sceneCutRisk)
                    throw new IllegalStateException(
                            "RIFE generated output crossed a rejected pair");
                nativeInFlight.contentProof = new ExternalGeneratedContentProof(
                        nativeProof.leftChecksum, nativeProof.rightChecksum,
                        nativeProof.outputChecksum, nativeProof.endpointMadPpm,
                        nativeProof.outputLeftMadPpm,
                        nativeProof.outputRightMadPpm,
                        nativeProof.endpointHistogramDistancePpm,
                        nativeProof.outputMin, nativeProof.outputMax,
                        nativeProof.sceneCutRisk, nativeProof.analysisWallNs,
                        nativeProof.width, nativeProof.height,
                        nativeProof.sampleCount, nativeProof.sequence,
                        nativeProof.byteCount);
                nativePending = false;
                nativeInFlight = null;
                retireDiscardedEndpoints();
            }
        }
    }

    /**
     * Polls GPU completion and all currently released physical-present rows.
     * Returned rows—and only returned rows—may increment actual delivered FPS.
     */
    @Override public List<PresentationEvent> poll() {
        requireOwner();
        requireOpen();
        if (appOwnedPresentation) {
            if (!preparationInFlight) {
                drainDeferredOutputReleases();
                bridge.pollBoundHardwareBufferRifeOutputs();
                secondaryBridge.pollBoundHardwareBufferRifeOutputs();
            }
            pollPreparedPresentation();
            swapPreparations();
            try {
                pollPreparedPresentation();
            } finally {
                swapPreparations();
            }
            scheduleEndpointPreparation();
            return java.util.Collections.emptyList();
        }
        if (!startupSurfaceProbeComplete) {
            advanceStartupSurfaceDrainProbe();
            return java.util.Collections.emptyList();
        }
        if (!pollNativeRelease()) return java.util.Collections.emptyList();
        // The preparation worker owns the native context mutex while creating
        // a cold per-buffer import pipeline.  Never let the renderer owner
        // block behind it. No native GPU submission is active when the worker
        // is admitted; only already-submitted rows whose physical timing is
        // still delayed may exist, so deferring their query is exact.
        if (preparationInFlight) return java.util.Collections.emptyList();
        pollPreparedPresentation();
        pollNativePresentationCompletion();
        ArrayList<PresentationEvent> completed = new ArrayList<>();
        while (true) {
            NativeRifeBridge.PresentationTiming timing =
                    bridge.pollPresentationTiming();
            if (timing == null) break;
            SubmittedPresentation pending = findSubmitted(timing.presentId);
            if (pending == null)
                throw new IllegalStateException(
                        "RIFE physical presentation identity mismatch");
            if (timing.dropped) {
                if (pending.timing != null || pending.physicallyDropped)
                    throw new IllegalStateException(
                            "RIFE dropped presentation identity mismatch");
                pending.physicallyDropped = true;
                continue;
            }
            if (pending.timing != null ||
                    timing.desiredPresentTimeNs !=
                            pending.nativeDesiredPresentTimeNs ||
                    (surfaceControlPresentation &&
                            timing.frameTimelineDeadlineNs !=
                                    pending.request.
                                            compositorFrameTimelineDeadlineNs()) ||
                    (!surfaceControlPresentation &&
                            (timing.frameTimelineDeadlineNs != 0L ||
                             timing.transactionApplyStartNs != 0L ||
                             timing.transactionApplyEndNs != 0L)))
                throw new IllegalStateException(
                        "RIFE physical presentation identity mismatch");
            if (surfaceControlPresentation &&
                    timing.earliestPresentTimeNs >
                            timing.frameTimelineDeadlineNs) {
                Log.e(TAG, "RIFE compositor deadline miss evidence" +
                        " presentId=" + timing.presentId +
                        " timelineDeadlineNs=" +
                                timing.frameTimelineDeadlineNs +
                        " applyStartNs=" + timing.transactionApplyStartNs +
                        " applyEndNs=" + timing.transactionApplyEndNs +
                        " reserveAtApplyStartNs=" +
                                (timing.frameTimelineDeadlineNs -
                                        timing.transactionApplyStartNs) +
                        " reserveAtApplyEndNs=" +
                                (timing.frameTimelineDeadlineNs -
                                        timing.transactionApplyEndNs) +
                        " latchNs=" + timing.earliestPresentTimeNs +
                        " actualNs=" + timing.actualPresentTimeNs);
            }
            if (!surfaceControlPresentation) {
                ++directLifecycleTimingCount;
                boolean earlyDesired = timing.actualPresentTimeNs <
                        timing.desiredPresentTimeNs;
                boolean actualBeforeGate = timing.actualPresentTimeNs <
                        timing.directGateSignalStartNs;
                // Qualification logs every exact-ID row. r117's six-ms arm
                // was early while r118's four-ms generated row was late; a
                // predicate that emitted only early rows hid half the physical
                // bracket and made the release boundary unauditable.
                Log.i(TAG, "RIFE direct presentation lifecycle" +
                            " count=" + directLifecycleTimingCount +
                            " presentId=" + timing.presentId +
                            " generated=" +
                                    (pending.request.isGenerated() ? 1 : 0) +
                            " contentNs=" + pending.request.
                                    desiredPhysicalPresentTimeNs() +
                            " desiredNs=" + timing.desiredPresentTimeNs +
                            " actualNs=" + timing.actualPresentTimeNs +
                            " earliestNs=" +
                                    timing.earliestPresentTimeNs +
                            " prequeueStartNs=" +
                                    timing.directPrequeueStartNs +
                            " prequeueEndNs=" +
                                    timing.directPrequeueEndNs +
                            " gateNotBeforeNs=" +
                                    timing.directGateNotBeforeNs +
                            " gateCutoffNs=" +
                                    timing.directGateCutoffNs +
                            " gateSignalStartNs=" +
                                    timing.directGateSignalStartNs +
                            " gateSignalEndNs=" +
                                    timing.directGateSignalEndNs +
                            " earlyDesired=" + (earlyDesired ? 1 : 0) +
                            " actualBeforeGate=" +
                                    (actualBeforeGate ? 1 : 0));
            }
            // The native boundary emits no timing row for a SurfaceControl
            // OnComplete callback that explicitly omitted its present fence.
            // It preserves order, retires that dropped buffer only after its
            // release fence, then exposes the next physically proven ID. The
            // resulting ID gap is therefore the same fail-closed drop evidence
            // as an omitted VK_GOOGLE_display_timing row; it is never a relabel.
            for (SubmittedPresentation candidate : submitted) {
                if (candidate.presentId >= timing.presentId) break;
                if (candidate.timing == null)
                    candidate.physicallyDropped = true;
            }
            pending.timing = timing;
        }
        while (true) {
            SubmittedPresentation pending = submitted.peekFirst();
            if (pending == null) break;
            if (pending.physicallyDropped) {
                submitted.removeFirst();
                completed.add(PresentationEvent.dropped(
                        pending.request, pending.presentId, refreshDurationNs));
                continue;
            }
            if (pending.timing == null ||
                    pending.gpuWorkNs == 0L || pending.contentProof == null) break;
            submitted.removeFirst();
            NativeRifeBridge.PresentationTiming timing = pending.timing;
            if (timing.presentMarginNs < 0L) {
                Log.w(TAG, "Clamping bounded wrapped physical present margin" +
                        " presentId=" + timing.presentId +
                        " marginRawUnsigned=" +
                        Long.toUnsignedString(timing.presentMarginNs) +
                        " refreshNs=" + timing.refreshDurationNs);
            }
            completed.add(PresentationEvent.presented(
                    new PhysicalPresentation(
                            pending.request, timing.presentId,
                            timing.desiredPresentTimeNs,
                            timing.actualPresentTimeNs,
                            timing.earliestPresentTimeNs,
                            timing.presentMarginNs,
                            timing.refreshDurationNs, pending.enqueueWallNs,
                            pending.gpuWorkNs, pending.contentProof)));
        }
        scheduleEndpointPreparation();
        return completed;
    }

    private SubmittedPresentation findSubmitted(long presentId) {
        for (SubmittedPresentation pending : submitted) {
            if (pending.presentId == presentId) return pending;
        }
        return null;
    }

    @Override public int pendingPhysicalPresentationCount() {
        requireOwner();
        return appOwnedPresentation ? 0 : submitted.size();
    }

    private boolean nativeReferences(long sequence) {
        RetainedEndpoint endpoint = retained.get(sequence);
        if (endpoint != null && endpoint.preparing) return true;
        for (PreparedPresentation ready : readyOutputs.values())
            if (ready.request.leftSequence() == sequence || ready.request.rightSequence() == sequence) return true;
        PreparedPresentation privateOutput = preparedPresentation;
        PreparedPresentation queued = queuedPreparation;
        if (queued != null && (queued.request.leftSequence() == sequence ||
                queued.request.rightSequence() == sequence || queued.lookaheadSequence == sequence)) return true;
        if (privateOutput != null &&
                (privateOutput.request.leftSequence() == sequence ||
                        privateOutput.request.rightSequence() == sequence ||
                        privateOutput.lookaheadSequence == sequence))
            return true;
        for (AppOwnedOutput appOutput : boundAppOwnedOutputs.values()) {
            if (
                (appOutput.request.leftSequence() == sequence ||
                        appOutput.request.rightSequence() == sequence))
                return true;
        }
        SubmittedPresentation pending = nativeInFlight;
        return pending != null &&
                (pending.request.leftSequence() == sequence ||
                        pending.request.rightSequence() == sequence ||
                        pending.lookaheadSequence == sequence);
    }

    private void recordPairAssessment(
            long leftSequence, long rightSequence, boolean unsafe) {
        if (leftSequence <= 0L || rightSequence != leftSequence + 1L ||
                !retained.containsKey(leftSequence) ||
                !retained.containsKey(rightSequence))
            throw new IllegalStateException(
                    "RIFE pair assessment lost its retained endpoint identity");
        GenerationReadiness result = unsafe ?
                GenerationReadiness.UNSAFE : GenerationReadiness.READY;
        GenerationReadiness prior = pairReadiness.put(rightSequence, result);
        if (prior != null && prior != result)
            throw new IllegalStateException(
                    "RIFE pair assessment changed for immutable endpoints");
        while (pairReadiness.size() > MAX_IMAGES)
            pairReadiness.remove(pairReadiness.keySet().iterator().next());
    }

    private void retireDiscardedEndpoints() {
        java.util.Iterator<Map.Entry<Long, RetainedEndpoint>> iterator =
                retained.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<Long, RetainedEndpoint> entry = iterator.next();
            if (!entry.getValue().discardRequested || nativeReferences(entry.getKey()))
                continue;
            entry.getValue().image.close();
            iterator.remove();
        }
    }

    /**
     * Starts at most one cold import task and never while native presentation
     * work owns the Vulkan context.
     *
     * <p>Past-presentation timing rows are deliberately delayed by
     * {@code VK_GOOGLE_display_timing} for roughly one swapchain. They do not
     * own endpoint images or the Vulkan context. Blocking preparation merely
     * because {@link #submitted} is non-empty deadlocks the live path: the
     * driver cannot release its oldest timing row until more presentations
     * are submitted, while those presentations need their successor endpoint
     * imports. Conversely, chaining cold imports while an already prepared
     * presentation window is waiting starves the Choreographer owner of a
     * safe submission slot. Direct presentation yields at an adjacent pair.
     * Once the immutable generated-rate arm is active, its next-pair safety
     * proof needs one already-imported successor, so yield only after a
     * consecutive prepared three-endpoint window exists. This remains one
     * cold import at a time and never admits cold work on a visible deadline.</p>
     */
    private void scheduleEndpointPreparation() {
        requireOwner();
        if (closed || fatalFailure != null || !startupSurfaceProbeComplete ||
                preparationInFlight || nativePending) return;
        RetainedEndpoint selected;
        HardwareBuffer selectedBuffer;
        while (true) {
            selected = null;
            for (RetainedEndpoint endpoint : retained.values()) {
                if (!endpoint.prepared && !endpoint.preparing &&
                        !endpoint.discardRequested) {
                    selected = endpoint;
                    break;
                }
            }
            if (selected == null) return;
            selectedBuffer = selected.image.getHardwareBuffer();
            if (selectedBuffer == null || selectedBuffer.isClosed()) {
                fatalFailure = new IllegalStateException(
                        "RIFE endpoint preparation lost its HardwareBuffer");
                return;
            }
            boolean handedToWorker = false;
            try {
                // ImageReader reuses a bounded pool. Once a native buffer has
                // been imported, later Image wrappers for that same buffer can
                // become schedulable immediately without a worker hop or a
                // presentation-callback stall.
                if (!bridge.isHardwareBufferEndpointPrepared(
                        selectedBuffer, width, height) || !secondaryBridge.isHardwareBufferEndpointPrepared(selectedBuffer, width, height)) {
                    // The presentation window limits cold imports, not cheap
                    // reuse of already-imported buffers. Returning before the
                    // cache query hid retained future endpoints from inference
                    // even when their native imports were already available.
                    if (hasPreparedPresentationWindow()) return;
                    consecutiveCachedEndpointCount = 0;
                    endpointImportCacheWarm = false;
                    handedToWorker = true;
                    break;
                }
                selected.prepared = true;
                if (generatedRatePathActive &&
                        consecutiveCachedEndpointCount < MAX_IMAGES &&
                        ++consecutiveCachedEndpointCount == MAX_IMAGES) {
                    endpointImportCacheWarm = true;
                    Log.i(TAG, "RIFE endpoint import cache proven warm" +
                            " consecutiveHits=" +
                                    consecutiveCachedEndpointCount +
                            " required=" + MAX_IMAGES);
                }
                if (!generatedRatePathActive) {
                    consecutiveCachedEndpointCount = 0;
                    endpointImportCacheWarm = false;
                }
            } catch (RuntimeException queryFailure) {
                fatalFailure = queryFailure;
                return;
            } finally {
                // A cached-import query is synchronous. Close its temporary
                // Java wrapper now; only the uncached path transfers the
                // wrapper to the preparation worker below.
                if (!handedToWorker) selectedBuffer.close();
            }
        }
        final RetainedEndpoint endpoint = selected;
        final long sequence = endpoint.sequence;
        final HardwareBuffer buffer = selectedBuffer;
        endpoint.preparing = true;
        preparationInFlight = true;
        preparationWorker.execute(() -> {
            long startedNs = System.nanoTime();
            Throwable failure = null;
            try {
                bridge.prepareHardwareBufferEndpoint(buffer, width, height);
                secondaryBridge.prepareHardwareBufferEndpoint(buffer, width, height);
            } catch (Throwable prepareFailure) {
                failure = prepareFailure;
            } finally {
                // Native import retains its own AHardwareBuffer reference.
                // This Java wrapper belongs to one worker call and must never
                // be left to Cleaner on the presentation process.
                buffer.close();
            }
            long wallNs = Math.max(1L, System.nanoTime() - startedNs);
            final Throwable completedFailure = failure;
            owner.post(() -> finishEndpointPreparation(
                    sequence, endpoint, wallNs, completedFailure));
        });
    }

    private boolean hasPreparedPresentationWindow() {
        long previousSequence = 0L;
        int consecutivePrepared = 0;
        int requiredPrepared = generatedRatePathActive ? 3 : 2;
        for (RetainedEndpoint endpoint : retained.values()) {
            if (endpoint.discardRequested) {
                previousSequence = 0L;
                consecutivePrepared = 0;
                continue;
            }
            if (!endpoint.prepared) {
                previousSequence = endpoint.sequence;
                consecutivePrepared = 0;
                continue;
            }
            if (consecutivePrepared > 0 &&
                    endpoint.sequence == previousSequence + 1L) {
                ++consecutivePrepared;
            } else {
                consecutivePrepared = 1;
            }
            if (consecutivePrepared >= requiredPrepared)
                return true;
            previousSequence = endpoint.sequence;
        }
        return false;
    }

    private void finishEndpointPreparation(
            long sequence, RetainedEndpoint endpoint, long wallNs,
            Throwable failure) {
        requireOwner();
        preparationInFlight = false;
        endpoint.preparing = false;
        if (closed) return;
        RetainedEndpoint current = retained.get(sequence);
        if (failure != null) {
            fatalFailure = failure instanceof RuntimeException ?
                    (RuntimeException) failure :
                    new IllegalStateException(
                            "RIFE endpoint preparation failed", failure);
        } else if (current != endpoint) {
            fatalFailure = new IllegalStateException(
                    "RIFE prepared endpoint ownership changed");
        } else {
            consecutiveCachedEndpointCount = 0;
            endpointImportCacheWarm = false;
            endpoint.prepared = true;
            ++preparedEndpointCount;
            preparationWallMaxNs = Math.max(preparationWallMaxNs, wallNs);
            Log.i(TAG, "RIFE endpoint Vulkan import prepared" +
                    " sequence=" + sequence +
                    " wallNs=" + wallNs +
                    " prepared=" + preparedEndpointCount +
                    " wallMaxNs=" + preparationWallMaxNs);
        }
        retireDiscardedEndpoints();
        scheduleEndpointPreparation();
    }

    private void requireOwner() {
        if (Looper.myLooper() != owner.getLooper())
            throw new IllegalStateException("RIFE transport called from a foreign thread");
    }

    private void requireOpen() {
        if (closed) throw new IllegalStateException("RIFE transport is closed");
        if (fatalFailure != null)
            throw new IllegalStateException("RIFE endpoint transport failed", fatalFailure);
    }

    @Override public void close() {
        requireOwner();
        if (teardownComplete) return;
        closed = true;
        reader.setOnImageAvailableListener(null, null);
        acquisitionWorker.shutdown();
        boolean acquisitionStopped = false;
        try {
            acquisitionStopped = acquisitionWorker.awaitTermination(5L, TimeUnit.SECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
        if (!acquisitionStopped) {
            acquisitionWorker.shutdownNow();
            // Do not close/recycle a reader while its native acquire still runs.
            throw new IllegalStateException("RIFE image acquisition did not stop at teardown");
        }
        AcquiredEndpoint unpublished = acquiredEndpoint.getAndSet(null);
        if (unpublished != null && unpublished.image != null) unpublished.image.close();
        acquisitionInFlight = false;
        preparationWorker.shutdown();
        boolean preparationStopped = false;
        try {
            preparationStopped = preparationWorker.awaitTermination(
                    5L, TimeUnit.SECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
        if (!preparationStopped) {
            preparationWorker.shutdownNow();
            // Interruption is not proof that a native import stopped. Keep
            // its Images and reader retained rather than recycle live buffers.
            throw new IllegalStateException(
                    "RIFE endpoint preparation did not stop at session teardown");
        }
        preparationInFlight = false;
        recordingPresentation = null;
        drainDeferredOutputReleases();
        discardCachedOutputs();
        java.util.Iterator<AppOwnedOutput> bound = boundAppOwnedOutputs.values().iterator();
        while (bound.hasNext()) {
            AppOwnedOutput output = bound.next();
            boundOutputBridges.get(output.proofSequence).releaseBoundHardwareBufferRifeOutput(
                    output.proofSequence, false);
            deleteOwnedTexture(output.proofSequence);
            boundTextureIds.remove(output.proofSequence);
            boundOutputBridges.remove(output.proofSequence);
            bound.remove();
        }
        // Native teardown drains submitted GPU reads and output release fences.
        // Image.close() returns carriers to the producer, so it must follow
        // that drain, never precede it.
        try {
            if (!primaryTransportDrained) {
                JSONObject teardown = new JSONObject(bridge.closePresentationSurface());
                if (!teardown.getBoolean("closed"))
                    throw new IllegalStateException("RIFE native teardown did not drain cleanly");
                primaryTransportDrained = true;
            }
            if (!secondaryTransportDrained) {
                JSONObject secondTeardown = new JSONObject(secondaryBridge.closePresentationSurface());
                if (!secondTeardown.getBoolean("closed"))
                    throw new IllegalStateException("RIFE secondary teardown did not drain cleanly");
                secondaryTransportDrained = true;
            }
        } catch (org.json.JSONException invalidResult) {
            throw new IllegalStateException("RIFE native teardown result is invalid", invalidResult);
        }
        secondaryBridge.close();
        prepared.close();
        for (RetainedEndpoint endpoint : retained.values()) endpoint.image.close();
        retained.clear();
        pairReadiness.clear();
        expected.clear();
        submitted.clear();
        nativeInFlight = null;
        preparedPresentation = null;
        queuedPreparation = null;
        reader.close();
        teardownComplete = true;
    }

    private static final class ExpectedEndpoint {
        final long sequence;
        final long timestampNs;
        boolean discard;
        ExpectedEndpoint(long sequence, long timestampNs) {
            this.sequence = sequence;
            this.timestampNs = timestampNs;
        }
    }

    private static final class RetainedEndpoint {
        final long sequence;
        final long timestampNs;
        final Image image;
        boolean discardRequested;
        boolean preparing;
        boolean prepared;
        RetainedEndpoint(long sequence, long timestampNs, Image image) {
            this.sequence = sequence;
            this.timestampNs = timestampNs;
            this.image = image;
        }
    }

    private static final class SubmittedPresentation {
        final long presentId;
        final long proofSequence;
        final FrameGenerationPresentationRequest request;
        final long enqueueWallNs;
        final long lookaheadSequence;
        final long lookaheadTimestampNs;
        final long nativeDesiredPresentTimeNs;
        final long timelineEpoch;
        long gpuWorkNs;
        ExternalGeneratedContentProof contentProof;
        NativeRifeBridge.PresentationTiming timing;
        boolean physicallyDropped;
        SubmittedPresentation(long presentId, long proofSequence,
                              FrameGenerationPresentationRequest request,
                              long enqueueWallNs,
                              long lookaheadSequence,
                              long lookaheadTimestampNs,
                              long nativeDesiredPresentTimeNs,
                              long timelineEpoch) {
            this.presentId = presentId;
            this.proofSequence = proofSequence;
            this.request = request;
            this.enqueueWallNs = enqueueWallNs;
            this.lookaheadSequence = lookaheadSequence;
            this.lookaheadTimestampNs = lookaheadTimestampNs;
            this.nativeDesiredPresentTimeNs = nativeDesiredPresentTimeNs;
            this.timelineEpoch = timelineEpoch;
        }
    }

    private static final class PreparedPresentation {
        final NativeRifeBridge jobBridge;
        final FrameGenerationPreparationRequest request;
        final long proofSequence;
        final long lookaheadSequence;
        final long lookaheadTimestampNs;
        final long timelineEpoch;
        long dispatchedNs;
        volatile long workerStartedNs;
        volatile long dependencyReadyNs;
        volatile long nativeReturnedNs;
        boolean ready;
        boolean discardRequested;
        long gpuWorkNs;
        ExternalGeneratedContentProof contentProof;

        String timingDiagnostic(long observedNs, long deadlineNs) {
            // Snapshot worker fields once; -1 means the stage is not observed.
            long returned = nativeReturnedNs;
            long dependency = dependencyReadyNs;
            long started = workerStartedNs;
            return "proof:" + proofSequence +
                    ",observedNs:" + observedNs + ",deadlineNs:" + deadlineNs +
                    ",dispatchedNs:" + dispatchedNs + ",workerStartedNs:" + started +
                    ",dependencyReadyNs:" + dependency + ",nativeReturnedNs:" + returned +
                    ",queueNs:" + stageDuration(dispatchedNs, started) +
                    ",dependencyWaitNs:" + stageDuration(started, dependency) +
                    ",nativeCallNs:" + stageDuration(dependency, returned) +
                    ",sinceNativeReturnNs:" + stageDuration(returned, observedNs);
        }

        private static long stageDuration(long begin, long end) {
            return begin > 0L && end >= begin ? end - begin : -1L;
        }

        PreparedPresentation(
                NativeRifeBridge jobBridge,
                FrameGenerationPreparationRequest request,
                long proofSequence,
                long lookaheadSequence,
                long lookaheadTimestampNs,
                long timelineEpoch) {
            this.jobBridge = jobBridge;
            this.request = request;
            this.proofSequence = proofSequence;
            this.lookaheadSequence = lookaheadSequence;
            this.lookaheadTimestampNs = lookaheadTimestampNs;
            this.timelineEpoch = timelineEpoch;
        }
    }

}
