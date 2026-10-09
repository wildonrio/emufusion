"""Keeps the controller mapping doc, the runtime table and the engine sessions
in agreement.

Two failures drive these tests.

The first is the ledger: the Thor reports its D-pad as a hat and its left stick
as ABS_X/ABS_Y, so both arrive as axes in one MotionEvent and both resolve to the
same RetroPad IDs on a D-pad-only console. Writing each source straight to
setJoypadButton made the last one written win, which is why one axis of the stick
and one axis of the hat each appeared dead on hardware.

The second is placement and IDs. The mapping used to live in two tables — one
holding the console's button names for the remap editor, one holding RetroPad
IDs for the runtime — and they drifted. The Mega Drive advertised "C" on the
right face button while that button pressed Mega Drive B, and the real C was
only reachable behind the right shoulder, which in Aladdin is the jump button.
There is now one table, and these tests pin it against the doc, against the
descriptors read out of the shipped cores, and against the console rosters.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "controller-mapping.md"
INPUT_DIR = ROOT / "unified-android" / "src" / "com" / "thorium" / "lucent" / "input"
LAYOUT = INPUT_DIR / "LibretroJoypadLayout.java"
LEDGER = INPUT_DIR / "JoypadPressLedger.java"
SYSTEM_LAYOUTS = INPUT_DIR / "SystemControlLayouts.java"
GAME_DIR = ROOT / "unified-android" / "src" / "com" / "thorium" / "preview" / "game"
LIBRETRO_SESSION = GAME_DIR / "LibretroEngineSession.java"
GLES_SESSION = GAME_DIR / "PpssppGlesEngineSession.java"
LAYOUT_TEST = (ROOT / "unified-android" / "test" / "com" / "thorium" / "lucent" /
               "input" / "LibretroJoypadLayoutTest.java")
LEDGER_TEST = (ROOT / "unified-android" / "test" / "com" / "thorium" / "lucent" /
               "input" / "JoypadPressLedgerTest.java")
TEST_RUNNER = ROOT / "unified-android" / "test.sh"
QA_HARNESS = ROOT / "unified-android" / "tools" / "run_runtime_acceptance_qa.py"

# Consoles whose core reads RETRO_DEVICE_ANALOG index 0 as its own control, so
# the left stick must not also press the digital D-pad. N64, GameCube, Wii,
# Dreamcast, PSP, PS2 and 3DS read the stick and the D-pad as different
# controls; gearcoleco reads that axis pair as keypad 9 and keypad 0, and
# AppleWin reads it as the two paddles.
ANALOG_STICK_SYSTEMS = {
    "n64", "nintendo64", "gc", "gamecube", "nintendogamecube", "wii",
    "nintendowii", "dreamcast", "naomi", "atomiswave", "psp", "ps2", "3ds",
    "colecovision", "apple2",
}

RETRO_IDS = {
    "RP_B": 0, "RP_Y": 1, "RP_SELECT": 2, "RP_START": 3, "RP_UP": 4,
    "RP_DOWN": 5, "RP_LEFT": 6, "RP_RIGHT": 7, "RP_A": 8, "RP_X": 9,
    "RP_L": 10, "RP_R": 11, "RP_L2": 12, "RP_R2": 13, "RP_L3": 14,
    "RP_R3": 15, "ANALOG": -1,
}

PUT = re.compile(r'\.put\(CanonicalControl\.(\w+), (?:"([^"]*)"|(\w+)), (\w+)\)')
# add(out, ...); blocks sit on consecutive lines, so the trailing newline is
# matched by lookahead: consuming it would hide every second block.
ADD = re.compile(r"\n        add\(out,(.*?)\);(?=\n)", re.S)
DPAD = (("DPAD_UP", "UP", 4), ("DPAD_DOWN", "DOWN", 5),
        ("DPAD_LEFT", "LEFT", 6), ("DPAD_RIGHT", "RIGHT", 7))
LEFT_AXES = ("LEFT_Y_NEGATIVE", "LEFT_Y_POSITIVE",
             "LEFT_X_NEGATIVE", "LEFT_X_POSITIVE")
RIGHT_AXES = ("RIGHT_X_NEGATIVE", "RIGHT_X_POSITIVE",
              "RIGHT_Y_NEGATIVE", "RIGHT_Y_POSITIVE")


def apply_helpers(block: str, table: dict) -> None:
    """Replays the Layout helpers the block calls, in source order."""
    for call, args in re.findall(r"\.(dpadOnly|dpad|dpadWithAnalogStick|"
                                 r"rightStick)\(([^)]*)\)", block):
        names = re.findall(r'"([^"]+)"', args)
        if call in ("dpad", "dpadOnly", "dpadWithAnalogStick"):
            for control, name, identifier in DPAD:
                table[control] = (name, identifier)
        if call == "dpad":
            for control, (_, name, identifier) in zip(LEFT_AXES, DPAD):
                table[control] = (name, identifier)
        elif call == "dpadWithAnalogStick":
            for control in LEFT_AXES:
                table[control] = (names[0], -1)
        elif call == "rightStick":
            picked = names * 4 if len(names) == 1 else names
            for control, name in zip(RIGHT_AXES, picked):
                table[control] = (name, -1)


def helper_puts(source: str, name: str) -> list:
    """The `.put` lines inside one `private static Layout <name>(...)` helper."""
    body = source.split("private static Layout " + name + "(", 1)[1].split(
        "\n    }", 1)[0]
    out = []
    for control, literal, variable, ident in PUT.findall(body):
        out.append((control, literal if variable == "" else variable,
                    RETRO_IDS[ident]))
    return out


def layout_body(source: str, name: str) -> str:
    return source.split("private static Layout " + name + "(", 1)[1].split(
        "\n    }", 1)[0]


def layout_blocks(source: str) -> dict:
    """Parses SystemControlLayouts.build() into {system: {control: (name, id)}}."""
    body = source.split("private static Map<String, Layout> build()", 1)[1]
    shared = {name: layout_body(source, name)
              for name in ("snes", "playstation", "computer")}
    tables = {}
    for block in ADD.findall(body):
        tail = block[block.rindex(")") + 1:]
        systems = re.findall(r'"([^"]+)"', tail)
        if not systems:
            continue
        table = {}
        for name, helper in shared.items():
            call = re.search(name + r"\(([^)]*)\)", block)
            if not call:
                continue
            arguments = re.findall(r'"([^"]+)"', call.group(1))
            alias = dict(zip(("primary", "secondary"), arguments))
            apply_helpers(helper, table)
            for control, literal, variable, ident in PUT.findall(helper):
                label = literal if variable == "" else alias.get(variable, variable)
                table[control] = (label, RETRO_IDS[ident])
        apply_helpers(block, table)
        for control, literal, variable, ident in PUT.findall(block):
            table[control] = (literal if variable == "" else variable,
                              RETRO_IDS[ident])
        for system in systems:
            tables[system] = table
    return tables


def doc_sections(doc: str) -> dict:
    """Parses the doc's per-system tables into {system: {control: (name, id)}}."""
    out = {}
    for chunk in doc.split("\n### ")[1:]:
        head, body = chunk.split("\n", 1)
        systems = re.findall(r"`([^`]+)`", head)
        rows = {}
        for line in body.splitlines():
            row = re.match(r"\| `([A-Z][A-Z0-9_]*)` [^|]*\| (\S+) \| `([^`]+)` \|",
                           line.strip())
            if row:
                identifier = -1 if row.group(2) == "analog" else int(row.group(2))
                rows[row.group(1)] = (row.group(3), identifier)
        if rows:
            for system in systems:
                out[system] = rows
    return out


class ControllerMappingDocTests(unittest.TestCase):
    def test_doc_exists_and_names_the_target_hardware(self):
        doc = DOC.read_text(encoding="utf-8")
        # The handover's recorded Thor facts. A doc that drifts from these is
        # describing a different device.
        for fact in ("BTN_SOUTH` 304", "BTN_SELECT` 314", "ABS_HAT0X",
                     "ABS_HAT0Y", "ABS_Z", "ABS_RZ",
                     "BTN_TL2` 312", "BTN_TR2` 313"):
            self.assertIn(fact, doc, f"the doc must record {fact}")

    def test_doc_covers_every_registered_system(self):
        doc = DOC.read_text(encoding="utf-8").lower()
        missing = []
        for name in ("registry.json", "phase2-registry.json", "phase3-registry.json"):
            registry = json.loads(
                (ROOT / "engines" / name).read_text(encoding="utf-8"))
            for engine in registry["engines"]:
                for system in engine["systems"]:
                    if f"`{system.lower()}`" not in doc:
                        missing.append(system)
        self.assertEqual([], sorted(set(missing)),
                         "every registered system needs a row in the mapping doc")

    def test_doc_states_the_placement_rules_it_applies(self):
        doc = DOC.read_text(encoding="utf-8")
        for rule in ("A diamond maps 1:1", "WEST -> SOUTH -> EAST",
                     "L1 -> NORTH -> R1",
                     "Two buttons put the action under the thumb",
                     "Console switches never sit under a thumb"):
            self.assertIn(rule, doc, f"the doc must state the rule: {rule}")

    def test_every_doc_row_matches_the_runtime_table(self):
        """The doc is generated from the table; this catches hand edits to either."""
        tables = layout_blocks(SYSTEM_LAYOUTS.read_text(encoding="utf-8"))
        sections = doc_sections(DOC.read_text(encoding="utf-8"))
        self.assertGreater(len(sections), 30, "the doc must table every system")
        checked = 0
        for system, rows in sections.items():
            self.assertIn(system, tables, f"{system} has a doc table but no layout")
            for control, (name, identifier) in rows.items():
                self.assertIn(control, tables[system],
                              f"{system} {control} is documented but not bound")
                self.assertEqual((name, identifier), tables[system][control],
                                 f"{system} {control} disagrees with the runtime table")
                checked += 1
        self.assertGreater(checked, 250, "the doc must table the real bindings")

    def test_every_layout_is_documented(self):
        tables = layout_blocks(SYSTEM_LAYOUTS.read_text(encoding="utf-8"))
        sections = doc_sections(DOC.read_text(encoding="utf-8"))
        self.assertEqual([], sorted(set(tables) - set(sections)),
                         "every system with a layout needs a doc table")


class RuntimeMappingTests(unittest.TestCase):
    def setUp(self):
        self.tables = layout_blocks(SYSTEM_LAYOUTS.read_text(encoding="utf-8"))

    def test_mega_drive_puts_its_three_button_row_on_the_face_cluster(self):
        # Read out of engines/build/arm64-v8a/blastem_libretro.so, from the
        # descriptor array retro_set_environment.desc: RetroPad B(0)="A",
        # A(8)="B", R(11)="C", Y(1)="X", X(9)="Y", L(10)="Z", SELECT(2)="Mode".
        # This is NOT the Genesis Plus GX convention, and assuming it was is
        # what left Aladdin without a jump button.
        for system in ("genesis", "megadrive", "segacd", "megacd", "sega32x"):
            table = self.tables[system]
            self.assertEqual(("A", 0), table["WEST"])
            self.assertEqual(("B", 8), table["SOUTH"])
            self.assertEqual(("C", 11), table["EAST"])
            self.assertEqual(("X", 1), table["L1"])
            self.assertEqual(("Y", 9), table["NORTH"])
            self.assertEqual(("Z", 10), table["R1"])
            self.assertEqual(("MODE", 2), table["SELECT"])
            self.assertEqual(("START", 3), table["START"])
        # Beetle Saturn declares the same six IDs for the same six buttons.
        saturn = self.tables["saturn"]
        for control, expected in (("WEST", ("A", 0)), ("SOUTH", ("B", 8)),
                                  ("EAST", ("C", 11)), ("L1", ("X", 1)),
                                  ("NORTH", ("Y", 9)), ("R1", ("Z", 10))):
            self.assertEqual(expected, saturn[control])

    def test_sega_eight_bit_keeps_reset_off_the_select_tap(self):
        # Gearsystem reads RetroPad SELECT(2) as the console's Reset switch, so
        # EmuFusion's Select tap must not reach it.
        for system in ("mastersystem", "gamegear", "sg1000"):
            table = self.tables[system]
            self.assertEqual(("1", 0), table["SOUTH"])
            self.assertEqual(("2", 8), table["EAST"])
            self.assertEqual(("RESET", 2), table["L3"])
            self.assertNotIn("SELECT", table)

    def test_diamonds_are_mapped_by_position(self):
        # Mesen-S, melonDS, SwanStation, PPSSPP, Play! and Azahar all agree:
        # the console's bottom button is RetroPad B(0) and its right is A(8).
        for system in ("snes", "superfamicom", "nds", "ds", "3ds"):
            self.assertEqual(0, self.tables[system]["SOUTH"][1])
            self.assertEqual(8, self.tables[system]["EAST"][1])
        # The NES duplicates its two action buttons across the Thor's four face
        # buttons. A and B both press NES A; X and Y both press NES B. The
        # Mesen-specific RetroPad X/Y turbo inputs must not be exposed.
        for system in ("nes", "famicom"):
            self.assertEqual(("A", 8), self.tables[system]["EAST"])
            self.assertEqual(("A", 8), self.tables[system]["SOUTH"])
            self.assertEqual(("B", 0), self.tables[system]["NORTH"])
            self.assertEqual(("B", 0), self.tables[system]["WEST"])
            self.assertFalse(any("TURBO" in label
                                 for label, _ in self.tables[system].values()))
        for system in ("psx", "ps1", "playstation", "ps2", "psp"):
            self.assertEqual(("CROSS", 0), self.tables[system]["SOUTH"])
            self.assertEqual(("CIRCLE", 8), self.tables[system]["EAST"])
            self.assertEqual(("SQUARE", 1), self.tables[system]["WEST"])
            self.assertEqual(("TRIANGLE", 9), self.tables[system]["NORTH"])
        self.assertEqual(("A", 0), self.tables["dreamcast"]["SOUTH"])
        self.assertEqual(("B", 8), self.tables["dreamcast"]["EAST"])

    def test_game_boy_uses_the_thor_a_and_y_buttons(self):
        for system in ("gb", "gbc"):
            self.assertEqual(("A", 8), self.tables[system]["EAST"])
            self.assertEqual(("B", 0), self.tables[system]["WEST"])
            self.assertNotIn("SOUTH", self.tables[system])
        # GBA keeps its established bottom/right pair.
        for system in ("gba", "gameboyadvance"):
            self.assertEqual(("A", 8), self.tables[system]["SOUTH"])
            self.assertEqual(("B", 0), self.tables[system]["EAST"])
        # Beetle PCE Fast reads I on A(8) and II on B(0).
        self.assertEqual(("I", 8), self.tables["pcengine"]["SOUTH"])
        self.assertEqual(("II", 0), self.tables["pcengine"]["EAST"])
        # Beetle NeoPop reads Neo Geo Pocket A on B(0) and B on A(8).
        self.assertEqual(("A", 0), self.tables["ngp"]["SOUTH"])
        self.assertEqual(("B", 8), self.tables["ngp"]["EAST"])
        # Fuse reads RetroPad B(0) as joystick Up, not Fire; sending the bottom
        # button there walked the player upwards instead of firing.
        self.assertEqual(("FIRE", 8), self.tables["zxspectrum"]["SOUTH"])
        self.assertEqual(("UP", 0), self.tables["zxspectrum"]["NORTH"])

    def test_gamecube_and_wii_use_the_dolphin_descriptors(self):
        # descGC: A=8, B=0, X=9, Y=1, L/R are the analog triggers, Z=R(11), and
        # RetroPad L(10)/SELECT(2) are the Triforce test and coin switches.
        gamecube = self.tables["gamecube"]
        self.assertEqual(("A", 8), gamecube["SOUTH"])
        self.assertEqual(("B", 0), gamecube["WEST"])
        self.assertEqual(("X", 9), gamecube["EAST"])
        self.assertEqual(("Y", 1), gamecube["NORTH"])
        self.assertEqual(("L", 12), gamecube["L2"])
        self.assertEqual(("R", 13), gamecube["R2"])
        self.assertEqual(("Z", 11), gamecube["R1"])
        self.assertNotIn("L1", gamecube)
        self.assertNotIn("SELECT", gamecube)
        wii = self.tables["wii"]
        self.assertEqual(8, wii["SOUTH"][1])
        self.assertEqual(0, wii["EAST"][1])
        self.assertEqual(9, wii["WEST"][1])
        self.assertEqual(1, wii["NORTH"][1])
        self.assertEqual(13, wii["R2"][1])

    def test_wii_labels_match_the_selected_nunchuk_controller(self):
        # Dolphin's active 0x301 device is not the plain Wiimote descriptor:
        # X/Y are C/Z, Start/Select are 1/2, and L/R remain minus/plus.
        for system in ("wii", "nintendowii"):
            wii = self.tables[system]
            self.assertEqual(("NUNCHUK_C", 9), wii["WEST"])
            self.assertEqual(("NUNCHUK_Z", 1), wii["NORTH"])
            self.assertEqual(("1", 3), wii["START"])
            self.assertEqual(("2", 2), wii["SELECT"])
            self.assertEqual(("MINUS", 10), wii["L1"])
            self.assertEqual(("PLUS", 11), wii["R1"])

    def test_both_remap_dialogs_use_console_function_labels(self):
        # The pure Java test verifies exact labels. This wiring check prevents
        # the Android picker/capture prompt from reverting to position-only UI.
        for path in (LIBRETRO_SESSION, GLES_SESSION):
            source = path.read_text()
            picker = source.split("private void showControlPicker(", 1)[1].split(
                "private void captureControl(", 1)[0]
            capture = source.split("private void captureControl(", 1)[1].split(
                "capture.setOnKeyListener", 1)[0]
            self.assertIn("SystemControlLayouts.controlLabel(", picker, path.name)
            self.assertIn("SystemControlLayouts.controlLabel(", capture, path.name)

    def test_n64_uses_the_mupen_default_map_not_the_generic_retropad(self):
        # mupen64plus-next ships alt-map=False: A=B(0), B=Y(1), Z=L2(12),
        # L=L(10), R=R(11), R2(13) is the C-buttons modifier and the four C
        # directions come from the right stick. The generic table put N64 B on
        # RetroPad A(8), which this core reads as a C-button.
        n64 = self.tables["n64"]
        self.assertEqual(("A", 0), n64["SOUTH"])
        self.assertEqual(("B", 1), n64["EAST"])
        self.assertEqual(("L", 10), n64["L1"])
        self.assertEqual(("R", 11), n64["R1"])
        self.assertEqual(("Z", 12), n64["L2"])
        self.assertEqual(("C_MODE", 13), n64["R2"])
        self.assertNotIn("SELECT", n64)
        self.assertEqual(("C_UP", -1), n64["RIGHT_Y_NEGATIVE"])
        self.assertEqual(("C_DOWN", -1), n64["RIGHT_Y_POSITIVE"])
        self.assertEqual(("C_LEFT", -1), n64["RIGHT_X_NEGATIVE"])
        self.assertEqual(("C_RIGHT", -1), n64["RIGHT_X_POSITIVE"])

    def test_keypad_consoles_reach_every_key(self):
        # A ColecoVision game that cannot be started without keypad 1 is as
        # unplayable as a platformer with no jump button.
        coleco = {name for name, _ in self.tables["colecovision"].values()}
        for key in range(10):
            self.assertIn(f"KEYPAD_{key}", coleco)
        self.assertIn("KEYPAD_STAR", coleco)
        self.assertIn("KEYPAD_HASH", coleco)
        intv = {name for name, _ in self.tables["intellivision"].values()}
        for control in ("LEFT_ACTION", "RIGHT_ACTION", "TOP_ACTION",
                        "KEYPAD_1_9", "KEYPAD_0", "KEYPAD_5", "KEYPAD_ENTER",
                        "KEYPAD_CLEAR"):
            self.assertIn(control, intv)
        wonderswan = {name for name, _ in self.tables["wonderswancolor"].values()}
        for cursor in ("Y_UP", "Y_DOWN", "Y_LEFT", "Y_RIGHT"):
            self.assertIn(cursor, wonderswan)
        a7800 = self.tables["atari7800"]
        self.assertEqual(("CONSOLE_RESET", 9), a7800["L3"])
        self.assertEqual(("LEFT_DIFFICULTY", 10), a7800["L1"])
        self.assertEqual(("RIGHT_DIFFICULTY", 11), a7800["R1"])

    def test_the_right_stick_is_analog_on_every_system(self):
        for system, table in self.tables.items():
            for control in ("RIGHT_X_NEGATIVE", "RIGHT_X_POSITIVE",
                            "RIGHT_Y_NEGATIVE", "RIGHT_Y_POSITIVE"):
                if control in table:
                    self.assertEqual(-1, table[control][1],
                                     f"{system} {control} must stay analog")
        # The fallback for a system with no table must not resurrect it either.
        fallback = LAYOUT.read_text(encoding="utf-8").split(
            "private static int genericRetroPad(", 1)[1].split("\n    }", 1)[0]
        self.assertIn("case RIGHT_X_NEGATIVE: case RIGHT_X_POSITIVE:", fallback)
        self.assertIn("case RIGHT_Y_NEGATIVE: case RIGHT_Y_POSITIVE:", fallback)

    def test_left_stick_doubles_as_the_dpad_except_on_analog_consoles(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        fallback = layout.split("private static int genericRetroPad(", 1)[1]
        for control, dpad in (("LEFT_Y_NEGATIVE", 4), ("LEFT_Y_POSITIVE", 5),
                              ("LEFT_X_NEGATIVE", 6), ("LEFT_X_POSITIVE", 7)):
            self.assertIn(f"case {control}: return analogStick ? -1 : {dpad};",
                          fallback)
        analog = layout.split("public static boolean hasAnalogStick(", 1)[1].split(
            "\n    }", 1)[0]
        self.assertEqual(ANALOG_STICK_SYSTEMS,
                         set(re.findall(r'case "([\w]+)":', analog)))
        # The curated tables have to agree with that list.
        source = SYSTEM_LAYOUTS.read_text(encoding="utf-8")
        for block in re.findall(r"\n        add\(out,(.*?)\);\n", source.split(
                "private static Map<String, Layout> build()", 1)[1], re.S):
            tail = block[block.rindex(")") + 1:]
            systems = re.findall(r'"([^"]+)"', tail)
            stick_is_dpad = ".dpad()" in block or "computer(" in block or (
                "snes()" in block or "playstation()" in block)
            stick_is_dpad = stick_is_dpad and "dpadWithAnalogStick" not in block
            stick_is_dpad = stick_is_dpad and "dpadOnly()" not in block
            for system in systems:
                self.assertEqual(system not in ANALOG_STICK_SYSTEMS, stick_is_dpad,
                                 f"{system} disagrees with hasAnalogStick")

    def test_one_table_carries_both_the_name_and_the_id(self):
        source = SYSTEM_LAYOUTS.read_text(encoding="utf-8")
        # The Binding is what stops the label and the ID drifting apart.
        self.assertIn("public final String control;", source)
        self.assertIn("public final int retroId;", source)
        self.assertIn("public static Map<CanonicalControl, Binding> bindings(",
                      source)
        self.assertIn("public static Set<String> consoleControls(", source)
        # ...and the runtime reads the ID out of that same entry.
        layout = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("SystemControlLayouts.bindings(system)", layout)
        self.assertIn("binding == null ? -1 : binding.retroId", layout)

    def test_wii_asks_for_the_nunchuk_port_device(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        # Dolphin defines RETRO_DEVICE_WIIMOTE_NC as (3 << 8) | JOYPAD.
        self.assertIn("WIIMOTE_NUNCHUK = (3 << 8) | RETRO_DEVICE_JOYPAD", layout)
        self.assertIn("RETRO_DEVICE_JOYPAD = 1", layout)
        self.assertIn("isWii(normalize(systemId)) ? WIIMOTE_NUNCHUK "
                      ": RETRO_DEVICE_JOYPAD", layout)
        # The doc has to say the native host cannot select it yet, otherwise a
        # reader assumes nunchuk-only titles already work.
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("set_controller_port_device(0, RETRO_DEVICE_JOYPAD)", doc)
        self.assertIn("dolphin_ir_mode", doc)


class CompletenessTests(unittest.TestCase):
    """The check that would have caught "I can't even jump"."""

    def test_every_system_declares_the_controls_its_console_shipped_with(self):
        source = SYSTEM_LAYOUTS.read_text(encoding="utf-8")
        body = source.split("private static Map<String, Layout> build()", 1)[1]
        blocks = re.findall(r"\n        add\(out,(.*?)\);\n", body, re.S)
        self.assertGreater(len(blocks), 30)
        for block in blocks:
            tail = block[block.rindex(")") + 1:]
            systems = re.findall(r'"([^"]+)"', tail)
            self.assertTrue(".console(" in block or "computer(" in block,
                            f"{systems} must declare its console's roster")

    def test_the_java_suite_proves_every_console_control_is_reachable(self):
        test = LAYOUT_TEST.read_text(encoding="utf-8")
        # Declared and invoked, not just defined.
        self.assertIn("everyConsoleControlIsReachable();", test)
        self.assertIn("private static void everyConsoleControlIsReachable()", test)
        self.assertIn("SystemControlLayouts.consoleControls(system)", test)
        self.assertIn("leaves console controls unreachable", test)
        # ...and the label a system advertises must be the ID it sends.
        self.assertIn("everyLabelAgreesWithTheIdItSends();", test)
        self.assertIn("megaDriveKeepsItsThreeButtonRowOnTheFace();", test)
        self.assertIn("keypadConsolesReachEveryKey();", test)
        # ...and the runner actually runs it.
        self.assertIn("com.thorium.lucent.input.LibretroJoypadLayoutTest",
                      TEST_RUNNER.read_text(encoding="utf-8"))


class LedgerWiringTests(unittest.TestCase):
    def test_the_ledger_ors_every_source_of_one_id(self):
        ledger = LEDGER.read_text(encoding="utf-8")
        self.assertIn(
            "public synchronized void apply(Object source, int retroId, "
            "boolean pressed", ledger)
        # A release from a source that never pressed must not clear an ID that
        # another source is holding: the motion sweep reports every axis on
        # every event, so those releases arrive constantly.
        self.assertIn("if (previous == null) return;", ledger)

    def test_both_sessions_write_the_joypad_only_through_the_ledger(self):
        for path in (LIBRETRO_SESSION, GLES_SESSION):
            source = path.read_text(encoding="utf-8")
            self.assertIn("JoypadPressLedger joypad = new JoypadPressLedger()", source)
            self.assertIn("JoypadPressLedger.Sink joypadSink", source)
            # Exactly one raw setJoypadButton call remains: the sink itself.
            raw = re.findall(r"\.setJoypadButton\(0, \w+, \w+\)", source)
            self.assertEqual(
                1, len(raw),
                f"{path.name} must reach setJoypadButton only through the sink")
            for dispatcher in ("dispatchKeyEvent", "dispatchVirtualControl",
                               "dispatchAxis"):
                self.assertIn(dispatcher, source)
            self.assertEqual(
                3, len(re.findall(r"joypad\.apply\(", source)),
                f"{path.name} routes keys, axes and on-screen controls through "
                "the ledger")

    def test_the_reported_hardware_failure_has_a_regression_test(self):
        test = LEDGER_TEST.read_text(encoding="utf-8")
        # Both halves of the user report, on both named systems.
        self.assertIn('holdSurvivesTheOtherSourceCentring("snes")', test)
        self.assertIn('holdSurvivesTheOtherSourceCentring("genesis")', test)
        self.assertIn('theThorAxisSweepOrderNoLongerDecidesTheWinner("snes")', test)
        self.assertIn('theThorAxisSweepOrderNoLongerDecidesTheWinner("genesis")', test)
        self.assertIn("AXIS_HAT_X", test)
        self.assertIn("AXIS_HAT_Y", test)

    def test_the_qa_harness_still_drives_the_hat_and_the_right_stick(self):
        # The acceptance harness is the only place real hardware input is
        # produced, so the doc's evdev facts have to match what it sends.
        harness = QA_HARNESS.read_text(encoding="utf-8")
        self.assertIn("A = 304", harness)
        self.assertIn("STOP = 314", harness)
        self.assertIn("HAT_X = 16", harness)
        self.assertIn("HAT_Y = 17", harness)
        self.assertIn('"ABS_Z": 2', harness)
        self.assertIn('"ABS_RZ": 5', harness)


if __name__ == "__main__":
    unittest.main()
