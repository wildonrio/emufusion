package com.thorium.preview.game;

import android.view.Surface;
import android.os.Handler;

import com.thorium.lucent.video.FrameGenerationPresentationRequest;
import com.thorium.lucent.video.FrameGenerationPreparationRequest;
import com.thorium.lucent.video.ExternalGeneratedContentProof;
import com.thorium.lucent.video.PhysicalPresentMargin;
import com.thorium.lucent.video.NativeSourceImageLedger;

import java.util.List;

/**
 * Optional renderer transport that consumes EmuFusion-owned presentation requests.
 *
 * <p>Implementations own pixels and presentation only. Source measurement,
 * output-rate selection, timestamp phase, underrun policy, and counters remain
 * in the one DisplayFrameGenerator/AdaptiveFrameRateController authority.</p>
 */
public interface ExternalFrameGenerationTransport extends AutoCloseable {
    enum EnqueueResult { SUBMITTED, DEFERRED, NOT_READY }
    enum GenerationReadiness { PENDING, READY, UNSAFE }
    enum PreparationResult { SUBMITTED, ALREADY_READY, NOT_READY }
    enum PreparationReadiness { ABSENT, PENDING, READY, UNSAFE }

    /** Opens one immutable transport at a renderer/session boundary. */
    interface Factory {
        /** Reopen an unused transport when the first software frame supplies native geometry. */
        default boolean nativeSoftwareGeometry() { return false; }
        /** Private input queue only; never changes the visible output surface. */
        default int endpointSwapInterval() { return 0; }
        ExternalFrameGenerationTransport open(
                Surface outputSurface, Handler owner,
                int suggestedWidth, int suggestedHeight) throws Exception;
    }

    /** GPU render target for one already-classified endpoint image. */
    Surface endpointSurface();

    int endpointWidth();

    int endpointHeight();

    /** Diagnostic/product label; never a selector or a capability claim. */
    default String backendLabel() { return "External"; }

    /**
     * Returns whether this exact backend build is authorized for the selected
     * source/output rate path.
     *
     * <p>Qualification is per path. Package presence, endpoint ownership, or
     * success at one rate must never authorize another rate with a different
     * phase/deadline budget. The safe default is no authorized path.</p>
     */
    default boolean supportsRatePath(int sourceFps, int outputFps) {
        return false;
    }

    /**
     * Largest output/source ratio this backend can serve.  A fixed-midpoint
     * backend returns 2.0 so the scheduler plans x2 targets (20->40, 30->60,
     * 60->120) instead of the built-in x3 tiers it can never fill.
     */
    default double maxGenerationFactor() {
        return com.thorium.lucent.video.UniformFrameRatePlan.MAX_GENERATION_FACTOR;
    }

    /**
     * Whether this transport can present either exact retained endpoint
     * without invoking frame generation.
     *
     * <p>This is the mandatory in-session Direct fallback for an external
     * qualification backend.  It is deliberately separate from
     * {@link #supportsRatePath(int, int)}: refusing an unqualified generated
     * path must leave the game visible, never turn the output surface black.
     * The safe default is false.</p>
     */
    default boolean supportsEndpointOnlyPresentation() {
        return false;
    }

    /**
     * Copies the newest compositor timelines from the same native
     * AChoreographer ownership domain used by ASurfaceTransaction.
     *
     * <p>The caller still owns target selection, expiry checks, and tolerance.
     * A backend only transports the immutable platform rows. Returning zero is
     * a fail-closed unavailable callback, never permission to reuse a Java
     * Choreographer token or synthesize a replacement.</p>
     */
    default int copyCompositorFrameTimelines(
            long[] vsyncIds, long[] expectedPresentationTimesNs,
            long[] deadlinesNs, long[] sourceMetadata) {
        return 0;
    }

    /**
     * Whether this transport requires an Android SurfaceControl frame-timeline
     * token on every immutable request.
     *
     * <p>The safe default is true. A direct Vulkan WSI transport may return
     * false only when it owns the real output Surface, requires
     * {@code VK_GOOGLE_display_timing}, and reports physical presentation
     * rows from that same swapchain. Such a transport still consumes the
     * EmuFusion-owned physical target and hard cutoff; it may not substitute
     * another clock.</p>
     */
    default boolean requiresCompositorFrameTimeline() { return true; }

    /**
     * Whether EmuFusion's EGL context, rather than this backend, owns the
     * visible output Surface and the only {@code eglSwapBuffers} call.
     *
     * <p>An app-owned backend may retain endpoints and generate a completed
     * private image, but it must not create a visible swapchain, submit a
     * SurfaceControl transaction, or count a generated image as delivered.
     * The safe default preserves the legacy backend-owned transport.</p>
     */
    default boolean usesAppOwnedPresentation() { return false; }

    /**
     * Publishes whether EmuFusion has selected this backend's exact generated
     * rate path for the current presentation epoch.
     *
     * <p>This is scheduling authority, not a backend capability probe. A
     * transport may use it only to prepare evidence for a future adjacent
     * pair; endpoint-only Direct presentation must remain unchanged while the
     * flag is false. The safe default performs no speculative work.</p>
     */
    default void setGeneratedRatePathActive(boolean active) {}

    /**
     * Owner-thread, zero-wait admission probe before announcing/exporting an image.
     * False transfers no ownership. The caller must count the rejected candidate
     * and break pair continuity; it must not increase capacity or wait for a fence.
     * An implementation without a separate carrier pool keeps its existing route.
     */
    default boolean canAcceptEndpoint() { return true; }

    /** Announces the immutable identity rendered by the next endpoint buffer. */
    void expectEndpoint(long sequence, long timestampNs);

    /**
     * Optional diagnostic observation of the exact image being exported. Copy
     * by value before returning; the caller may retire its lease immediately.
     * Missing/unknown metadata must not block real endpoints or grant authority.
     */
    default void expectEndpoint(long sequence, long timestampNs,
                                NativeSourceImageLedger provenance, int slot, long lease) {
        expectEndpoint(sequence, timestampNs);
    }

    /** Periodic, owner-thread coverage only; not a source/clock capability. */
    default String sourceProvenanceDiagnostic() { return "unsupported authority=false"; }

    /** Cancels only an announced endpoint whose EGL buffer was not submitted. */
    void cancelExpectedEndpoint(long sequence);

    /**
     * Consumes the number of announced endpoint buffers that the transport
     * proved were skipped before a later exact timestamp arrived.
     *
     * <p>A positive value is a presentation-timeline discontinuity. The
     * caller must discard its active pair and re-prime from later adjacent
     * endpoints; it may never relabel the later image as the missing one. The
     * safe default reports no independently observed loss.</p>
     */
    default long consumeEndpointDiscontinuities() { return 0L; }

    /**
     * Consumes transport-capacity interruptions that made the physical output
     * timeline unavailable for a bounded interval.
     *
     * <p>This is not an endpoint loss and must not be hidden as one. A positive
     * value tells EmuFusion to end the current presentation/proof epoch,
     * quarantine generated output for the session, and re-prime exact Direct
     * endpoints. Already-submitted physical rows remain reportable in their
     * original epoch. The safe default reports no independent interruption.</p>
     */
    default long consumePresentationDiscontinuities() { return 0L; }

    boolean hasAdjacentPair(long leftSequence, long rightSequence);

    /**
     * Returns whether the exact retained pair is safe to interpolate.
     *
     * <p>Endpoint ownership and generation safety are deliberately separate:
     * an UNSAFE pair may still present either exact endpoint, but no timestamp
     * strictly inside that interval may be submitted. Implementations must
     * never report READY before their nonblocking pair classifier has completed
     * for these exact sequence identities.</p>
     */
    default GenerationReadiness generationReadiness(
            long leftSequence, long rightSequence) {
        // Retention proves identity, not interpolation safety. A backend that
        // has not implemented and completed a classifier must remain direct.
        return GenerationReadiness.PENDING;
    }

    /**
     * Whether the exact endpoint after {@code rightSequence} is already
     * retained and backend-prepared for a look-ahead safety proof.
     *
     * <p>This never authorizes interpolation by itself.  It only lets the
     * renderer avoid putting a cold third-buffer import on a visible output
     * deadline. The safe default reports no prepared look-ahead.</p>
     */
    default boolean hasPreparedLookahead(long rightSequence) { return false; }

    void releaseBefore(long minimumSequence);

    /**
     * Ends the current endpoint chain without waiting for GPU work.
     *
     * <p>Already-submitted physical presentations remain reportable. Pending
     * producer buffers are consumed and discarded in order, and a native
     * in-flight request keeps its Images alive until its zero-wait completion
     * poll retires them.</p>
     */
    void resetEndpointTimeline();

    /**
     * Starts private GPU preparation without acquiring a swapchain image.
     *
     * <p>The preparation identity contains exact endpoints, timestamps, phase,
     * epoch, geometry and format, but no WSI deadline. Implementations must
     * retain that identity with the private output and return immediately. A
     * zero-wait NOT_READY result drops only this preparation opportunity; it
     * never authorizes synchronous inference inside {@link #enqueue}.</p>
     */
    default PreparationResult prepare(
            FrameGenerationPreparationRequest request) {
        return PreparationResult.NOT_READY;
    }

    /** Optional owner-thread notification after private recording frees capacity.
     * This is not GPU completion and never authorizes a visible presentation. */
    default void setPreparationCapacityListener(Runnable listener) {}

    /** Zero-wait readiness for the exact private-output identity. */
    default PreparationReadiness preparationReadiness(
            FrameGenerationPreparationRequest request) {
        return PreparationReadiness.ABSENT;
    }

    /** Private copying/proof of both real endpoints, never generation authority. */
    default boolean supportsPrivateRealPairPreparation() { return false; }

    /**
     * Announces an exact adjacent pair before any physical deadline exists.
     * The canonical phase-zero request identifies BOTH immutable endpoints;
     * later activation may select either endpoint, but never an interior pixel.
     */
    default PreparationResult prepareRealPair(
            FrameGenerationPreparationRequest request) {
        return PreparationResult.NOT_READY;
    }

    /** Zero-wait proof readiness for the same canonical real-pair identity. */
    default PreparationReadiness realPairPreparationReadiness(
            FrameGenerationPreparationRequest request) {
        return PreparationReadiness.ABSENT;
    }

    /**
     * Whether an endpoint presentation can be submitted immediately without
     * waiting for transport-owned work to retire.
     *
     * <p>This is a zero-wait capacity fact only. It does not authorize a
     * presentation slot, deadline, endpoint pair, or generated image. The
     * safe default preserves transports that have no asynchronous admission
     * state.</p>
     */
    default boolean visibleSubmissionReady() { return true; }

    /**
     * Whether one complete private generated-output execution has retired in
     * this transport session.
     *
     * <p>This is a warm-up fact only. It does not authorize a rate path, a
     * pair, or a prepared image. EmuFusion may use it to keep endpoint-only
     * Direct presentation active until one cold private execution has paid
     * its session-local pipeline cost, then discard that result and start a
     * fresh generated presentation epoch. The safe default never claims the
     * property.</p>
     */
    default boolean privateGenerationPipelineWarm() { return false; }

    /** Bounded future adjacent pairs supported by a retained-output provider. */
    default int preparationLookaheadPairs() { return 0; }

    /**
     * Binds the exact READY private generated image to {@code textureId} in
     * the caller's current EGL/GLES context without waiting.
     *
     * <p>The returned row owns the immutable request, native GPU duration and
     * content proof.  A null result is a normal not-ready slot; it never
     * authorizes a late retry. Backends that own visible presentation must not
     * implement this method.</p>
     */
    default AppOwnedOutput bindAppOwnedOutput(
            FrameGenerationPresentationRequest request, int textureId) {
        return null;
    }

    /**
     * Retires the exact image bound by {@link #bindAppOwnedOutput}.
     *
     * <p>Once bound, the image must always retire behind a nonblocking EGL
     * completion fence before its private slot is reusable—even when the
     * visible swap fails, because already-issued GL sampling commands may
     * still be in flight. {@code swapSucceeded} controls presentation
     * accounting only; it never weakens buffer-lifetime safety. Identity
     * changes fail closed.</p>
     */
    default void releaseAppOwnedOutput(
            AppOwnedOutput output, boolean swapSucceeded) {
        if (output != null)
            throw new UnsupportedOperationException(
                    "backend does not own an app-presented output");
    }

    /**
     * Zero-wait submission of the complete immutable EmuFusion contract.
     *
     * <p>The request owns session/presentation epochs, exact endpoint and
     * source timestamps, physical scan target, earlier platform timestamp,
     * hard GPU-completion cutoff, phase, geometry and format. Implementations
     * must reject a stale deadline or changed identity; they may not derive a
     * replacement clock or retry later. NOT_READY is an underrun and must
     * never catch up.</p>
     */
    EnqueueResult enqueue(FrameGenerationPresentationRequest request);

    /**
     * Zero-wait ordered physical-presentation events released since the prior
     * poll.
     *
     * <p>A compositor-rejected ID is an explicit event, not an inferred gap.
     * This is required for a dropped tail: no later successful presentation
     * may exist from which to infer the missing ID. Implementations must keep
     * dropped and presented events in submission order.</p>
     */
    List<PresentationEvent> poll();

    int pendingPhysicalPresentationCount();

    @Override void close();

    final class AppOwnedOutput {
        public final FrameGenerationPresentationRequest request;
        public final long proofSequence;
        public final long gpuWorkNs;
        public final ExternalGeneratedContentProof contentProof;
        /** Provider-retained GL texture, or zero for the caller-supplied texture. */
        public final int textureId;

        public AppOwnedOutput(
                FrameGenerationPresentationRequest request,
                long proofSequence, long gpuWorkNs,
                ExternalGeneratedContentProof contentProof) {
            this(request, proofSequence, gpuWorkNs, contentProof, 0);
        }

        public AppOwnedOutput(
                FrameGenerationPresentationRequest request,
                long proofSequence, long gpuWorkNs,
                ExternalGeneratedContentProof contentProof, int textureId) {
            if (request == null || !request.isGenerated() ||
                    proofSequence <= 0L || gpuWorkNs <= 0L ||
                    contentProof == null ||
                    contentProof.sequence != proofSequence || textureId < 0)
                throw new IllegalArgumentException(
                        "app-owned generated output identity is invalid");
            this.request = request;
            this.proofSequence = proofSequence;
            this.gpuWorkNs = gpuWorkNs;
            this.contentProof = contentProof;
            this.textureId = textureId;
        }
    }

    final class PresentationEvent {
        public enum Kind { PRESENTED, DROPPED }

        public final Kind kind;
        public final PhysicalPresentation presentation;
        public final FrameGenerationPresentationRequest request;
        public final long presentId;
        public final long refreshDurationNs;

        private PresentationEvent(
                Kind kind, PhysicalPresentation presentation,
                FrameGenerationPresentationRequest request,
                long presentId, long refreshDurationNs) {
            if (kind == null || request == null || presentId <= 0L ||
                    refreshDurationNs <= 0L)
                throw new IllegalArgumentException(
                        "physical presentation event identity is invalid");
            if ((kind == Kind.PRESENTED) != (presentation != null) ||
                    (presentation != null &&
                            (presentation.request != request ||
                             presentation.presentId != presentId ||
                             presentation.refreshDurationNs != refreshDurationNs)))
                throw new IllegalArgumentException(
                        "physical presentation event payload is invalid");
            this.kind = kind;
            this.presentation = presentation;
            this.request = request;
            this.presentId = presentId;
            this.refreshDurationNs = refreshDurationNs;
        }

        public static PresentationEvent presented(PhysicalPresentation row) {
            if (row == null)
                throw new IllegalArgumentException("physical presentation is absent");
            return new PresentationEvent(Kind.PRESENTED, row, row.request,
                    row.presentId, row.refreshDurationNs);
        }

        public static PresentationEvent dropped(
                FrameGenerationPresentationRequest request,
                long presentId, long refreshDurationNs) {
            return new PresentationEvent(Kind.DROPPED, null, request,
                    presentId, refreshDurationNs);
        }
    }

    final class PhysicalPresentation {
        public final FrameGenerationPresentationRequest request;
        public final long presentId;
        public final long desiredPresentTimeNs;
        public final long actualPresentTimeNs;
        public final long earliestPresentTimeNs;
        public final long presentMarginNs;
        public final long refreshDurationNs;
        public final long enqueueWallNs;
        public final long gpuWorkNs;
        public final ExternalGeneratedContentProof contentProof;

        public PhysicalPresentation(
                FrameGenerationPresentationRequest request,
                long presentId, long desiredPresentTimeNs, long actualPresentTimeNs,
                long earliestPresentTimeNs, long presentMarginNs,
                long refreshDurationNs, long enqueueWallNs, long gpuWorkNs,
                ExternalGeneratedContentProof contentProof) {
            if (request == null || contentProof == null)
                throw new IllegalArgumentException(
                        "physical presentation row identity is absent");
            if (presentId <= 0L || desiredPresentTimeNs <= 0L ||
                    actualPresentTimeNs <= 0L || refreshDurationNs <= 0L ||
                    enqueueWallNs <= 0L || gpuWorkNs <= 0L)
                throw new IllegalArgumentException(
                        "physical presentation row has a nonpositive core value" +
                        " presentId=" + presentId +
                        " desired=" + desiredPresentTimeNs +
                        " actual=" + actualPresentTimeNs +
                        " refresh=" + refreshDurationNs +
                        " enqueue=" + enqueueWallNs +
                        " gpu=" + gpuWorkNs);
            if (earliestPresentTimeNs <= 0L)
                throw new IllegalArgumentException(
                        "physical earliest-present time is invalid" +
                        " presentId=" + presentId +
                        " earliestRawUnsigned=" +
                        Long.toUnsignedString(earliestPresentTimeNs));
            long normalizedPresentMarginNs = PhysicalPresentMargin.normalize(
                    presentMarginNs, refreshDurationNs);
            this.request = request;
            this.presentId = presentId;
            this.desiredPresentTimeNs = desiredPresentTimeNs;
            this.actualPresentTimeNs = actualPresentTimeNs;
            this.earliestPresentTimeNs = earliestPresentTimeNs;
            this.presentMarginNs = normalizedPresentMarginNs;
            this.refreshDurationNs = refreshDurationNs;
            this.enqueueWallNs = enqueueWallNs;
            this.gpuWorkNs = gpuWorkNs;
            this.contentProof = contentProof;
        }
    }

}
