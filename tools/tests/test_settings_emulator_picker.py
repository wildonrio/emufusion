"""Settings' per-system Internal/External emulator picker.

The routing *rule* is covered by test_external_emulator_routing.py. This module
covers the surface the user actually operates:

1. engines/external-emulators.json — the per-system directory of common
   standalone emulators, its schema, and the honesty rules on it (nothing may
   claim to be verified while the file says nothing has been).
2. Drift — every option the directory offers must exist in EmulatorCatalog,
   which owns the launch recipe, and every system the catalog serves must be
   listed. A name that cannot launch is worse than an absent one.
3. Link detection — the Android 11+ package-visibility trap, and the
   <queries> declarations that are the only thing standing between the picker
   and a permanent, silent "nothing is installed".
4. The /route/* HTTP surface the QML settings screen calls.
5. Custom emulators — validated before they are ever stored.
"""

import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMPANION = ROOT / "android-companion" / "src" / "com" / "thorium" / "preview"
LUCENT = ROOT / "unified-android" / "src" / "com" / "thorium" / "lucent" / "emulators"
DIRECTORY_PATH = ROOT / "engines" / "external-emulators.json"
SCHEMA_PATH = ROOT / "engines" / "external-emulators.schema.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


DIRECTORY = json.loads(_read(DIRECTORY_PATH))
CATALOG = _read(COMPANION / "EmulatorCatalog.java")
ROUTE_STORE = _read(COMPANION / "EngineRouteStore.java")
PICKER = _read(COMPANION / "RoutePicker.java")
SERVICE = _read(COMPANION / "PreviewService.java")
IMPORTER = _read(COMPANION / "ImportManager.java")
INSTALLED = _read(COMPANION / "InstalledPackages.java")
CUSTOM_STORE = _read(COMPANION / "CustomEmulatorStore.java")
LOADER = _read(COMPANION / "ExternalEmulatorDirectoryLoader.java")
CUSTOM_SPEC = _read(LUCENT / "CustomEmulatorSpec.java")
MANIFEST = _read(ROOT / "android-companion" / "AndroidManifest.xml")
BUILD = _read(ROOT / "unified-android" / "build.sh")
THEME_INSTALLER = _read(COMPANION / "ThemeInstaller.java")
TEST_SH = _read(ROOT / "unified-android" / "test.sh")
DOC = _read(ROOT / "docs" / "external-emulator-routing.md")

PACKAGE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")


# ---------------------------------------------------------------------------
# A tiny reader for EmulatorCatalog.java's static block.
#
# Regex-scanning Java is normally a smell, but the alternative here is to
# compile the whole Android tree for a data-consistency check, which would make
# the check skip on any machine without the SDK — exactly the machines where a
# stale directory would go unnoticed. The block being read is a fixed, regular
# `put("system", builder(...), ...)` form, and any change that broke this reader
# would fail loudly rather than pass vacuously (test_catalog_reader_sees_the_
# known_shape below is the canary).
# ---------------------------------------------------------------------------

# Java string literals are split across lines with `" +\n "`; rejoin them first
# so a package list stays one token.
_JOINED_CATALOG = re.sub(r'"\s*\+\s*"', "", CATALOG)

RETROARCH_PACKAGES = ["com.retroarch.aarch64", "com.retroarch"]


def _call_arguments(text: str, start: int):
    """The raw argument text of a call whose '(' is at `start`."""
    depth = 0
    in_string = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if character == "\\":
                continue
            if character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    raise AssertionError("unbalanced call in EmulatorCatalog.java")


def _split_top_level(arguments: str):
    parts, depth, in_string, current = [], 0, False, []
    for character in arguments:
        if in_string:
            current.append(character)
            if character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(character)
    if "".join(current).strip():
        parts.append("".join(current))
    return [part.strip() for part in parts]


def _strings(text: str):
    return re.findall(r'"((?:[^"\\]|\\.)*)"', text)


def _option_from_builder(expression: str):
    """(option id, [packages]) for one builder call, or None."""
    match = re.match(r"(emuEx|pathApp|contentUri|retroArch|mdEmu|ps3App)\s*\(", expression)
    if not match:
        return None
    builder = match.group(1)
    arguments = _call_arguments(expression, match.end() - 1)
    literals = _strings(arguments)
    if builder == "mdEmu":
        return "mdemu", ["com.explusalpha.MdEmu"]
    if builder == "ps3App":
        return "aps3e", ["aenu.aps3e"]
    if builder == "retroArch":
        return "retroarch-" + literals[0], list(RETROARCH_PACKAGES)
    # emuEx/pathApp/contentUri all take (id, name, packages, ...).
    return literals[0], literals[2].split()


def parse_catalog():
    """{system: [(option id, [packages])]} and the unsupported system list."""
    block_start = _JOINED_CATALOG.index("static {")
    block = _JOINED_CATALOG[block_start:_JOINED_CATALOG.index("// ---- Option builders")]
    systems = {}
    for match in re.finditer(r"\bput\s*\(", block):
        arguments = _call_arguments(block, match.end() - 1)
        parts = _split_top_level(arguments)
        system = _strings(parts[0])[0]
        options = []
        for expression in parts[1:]:
            parsed = _option_from_builder(expression)
            if parsed:
                options.append(parsed)
        systems[system] = options
    unsupported = []
    for match in re.finditer(r"\bunsupported\s*\(", block):
        unsupported.extend(
            _strings(_call_arguments(block, match.end() - 1))[0].split())
    return systems, unsupported


CATALOG_SYSTEMS, CATALOG_UNSUPPORTED = parse_catalog()


class CatalogReaderTest(unittest.TestCase):
    """Canary: if this fails, the reader below is measuring nothing."""

    def test_catalog_reader_sees_the_known_shape(self):
        self.assertGreater(len(CATALOG_SYSTEMS), 40,
                           "the catalog reader found almost no systems")
        self.assertIn("psx", CATALOG_SYSTEMS)
        ids = [option for option, _ in CATALOG_SYSTEMS["psx"]]
        self.assertEqual(["duckstation", "epsxe", "retroarch-psx"], ids)
        packages = dict(CATALOG_SYSTEMS["psx"])
        self.assertEqual(["com.github.stenzek.duckstation"], packages["duckstation"])
        self.assertEqual(RETROARCH_PACKAGES, packages["retroarch-psx"])
        # Multi-package and line-split literals must survive rejoining.
        self.assertEqual(["org.mupen64plusae.v3.fzurita.pro",
                          "org.mupen64plusae.v3.fzurita",
                          "org.mupen64plusae.v3.fzurita.amazon"],
                         dict(CATALOG_SYSTEMS["n64"])["m64plus-fz"])
        self.assertEqual(["apple2", "xbox", "xbox360"], CATALOG_UNSUPPORTED)


class DirectoryDataTest(unittest.TestCase):
    def test_schema_version_and_shape(self):
        self.assertEqual(1, DIRECTORY["schemaVersion"])
        self.assertTrue(DIRECTORY["note"].strip())
        self.assertTrue(DIRECTORY["emulators"])
        self.assertTrue(DIRECTORY["systems"])

    def test_nothing_claims_to_be_verified_that_has_not_been(self):
        # The file's whole honesty contract: a per-entry verified flag may only
        # be true once the file as a whole says ids have been checked. Flipping
        # one without the other is how "we verified it" quietly becomes untrue.
        verified_overall = DIRECTORY["packageIdsVerified"]
        for emulator in DIRECTORY["emulators"]:
            self.assertIn("verified", emulator, emulator["id"])
            if emulator["verified"]:
                self.assertTrue(
                    verified_overall,
                    f"{emulator['id']} claims verification the file denies")

    def test_every_emulator_entry_is_complete_and_reachable(self):
        seen = set()
        for emulator in DIRECTORY["emulators"]:
            identifier = emulator["id"]
            self.assertNotIn(identifier, seen, f"duplicate emulator {identifier}")
            seen.add(identifier)
            self.assertRegex(identifier, r"^[a-z0-9-]+$")
            self.assertTrue(emulator["name"].strip(), identifier)
            self.assertTrue(emulator["packages"], identifier)
            for package in emulator["packages"]:
                self.assertRegex(package, PACKAGE_ID, f"{identifier}: {package}")
            install = emulator["install"]
            self.assertIn(install["kind"], ("play", "web"), identifier)
            self.assertTrue(install["url"].startswith("https://"), identifier)
            if install["kind"] == "play":
                # A Play listing must name the package it installs, or the
                # market:// hand-off has nothing to open.
                self.assertIn(emulator["packages"][0], install["url"], identifier)

    def test_system_keys_are_canonical(self):
        # The catalog is looked up post-canonicalization, so keying the
        # directory on a raw alias would leave that system silently unlisted —
        # the same class of bug as the historical "gc"/"n3ds" regression.
        for alias in ("gc", "n3ds", "genesis", "ds", "ps1", "dc", "sms",
                      "tg16", "mame", "supernintendo", "famicom"):
            self.assertNotIn(alias, DIRECTORY["systems"],
                             f"{alias} is an alias, not a canonical system")
        self.assertIn("gamecube", DIRECTORY["systems"])
        self.assertIn("3ds", DIRECTORY["systems"])

    def test_unsupported_systems_explain_themselves(self):
        listed = {row["system"]: row["reason"] for row in
                  DIRECTORY["unsupportedSystems"]}
        self.assertEqual(sorted(CATALOG_UNSUPPORTED), sorted(listed))
        for system, reason in listed.items():
            self.assertGreater(len(reason), 10, system)
            # An optionless system must never also be offered options.
            self.assertNotIn(system, DIRECTORY["systems"], system)

    def test_schema_document_matches_the_data(self):
        try:
            import jsonschema
        except ImportError:  # pragma: no cover - environment dependent
            self.skipTest("jsonschema is not installed")
        jsonschema.validate(DIRECTORY, json.loads(_read(SCHEMA_PATH)))


class DirectoryMatchesCatalogTest(unittest.TestCase):
    """The directory may never offer something the catalog cannot launch."""

    def test_every_offered_option_exists_in_the_catalog(self):
        for system, choices in DIRECTORY["systems"].items():
            self.assertIn(system, CATALOG_SYSTEMS,
                          f"{system} is offered but the catalog has no entry")
            catalog_ids = [option for option, _ in CATALOG_SYSTEMS[system]]
            offered = [choice["option"] for choice in choices]
            self.assertEqual(catalog_ids, offered,
                             f"{system}: directory and catalog disagree")

    def test_every_launchable_catalog_system_is_listed(self):
        for system, options in CATALOG_SYSTEMS.items():
            if system in CATALOG_UNSUPPORTED:
                continue
            self.assertIn(system, DIRECTORY["systems"],
                          f"{system} can launch externally but Settings never "
                          "offers it")
            self.assertTrue(options, system)

    def test_referenced_apps_exist_and_carry_the_catalog_packages(self):
        apps = {emulator["id"]: emulator for emulator in DIRECTORY["emulators"]}
        catalog_packages = {}
        for options in CATALOG_SYSTEMS.values():
            for option, packages in options:
                catalog_packages[option] = packages
        for system, choices in DIRECTORY["systems"].items():
            for choice in choices:
                app_id = choice.get("app", choice["option"])
                self.assertIn(app_id, apps,
                              f"{system}/{choice['option']} names a missing app")
                # The install target has to be a package the catalog will
                # actually look for, or "installed" and "install" disagree.
                self.assertEqual(
                    catalog_packages[choice["option"]], apps[app_id]["packages"],
                    f"{system}/{choice['option']}: package list drifted")

    def test_one_app_may_serve_many_systems(self):
        # RetroArch is one download but a per-system catalog option; collapsing
        # them would either lose the core or list it once per system.
        retroarch = [choice for choices in DIRECTORY["systems"].values()
                     for choice in choices if choice.get("app") == "retroarch"]
        self.assertGreater(len(retroarch), 20)
        self.assertTrue(all(choice["option"].startswith("retroarch-")
                            for choice in retroarch))


class PackageVisibilityTest(unittest.TestCase):
    """Android 11+ filtering answers "not installed" for anything undeclared."""

    def test_queries_block_is_in_sync_with_the_directory(self):
        result = subprocess.run(
            ["python3", str(ROOT / "tools" / "sync_external_emulator_queries.py")],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(0, result.returncode,
                         f"{result.stdout}\n{result.stderr}")

    def test_every_directory_package_is_declared(self):
        declared = set(re.findall(
            r'<package android:name="([^"]+)"', MANIFEST))
        for emulator in DIRECTORY["emulators"]:
            for package in emulator["packages"]:
                self.assertIn(package, declared,
                              f"{package} would be invisible under filtering")

    def test_custom_emulators_are_covered_by_an_intent_filter(self):
        # A package the user picks at runtime cannot be in a static list, so
        # without this the guided custom setup could never confirm an install.
        queries = re.search(r"<queries>.*?</queries>", MANIFEST, re.DOTALL)
        self.assertIsNotNone(queries)
        self.assertIn("android.intent.action.MAIN", queries.group(0))
        self.assertIn("android.intent.category.LAUNCHER", queries.group(0))

    def test_query_all_packages_is_not_requested(self):
        # Play treats it as restricted and the two <queries> declarations
        # already answer the question. Naming it in the explanatory comment is
        # fine; requesting it is not.
        self.assertNotIn("QUERY_ALL_PACKAGES\"", MANIFEST)
        self.assertNotIn("permission.QUERY_ALL_PACKAGES", MANIFEST)

    def test_detection_has_a_visibility_fallback_and_says_why(self):
        self.assertIn("getPackageInfo(packageName, 0)", INSTALLED)
        self.assertIn("queryIntentActivities", INSTALLED)
        self.assertIn("getLaunchIntentForPackage", INSTALLED)
        # The reasoning has to live next to the code, because the failure mode
        # is silence: nothing logs, nothing throws, everything reads "missing".
        for phrase in ("targetSdkVersion 28", "<queries>", "QUERY_ALL_PACKAGES"):
            self.assertIn(phrase, INSTALLED)

    def test_the_catalog_routes_detection_through_it(self):
        # A bare getPackageInfo anywhere in the catalog would reintroduce the
        # filtering hole for whichever option used it.
        self.assertIn("InstalledPackages.firstInstalled(context, packages)", CATALOG)
        self.assertNotIn("manager.getPackageInfo", CATALOG)

    def test_an_exported_activity_check_backs_the_custom_setup(self):
        self.assertIn("hasExportedActivity", INSTALLED)
        self.assertIn("info.exported", INSTALLED)


class CustomEmulatorTest(unittest.TestCase):
    def test_validation_is_whitelist_only_and_explains_why(self):
        # These values are interpolated into the am start string Pegasus runs.
        self.assertIn("argument-injection", CUSTOM_SPEC)
        self.assertIn('Pattern.compile("[A-Za-z][A-Za-z0-9_]*(\\\\.[A-Za-z][A-Za-z0-9_]*)+")',
                      CUSTOM_SPEC)
        self.assertIn('Pattern.compile("[A-Za-z][A-Za-z0-9_.]*")', CUSTOM_SPEC)

    def test_an_invalid_spec_can_never_become_a_launch_command(self):
        block = CUSTOM_SPEC[CUSTOM_SPEC.index("public String component()"):]
        self.assertIn('if (!valid()) return "";', block)

    def test_nothing_is_stored_until_the_device_confirms_it(self):
        self.assertIn("InstalledPackages.isInstalled(context, spec.packageName())",
                      CUSTOM_STORE)
        self.assertIn("InstalledPackages.hasExportedActivity(", CUSTOM_STORE)
        # Storage happens only in the branch where both checks passed.
        save = CUSTOM_STORE[CUSTOM_STORE.index("static JSONObject save("):]
        save = save[:save.index("static void clear(")]
        self.assertLess(save.index("hasExportedActivity"),
                        save.index("prefs(context).edit()"))

    def test_pointing_at_emufusion_itself_is_refused(self):
        self.assertIn("ownPackage", CUSTOM_SPEC)
        self.assertIn("context.getPackageName()", CUSTOM_STORE)

    def test_problems_are_field_addressed_for_the_guided_setup(self):
        self.assertIn('problem.field()', CUSTOM_STORE)
        self.assertIn('problem.message()', CUSTOM_STORE)
        self.assertIn('response.put("problems", problems)', CUSTOM_STORE)

    def test_route_store_accepts_custom_only_once_it_resolves(self):
        self.assertIn("CustomEmulatorStore.ID.equalsIgnoreCase(trimmed)", ROUTE_STORE)
        self.assertIn(
            "if (CustomEmulatorStore.option(context, canonical) == null) return false;",
            ROUTE_STORE)

    def test_a_stale_custom_target_does_not_strand_the_system(self):
        # option() returns null when the app is gone, and effectiveOption then
        # falls back to the catalog rather than leaving nothing launchable.
        self.assertIn("InstalledPackages.hasExportedActivity(context, packageName, component)",
                      CUSTOM_STORE)
        self.assertIn("resolvedOptionForId(context, system, chosenId)", CATALOG)


class RouteEndpointTest(unittest.TestCase):
    ENDPOINTS = ("/route/systems", "/route/options", "/route/resolve",
                 "/route/set", "/route/clear", "/route/link", "/route/custom")
    MUTATING = ("/route/set", "/route/clear", "/route/link", "/route/custom")

    def test_every_endpoint_is_dispatched(self):
        for endpoint in self.ENDPOINTS:
            self.assertIn(f'"{endpoint}".equals(path)', SERVICE, endpoint)

    def test_mutating_endpoints_are_declared_mutating(self):
        mutating = SERVICE[SERVICE.index("MUTATING_ENDPOINTS"):]
        mutating = mutating[:mutating.index("THEME_CALLED_ENDPOINTS")]
        for endpoint in self.MUTATING:
            self.assertIn(f'"{endpoint}"', mutating, endpoint)
        # Reads must NOT be listed: they would then reject the theme's own
        # polling for no benefit.
        for endpoint in ("/route/systems", "/route/options", "/route/resolve"):
            self.assertNotIn(f'"{endpoint}"', mutating, endpoint)

    def test_theme_called_endpoints_are_reachable_from_qml(self):
        theme = SERVICE[SERVICE.index("THEME_CALLED_ENDPOINTS"):]
        theme = theme[:theme.index("private volatile String controlToken")]
        for endpoint in self.MUTATING:
            self.assertIn(f'"{endpoint}"', theme, endpoint)
        # ...and the residual risk is written down where it is taken.
        self.assertIn("Origin/Referer", theme)

    def test_the_tap_flow_is_one_endpoint_with_two_outcomes(self):
        link = PICKER[PICKER.index("static JSONObject link("):]
        self.assertIn('response.put("linked", false)', link)
        self.assertIn("option.installedPackage(context)", link)
        self.assertIn("EngineRouteStore.setRoute(", link)
        # Install state is read on every tap, never cached from the first.
        self.assertIn("never cached from the first one", PICKER)

    def test_a_missing_emulator_opens_its_source_and_binds_nothing(self):
        block = SERVICE[SERVICE.index('"/route/link".equals(path)'):]
        block = block[:block.index('"/route/custom".equals(path)')]
        self.assertIn('result.optBoolean("linked", false)', block)
        self.assertIn("openInstallSource(", block)

    def test_play_and_website_sources_are_both_handled(self):
        self.assertIn("marketUrl", PICKER)
        self.assertIn('install.put("kind", app.installKind())', PICKER)
        opener = SERVICE[SERVICE.index("private boolean openInstallSource"):]
        opener = opener[:opener.index("private boolean startExternalView")]
        self.assertIn('install.optString("marketUrl", "")', opener)
        self.assertIn("BrowserActivity.open(this, url)", opener)

    def test_a_route_change_re_emits_launch_commands_off_the_http_worker(self):
        apply_block = SERVICE[SERVICE.index("private void applyRouteChange"):]
        apply_block = apply_block[:apply_block.index("private boolean openInstallSource")]
        self.assertIn("importManager.rewriteLaunchRoutes()", apply_block)
        self.assertIn("Thread", apply_block)
        self.assertIn('result.optBoolean("ok", false)', apply_block)

    def test_options_payload_carries_what_the_screen_needs(self):
        options = PICKER[PICKER.index("static String optionsJson("):]
        options = options[:options.index("private static JSONArray deliveryOptions")]
        for field in ('"internalAvailable"', '"route"', '"explicit"', '"chosen"',
                      '"unsupportedReason"', '"options"', '"custom"',
                      '"installed"', '"selected"', '"install"', '"verified"'):
            self.assertIn(field, options, field)

    def test_system_inventory_is_strictly_library_driven(self):
        systems = PICKER[PICKER.index("static String systemsJson("):]
        systems = systems[:systems.index("static String optionsJson(")]
        visibility = "if (activeFolders == null || !activeFolders.contains(system.folder))"
        self.assertIn(visibility, systems)
        self.assertLess(systems.index(visibility),
                        systems.index("EngineRouteStore.hasInternalEngine"))
        self.assertIn('row.put("active", true);', systems)

        load = THEME[THEME.index("function loadEmulatorRoutes()") :]
        load = load[:load.index("function currentRouteSystem()")]
        self.assertIn("if (row.active === true) visible.push(row)", load)
        self.assertIn("root.emulatorRouteSystems = visible", load)
        self.assertNotIn("active.concat(rest)", load)

    def test_system_inventory_reconciles_live_pre_registry_metadata(self):
        active = IMPORTER[IMPORTER.index("Set<String> activeSystemFolders()"):]
        active = active[:active.index("String archiveJson()")]
        self.assertIn("for (File metadata : metadataFiles())", active)
        self.assertIn("for (String stanza : splitStanzas(readText(metadata)))", active)
        self.assertIn('String title = field(stanza, "game")', active)
        self.assertIn('String path = field(stanza, "file")', active)
        self.assertIn("!new File(path).exists()", active)
        self.assertIn("GameSystems.SystemDef system = systemFromRomPath(path)", active)
        self.assertIn("if (system != null) systems.add(system.folder)", active)

    def test_clear_returns_the_same_effective_projection_as_resolve(self):
        # The clear mutation and read-only resolve endpoint must not grow two
        # subtly different definitions of the effective route.
        resolve = PICKER[PICKER.index("private static JSONObject resolvedRoute("):]
        resolve = resolve[:resolve.index("static String resolveJson(")]
        for field in ('"route"', '"explicit"', '"internalAvailable"',
                      '"chosen"', '"emulator"', '"emulatorName"'):
            self.assertIn(field, resolve, field)
        clear = PICKER[PICKER.index("static JSONObject clearRoute("):]
        clear = clear[:clear.index("static JSONObject link(")]
        self.assertIn("response = resolvedRoute(context, canonical);", clear)
        self.assertIn('response.put("ok", true)', clear)

    def test_clearing_a_route_does_not_delete_a_custom_definition(self):
        # Reset means forget the route override, not destroy setup the user may
        # want to select again later.
        clear = PICKER[PICKER.index("static JSONObject clearRoute("):]
        clear = clear[:clear.index("static JSONObject link(")]
        self.assertIn("EngineRouteStore.clearRoute(context, canonical)", clear)
        self.assertNotIn("CustomEmulatorStore.clear", clear)

    def test_internal_availability_comes_from_real_catalog_state(self):
        # Never a hardcoded list: the screen must show Internal exactly when a
        # release-qualified engine is actually bundled.
        self.assertIn("EngineRouteStore.hasInternalEngine(context, canonical)", PICKER)
        self.assertIn("GameLaunchRouter.supportsSystem(context,", ROUTE_STORE)

    def test_refusals_are_sentences_the_ui_can_show(self):
        refusal = PICKER[PICKER.index("private static String refusal("):]
        refusal = refusal[:refusal.index("static JSONObject clearRoute(")]
        self.assertIn("There is no built-in engine for this system yet.", refusal)
        self.assertIn("Set up the custom emulator first.", refusal)


THEME = _read(ROOT / "theme" / "theme.qml")
LEGAL = _read(ROOT / "unified-android" / "src" / "com" / "thorium" / "lucent" /
              "legal" / "LegalNotice.java")


class SettingsScreenTest(unittest.TestCase):
    """The QML the user actually operates."""

    def test_the_tail_rows_are_appended_below_the_historic_block(self):
        # The tail grew a third row for the missing-box-art review, so its
        # length is read from the declared slot order rather than written twice.
        self.assertIn("readonly property int settingsTailCount: settingsTailSlots.length",
                      THEME)
        self.assertIn("baseSettingsOptionCount + settingsTailCount", THEME)
        self.assertIn('"EMULATOR FOR EACH SYSTEM"', THEME)
        self.assertIn('"LEGAL NOTICE"', THEME)
        self.assertIn('"GAMES WITH NO BOX ART"', THEME)

    def test_the_legal_notice_is_the_very_last_row(self):
        # Display order is the tail slot order, not the order the titles happen
        # to be written in: a new row appends to the titles array but is placed
        # by settingsTailSlots, so the legal notice keeps the bottom.
        tail = re.search(r"readonly property var settingsTailSlots: \[([^\]]*)\]",
                         THEME).group(1)
        slots = [int(value.strip()) for value in tail.split(",")]
        titles = re.search(r"function settingTitle\(index\).*?\n    \}", THEME,
                           re.DOTALL).group(0)
        entries = re.findall(r'"([A-Z][^"]*)"', titles)
        self.assertEqual("LEGAL NOTICE", entries[slots[-1]])
        self.assertEqual("EMULATOR FOR EACH SYSTEM", entries[slots[0]])

    def test_the_tail_survives_the_single_screen_only_row(self):
        # Slot 16 (PIP/box-art order) exists only on a single-screen device, so
        # an absolute index is not a slot. Without the remap the tail would
        # land on top of that row on the dual-screen Thor.
        self.assertIn("function settingSlot(index)", THEME)
        self.assertIn("if (index < baseSettingsOptionCount) return index", THEME)
        self.assertIn(
            "return Number(settingsTailSlots[index - baseSettingsOptionCount])", THEME)
        for helper in ("settingTitle", "settingDescription"):
            block = re.search(r"function %s\(index\).*?\n    \}" % helper, THEME,
                              re.DOTALL).group(0)
            self.assertIn("settingSlot(index)", block, helper)

    def test_every_route_endpoint_the_screens_need_is_called(self):
        for endpoint in ("route/systems", "route/options", "route/resolve",
                         "route/set", "route/clear", "route/link",
                         "route/custom", "legal/notice"):
            self.assertIn(endpoint, THEME, endpoint)
        self.assertIn("route/custom?clear=1", THEME)

    def test_empty_library_reveals_no_system_or_emulator_inventory(self):
        self.assertIn('return "NO GAMES YET"', THEME)
        self.assertIn("Only systems represented in your game library appear here.", THEME)
        self.assertIn("Add a game to reveal its emulator settings.", THEME)
        self.assertNotIn("No games imported yet", THEME)

    def test_an_apk_update_refreshes_changed_bundled_theme_bytes_once(self):
        self.assertIn('ASSET_BUNDLED_FINGERPRINT', THEME_INSTALLER)
        self.assertIn('new File(PEGASUS,\n            ".lucent-bundled-theme.sha256")',
                      THEME_INSTALLER)
        self.assertIn("boolean bundledChanged", THEME_INSTALLER)
        self.assertIn("private static synchronized boolean installBundledBlocking(",
                      THEME_INSTALLER)
        self.assertIn("force || firstEmuFusionInstall || bundledChanged",
                      THEME_INSTALLER)
        self.assertIn("writeText(BUNDLED_FINGERPRINT", THEME_INSTALLER)
        self.assertIn('THEME_FINGERPRINT=', BUILD)
        self.assertIn('shasum -a 256 "$THEME_ARCHIVE"', BUILD)
        self.assertIn('cp "$THEME_ARCHIVE" "$THEME_FINGERPRINT"', BUILD)

    def test_theme_update_keeps_the_live_entrypoint_present(self):
        install = THEME_INSTALLER[
            THEME_INSTALLER.index("static synchronized void installZip(InputStream") :
            THEME_INSTALLER.index("static String installedVersion()")
        ]
        self.assertNotIn("deleteTree(THEME)", install)
        self.assertIn("publishStagedTheme(staging)", install)
        self.assertIn("Os.rename(source.getAbsolutePath(), target.getAbsolutePath())", install)
        self.assertLess(install.index('publishStagedFile(staging, "theme.cfg")'),
                        install.index('publishStagedFile(staging, "theme.qml")'))

    def test_automatic_default_clears_then_reads_the_effective_route(self):
        reset = THEME[THEME.index("function restoreAutomaticEmulatorRoute()") :]
        reset = reset[:reset.index("function activateEmulatorPickerRow()")]
        self.assertLess(reset.index('requestPreviewJson("route/clear?system="'),
                        reset.index('requestPreviewJson("route/resolve?system="'))
        self.assertIn("restoredRouteDescription(resolved)", reset)
        self.assertIn("loadEmulatorPicker()", reset)
        self.assertIn("loadEmulatorRoutes()", reset)

    def test_automatic_default_is_distinct_from_an_explicit_internal_choice(self):
        rows = THEME[THEME.index("function rebuildEmulatorPickerRows()") :]
        rows = rows[:rows.index("function currentPickerRow()")]
        self.assertIn('kind: "default"', rows)
        self.assertIn('name: "Automatic default"', rows)
        self.assertIn("selected: data.explicit !== true", rows)
        self.assertIn(
            'selected: data.explicit === true && data.route === "internal"', rows)

    def test_route_reset_failures_are_visible_and_do_not_claim_success(self):
        reset = THEME[THEME.index("function restoreAutomaticEmulatorRoute()") :]
        reset = reset[:reset.index("function activateEmulatorPickerRow()")]
        self.assertIn("if (!cleared || cleared.ok !== true)", reset)
        self.assertIn("The automatic route could not be restored.", reset)
        self.assertIn("The route was reset, but its default could not be read.", reset)
        self.assertLess(reset.index("if (!cleared || cleared.ok !== true)"),
                        reset.index("Automatic default restored"))

    def test_route_option_reads_and_mutations_report_transport_failures(self):
        load = THEME[THEME.index("function loadEmulatorPicker()") :]
        load = load[:load.index("function rebuildEmulatorPickerRows()")]
        self.assertIn("if (!data)", load)
        self.assertIn("Could not read this system's emulator settings.", load)
        toggle = THEME[THEME.index("function toggleEmulatorRoute(direction)") :]
        toggle = toggle[:toggle.index("function openEmulatorPicker(")]
        self.assertIn("Could not reach the emulator service.", toggle)

    def test_the_screens_are_reachable_with_a_dpad_alone(self):
        # Each overlay must own an Up/Down/Accept/Cancel branch in the key
        # chain; a touch-only surface is unusable on the handheld.
        for state in ("emulatorRoutesOpen", "emulatorPickerOpen",
                      "customEmulatorOpen", "legalOpen"):
            self.assertIn("} else if (%s) {" % state, THEME, state)
        chain = THEME[THEME.index("Keys.onPressed:"):]
        routes = chain[chain.index("} else if (emulatorRoutesOpen) {"):]
        routes = routes[:routes.index("} else if (coverOrderEditorOpen) {")]
        for key in ("Qt.Key_Up", "Qt.Key_Down", "Qt.Key_Left", "Qt.Key_Right",
                    "api.keys.isAccept(event)", "api.keys.isCancel(event)"):
            self.assertIn(key, routes, key)

    def test_lists_use_the_shared_row_helpers(self):
        # Reclaimed height goes into rows, never into a gap under the last one.
        for expression in ("listRowCount(settingsListAvailable, 102",
                           "listRowHeight(settingsListAvailable, 102",
                           "listRowCount(\n            routesListAvailable",
                           "shareRowHeight(routesListAvailable, pickerRowCount"):
            self.assertIn(expression, THEME, expression)
        self.assertIn("y: root.settingsListTop +\n                       index * "
                      "(root.routesRowHeight + root.settingsListSpacing)", THEME)

    def test_a_short_list_is_centred_rather_than_top_pinned(self):
        self.assertIn("function centredListTop(", THEME)
        self.assertIn("y: root.pickerListTop + index * (root.pickerRowHeight + 12)",
                      THEME)

    def test_the_tap_flow_is_explained_on_screen(self):
        # The two-tap install/link flow only works if the screen says so.
        self.assertIn("install it, then press A again", THEME)
        self.assertIn("come back and press A on it again", THEME)

    def test_the_custom_form_shows_per_field_problems(self):
        self.assertIn("function customEmulatorProblemFor(field)", THEME)
        self.assertIn("problems[index].field === field", THEME)
        # A truncated validation message is no better than none.
        self.assertIn("wrapMode: Text.WordWrap\n                        "
                      "maximumLineCount: 2", THEME)

    def test_the_field_editor_releases_the_input_session_deferred(self):
        # Releasing focus inside the key handler leaves Gboard up in fullscreen
        # extract mode, where it swallows the D-pad and the form dies.
        editor = THEME[THEME.index("id: customEmulatorEditor"):]
        editor = editor[:editor.index("id: legalOverlay")]
        self.assertIn("property bool closing: false", editor)
        self.assertIn("Qt.inputMethod.hide()", editor)
        self.assertIn("Qt.callLater(function()", editor)
        self.assertIn("customEmulatorInput.focus = false", editor)
        self.assertIn("root.forceActiveFocus()", editor)


class LegalNoticeScreenTest(unittest.TestCase):
    def test_the_wording_is_never_duplicated_into_qml(self):
        # One home for the text. A notice that says two different things in two
        # places is worse than one that says nothing.
        for paragraph in json.loads(json.dumps(
                re.findall(r'"([^"]{60,})"\n?\s*\+?', LEGAL)))[:3]:
            snippet = paragraph.strip()[:45]
            self.assertNotIn(snippet, THEME,
                             "legal wording was copied into the theme")
        self.assertIn("legal/notice", THEME)
        self.assertIn("root.legalParagraphs[index]", THEME)

    def test_the_endpoint_serves_the_single_source(self):
        self.assertIn("com.thorium.lucent.legal.LegalNotice.PARAGRAPHS", SERVICE)
        self.assertIn("com.thorium.lucent.legal.LegalNotice.TITLE", SERVICE)
        self.assertIn('"/legal/notice".equals(path)', SERVICE)

    def test_the_settings_copy_has_no_acceptance_gate(self):
        # The startup popup owns the scroll gate and the checkbox; this one is
        # only a reader, so it must not re-ask for consent.
        legal = THEME[THEME.index("id: legalOverlay"):]
        for gate in ("SUPPRESS_LABEL", "CONFIRM_LABEL", "checkbox", "Confirm"):
            self.assertNotIn(gate, legal, gate)

    def test_the_reader_is_read_only_and_scrollable(self):
        self.assertIn("function scrollLegalNotice(direction)", THEME)
        self.assertIn("root.legalBodyHeight > root.legalViewportHeight", THEME)
        # Re-read on every open, so a wording change cannot go stale.
        opener = THEME[THEME.index("function openLegalNotice()"):]
        opener = opener[:opener.index("function scrollLegalNotice")]
        self.assertIn('requestPreviewJson("legal/notice"', opener)


class PackagingTest(unittest.TestCase):
    def test_directory_ships_as_an_asset(self):
        self.assertIn('cp "$ROOT_DIR/engines/external-emulators.json"', BUILD)
        self.assertIn('"$DECODED/assets/external-emulators.json"', BUILD)
        self.assertIn('"external-emulators.json"', LOADER)

    def test_a_damaged_asset_degrades_presentation_not_launching(self):
        self.assertIn("ExternalEmulatorDirectory.empty()", LOADER)
        self.assertIn("schemaVersion", LOADER)
        # The picker still enumerates the compiled catalog, so every emulator
        # stays selectable even with no asset at all.
        self.assertIn("EmulatorCatalog.optionsForSystem(canonical)", PICKER)

    def test_host_tests_are_compiled_and_actually_run(self):
        self.assertIn("src/com/thorium/lucent/emulators", TEST_SH)
        self.assertIn("com.thorium.lucent.emulators.ExternalEmulatorModelTest", TEST_SH)

    def test_the_model_layer_stays_free_of_android_and_json(self):
        # This split is what makes the host tests possible at all.
        for path in sorted(LUCENT.glob("*.java")):
            source = _read(path)
            self.assertNotIn("import android.", source, path.name)
            self.assertNotIn("import org.json", source, path.name)

    def test_the_design_note_documents_the_picker(self):
        for endpoint in RouteEndpointTest.ENDPOINTS:
            self.assertIn(endpoint, DOC, endpoint)
        self.assertIn("external-emulators.json", DOC)
        self.assertIn("package visibility", DOC.lower())
        self.assertIn("Custom", DOC)


if __name__ == "__main__":
    unittest.main()
