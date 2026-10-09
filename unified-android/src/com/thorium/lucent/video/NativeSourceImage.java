package com.thorium.lucent.video;

import java.nio.ByteBuffer;

/**
 * Fixed-size v1 queued-image provenance; NOT guest-clock, pixel or scanout proof.
 *
 * <p>The Android arm64 ABI is little endian. Reads use absolute byte offsets,
 * without changing the caller's position/order or allocating views. Construct
 * slots at setup, then reuse them only after their retained image is released.
 * Decode seals a private value copy: an occupied slot cannot be overwritten.
 * All methods are single-owner; the caller must not concurrently write the JNI
 * buffer, release a slot, or read a slot on another thread.</p>
 */
public final class NativeSourceImage {
    public static final int VERSION = 1;
    public static final int IMAGE_BYTES = 808;
    public static final int BINDING_BYTES = 64;
    public static final int LAYER_BYTES = 88;
    public static final int MAX_LAYERS = 8;
    private static final int LAYERS_OFFSET = 104;
    private static final int VK_SUBOPTIMAL = 1000001003;
    private static final int ACQUIRED = 1, HELD = 2, OVERLAY = 4, AUTO_TIMESTAMP = 8;

    public enum Decode {
        ACCEPTED, PENDING, BUSY, NOT_FOUND, AMBIGUOUS, REJECTED, UNSUPPORTED,
        CLOSED, BAD_ARGUMENT, STALE_EPOCH, MALFORMED, WRONG_IMAGE,
        INCOMPLETE_COMPOSITION, BINDING_NOT_READY, SLOT_IN_USE
    }

    public enum Pair {
        ADJACENT_QUEUED_IMAGES, HELD_QUEUED_IMAGE, MISSING_IMAGE,
        // Retention-ledger guards precede the value-only native comparison.
        MISSING_PTS, PROVIDER_CHANGED, STALE_RETENTION,
        CLASSIFIED_TIMESTAMP_MISMATCH, EXPORTED_TIMESTAMP_MISMATCH,
        UNSUPPORTED_LAYERS, OVERLAY_LAYER, EPOCH_CHANGED, QUEUE_CHANGED,
        GEOMETRY_CHANGED, SWAP_INTERVAL_CHANGED, UNSUPPORTED_SWAP_MODE,
        NONMONOTONIC_OBSERVATION, QUEUE_FRAME_GAP, QUEUE_FRAME_REVERSED,
        INCONSISTENT_SAME_IMAGE, RIGHT_IMAGE_NOT_NEW
    }

    public enum Transfer {
        COPIED, MOVED, BAD_ARGUMENT, DESTINATION_OCCUPIED, SOURCE_EMPTY
    }

    public static final class Binding {
        private final byte[] value = new byte[BINDING_BYTES];
        private boolean sealed;
        public boolean isSealed() { return sealed; }
        public void release() { sealed = false; }
        public long sessionEpoch() { return sealed ? i64(value, 8) : 0; }
        public long surfaceEpoch() { return sealed ? i64(value, 16) : 0; }
        public long swapchainEpoch() { return sealed ? i64(value, 24) : 0; }
    }

    public static final class Slot {
        private final byte[] value = new byte[IMAGE_BYTES];
        private boolean sealed;
        public boolean isSealed() { return sealed; }
        /** Invalidates the snapshot; call only after releasing its retained image. */
        public void release() { clear(); }
        /** Metadata only: the caller must first retire or transfer its image ownership. */
        public void clear() { sealed = false; }
        /** Copies into an empty destination without changing the source's ownership. */
        public Transfer copyFrom(Slot source) {
            if (source == null || source == this) return Transfer.BAD_ARGUMENT;
            if (sealed) return Transfer.DESTINATION_OCCUPIED;
            if (!source.sealed) return Transfer.SOURCE_EMPTY;
            System.arraycopy(source.value, 0, value, 0, IMAGE_BYTES);
            sealed = true;
            return Transfer.COPIED;
        }
        /** Establish destination image ownership first; retire the source image only on success. */
        public Transfer moveFrom(Slot source) {
            Transfer result = copyFrom(source);
            if (result != Transfer.COPIED) return result;
            source.clear();
            return Transfer.MOVED;
        }
        public long sessionEpoch() { return sealed ? i64(value, 40) : 0; }
        public long surfaceEpoch() { return sealed ? i64(value, 48) : 0; }
        public long swapchainEpoch() { return sealed ? i64(value, 56) : 0; }
        public long displayId() { return sealed ? i64(value, 64) : 0; }
        public long compositionOrdinal() { return sealed ? i64(value, 72) : 0; }
        public long observedMonotonicNs() { return sealed ? i64(value, 80) : 0; }
        public long submissionOrdinal() { return sealed ? i64(value, 16) : 0; }
        public long bufferTimestampNs() { return sealed ? i64(value, 24) : 0; }
        public int layerCount() { return sealed ? i32(value, 88) : 0; }
        public long queueEpoch(int layer) { return layer64(layer, 0); }
        public long queueFrameNumber(int layer) { return layer64(layer, 8); }
        /** Raw guest-requested value; its clock domain is unknown, including negative values. */
        public long guestRequestedTimestampNs(int layer) { return layer64(layer, 16); }
        public int layerFlags(int layer) {
            return hasLayer(layer) ? i32(value, LAYERS_OFFSET + layer * LAYER_BYTES + 40) : 0;
        }
        private boolean hasLayer(int layer) { return sealed && layer >= 0 && layer < layerCount(); }
        private long layer64(int layer, int offset) {
            return hasLayer(layer) ? i64(value, LAYERS_OFFSET + layer * LAYER_BYTES + offset) : 0;
        }
    }

    private NativeSourceImage() {}

    /** The return code alone never supplies data; accepted bindings must validate their bytes. */
    public static Decode decodeBinding(int nativeResult, ByteBuffer input, Binding out) {
        if (out == null) return Decode.BAD_ARGUMENT;
        if (out.sealed) return Decode.SLOT_IN_USE;
        Decode state = result(nativeResult);
        if (state != Decode.ACCEPTED) return state;
        if (!copy(input, out.value)) return Decode.BAD_ARGUMENT;
        byte[] b = out.value;
        if (i32(b, 0) != VERSION || i32(b, 4) != BINDING_BYTES ||
                i64(b, 8) <= 0 || i64(b, 16) <= 0 || i64(b, 24) < 0)
            return Decode.MALFORMED;
        if (i64(b, 24) == 0) return Decode.BINDING_NOT_READY;
        out.sealed = true;
        return Decode.ACCEPTED;
    }

    /**
     * Validate the exact consumed-buffer query key, not a neighboring timestamp.
     * Pending/error rows never seal a usable endpoint. Retry pending against the
     * SAME retained image/key; do not relabel a later updateTexImage result.
     */
    public static Decode decode(int nativeResult, ByteBuffer input, long expectedSession,
                                long expectedSurface, long exactBufferTimestampNs, Slot out) {
        if (out == null) return Decode.BAD_ARGUMENT;
        if (out.sealed) return Decode.SLOT_IN_USE;
        if (expectedSession <= 0 || expectedSurface <= 0 || exactBufferTimestampNs <= 0)
            return Decode.BAD_ARGUMENT;
        Decode state = result(nativeResult);
        if (state != Decode.ACCEPTED && state != Decode.PENDING &&
                state != Decode.AMBIGUOUS && state != Decode.REJECTED) return state;
        if (!copy(input, out.value)) return Decode.BAD_ARGUMENT;
        byte[] b = out.value;
        if (i32(b, 0) != VERSION || i32(b, 4) != IMAGE_BYTES || i32(b, 8) != nativeResult)
            return Decode.MALFORMED;
        if (i64(b, 40) != expectedSession || i64(b, 48) != expectedSurface ||
                i64(b, 24) != exactBufferTimestampNs) return Decode.WRONG_IMAGE;
        if (i64(b, 56) <= 0 || i64(b, 64) < 0 || i64(b, 16) <= 0 ||
                i64(b, 72) <= 0 || i64(b, 80) <= 0 || i64(b, 80) > i64(b, 24) ||
                i32(b, 100) != 0) return Decode.MALFORMED;
        int count = i32(b, 88), retained = i32(b, 96), flags = i32(b, 92);
        if (count < 0 || retained < 0 || retained > MAX_LAYERS || (flags & ~7) != 0)
            return Decode.MALFORMED;
        if (flags != 1 || count == 0 || count > MAX_LAYERS || retained != count)
            return Decode.INCOMPLETE_COMPOSITION;
        for (int layer = 0; layer < count; ++layer) {
            int base = LAYERS_OFFSET + layer * LAYER_BYTES;
            int layerFlags = i32(b, base + 40), raw = i32(b, base + 32);
            int normalized = i32(b, base + 36);
            int acquiredOrHeld = layerFlags & (ACQUIRED | HELD);
            if (i64(b, base) <= 0 || i64(b, base + 8) <= 0 ||
                    i32(b, base + 24) < 0 || i32(b, base + 28) < 0 ||
                    (layerFlags & ~(ACQUIRED | HELD | OVERLAY | AUTO_TIMESTAMP)) != 0 ||
                    (acquiredOrHeld != ACQUIRED && acquiredOrHeld != HELD) ||
                    normalized != (raw >= 1 && raw <= 4 ? raw : 1) ||
                    i32(b, base + 44) <= 0 || i32(b, base + 48) <= 0 ||
                    i32(b, base + 52) < i32(b, base + 44)) return Decode.MALFORMED;
            for (int previous = 0; previous < layer; ++previous) {
                int prior = LAYERS_OFFSET + previous * LAYER_BYTES;
                if (i64(b, base) == i64(b, prior)) return Decode.MALFORMED;
            }
        }
        int vkResult = i32(b, 12);
        if (state == Decode.ACCEPTED && vkResult != 0 && vkResult != VK_SUBOPTIMAL)
            return Decode.MALFORMED;
        if (state == Decode.REJECTED && (vkResult == 0 || vkResult == VK_SUBOPTIMAL))
            return Decode.MALFORMED;
        if (state == Decode.PENDING && vkResult != 0) return Decode.MALFORMED;
        if (state != Decode.ACCEPTED) return state;
        out.sealed = true;
        return Decode.ACCEPTED;
    }

    /** Pure compatibility test; never mutates snapshots or grants interpolation authority. */
    public static Pair compare(Slot left, Slot right) {
        if (left == null || right == null || !left.sealed || !right.sealed)
            return Pair.MISSING_IMAGE;
        if (left.layerCount() != 1 || right.layerCount() != 1) return Pair.UNSUPPORTED_LAYERS;
        byte[] a = left.value, b = right.value;
        if (((i32(a, 144) | i32(b, 144)) & OVERLAY) != 0) return Pair.OVERLAY_LAYER;
        if (left.sessionEpoch() != right.sessionEpoch() || left.surfaceEpoch() != right.surfaceEpoch() ||
                left.swapchainEpoch() != right.swapchainEpoch() || left.displayId() != right.displayId())
            return Pair.EPOCH_CHANGED;
        if (left.queueEpoch(0) != right.queueEpoch(0) || i32(a, 128) != i32(b, 128))
            return Pair.QUEUE_CHANGED;
        // Geometry is the complete value tuple, never a hash. A reusable buffer
        // slot is deliberately excluded: adjacent real images usually alternate slots.
        for (int offset = 148; offset < 192; offset += 4) {
            if (i32(a, offset) != i32(b, offset)) return Pair.GEOMETRY_CHANGED;
        }
        if (i32(a, 136) != i32(b, 136) || i32(a, 140) != i32(b, 140))
            return Pair.SWAP_INTERVAL_CHANGED;
        // Eden's extended raw intervals modify speed semantics. That separate
        // guest-clock contract has not been qualified for this initial subset.
        if (i32(a, 136) < 1 || i32(a, 136) > 4) return Pair.UNSUPPORTED_SWAP_MODE;
        if (right.bufferTimestampNs() <= left.bufferTimestampNs() ||
                right.submissionOrdinal() <= left.submissionOrdinal() ||
                right.compositionOrdinal() < left.compositionOrdinal() ||
                right.observedMonotonicNs() < left.observedMonotonicNs())
            return Pair.NONMONOTONIC_OBSERVATION;
        long previous = left.queueFrameNumber(0), next = right.queueFrameNumber(0);
        if (next == previous) {
            if (left.guestRequestedTimestampNs(0) != right.guestRequestedTimestampNs(0) ||
                    i32(a, 132) != i32(b, 132) || ((i32(a, 144) ^ i32(b, 144)) & AUTO_TIMESTAMP) != 0)
                return Pair.INCONSISTENT_SAME_IMAGE;
            return Pair.HELD_QUEUED_IMAGE; // Includes a retry of the exact same Frame.
        }
        if (next < previous) return Pair.QUEUE_FRAME_REVERSED;
        if (previous == Long.MAX_VALUE || next - previous != 1) return Pair.QUEUE_FRAME_GAP;
        if (right.compositionOrdinal() == left.compositionOrdinal() ||
                right.observedMonotonicNs() == left.observedMonotonicNs())
            return Pair.NONMONOTONIC_OBSERVATION;
        if ((i32(b, 144) & ACQUIRED) == 0) return Pair.RIGHT_IMAGE_NOT_NEW;
        return Pair.ADJACENT_QUEUED_IMAGES;
    }

    private static Decode result(int value) {
        switch (value) {
            case 1: return Decode.ACCEPTED;
            case 2: return Decode.PENDING;
            case 3: return Decode.BUSY;
            case 4: return Decode.NOT_FOUND;
            case 5: return Decode.AMBIGUOUS;
            case 6: return Decode.REJECTED;
            case 7: return Decode.UNSUPPORTED;
            case 8: return Decode.CLOSED;
            case 9: return Decode.BAD_ARGUMENT;
            case 10: return Decode.STALE_EPOCH;
            default: return Decode.MALFORMED;
        }
    }

    private static boolean copy(ByteBuffer from, byte[] to) {
        if (from == null || from.limit() < to.length) return false;
        for (int index = 0; index < to.length; ++index) to[index] = from.get(index);
        return true;
    }
    private static int i32(byte[] bytes, int offset) {
        return (bytes[offset] & 255) | ((bytes[offset + 1] & 255) << 8) |
                ((bytes[offset + 2] & 255) << 16) | ((bytes[offset + 3] & 255) << 24);
    }
    private static long i64(byte[] bytes, int offset) {
        return (i32(bytes, offset) & 0xffffffffL) | ((long) i32(bytes, offset + 4) << 32);
    }
}
