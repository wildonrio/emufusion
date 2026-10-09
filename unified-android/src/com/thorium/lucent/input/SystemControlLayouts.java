package com.thorium.lucent.input;

import java.util.Arrays;
import java.util.Collections;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/**
 * The one per-system controller table.
 *
 * <p>Every entry says two things at once: which control of the <em>original</em>
 * console a physical control on the AYN Thor is, and which libretro RetroPad ID
 * reaches that control in the core EmuFusion actually ships. Keeping the name and
 * the ID in one {@link Binding} is deliberate: they used to live in two tables
 * and drifted apart, which is how the Mega Drive ended up advertising "C" on a
 * button that pressed Mega Drive B, leaving the real C on a shoulder.
 * {@code LibretroJoypadLayout} reads the ID out of these entries at runtime and
 * {@code docs/controller-mapping.md} is generated from the same entries, so
 * neither can describe a different button from the one that gets pressed.
 *
 * <p>Placement follows the original hardware:
 * <ul>
 * <li>A console whose face buttons form a <b>diamond</b> (SNES, PlayStation,
 *     Dreamcast, DS, 3DS) maps 1:1 — bottom to {@code SOUTH}, right to
 *     {@code EAST}, left to {@code WEST}, top to {@code NORTH}.</li>
 * <li>A console whose face buttons form a <b>row</b> (Mega Drive A-B-C, Saturn
 *     A-B-C, PC Engine, Neo Geo) is laid along the arc
 *     {@code WEST -> SOUTH -> EAST}, which a thumb sweeps in the original
 *     left-to-right order. A second row above it (Mega Drive / Saturn X-Y-Z)
 *     goes to {@code L1 -> NORTH -> R1}: the Thor has no second face row, and
 *     those three sit up-and-over from their partners.</li>
 * <li>A <b>two-button</b> console puts its primary action on {@code SOUTH},
 *     where the thumb rests, and the secondary on {@code EAST}.</li>
 * <li>Console switches that are not pad buttons at all — Reset, difficulty,
 *     coin — go to controls no thumb rests on, never to {@code SOUTH} or
 *     {@code EAST}.</li>
 * </ul>
 *
 * <p>{@link #consoleControls} is the console's own roster, declared separately
 * from the bindings so a test can prove no control of the original machine is
 * unreachable.
 */
public final class SystemControlLayouts {
    /** A control the core reads as an axis (RETRO_DEVICE_ANALOG), not a button. */
    public static final int ANALOG = -1;

    /** One Thor control, the console control it is, and the RetroPad ID for it. */
    public static final class Binding {
        public final String control;
        public final int retroId;

        Binding(String control, int retroId) {
            this.control = control;
            this.retroId = retroId;
        }

        public boolean analog() { return retroId == ANALOG; }

        @Override public String toString() { return control + "#" + retroId; }
    }

    // RetroPad IDs. The names are libretro's, which are the SNES pad's, so the
    // constant name is the SNES button and never the Thor's printed label.
    private static final int RP_B = 0, RP_Y = 1, RP_SELECT = 2, RP_START = 3;
    private static final int RP_UP = 4, RP_DOWN = 5, RP_LEFT = 6, RP_RIGHT = 7;
    private static final int RP_A = 8, RP_X = 9, RP_L = 10, RP_R = 11;
    private static final int RP_L2 = 12, RP_R2 = 13, RP_L3 = 14, RP_R3 = 15;

    private static final Map<String, Layout> LAYOUTS = build();

    private SystemControlLayouts() {}

    /** Thor control to console control name, for the remap editor. */
    public static Map<CanonicalControl, String> forSystem(String systemId) {
        Layout layout = LAYOUTS.get(normalize(systemId));
        return layout == null ? Collections.<CanonicalControl, String>emptyMap()
                : layout.names;
    }

    /** Physical position plus the console function the active core receives. */
    public static String controlLabel(String systemId, CanonicalControl control) {
        String position = control.name().replace('_', ' ');
        String function = forSystem(systemId).get(control);
        if (function == null) return position;
        function = function.replace('_', ' ');
        return position.equals(function) ? position : position + " — " + function;
    }

    /** Thor control to console control plus the RetroPad ID that reaches it. */
    public static Map<CanonicalControl, Binding> bindings(String systemId) {
        Layout layout = LAYOUTS.get(normalize(systemId));
        return layout == null ? Collections.<CanonicalControl, Binding>emptyMap()
                : layout.bindings;
    }

    /** Phone sticks for systems with a separately mapped analog controller. */
    public static int analogStickCount(String systemId) {
        String id = normalize(systemId);
        Map<CanonicalControl, Binding> table = bindings("n3ds".equals(id) ? "3ds" : id);
        Binding left = table.get(CanonicalControl.LEFT_X_NEGATIVE);
        Binding right = table.get(CanonicalControl.RIGHT_X_NEGATIVE);
        if (left == null || !left.analog()) return 0;
        return right != null && right.analog() ? 2 : 1;
    }

    /**
     * Every control the original console shipped with. Declared by hand rather
     * than derived from the bindings, so "this console has a C button" survives
     * even when nothing is bound to it and a test can fail.
     */
    public static Set<String> consoleControls(String systemId) {
        Layout layout = LAYOUTS.get(normalize(systemId));
        return layout == null ? Collections.<String>emptySet() : layout.console;
    }

    /** Every system id with a curated layout. */
    public static Set<String> systems() {
        return LAYOUTS.keySet();
    }

    private static Map<String, Layout> build() {
        Map<String, Layout> out = new HashMap<>();

        // --- Nintendo ----------------------------------------------------
        // Mesen2 (verified): A=8, B=0, Select=2 and Start=3. The NES has only
        // two action buttons, so make the whole Thor face cluster useful
        // without exposing Mesen's turbo-only RetroPad X/Y inputs: printed A
        // and B both press NES A, while printed X and Y both press NES B.
        add(out, new Layout().dpad()
                .put(CanonicalControl.EAST, "A", RP_A)
                .put(CanonicalControl.SOUTH, "A", RP_A)
                .put(CanonicalControl.NORTH, "B", RP_B)
                .put(CanonicalControl.WEST, "B", RP_B)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT)
                .console("A", "B", "START", "SELECT"),
                "nes", "famicom");

        // SameBoy (verified): A=8, B=0. On Thor, the printed A button is the
        // right face button and printed Y is the left face button. Keep those
        // physical labels meaningful: Thor A presses Game Boy A and Thor Y
        // presses Game Boy B.
        add(out, new Layout().dpad()
                .put(CanonicalControl.EAST, "A", RP_A)
                .put(CanonicalControl.WEST, "B", RP_B)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT)
                .console("A", "B", "START", "SELECT"),
                "gb", "gbc", "gameboy", "gameboycolor");

        // mGBA (verified): A=8, B=0, L=10, R=11, and L3/R3 drive the Boktai
        // cartridge's solar sensor, the only other input a GBA accepts.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "A", RP_A)
                .put(CanonicalControl.EAST, "B", RP_B)
                .put(CanonicalControl.L1, "L", RP_L)
                .put(CanonicalControl.R1, "R", RP_R)
                .put(CanonicalControl.L3, "SOLAR_DARKEN", RP_L3)
                .put(CanonicalControl.R3, "SOLAR_BRIGHTEN", RP_R3)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT)
                .console("A", "B", "L", "R", "START", "SELECT"),
                "gba", "gameboyadvance");

        // Mesen-S (verified): A=8, B=0, X=9, Y=1, L=10, R=11. The SNES diamond
        // is the diamond libretro's own IDs are named after, so this is a 1:1
        // geometric map: B under the thumb, exactly where a SNES player jumps.
        add(out, snes().console("A", "B", "X", "Y", "L", "R", "START", "SELECT"),
                "snes", "superfamicom");

        // melonDS DS (verified): the SNES diamond plus the DS's own extras.
        add(out, snes()
                .put(CanonicalControl.L2, "MICROPHONE", RP_L2)
                .put(CanonicalControl.R2, "SCREEN_LAYOUT", RP_R2)
                .put(CanonicalControl.L3, "LID", RP_L3)
                .put(CanonicalControl.R3, "TOUCH", RP_R3)
                .put(CanonicalControl.TOUCH_PRIMARY, "TOUCH", ANALOG)
                .rightStick("TOUCH_CURSOR")
                .console("A", "B", "X", "Y", "L", "R", "START", "SELECT",
                        "TOUCH", "LID", "MICROPHONE"),
                "nds", "nintendods", "ds");

        // Virtual Boy: two D-pads, A/B on the right face, L/R on the back.
        // beetle-vb is not built in this tree, so the IDs follow the libretro
        // convention and the second D-pad rides the right stick.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "A", RP_A)
                .put(CanonicalControl.EAST, "B", RP_B)
                .put(CanonicalControl.L1, "L", RP_L)
                .put(CanonicalControl.R1, "R", RP_R)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT)
                .rightStick("D_PAD_2_LEFT", "D_PAD_2_RIGHT", "D_PAD_2_UP", "D_PAD_2_DOWN")
                .console("A", "B", "L", "R", "START", "SELECT",
                        "D_PAD_2_UP", "D_PAD_2_DOWN", "D_PAD_2_LEFT", "D_PAD_2_RIGHT"),
                "virtualboy");

        // --- Sega --------------------------------------------------------
        // BlastEm (verified from the shipped core's own descriptor table):
        // A=B(0), B=A(8), C=R(11), X=Y(1), Y=X(9), Z=L(10), Mode=SELECT(2).
        // The three-button row A-B-C runs left to right across WEST, SOUTH and
        // EAST, so B — the button a Mega Drive thumb rests on — is the Thor's
        // bottom button and every one of the three is on the face cluster.
        // X-Y-Z is the row above: each sits up-and-over from its partner.
        add(out, new Layout().dpad()
                .put(CanonicalControl.WEST, "A", RP_B)
                .put(CanonicalControl.SOUTH, "B", RP_A)
                .put(CanonicalControl.EAST, "C", RP_R)
                .put(CanonicalControl.L1, "X", RP_Y)
                .put(CanonicalControl.NORTH, "Y", RP_X)
                .put(CanonicalControl.R1, "Z", RP_L)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "MODE", RP_SELECT)
                .console("A", "B", "C", "X", "Y", "Z", "START", "MODE"),
                "genesis", "megadrive", "segacd", "megacd", "sega32x");

        // Gearsystem (verified): B(0)="1", A(8)="2", START(3)="Start" and
        // SELECT(2) is the console's Reset switch, which is why Reset is on the
        // left stick click and EmuFusion's Select tap reaches nothing here.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "1", RP_B)
                .put(CanonicalControl.EAST, "2", RP_A)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.L3, "RESET", RP_SELECT)
                .console("1", "2", "START", "RESET"),
                "sg1000", "mastersystem", "gamegear");

        // Beetle Saturn (verified): A=0, B=8, C=11, X=1, Y=9, Z=10, L=12, R=13.
        // The same two rows as a Mega Drive pad, plus real shoulder triggers.
        add(out, new Layout().dpad()
                .put(CanonicalControl.WEST, "A", RP_B)
                .put(CanonicalControl.SOUTH, "B", RP_A)
                .put(CanonicalControl.EAST, "C", RP_R)
                .put(CanonicalControl.L1, "X", RP_Y)
                .put(CanonicalControl.NORTH, "Y", RP_X)
                .put(CanonicalControl.R1, "Z", RP_L)
                .put(CanonicalControl.L2, "L", RP_L2)
                .put(CanonicalControl.R2, "R", RP_R2)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.L3, "MODE", RP_SELECT)
                .console("A", "B", "C", "X", "Y", "Z", "L", "R", "START"),
                "saturn");

        // Flycast: the Dreamcast face cluster is already a diamond — A bottom,
        // B right, X left, Y top — and its two triggers are analog, so they
        // land on the Thor's analog triggers rather than its shoulders.
        add(out, new Layout().dpadWithAnalogStick("ANALOG_STICK")
                .put(CanonicalControl.SOUTH, "A", RP_B)
                .put(CanonicalControl.EAST, "B", RP_A)
                .put(CanonicalControl.WEST, "X", RP_Y)
                .put(CanonicalControl.NORTH, "Y", RP_X)
                .put(CanonicalControl.L2, "L", RP_L2)
                .put(CanonicalControl.R2, "R", RP_R2)
                .put(CanonicalControl.START, "START", RP_START)
                .console("A", "B", "X", "Y", "L", "R", "START", "ANALOG_STICK"),
                "dreamcast", "naomi", "atomiswave");

        // --- NEC, SNK, Bandai --------------------------------------------
        // Beetle PCE Fast (verified): II=0, I=8, III=1, IV=9, V=10, VI=11,
        // Run=3, Select=2, L2=the 6-button pad's mode switch. I is the action
        // button, so it takes SOUTH with II to its right; III-VI continue onto
        // the remaining face buttons and the shoulders.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "I", RP_A)
                .put(CanonicalControl.EAST, "II", RP_B)
                .put(CanonicalControl.WEST, "III", RP_Y)
                .put(CanonicalControl.NORTH, "IV", RP_X)
                .put(CanonicalControl.L1, "V", RP_L)
                .put(CanonicalControl.R1, "VI", RP_R)
                .put(CanonicalControl.L2, "MODE", RP_L2)
                .put(CanonicalControl.START, "RUN", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT)
                .console("I", "II", "III", "IV", "V", "VI", "RUN", "SELECT", "MODE"),
                "pcengine", "pcenginecd", "turbografx16");

        // Beetle NeoPop (verified): A=0, B=8, Option=3. A is left of B on the
        // hardware and is the action button, so the row falls on SOUTH, EAST.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "A", RP_B)
                .put(CanonicalControl.EAST, "B", RP_A)
                .put(CanonicalControl.START, "OPTION", RP_START)
                .console("A", "B", "OPTION"),
                "ngp", "ngpc", "neogeopocket", "neogeopocketcolor");

        // Beetle Cygne (verified): A=8, B=0, the X cursor is the D-pad and the
        // second (Y) cursor is L=left, R=right, L2=down, R2=up. A WonderSwan is
        // held two ways, so the Y cursor goes to the four index-finger controls
        // rather than stealing face buttons from A and B.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "A", RP_A)
                .put(CanonicalControl.EAST, "B", RP_B)
                .put(CanonicalControl.L1, "Y_LEFT", RP_L)
                .put(CanonicalControl.R1, "Y_RIGHT", RP_R)
                .put(CanonicalControl.L2, "Y_DOWN", RP_L2)
                .put(CanonicalControl.R2, "Y_UP", RP_R2)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "ROTATE", RP_SELECT)
                .console("A", "B", "START", "ROTATE",
                        "Y_UP", "Y_DOWN", "Y_LEFT", "Y_RIGHT"),
                "wonderswan", "wonderswancolor");

        // --- Sony ---------------------------------------------------------
        // SwanStation (verified): Cross=0, Circle=8, Triangle=9, Square=1, and
        // the shoulders and stick clicks are already 1:1. The DualShock diamond
        // maps straight onto the Thor's.
        add(out, playstation().console("CROSS", "CIRCLE", "SQUARE", "TRIANGLE",
                "L1", "R1", "L2", "R2", "START", "SELECT"),
                "psx", "ps1", "playstation");

        // Play! (verified): identical IDs. A PS2 pad reads its sticks and its
        // D-pad as separate controls, so the left stick stays analog here.
        add(out, playstation().dpadWithAnalogStick("LEFT_STICK")
                .rightStick("RIGHT_STICK")
                .console("CROSS", "CIRCLE", "SQUARE", "TRIANGLE", "L1", "R1",
                        "L2", "R2", "L3", "R3", "START", "SELECT",
                        "LEFT_STICK", "RIGHT_STICK"),
                "ps2");

        // PPSSPP (verified): Cross=0, Circle=8, Triangle=9, Square=1, L=10,
        // R=11. The PSP's analog nub is the left stick and is not the D-pad.
        add(out, new Layout().dpadWithAnalogStick("ANALOG_NUB")
                .put(CanonicalControl.SOUTH, "CROSS", RP_B)
                .put(CanonicalControl.EAST, "CIRCLE", RP_A)
                .put(CanonicalControl.WEST, "SQUARE", RP_Y)
                .put(CanonicalControl.NORTH, "TRIANGLE", RP_X)
                .put(CanonicalControl.L1, "L", RP_L)
                .put(CanonicalControl.R1, "R", RP_R)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT)
                .console("CROSS", "CIRCLE", "SQUARE", "TRIANGLE", "L", "R",
                        "START", "SELECT", "ANALOG_NUB"),
                "psp");

        // --- Nintendo 64, GameCube, Wii -----------------------------------
        // mupen64plus-next with its shipped mupen64plus-next-alt-map=False
        // (verified): A=B(0), B=Y(1), C1=A(8), C4=X(9), Z=L2(12), L=L(10),
        // R=R(11), R2(13) is the "C Buttons Mode" modifier and the four C
        // directions are RETRO_DEVICE_ANALOG index 1 — the right stick.
        add(out, new Layout().dpadWithAnalogStick("CONTROL_STICK")
                .put(CanonicalControl.SOUTH, "A", RP_B)
                .put(CanonicalControl.EAST, "B", RP_Y)
                .put(CanonicalControl.WEST, "C_DOWN", RP_A)
                .put(CanonicalControl.NORTH, "C_UP", RP_X)
                .put(CanonicalControl.L1, "L", RP_L)
                .put(CanonicalControl.R1, "R", RP_R)
                .put(CanonicalControl.L2, "Z", RP_L2)
                .put(CanonicalControl.R2, "C_MODE", RP_R2)
                .put(CanonicalControl.START, "START", RP_START)
                .rightStick("C_LEFT", "C_RIGHT", "C_UP", "C_DOWN")
                .console("A", "B", "Z", "L", "R", "START", "CONTROL_STICK",
                        "C_UP", "C_DOWN", "C_LEFT", "C_RIGHT"),
                "n64", "nintendo64");

        // Dolphin descGC (verified): A=8, B=0, X=9, Y=1, L=L2(12), R=R2(13),
        // Z=R(11), L3/R3 are the triggers' full-press clicks. RetroPad L(10)
        // and SELECT(2) are Dolphin's Triforce test and coin switches, which no
        // GameCube pad has, so both stay unmapped. The GameCube cluster is A in
        // the middle with B to its lower left, X to its right and Y above it.
        add(out, new Layout().dpadWithAnalogStick("CONTROL_STICK")
                .put(CanonicalControl.SOUTH, "A", RP_A)
                .put(CanonicalControl.WEST, "B", RP_B)
                .put(CanonicalControl.EAST, "X", RP_X)
                .put(CanonicalControl.NORTH, "Y", RP_Y)
                .put(CanonicalControl.L2, "L", RP_L2)
                .put(CanonicalControl.R2, "R", RP_R2)
                .put(CanonicalControl.R1, "Z", RP_R)
                .put(CanonicalControl.L3, "L_ANALOG", RP_L3)
                .put(CanonicalControl.R3, "R_ANALOG", RP_R3)
                .put(CanonicalControl.START, "START", RP_START)
                .rightStick("C_STICK")
                .console("A", "B", "X", "Y", "L", "R", "Z", "START",
                        "CONTROL_STICK", "C_STICK"),
                "gc", "gamecube", "nintendogamecube");

        // Match the actual WIIMOTE_NUNCHUK device selected by portDeviceFor:
        // A=8, B=0, X(9)=C, Y(1)=Z, Start(3)=1 and Select(2)=2.
        // L(10)/R(11) are -/+; the plain Wiimote has different 1/2 bindings.
        add(out, new Layout().dpadWithAnalogStick("NUNCHUK_STICK")
                .put(CanonicalControl.SOUTH, "A", RP_A)
                .put(CanonicalControl.EAST, "B", RP_B)
                .put(CanonicalControl.WEST, "NUNCHUK_C", RP_X)
                .put(CanonicalControl.NORTH, "NUNCHUK_Z", RP_Y)
                .put(CanonicalControl.L1, "MINUS", RP_L)
                .put(CanonicalControl.R1, "PLUS", RP_R)
                .put(CanonicalControl.L2, "SHAKE_NUNCHUK", RP_L2)
                .put(CanonicalControl.R2, "SHAKE_WIIMOTE", RP_R2)
                .put(CanonicalControl.R3, "HOME", RP_R3)
                .put(CanonicalControl.START, "1", RP_START)
                .put(CanonicalControl.SELECT, "2", RP_SELECT)
                .rightStick("IR_POINTER")
                .console("A", "B", "NUNCHUK_C", "NUNCHUK_Z", "1", "2", "PLUS",
                        "MINUS", "HOME", "NUNCHUK_STICK", "IR_POINTER"),
                "wii", "nintendowii");

        // Azahar (verified): B=0, A=8, Y=1, X=9, L=10, R=11, ZL=12, ZR=13,
        // L3=Home, R3=touch, Circle Pad on analog 0 and the C-stick on analog 1.
        add(out, new Layout().dpadWithAnalogStick("CIRCLE_PAD")
                .put(CanonicalControl.SOUTH, "B", RP_B)
                .put(CanonicalControl.EAST, "A", RP_A)
                .put(CanonicalControl.WEST, "Y", RP_Y)
                .put(CanonicalControl.NORTH, "X", RP_X)
                .put(CanonicalControl.L1, "L", RP_L)
                .put(CanonicalControl.R1, "R", RP_R)
                .put(CanonicalControl.L2, "ZL", RP_L2)
                .put(CanonicalControl.R2, "ZR", RP_R2)
                .put(CanonicalControl.L3, "HOME", RP_L3)
                .put(CanonicalControl.R3, "TOUCH", RP_R3)
                .put(CanonicalControl.TOUCH_PRIMARY, "TOUCH", ANALOG)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT)
                .rightStick("C_STICK")
                .console("A", "B", "X", "Y", "L", "R", "ZL", "ZR", "START",
                        "SELECT", "HOME", "TOUCH", "CIRCLE_PAD", "C_STICK"),
                "3ds");

        // --- Atari, Mattel, Coleco, Magnavox -------------------------------
        // ProSystem (verified): 1=0, 2=8, Console Reset=9, Console Select=2,
        // Console Pause=3, Left/Right Difficulty=10/11. The console switches
        // sit where a thumb never rests; Reset needs a deliberate stick click.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "1", RP_B)
                .put(CanonicalControl.EAST, "2", RP_A)
                .put(CanonicalControl.L1, "LEFT_DIFFICULTY", RP_L)
                .put(CanonicalControl.R1, "RIGHT_DIFFICULTY", RP_R)
                .put(CanonicalControl.L3, "CONSOLE_RESET", RP_X)
                .put(CanonicalControl.START, "CONSOLE_PAUSE", RP_START)
                .put(CanonicalControl.SELECT, "CONSOLE_SELECT", RP_SELECT)
                .rightStick("PLAYER_2_STICK")
                .console("1", "2", "CONSOLE_RESET", "CONSOLE_SELECT",
                        "CONSOLE_PAUSE", "LEFT_DIFFICULTY", "RIGHT_DIFFICULTY"),
                "atari7800");

        // Stella is not built in this tree; these follow the libretro
        // convention. The 2600 joystick has one button, the rest are the six
        // console switches.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "FIRE", RP_B)
                .put(CanonicalControl.EAST, "FIRE_2", RP_A)
                .put(CanonicalControl.NORTH, "COLOR_BW", RP_X)
                .put(CanonicalControl.L1, "LEFT_DIFFICULTY", RP_L)
                .put(CanonicalControl.R1, "RIGHT_DIFFICULTY", RP_R)
                .put(CanonicalControl.START, "CONSOLE_RESET", RP_START)
                .put(CanonicalControl.SELECT, "CONSOLE_SELECT", RP_SELECT)
                .console("FIRE", "CONSOLE_RESET", "CONSOLE_SELECT", "COLOR_BW",
                        "LEFT_DIFFICULTY", "RIGHT_DIFFICULTY"),
                "atari2600");

        // atari800 is not built in this tree. The 5200 pad is two fire buttons
        // plus Start, Pause, Reset and a twelve-key pad the core overlays.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "FIRE", RP_B)
                .put(CanonicalControl.EAST, "FIRE_2", RP_A)
                .put(CanonicalControl.NORTH, "PAUSE", RP_X)
                .put(CanonicalControl.WEST, "RESET", RP_Y)
                .put(CanonicalControl.L1, "KEYPAD_HASH", RP_L)
                .put(CanonicalControl.R1, "KEYPAD_STAR", RP_R)
                .put(CanonicalControl.L3, "KEYBOARD", RP_L3)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT)
                .console("FIRE", "FIRE_2", "START", "SELECT", "PAUSE", "RESET",
                        "KEYPAD_STAR", "KEYPAD_HASH", "KEYBOARD"),
                "atari5200", "atari800", "atari8bit");

        // Gearcoleco (verified): Yellow/left=0, Red/right=8, keypad 1-8 on
        // Y(1), X(9), L(10), R(11), L2(12), R2(13), L3(14), R3(15), * on
        // START(3), # on SELECT(2). Keypad 9 and 0 are the two axes of
        // RETRO_DEVICE_ANALOG index 0, which is why the ColecoVision left stick
        // is the keypad and not a second D-pad.
        add(out, new Layout().dpadOnly()
                .put(CanonicalControl.LEFT_Y_NEGATIVE, "KEYPAD_9", ANALOG)
                .put(CanonicalControl.LEFT_Y_POSITIVE, "KEYPAD_9", ANALOG)
                .put(CanonicalControl.LEFT_X_NEGATIVE, "KEYPAD_0", ANALOG)
                .put(CanonicalControl.LEFT_X_POSITIVE, "KEYPAD_0", ANALOG)
                .put(CanonicalControl.SOUTH, "LEFT_FIRE", RP_B)
                .put(CanonicalControl.EAST, "RIGHT_FIRE", RP_A)
                .put(CanonicalControl.WEST, "KEYPAD_1", RP_Y)
                .put(CanonicalControl.NORTH, "KEYPAD_2", RP_X)
                .put(CanonicalControl.L1, "KEYPAD_3", RP_L)
                .put(CanonicalControl.R1, "KEYPAD_4", RP_R)
                .put(CanonicalControl.L2, "KEYPAD_5", RP_L2)
                .put(CanonicalControl.R2, "KEYPAD_6", RP_R2)
                .put(CanonicalControl.L3, "KEYPAD_7", RP_L3)
                .put(CanonicalControl.R3, "KEYPAD_8", RP_R3)
                .put(CanonicalControl.START, "KEYPAD_STAR", RP_START)
                .put(CanonicalControl.SELECT, "KEYPAD_HASH", RP_SELECT)
                .console("LEFT_FIRE", "RIGHT_FIRE", "KEYPAD_0", "KEYPAD_1",
                        "KEYPAD_2", "KEYPAD_3", "KEYPAD_4", "KEYPAD_5",
                        "KEYPAD_6", "KEYPAD_7", "KEYPAD_8", "KEYPAD_9",
                        "KEYPAD_STAR", "KEYPAD_HASH"),
                "colecovision");

        // FreeIntv (verified): left action=8, right action=0, top action=1,
        // last keypad=9, show keypad=10/11, clear=12, enter=13, keypad 0=14,
        // keypad 5=15, pause=3, swap controllers=2, and keypad 1-9 is
        // RETRO_DEVICE_ANALOG index 1 — the right stick, which is exactly the
        // shape of the Intellivision's own twelve-key pad.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "RIGHT_ACTION", RP_B)
                .put(CanonicalControl.WEST, "LEFT_ACTION", RP_A)
                .put(CanonicalControl.NORTH, "TOP_ACTION", RP_Y)
                .put(CanonicalControl.EAST, "KEYPAD_LAST", RP_X)
                .put(CanonicalControl.L1, "SHOW_KEYPAD", RP_L)
                .put(CanonicalControl.R1, "SHOW_KEYPAD", RP_R)
                .put(CanonicalControl.L2, "KEYPAD_CLEAR", RP_L2)
                .put(CanonicalControl.R2, "KEYPAD_ENTER", RP_R2)
                .put(CanonicalControl.L3, "KEYPAD_0", RP_L3)
                .put(CanonicalControl.R3, "KEYPAD_5", RP_R3)
                .put(CanonicalControl.START, "PAUSE", RP_START)
                .put(CanonicalControl.SELECT, "SWAP_CONTROLLERS", RP_SELECT)
                .rightStick("KEYPAD_1_9")
                .console("LEFT_ACTION", "RIGHT_ACTION", "TOP_ACTION",
                        "KEYPAD_0", "KEYPAD_5", "KEYPAD_1_9", "KEYPAD_CLEAR",
                        "KEYPAD_ENTER", "SHOW_KEYPAD", "PAUSE"),
                "intellivision");

        // o2em is not built in this tree. The Odyssey² pad is one action
        // button; everything else is the console's own keyboard.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "ACTION", RP_B)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "KEYBOARD", RP_SELECT)
                .console("ACTION", "KEYBOARD"),
                "odyssey2");

        // --- Arcade --------------------------------------------------------
        // MAME assigns arcade buttons to RetroPad IDs from its own per-game
        // profile and remaps them in its TAB menu, so EmuFusion only guarantees
        // the eight buttons, coin and start are reachable and in reading order.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "BUTTON_1", RP_B)
                .put(CanonicalControl.EAST, "BUTTON_2", RP_A)
                .put(CanonicalControl.WEST, "BUTTON_3", RP_Y)
                .put(CanonicalControl.NORTH, "BUTTON_4", RP_X)
                .put(CanonicalControl.L1, "BUTTON_5", RP_L)
                .put(CanonicalControl.R1, "BUTTON_6", RP_R)
                .put(CanonicalControl.L2, "BUTTON_7", RP_L2)
                .put(CanonicalControl.R2, "BUTTON_8", RP_R2)
                .put(CanonicalControl.START, "START_1", RP_START)
                .put(CanonicalControl.SELECT, "COIN_1", RP_SELECT)
                .rightStick("RIGHT_STICK")
                .console("BUTTON_1", "BUTTON_2", "BUTTON_3", "BUTTON_4",
                        "BUTTON_5", "BUTTON_6", "BUTTON_7", "BUTTON_8",
                        "START_1", "COIN_1"),
                "arcade", "mame", "neogeo", "neogeocd");

        // --- Home computers -------------------------------------------------
        // Fuse (verified): Fire is A(8), X(9) and Y(1); B(0) is joystick Up,
        // which is how a Spectrum jumps; L(10) is Enter, R(11) is Space and
        // SELECT(2) raises the keyboard overlay. Sending the bottom button to
        // RetroPad B here used to walk the player upwards instead of firing.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "FIRE", RP_A)
                .put(CanonicalControl.EAST, "FIRE_2", RP_X)
                .put(CanonicalControl.WEST, "FIRE_3", RP_Y)
                .put(CanonicalControl.NORTH, "UP", RP_B)
                .put(CanonicalControl.L1, "ENTER", RP_L)
                .put(CanonicalControl.R1, "SPACE", RP_R)
                .put(CanonicalControl.SELECT, "KEYBOARD", RP_SELECT)
                .console("FIRE", "ENTER", "SPACE", "KEYBOARD"),
                "zxspectrum", "zx");

        // PUAE (verified): Fire/Red=0, 2nd fire/Blue=8, Green=1, Yellow=9,
        // Rewind=10, Forward=11, Play=3, Select=2. Plain Amiga games use the
        // one red fire button; the four colours are the CD32 pad.
        add(out, new Layout().dpad()
                .put(CanonicalControl.SOUTH, "RED_FIRE", RP_B)
                .put(CanonicalControl.EAST, "BLUE", RP_A)
                .put(CanonicalControl.WEST, "GREEN", RP_Y)
                .put(CanonicalControl.NORTH, "YELLOW", RP_X)
                .put(CanonicalControl.L1, "REWIND", RP_L)
                .put(CanonicalControl.R1, "FORWARD", RP_R)
                .put(CanonicalControl.START, "PLAY", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT)
                .rightStick("MOUSE")
                .console("RED_FIRE", "BLUE", "GREEN", "YELLOW", "REWIND",
                        "FORWARD", "PLAY", "SELECT"),
                "amiga", "amigacd32");

        // AppleWin (verified): Button 0=8, Button 1=0, and the D-pad drives the
        // two paddles to their extremes while RETRO_DEVICE_ANALOG index 0 is
        // the paddle pair itself, so the left stick is the paddle.
        add(out, new Layout().dpadOnly()
                .put(CanonicalControl.LEFT_X_NEGATIVE, "PADDLE", ANALOG)
                .put(CanonicalControl.LEFT_X_POSITIVE, "PADDLE", ANALOG)
                .put(CanonicalControl.LEFT_Y_NEGATIVE, "PADDLE", ANALOG)
                .put(CanonicalControl.LEFT_Y_POSITIVE, "PADDLE", ANALOG)
                .put(CanonicalControl.SOUTH, "BUTTON_0", RP_A)
                .put(CanonicalControl.EAST, "BUTTON_1", RP_B)
                .console("BUTTON_0", "BUTTON_1", "PADDLE"),
                "apple2");

        // vice, caprice32, hatari and bluemsx are not built in this tree. Every
        // one of these machines is a one- or two-button digital joystick plus a
        // keyboard the core overlays.
        add(out, computer("FIRE", "FIRE_2"), "c64", "commodore64");
        add(out, computer("FIRE_1", "FIRE_2"), "amstradcpc", "atarist");
        add(out, computer("A", "B"), "msx");
        // DOSBox Pure and ScummVM both build their own descriptors per title
        // and expose an in-core remapper, so EmuFusion only guarantees that every
        // RetroPad control is reachable in the standard positions.
        add(out, computer("BUTTON_1", "BUTTON_2"),
                "dos", "windows", "windows9x", "scummvm");

        // virtualjaguar is not built in this tree. The Jaguar pad is A, B, C in
        // a row, Option and Pause, and a twelve-key pad the core overlays.
        add(out, new Layout().dpad()
                .put(CanonicalControl.WEST, "A", RP_Y)
                .put(CanonicalControl.SOUTH, "B", RP_B)
                .put(CanonicalControl.EAST, "C", RP_A)
                .put(CanonicalControl.NORTH, "OPTION", RP_X)
                .put(CanonicalControl.L1, "KEYPAD_STAR", RP_L)
                .put(CanonicalControl.R1, "KEYPAD_HASH", RP_R)
                .put(CanonicalControl.START, "PAUSE", RP_START)
                .put(CanonicalControl.SELECT, "KEYPAD", RP_SELECT)
                .console("A", "B", "C", "OPTION", "PAUSE", "KEYPAD",
                        "KEYPAD_STAR", "KEYPAD_HASH"),
                "jaguar");

        Map<String, Layout> frozen = new HashMap<>();
        for (Map.Entry<String, Layout> entry : out.entrySet())
            frozen.put(entry.getKey(), entry.getValue().freeze());
        return Collections.unmodifiableMap(frozen);
    }

    /** The SNES diamond, shared by the SNES and the DS. */
    private static Layout snes() {
        return new Layout().dpad()
                .put(CanonicalControl.SOUTH, "B", RP_B)
                .put(CanonicalControl.EAST, "A", RP_A)
                .put(CanonicalControl.WEST, "Y", RP_Y)
                .put(CanonicalControl.NORTH, "X", RP_X)
                .put(CanonicalControl.L1, "L", RP_L)
                .put(CanonicalControl.R1, "R", RP_R)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT);
    }

    /** The DualShock diamond, shared by the PlayStation and the PS2. */
    private static Layout playstation() {
        return new Layout().dpad()
                .put(CanonicalControl.SOUTH, "CROSS", RP_B)
                .put(CanonicalControl.EAST, "CIRCLE", RP_A)
                .put(CanonicalControl.WEST, "SQUARE", RP_Y)
                .put(CanonicalControl.NORTH, "TRIANGLE", RP_X)
                .put(CanonicalControl.L1, "L1", RP_L)
                .put(CanonicalControl.R1, "R1", RP_R)
                .put(CanonicalControl.L2, "L2", RP_L2)
                .put(CanonicalControl.R2, "R2", RP_R2)
                .put(CanonicalControl.L3, "L3", RP_L3)
                .put(CanonicalControl.R3, "R3", RP_R3)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "SELECT", RP_SELECT);
    }

    /** A digital joystick with one or two buttons plus a keyboard overlay. */
    private static Layout computer(String primary, String secondary) {
        return new Layout().dpad()
                .put(CanonicalControl.SOUTH, primary, RP_B)
                .put(CanonicalControl.EAST, secondary, RP_A)
                .put(CanonicalControl.WEST, "BUTTON_3", RP_Y)
                .put(CanonicalControl.NORTH, "BUTTON_4", RP_X)
                .put(CanonicalControl.L1, "L", RP_L)
                .put(CanonicalControl.R1, "R", RP_R)
                .put(CanonicalControl.L2, "L2", RP_L2)
                .put(CanonicalControl.R2, "R2", RP_R2)
                .put(CanonicalControl.START, "START", RP_START)
                .put(CanonicalControl.SELECT, "KEYBOARD", RP_SELECT)
                .rightStick("MOUSE")
                .console(primary, secondary, "START", "KEYBOARD");
    }

    private static void add(Map<String, Layout> target, Layout layout, String... ids) {
        for (String id : ids) target.put(normalize(id), layout);
    }

    private static String normalize(String value) {
        return value == null ? "" : value.toLowerCase().replaceAll("[^a-z0-9]", "");
    }

    private static final class Layout {
        Map<CanonicalControl, Binding> bindings = new EnumMap<>(CanonicalControl.class);
        Set<String> console = new LinkedHashSet<>();
        Map<CanonicalControl, String> names;

        Layout put(CanonicalControl control, String name, int retroId) {
            bindings.put(control, new Binding(name, retroId));
            return this;
        }

        Layout console(String... controls) {
            console.addAll(Arrays.asList(controls));
            return this;
        }

        /** The digital D-pad only. */
        Layout dpadOnly() {
            put(CanonicalControl.DPAD_UP, "UP", RP_UP);
            put(CanonicalControl.DPAD_DOWN, "DOWN", RP_DOWN);
            put(CanonicalControl.DPAD_LEFT, "LEFT", RP_LEFT);
            put(CanonicalControl.DPAD_RIGHT, "RIGHT", RP_RIGHT);
            return console("UP", "DOWN", "LEFT", "RIGHT");
        }

        /**
         * The D-pad, plus the left stick as a second source for the same four
         * directions. Every console that shipped without a stick gets this, so
         * a stick-first player can play it; {@link JoypadPressLedger} ORs the
         * two sources so neither cancels the other.
         */
        Layout dpad() {
            dpadOnly();
            put(CanonicalControl.LEFT_Y_NEGATIVE, "UP", RP_UP);
            put(CanonicalControl.LEFT_Y_POSITIVE, "DOWN", RP_DOWN);
            put(CanonicalControl.LEFT_X_NEGATIVE, "LEFT", RP_LEFT);
            put(CanonicalControl.LEFT_X_POSITIVE, "RIGHT", RP_RIGHT);
            return this;
        }

        /**
         * The D-pad stays digital and the left stick becomes the console's own
         * analog stick. Aliasing the two on these consoles made every stick
         * movement also press a D-pad direction, which their games read as a
         * different control.
         */
        Layout dpadWithAnalogStick(String name) {
            dpadOnly();
            put(CanonicalControl.LEFT_Y_NEGATIVE, name, ANALOG);
            put(CanonicalControl.LEFT_Y_POSITIVE, name, ANALOG);
            put(CanonicalControl.LEFT_X_NEGATIVE, name, ANALOG);
            put(CanonicalControl.LEFT_X_POSITIVE, name, ANALOG);
            return this;
        }

        Layout rightStick(String name) {
            return rightStick(name, name, name, name);
        }

        /** The right stick is always RETRO_DEVICE_ANALOG index 1, never a button. */
        Layout rightStick(String left, String right, String up, String down) {
            put(CanonicalControl.RIGHT_X_NEGATIVE, left, ANALOG);
            put(CanonicalControl.RIGHT_X_POSITIVE, right, ANALOG);
            put(CanonicalControl.RIGHT_Y_NEGATIVE, up, ANALOG);
            put(CanonicalControl.RIGHT_Y_POSITIVE, down, ANALOG);
            return this;
        }

        Layout freeze() {
            if (names != null) return this;
            EnumMap<CanonicalControl, String> byName =
                    new EnumMap<>(CanonicalControl.class);
            for (Map.Entry<CanonicalControl, Binding> entry : bindings.entrySet())
                byName.put(entry.getKey(), entry.getValue().control);
            names = Collections.unmodifiableMap(byName);
            bindings = Collections.unmodifiableMap(bindings);
            console = Collections.unmodifiableSet(console);
            return this;
        }
    }
}
