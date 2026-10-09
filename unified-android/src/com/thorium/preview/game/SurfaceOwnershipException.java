package com.thorium.preview.game;

/** Startup failed without proving that the output Surface is safe to reuse. */
public final class SurfaceOwnershipException extends IllegalStateException {
    public SurfaceOwnershipException(String message, Throwable cause) {
        super(message, cause);
    }

    public static boolean isUnsafe(Throwable failure) {
        return isUnsafe(failure, 0);
    }

    private static boolean isUnsafe(Throwable failure, int depth) {
        if (failure == null || depth > 16) return false;
        if (failure instanceof SurfaceOwnershipException) return true;
        if (isUnsafe(failure.getCause(), depth + 1)) return true;
        for (Throwable suppressed : failure.getSuppressed())
            if (isUnsafe(suppressed, depth + 1)) return true;
        return false;
    }
}
