import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FIXTURES = load("phase1a_fixtures", ROOT / "engines" / "qa" / "generate_fixtures.py")
RUNNER = load("phase1a_runner", ROOT / "engines" / "qa" / "run_phase1a_qa.py")


class Phase1AQATest(unittest.TestCase):
    def test_matrix_has_exact_system_set(self):
        self.assertEqual(
            {
                "nes", "snes", "gb", "gbc", "gba", "sg1000", "mastersystem",
                "gamegear", "colecovision", "intellivision", "psx", "nds",
                "zxspectrum", "arcade", "neogeo", "neogeocd", "dos", "windows",
                "pcengine", "pcenginecd", "ngp", "wonderswancolor",
                "amstradcpc", "atari2600", "atari5200", "atari7800",
                "atari800", "atarist", "c64", "megadrive", "msx", "n64",
                "odyssey2", "sega32x", "segacd", "virtualboy",
            },
            {case.system for case in RUNNER.CASES},
        )

    def test_every_case_is_runnable_or_has_a_blocker(self):
        for case in RUNNER.CASES:
            with self.subTest(system=case.system):
                self.assertTrue(
                    bool(case.blocked_reason)
                    or (case.core is not None and case.fixture is not None)
                )

    def test_matrix_exactly_covers_the_registry_without_duplicate_systems(self):
        import json

        registry = json.loads(
            (ROOT / "engines" / "registry.json").read_text(encoding="utf-8")
        )
        registry_systems = {
            system for engine in registry["engines"] for system in engine["systems"]
        }
        qa_systems = [case.system for case in RUNNER.CASES]
        self.assertEqual(registry_systems, set(qa_systems))
        self.assertEqual(len(qa_systems), len(set(qa_systems)))

    def test_every_runnable_case_requires_hundred_state_cycles(self):
        for case in RUNNER.CASES:
            if case.core is not None and case.blocked_reason is None:
                with self.subTest(system=case.system):
                    self.assertEqual(100, case.state_cycles)

    def test_generated_fixtures_are_deterministic(self):
        expected = {
            "nes": (FIXTURES.make_nes(), "42019e9ca4a3a11815a9e13b7c60734a73fb7ae3cb06a140915daa4605ee8508"),
            "snes": (FIXTURES.make_snes(), "e841dcdca175a4473b8d5db9c59f48f7291e3974f89917aa136ba137e5c14cbc"),
            "sg1000": (FIXTURES.make_sega(None), "2b98b5c06119e72b24bb35c7bb576babc1da495416389bccfd014e0e2de93e24"),
            "mastersystem": (FIXTURES.make_sega(0x4C), "772ff72c94820cb1efb792ede85ce105d5cf0867deba644d4d094f9c97f37fd9"),
            "gamegear": (FIXTURES.make_sega(0x6C), "0a5565580bb8713d512a5f14e2de42d8559d9a789908edc9bceb2d12b0d9d10d"),
            "colecovision": (FIXTURES.make_colecovision(), "b1957ab50ca1a1710a11f705db535e749e3c95167ca10980deae4031f204ae7c"),
            "psx": (FIXTURES.make_psx(), "5f0688ab0120fd2b5f26466d2805981ed33ceef42a67a7afc5bf711e68498460"),
            "zxspectrum": (FIXTURES.make_zx_spectrum(), "80e5788ca68ad3177dd0240a6eee28be1bc2d96f8615dc9e3dc0f3c5fa735f9a"),
            "arcade": (FIXTURES.make_mame_command(), "5a6a28fc1600ea141d7b39125822c1d51fb166abe5628e7fc1f99a9b02f5d52c"),
            "neogeo": (FIXTURES.make_neogeo_command(), "c2d676acb9d32f56daa26797caaebea84f07382791aeccfea35363972e26194c"),
            "dos": (FIXTURES.make_dos_zip(), "cc80753646f0ab9ea27f0a65f7401fc94f651b05d0c4fe02ecd5d8cca32aa537"),
        }
        for system, (payload, digest) in expected.items():
            with self.subTest(system=system):
                self.assertEqual(digest, hashlib.sha256(payload).hexdigest())

    def test_firmware_gated_systems_cannot_be_generic_passes(self):
        gated = {
            case.system: case for case in RUNNER.CASES
            if case.system in {"colecovision", "intellivision"}
        }
        self.assertEqual({"colecovision", "intellivision"}, set(gated))
        coleco = next(case for case in RUNNER.CASES if case.system == "colecovision")
        self.assertEqual((), coleco.firmware)

    def test_melonds_uses_hundred_state_cycles(self):
        nds = next(case for case in RUNNER.CASES if case.system == "nds")
        self.assertEqual("melonds-ds", nds.core)
        self.assertEqual("melonds-homebrew-periph-slot2.nds", nds.fixture)
        self.assertEqual(100, nds.state_cycles)
        generator = (ROOT / "engines" / "qa" / "generate_fixtures.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "4eaf6d5b0450b9a658273cccead71f432f6c191b75e7066fc7201b0ce5d0285b",
            generator,
        )

    def test_melonds_recipe_pins_complete_offline_source_closure(self):
        recipe = (ROOT / "engines" / "build_core.sh").read_text(encoding="utf-8")
        hashes = {
            "502d33556397836b32c2b81d0ef066558710eb1e22758d53c3463a63b91796a5",
            "99332b46d4b69b17ba8a0f9c508c0292987056e367a91657e24ae8c1f74938e4",
            "967fc5680bda0c9411a34509a5b4bf289cc2af1263edc0ef41fd2f1226668c1b",
            "3b1017d10077de692e19c3772d824010705533ec441583587fac4a959ae77bd5",
            "2111416bc7cf67aeac54d4eeb0fd68109ac20b97df7bf860114bf18679e8467e",
            "2269005f612868c31027ea992bd88f0f7c89c69e7f2eef495479cb2a2f9e2ed3",
            "0980b1f0b2dc74b77be3e956834ffce2876b02043c52fb8d8bb51c4ec4a6f6b4",
            "f94052c10b611fd374194ca6e0dc4d159459c0b370abfe9002c13058863b7039",
            "f322d79bfd7dda607c69c867a1cc57192173f02d973e6c9bae02c3ad984c114e",
            "0d98623e0a6ee6bbc84b9dee049c3ddfeb8fb4cfe3ad21cae598c5869deb2b82",
            "8b4096b7b49e06d756f4aa0949151863ab7b812679a1646039fab6e821d3c049",
            "d9e270d46252734aa49770fbc544125391617956266f220bd63216c834f3a522",
        }
        for digest in hashes:
            self.assertIn(digest, recipe)
        self.assertIn("-DFETCHCONTENT_FULLY_DISCONNECTED=ON", recipe)

    def test_mame_arcade_uses_romless_fixture_and_hundred_state_cycles(self):
        arcade = next(case for case in RUNNER.CASES if case.system == "arcade")
        self.assertEqual("mame", arcade.core)
        self.assertEqual("pong.cmd", arcade.fixture)
        self.assertIsNone(arcade.blocked_reason)
        self.assertEqual(100, arcade.state_cycles)
        self.assertEqual(b"pong\n", FIXTURES.make_mame_command())

        recipe = (ROOT / "engines" / "build_core.sh").read_text(encoding="utf-8")
        self.assertIn(
            "938efbe6bdd2d6e54fad7d9d53e93e9b09a0a708243e5929c286f21b1438833f",
            recipe,
        )
        self.assertIn("src/mame/atari/pong.cpp", recipe)
        self.assertIn("src/mame/snk/neogeo.cpp", recipe)
        self.assertIn("src/mame/snk/neogeocd.cpp", recipe)

        neo_geo = next(case for case in RUNNER.CASES if case.system == "neogeo")
        self.assertEqual("mame", neo_geo.core)
        self.assertEqual("ngdevkit-open.cmd", neo_geo.fixture)
        self.assertIsNone(neo_geo.blocked_reason)
        self.assertEqual(100, neo_geo.state_cycles)

        blocked = {
            case.system: case for case in RUNNER.CASES
            if case.system == "neogeocd"
        }
        self.assertEqual({"neogeocd"}, set(blocked))
        for case in blocked.values():
            self.assertIsNone(case.core)
            self.assertIsNone(case.fixture)
            self.assertIn("user-supplied", case.blocked_reason)

    def test_neogeo_fixture_builder_pins_only_open_inputs(self):
        builder = (ROOT / "engines" / "qa" / "build_neogeo_open_fixture.py").read_text(
            encoding="utf-8"
        )
        for value in (
            "b36a345dd65097040d48933408586e0a9d7c764b",
            "1099364b1661ad390cac5d8a7af8e51c09dcf690c2f8fd99afee4917a9ae6ac0",
            "60f1bd113471ade1a1850e0dca945cffeef38231",
            "4855effd60ecf57124c03eb76d12acb14f891b9544821fe2af7021bd73c60b7f",
            "c9412cfd819b18b57c6c02d360b652ebe9a0fad80225ac3f30c376205c54516f",
            "9c39bb9391f10974361c0383a4811a94fa2fe8a3b619294f4bfa019b7d82cca4",
        ):
            self.assertIn(value, builder)
        self.assertIn("proprietary substitutes are forbidden", builder)

    def test_mame_build_reuses_only_exact_qualified_artifact(self):
        recipe = (ROOT / "engines" / "build_core.sh").read_text(encoding="utf-8")
        for value in (
            "1160d48a52f0271e3a83bb57498fe5f86069336be6eb175be9d3842795fc0d07",
            "1c4a54b31c5ed242a901b4a472d412819b5e08405df1c58066bd555f9dd52515",
            "08e3e6f9e21ea6ec1c9d9b0882f576a9abb03aa5aeeeefb3ad8bc4a3f13d96de",
            "LUCENT_FORCE_REBUILD",
            "recipeRevision=3",
            "elfMaxPageSize=16384",
            "elfCommonPageSize=16384",
        ):
            self.assertIn(value, recipe)

    def test_probe_rejects_single_visible_startup_frame(self):
        probe = (ROOT / "engines" / "qa" / "libretro_probe.c").read_text(
            encoding="utf-8"
        )
        self.assertIn("g_video_nonzero_callbacks * 10", probe)
        self.assertIn("g_video_callbacks * 9", probe)

    def test_new_mednafen_fixtures_are_pinned_and_require_real_input_effect(self):
        cases = {
            case.system: case for case in RUNNER.CASES
            if case.system in {"pcengine", "ngp", "wonderswancolor"}
        }
        self.assertEqual({"pcengine", "ngp", "wonderswancolor"}, set(cases))
        self.assertTrue(all(case.require_input_effect for case in cases.values()))
        builder = (ROOT / "engines" / "qa" /
                   "build_open_newcore_fixtures.py").read_text(encoding="utf-8")
        for digest in (
            "bf15e23d6a20235717db494af91dcab4d557b83aa2573ed4d278f5e45c576be6",
            "089e2d9520dc2f84d34a33b1dfa1710eb9a429d90b3b0a195a06ccab89c9022f",
            "ccacf10e9734630ad4f9a5b2301dcc3aca7b06a0e92771d92d95a2ced0487d21",
            "1915cf1ce467a726163618007e6c7a87ae8c8a5f7c8f7651640c4e90a941ed78",
        ):
            self.assertIn(digest, builder)
        probe = (ROOT / "engines" / "qa" / "libretro_probe.c").read_text(
            encoding="utf-8"
        )
        self.assertIn('getenv("LUCENT_PROBE_REQUIRE_INPUT_EFFECT")', probe)
        self.assertIn("inputEffectRequired", probe)

    def test_playstation_uses_built_swanstation_and_legal_fixture(self):
        case = next(case for case in RUNNER.CASES if case.system == "psx")
        self.assertEqual("swanstation", case.core)
        self.assertEqual("lucent-callback-test.psexe", case.fixture)
        self.assertIsNone(case.blocked_reason)
        build_script = (ROOT / "engines" / "build_core.sh").read_text(encoding="utf-8")
        self.assertIn("df747c49b9038499b8d8762cd2662f0b8c128ee3999b74b19979e5ab20dd622d", build_script)


if __name__ == "__main__":
    unittest.main()
