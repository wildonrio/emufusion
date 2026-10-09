"""Cheats reach every engine, and every engine's session can switch them.

Before 2026-09-06 only the two libretro session classes listed cheats, and
only for the cores whose ``retro_cheat_set`` is real. The delivery layer
(``unified-android/src/com/thorium/preview/cheats/delivery``) adds the rest:

* ``EngineSession``'s default ``availableCheats / enabledCheatIds /
  setCheatEnabled`` consult ``CheatSessionRegistry`` instead of answering a
  constant, so the pause-menu "Cheats" button lights up for the native
  adapters and the vulkan-libretro runtime too. A session with its own
  override (the live path) is untouched: the registry is only reached
  through the defaults.
* ``InternalEngineBootstrap`` wraps each of its three factory lambdas in
  ``CheatLaunchHooks.prepare`` so the boot writers run and the registry is
  filled before the session is handed to the host.
* ``CheatCatalog.forGame`` merges the per-game downloaded file before the
  user override and parses the bundled asset once per process.
* ``CheatControl.listJson`` says where each row came from and how it is
  delivered, without renaming the fields the theme already reads.

These are text pins because none of it can run without an Android runtime;
the writers and the registry themselves are proven by the host tests in
``unified-android/test/com/thorium/preview/cheats/delivery``.
"""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UNIFIED = ROOT / "unified-android"
SRC = UNIFIED / "src" / "com" / "thorium"
DELIVERY = SRC / "preview" / "cheats" / "delivery"
ENGINE_SESSION = SRC / "preview" / "game" / "EngineSession.java"
BOOTSTRAP = SRC / "preview" / "game" / "InternalEngineBootstrap.java"
CATALOG = SRC / "preview" / "cheats" / "CheatCatalog.java"
CONTROL = SRC / "preview" / "cheats" / "CheatControl.java"
SOFTWARE = SRC / "preview" / "game" / "LibretroEngineSession.java"
HARDWARE = SRC / "preview" / "game" / "PpssppGlesEngineSession.java"
TEST_RUNNER = UNIFIED / "test.sh"
HOST_TESTS = UNIFIED / "test" / "com" / "thorium" / "preview" / "cheats" / "delivery"

WRITERS = {
    "dolphin": "DolphinGameSettingsWriter",
    "ppsspp": "PpssppCheatWriter",
    "armsx2": "Pcsx2PnachWriter",
    "azahar": "AzaharCheatWriter",
    "eden": "EdenCheatWriter",
    "aps3e": "Aps3ePatchWriter",
    "cemu": "CemuGraphicPackWriter",
    "flycast": "FlycastCheatWriter",
}


def body(source: str, start: str, end: str) -> str:
    assert start in source, f"missing anchor {start!r}"
    remainder = source.split(start, 1)[1]
    assert end in remainder, f"missing anchor {end!r} after {start!r}"
    return remainder.split(end, 1)[0]


def string_literals(text: str) -> set:
    return set(re.findall(r'"([^"]+)"', text))


class EngineSessionDefaultTests(unittest.TestCase):
    """The interface defaults, and only the defaults, reach the registry."""

    def setUp(self):
        self.source = ENGINE_SESSION.read_text(encoding="utf-8")

    def test_the_three_defaults_consult_the_registry(self):
        available = body(self.source, "default List<Cheat> availableCheats()", "default Set<String> enabledCheatIds()")
        enabled = body(self.source, "default Set<String> enabledCheatIds()", "default boolean setCheatEnabled(")
        toggle = body(self.source, "default boolean setCheatEnabled(", "\n    }")
        self.assertIn("CheatSessionRegistry.availableCheats(this)", available)
        self.assertIn("CheatSessionRegistry.enabledCheatIds(this)", enabled)
        self.assertIn("return CheatSessionRegistry.setCheatEnabled(this, cheatId, enabled)", toggle)

    def test_the_defaults_still_fail_closed(self):
        available = body(self.source, "default List<Cheat> availableCheats()", "default Set<String> enabledCheatIds()")
        enabled = body(self.source, "default Set<String> enabledCheatIds()", "default boolean setCheatEnabled(")
        self.assertIn("Collections.<Cheat>emptyList()", available)
        self.assertIn("Collections.<String>emptySet()", enabled)

    def test_the_live_sessions_keep_their_own_overrides(self):
        # The registry must never shadow a session's own live path.
        for session in (SOFTWARE, HARDWARE):
            text = session.read_text(encoding="utf-8")
            for method in ("availableCheats()", "enabledCheatIds()", "setCheatEnabled(String cheatId, boolean enabled)"):
                self.assertIn(f"@Override public java.util.List<Cheat> {method}" if method == "availableCheats()"
                              else f"@Override public java.util.Set<String> {method}" if method == "enabledCheatIds()"
                              else f"@Override public boolean {method}", text,
                              f"{session.name} lost its own {method}")
            self.assertNotIn("CheatSessionRegistry", text,
                             f"{session.name} must not route through the registry")


class BootstrapWrapTests(unittest.TestCase):
    def test_every_factory_is_wrapped_exactly_once(self):
        source = BOOTSTRAP.read_text(encoding="utf-8")
        wraps = source.count("CheatLaunchHooks.prepare(sessionContext, request, entry.id,")
        registrations = source.count("EngineSessionRegistry.register(entry.id,")
        self.assertEqual(3, registrations)
        self.assertEqual(registrations, wraps,
                         "each registered factory must hand its session through CheatLaunchHooks.prepare")
        self.assertIn("import com.thorium.preview.cheats.delivery.CheatLaunchHooks;", source)

    def test_the_hook_returns_the_same_session_and_never_throws(self):
        hooks = (DELIVERY / "CheatLaunchHooks.java").read_text(encoding="utf-8")
        prepare = body(hooks, "public static EngineSession prepare(", "\n    }\n")
        self.assertIn("return session;", prepare)
        self.assertIn("catch (Throwable failure)", prepare)
        # The factory runs on the UI thread: the catalogue work must not.
        self.assertIn('new Thread(', prepare)
        self.assertIn('"lucent-cheat-prepare"', prepare)
        # 2026-09-06 review fix: the 3-arg overload always left
        # perGameWidescreenCodeSelected false, so Dolphin's generic
        # projection hack and a per-game 16:9 code the widescreen-by-cheat
        # pick had just enabled were applied together (design section 7's
        # "else" broken). The catalogue resolution and the widescreen pick
        # now run synchronously in prepare() (a store read plus a small
        # write, not the archive scan) precisely so this call can pass the
        # real decision through the 4-arg overload instead of guessing false
        # and correcting later.
        self.assertIn("WidescreenHackPolicy.prepareLaunch(app, request, engine, perGameWidescreenCodeSelected)",
                       prepare)
        self.assertNotIn("WidescreenHackPolicy.prepareLaunch(app, request, engine);", prepare)


class CatalogMergeTests(unittest.TestCase):
    def setUp(self):
        self.source = CATALOG.read_text(encoding="utf-8")

    def test_downloaded_rows_merge_before_the_user_override(self):
        for_game = body(self.source, "String contentName, String contentIdentity) {", "private static List<Cheat> deduplicate")
        archive = for_game.index("CheatArchive.forGame(")
        downloaded = for_game.index("downloadedFor(context, canonical, title, contentName)")
        override = for_game.index("new File(userDirectory, USER_FILE)")
        self.assertLess(archive, downloaded)
        self.assertLess(downloaded, override)

    def test_the_stem_is_tried_when_the_title_misses(self):
        helper = body(self.source, "private static List<Cheat> downloadedFor(", "static void merge(")
        self.assertIn("DownloadedCheatFile.pathFor(", helper)
        self.assertIn("rows.isEmpty() && contentName != null", helper)
        self.assertIn("catch (RuntimeException unreadable)", helper)

    def test_the_bundled_asset_is_parsed_once_per_process(self):
        self.assertEqual(1, self.source.count("readAsset(context, BUNDLED_ASSET)"),
                         "only the cache may read the bundled asset")
        self.assertIn("private static volatile Map<CheatDatabase.GameId, List<Cheat>> bundledCache;", self.source)
        self.assertIn("bundled(context)", body(self.source, "public static CheatDatabase load(", "}"))
        self.assertIn("bundled(context)", body(self.source, "String contentName, String contentIdentity) {", "deduplicate(aggregate)"))


class ControlListTests(unittest.TestCase):
    def test_list_json_adds_source_and_delivery_without_renaming_fields(self):
        source = CONTROL.read_text(encoding="utf-8")
        listing = body(source, "public static String listJson(", "public static boolean setEnabled(")
        for field in ("id", "name", "description", "enabled", "source", "delivery"):
            self.assertIn(f'item.put("{field}"', listing)
        for field in ("ok", "system", "title", "count", "cheats"):
            self.assertIn(f'response.put("{field}"', listing)

    def test_game_cheats_resolve_delivery_for_the_engine(self):
        source = CONTROL.read_text(encoding="utf-8")
        self.assertIn("public static GameCheats gameCheatsFor(", source)
        self.assertIn("CheatDelivery.resolve(engineId, row == null ? \"\" : row.delivery)", source)


class DeliveryPolicyTests(unittest.TestCase):
    def test_live_engines_match_the_two_sessions(self):
        policy = (DELIVERY / "CheatDelivery.java").read_text(encoding="utf-8")
        live = string_literals(body(policy, "LIVE_ENGINES = new HashSet<>(Arrays.asList(", "));"))
        software = string_literals(body(SOFTWARE.read_text(encoding="utf-8"),
                                        "private static boolean supportsLiveCheats(String engineId)", "\n    }"))
        hardware = string_literals(body(HARDWARE.read_text(encoding="utf-8"),
                                        "private static boolean supportsLiveCheats(String engineId)", "\n    }"))
        self.assertEqual(software | hardware, live,
                         "CheatDelivery.LIVE_ENGINES must mirror both supportsLiveCheats lists")

    def test_every_boot_engine_has_its_writer(self):
        table = (DELIVERY / "BootCheatWriters.java").read_text(encoding="utf-8")
        policy = (DELIVERY / "CheatDelivery.java").read_text(encoding="utf-8")
        boot = string_literals(body(policy, "BOOT_ENGINES = new HashSet<>(Arrays.asList(", "));"))
        # flycast keeps a writer but is not a boot engine: the pinned core
        # compiles its .cht loading out under LIBRETRO, so its rows stay honest.
        self.assertEqual(set(WRITERS) - {"flycast"}, boot)
        self.assertIn("#ifndef LIBRETRO", policy)
        for engine, writer in WRITERS.items():
            self.assertIn(f'case "{engine}": return new {writer}();', table)
            self.assertTrue((DELIVERY / f"{writer}.java").is_file(), writer)
            self.assertIn("implements BootCheatWriter", (DELIVERY / f"{writer}.java").read_text(encoding="utf-8"))

    def test_boot_rows_say_when_they_apply(self):
        row = (DELIVERY / "DeliveryCheat.java").read_text(encoding="utf-8")
        self.assertIn('BOOT_NOTE = "applies on next launch"', row)
        # Same words as the downloader's own annotation, so nothing is said twice.
        codec = SRC / "preview" / "cheats" / "sources" / "DownloadedCheatCodec.java"
        if codec.is_file():
            self.assertIn('BOOT_NOTE = "applies on next launch"', codec.read_text(encoding="utf-8"))

    def test_writers_stay_host_testable(self):
        # The host suite compiles the delivery package minus its three Android
        # files; nothing else in it may import Android or org.json.
        android_only = {"CheatLaunchHooks.java", "EngineRoots.java", "WidescreenCheatOverlay.java"}
        for path in DELIVERY.glob("*.java"):
            text = path.read_text(encoding="utf-8")
            if path.name in android_only:
                continue
            self.assertNotIn("import android.", text, path.name)
            self.assertNotIn("import org.json.", text, path.name)

    def test_every_writer_writes_atomically_through_owned_files(self):
        for writer in WRITERS.values():
            text = (DELIVERY / f"{writer}.java").read_text(encoding="utf-8")
            self.assertIn("OwnedFiles.write(", text, writer)
            self.assertNotIn("new FileWriter(", text, writer)
        owned = (DELIVERY / "OwnedFiles.java").read_text(encoding="utf-8")
        self.assertIn('".part"', owned)
        self.assertIn("getFD().sync()", owned)
        self.assertIn("MAX_BYTES = 4 * 1024 * 1024", owned)


class HostSuiteTests(unittest.TestCase):
    def test_the_host_runner_compiles_and_runs_the_delivery_tests(self):
        runner = TEST_RUNNER.read_text(encoding="utf-8")
        self.assertTrue((HOST_TESTS / "BootCheatWritersTest.java").is_file())
        self.assertTrue((HOST_TESTS / "CheatSessionRegistryTest.java").is_file())
        self.assertIn("preview/cheats/delivery", runner,
                      "test.sh must add the delivery package (minus its Android files) to SOURCES")
        self.assertIn("com.thorium.preview.cheats.delivery.BootCheatWritersTest", runner)
        self.assertIn("com.thorium.preview.cheats.delivery.CheatSessionRegistryTest", runner)


if __name__ == "__main__":
    unittest.main()
