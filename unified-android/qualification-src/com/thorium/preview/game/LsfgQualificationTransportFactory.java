package com.thorium.preview.game;

import android.content.Context;
import android.os.Handler;
import android.view.Surface;

/** APK-conditional constructor for fixed-midpoint LSFG qualification only. */
public final class LsfgQualificationTransportFactory
        implements ExternalFrameGenerationTransport.Factory {
    private static final int ENDPOINT_WIDTH = 320;
    private static final int ENDPOINT_HEIGHT = 180;

    private final Context context;

    public static ExternalFrameGenerationTransport.Factory create(Context context) {
        if (context == null) throw new IllegalArgumentException("Context is required");
        return new LsfgQualificationTransportFactory(context.getApplicationContext());
    }

    private LsfgQualificationTransportFactory(Context context) {
        this.context = context;
    }

    @Override public ExternalFrameGenerationTransport open(
            Surface outputSurface, Handler owner,
            int suggestedWidth, int suggestedHeight) throws Exception {
        if (suggestedWidth < 1 || suggestedHeight < 1)
            throw new IllegalArgumentException("endpoint geometry is invalid");
        // Endpoint geometry follows the game surface scaled by the shell
        // global emufusion_lsfg_endpoint_scale (default 0.5, so 1920x1080
        // gameplay generates at 960x540); the fixed 320x180 qualification
        // geometry remains the floor.  Even dimensions keep RGBA8 AHB import
        // and LSFG's internal downscale exact.
        float scale = 0.5f;
        try {
            String stored = android.provider.Settings.Global.getString(
                    context.getContentResolver(), "emufusion_lsfg_endpoint_scale");
            if (stored != null) scale = Float.parseFloat(stored.trim());
        } catch (RuntimeException ignored) {
            scale = 0.5f;
        }
        scale = Math.max(0.1f, Math.min(1.0f, scale));
        int width = Math.max(ENDPOINT_WIDTH,
                Math.min(suggestedWidth, (Math.round(suggestedWidth * scale) / 2) * 2));
        int height = Math.max(ENDPOINT_HEIGHT,
                Math.min(suggestedHeight, (Math.round(suggestedHeight * scale) / 2) * 2));
        android.util.Log.i("LucentLsfg", "LSFG endpoint geometry " + width + "x" + height +
                " (suggested " + suggestedWidth + "x" + suggestedHeight +
                " scale=" + scale + ")");
        return LsfgPresentationTransport.open(context, outputSurface, owner,
                width, height);
    }
}
