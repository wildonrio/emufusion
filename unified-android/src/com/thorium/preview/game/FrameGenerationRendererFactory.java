package com.thorium.preview.game;

import android.view.Surface;

import com.thorium.lucent.video.FrameGenerationBackendPolicy;

import java.util.function.BooleanSupplier;
import java.util.concurrent.atomic.AtomicLong;

/** Creates exactly one immutable renderer backend at a safe Surface boundary. */
public final class FrameGenerationRendererFactory {
    private static final AtomicLong CREATED = new AtomicLong();
    private FrameGenerationRendererFactory() {}

    public static FrameGenerationRenderer create(
            FrameGenerationBackendPolicy.Selection selection,
            Surface output, int inputWidth, int inputHeight,
            int outputWidth, int outputHeight, float refreshHz,
            String displayRole, int displayId) {
        return create(selection, output, inputWidth, inputHeight,
                outputWidth, outputHeight, refreshHz, displayRole, displayId,
                () -> false, () -> false, () -> false, () -> false);
    }

    public static FrameGenerationRenderer create(
            FrameGenerationBackendPolicy.Selection selection,
            Surface output, int inputWidth, int inputHeight,
            int outputWidth, int outputHeight, float refreshHz,
            String displayRole, int displayId,
            BooleanSupplier qualificationProof,
            BooleanSupplier densePyramid,
            BooleanSupplier denseV27,
            BooleanSupplier denseV28) {
        if (selection == null)
            throw new IllegalArgumentException("backend selection is required");
        if (selection.backend == FrameGenerationBackendPolicy.Backend.DIRECT)
            throw new IllegalArgumentException("Direct presentation has no renderer");
        if (selection.backend == FrameGenerationBackendPolicy.Backend.LSFG)
            throw new IllegalStateException("LSFG selected without an integrated renderer");
        BooleanSupplier safeProof = safe(qualificationProof);
        BooleanSupplier safeDense = safe(densePyramid);
        BooleanSupplier safeV27 = safe(denseV27);
        BooleanSupplier safeV28 = safe(denseV28);
        // The legacy dense renderer remains the only product implementation at
        // this checkpoint. The lawful RIFE qualification payload cannot enter
        // this branch until its common endpoint transport and live output
        // self-test are complete; package presence alone never changes it.
        FrameGenerationRenderer renderer = new DisplayFrameGenerator(output,
                inputWidth, inputHeight, outputWidth, outputHeight, refreshHz,
                displayRole, displayId,
                safeProof::getAsBoolean,
                safeDense::getAsBoolean,
                safeV27::getAsBoolean,
                safeV28::getAsBoolean);
        CREATED.incrementAndGet();
        return renderer;
    }

    /**
     * Creates the shell-only live-output qualification arm.
     *
     * <p>The caller may reach this method only after the conditional factory
     * was found in a qualification APK. It deliberately bypasses product
     * backend selection without marking the built-in assessment usable.</p>
     */
    static FrameGenerationRenderer createRifeQualification(
            ExternalFrameGenerationTransport.Factory transportFactory,
            Surface output, int inputWidth, int inputHeight,
            int outputWidth, int outputHeight, float refreshHz,
            String displayRole, int displayId,
            BooleanSupplier qualificationProof) {
        if (transportFactory == null)
            throw new IllegalArgumentException("RIFE qualification transport is required");
        return createExternalQualification(transportFactory, output,
                inputWidth, inputHeight, outputWidth, outputHeight, refreshHz,
                displayRole, displayId, qualificationProof);
    }

    /** Creates one shell-only external transport without changing product policy. */
    static FrameGenerationRenderer createExternalQualification(
            ExternalFrameGenerationTransport.Factory transportFactory,
            Surface output, int inputWidth, int inputHeight,
            int outputWidth, int outputHeight, float refreshHz,
            String displayRole, int displayId,
            BooleanSupplier qualificationProof) {
        if (transportFactory == null)
            throw new IllegalArgumentException(
                    "external qualification transport is required");
        FrameGenerationRenderer renderer = new DisplayFrameGenerator(output,
                inputWidth, inputHeight, outputWidth, outputHeight, refreshHz,
                displayRole, displayId,
                safe(qualificationProof)::getAsBoolean,
                () -> false, () -> false, () -> false, transportFactory);
        CREATED.incrementAndGet();
        return renderer;
    }

    /** Process-monotonic attestation; Off sessions must never advance it. */
    static long createdCount() { return CREATED.get(); }

    private static BooleanSupplier safe(BooleanSupplier value) {
        return value == null ? () -> false : value;
    }
}
