package com.thorium.preview.game;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Owner-thread completion, not cancellation/request/registry removal, retires a Surface. */
final class SurfaceRetirement {
    private final CountDownLatch completed = new CountDownLatch(1);
    private volatile Throwable failure;

    void complete(Throwable cleanupFailure) {
        failure = cleanupFailure;
        completed.countDown();
    }

    void await(long timeoutMs, Throwable originalFailure) {
        try {
            if (!completed.await(timeoutMs, TimeUnit.MILLISECONDS))
                throw new SurfaceOwnershipException(
                        "Frame generator did not release its display within the shutdown bound",
                        originalFailure);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            if (originalFailure != null) originalFailure.addSuppressed(interrupted);
            throw new SurfaceOwnershipException(
                    "Display retirement was interrupted", originalFailure == null ?
                            interrupted : originalFailure);
        }
        if (failure != null) {
            if (originalFailure != null && originalFailure != failure)
                originalFailure.addSuppressed(failure);
            throw new SurfaceOwnershipException("Display retirement failed",
                    originalFailure == null ? failure : originalFailure);
        }
    }
}
