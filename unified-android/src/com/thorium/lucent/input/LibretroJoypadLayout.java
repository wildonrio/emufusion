package com.thorium.lucent.input;

import java.util.Map;

/**
 * Maps EmuFusion's physical geometry to the libretro RetroPad IDs a system's core
 * expects.
 *
 * <p>The tables live in {@link SystemControlLayouts}, which holds the console's
 * own name for a control and the RetroPad ID that reaches it in one entry, so
 * what a control is called and what it presses can never diverge. A system with
 * no curated table falls back to the generic RetroPad below.
 */
public final class LibretroJoypadLayout {
    private LibretroJoypadLayout() {}

    /** The RetroPad ID this system's core reads for a Thor control, or -1. */
    public static int idFor(String systemId, CanonicalControl control) {
        if (control == null) return -1;
        String system = normalize(systemId);
        Map<CanonicalControl, SystemControlLayouts.Binding> table =
                SystemControlLayouts.bindings(system);
        if (!table.isEmpty()) {
            SystemControlLayouts.Binding binding = table.get(control);
            return binding == null ? -1 : binding.retroId;
        }
        return genericRetroPad(system, control);
    }

    /**
     * The fallback for a system with no curated table: the RetroPad's own
     * geometry, which is the SNES pad's. The Thor's bottom button is the
     * console's bottom button (RetroPad B), its right is the console's right
     * (RetroPad A), and so on around the diamond.
     *
     * <p>The left stick doubles as the D-pad unless the core reads
     * {@code RETRO_DEVICE_ANALOG} index 0 as a control of its own, and the
     * right stick is never a digital button.
     */
    private static int genericRetroPad(String system, CanonicalControl control) {
        boolean analogStick = hasAnalogStick(system);
        switch (control) {
            case LEFT_Y_NEGATIVE: return analogStick ? -1 : 4;
            case LEFT_Y_POSITIVE: return analogStick ? -1 : 5;
            case LEFT_X_NEGATIVE: return analogStick ? -1 : 6;
            case LEFT_X_POSITIVE: return analogStick ? -1 : 7;
            case DPAD_UP: return 4;
            case DPAD_DOWN: return 5;
            case DPAD_LEFT: return 6;
            case DPAD_RIGHT: return 7;
            case RIGHT_X_NEGATIVE: case RIGHT_X_POSITIVE:
            case RIGHT_Y_NEGATIVE: case RIGHT_Y_POSITIVE:
                return -1;
            case SOUTH: return 0;
            case EAST: return 8;
            case WEST: return 1;
            case NORTH: return 9;
            case SELECT: return 2;
            case START: return 3;
            case L1: return 10;
            case R1: return 11;
            case L2: return 12;
            case R2: return 13;
            case L3: return 14;
            case R3: return 15;
            default: return -1;
        }
    }

    /**
     * RETRO_DEVICE type EmuFusion wants on port 0 for this system. Everything runs
     * as a plain RetroPad except Wii, which needs Dolphin's Wiimote+Nunchuk
     * device so extension-only titles (Super Mario Galaxy 2) accept input at
     * all. Selecting it requires {@code retro_set_controller_port_device}; the
     * in-process host currently hard-codes RETRO_DEVICE_JOYPAD.
     */
    public static int portDeviceFor(String systemId) {
        return isWii(normalize(systemId)) ? WIIMOTE_NUNCHUK : RETRO_DEVICE_JOYPAD;
    }

    public static final int RETRO_DEVICE_JOYPAD = 1;
    /** Dolphin's {@code RETRO_DEVICE_WIIMOTE_NC}: {@code (3 << 8) | JOYPAD}. */
    public static final int WIIMOTE_NUNCHUK = (3 << 8) | RETRO_DEVICE_JOYPAD;

    /**
     * True when the core reads {@code RETRO_DEVICE_ANALOG} index 0 as its own
     * control, so the left stick must not also press the digital D-pad.
     *
     * <p>N64, GameCube, Wii, Dreamcast, PSP, PS2 and 3DS games read the stick
     * and the D-pad as different controls. ColecoVision and Apple II are on the
     * list for a stranger reason: gearcoleco reads that axis pair as keypad 9
     * and keypad 0, and AppleWin reads it as the two paddles, so a stick that
     * also meant "D-pad" would type on the keypad while it steered.
     */
    public static boolean hasAnalogStick(String systemId) {
        switch (normalize(systemId)) {
            case "n64": case "nintendo64":
            case "gc": case "gamecube": case "nintendogamecube":
            case "wii": case "nintendowii":
            case "dreamcast": case "naomi": case "atomiswave":
            case "psp":
            case "ps2":
            case "3ds":
            case "colecovision":
            case "apple2":
                return true;
            default:
                return false;
        }
    }

    private static boolean isWii(String system) {
        return "wii".equals(system) || "nintendowii".equals(system);
    }

    private static String normalize(String value) {
        return value == null ? "" : value.toLowerCase().replaceAll("[^a-z0-9]", "");
    }
}
