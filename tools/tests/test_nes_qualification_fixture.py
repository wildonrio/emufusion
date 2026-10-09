import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "engines" / "qa" / "generate_fixtures.py"
SPEC = importlib.util.spec_from_file_location("nes_qualification_fixture", GENERATOR)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NesQualificationFixtureTest(unittest.TestCase):
    EXPECTED_SHA256 = "42019e9ca4a3a11815a9e13b7c60734a73fb7ae3cb06a140915daa4605ee8508"

    def setUp(self):
        self.rom = MODULE.make_nes()
        self.prg = self.rom[16:16 + 0x4000]
        self.chr = self.rom[16 + 0x4000:]

    def test_is_deterministic_nrom_with_battery_ram(self):
        self.assertEqual(self.rom, MODULE.make_nes())
        self.assertEqual(hashlib.sha256(self.rom).hexdigest(), self.EXPECTED_SHA256)
        self.assertEqual(len(self.rom), 16 + 0x4000 + 0x2000)
        self.assertEqual(self.rom[:4], b"NES\x1a")
        self.assertEqual(self.rom[4:8], bytes((1, 1, 0x02, 0x00)))

    def test_vectors_point_inside_the_generated_program(self):
        nmi = int.from_bytes(self.prg[0x3FFA:0x3FFC], "little")
        reset = int.from_bytes(self.prg[0x3FFC:0x3FFE], "little")
        irq = int.from_bytes(self.prg[0x3FFE:0x4000], "little")
        self.assertEqual(reset, 0x8000)
        self.assertTrue(0x8000 < nmi < irq < 0x8400)
        self.assertEqual(self.prg[irq - 0x8000], 0x40)  # RTI

    def test_rom_initializes_visible_edges_audio_and_controller(self):
        # PPUMASK=$1E keeps background/sprites visible through both 8px edges.
        self.assertIn(bytes((0xA9, 0x1E, 0x8D, 0x01, 0x20)), self.prg)
        # Pulse 1 is enabled with 50% duty, constant volume 15, timer 253.
        self.assertIn(bytes((0xA9, 0x01, 0x8D, 0x15, 0x40)), self.prg)
        self.assertIn(bytes((0xA9, 0xBF, 0x8D, 0x00, 0x40)), self.prg)
        self.assertIn(bytes((0xA9, 0xFD, 0x8D, 0x02, 0x40)), self.prg)
        # Canonical strobe and eight serial controller reads.
        self.assertIn(bytes((0xA9, 0x01, 0x8D, 0x16, 0x40)), self.prg)
        self.assertIn(bytes((0xA2, 0x08, 0xAD, 0x16, 0x40, 0x4A, 0x66, 0x00)),
                      self.prg)
        # All unused OAM entries are hidden (Y=$F8) before the two authored
        # sprites are installed; four INX operations walk each 4-byte record.
        self.assertIn(bytes((0xA9, 0xF8, 0xA2, 0x00, 0x9D, 0x00, 0x02,
                             0xE8, 0xE8, 0xE8, 0xE8)), self.prg)

    def test_nametable_pages_are_copied_in_four_separate_loops(self):
        # Each loop reloads X=0 and performs exactly one absolute-indexed read
        # followed by $2007 write/INX/BNE. This prevents page interleaving.
        pattern = bytes((0xA2, 0x00, 0xBD))
        starts = []
        offset = 0
        while True:
            offset = self.prg.find(pattern, offset)
            if offset < 0:
                break
            if self.prg[offset + 5:offset + 11] == bytes(
                    (0x8D, 0x07, 0x20, 0xE8, 0xD0, 0xF7)):
                starts.append(offset)
            offset += 1
        self.assertEqual(len(starts), 4)

    def test_control_and_cheat_oracles_are_material_pixels(self):
        # Eight authored control colours and marker positions are embedded.
        self.assertIn(bytes((0x16, 0x2A, 0x28, 0x24,
                             0x30, 0x12, 0x1A, 0x27)), self.prg)
        self.assertIn(bytes((0x18, 0x30, 0x48, 0x60,
                             0x78, 0x90, 0xA8, 0xC0)), self.prg)
        # Read $6000, compare $3F and select red ($16) for the edge marker.
        self.assertIn(bytes((0xAD, 0x00, 0x60, 0xC9, 0x3F)), self.prg)
        self.assertIn(bytes((0xA9, 0x16)), self.prg)

    def test_chr_has_solid_interior_border_and_motion_glyphs(self):
        def tile(index):
            start = index * 16
            return self.chr[start:start + 16]

        self.assertEqual(tile(0), bytes((0xF0,) * 8 + (0x0F,) * 8))
        self.assertEqual(tile(1), bytes((0x00,) * 8 + (0xFF,) * 8))
        self.assertNotEqual(tile(2), bytes(16))
        self.assertEqual(len({tile(index) for index in range(3, 7)}), 4)
        self.assertEqual(tile(8), bytes((0x0F,) * 8 + (0xF0,) * 8))
        self.assertEqual(len({tile(index) for index in range(9, 17)}), 8)

    def test_all_scroll_phases_change_the_generator_signature_lattice(self):
        # Recover the emitted nametable through its authored 1024-byte suffix:
        # the tile-index field has a unique deterministic prefix.
        expected = bytearray(1024)
        for row in range(30):
            for column in range(32):
                expected[row * 32 + column] = (
                    1 if row in {0, 29} or column in {0, 31}
                    else 9 + ((row * 17 + column * 29 + row * column * 7 +
                               (column >> 1) * 3) % 8)
                )
        offset = self.prg.find(bytes(expected))
        self.assertGreater(offset, 0)

        def pixel(source_x, source_y, scroll):
            x = (source_x + scroll) % 256
            tile_index = expected[(source_y // 8) * 32 + x // 8]
            tile_start = tile_index * 16
            shift = 7 - (x % 8)
            low = (self.chr[tile_start + source_y % 8] >> shift) & 1
            high = (self.chr[tile_start + 8 + source_y % 8] >> shift) & 1
            return low | (high << 1)

        signatures = []
        for scroll in range(8):
            signatures.append(tuple(
                pixel(8 + column * 16, 13 + row * 26, scroll)
                for row in range(9) for column in range(16)
            ))
        self.assertEqual(len(set(signatures)), 8)
        self.assertTrue(all(left != right for left, right in
                            zip(signatures, signatures[1:])))

    def test_generator_declares_fail_closed_qualification_contract(self):
        source = GENERATOR.read_text(encoding="utf-8")
        for token in (
            '"profile": "emufusion-nes-v1"',
            '"width": 256, "height": 240',
            '"frequencyHzApprox": 440.4',
            "Select+Up=60, Select+Right=50, Select+Down=40, Select+Left=30",
            '"uniqueFramesPerPeriod": 5',
            '"clockSource": "native NES NMI; no host or timestamp override"',
            '"semanticAction": "toggle-motion-freeze"',
            '"code": "6000:3F"',
            '"visibleEffect": "border white-to-red"',
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
