package com.thorium.preview.game;

import android.content.Context;
import android.graphics.PixelFormat;
import android.hardware.HardwareBuffer;
import android.hardware.SyncFence;
import android.media.Image;
import android.media.ImageReader;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.view.Surface;

import com.thorium.lucent.video.ExternalGeneratedContentProof;
import com.thorium.lucent.video.FrameGenerationPresentationRequest;
import com.thorium.lucent.video.FrameGenerationPreparationRequest;

import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.io.IOException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/** Qualification-only exact-endpoint/fixed-midpoint LSFG transport. */
public final class LsfgPresentationTransport
        implements ExternalFrameGenerationTransport, ImageReader.OnImageAvailableListener {
    private static final int MAX_IMAGES = 8;
    private static final int MAX_PENDING_PRESENTATIONS = 16;
    private static final int VK_PRESENT_MODE_FIFO_KHR = 2;

    // Native LSFG already has one process-wide g_libraryOwner. Reserve its
    // complete Java lifecycle too, BEFORE native open, and retain a strong
    // reference until full retirement. In-flight constructors count as owners.
    // No monitor is held across native calls or worker waits.
    private static final Object LIFECYCLE_LOCK = new Object();
    private static LsfgPresentationTransport lifecycleOwner;
    private static SurfaceOwnershipException processCloseFailure;

    private final Handler owner;
    private final int width;
    private final int height;
    private final ImageReader reader;
    private final Surface endpointSurface;
    private final long nativeHandle;
    private final ArrayDeque<ExpectedEndpoint> expected = new ArrayDeque<>();
    // Eight value slots mirror the bounded announced/acquired carrier owners.
    // Lazy setup only; no per-frame snapshot allocation or native query.
    private com.thorium.lucent.video.NativeSourceImageLedger endpointProvenance;
    private long endpointProvenanceFailures, endpointProvenanceMissing;
    private final LinkedHashMap<Long, RetainedEndpoint> retained =
            new LinkedHashMap<>();
    private final LinkedHashMap<Long, GenerationReadiness> pairReadiness =
            new LinkedHashMap<>();
    private final LinkedHashMap<Long, SubmittedPresentation> submitted =
            new LinkedHashMap<>();
    private final ExecutorService preparationWorker =
            Executors.newSingleThreadExecutor(runnable -> {
                Thread thread = new Thread(runnable, "EmuFusion-LSFG-Prepare");
                thread.setDaemon(true);
                return thread;
            });
    private long lastExpectedSequence;
    private long lastExpectedTimestampNs;
    private long endpointDiscontinuities;
    private long endpointDiscontinuitiesTotal;
    private long nextPresentId = 1L;
    private long requestSessionEpoch;
    private long requestPresentationEpoch;
    private boolean closed;
    private boolean retirementComplete;
    private SurfaceOwnershipException closeFailure;
    private boolean preparationInFlight;
    private boolean generatedRatePathActive;
    private boolean privateGenerationPipelineWarm;
    private boolean endpointImportCacheWarm;
    private PreparedGenerated preparedGenerated;
    private PreparedRealPair preparedRealPair;
    private FrameGenerationPreparationRequest announcedRealPair;
    private RuntimeException fatalFailure;
    private final AdmissionDiagnostics admission = new AdmissionDiagnostics();

    /** Fixed counters only: no per-attempt logging, allocation, or authority. */
    private static final class AdmissionDiagnostics {
        static final int DEADLINE=0, CAPACITY=1, ENDPOINT=2, FENCE=3,
                GENERATED_ABSENT=4, GENERATED_MISMATCH=5, GENERATED_PENDING=6,
                REAL_ABSENT=7, REAL_MISMATCH=8, REAL_IMPORT_BUSY=9,
                REAL_GPU_PENDING=10, NATIVE=11, PREPARE_NATIVE_BUSY=12,
                PREPARE_SUBMITTED=13, PREPARE_READY=14, REPLACE_PENDING=15,
                REPLACE_READY=16, IMPORT_OWNER_DELAY=17;
        private static final String[] NAMES = {"Deadline", "Capacity", "Endpoint",
                "Fence", "GeneratedAbsent", "GeneratedMismatch", "GeneratedPending",
                "RealAbsent", "RealMismatch", "RealImportBusy", "RealGpuPending", "Native",
                "PrepareNativeBusy", "PrepareSubmitted", "PrepareReady",
                "ReplacePending", "ReplaceReady", "ImportOwnerDelay"};
        final long[] counts = new long[NAMES.length];
        void record(int reason) {
            if (counts[reason] != Long.MAX_VALUE) ++counts[reason];
        }
        EnqueueResult blocked(int reason) {
            record(reason);
            return EnqueueResult.NOT_READY;
        }
        String describe() {
            StringBuilder result = new StringBuilder();
            for (int i=0;i<counts.length;++i)
                result.append(" admission").append(NAMES[i]).append('=').append(counts[i]);
            return result.toString();
        }
    }

    static LsfgPresentationTransport open(
            Context context, Surface outputSurface, Handler owner,
            int width, int height) throws Exception {
        if (outputSurface == null || !outputSurface.isValid() || owner == null ||
                width < 1 || height < 1)
            throw new IllegalArgumentException("valid LSFG output/owner/size required");
        requireLifecycleAdmissionAvailable();
        LsfgQualificationRuntime.Prepared prepared =
                LsfgQualificationRuntime.open(context);
        return new LsfgPresentationTransport(
                outputSurface, owner, width, height, prepared);
    }

    private LsfgPresentationTransport(
            Surface outputSurface, Handler owner, int width, int height,
            LsfgQualificationRuntime.Prepared prepared) throws Exception {
        this.owner = owner;
        this.width = width;
        this.height = height;
        // A rejected reservation has created no reader/native resources and
        // the lazy preparation executor has never started a thread.
        reserveLifecycleOwner();
        ImageReader createdReader = null;
        long createdHandle = 0L;
        try {
        if (Build.VERSION.SDK_INT < 33)
            throw new UnsupportedOperationException(
                    "LSFG zero-wait Image acquire fences require Android 13+");
        long usage = HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE |
                HardwareBuffer.USAGE_GPU_COLOR_OUTPUT;
        reader = createdReader = ImageReader.newInstance(
                width, height, PixelFormat.RGBA_8888, MAX_IMAGES, usage);
        endpointSurface = reader.getSurface();
        reader.setOnImageAvailableListener(this, owner);
        nativeHandle = createdHandle = NativeLsfgBridge.open(outputSurface,
                prepared.shaderDirectory.getAbsolutePath(), width, height);
        if (nativeHandle == 0L) throw new IllegalStateException("LSFG native open failed");
        JSONObject capabilities = new JSONObject(
                NativeLsfgBridge.capabilities(nativeHandle));
        long selfTestRefreshDurationNs = capabilities.getLong("refreshDurationNs");
        long selfTestPresentFenceOffsetNs =
                capabilities.getLong("selfTestPresentFenceOffsetNs");
        if (!capabilities.getBoolean("selfTestPassed") ||
                !capabilities.getBoolean("selfTestEndpoint") ||
                !capabilities.getBoolean("selfTestGenerated") ||
                !capabilities.getBoolean("selfTestDeadline") ||
                !capabilities.getBoolean("selfTestPhysicalTiming") ||
                !capabilities.getBoolean("selfTestContent") ||
                !capabilities.getBoolean("selfTestLiveSurfaceControl") ||
                !capabilities.getBoolean("selfTestLiveCadence") ||
                capabilities.getLong("selfTestLiveCadencePresents") != 240L ||
                capabilities.getLong("selfTestLiveCadenceGenerated") != 120L ||
                capabilities.getLong("selfTestLiveCadenceMinIntervalNs") <= 0L ||
                capabilities.getLong("selfTestLiveCadenceMaxIntervalNs") <
                        capabilities.getLong("selfTestLiveCadenceMinIntervalNs") ||
                !capabilities.getBoolean("androidArm64") ||
                !capabilities.getBoolean("fixedMidpoint") ||
                capabilities.getInt("generationCount") != 1 ||
                capabilities.getInt("slotCount") != 3 ||
                capabilities.getInt("presentMode") != VK_PRESENT_MODE_FIFO_KHR ||
                !capabilities.getBoolean("displayTiming") ||
                selfTestRefreshDurationNs <= 0L ||
                selfTestPresentFenceOffsetNs < 0L ||
                selfTestPresentFenceOffsetNs > selfTestRefreshDurationNs * 2L ||
                !capabilities.getBoolean("sameGraphicsPresentQueue") ||
                !capabilities.getBoolean("externalSyncFd") ||
                !capabilities.getBoolean("fixedBuffersImported") ||
                !capabilities.getBoolean("setupOwnershipReleased") ||
                !capabilities.getBoolean("liveResourcesReady") ||
                !capabilities.getBoolean("ownedWsiSetupPassed") ||
                capabilities.getBoolean("ownedWsiImplemented") ||
                !capabilities.getBoolean("ownedWsiFrozenReference") ||
                !capabilities.getBoolean("surfaceControlPresentation") ||
                !capabilities.getBoolean("surfaceControlDesiredPresentTime") ||
                !capabilities.getBoolean("surfaceControlPhysicalFence") ||
                !capabilities.getBoolean("surfaceControlLiveImplemented") ||
                !capabilities.getBoolean("surfaceControlReleaseFenceReuse") ||
                !capabilities.getBoolean("zeroWaitLivePath") ||
                capabilities.getBoolean("liveDeviceWaitIdle") ||
                capabilities.getBoolean("liveBlockingFenceWait")) {
            throw new UnsupportedOperationException("LSFG native self-test failed");
        }
        } catch (Exception | Error failure) {
            // The constructor never escapes on these paths, so normal close()
            // cannot run. Retire every successfully acquired resource here,
            // including native-open==0 and malformed capability JSON.
            closed = true; // Any already-posted reader callback must stop too.
            boolean cleanupFailed = false;
            boolean nativeRetired = createdHandle == 0L;
            if (createdHandle != 0L) {
                try {
                    NativeLsfgBridge.close(createdHandle);
                    nativeRetired = true;
                }
                catch (Throwable cleanup) {
                    failure.addSuppressed(cleanup);
                    cleanupFailed = true;
                }
            }
            if (createdReader != null) {
                try { createdReader.setOnImageAvailableListener(null, null); }
                catch (Throwable cleanup) {
                    failure.addSuppressed(cleanup);
                    cleanupFailed = true;
                }
                // Retain the exact reader too when native retirement is
                // unproven. The static lifecycle owner keeps this failed
                // constructor reachable; no retry or second host is admitted.
                if (nativeRetired) {
                    try { createdReader.close(); }
                    catch (Throwable cleanup) {
                        failure.addSuppressed(cleanup);
                        cleanupFailed = true;
                    }
                }
            }
            try { preparationWorker.shutdownNow(); }
            catch (Throwable cleanup) {
                failure.addSuppressed(cleanup);
                cleanupFailed = true;
            }
            if (cleanupFailed) throw quarantineCloseFailure(
                    new SurfaceOwnershipException("LSFG startup cleanup failed", failure));
            releaseLifecycleOwner();
            throw failure;
        }
    }

    private static void requireLifecycleAdmissionAvailable() {
        synchronized (LIFECYCLE_LOCK) {
            if (processCloseFailure != null) throw processCloseFailure;
            if (lifecycleOwner != null)
                throw new UnsupportedOperationException(
                        "LSFG already has a starting/live/closing process owner");
        }
    }

    private void reserveLifecycleOwner() {
        synchronized (LIFECYCLE_LOCK) {
            requireLifecycleAdmissionAvailable();
            lifecycleOwner = this;
        }
    }

    private void releaseLifecycleOwner() {
        synchronized (LIFECYCLE_LOCK) {
            if (lifecycleOwner != this)
                throw new IllegalStateException("LSFG lifecycle owner changed before retirement");
            lifecycleOwner = null;
        }
    }

    private SurfaceOwnershipException quarantineCloseFailure(Throwable failure) {
        synchronized (LIFECYCLE_LOCK) {
            if (closeFailure == null)
                closeFailure = failure instanceof SurfaceOwnershipException ?
                        (SurfaceOwnershipException) failure :
                        new SurfaceOwnershipException("LSFG retirement failed; restart the process", failure);
            if (processCloseFailure == null) processCloseFailure = closeFailure;
            // Never clear lifecycleOwner on an unproven close: it is the
            // process-lifetime strong quarantine for this transport, its
            // Images/HardwareBuffers, reader and preparation executor. No
            // further owner can be admitted, bounding quarantine to ONE host.
            closed = true;
            return closeFailure;
        }
    }

    @Override public Surface endpointSurface() { requireOwner(); requireOpen(); return endpointSurface; }
    @Override public int endpointWidth() { return width; }
    @Override public int endpointHeight() { return height; }

    @Override public String backendLabel() { return "LSFG"; }

    /** The bounded live feasibility arm is certified for no path beyond 20->40. */
    @Override public boolean supportsRatePath(int sourceFps, int outputFps) {
        // Fixed midpoint: exactly one generated frame per pair, so only x2
        // paths whose output divides the 120-Hz panel (40 = three scans,
        // 60 = two, 120 = one).  20->40 is the qualified Ocarina arm; 30->60
        // and 60->120 are admitted for the owner's live demonstration and
        // still fail closed per slot on any missed physical deadline.
        return outputFps == 2 * sourceFps &&
                (sourceFps == 20 || sourceFps == 30 || sourceFps == 60);
    }

    @Override public double maxGenerationFactor() { return 2.0; }

    /** Native capabilities require selfTestEndpoint before construction succeeds. */
    @Override public boolean supportsEndpointOnlyPresentation() { return true; }

    @Override public boolean supportsPrivateRealPairPreparation() { return true; }

    @Override public void setGeneratedRatePathActive(boolean active) {
        requireOwner();
        requireOpen();
        generatedRatePathActive = active;
        if (!active && preparedGenerated != null) {
            NativeLsfgBridge.discardPreparedGenerated(nativeHandle);
            preparedGenerated = null;
            retireDiscardedEndpoints();
        }
    }

    @Override public int copyCompositorFrameTimelines(
            long[] vsyncIds, long[] expectedPresentationTimesNs,
            long[] deadlinesNs, long[] sourceMetadata) {
        requireOwner();
        requireOpen();
        return NativeLsfgBridge.copyCompositorFrameTimelines(
                nativeHandle, vsyncIds, expectedPresentationTimesNs,
                deadlinesNs, sourceMetadata);
    }

    @Override public boolean canAcceptEndpoint() {
        requireOwner(); requireOpen();
        // Source copies can finish between owner callbacks. Release only images
        // already discarded by the renderer and proven unused by the native copy.
        retireDiscardedEndpoints();
        return expected.size() + retained.size() < MAX_IMAGES;
    }

    @Override public void expectEndpoint(long sequence, long timestampNs) {
        requireOwner(); requireOpen();
        if (sequence <= lastExpectedSequence || timestampNs <= lastExpectedTimestampNs)
            throw new IllegalArgumentException("LSFG endpoint identity is not monotonic");
        if (expected.size() + retained.size() >= MAX_IMAGES)
            throw new IllegalStateException("LSFG endpoint pool is full");
        expected.addLast(new ExpectedEndpoint(sequence, timestampNs));
        lastExpectedSequence = sequence;
        lastExpectedTimestampNs = timestampNs;
    }

    @Override public void cancelExpectedEndpoint(long sequence) {
        requireOwner(); requireOpen();
        ExpectedEndpoint tail = expected.peekLast();
        if (tail == null || tail.sequence != sequence)
            throw new IllegalStateException("LSFG cancellation is not the queue tail");
        expected.removeLast();
        tail.releaseProvenance();
    }

    @Override public void expectEndpoint(long sequence, long timestampNs,
            com.thorium.lucent.video.NativeSourceImageLedger provenance, int source, long lease) {
        expectEndpoint(sequence, timestampNs);
        if (provenance == null || lease == 0L) { ++endpointProvenanceMissing; return; }
        if (endpointProvenance == null)
            endpointProvenance = new com.thorium.lucent.video.NativeSourceImageLedger(MAX_IMAGES);
        int slot = 0;
        while (slot < MAX_IMAGES && endpointProvenance.lease(slot) != 0L) ++slot;
        if (slot == MAX_IMAGES) { ++endpointProvenanceFailures; ++endpointProvenanceMissing; return; }
        com.thorium.lucent.video.NativeSourceImageLedger.Result result =
                provenance.copyTo(source, lease, endpointProvenance, slot);
        if (result != com.thorium.lucent.video.NativeSourceImageLedger.Result.SUCCESS) {
            ++endpointProvenanceFailures;
            ++endpointProvenanceMissing;
            return;
        }
        endpointProvenance.recordExportedTimestamp(slot, endpointProvenance.lease(slot), timestampNs);
        ExpectedEndpoint tail = expected.peekLast();
        tail.provenance = endpointProvenance;
        tail.provenanceSlot = slot;
        tail.provenanceLease = endpointProvenance.lease(slot);
    }

    /** Periodic diagnostic only; missing coverage cannot authorize or block a real image. */
    @Override public String sourceProvenanceDiagnostic() {
        requireOwner();
        int expectedCovered = 0, retainedCovered = 0, mismatches = 0;
        for (ExpectedEndpoint identity : expected) {
            if (identity.provenanceLease != 0L) ++expectedCovered;
            if (identity.hasProvenanceMismatch()) ++mismatches;
        }
        for (RetainedEndpoint endpoint : retained.values()) {
            ExpectedEndpoint identity = endpoint.provenanceOwner;
            if (identity != null && identity.provenanceLease != 0L) ++retainedCovered;
            if (identity != null && identity.hasProvenanceMismatch()) ++mismatches;
        }
        return "authority=false expectedCovered=" + expectedCovered +
                " expectedMissing=" + (expected.size() - expectedCovered) +
                " retainedCovered=" + retainedCovered +
                " retainedMissing=" + (retained.size() - retainedCovered) +
                " liveMismatches=" + mismatches + " missingTotal=" + endpointProvenanceMissing +
                " failures=" + endpointProvenanceFailures + admission.describe();
    }

    @Override public void onImageAvailable(ImageReader source) {
        requireOwner();
        if (closed || fatalFailure != null) return;
        try {
            // acquireNextImage throws at maxImages even if the producer queue
            // is empty. Retained endpoints own all acquired Images outside
            // this callback; never probe for a ninth Image while holding eight.
            // This does not discard/relabel a queued endpoint or raise capacity.
            while (retained.size() < MAX_IMAGES) {
                Image image = source.acquireNextImage();
                if (image == null) return;
                boolean keep = false;
                HardwareBuffer buffer = null;
                try {
                    ExpectedEndpoint identity = expected.peekFirst();
                    long timestampNs = image.getTimestamp();
                    buffer = image.getHardwareBuffer();
                    ExpectedEndpoint exact = null;
                    int exactMatches = 0;
                    int skipped = 0;
                    int index = 0;
                    // Swap-interval-zero producer queues may replace an
                    // unacquired carrier. Only a UNIQUE, exactly announced
                    // timestamp proves that loss; never use nearest timestamps
                    // or assign the later image the missing endpoint's ID.
                    for (ExpectedEndpoint candidate : expected) {
                        if (candidate.timestampNs == timestampNs) {
                            exact = candidate;
                            skipped = index;
                            ++exactMatches;
                        }
                        ++index;
                    }
                    if (timestampNs <= 0L || exactMatches != 1 || exact == null)
                        throw new IllegalStateException(
                                "LSFG endpoint timestamp identity mismatch" +
                                " actualTimestampNs=" + timestampNs +
                                " expectedSequence=" + (identity == null ? 0L : identity.sequence) +
                                " expectedTimestampNs=" + (identity == null ? 0L : identity.timestampNs) +
                                " expectedDiscard=" + (identity != null && identity.discard) +
                                " exactMatches=" + exactMatches +
                                " expectedDepth=" + expected.size() +
                                " retainedDepth=" + retained.size() +
                                " lastExpectedSequence=" + lastExpectedSequence +
                                " lastExpectedTimestampNs=" + lastExpectedTimestampNs);
                    boolean bufferClosed = buffer != null && buffer.isClosed();
                    int bufferWidth = buffer == null || bufferClosed ? 0 : buffer.getWidth();
                    int bufferHeight = buffer == null || bufferClosed ? 0 : buffer.getHeight();
                    int bufferLayers = buffer == null || bufferClosed ? 0 : buffer.getLayers();
                    int bufferFormat = buffer == null || bufferClosed ? 0 : buffer.getFormat();
                    long bufferUsage = buffer == null || bufferClosed ? 0L : buffer.getUsage();
                    if (buffer == null || bufferClosed ||
                            bufferWidth != width || bufferHeight != height ||
                            bufferLayers != 1 || bufferFormat != HardwareBuffer.RGBA_8888 ||
                            (bufferUsage & HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE) == 0L)
                        throw new IllegalStateException(
                                "LSFG endpoint HardwareBuffer identity is invalid" +
                                " sequence=" + exact.sequence + " timestampNs=" + timestampNs +
                                " null=" + (buffer == null) + " closed=" + bufferClosed +
                                " actualSize=" + bufferWidth + "x" + bufferHeight +
                                " expectedSize=" + width + "x" + height +
                                " layers=" + bufferLayers + " format=" + bufferFormat +
                                " usage=" + bufferUsage + " skippedCandidates=" + skipped +
                                " expectedDepth=" + expected.size() +
                                " retainedDepth=" + retained.size());
                    // Validate the carrier before consuming any expectation or
                    // counting loss. Missing entries have never been acquired
                    // or imported; accepted Images/native owners are untouched.
                    if (skipped > 0) {
                        long pendingLoss = Math.addExact(endpointDiscontinuities, skipped);
                        long totalLoss = Math.addExact(endpointDiscontinuitiesTotal, skipped);
                        for (int missing = 0; missing < skipped; ++missing)
                            expected.removeFirst().releaseProvenance();
                        endpointDiscontinuities = pendingLoss;
                        endpointDiscontinuitiesTotal = totalLoss;
                        android.util.Log.w("EmuFusionLsfg", "LSFG endpoint carrier discontinuity" +
                                " skipped=" + skipped + " totalSkipped=" + totalLoss +
                                " firstSkippedSequence=" + identity.sequence +
                                " firstSkippedTimestampNs=" + identity.timestampNs +
                                " resumedSequence=" + exact.sequence +
                                " resumedTimestampNs=" + timestampNs +
                                " resumedDiscard=" + exact.discard +
                                " expectedDepth=" + expected.size() +
                                " retainedDepth=" + retained.size());
                    }
                    identity = expected.removeFirst();
                    if (identity.discard) { identity.releaseProvenance(); continue; }
                    if (retained.put(identity.sequence, new RetainedEndpoint(
                            identity.sequence, identity.timestampNs, image, buffer, identity)) != null)
                        throw new IllegalStateException("duplicate LSFG endpoint sequence");
                    keep = true;
                    scheduleEndpointPreparation();
                } finally {
                    if (!keep) {
                        try { if (buffer != null) buffer.close(); }
                        finally { image.close(); }
                    }
                }
            }
        } catch (RuntimeException failure) {
            fatalFailure = failure;
        }
    }

    @Override public long consumeEndpointDiscontinuities() {
        requireOwner(); requireOpen();
        long result = endpointDiscontinuities;
        endpointDiscontinuities = 0L;
        // The lifetime total intentionally survives reads and timeline resets.
        return result;
    }

    @Override public boolean hasAdjacentPair(long left, long right) {
        requireOwner(); requireOpen();
        RetainedEndpoint leftEndpoint = retained.get(left);
        RetainedEndpoint rightEndpoint = retained.get(right);
        // Importing a distinct look-ahead endpoint does not mutate either
        // member of an already-prepared pair.  Treating that tiny background
        // import as a global pair outage made the 20->40 scheduler count only
        // the roughly 60 callbacks on which no import was active, then apply
        // its three-scan divisor to those callbacks and present only ~20 Hz.
        return right == left + 1L &&
                leftEndpoint != null && rightEndpoint != null &&
                leftEndpoint.prepared && rightEndpoint.prepared;
    }

    @Override public boolean hasPreparedLookahead(long rightSequence) {
        requireOwner(); requireOpen();
        RetainedEndpoint endpoint = retained.get(rightSequence + 1L);
        return endpoint != null && endpoint.prepared && !endpoint.preparing;
    }

    @Override public GenerationReadiness generationReadiness(long left, long right) {
        requireOwner(); requireOpen();
        if (!hasAdjacentPair(left, right)) return GenerationReadiness.PENDING;
        GenerationReadiness result = pairReadiness.get(right);
        return result == null ? GenerationReadiness.PENDING : result;
    }

    @Override public void releaseBefore(long minimumSequence) {
        requireOwner(); requireOpen();
        java.util.Iterator<Map.Entry<Long, RetainedEndpoint>> iterator =
                retained.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<Long, RetainedEndpoint> entry = iterator.next();
            if (entry.getKey() >= minimumSequence) break;
            if (nativeReferences(entry.getKey())) entry.getValue().discardRequested = true;
            else { entry.getValue().close(); iterator.remove(); }
        }
        pairReadiness.entrySet().removeIf(entry -> entry.getKey() < minimumSequence);
        scheduleEndpointPreparation();
    }

    @Override public void resetEndpointTimeline() {
        requireOwner(); requireOpen();
        announcedRealPair = null;
        if (preparedRealPair != null) {
            NativeLsfgBridge.discardPreparedRealPair(nativeHandle);
            preparedRealPair = null;
        }
        if (preparedGenerated != null) {
            NativeLsfgBridge.discardPreparedGenerated(nativeHandle);
            preparedGenerated = null;
        }
        for (ExpectedEndpoint endpoint : expected) endpoint.discard = true;
        for (RetainedEndpoint endpoint : retained.values()) endpoint.discardRequested = true;
        pairReadiness.clear();
        requestPresentationEpoch = 0L;
        // Zero means "await the next positive renderer epoch" only in Java.
        // Native keeps retiring prior work until the first new request installs
        // that positive epoch. Passing zero would be an invalid native command.
        retireDiscardedEndpoints();
    }

    @Override public PreparationResult prepareRealPair(
            FrameGenerationPreparationRequest request) {
        requireOwner(); requireOpen();
        validateRealPairIdentity(request);
        // Announce before asynchronous import completes. The owner retries
        // this SAME identity from finishEndpointPreparation, not a guessed
        // newest pair and not a request containing a future physical target.
        announcedRealPair = request;
        if (preparationInFlight) return PreparationResult.NOT_READY;
        if (preparedRealPair != null &&
                !preparedRealPair.request.matches(request)) {
            // Owner-observed readiness only: do not poll or wait merely for
            // diagnostics, and do not infer GPU failure from replacement.
            admission.record(preparedRealPair.ready ?
                    AdmissionDiagnostics.REPLACE_READY : AdmissionDiagnostics.REPLACE_PENDING);
            NativeLsfgBridge.discardPreparedRealPair(nativeHandle);
            preparedRealPair = null;
            retireDiscardedEndpoints();
        }
        if (preparedRealPair != null) {
            return realPairPreparationReadiness(request) == PreparationReadiness.READY ?
                    PreparationResult.ALREADY_READY : PreparationResult.SUBMITTED;
        }
        RetainedEndpoint left = retained.get(request.leftSequence());
        RetainedEndpoint right = retained.get(request.rightSequence());
        if (left == null || right == null || !left.prepared || !right.prepared ||
                left.preparing || right.preparing ||
                left.discardRequested || right.discardRequested)
            return PreparationResult.NOT_READY;
        if (left.timestampNs != request.leftTimestampNs() ||
                right.timestampNs != request.rightTimestampNs())
            throw new IllegalStateException("LSFG real pair/Image identity mismatch");
        if (!endpointAcquireFenceReady(left) || !endpointAcquireFenceReady(right))
            return PreparationResult.NOT_READY;
        int result = NativeLsfgBridge.prepareRealPair(nativeHandle, left.buffer, right.buffer,
                request.sessionEpoch(), request.presentationEpoch(),
                request.leftSequence(), request.leftTimestampNs(),
                request.rightSequence(), request.rightTimestampNs(),
                width, height, request.outputFormat());
        if (result == NativeLsfgBridge.PREPARE_NOT_READY) {
            admission.record(AdmissionDiagnostics.PREPARE_NATIVE_BUSY);
            return PreparationResult.NOT_READY;
        }
        if (result != NativeLsfgBridge.PREPARE_SUBMITTED &&
                result != NativeLsfgBridge.PREPARE_READY)
            throw new IllegalStateException("LSFG private real pair submission failed");
        preparedRealPair = new PreparedRealPair(request, left, right,
                result == NativeLsfgBridge.PREPARE_READY);
        admission.record(preparedRealPair.ready ? AdmissionDiagnostics.PREPARE_READY :
                AdmissionDiagnostics.PREPARE_SUBMITTED);
        return preparedRealPair.ready ? PreparationResult.ALREADY_READY :
                PreparationResult.SUBMITTED;
    }

    @Override public PreparationReadiness realPairPreparationReadiness(
            FrameGenerationPreparationRequest request) {
        requireOwner(); requireOpen();
        validateRealPairIdentity(request);
        if (preparationInFlight) return PreparationReadiness.PENDING;
        PreparedRealPair current = preparedRealPair;
        if (current == null) return PreparationReadiness.ABSENT;
        if (!current.request.matches(request)) return PreparationReadiness.UNSAFE;
        if (!current.ready) {
            int result = NativeLsfgBridge.preparedRealPairReadiness(
                    nativeHandle, current.left.buffer, current.right.buffer,
                    request.sessionEpoch(), request.presentationEpoch(),
                    request.leftSequence(), request.leftTimestampNs(),
                    request.rightSequence(), request.rightTimestampNs());
            // Real readiness is GPU completion, not permission to interpolate.
            if (result != NativeLsfgBridge.PREPARE_SUBMITTED &&
                    result != NativeLsfgBridge.PREPARE_READY)
                throw new IllegalStateException("LSFG private real pair readiness failed");
            current.ready = result == NativeLsfgBridge.PREPARE_READY;
            if (current.ready) admission.record(AdmissionDiagnostics.PREPARE_READY);
        }
        return current.ready ? PreparationReadiness.READY : PreparationReadiness.PENDING;
    }

    private void validateRealPairIdentity(FrameGenerationPreparationRequest request) {
        if (request == null || request.isGenerated() || request.phase() != 0.0 ||
                request.presentationTimestampNs() != request.leftTimestampNs() ||
                !request.hasAdjacentPair() || request.outputWidth() != width ||
                request.outputHeight() != height || request.outputFormat() !=
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM)
            throw new IllegalArgumentException("LSFG real pair announcement is not canonical");
        if ((requestSessionEpoch != 0L && requestSessionEpoch != request.sessionEpoch()) ||
                (requestPresentationEpoch != 0L &&
                        requestPresentationEpoch != request.presentationEpoch()))
            throw new IllegalStateException("LSFG real pair epoch changed without reset");
        // An import worker may own the native Host mutex. Defer first-epoch
        // binding too; the announcement will retry on that worker's completion.
        if (preparationInFlight) return;
        validatePreparationIdentity(request);
    }

    private void retryAnnouncedRealPair() {
        if (closed || fatalFailure != null || announcedRealPair == null) return;
        try {
            prepareRealPair(announcedRealPair);
        } catch (RuntimeException failure) {
            fatalFailure = failure;
        }
    }

    @Override public PreparationResult prepare(
            FrameGenerationPreparationRequest request) {
        requireOwner();
        requireOpen();
        validatePreparationIdentity(request);
        if (!generatedRatePathActive || !request.isGenerated() ||
                preparationInFlight)
            return PreparationResult.NOT_READY;
        if (!isExactMidpoint(request))
            throw new IllegalArgumentException(
                    "LSFG private output is not an exact midpoint");
        if (preparedGenerated != null &&
                !preparedGenerated.request.matches(request)) {
            NativeLsfgBridge.discardPreparedGenerated(nativeHandle);
            preparedGenerated = null;
            retireDiscardedEndpoints();
        }
        if (preparedGenerated != null) {
            PreparationReadiness readiness = preparationReadiness(request);
            return readiness == PreparationReadiness.READY ?
                    PreparationResult.ALREADY_READY :
                    PreparationResult.SUBMITTED;
        }
        RetainedEndpoint left = retained.get(request.leftSequence());
        RetainedEndpoint right = retained.get(request.rightSequence());
        if (left == null || right == null || !left.prepared || !right.prepared ||
                left.preparing || right.preparing)
            return PreparationResult.NOT_READY;
        if (left.timestampNs != request.leftTimestampNs() ||
                right.timestampNs != request.rightTimestampNs())
            throw new IllegalStateException(
                    "LSFG private preparation/Image identity mismatch");
        GenerationReadiness pairState = generationReadiness(
                request.leftSequence(), request.rightSequence());
        if (pairState == GenerationReadiness.UNSAFE)
            return PreparationResult.NOT_READY;
        int result = NativeLsfgBridge.prepareGenerated(
                nativeHandle, left.buffer, right.buffer,
                request.sessionEpoch(), request.presentationEpoch(),
                request.leftSequence(), request.leftTimestampNs(),
                request.rightSequence(), request.rightTimestampNs(),
                request.presentationTimestampNs(), width, height,
                request.outputFormat());
        if (result == NativeLsfgBridge.PREPARE_NOT_READY)
            return PreparationResult.NOT_READY;
        if (result != NativeLsfgBridge.PREPARE_SUBMITTED &&
                result != NativeLsfgBridge.PREPARE_READY)
            throw new IllegalStateException(
                    "LSFG private output submission failed");
        preparedGenerated = new PreparedGenerated(request, left, right,
                result == NativeLsfgBridge.PREPARE_READY);
        // Both endpoint AHBs were imported by prepareEndpoint(), and the
        // successful private submission just reused those exact cached images.
        endpointImportCacheWarm = true;
        if (preparedGenerated.ready) privateGenerationPipelineWarm = true;
        return preparedGenerated.ready ? PreparationResult.ALREADY_READY :
                PreparationResult.SUBMITTED;
    }

    @Override public PreparationReadiness preparationReadiness(
            FrameGenerationPreparationRequest request) {
        requireOwner();
        requireOpen();
        validatePreparationIdentity(request);
        if (preparationInFlight) return PreparationReadiness.PENDING;
        PreparedGenerated current = preparedGenerated;
        if (current == null) return PreparationReadiness.ABSENT;
        if (!current.request.matches(request)) return PreparationReadiness.UNSAFE;
        if (!current.ready) {
            int result = NativeLsfgBridge.preparedGeneratedReadiness(
                    nativeHandle, current.left.buffer, current.right.buffer,
                    request.sessionEpoch(), request.presentationEpoch(),
                    request.leftSequence(), request.leftTimestampNs(),
                    request.rightSequence(), request.rightTimestampNs(),
                    request.presentationTimestampNs());
            if (result == NativeLsfgBridge.PREPARE_UNSAFE)
                current.unsafe = true;
            if (result != NativeLsfgBridge.PREPARE_SUBMITTED &&
                    result != NativeLsfgBridge.PREPARE_READY &&
                    result != NativeLsfgBridge.PREPARE_UNSAFE)
                throw new IllegalStateException(
                        "LSFG private output readiness failed");
            current.ready = result == NativeLsfgBridge.PREPARE_READY;
            if (current.ready || current.unsafe) {
                privateGenerationPipelineWarm = true;
                GenerationReadiness assessment = current.unsafe ?
                        GenerationReadiness.UNSAFE : GenerationReadiness.READY;
                GenerationReadiness prior = pairReadiness.put(
                        request.rightSequence(), assessment);
                if (prior != null && prior != assessment)
                    throw new IllegalStateException(
                            "LSFG immutable private pair classification changed");
            }
        }
        if (current.unsafe) return PreparationReadiness.UNSAFE;
        return current.ready ? PreparationReadiness.READY :
                PreparationReadiness.PENDING;
    }

    @Override public boolean privateGenerationPipelineWarm() {
        requireOwner();
        requireOpen();
        // Warm-up output is intentionally never visible, so no generated
        // presentation asks preparationReadiness() for it. Poll that private
        // fence here; otherwise its slot can remain held forever while the
        // scheduler correctly waits for this exact warm-up fact.
        if (preparedGenerated != null && !preparedGenerated.ready &&
                !preparedGenerated.unsafe)
            preparationReadiness(preparedGenerated.request);
        return privateGenerationPipelineWarm && endpointImportCacheWarm;
    }

    private void validatePreparationIdentity(
            FrameGenerationPreparationRequest request) {
        if (request == null || !request.hasAdjacentPair() ||
                request.outputWidth() != width ||
                request.outputHeight() != height ||
                request.outputFormat() !=
                        FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM)
            throw new IllegalArgumentException(
                    "LSFG private preparation contract is invalid");
        if (requestSessionEpoch == 0L)
            requestSessionEpoch = request.sessionEpoch();
        if (request.sessionEpoch() != requestSessionEpoch)
            throw new IllegalStateException(
                    "LSFG preparation session identity changed in place");
        if (requestPresentationEpoch == 0L) {
            requestPresentationEpoch = request.presentationEpoch();
            NativeLsfgBridge.resetTimeline(nativeHandle,
                    requestPresentationEpoch);
        }
        if (request.presentationEpoch() != requestPresentationEpoch)
            throw new IllegalStateException(
                    "LSFG preparation epoch changed without timeline reset");
    }

    @Override public EnqueueResult enqueue(FrameGenerationPresentationRequest request) {
        requireOwner(); requireOpen();
        if (request == null || !request.hasAdjacentPair() ||
                request.outputWidth() != width || request.outputHeight() != height ||
                request.outputFormat() != FrameGenerationPresentationRequest.FORMAT_RGBA8_UNORM)
            throw new IllegalArgumentException("LSFG request contract is invalid");
        if (request.isGenerated() && !isExactMidpoint(request))
            throw new IllegalArgumentException("LSFG 3.1 supports exact midpoint only");
        if (requestSessionEpoch == 0L) requestSessionEpoch = request.sessionEpoch();
        if (request.sessionEpoch() != requestSessionEpoch)
            throw new IllegalStateException("LSFG session identity changed in place");
        if (requestPresentationEpoch == 0L) {
            requestPresentationEpoch = request.presentationEpoch();
            NativeLsfgBridge.resetTimeline(nativeHandle, requestPresentationEpoch);
        }
        if (request.presentationEpoch() != requestPresentationEpoch)
            throw new IllegalStateException("LSFG epoch changed without timeline reset");
        if (System.nanoTime() >= request.hardCompletionDeadlineNs())
            return admission.blocked(AdmissionDiagnostics.DEADLINE);
        if (submitted.size() >= MAX_PENDING_PRESENTATIONS)
            return admission.blocked(AdmissionDiagnostics.CAPACITY);
        RetainedEndpoint left = retained.get(request.leftSequence());
        RetainedEndpoint right = retained.get(request.rightSequence());
        if (left == null || right == null)
            return admission.blocked(AdmissionDiagnostics.ENDPOINT);
        if (left.timestampNs != request.leftTimestampNs() ||
                right.timestampNs != request.rightTimestampNs())
            throw new IllegalStateException("LSFG request/Image identity mismatch");
        if (!endpointAcquireFenceReady(left) || !endpointAcquireFenceReady(right))
            return admission.blocked(AdmissionDiagnostics.FENCE);
        if (request.isGenerated() && generationReadiness(
                request.leftSequence(), request.rightSequence()) != GenerationReadiness.READY)
            throw new IllegalStateException("LSFG pair is not classified safe");
        if (request.isGenerated()) {
            if (preparedGenerated == null)
                return admission.blocked(AdmissionDiagnostics.GENERATED_ABSENT);
            if (!preparedGenerated.request.matches(request))
                return admission.blocked(AdmissionDiagnostics.GENERATED_MISMATCH);
            if (preparationReadiness(
                            FrameGenerationPreparationRequest.from(request)) !=
                            PreparationReadiness.READY)
                return admission.blocked(AdmissionDiagnostics.GENERATED_PENDING);
        } else {
            if (preparedRealPair == null)
                return admission.blocked(AdmissionDiagnostics.REAL_ABSENT);
            if (!preparedRealPair.matches(request))
                return admission.blocked(AdmissionDiagnostics.REAL_MISMATCH);
            if (realPairPreparationReadiness(preparedRealPair.request) !=
                            PreparationReadiness.READY)
                return admission.blocked(preparationInFlight ?
                        AdmissionDiagnostics.REAL_IMPORT_BUSY : AdmissionDiagnostics.REAL_GPU_PENDING);
        }
        long presentId = nextPresentId;
        long startNs = System.nanoTime();
        int result = NativeLsfgBridge.enqueue(nativeHandle, left.buffer, right.buffer,
                request.sessionEpoch(), request.presentationEpoch(),
                request.leftSequence(), request.leftTimestampNs(),
                request.rightSequence(), request.rightTimestampNs(),
                request.presentationTimestampNs(),
                request.desiredPhysicalPresentTimeNs(),
                request.driverDesiredPresentTimeNs(),
                request.hardCompletionDeadlineNs(),
                request.compositorFrameTimelineVsyncId(),
                request.compositorTokenExpectedPresentationTimeNs(),
                request.compositorFrameTimelineDeadlineNs(), width, height,
                request.outputFormat(), presentId);
        long enqueueWallNs = System.nanoTime() - startNs;
        if (result == NativeLsfgBridge.SUBMIT_NOT_READY)
            return admission.blocked(AdmissionDiagnostics.NATIVE);
        if (result != NativeLsfgBridge.SUBMIT_ACCEPTED || enqueueWallNs <= 0L)
            throw new IllegalStateException("LSFG native submission failed");
        if (request.isGenerated()) preparedGenerated = null;
        else {
            preparedRealPair = null;
            announcedRealPair = null;
        }
        submitted.put(presentId, new SubmittedPresentation(
                presentId, request, enqueueWallNs));
        ++nextPresentId;
        return EnqueueResult.SUBMITTED;
    }

    @Override public List<PresentationEvent> poll() {
        requireOwner(); requireOpen();
        ArrayList<PresentationEvent> rows = new ArrayList<>();
        while (true) {
            long[] raw = NativeLsfgBridge.poll(nativeHandle);
            if (raw == null) break;
            if (raw.length != NativeLsfgBridge.COMPLETION_WORDS)
                throw new IllegalStateException("LSFG completion ABI mismatch");
            SubmittedPresentation pending = submitted.remove(raw[0]);
            if (pending == null || raw[1] != pending.request.driverDesiredPresentTimeNs())
                throw new IllegalStateException("LSFG completion identity mismatch");
            if (raw[2] == 0L) {
                rows.add(PresentationEvent.dropped(
                        pending.request, pending.presentId, raw[5]));
                continue;
            }
            GenerationReadiness readiness = raw[7] == NativeLsfgBridge.PAIR_READY ?
                    GenerationReadiness.READY : raw[7] == NativeLsfgBridge.PAIR_UNSAFE ?
                    GenerationReadiness.UNSAFE : GenerationReadiness.PENDING;
            if (readiness == GenerationReadiness.PENDING)
                throw new IllegalStateException("LSFG completion lacks pair classification");
            GenerationReadiness prior = pairReadiness.put(
                    pending.request.rightSequence(), readiness);
            if (prior != null && prior != readiness)
                throw new IllegalStateException("LSFG immutable pair classification changed");
            ExternalGeneratedContentProof proof = new ExternalGeneratedContentProof(
                    raw[8], raw[9], raw[10], raw[11], raw[12], raw[13], raw[14],
                    (int) raw[15], (int) raw[16], raw[17] != 0L,
                    raw[18], (int) raw[19],
                    (int) raw[20], (int) raw[21], raw[22], raw[23]);
            if (proof.sequence != pending.presentId ||
                    (pending.request.isGenerated() && readiness != GenerationReadiness.READY))
                throw new IllegalStateException("LSFG generated content proof is unsafe");
            rows.add(PresentationEvent.presented(
                    new PhysicalPresentation(
                            pending.request, pending.presentId,
                            raw[1], raw[2], raw[3], raw[4], raw[5],
                            pending.enqueueWallNs, raw[6], proof)));
        }
        retireDiscardedEndpoints();
        retryAnnouncedRealPair();
        scheduleEndpointPreparation();
        return rows;
    }

    private static boolean isExactMidpoint(FrameGenerationPresentationRequest request) {
        return isExactMidpoint(request.leftTimestampNs(),
                request.rightTimestampNs(), request.presentationTimestampNs());
    }

    private static boolean isExactMidpoint(FrameGenerationPreparationRequest request) {
        return isExactMidpoint(request.leftTimestampNs(),
                request.rightTimestampNs(), request.presentationTimestampNs());
    }

    private static boolean isExactMidpoint(long left, long right, long middle) {
        // Same floor-nanosecond representation as the renderer/native request;
        // the interpolation phase remains 1/2 for odd as well as even spans.
        return left > 0L && right > left && right - left >= 2L &&
                middle == left + (right - left) / 2L;
    }

    /** Zero-duration only: the render thread never waits for an endpoint producer. */
    private static boolean endpointAcquireFenceReady(RetainedEndpoint endpoint) {
        try (SyncFence fence = endpoint.image.getFence()) {
            // ImageReader represents an already-complete producer with an
            // invalid/empty fence. SyncFence.await() returns false for that
            // sentinel even though there is nothing to wait for.
            if (!fence.isValid()) return true;
            return fence.getSignalTime() != SyncFence.SIGNAL_TIME_PENDING;
        } catch (IOException failure) {
            throw new IllegalStateException("LSFG endpoint acquire fence failed", failure);
        }
    }

    private boolean nativeReferences(long sequence) {
        RetainedEndpoint endpoint = retained.get(sequence);
        // A cache import owns the native Host mutex. Retain conservatively
        // while it runs rather than blocking this owner on the query below.
        if (preparationInFlight || (endpoint != null && endpoint.preparing)) return true;
        if (preparedRealPair != null &&
                (preparedRealPair.request.leftSequence() == sequence ||
                        preparedRealPair.request.rightSequence() == sequence))
            return true;
        if (preparedGenerated != null &&
                (preparedGenerated.request.leftSequence() == sequence ||
                        preparedGenerated.request.rightSequence() == sequence))
            return true;
        // Submitted requests retain their immutable metadata and fixed native
        // output, not the original ImageReader pixels after their exact copy
        // fence completes. Native checks ALL matching copies, including abandoned
        // work. Unknown/pending copy ownership must still retain this Image.
        return endpoint != null && NativeLsfgBridge.referencesSourceImage(
                nativeHandle, endpoint.buffer);
    }

    @Override public boolean visibleSubmissionReady() {
        requireOwner(); requireOpen();
        return !preparationInFlight;
    }

    private void scheduleEndpointPreparation() {
        requireOwner();
        if (closed || fatalFailure != null || preparationInFlight ||
                hasPreparedPresentationWindow()) return;
        // A pending SurfaceControl row owns only its immutable fixed live
        // slot.  Endpoint import is cache-only, takes the native Host mutex,
        // and targets a different retained AHardwareBuffer.  Waiting for the
        // entire physical-present queue to drain created a circular stall:
        // the next pair could not be imported while output was active, so the
        // output path repeatedly ran out of its three-endpoint look-ahead.
        RetainedEndpoint selected = null;
        for (RetainedEndpoint endpoint : retained.values()) {
            if (!endpoint.prepared && !endpoint.preparing &&
                    !endpoint.discardRequested) {
                selected = endpoint;
                break;
            }
        }
        if (selected == null) return;
        final RetainedEndpoint endpoint = selected;
        endpoint.preparing = true;
        preparationInFlight = true;
        preparationWorker.execute(() -> {
            long startedNs = System.nanoTime();
            Throwable failure = null;
            try {
                NativeLsfgBridge.prepareEndpoint(nativeHandle, endpoint.buffer);
            } catch (Throwable prepareFailure) {
                failure = prepareFailure;
            }
            long wallNs = Math.max(1L, System.nanoTime() - startedNs);
            final Throwable completedFailure = failure;
            final long completedNs = System.nanoTime();
            owner.post(() -> {
                // Distinguish actual native import occupancy from an already
                // finished worker awaiting its serialized owner callback.
                // Count only; do not reorder callbacks or relax native leases.
                if (System.nanoTime() - completedNs >= 1_000_000L)
                    admission.record(AdmissionDiagnostics.IMPORT_OWNER_DELAY);
                finishEndpointPreparation(endpoint, wallNs, completedFailure);
            });
        });
    }

    private boolean hasPreparedPresentationWindow() {
        long prior = 0L;
        int adjacent = 0;
        // Both real-only and generated output advance from A/B to B/C. Keeping
        // only A/B imported in real-only mode prevents queued C from warming
        // until A retires, serializing the next import with its copy/proof work.
        // Target one cache-imported successor ahead in either mode. This does
        // not prepare a synthetic image or change the source-copy lease rules.
        int requiredAdjacent = 3;
        for (RetainedEndpoint endpoint : retained.values()) {
            if (endpoint.discardRequested || !endpoint.prepared) {
                prior = 0L;
                adjacent = 0;
                continue;
            }
            adjacent = adjacent > 0 && endpoint.sequence == prior + 1L ?
                    adjacent + 1 : 1;
            if (adjacent >= requiredAdjacent) return true;
            prior = endpoint.sequence;
        }
        return false;
    }

    private void finishEndpointPreparation(
            RetainedEndpoint endpoint, long wallNs, Throwable failure) {
        requireOwner();
        preparationInFlight = false;
        endpoint.preparing = false;
        if (closed) return;
        if (failure != null) {
            fatalFailure = failure instanceof RuntimeException ?
                    (RuntimeException) failure :
                    new IllegalStateException(
                            "LSFG endpoint preparation failed", failure);
            return;
        }
        if (retained.get(endpoint.sequence) != endpoint) {
            fatalFailure = new IllegalStateException(
                    "LSFG prepared endpoint ownership changed");
            return;
        }
        endpoint.prepared = true;
        android.util.Log.i("EmuFusionLsfg",
                "Endpoint Vulkan import prepared sequence=" +
                        endpoint.sequence + " wallNs=" + wallNs);
        retireDiscardedEndpoints();
        retryAnnouncedRealPair();
        scheduleEndpointPreparation();
    }

    private void retireDiscardedEndpoints() {
        java.util.Iterator<Map.Entry<Long, RetainedEndpoint>> iterator =
                retained.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<Long, RetainedEndpoint> entry = iterator.next();
            if (!entry.getValue().discardRequested || nativeReferences(entry.getKey())) continue;
            entry.getValue().close();
            iterator.remove();
        }
    }

    @Override public int pendingPhysicalPresentationCount() {
        requireOwner(); return submitted.size();
    }

    private void requireOwner() {
        if (Looper.myLooper() != owner.getLooper())
            throw new IllegalStateException("LSFG transport called from a foreign thread");
    }

    private void requireOpen() {
        if (closed) throw new IllegalStateException("LSFG transport is closed");
        if (fatalFailure != null)
            throw new IllegalStateException("LSFG endpoint transport failed", fatalFailure);
    }

    @Override public void close() {
        requireOwner();
        if (closeFailure != null) throw closeFailure;
        if (retirementComplete) return;
        if (closed) throw new SurfaceOwnershipException(
                "LSFG retirement is still in progress", null);
        closed = true;
        try {
            reader.setOnImageAvailableListener(null, null);
            preparationWorker.shutdown();
            if (!preparationWorker.awaitTermination(5L, TimeUnit.SECONDS))
                throw new IllegalStateException(
                        "LSFG endpoint preparation did not stop");
            // Native imports/prepared work may still reference these Images.
            // Only a proven native drain permits returning them to a producer.
            NativeLsfgBridge.close(nativeHandle);
            for (RetainedEndpoint endpoint : retained.values()) endpoint.close();
            retained.clear();
            for (ExpectedEndpoint endpoint : expected) endpoint.releaseProvenance();
            expected.clear();
            pairReadiness.clear();
            preparedGenerated = null;
            preparedRealPair = null;
            announcedRealPair = null;
            submitted.clear();
            reader.close();
            releaseLifecycleOwner();
            retirementComplete = true;
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw quarantineCloseFailure(interrupted);
        } catch (Throwable failure) {
            throw quarantineCloseFailure(failure);
        }
    }

    private static final class ExpectedEndpoint {
        final long sequence;
        final long timestampNs;
        boolean discard;
        com.thorium.lucent.video.NativeSourceImageLedger provenance;
        int provenanceSlot;
        long provenanceLease;
        ExpectedEndpoint(long sequence, long timestampNs) {
            this.sequence = sequence;
            this.timestampNs = timestampNs;
        }
        void releaseProvenance() {
            if (provenance != null && provenanceLease != 0L)
                provenance.release(provenanceSlot, provenanceLease);
            provenanceLease = 0L;
            provenance = null;
        }
        boolean hasProvenanceMismatch() {
            return provenance != null && provenanceLease != 0L &&
                    (provenance.classifiedJoin(provenanceSlot, provenanceLease) ==
                            com.thorium.lucent.video.NativeSourceImageLedger.TimestampJoin.MISMATCH ||
                     provenance.exportedJoin(provenanceSlot, provenanceLease) ==
                            com.thorium.lucent.video.NativeSourceImageLedger.TimestampJoin.MISMATCH);
        }
    }

    private static final class RetainedEndpoint {
        final long sequence;
        final long timestampNs;
        final Image image;
        final HardwareBuffer buffer;
        final ExpectedEndpoint provenanceOwner;
        boolean discardRequested;
        boolean preparing;
        boolean prepared;
        RetainedEndpoint(long sequence, long timestampNs, Image image,
                         HardwareBuffer buffer) {
            this(sequence, timestampNs, image, buffer, null);
        }
        RetainedEndpoint(long sequence, long timestampNs, Image image,
                         HardwareBuffer buffer, ExpectedEndpoint provenanceOwner) {
            this.sequence = sequence;
            this.timestampNs = timestampNs;
            this.image = image;
            this.buffer = buffer;
            this.provenanceOwner = provenanceOwner;
        }
        void close() {
            buffer.close();
            image.close();
            if (provenanceOwner != null) provenanceOwner.releaseProvenance();
        }
    }

    private static final class SubmittedPresentation {
        final long presentId;
        final FrameGenerationPresentationRequest request;
        final long enqueueWallNs;
        SubmittedPresentation(long presentId, FrameGenerationPresentationRequest request,
                              long enqueueWallNs) {
            this.presentId = presentId;
            this.request = request;
            this.enqueueWallNs = enqueueWallNs;
        }
    }

    private static final class PreparedGenerated {
        final FrameGenerationPreparationRequest request;
        final RetainedEndpoint left;
        final RetainedEndpoint right;
        boolean ready;
        boolean unsafe;
        PreparedGenerated(FrameGenerationPreparationRequest request,
                          RetainedEndpoint left, RetainedEndpoint right,
                          boolean ready) {
            this.request = request;
            this.left = left;
            this.right = right;
            this.ready = ready;
        }
    }

    private static final class PreparedRealPair {
        final FrameGenerationPreparationRequest request;
        final RetainedEndpoint left;
        final RetainedEndpoint right;
        boolean ready;
        PreparedRealPair(FrameGenerationPreparationRequest request,
                         RetainedEndpoint left, RetainedEndpoint right, boolean ready) {
            this.request = request;
            this.left = left;
            this.right = right;
            this.ready = ready;
        }
        boolean matches(FrameGenerationPresentationRequest visible) {
            if (visible == null || visible.isGenerated() || !visible.hasAdjacentPair())
                return false;
            long selected = visible.presentationTimestampNs();
            return (selected == request.leftTimestampNs() ||
                    selected == request.rightTimestampNs()) &&
                    visible.sessionEpoch() == request.sessionEpoch() &&
                    visible.presentationEpoch() == request.presentationEpoch() &&
                    visible.leftSequence() == request.leftSequence() &&
                    visible.leftTimestampNs() == request.leftTimestampNs() &&
                    visible.rightSequence() == request.rightSequence() &&
                    visible.rightTimestampNs() == request.rightTimestampNs() &&
                    visible.outputWidth() == request.outputWidth() &&
                    visible.outputHeight() == request.outputHeight() &&
                    visible.outputFormat() == request.outputFormat();
        }
    }
}
