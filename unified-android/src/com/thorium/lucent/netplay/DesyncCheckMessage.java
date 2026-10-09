package com.thorium.lucent.netplay;

/**
 * The periodic "does your core agree with mine" heartbeat described in the
 * design plan's key risks section: "every ~60 frames, exchange a fast
 * checksum (CRC32/xxHash) of each side's serialize() output; on mismatch,
 * end the session with a clear message rather than silently drifting."
 *
 * <p>This alpha's netplay is deliberately "apply input on arrival," not
 * frame-buffered lockstep (see {@link NetplayInputMessage}'s doc comment for
 * why) -- so there is no shared, authoritative frame number both sides agree
 * on to check "one exact frame" against. This message instead ticks on each
 * sender's own fixed wall-clock interval ({@link NetplayInputRelay}'s
 * DESYNC_CHECK_INTERVAL_MS) and tags each tick with a locally-incrementing
 * {@code checkIndex}. Two peers' index-N ticks land at roughly the same
 * point in each side's own timeline (both start counting from match start
 * and tick at the same real-time interval), not at a guaranteed-identical
 * frame -- a real, honest imprecision worth remembering: this catches
 * sustained, real divergence (the two cores producing different game state)
 * far more reliably than it catches a one-frame-wide transient blip, which
 * is exactly the tradeoff of not having built full lockstep for this alpha.
 *
 * <p>Fixed 9-byte frame. Byte 0: message kind
 * ({@link #KIND_DESYNC_CHECK}). Bytes 1-4: checkIndex (big-endian int32).
 * Bytes 5-8: a CRC32 checksum of the sender's serialize() output, truncated
 * to the low 32 bits (CRC32 is already a 32-bit value; this is just making
 * that explicit) and packed big-endian.
 */
public final class DesyncCheckMessage {
    public static final byte KIND_DESYNC_CHECK = 0x03;

    private DesyncCheckMessage() {}

    public static byte[] encode(int checkIndex, int checksum) {
        return new byte[]{
                KIND_DESYNC_CHECK,
                (byte) ((checkIndex >>> 24) & 0xFF),
                (byte) ((checkIndex >>> 16) & 0xFF),
                (byte) ((checkIndex >>> 8) & 0xFF),
                (byte) (checkIndex & 0xFF),
                (byte) ((checksum >>> 24) & 0xFF),
                (byte) ((checksum >>> 16) & 0xFF),
                (byte) ((checksum >>> 8) & 0xFF),
                (byte) (checksum & 0xFF),
        };
    }

    /** Decoded (checkIndex, checksum), or null if {@code data} isn't a recognized desync-check message. */
    public static Decoded decode(byte[] data) {
        if (data == null || data.length < 9 || data[0] != KIND_DESYNC_CHECK) return null;
        int checkIndex = ((data[1] & 0xFF) << 24) | ((data[2] & 0xFF) << 16) |
                ((data[3] & 0xFF) << 8) | (data[4] & 0xFF);
        int checksum = ((data[5] & 0xFF) << 24) | ((data[6] & 0xFF) << 16) |
                ((data[7] & 0xFF) << 8) | (data[8] & 0xFF);
        return new Decoded(checkIndex, checksum);
    }

    public static final class Decoded {
        public final int checkIndex;
        public final int checksum;

        Decoded(int checkIndex, int checksum) {
            this.checkIndex = checkIndex;
            this.checksum = checksum;
        }
    }
}
