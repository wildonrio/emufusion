"""Structural guards for the shipped cheat catalogue.

The catalogue is data, and it is meant to grow. Every rule here is one the
running app already assumes but cannot report: `CheatCatalog.merge` replaces a
game wholesale on its (system, title) key, so a duplicated key silently drops
the earlier entry's cheats; `Cheat`'s constructor throws on an empty id or code
and the parser answers by skipping that cheat with only a log line; and the
selection is stored by id, so two rows sharing an id in one game would toggle
each other.

None of those fail loudly on a device. They fail as a cheat that is simply not
in the list.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "engines" / "cheats" / "cheat-database.json"
BUILD = ROOT / "unified-android" / "build.sh"
CATALOG = (ROOT / "unified-android" / "src" / "com" / "thorium" / "preview"
           / "cheats" / "CheatCatalog.java")


def normalise(title: str) -> str:
    """Mirrors CheatDatabase.normalise closely enough to catch a collision."""
    without_tags = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", title)
    return re.sub(r"[^a-z0-9]+", "", without_tags.lower())


class CheatDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(DATABASE.read_text(encoding="utf-8"))

    def test_it_declares_the_schema_the_parser_reads(self):
        self.assertEqual(1, self.data["schemaVersion"])
        self.assertIsInstance(self.data["games"], list)
        self.assertGreater(len(self.data["games"]), 0)

    def test_every_game_is_addressable_and_carries_cheats(self):
        for game in self.data["games"]:
            self.assertTrue(game.get("system", "").strip(),
                            f"a game with no system is unreachable: {game}")
            self.assertTrue(game.get("title", "").strip(),
                            f"a game with no title is unreachable: {game}")
            self.assertGreater(len(game.get("cheats", [])), 0,
                               f"{game.get('title')} has an empty cheat list")

    def test_no_two_entries_claim_the_same_game(self):
        # The parser's put() replaces wholesale, so the second entry would win
        # and the first one's cheats would never appear anywhere.
        seen = {}
        for game in self.data["games"]:
            key = (game["system"].strip().lower(), normalise(game["title"]))
            self.assertNotIn(key, seen,
                             f"{game['title']} on {game['system']} is listed twice")
            seen[key] = True

    def test_every_cheat_would_survive_the_model(self):
        for game in self.data["games"]:
            ids = set()
            for cheat in game["cheats"]:
                where = f"{game['title']}/{cheat.get('id')}"
                # Cheat's constructor throws on either of these, and the
                # parser's answer is to skip the row in silence.
                self.assertTrue(cheat.get("id", "").strip(), f"{where}: id required")
                self.assertTrue(cheat.get("code", "").strip(), f"{where}: code required")
                self.assertTrue(cheat.get("name", "").strip(),
                                f"{where}: a nameless row reads as its id")
                self.assertNotIn(cheat["id"], ids,
                                 f"{where}: two rows sharing an id toggle each other")
                ids.add(cheat["id"])

    def test_multi_line_codes_use_the_separator_the_cores_parse(self):
        for game in self.data["games"]:
            for cheat in game["cheats"]:
                code = cheat["code"]
                self.assertNotIn("\n", code,
                                 f"{cheat['id']}: join lines with '+', not a newline")
                self.assertEqual(code, code.strip(),
                                 f"{cheat['id']}: a padded code is passed on verbatim")
        self.assertIn("'+' joining the lines", self.data["note"],
                      "the file has to state its own code convention")

    def test_nes_qualification_cheat_is_discoverable_through_the_normal_catalog(self):
        matches = [game for game in self.data["games"]
                   if game["system"] == "nes" and
                   normalise(game["title"]) == normalise("Lucent Callback Test")]
        self.assertEqual(1, len(matches),
                         "the physical QA ROM must use the same title lookup as users")
        cheats = matches[0]["cheats"]
        self.assertEqual(["6000:3F"], [cheat["code"] for cheat in cheats])
        self.assertIn(
            "42019e9ca4a3a11815a9e13b7c60734a73fb7ae3cb06a140915daa4605ee8508",
            cheats[0]["description"],
            "the title-only model needs an explicit exact-ROM guard in the visible row",
        )

    def test_the_catalogue_is_packaged_where_the_loader_looks_for_it(self):
        build = BUILD.read_text(encoding="utf-8")
        self.assertIn('cp "$ROOT_DIR/engines/cheats/cheat-database.json" '
                      '"$DECODED/assets/cheats/"', build,
                      "an expanded catalogue that is never copied ships stale")
        self.assertIn('BUNDLED_ASSET = "cheats/cheat-database.json"',
                      CATALOG.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
