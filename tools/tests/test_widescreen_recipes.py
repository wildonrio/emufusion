"""The Widescreen Hack's per-game table and the plumbing it depends on."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECIPES = json.loads((ROOT / 'engines/widescreen/widescreen-recipes.json').read_text())
GAME = ROOT / 'unified-android/src/com/thorium/preview/game'
TOP20 = json.loads((ROOT / 'docs/widescreen/top20-by-critic.json').read_text())
STRATEGIES = {'widen', 'fixed-screen', 'already-native', 'untested'}


def normalize(title):
    """TitleMatcher.normalize for the titles in this table, enough to test the keys."""
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', title.lower())).strip()


class RecipeTableTest(unittest.TestCase):
    def test_every_system_declares_how_to_widen(self):
        for name, system in RECIPES['systems'].items():
            for field in ('engine', 'widthOption', 'baseWidth', 'height', 'pixelAspect', 'games'):
                self.assertIn(field, system, name)
            self.assertGreater(system['pixelAspect'], 0.5)

    def test_every_game_has_a_known_strategy_and_evidence(self):
        for name, system in RECIPES['systems'].items():
            for title, game in system['games'].items():
                self.assertIn(game['strategy'], STRATEGIES, title)
                self.assertTrue(game.get('tested'), f'{title}: no test evidence')
                for key, value in game.get('options', {}).items():
                    self.assertIsInstance(value, str, f'{title}: {key}')
                    self.assertLessEqual(len(value), 1023, f'{title}: {key} exceeds the override file')

    def test_games_are_keyed_by_the_metadata_title(self):
        for name, system in RECIPES['systems'].items():
            known = {normalize(row['title']) for row in TOP20.get(name, [])}
            for title in system['games']:
                # A game outside the top 20 is allowed; a typo in a top-20 title is not.
                if normalize(title) not in known:
                    self.assertNotIn(normalize(title).rstrip('s'),
                                     {k.rstrip('s') for k in known}, title)

    def test_scene_and_hud_rules_parse(self):
        scene_term = re.compile(r'^(bgmode|[0-9A-F]{4,6}(/[0-9A-F]{2})?)!?=[0-9A-F]+$')
        hud_rule = re.compile(r'^(bg[1-4]|obj):\d+-\d+:-?\d+-\d+:-?1(:[0-9a-fA-F]+-[0-9a-fA-F]+)?$')
        for system in RECIPES['systems'].values():
            for title, game in system['games'].items():
                options = game.get('options', {})
                for term in re.split(r'[,|]', options.get('emufusion_ws_scene', '')):
                    if term:
                        self.assertRegex(term, scene_term, title)
                for rule in filter(None, options.get('emufusion_ws_hud', '').split(';')):
                    self.assertRegex(rule, hud_rule, title)


class PlumbingTest(unittest.TestCase):
    def test_aspect_is_reread_after_a_width_change(self):
        session = (GAME / 'LibretroEngineSession.java').read_text()
        self.assertIn('widescreenAspectChecks = newest.width != widescreenFrameWidth', session)

    def test_a_game_gear_cart_in_master_system_mode_is_never_offered_widening(self):
        self.assertTrue(RECIPES['systems']['gamegear']['exactBase'])
        recipes = (GAME / 'WidescreenRecipes.java').read_text()
        self.assertIn('return !exactBase || (coreWidth == baseWidth && coreHeight == height);', recipes)
        session = (GAME / 'LibretroEngineSession.java').read_text()
        self.assertIn('widescreenRecipe.fitsCore(av.baseWidth, av.baseHeight)', session)

    def test_a_system_reaches_players_only_after_a_device_pass(self):
        recipes = (GAME / 'WidescreenRecipes.java').read_text()
        self.assertIn('if (!entry.optBoolean("release", false) && !qaAll) continue;', recipes)
        self.assertIn('"emufusion_qa_widescreen_all"', recipes)

    def test_host_reports_live_option_changes_to_the_core(self):
        host = (ROOT / 'unified-android/native/emufusion_libretro_host.c').read_text()
        self.assertIn('*(bool *)data = active_host->core_variables_updated;', host)
        self.assertIn('host->core_variables_updated = true;', host)
        self.assertIn('strncmp(key, "emufusion_", 10) == 0', host)

    def test_alternate_engine_never_becomes_the_system_default(self):
        catalog = (GAME / 'InternalEngineCatalog.java').read_text()
        self.assertIn('if (row.optBoolean("alternateEngine", false)) continue;', catalog)
        registry = json.loads((ROOT / 'engines/registry.json').read_text())
        rows = {row['id']: row for row in registry['engines']}
        self.assertTrue(rows['bsnes-hd']['alternateEngine'])
        self.assertFalse(rows['mesen-s'].get('alternateEngine', False))

    def test_game_starts_narrow_and_session_applies_width_before_each_frame(self):
        policy = (GAME / 'WidescreenHackPolicy.java').read_text()
        self.assertIn('overrides.put(recipe.widthOption, "0");', policy)
        session = (GAME / 'LibretroEngineSession.java').read_text()
        apply = session.index('widen.applyBeforeFrame(active, surfaceWidth, surfaceHeight);')
        self.assertLess(apply, session.index('active.runFrame();', apply))
        self.assertIn('displayAspect = aspect;', session)

    def test_overlay_never_claims_touches_outside_the_bars_and_edges(self):
        overlay = (GAME / 'WidescreenOverlayView.java').read_text()
        self.assertIn('following = session.isEnabled() ? atEdge :', overlay)
        self.assertIn('inBar(downX) && (!touchControlsShown || promptShowing());', overlay)
        self.assertIn('setSystemGestureExclusionRects(edges);', overlay)

    def test_save_of_another_size_is_carried_across_and_kept(self):
        session = (GAME / 'LibretroEngineSession.java').read_text()
        self.assertIn('if (attempt == 3 && carrySaveRamAcrossEngines(active, file, value, current)) return;', session)
        self.assertIn('if (!original.exists()) DurableBlobStore.write(original, value, MAX_SAVE_RAM_BYTES);', session)

    def test_saves_are_keyed_by_rom_so_engine_changes_keep_them(self):
        session = (GAME / 'LibretroEngineSession.java').read_text()
        self.assertIn('saveRoot + "/" + storageKey(romSha));', session)
        self.assertIn('saveRamFile = new File(saves, "save-ram.bin");', session)


if __name__ == '__main__':
    unittest.main()
