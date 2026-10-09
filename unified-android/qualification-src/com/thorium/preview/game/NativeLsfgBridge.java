package com.thorium.preview.game;

import android.hardware.HardwareBuffer;
import android.view.Surface;

/** JNI boundary for the conditional EmuFusion-owned LSFG Vulkan host. */
final class NativeLsfgBridge {
    static final int SUBMIT_NOT_READY = 0;
    static final int SUBMIT_ACCEPTED = 1;
    static final int PREPARE_NOT_READY = 0;
    static final int PREPARE_SUBMITTED = 1;
    static final int PREPARE_READY = 2;
    static final int PREPARE_UNSAFE = 3;
    static final int PAIR_PENDING = 0;
    static final int PAIR_READY = 1;
    static final int PAIR_UNSAFE = 2;
    static final int COMPLETION_WORDS = 24;

    static {
        System.loadLibrary("lucent_lsfg_qualification");
    }

    private NativeLsfgBridge() {}

    static native String libraryBuildId();

    /**
     * Creates the Vulkan device, bounded setup WSI, owned SurfaceControl child,
     * and three prewarmed fixed-AHB LSFG contexts. Live presentation never uses
     * WSI timing feedback. The shader directory is app-private and never an
     * APK asset.
     */
    static native long open(Surface output, String shaderDirectory,
                            int endpointWidth, int endpointHeight);

    /** JSON capability/self-test record; presence alone is never sufficient. */
    static native String capabilities(long handle);

    /** Copies the newest native AChoreographer frame-timeline batch. */
    static native int copyCompositorFrameTimelines(
            long handle, long[] vsyncIds, long[] expectedPresentationTimesNs,
            long[] deadlinesNs, long[] sourceMetadata);

    /** Imports one ImageReader carrier into the native Vulkan cache. */
    static native void prepareEndpoint(long handle, HardwareBuffer endpoint);

    /** Queues the exact generated pixels into private LSFG storage only. */
    static native int prepareGenerated(
            long handle, HardwareBuffer left, HardwareBuffer right,
            long sessionEpoch, long presentationEpoch,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs,
            long presentationTimestampNs, int width, int height, int format);

    /** Zero-polls an exact private generated identity. */
    static native int preparedGeneratedReadiness(
            long handle, HardwareBuffer left, HardwareBuffer right,
            long sessionEpoch, long presentationEpoch,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs,
            long presentationTimestampNs);

    /** Safely abandons private pixels without ever publishing them. */
    static native void discardPreparedGenerated(long handle);

    /** Privately copies/proves both real endpoints; no target or inference. */
    static native int prepareRealPair(
            long handle, HardwareBuffer left, HardwareBuffer right,
            long sessionEpoch, long presentationEpoch,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs,
            int width, int height, int format);

    /** Zero-polls that exact real-pair identity; scene cuts do not reject real pixels. */
    static native int preparedRealPairReadiness(
            long handle, HardwareBuffer left, HardwareBuffer right,
            long sessionEpoch, long presentationEpoch,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs);

    static native void discardPreparedRealPair(long handle);

    /** Includes abandoned GPU work, not merely submitted/published identities. */
    static native boolean referencesSourceImage(long handle, HardwareBuffer endpoint);

    /**
     * Activates only an exactly matching, already-proved private real pair or
     * LSFG midpoint. It never starts deadline-critical copy/inference work.
     */
    static native int enqueue(
            long handle, HardwareBuffer left, HardwareBuffer right,
            long sessionEpoch, long presentationEpoch,
            long leftSequence, long leftTimestampNs,
            long rightSequence, long rightTimestampNs,
            long presentationTimestampNs,
            long desiredPhysicalPresentTimeNs,
            long driverDesiredPresentTimeNs,
            long hardCompletionDeadlineNs,
            long compositorFrameTimelineVsyncId,
            long compositorFrameTimelineExpectedNs,
            long compositorFrameTimelineDeadlineNs,
            int width, int height, int format, long presentId);

    /**
     * Returns null while no complete physical row is available. A returned row
     * has exactly {@link #COMPLETION_WORDS} entries and is decoded fail-closed.
     */
    static native long[] poll(long handle);

    /** Invalidates pair classification without waiting for in-flight rows. */
    static native void resetTimeline(long handle, long presentationEpoch);

    /** Teardown-only: no live request may race this call. */
    static native void close(long handle);
}
