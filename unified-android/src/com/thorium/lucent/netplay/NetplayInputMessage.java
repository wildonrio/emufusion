package com.thorium.lucent.netplay;

/**
 * The binary message one peer sends over its DataChannel to report its
 * current local joypad button state. Deliberately not JSON: this is the
 * highest-frequency traffic in the whole feature (sent on every button
 * transition, potentially dozens of times a second during fast gameplay),
 * so it is a fixed 3-byte binary frame instead.
 *
 * <p>Byte 0: message kind (only {@link #KIND_JOYPAD_BUTTONS} exists today).
 * Bytes 1-2: a 16-bit bitmask, bit N set means retro joypad ID N is
 * currently held. 16 bits covers every standard RETRO_DEVICE_ID_JOYPAD_*
 * button (0-15 across the classic and newer analog IDs).
 *
 * <p><b>Deliberately not lockstep-synchronized</b>: this carries "the
 * sender's current button state," not "the sender's input for frame N,"
 * and the receiver applies it immediately on arrival rather than
 * buffering it against a matching local frame number. This mirrors
 * libretro's own polling model (a core asks "what is held right now"
 * every frame; it was never an event log to begin with) and is exactly
 * the mechanism already proven live on-device via
 * NetplaySyntheticInputTester. A frame-delay-buffered lockstep model
 * (the design plan's stated ambition for hiding higher latencies) is
 * real future work, deliberately deferred: it means blocking inside
 * LibretroEngineSession/PpssppGlesEngineSession's carefully-tuned
 * AbsoluteFramePacer-driven frame loop, which is not something to bolt
 * on without its own dedicated design and a real two-network-peer test
 * rig to verify against -- neither of which this pass has.
 */
public final class NetplayInputMessage {
    public static final byte KIND_JOYPAD_BUTTONS = 0x01;

    private NetplayInputMessage() {}

    public static byte[] encodeButtonState(int bitmask) {
        return new byte[]{
                KIND_JOYPAD_BUTTONS,
                (byte) (bitmask & 0xFF),
                (byte) ((bitmask >> 8) & 0xFF),
        };
    }

    /** Returns -1 if {@code data} isn't a recognized button-state message. */
    public static int decodeButtonState(byte[] data) {
        if (data == null || data.length < 3 || data[0] != KIND_JOYPAD_BUTTONS) return -1;
        return (data[1] & 0xFF) | ((data[2] & 0xFF) << 8);
    }
}
