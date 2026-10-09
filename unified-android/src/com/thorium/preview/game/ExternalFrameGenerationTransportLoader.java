package com.thorium.preview.game;

import android.content.Context;

import java.lang.reflect.Method;

/** Loads an APK-conditional transport without making it a product dependency. */
final class ExternalFrameGenerationTransportLoader {
    private ExternalFrameGenerationTransportLoader() {}

    static ExternalFrameGenerationTransport.Factory lsfgQualification(
            Context context) {
        return qualificationFactory(context,
                "com.thorium.preview.game.LsfgQualificationTransportFactory");
    }

    static ExternalFrameGenerationTransport.Factory rifeQualification(
            Context context) {
        return qualificationFactory(context,
                "com.thorium.preview.game.RifeQualificationTransportFactory");
    }

    private static ExternalFrameGenerationTransport.Factory qualificationFactory(
            Context context, String className) {
        if (context == null) return null;
        try {
            Class<?> type = Class.forName(className);
            Method create = type.getMethod("create", Context.class);
            Object value = create.invoke(null, context.getApplicationContext());
            return value instanceof ExternalFrameGenerationTransport.Factory ?
                    (ExternalFrameGenerationTransport.Factory) value : null;
        } catch (Throwable absentOrRejected) {
            return null;
        }
    }
}
