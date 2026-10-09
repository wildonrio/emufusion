package com.thorium.preview;

import android.view.Surface;
import android.os.SystemClock;
import com.thorium.lucent.video.NativeSourceImage;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.concurrent.locks.ReentrantReadWriteLock;

/**
 * Lifecycle-safe Java boundary for EmuFusion's Phase 3 native-adapter host.
 *
 * The adapter shared library is never downloaded by this class. The caller must
 * pass an adapter under the app-private trusted directory only after
 * NativeAdapterCatalog has approved its exact source/build identity. Every call
 * for one session must run on the single render-owner thread, matching the C
 * host's serialization contract.
 */
public final class NativeAdapterHost implements Closeable {
    public static final int TIMING_BASE_CLOCK_CORRECTION = 1;
    public static final int TIMING_SUBMISSION_TIMESTAMPS = 2;
    public static final int TIMING_AUTHORITATIVE_SOURCE_TIMELINE = 4;
    public static final int SOURCE_IMAGE_BUFFER_BYTES = NativeSourceImage.IMAGE_BYTES;
    public static final int SOURCE_BINDING_BUFFER_BYTES = NativeSourceImage.BINDING_BYTES;
    public static final int SOURCE_MATCH_ACCEPTED = 1;
    public static final int SOURCE_PENDING = 2;
    public static final int SOURCE_BUSY = 3;
    public static final int SOURCE_CLOSED = 8;
    public static final int SOURCE_BAD_ARGUMENT = 9;

    /** Honest capability report copied from the adapter's describe(). */
    public static final class Capabilities {
        public final int abiVersion;
        public final boolean hasQuickResume;
        public final boolean hasPersistentSave;
        public final boolean dualScreen;
        public final int requiredFirmware;
        /** How many set_control() controller_index values 0..N-1 this engine
         * actually honors. Always >= 1. */
        public final int maxControllers;
        public final String engineId;

        Capabilities(int[] values, String engineId) {
            abiVersion = values[0];
            hasQuickResume = values[1] != 0;
            hasPersistentSave = values[2] != 0;
            dualScreen = values[3] != 0;
            requiredFirmware = values[4];
            maxControllers = values.length > 5 ? values[5] : 1;
            this.engineId = engineId == null ? "" : engineId;
        }
    }

    static {
        System.loadLibrary("lucent_native_adapter_host");
    }

    private long handle;
    private final ReentrantReadWriteLock sourceQueryLease = new ReentrantReadWriteLock();
    private volatile boolean sourceQueriesEnabled;

    public NativeAdapterHost(File adapter, File trustedDirectory) throws IOException {
        if (adapter == null || trustedDirectory == null)
            throw new IllegalArgumentException("adapter and trusted directory are required");
        File canonicalAdapter = adapter.getCanonicalFile();
        File canonicalRoot = trustedDirectory.getCanonicalFile();
        if (!isInside(canonicalAdapter, canonicalRoot))
            throw new SecurityException(
                    "adapter must be in EmuFusion's app-private trusted directory");
        handle = nativeOpen(canonicalAdapter.getPath(), canonicalRoot.getPath());
        if (handle == 0L) throw new IOException("adapter host could not be opened");
    }

    /**
     * Maps, relocates, verifies and JNI-initialises an adapter before gameplay.
     *
     * <p>The native host intentionally keeps a successfully loaded engine
     * library mapped for the process lifetime because these emulator libraries
     * own detached threads and file-scope objects that cannot be safely
     * dlclosed. Closing this temporary host therefore releases only the cheap
     * per-session wrapper. A later constructor reuses the already-relocated
     * library, moving Eden's multi-second linker cost out of the user's A-button
     * launch path.
     */
    public static long preload(File adapter, File trustedDirectory) throws IOException {
        long started = SystemClock.elapsedRealtime();
        try (NativeAdapterHost ignored = new NativeAdapterHost(adapter, trustedDirectory)) {
            ignored.describe();
        }
        return SystemClock.elapsedRealtime() - started;
    }

    public Capabilities describe() {
        return new Capabilities(nativeDescribe(handle), nativeEngineId(handle));
    }

    public void create() { nativeCreate(handle); }

    public void loadContent(File systemDirectory, File saveDirectory, String contentPath) {
        if (contentPath == null || contentPath.isEmpty())
            throw new IllegalArgumentException("content path is required");
        nativeLoadContent(handle,
                systemDirectory == null ? null : systemDirectory.getPath(),
                saveDirectory == null ? null : saveDirectory.getPath(),
                contentPath);
    }

    public void start(Surface primary, Surface lower) {
        sourceQueriesEnabled = false;
        sourceQueryLease.writeLock().lock();
        try { nativeStart(handle, primary, lower); sourceQueriesEnabled = true; }
        finally { sourceQueryLease.writeLock().unlock(); }
    }

    public void surfaceRecreated(Surface primary, Surface lower) {
        boolean wasEnabled = sourceQueriesEnabled;
        sourceQueriesEnabled = false;
        sourceQueryLease.writeLock().lock();
        try { nativeSurfaceRecreated(handle, primary, lower); sourceQueriesEnabled = wasEnabled; }
        finally { sourceQueryLease.writeLock().unlock(); }
    }

    public void runFrame() { nativeRunFrame(handle); }

    /** Owner-thread configuration before start/rebind; false means unsupported. */
    public boolean setFgPresentation(boolean enabled) {
        return nativeSetFgPresentation(handle, enabled);
    }

    /**
     * The engine's own averaged emulated-frame rate, or a negative value when
     * this adapter publishes no measurement hook.
     *
     * <p>This is not the rate EmuFusion presents at. A surface swapping at the
     * panel's refresh proves nothing about whether the guest advanced, because
     * a repeated frame still counts as a present, so a speed claim has to come
     * from the engine's own counter.
     */
    public double averageFps() { return nativeAverageFps(handle); }

    /** True when {@link #averageFps()} returned a real measurement. */
    public static boolean isMeasuredFps(double fps) { return fps >= 0.0; }

    /** The guest's frame clock in Hz, or zero when the adapter publishes none. */
    public double declaredVideoHz() { return nativeDeclaredVideoHz(handle); }

    /** Bounded correction of the declared clock; explicit zero restores normal timing. */
    public boolean setPacedVideoHz(double hz) { return nativeSetPacedVideoHz(handle, hz); }

    /** Versioned optional capabilities, zero when absent or not yet started. */
    public int timingCapabilities() { return nativeTimingCapabilities(handle); }

    /** Image-linked source timeline only; submission timestamps never authorize it. */
    public double producerTimelineHz() { return nativeProducerTimelineHz(handle); }

    /** Optional value-only C v1 record, native byte order. Allocate the direct
     * output once during setup; never share one output across concurrent calls.
     * No image authority is granted by a successful diagnostic metadata join. */
    public int sourceImageBinding(ByteBuffer output) {
        if (output == null || !output.isDirect() || output.isReadOnly() ||
                output.capacity() < SOURCE_BINDING_BUFFER_BYTES) return SOURCE_BAD_ARGUMENT;
        if (!sourceQueriesEnabled) return SOURCE_CLOSED;
        if (!sourceQueryLease.readLock().tryLock()) return SOURCE_BUSY;
        try { return !sourceQueriesEnabled || handle == 0L ? SOURCE_CLOSED : nativeSourceImageBinding(handle, output); }
        finally { sourceQueryLease.readLock().unlock(); }
    }

    /** Exact consumed SurfaceTexture timestamp only; never a nearest-row query. */
    public int querySourceImage(long sessionEpoch, long surfaceEpoch,
                                long bufferTimestampNs, ByteBuffer output) {
        if (output == null || !output.isDirect() || output.isReadOnly() ||
                output.capacity() < SOURCE_IMAGE_BUFFER_BYTES) return SOURCE_BAD_ARGUMENT;
        if (!sourceQueriesEnabled) return SOURCE_CLOSED;
        if (!sourceQueryLease.readLock().tryLock()) return SOURCE_BUSY;
        try { return !sourceQueriesEnabled || handle == 0L ? SOURCE_CLOSED : nativeQuerySourceImage(
                handle, sessionEpoch, surfaceEpoch, bufferTimestampNs, output); }
        finally { sourceQueryLease.readLock().unlock(); }
    }

    /** controllerIndex 0 is always the primary/local player. */
    public void setControl(int controllerIndex, int controlOrdinal, float value) {
        nativeSetControl(handle, controllerIndex, controlOrdinal, value);
    }

    public void pause() { nativePause(handle); }

    public void resume() { nativeResume(handle); }

    public void flushSave() { nativeFlushSave(handle); }

    /** Drains up to maxFrames interleaved stereo s16 frames; never null. */
    public short[] drainAudio(int maxFrames) {
        short[] samples = nativeDrainAudio(handle, maxFrames);
        return samples == null ? new short[0] : samples;
    }

    /** Returns null when the adapter has no Quick Resume, not a fake snapshot. */
    public byte[] serialize() { return nativeSerialize(handle); }

    public boolean unserialize(byte[] state) { return nativeUnserialize(handle, state); }

    public void stop() {
        sourceQueriesEnabled = false;
        sourceQueryLease.writeLock().lock();
        try { nativeStop(handle); }
        finally { sourceQueryLease.writeLock().unlock(); }
    }

    @Override public void close() {
        sourceQueriesEnabled = false;
        sourceQueryLease.writeLock().lock();
        try {
            if (handle != 0L) {
                nativeDestroy(handle);
                handle = 0L;
            }
        } finally { sourceQueryLease.writeLock().unlock(); }
    }

    private static boolean isInside(File candidate, File root) {
        for (File parent = candidate.getParentFile(); parent != null;
             parent = parent.getParentFile())
            if (parent.equals(root)) return true;
        return false;
    }

    private static native long nativeOpen(String adapterPath, String trustedRoot);
    private static native int[] nativeDescribe(long handle);
    private static native String nativeEngineId(long handle);
    private static native double nativeAverageFps(long handle);
    private static native double nativeDeclaredVideoHz(long handle);
    private static native boolean nativeSetPacedVideoHz(long handle, double hz);
    private static native int nativeTimingCapabilities(long handle);
    private static native double nativeProducerTimelineHz(long handle);
    private static native int nativeSourceImageBinding(long handle, ByteBuffer output);
    private static native int nativeQuerySourceImage(long handle, long sessionEpoch,
            long surfaceEpoch, long timestampNs, ByteBuffer output);
    private static native void nativeCreate(long handle);
    private static native void nativeLoadContent(long handle, String systemDirectory,
            String saveDirectory, String contentPath);
    private static native boolean nativeSetFgPresentation(long handle, boolean enabled);
    private static native void nativeStart(long handle, Surface primary, Surface lower);
    private static native void nativeSurfaceRecreated(long handle, Surface primary,
            Surface lower);
    private static native void nativeRunFrame(long handle);
    private static native void nativeSetControl(long handle, int controllerIndex, int control, float value);
    private static native void nativePause(long handle);
    private static native void nativeResume(long handle);
    private static native void nativeFlushSave(long handle);
    private static native short[] nativeDrainAudio(long handle, int maxFrames);
    private static native byte[] nativeSerialize(long handle);
    private static native boolean nativeUnserialize(long handle, byte[] state);
    private static native void nativeStop(long handle);
    private static native void nativeDestroy(long handle);
}
