package com.thorium.preview.game;

/** Lazy, qualification-only bridge to EXT_disjoint_timer_query. */
final class DenseGpuTimer implements AutoCloseable {
    static final int ENDPOINT_COPY = 1;
    static final int PYRAMID = 2;
    static final int FORWARD_SOLVE = 3;
    static final int REVERSE_SOLVE = 4;
    static final int VALIDATION = 5;
    static final int VISIBLE_WARP = 6;
    static final int RESULT_FIELDS = 12;
    static final int SIGNATURE_RESULT_FIELDS = 8;
    // Context + core/EXT query API + functions + objects + empty-draw
    // execution self-test. The Java owner adds its independent RGBA8 bit.
    static final int SIGNATURE_CAP_READY = 31;
    static final int STATUS_OK = 0;
    // Mirrors of the native poll's row status codes that name measurement
    // anomalies rather than GL pipeline failures; the generator classifies
    // exactly these as transient. The remaining codes stay unnamed here so
    // they cannot be classified without reading the native contract.
    static final int STATUS_DISJOINT = 2;
    static final int STATUS_ELAPSED_OVERFLOW = 5;

    static long nanosecondsToMicroseconds(long nanoseconds) {
        if (nanoseconds <= 0L) return 0L;
        return nanoseconds / 1000L + (nanoseconds % 1000L == 0L ? 0L : 1L);
    }

    private static boolean libraryLoaded;
    private long handle;

    static synchronized DenseGpuTimer create() {
        if (!libraryLoaded) {
            System.loadLibrary("lucent_framegen_timer");
            libraryLoaded = true;
        }
        long value = nativeCreate();
        if (value == 0L) throw new IllegalStateException("EXT_disjoint_timer_query unavailable");
        return new DenseGpuTimer(value);
    }

    private DenseGpuTimer(long handle) { this.handle = handle; }

    boolean begin(int stage, long sequence) {
        return handle != 0L && nativeBegin(handle, stage, sequence);
    }

    void end() {
        if (handle == 0L || !nativeEnd(handle))
            throw new IllegalStateException("GPU timer query end failed");
    }

    /** Rows are status, slot, query, stage, sequence, current-pair,
     * current-warp, available, raw elapsed-ns, queue-age, context-ok,
     * disjoint. Raw nanoseconds are never truncated in native code. */
    long[] poll(long currentPairSequence, long currentWarpSequence) {
        return handle == 0L ? new long[0] :
                nativePoll(handle, currentPairSequence, currentWarpSequence);
    }

    int takeDisjointCount() {
        return handle == 0L ? 0 : nativeTakeDisjointCount(handle);
    }

    int pendingCount() { return handle == 0L ? 0 : nativePendingCount(handle); }

    boolean signatureSupported() {
        return handle != 0L && nativeSignatureSupported(handle);
    }

    int signatureCapability() {
        return handle == 0L ? 0 : nativeSignatureCapability(handle);
    }

    boolean beginSignature(long sequence) {
        return handle != 0L && nativeBeginSignature(handle, sequence);
    }

    void endSignature() {
        if (handle == 0L || !nativeEndSignature(handle))
            throw new IllegalStateException("signature query end failed");
    }

    long[] pollSignature(long currentSequence) {
        return handle == 0L ? new long[0] :
                nativePollSignature(handle, currentSequence);
    }

    int pendingSignatures() {
        return handle == 0L ? 0 : nativePendingSignatures(handle);
    }

    int configureProofAtlas(int width, int height, int byteCount, int ringSize) {
        return handle == 0L ? 0 :
                nativeConfigureProofAtlas(handle, width, height, byteCount, ringSize);
    }

    int proofAtlasCapability() {
        return handle == 0L ? 0 : nativeProofAtlasCapability(handle);
    }

    int enqueueProofAtlas(long proofSequence, long presentOrdinal) {
        return handle == 0L ? -1 :
                nativeEnqueueProofAtlas(handle, proofSequence, presentOrdinal);
    }

    long[] pollProofAtlas(long currentPresentOrdinal,
                          java.nio.ByteBuffer destination) {
        return handle == 0L ? new long[0] :
                nativePollProofAtlas(handle, currentPresentOrdinal, destination);
    }

    int pendingProofAtlases() {
        return handle == 0L ? 0 : nativePendingProofAtlases(handle);
    }

    void discardPending() {
        if (handle != 0L) nativeDiscard(handle);
    }

    @Override public void close() {
        long value = handle;
        handle = 0L;
        if (value != 0L) nativeDestroy(value);
    }

    private static native long nativeCreate();
    private static native boolean nativeBegin(long handle, int stage, long sequence);
    private static native boolean nativeEnd(long handle);
    private static native long[] nativePoll(long handle, long currentPairSequence,
            long currentWarpSequence);
    private static native int nativeTakeDisjointCount(long handle);
    private static native int nativePendingCount(long handle);
    private static native boolean nativeSignatureSupported(long handle);
    private static native int nativeSignatureCapability(long handle);
    private static native boolean nativeBeginSignature(long handle, long sequence);
    private static native boolean nativeEndSignature(long handle);
    private static native long[] nativePollSignature(long handle, long currentSequence);
    private static native int nativePendingSignatures(long handle);
    private static native int nativeConfigureProofAtlas(long handle, int width,
            int height, int byteCount, int ringSize);
    private static native int nativeProofAtlasCapability(long handle);
    private static native int nativeEnqueueProofAtlas(long handle,
            long proofSequence, long presentOrdinal);
    private static native long[] nativePollProofAtlas(long handle,
            long currentPresentOrdinal, java.nio.ByteBuffer destination);
    private static native int nativePendingProofAtlases(long handle);
    private static native void nativeDiscard(long handle);
    private static native void nativeDestroy(long handle);
}
