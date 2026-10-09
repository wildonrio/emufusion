package com.thorium.lucent.netplay;

/**
 * The binary message one peer sends over its DataChannel to report one of
 * ITS OWN local {@code lucent_native_control} value changes, for the Phase 3
 * native-adapter engine family (Eden/Cemu/aPS3e). See
 * {@link NetplayInputMessage} for the libretro/PPSSPP-family equivalent and
 * why this is a separate, differently shaped message rather than a shared
 * one: a native-adapter control is a float against a control ordinal, not a
 * boolean bit in a fixed per-port mask, so packing it into the same 3-byte
 * bitmask frame would lose analog stick/touch precision.
 *
 * <p>Fixed 6-byte frame. Byte 0: message kind (only
 * {@link #KIND_NATIVE_CONTROL} exists today). Byte 1: the
 * {@code lucent_native_control} ordinal (0-21 today). Bytes 2-5: the float
 * value, IEEE-754 big-endian. There is deliberately no controller-index
 * field: like {@link NetplayInputMessage}'s port, which controller_index a
 * message's sender should land on is assigned out-of-band per peer (see
 * {@code NetplayPortAssignment}/{@code NativeAdapterInputRelay}'s own
 * peerControllerIndices map) rather than trusted from the wire, exactly the
 * same reasoning as the libretro-family relay already applies to ports.
 *
 * <p>Same "apply on arrival, not lockstep" model as
 * {@link NetplayInputMessage} -- see its doc comment for the full reasoning,
 * which applies here unchanged.
 */
public final class NativeControlMessage {
    public static final byte KIND_NATIVE_CONTROL = 0x02;

    private NativeControlMessage() {}

    public static byte[] encode(int control, float value) {
        int bits = Float.floatToIntBits(value);
        return new byte[]{
                KIND_NATIVE_CONTROL,
                (byte) (control & 0xFF),
                (byte) ((bits >>> 24) & 0xFF),
                (byte) ((bits >>> 16) & 0xFF),
                (byte) ((bits >>> 8) & 0xFF),
                (byte) (bits & 0xFF),
        };
    }

    /** Decoded (control, value), or null if {@code data} isn't a recognized
     * native-control message. */
    public static Decoded decode(byte[] data) {
        if (data == null || data.length < 6 || data[0] != KIND_NATIVE_CONTROL) return null;
        int control = data[1] & 0xFF;
        int bits = ((data[2] & 0xFF) << 24) | ((data[3] & 0xFF) << 16) |
                ((data[4] & 0xFF) << 8) | (data[5] & 0xFF);
        return new Decoded(control, Float.intBitsToFloat(bits));
    }

    public static final class Decoded {
        public final int control;
        public final float value;

        Decoded(int control, float value) {
            this.control = control;
            this.value = value;
        }
    }
}
