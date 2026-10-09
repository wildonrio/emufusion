package com.thorium.preview.game;

import android.content.Context;
import android.os.Handler;
import android.view.Surface;

/** APK-conditional constructor for the quarantined RIFE live-output arm. */
public final class RifeQualificationTransportFactory
        implements ExternalFrameGenerationTransport.Factory {
    // Preserve the producer's geometry and use actual model RGB output.
    // Reduced-analysis reconstruction is not a qualified quality tier: do not
    // silently substitute it for native-size inference to meet a deadline.
    // Larger inputs still require device throughput/quality qualification.

    private final Context context;

    public static ExternalFrameGenerationTransport.Factory create(Context context) {
        if (context == null) throw new IllegalArgumentException("Context is required");
        return new RifeQualificationTransportFactory(context.getApplicationContext());
    }

    private RifeQualificationTransportFactory(Context context) {
        this.context = context;
    }

    @Override public boolean nativeSoftwareGeometry() { return true; }

    // Android swap interval zero enables async BufferQueue replacement. RIFE
    // needs each announced endpoint, not merely the newest queued image.
    @Override public int endpointSwapInterval() { return 1; }

    @Override public ExternalFrameGenerationTransport open(
            Surface outputSurface, Handler owner,
            int suggestedWidth, int suggestedHeight) throws Exception {
        if (suggestedWidth < 1 || suggestedHeight < 1)
            throw new IllegalArgumentException("endpoint geometry is invalid");
        return RifePresentationTransport.open(context, outputSurface, owner,
                suggestedWidth, suggestedHeight,
                suggestedWidth, suggestedHeight);
    }
}
