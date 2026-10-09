package com.thorium.lucent.input;

import com.thorium.lucent.TestSupport;

import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

public final class LibretroJoypadLayoutTest {
    public static void main(String[] args) {
        everyConsoleControlIsReachable();
        everyLabelAgreesWithTheIdItSends();
        megaDriveKeepsItsThreeButtonRowOnTheFace();
        segaEightBitReachesResetWithoutTheSelectTap();
        nintendoDiamondsAreMappedByPosition();
        twoButtonConsolesPutTheActionUnderTheThumb();
        pcEngineCdUsesTheSamePadAsCartridges();
        playStationAndHandheldsAreOneToOne();
        gameCubeAndWiiUseTheDolphinIds();
        remapLabelsShowTheActualConsoleFunction();
        nintendo64UsesTheMupenDefaultMap();
        keypadConsolesReachEveryKey();
        dpadOnlySystemsAlsoAcceptTheLeftStick();
        analogStickSystemsKeepTheStickOffTheDpad();
        theRightStickIsNeverADigitalButton();
        unknownSystemsFallBackToTheGenericRetroPad();
        System.out.println("LibretroJoypadLayoutTest passed");
    }

    /**
     * The check that would have caught "I can't even jump". Every control the
     * original console shipped with has to be reachable from some physical
     * control on the Thor: the Mega Drive's C used to be declared on the right
     * face button while that button actually pressed Mega Drive B, leaving C
     * only on a shoulder — and in Aladdin, C is the jump button.
     */
    private static void everyConsoleControlIsReachable() {
        for (String system : new TreeSet<>(SystemControlLayouts.systems())) {
            Set<String> bound = new LinkedHashSet<>(
                    SystemControlLayouts.forSystem(system).values());
            Set<String> missing = new TreeSet<>();
            for (String control : SystemControlLayouts.consoleControls(system))
                if (!bound.contains(control)) missing.add(control);
            TestSupport.equal("[]", missing.toString(),
                    system + " leaves console controls unreachable");
            TestSupport.truth(!SystemControlLayouts.consoleControls(system).isEmpty(),
                    system + " must declare the controls its console shipped with");
        }
    }

    /**
     * The remap editor and the running game read one table, so a label can
     * never name a different button from the one the ID presses. Two Thor
     * controls may share a console control (the D-pad and the left stick), but
     * one console control must not appear on two different RetroPad IDs unless
     * the core really exposes it twice.
     */
    private static void everyLabelAgreesWithTheIdItSends() {
        for (String system : SystemControlLayouts.systems()) {
            Map<CanonicalControl, SystemControlLayouts.Binding> bindings =
                    SystemControlLayouts.bindings(system);
            for (Map.Entry<CanonicalControl, SystemControlLayouts.Binding> entry
                    : bindings.entrySet()) {
                SystemControlLayouts.Binding binding = entry.getValue();
                TestSupport.equal(binding.retroId,
                        LibretroJoypadLayout.idFor(system, entry.getKey()),
                        system + " " + entry.getKey() + " runtime ID matches its label");
                TestSupport.equal(binding.control,
                        SystemControlLayouts.forSystem(system).get(entry.getKey()),
                        system + " " + entry.getKey() + " label matches its binding");
                TestSupport.truth(binding.retroId == SystemControlLayouts.ANALOG
                                || (binding.retroId >= 0 && binding.retroId <= 15),
                        system + " " + entry.getKey() + " uses a real RetroPad ID");
            }
            // A control with no binding is genuinely unmapped, not id 0.
            for (CanonicalControl control : CanonicalControl.values())
                if (!bindings.containsKey(control))
                    TestSupport.equal(-1, LibretroJoypadLayout.idFor(system, control),
                            system + " " + control + " is unmapped");
        }
    }

    /**
     * BlastEm's own descriptor table, read out of the shipped core: Mega Drive
     * A=RetroPad B(0), B=A(8), C=R(11), X=Y(1), Y=X(9), Z=L(10), Mode=SELECT(2).
     * The three-button row lands on the face cluster in its original order, so
     * every one of A, B and C is under the thumb and Aladdin can jump.
     */
    private static void megaDriveKeepsItsThreeButtonRowOnTheFace() {
        for (String system : new String[] {"genesis", "megadrive", "segacd", "sega32x"}) {
            Map<CanonicalControl, String> names = SystemControlLayouts.forSystem(system);
            TestSupport.equal("A", names.get(CanonicalControl.WEST), system + " left is A");
            TestSupport.equal("B", names.get(CanonicalControl.SOUTH), system + " bottom is B");
            TestSupport.equal("C", names.get(CanonicalControl.EAST), system + " right is C");
            TestSupport.equal(0, LibretroJoypadLayout.idFor(system, CanonicalControl.WEST),
                    system + " A is RetroPad B(0)");
            TestSupport.equal(8, LibretroJoypadLayout.idFor(system, CanonicalControl.SOUTH),
                    system + " B is RetroPad A(8)");
            TestSupport.equal(11, LibretroJoypadLayout.idFor(system, CanonicalControl.EAST),
                    system + " C is RetroPad R(11), not a face ID");
            // The six-button pad's second row: X above A, Y above B, Z above C.
            TestSupport.equal(1, LibretroJoypadLayout.idFor(system, CanonicalControl.L1),
                    system + " X is RetroPad Y(1)");
            TestSupport.equal(9, LibretroJoypadLayout.idFor(system, CanonicalControl.NORTH),
                    system + " Y is RetroPad X(9)");
            TestSupport.equal(10, LibretroJoypadLayout.idFor(system, CanonicalControl.R1),
                    system + " Z is RetroPad L(10)");
            TestSupport.equal(2, LibretroJoypadLayout.idFor(system, CanonicalControl.SELECT),
                    system + " Mode is RetroPad Select(2)");
            TestSupport.equal(3, LibretroJoypadLayout.idFor(system, CanonicalControl.START),
                    system + " Start is RetroPad Start(3)");
        }
        // Beetle Saturn declares the same six IDs for the same six buttons.
        TestSupport.equal(0, LibretroJoypadLayout.idFor("saturn", CanonicalControl.WEST),
                "Saturn A is RetroPad B(0)");
        TestSupport.equal(8, LibretroJoypadLayout.idFor("saturn", CanonicalControl.SOUTH),
                "Saturn B is RetroPad A(8)");
        TestSupport.equal(11, LibretroJoypadLayout.idFor("saturn", CanonicalControl.EAST),
                "Saturn C is RetroPad R(11)");
        TestSupport.equal(12, LibretroJoypadLayout.idFor("saturn", CanonicalControl.L2),
                "Saturn L is an analog trigger");
    }

    /**
     * Gearsystem reads RetroPad SELECT(2) as the console's Reset switch, so
     * EmuFusion's Select tap must not reach it: a stray tap would restart the
     * game. Reset lives on the left stick click instead.
     */
    private static void segaEightBitReachesResetWithoutTheSelectTap() {
        for (String system : new String[] {"mastersystem", "gamegear", "sg1000"}) {
            TestSupport.equal(0, LibretroJoypadLayout.idFor(system, CanonicalControl.SOUTH),
                    system + " button 1 is RetroPad B(0)");
            TestSupport.equal(8, LibretroJoypadLayout.idFor(system, CanonicalControl.EAST),
                    system + " button 2 is RetroPad A(8)");
            TestSupport.equal(-1, LibretroJoypadLayout.idFor(system, CanonicalControl.SELECT),
                    system + " Select must not reach the console Reset switch");
            TestSupport.equal(2, LibretroJoypadLayout.idFor(system, CanonicalControl.L3),
                    system + " Reset is a deliberate stick click");
            TestSupport.equal("RESET", SystemControlLayouts.forSystem(system)
                    .get(CanonicalControl.L3), system + " labels it Reset");
        }
    }

    /**
     * The SNES diamond is the diamond libretro's IDs are named after, so it maps
     * by position: B at the bottom where a SNES player jumps, A to its right,
     * Y left, X on top. The DS and the 3DS use the same cluster.
     */
    private static void nintendoDiamondsAreMappedByPosition() {
        for (String system : new String[] {"snes", "superfamicom", "nds", "ds"}) {
            TestSupport.equal(0, LibretroJoypadLayout.idFor(system, CanonicalControl.SOUTH),
                    system + " bottom is B");
            TestSupport.equal(8, LibretroJoypadLayout.idFor(system, CanonicalControl.EAST),
                    system + " right is A");
            TestSupport.equal(1, LibretroJoypadLayout.idFor(system, CanonicalControl.WEST),
                    system + " left is Y");
            TestSupport.equal(9, LibretroJoypadLayout.idFor(system, CanonicalControl.NORTH),
                    system + " top is X");
            TestSupport.equal("B", SystemControlLayouts.forSystem(system)
                    .get(CanonicalControl.SOUTH), system + " labels the bottom button B");
        }
        TestSupport.equal(14, LibretroJoypadLayout.idFor("nds", CanonicalControl.L3),
                "the DS lid is melonDS's Close Lid");
        TestSupport.equal(0, LibretroJoypadLayout.idFor("3ds", CanonicalControl.SOUTH),
                "the 3DS uses the same cluster as the SNES");
    }

    /** The NES has no turbo controls: A/B duplicate A and X/Y duplicate B. */
    private static void nesPlacesItsButtonsByName() {
        for (String system : new String[] {"nes", "famicom"}) {
            TestSupport.equal(8, LibretroJoypadLayout.idFor(system, CanonicalControl.EAST),
                    system + " printed A presses NES A");
            TestSupport.equal(8, LibretroJoypadLayout.idFor(system, CanonicalControl.SOUTH),
                    system + " printed B also presses NES A");
            TestSupport.equal("A", SystemControlLayouts.forSystem(system)
                    .get(CanonicalControl.EAST), system + " labels the right button A");
            TestSupport.equal("A", SystemControlLayouts.forSystem(system)
                    .get(CanonicalControl.SOUTH), system + " labels the bottom button A");
            TestSupport.equal(0, LibretroJoypadLayout.idFor(system, CanonicalControl.NORTH),
                    system + " printed X presses NES B");
            TestSupport.equal(0, LibretroJoypadLayout.idFor(system, CanonicalControl.WEST),
                    system + " printed Y presses NES B");
            TestSupport.equal("B", SystemControlLayouts.forSystem(system)
                    .get(CanonicalControl.NORTH), system + " labels the top button B");
            TestSupport.equal("B", SystemControlLayouts.forSystem(system)
                    .get(CanonicalControl.WEST), system + " labels the left button B");
            for (String label : SystemControlLayouts.forSystem(system).values())
                TestSupport.truth(!label.contains("TURBO"),
                        system + " exposes no turbo control");
        }
    }

    /**
     * A console with one row of buttons cannot reproduce that row on a diamond,
     * so the action button takes the bottom position, where the thumb rests,
     * and the second button sits to its right.
     */
    private static void twoButtonConsolesPutTheActionUnderTheThumb() {
        // NES and Famicom deliberately duplicate their two buttons across the
        // four-button face cluster; see nesPlacesItsButtonsByName().
        // The Thor's printed A/right and Y/left buttons are the Game Boy's A/B.
        for (String system : new String[] {"gb", "gbc"}) {
            TestSupport.equal(8, LibretroJoypadLayout.idFor(system, CanonicalControl.EAST),
                    system + " printed A is Game Boy A");
            TestSupport.equal(0, LibretroJoypadLayout.idFor(system, CanonicalControl.WEST),
                    system + " printed Y is Game Boy B");
            TestSupport.equal(-1, LibretroJoypadLayout.idFor(system, CanonicalControl.SOUTH),
                    system + " printed B is intentionally unbound");
            TestSupport.equal("A", SystemControlLayouts.forSystem(system)
                    .get(CanonicalControl.EAST), system + " labels printed A correctly");
        }
        // GBA retains its established bottom/right pair.
        for (String system : new String[] {"gba"}) {
            TestSupport.equal(8, LibretroJoypadLayout.idFor(system, CanonicalControl.SOUTH),
                    system + " bottom is A");
            TestSupport.equal(0, LibretroJoypadLayout.idFor(system, CanonicalControl.EAST),
                    system + " right is B");
            TestSupport.equal("A", SystemControlLayouts.forSystem(system)
                    .get(CanonicalControl.SOUTH), system + " labels the bottom button A");
        }
        TestSupport.equal(10, LibretroJoypadLayout.idFor("gba", CanonicalControl.L1),
                "the GBA keeps its shoulders");
        nesPlacesItsButtonsByName();
        // Beetle PCE Fast reads I on RetroPad A(8) and II on B(0).
        TestSupport.equal(8, LibretroJoypadLayout.idFor("pcengine", CanonicalControl.SOUTH),
                "PC Engine I is the action button");
        TestSupport.equal(0, LibretroJoypadLayout.idFor("pcengine", CanonicalControl.EAST),
                "PC Engine II sits to its right");
        TestSupport.equal(11, LibretroJoypadLayout.idFor("pcengine", CanonicalControl.R1),
                "the six-button PC Engine pad reaches VI");
        // Beetle NeoPop reads Neo Geo Pocket A on RetroPad B(0) and B on A(8),
        // which is also their left-to-right order on the hardware.
        TestSupport.equal(0, LibretroJoypadLayout.idFor("ngp", CanonicalControl.SOUTH),
                "Neo Geo Pocket A is RetroPad B(0)");
        TestSupport.equal(8, LibretroJoypadLayout.idFor("ngp", CanonicalControl.EAST),
                "Neo Geo Pocket B is RetroPad A(8)");
        TestSupport.equal("A", SystemControlLayouts.forSystem("ngp")
                .get(CanonicalControl.SOUTH), "the Neo Geo Pocket label follows the ID");
        // Fuse reads RetroPad B(0) as joystick Up, not Fire. Sending the bottom
        // button there walked the player upwards instead of firing.
        TestSupport.equal(8, LibretroJoypadLayout.idFor("zxspectrum", CanonicalControl.SOUTH),
                "the Spectrum fire button is RetroPad A(8)");
        TestSupport.equal("FIRE", SystemControlLayouts.forSystem("zxspectrum")
                .get(CanonicalControl.SOUTH), "the Spectrum bottom button is Fire");
        TestSupport.equal(0, LibretroJoypadLayout.idFor("zxspectrum", CanonicalControl.NORTH),
                "RetroPad B(0) is Fuse's joystick Up");
    }

    /** Cross, Circle, Square and Triangle sit exactly where the Thor's do. */
    private static void playStationAndHandheldsAreOneToOne() {
        for (String system : new String[] {"psx", "ps1", "playstation", "ps2", "psp"}) {
            TestSupport.equal(0, LibretroJoypadLayout.idFor(system, CanonicalControl.SOUTH),
                    system + " Cross is at the bottom");
            TestSupport.equal(8, LibretroJoypadLayout.idFor(system, CanonicalControl.EAST),
                    system + " Circle is on the right");
            TestSupport.equal(1, LibretroJoypadLayout.idFor(system, CanonicalControl.WEST),
                    system + " Square is on the left");
            TestSupport.equal(9, LibretroJoypadLayout.idFor(system, CanonicalControl.NORTH),
                    system + " Triangle is on top");
            TestSupport.equal("CROSS", SystemControlLayouts.forSystem(system)
                    .get(CanonicalControl.SOUTH), system + " labels the bottom button Cross");
        }
        // Flycast: the Dreamcast cluster is already A bottom, B right, X left,
        // Y top, and its two triggers are analog.
        TestSupport.equal(0, LibretroJoypadLayout.idFor("dreamcast", CanonicalControl.SOUTH),
                "Dreamcast A is at the bottom");
        TestSupport.equal(8, LibretroJoypadLayout.idFor("dreamcast", CanonicalControl.EAST),
                "Dreamcast B is on the right");
        TestSupport.equal(12, LibretroJoypadLayout.idFor("dreamcast", CanonicalControl.L2),
                "Dreamcast L is an analog trigger");
    }

    /**
     * Dolphin's descGC: A=8, B=0, X=9, Y=1, L/R are the analog triggers at
     * 12/13 and Z is R(11). RetroPad L(10) and SELECT(2) are the Triforce test
     * and coin switches, which no GameCube pad has. The Wiimote descriptors
     * agree on A=8 and B=0 with and without a Nunchuk.
     */
    private static void gameCubeAndWiiUseTheDolphinIds() {
        TestSupport.equal(8, LibretroJoypadLayout.idFor("gamecube", CanonicalControl.SOUTH),
                "GameCube A is the button under the thumb");
        TestSupport.equal(0, LibretroJoypadLayout.idFor("gamecube", CanonicalControl.WEST),
                "GameCube B sits to the lower left of A, as on the pad");
        TestSupport.equal(9, LibretroJoypadLayout.idFor("gamecube", CanonicalControl.EAST),
                "GameCube X sits to the right of A");
        TestSupport.equal(1, LibretroJoypadLayout.idFor("gamecube", CanonicalControl.NORTH),
                "GameCube Y sits above A");
        TestSupport.equal(-1, LibretroJoypadLayout.idFor("gamecube", CanonicalControl.L1),
                "GameCube does not expose Dolphin's Triforce-test switch");
        TestSupport.equal(-1, LibretroJoypadLayout.idFor("gamecube", CanonicalControl.SELECT),
                "GameCube does not expose Dolphin's Triforce-coin switch");
        TestSupport.equal(12, LibretroJoypadLayout.idFor("gamecube", CanonicalControl.L2),
                "GameCube left trigger");
        TestSupport.equal(13, LibretroJoypadLayout.idFor("gamecube", CanonicalControl.R2),
                "GameCube right trigger");
        TestSupport.equal(11, LibretroJoypadLayout.idFor("gamecube", CanonicalControl.R1),
                "GameCube Z shoulder");
        TestSupport.equal("A", SystemControlLayouts.forSystem("gamecube")
                .get(CanonicalControl.SOUTH), "GameCube remap label matches runtime A");
        TestSupport.equal("L", SystemControlLayouts.forSystem("gamecube")
                .get(CanonicalControl.L2), "GameCube remap label exposes L on the trigger");
        TestSupport.equal(8, LibretroJoypadLayout.idFor("wii", CanonicalControl.SOUTH),
                "Wii primary south is A");
        TestSupport.equal(0, LibretroJoypadLayout.idFor("wii", CanonicalControl.EAST),
                "Wii secondary east is B");
        TestSupport.equal(9, LibretroJoypadLayout.idFor("wii", CanonicalControl.WEST),
                "Wii west is Nunchuk C under the active controller device");
        TestSupport.equal(1, LibretroJoypadLayout.idFor("wii", CanonicalControl.NORTH),
                "Wii north is Nunchuk Z under the active controller device");
        TestSupport.equal(10, LibretroJoypadLayout.idFor("wii", CanonicalControl.L1),
                "Wii L1 is the Nunchuk-era minus button");
        TestSupport.equal(11, LibretroJoypadLayout.idFor("wii", CanonicalControl.R1),
                "Wii R1 is the Nunchuk-era plus button");
        TestSupport.equal(13, LibretroJoypadLayout.idFor("wii", CanonicalControl.R2),
                "Wii R2 shakes the Wiimote");
        TestSupport.equal("A", SystemControlLayouts.forSystem("wii")
                .get(CanonicalControl.SOUTH), "Wii remap label matches runtime A mapping");
        TestSupport.equal(LibretroJoypadLayout.WIIMOTE_NUNCHUK,
                LibretroJoypadLayout.portDeviceFor("wii"),
                "Wii asks for Dolphin's Wiimote+Nunchuk port device");
        for (String system : new String[] {"wii", "nintendowii"}) {
            Map<CanonicalControl, String> names = SystemControlLayouts.forSystem(system);
            TestSupport.equal("NUNCHUK_C", names.get(CanonicalControl.WEST),
                    system + " west label does not claim to press remote 1");
            TestSupport.equal("NUNCHUK_Z", names.get(CanonicalControl.NORTH),
                    system + " north label does not claim to press remote 2");
            TestSupport.equal("1", names.get(CanonicalControl.START),
                    system + " Start sends remote 1, not Plus");
            TestSupport.equal("2", names.get(CanonicalControl.SELECT),
                    system + " Select sends remote 2, not Minus");
            TestSupport.equal(3, LibretroJoypadLayout.idFor(system, CanonicalControl.START),
                    system + " remote 1 preserves the existing Start ID");
            TestSupport.equal(2, LibretroJoypadLayout.idFor(system, CanonicalControl.SELECT),
                    system + " remote 2 preserves the existing Select ID");
            TestSupport.equal("MINUS", names.get(CanonicalControl.L1),
                    system + " Minus remains on L1");
            TestSupport.equal("PLUS", names.get(CanonicalControl.R1),
                    system + " Plus remains on R1");
        }
        TestSupport.equal(LibretroJoypadLayout.RETRO_DEVICE_JOYPAD,
                LibretroJoypadLayout.portDeviceFor("gamecube"),
                "every other system is a plain RetroPad");
    }

    private static void pcEngineCdUsesTheSamePadAsCartridges() {
        for (String system : new String[] {"pcenginecd", "PC Engine CD"}) {
            TestSupport.equal(8, LibretroJoypadLayout.idFor(system, CanonicalControl.SOUTH),
                    "PC Engine CD I must not fall back to generic RetroPad B");
            TestSupport.equal(0, LibretroJoypadLayout.idFor(system, CanonicalControl.EAST),
                    "PC Engine CD II must not be exchanged with I");
            TestSupport.equal("RUN", SystemControlLayouts.forSystem(system).get(CanonicalControl.START),
                    "CD start label must describe Run");
            TestSupport.equal(SystemControlLayouts.consoleControls("pcengine"),
                    SystemControlLayouts.consoleControls(system), "CD console roster");
            for (CanonicalControl control : CanonicalControl.values()) {
                TestSupport.equal(LibretroJoypadLayout.idFor("pcengine", control),
                        LibretroJoypadLayout.idFor(system, control), "CD pad ID: " + control);
                TestSupport.equal(SystemControlLayouts.forSystem("pcengine").get(control),
                        SystemControlLayouts.forSystem(system).get(control), "CD pad label: " + control);
            }
            TestSupport.equal(0, SystemControlLayouts.analogStickCount(system),
                    "CD pad has no separate phone analog stick");
            TestSupport.equal(LibretroJoypadLayout.RETRO_DEVICE_JOYPAD,
                    LibretroJoypadLayout.portDeviceFor(system), "CD uses the same RetroPad port");
        }
    }

    private static void remapLabelsShowTheActualConsoleFunction() {
        TestSupport.equal("START — 1",
                SystemControlLayouts.controlLabel("wii", CanonicalControl.START),
                "Wii picker describes remote 1 rather than Plus");
        TestSupport.equal("SELECT — 2",
                SystemControlLayouts.controlLabel("nintendowii", CanonicalControl.SELECT),
                "Wii picker describes remote 2 rather than Minus");
        TestSupport.equal("WEST — NUNCHUK C",
                SystemControlLayouts.controlLabel("wii", CanonicalControl.WEST),
                "Wii picker describes the active Nunchuk device");
        TestSupport.equal("SOUTH — B",
                SystemControlLayouts.controlLabel("snes", CanonicalControl.SOUTH),
                "other curated cores show their own real console function");
        TestSupport.equal("START",
                SystemControlLayouts.controlLabel("nes", CanonicalControl.START),
                "matching labels are not repeated");
        TestSupport.equal("SOUTH",
                SystemControlLayouts.controlLabel("unknown", CanonicalControl.SOUTH),
                "unknown systems retain the existing position label");
        TestSupport.equal("L1",
                SystemControlLayouts.controlLabel("gamecube", CanonicalControl.L1),
                "unmapped controls do not invent a console function");
    }

    /**
     * mupen64plus-next with its shipped alt-map=False default: A=B(0), B=Y(1),
     * Z=L2(12), L=L(10), R=R(11), and R2(13) is the C-buttons modifier. The
     * generic RetroPad table put N64 B on RetroPad A(8), which the core reads
     * as a C-button rather than B.
     */
    private static void nintendo64UsesTheMupenDefaultMap() {
        TestSupport.equal(0, LibretroJoypadLayout.idFor("n64", CanonicalControl.SOUTH),
                "N64 south is A");
        TestSupport.equal(1, LibretroJoypadLayout.idFor("n64", CanonicalControl.EAST),
                "N64 east is B, not a C-button");
        TestSupport.equal(10, LibretroJoypadLayout.idFor("n64", CanonicalControl.L1),
                "N64 L1 is the L shoulder");
        TestSupport.equal(11, LibretroJoypadLayout.idFor("n64", CanonicalControl.R1),
                "N64 R1 is the R shoulder");
        TestSupport.equal(12, LibretroJoypadLayout.idFor("n64", CanonicalControl.L2),
                "N64 L2 is the Z trigger");
        TestSupport.equal(13, LibretroJoypadLayout.idFor("n64", CanonicalControl.R2),
                "N64 R2 is the C-buttons modifier");
        TestSupport.equal(-1, LibretroJoypadLayout.idFor("n64", CanonicalControl.SELECT),
                "the N64 pad has no Select");
        TestSupport.equal(4, LibretroJoypadLayout.idFor("n64", CanonicalControl.DPAD_UP),
                "the N64 D-pad stays the D-pad");
        // The four C directions are analog: mupen reads them from
        // RETRO_DEVICE_ANALOG index 1, which is the right stick.
        Map<CanonicalControl, String> n64 = SystemControlLayouts.forSystem("n64");
        TestSupport.equal("C_UP", n64.get(CanonicalControl.RIGHT_Y_NEGATIVE),
                "right stick up is C-up");
        TestSupport.equal("C_DOWN", n64.get(CanonicalControl.RIGHT_Y_POSITIVE),
                "right stick down is C-down");
        TestSupport.equal("C_LEFT", n64.get(CanonicalControl.RIGHT_X_NEGATIVE),
                "right stick left is C-left");
        TestSupport.equal("C_RIGHT", n64.get(CanonicalControl.RIGHT_X_POSITIVE),
                "right stick right is C-right");
        TestSupport.equal("CONTROL_STICK", n64.get(CanonicalControl.LEFT_X_NEGATIVE),
                "the N64 analog stick is the left stick");
        TestSupport.equal("Z", n64.get(CanonicalControl.L2), "N64 Z trigger label");
    }

    /**
     * A ColecoVision or Intellivision game that asks for a keypad digit is
     * unplayable if the keypad is unreachable, which is the same failure as a
     * missing jump button.
     */
    private static void keypadConsolesReachEveryKey() {
        Map<CanonicalControl, String> coleco =
                SystemControlLayouts.forSystem("colecovision");
        for (int key = 0; key <= 9; key++)
            TestSupport.truth(coleco.containsValue("KEYPAD_" + key),
                    "ColecoVision keypad " + key + " must be reachable");
        TestSupport.truth(coleco.containsValue("KEYPAD_STAR")
                        && coleco.containsValue("KEYPAD_HASH"),
                "ColecoVision * and # must be reachable");
        // gearcoleco reads RETRO_DEVICE_ANALOG index 0 as keypad 9 and 0, so
        // the ColecoVision left stick cannot also be the D-pad.
        TestSupport.equal(-1, LibretroJoypadLayout.idFor("colecovision",
                CanonicalControl.LEFT_Y_NEGATIVE),
                "the ColecoVision left stick is the keypad, not the D-pad");
        TestSupport.equal(4, LibretroJoypadLayout.idFor("colecovision",
                CanonicalControl.DPAD_UP), "the ColecoVision D-pad still works");
        Map<CanonicalControl, String> intv =
                SystemControlLayouts.forSystem("intellivision");
        TestSupport.equal("KEYPAD_1_9", intv.get(CanonicalControl.RIGHT_X_POSITIVE),
                "the Intellivision keypad is the right stick");
        TestSupport.truth(intv.containsValue("TOP_ACTION")
                        && intv.containsValue("LEFT_ACTION")
                        && intv.containsValue("RIGHT_ACTION"),
                "all three Intellivision action buttons must be reachable");
        // ProSystem exposes the 7800's console switches; Reset needs a click.
        Map<CanonicalControl, String> a7800 = SystemControlLayouts.forSystem("atari7800");
        TestSupport.equal("CONSOLE_RESET", a7800.get(CanonicalControl.L3),
                "the 7800 Reset switch is a deliberate stick click");
        TestSupport.equal(9, LibretroJoypadLayout.idFor("atari7800", CanonicalControl.L3),
                "ProSystem reads Console Reset on RetroPad X(9)");
        TestSupport.truth(a7800.containsValue("LEFT_DIFFICULTY")
                        && a7800.containsValue("RIGHT_DIFFICULTY"),
                "the 7800 difficulty switches must be reachable");
        // The WonderSwan's second cursor is a real control of the machine.
        Map<CanonicalControl, String> ws = SystemControlLayouts.forSystem("wonderswancolor");
        for (String cursor : new String[] {"Y_UP", "Y_DOWN", "Y_LEFT", "Y_RIGHT"})
            TestSupport.truth(ws.containsValue(cursor),
                    "the WonderSwan " + cursor + " must be reachable");
    }

    /** Every console that shipped without a stick still accepts one. */
    private static void dpadOnlySystemsAlsoAcceptTheLeftStick() {
        String[] systems = {
                "nes", "snes", "gb", "gbc", "gba", "genesis", "megadrive", "mastersystem",
                "gamegear", "sg1000", "segacd", "sega32x", "pcengine", "pcenginecd", "turbografx16",
                "neogeo", "neogeocd", "arcade", "atari2600", "atari5200", "atari7800",
                "atari800", "atarist", "amstradcpc", "c64", "msx", "zxspectrum",
                "wonderswan", "wonderswancolor", "ngp", "ngpc", "virtualboy", "dos",
                "scummvm", "psx", "nds", "intellivision", "odyssey2", "saturn",
                "amiga", "amigacd32", "jaguar",
        };
        for (String system : systems) {
            TestSupport.equal(4, LibretroJoypadLayout.idFor(system,
                    CanonicalControl.LEFT_Y_NEGATIVE), system + " left stick up is D-pad up");
            TestSupport.equal(5, LibretroJoypadLayout.idFor(system,
                    CanonicalControl.LEFT_Y_POSITIVE), system + " left stick down is D-pad down");
            TestSupport.equal(6, LibretroJoypadLayout.idFor(system,
                    CanonicalControl.LEFT_X_NEGATIVE), system + " left stick left is D-pad left");
            TestSupport.equal(7, LibretroJoypadLayout.idFor(system,
                    CanonicalControl.LEFT_X_POSITIVE),
                    system + " left stick right is D-pad right");
            Map<CanonicalControl, String> layout = SystemControlLayouts.forSystem(system);
            if (layout.isEmpty()) continue;
            TestSupport.equal("UP", layout.get(CanonicalControl.LEFT_Y_NEGATIVE),
                    system + " declares the left stick as its D-pad");
            TestSupport.equal("RIGHT", layout.get(CanonicalControl.LEFT_X_POSITIVE),
                    system + " declares the left stick as its D-pad");
        }
    }

    /**
     * Consoles whose core reads RETRO_DEVICE_ANALOG index 0 must keep the stick
     * off the digital D-pad: those games read the two as separate controls.
     */
    private static void analogStickSystemsKeepTheStickOffTheDpad() {
        String[] systems = {"n64", "gamecube", "gc", "wii", "dreamcast", "naomi",
                "atomiswave", "psp", "ps2", "3ds", "colecovision", "apple2"};
        for (String system : systems) {
            TestSupport.truth(LibretroJoypadLayout.hasAnalogStick(system),
                    system + " has its own analog stick");
            TestSupport.equal(-1, LibretroJoypadLayout.idFor(system,
                    CanonicalControl.LEFT_Y_NEGATIVE),
                    system + " does not press the D-pad from the stick");
            TestSupport.equal(-1, LibretroJoypadLayout.idFor(system,
                    CanonicalControl.LEFT_X_POSITIVE),
                    system + " does not press the D-pad from the stick");
            TestSupport.equal(4, LibretroJoypadLayout.idFor(system, CanonicalControl.DPAD_UP),
                    system + " keeps a working D-pad");
        }
        TestSupport.truth(!LibretroJoypadLayout.hasAnalogStick("snes"),
                "the SNES pad has no analog stick");
        // The curated tables and hasAnalogStick have to agree, or the fallback
        // and the table would disagree for the same system.
        for (String system : SystemControlLayouts.systems()) {
            boolean tableIsAnalog = LibretroJoypadLayout.idFor(system,
                    CanonicalControl.LEFT_Y_NEGATIVE) < 0;
            TestSupport.equal(LibretroJoypadLayout.hasAnalogStick(system), tableIsAnalog,
                    system + " table and hasAnalogStick agree about the left stick");
        }
    }

    private static void theRightStickIsNeverADigitalButton() {
        Set<String> systems = new LinkedHashSet<>(SystemControlLayouts.systems());
        systems.add("switch");
        systems.add("wiiu");
        for (String system : systems)
            for (CanonicalControl control : new CanonicalControl[] {
                    CanonicalControl.RIGHT_X_NEGATIVE, CanonicalControl.RIGHT_X_POSITIVE,
                    CanonicalControl.RIGHT_Y_NEGATIVE, CanonicalControl.RIGHT_Y_POSITIVE})
                TestSupport.equal(-1, LibretroJoypadLayout.idFor(system, control),
                        system + " keeps the right stick analog for " + control);
    }

    /** A system with no curated table still gets a playable pad. */
    private static void unknownSystemsFallBackToTheGenericRetroPad() {
        TestSupport.truth(SystemControlLayouts.forSystem("3do").isEmpty(),
                "3do has no curated table");
        TestSupport.equal(0, LibretroJoypadLayout.idFor("3do", CanonicalControl.SOUTH),
                "the fallback puts the console's bottom button at the bottom");
        TestSupport.equal(8, LibretroJoypadLayout.idFor("3do", CanonicalControl.EAST),
                "the fallback puts the console's right button on the right");
        TestSupport.equal(1, LibretroJoypadLayout.idFor("3do", CanonicalControl.WEST),
                "the fallback puts the console's left button on the left");
        TestSupport.equal(9, LibretroJoypadLayout.idFor("3do", CanonicalControl.NORTH),
                "the fallback puts the console's top button on top");
        TestSupport.equal(4, LibretroJoypadLayout.idFor("3do", CanonicalControl.LEFT_Y_NEGATIVE),
                "the fallback still lets the left stick drive the D-pad");
        TestSupport.equal(-1, LibretroJoypadLayout.idFor("3do", CanonicalControl.GUIDE),
                "the fallback leaves Guide to Lucent");
    }
}
