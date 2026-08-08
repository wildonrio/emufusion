"""Phase 3 Eden (Switch) native-adapter packaging, gating, and routing.

The adapter is an already-built artifact staged into engines/build (which is not
tracked), so these tests lock the things that ARE checked in: the pinned identity
shared by the registry, the source lock, and the opt-in; the executable gates
that decide whether the engine is present at all; the build.sh flag plumbing that
keeps a default build byte-unchanged; and the routing that only prefers INTERNAL
once a hash-verified adapter is really bundled.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

EDEN_COMMIT = "c0ffc900cdf19b9373549c59a7e6b22c33615ea4"
SUPERSEDED_COMMIT = "5ec94b19714f75489cdfc62d890d2f94d45514ce"
ADAPTER_SHA256 = "86eaf8a8c90e3f9adafc88ed7aa3f20d0a335892712f9c2dc54ab06349bae7f7"
ADAPTER_LIBRARY = "liblucent_native_adapter_eden.so"
STAGED_ADAPTER = ROOT / "engines" / "build" / "arm64-v8a" / ADAPTER_LIBRARY
ADAPTER_PATCH = ROOT / "engines" / "patches" / "eden-lucent-adapter.cpp"

MANIFEST_TOOL = ROOT / "unified-android" / "tools" / "generate_engine_artifact_manifest.py"
APK_VERIFIER = ROOT / "unified-android" / "tools" / "verify_phase3_apk.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MANIFEST = _load(MANIFEST_TOOL, "phase3_artifact_manifest")
VERIFIER = _load(APK_VERIFIER, "phase3_apk_verifier")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


REGISTRY = json.loads(_read(ROOT / "engines" / "phase3-registry.json"))
OPT_IN = json.loads(_read(ROOT / "engines" / "phase3-qualification-opt-in.json"))
SOURCE_LOCK = json.loads(_read(ROOT / "engines" / "eden-source-lock.json"))
SCHEMA = json.loads(_read(ROOT / "engines" / "phase3-registry.schema.json"))
BUILD = _read(ROOT / "unified-android" / "build.sh")
CATALOG = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                "preview" / "game" / "NativeAdapterCatalog.java")
SESSION = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                "preview" / "game" / "NativeAdapterEngineSession.java")
SYSTEM_DIR = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                   "preview" / "game" / "NativeAdapterSystemDirectory.java")
ROUTER = _read(ROOT / "android-companion" / "src" / "com" / "thorium" /
               "preview" / "GameLaunchRouter.java")
ROUTE_STORE = _read(ROOT / "android-companion" / "src" / "com" / "thorium" /
                    "preview" / "EngineRouteStore.java")
IMPORT_MANAGER = _read(ROOT / "android-companion" / "src" / "com" / "thorium" /
                       "preview" / "ImportManager.java")
EMULATOR_CATALOG = _read(ROOT / "android-companion" / "src" / "com" / "thorium" /
                         "preview" / "EmulatorCatalog.java")


def _eden_row() -> dict:
    rows = [row for row in REGISTRY["engines"] if row["id"] == "eden"]
    assert len(rows) == 1
    return rows[0]


class Phase3EdenIdentityTest(unittest.TestCase):
    """The registry, source lock, and opt-in must name one identical build."""

    def test_registry_pins_the_commit_that_was_actually_built(self):
        row = _eden_row()
        self.assertEqual(EDEN_COMMIT, row["source"]["commit"])
        self.assertNotEqual(SUPERSEDED_COMMIT, row["source"]["commit"])
        self.assertEqual("native-adapter", row["route"])
        self.assertEqual(["switch"], row["systems"])

    def test_registry_records_why_the_commit_moved(self):
        note = _eden_row().get("note", "")
        self.assertIn(SUPERSEDED_COMMIT, note)
        self.assertIn("note", SCHEMA["$defs"]["engine"]["properties"])
        self.assertNotIn("note", SCHEMA["$defs"]["engine"]["required"])

    def test_registry_row_still_fails_closed(self):
        row = _eden_row()
        self.assertEqual("research", row["status"])
        self.assertFalse(row["shipped"])
        self.assertTrue(all(value is False for value in row["gates"].values()))

    def test_source_lock_matches_the_registry_and_claims_no_reproducibility(self):
        self.assertEqual("eden", SOURCE_LOCK["engineId"])
        self.assertEqual("native-adapter", SOURCE_LOCK["route"])
        self.assertEqual(EDEN_COMMIT, SOURCE_LOCK["core"]["commit"])
        self.assertIs(False, SOURCE_LOCK["reproducible"])
        self.assertNotIn("independentBuilds", SOURCE_LOCK)
        self.assertEqual("lucent_native_adapter_entry",
                         SOURCE_LOCK["adapterAbi"]["entrySymbol"])
        self.assertEqual(ADAPTER_LIBRARY,
                         SOURCE_LOCK["adapterAbi"]["expectedLibraryName"])

    def test_source_lock_records_the_toolchain_that_produced_the_artifact(self):
        toolchain = SOURCE_LOCK["toolchain"]
        self.assertEqual("arm64-v8a", toolchain["androidAbi"])
        self.assertEqual(30, toolchain["androidApi"])
        self.assertEqual("28.2.13676358", toolchain["ndkVersion"])
        self.assertEqual("3.31.6", toolchain["cmakeVersion"])
        self.assertEqual("Release", toolchain["buildType"])
        self.assertEqual("16.5.0", toolchain["glslangValidator"]["version"])
        options = SOURCE_LOCK["cmakeOptions"]
        self.assertEqual(0, options["ENABLE_QT"])
        self.assertEqual(1, options["ENABLE_WEB_SERVICE"])
        self.assertIs(True, options["ANDROID_ARM_NEON"])
        self.assertEqual("ON", options["YUZU_USE_CPM"])
        self.assertEqual("ON", options["CPMUTIL_FORCE_BUNDLED"])
        self.assertEqual("ON", options["YUZU_USE_BUNDLED_FFMPEG"])
        self.assertEqual("OFF", options["BUILD_TESTING"])
        self.assertEqual("OFF", options["YUZU_TESTS"])
        self.assertEqual("OFF", options["DYNARMIC_TESTS"])
        self.assertEqual("arm64-v8a", options["ANDROID_ABI"])
        self.assertEqual("android-30", options["ANDROID_PLATFORM"])

    def test_source_lock_pins_the_adapter_translation_unit_it_compiled_in(self):
        patches = SOURCE_LOCK["patches"]
        self.assertEqual(1, len(patches))
        self.assertEqual("engines/patches/eden-lucent-adapter.cpp",
                         patches[0]["path"])
        self.assertEqual(
            hashlib.sha256(ADAPTER_PATCH.read_bytes()).hexdigest(),
            patches[0]["sha256"])

    def test_source_lock_does_not_overstate_the_artifact(self):
        artifact = SOURCE_LOCK["artifact"]
        self.assertEqual(ADAPTER_SHA256, artifact["sha256"])
        self.assertEqual(ADAPTER_LIBRARY, artifact["fileName"])
        # Measured facts only: the library is Eden's whole native library with
        # the adapter compiled in, so it does NOT export only the entry symbol.
        self.assertIs(False, artifact["exportsOnlyTheAdapterEntry"])
        self.assertIn("lucent_native_adapter_entry", artifact["requiredExports"])
        self.assertIn("lucent_eden_average_game_fps", artifact["requiredExports"])
        self.assertEqual("0x4000", artifact["ptLoadAlignment"])

    def test_no_keys_or_firmware_are_ever_claimed_as_bundled(self):
        self.assertIs(False, SOURCE_LOCK["runtimeInputs"]["keysAndFirmwareBundled"])
        self.assertIs(False, OPT_IN["engines"][0]["userSuppliedRuntimeInputs"]
                      ["bundledInApk"])

    def test_opt_in_is_qualification_only_and_never_auto_selected(self):
        self.assertEqual(1, OPT_IN["schemaVersion"])
        self.assertIs(True, OPT_IN["qualificationOnly"])
        self.assertIs(False, OPT_IN["autoSelect"])
        self.assertEqual(1, len(OPT_IN["engines"]))
        engine = OPT_IN["engines"][0]
        self.assertEqual("eden", engine["id"])
        self.assertEqual(EDEN_COMMIT, engine["commit"])
        self.assertEqual(ADAPTER_LIBRARY, engine["libraryName"])
        self.assertEqual("native-adapter", engine["runtime"])
        self.assertEqual(["switch"], engine["libraryRouteSystems"])

    def test_opt_in_library_routes_are_a_subset_of_the_registry_systems(self):
        # NativeAdapterCatalog rejects the entry otherwise; assert it here so a
        # bad edit fails on the host instead of silently on device.
        self.assertTrue(
            set(OPT_IN["engines"][0]["libraryRouteSystems"])
            <= set(_eden_row()["systems"]))

    @unittest.skipUnless(STAGED_ADAPTER.is_file(),
                         "staged adapter is not in this working tree")
    def test_recorded_hash_is_the_real_staged_artifact(self):
        digest = hashlib.sha256()
        with STAGED_ADAPTER.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        self.assertEqual(ADAPTER_SHA256, digest.hexdigest())
        self.assertEqual(SOURCE_LOCK["artifact"]["sizeBytes"],
                         STAGED_ADAPTER.stat().st_size)


class Phase3ArtifactManifestTest(unittest.TestCase):
    """The manifest generator must only ever claim what is really staged."""

    def _fixture(self, root: Path, *, route: str = "native-adapter",
                 stage: bool = True) -> None:
        libraries = root / "lib"
        libraries.mkdir()
        if stage:
            (libraries / ADAPTER_LIBRARY).write_bytes(b"adapter")
        (root / "registry.json").write_text(json.dumps({"engines": [
            {"id": "eden", "route": route, "source": {"commit": EDEN_COMMIT}},
        ]}), encoding="utf-8")

    def _run(self, root: Path, expected_count: int, kind="native-adapter"):
        return subprocess.run(
            [sys.executable, str(MANIFEST_TOOL),
             "--registry", str(root / "registry.json"),
             "--library-dir", str(root / "lib"),
             "--artifact-kind", kind,
             "--expected-count", str(expected_count),
             "--output", str(root / "manifest.json")],
            capture_output=True, text=True)

    def test_staged_adapter_is_hashed_into_the_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture(root)
            completed = self._run(root, 1)
            self.assertEqual(0, completed.returncode, completed.stderr)
            manifest = json.loads((root / "manifest.json").read_text())
            self.assertEqual(1, manifest["schemaVersion"])
            row = manifest["artifacts"][0]
            self.assertEqual("eden", row["engineId"])
            self.assertEqual(ADAPTER_LIBRARY, row["fileName"])
            self.assertEqual(EDEN_COMMIT, row["sourceCommit"])
            self.assertEqual(hashlib.sha256(b"adapter").hexdigest(), row["sha256"])

    def test_missing_adapter_fails_the_count_gate_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture(root, stage=False)
            completed = self._run(root, 1)
            self.assertEqual(1, completed.returncode)
            self.assertIn("found 0", completed.stderr)
            self.assertFalse((root / "manifest.json").exists())

    def test_a_row_without_the_native_adapter_route_contributes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture(root, route="libretro-core")
            self.assertEqual(0, len(MANIFEST.generate(
                root / "registry.json", root / "lib", "native-adapter")["artifacts"]))

    def test_the_core_manifest_never_picks_up_a_native_adapter(self):
        # Phase 1/2 manifests are generated from the same library directory; an
        # adapter must not leak into them and inflate their count gate.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture(root)
            self.assertEqual(0, len(MANIFEST.generate(
                root / "registry.json", root / "lib", "core")["artifacts"]))

    def test_default_artifact_kind_stays_core(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture(root)
            self.assertEqual(
                MANIFEST.generate(root / "registry.json", root / "lib"),
                MANIFEST.generate(root / "registry.json", root / "lib", "core"))


class Phase3ApkGateTest(unittest.TestCase):
    """Wrong hash or missing .so must make the engine absent, not present."""

    ADAPTER_BYTES = b"a staged phase 3 adapter"

    def _payload(self) -> dict:
        adapter_hash = hashlib.sha256(self.ADAPTER_BYTES).hexdigest()
        patch = ADAPTER_PATCH.read_bytes()
        registry = json.loads(json.dumps(REGISTRY))
        source_lock = json.loads(json.dumps(SOURCE_LOCK))
        source_lock["artifact"]["sha256"] = adapter_hash
        source_lock["patches"][0]["sha256"] = hashlib.sha256(patch).hexdigest()
        return {
            "lib/arm64-v8a/" + ADAPTER_LIBRARY: self.ADAPTER_BYTES,
            "assets/phase3-engine-registry.json": json.dumps(registry).encode(),
            "assets/phase3-qualification-opt-in.json":
                json.dumps(OPT_IN).encode(),
            "assets/phase3-engine-artifacts.json": json.dumps({
                "schemaVersion": 1,
                "artifacts": [{
                    "engineId": "eden",
                    "fileName": ADAPTER_LIBRARY,
                    "sha256": adapter_hash,
                    "sourceCommit": EDEN_COMMIT,
                }],
            }).encode(),
            "assets/phase3-eden-source-lock.json":
                json.dumps(source_lock).encode(),
            "assets/phase3-eden-lucent-adapter.cpp": patch,
        }

    def _verify(self, payload: dict) -> list:
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "lucent.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                for name, data in payload.items():
                    archive.writestr(name, data)
            return VERIFIER.verify(apk)

    def _mutate(self, asset: str, mutator) -> list:
        payload = self._payload()
        document = json.loads(payload[asset].decode())
        mutator(document)
        payload[asset] = json.dumps(document).encode()
        return self._verify(payload)

    def test_a_complete_payload_verifies(self):
        self.assertEqual([], self._verify(self._payload()))

    def test_a_missing_adapter_library_fails_closed(self):
        payload = self._payload()
        del payload["lib/arm64-v8a/" + ADAPTER_LIBRARY]
        errors = self._verify(payload)
        self.assertTrue(any("missing Phase 3 qualification payload" in error
                            for error in errors), errors)

    def test_a_wrong_manifest_hash_fails_closed(self):
        errors = self._mutate(
            "assets/phase3-engine-artifacts.json",
            lambda document: document["artifacts"][0].update({"sha256": "0" * 64}))
        self.assertTrue(any("hash does not match the manifest" in error
                            for error in errors), errors)

    def test_a_swapped_adapter_binary_fails_closed(self):
        payload = self._payload()
        payload["lib/arm64-v8a/" + ADAPTER_LIBRARY] = b"a different adapter"
        errors = self._verify(payload)
        self.assertTrue(any("hash does not match the manifest" in error
                            for error in errors), errors)

    def test_an_auto_selecting_opt_in_fails_closed(self):
        errors = self._mutate("assets/phase3-qualification-opt-in.json",
                              lambda document: document.update({"autoSelect": True}))
        self.assertIn("Phase 3 qualification payload is not fail-closed", errors)

    def test_a_commit_that_disagrees_across_assets_fails_closed(self):
        errors = self._mutate(
            "assets/phase3-qualification-opt-in.json",
            lambda document: document["engines"][0].update(
                {"commit": SUPERSEDED_COMMIT}))
        self.assertTrue(any("source commit differs" in error for error in errors),
                        errors)

    def test_routing_a_system_the_registry_does_not_own_fails_closed(self):
        errors = self._mutate(
            "assets/phase3-qualification-opt-in.json",
            lambda document: document["engines"][0].update(
                {"libraryRouteSystems": ["switch", "wiiu"]}))
        self.assertIn(
            "Phase 3 normal-library routes are not the exact qualified subset",
            errors)

    def test_a_claimed_gate_or_shipment_fails_closed(self):
        errors = self._mutate(
            "assets/phase3-engine-registry.json",
            lambda document: next(
                row for row in document["engines"] if row["id"] == "eden"
            )["gates"].update({"androidArm64": True}))
        self.assertTrue(any("claims a qualification gate" in error
                            for error in errors), errors)
        errors = self._mutate(
            "assets/phase3-engine-registry.json",
            lambda document: next(
                row for row in document["engines"] if row["id"] == "eden"
            ).update({"shipped": True}))
        self.assertTrue(any("claims a shipped engine" in error
                            for error in errors), errors)

    def test_a_reproducibility_claim_fails_closed(self):
        errors = self._mutate("assets/phase3-eden-source-lock.json",
                              lambda document: document.update({"reproducible": True}))
        self.assertIn(
            "Eden source lock claims reproducibility that was never proven", errors)

    def test_bundled_keys_or_firmware_fail_closed(self):
        for name, data in (("assets/prod.keys", b"never"),
                           ("assets/firmware/0100.nca", b"never")):
            payload = self._payload()
            payload[name] = data
            errors = self._verify(payload)
            self.assertTrue(
                any("keys/firmware are unexpectedly bundled" in error
                    for error in errors), (name, errors))


class Phase3BuildFlagTest(unittest.TestCase):
    """Packaging is opt-in; a default build must be byte-unchanged."""

    def test_the_flag_is_known_to_both_misspelling_guards(self):
        # Unprefixed stray name is refused outright...
        stray = BUILD[BUILD.index("for stray_flag in"):BUILD.index("# A misspelled")]
        self.assertIn("INCLUDE_PHASE3_EDEN", stray)
        # ...and the LUCENT_ allowlist must accept the real flag so the guard
        # does not reject a legitimate Phase 3 build.
        self.assertIn("LUCENT_INCLUDE_PHASE3_EDEN) ;;", BUILD)
        self.assertIn("LUCENT_REUSE_PHASE2_PPSSPP LUCENT_INCLUDE_PHASE3_EDEN)", BUILD)

    def test_the_flag_defaults_to_off(self):
        self.assertIn("INCLUDE_PHASE3_EDEN=${LUCENT_INCLUDE_PHASE3_EDEN:-0}", BUILD)
        self.assertIn("LUCENT_INCLUDE_PHASE3_EDEN must be 0 or 1", BUILD)

    def test_a_missing_staged_adapter_refuses_the_build(self):
        self.assertIn(
            'if [ "$INCLUDE_PHASE3_EDEN" = 1 ] && [ ! -f "$PHASE3_EDEN_ADAPTER" ]',
            BUILD)
        self.assertIn(
            "engines/build/arm64-v8a/liblucent_native_adapter_eden.so", BUILD)

    def test_every_phase3_asset_is_staged_only_under_the_flag(self):
        block = BUILD[BUILD.index('if [ "$INCLUDE_PHASE3_EDEN" = 1 ]; then\n    # Phase 3 stages'):]
        block = block[:block.index("\nfi\n")]
        for staged in ('"$DECODED/lib/arm64-v8a/liblucent_native_adapter_eden.so"',
                       '"$DECODED/assets/phase3-qualification-opt-in.json"',
                       '"$DECODED/assets/phase3-eden-source-lock.json"',
                       '"$DECODED/assets/phase3-engine-artifacts.json"'):
            self.assertIn(staged, block)
            self.assertEqual(1, BUILD.count(staged), staged)

    def test_the_manifest_is_count_gated_like_phase_1_and_2(self):
        self.assertIn("PHASE3_STAGED_ADAPTER_COUNT=0", BUILD)
        self.assertIn(
            "PHASE3_STAGED_ADAPTER_COUNT=$((PHASE3_STAGED_ADAPTER_COUNT + 1))",
            BUILD)
        self.assertIn('--expected-count "$PHASE3_STAGED_ADAPTER_COUNT"', BUILD)
        self.assertIn("--artifact-kind native-adapter", BUILD)
        # Every manifest generation stays count-gated, including the new one.
        self.assertEqual(BUILD.count("generate_engine_artifact_manifest.py"),
                         BUILD.count("--expected-count"))

    def test_the_apk_payload_is_verified_only_for_a_phase3_build(self):
        self.assertIn("verify_phase3_apk.py", BUILD)
        verifier_at = BUILD.index('python3 "$PROJECT_DIR/tools/verify_phase3_apk.py"')
        guard_at = BUILD.rindex('if [ "$INCLUDE_PHASE3_EDEN" = 1 ]; then', 0, verifier_at)
        self.assertLess(guard_at, verifier_at)

    def test_a_phase3_apk_is_named_distinctly_from_a_release(self):
        self.assertIn("lucent-$VERSION_NAME-phase3-qualification.apk", BUILD)
        self.assertIn("lucent-$VERSION_NAME-phase2-phase3-qualification.apk", BUILD)
        self.assertIn("phase3-qualification-$OUTPUT_SHA.apk", BUILD)

    def test_the_release_registry_asset_is_unconditional(self):
        # phase3-engine-registry.json ships in EVERY build; it is the authority
        # the catalog checks the opt-in against, and shipping it alone changes
        # nothing because the opt-in asset is absent.
        registry_copy = ('cp "$ROOT_DIR/engines/phase3-registry.json" '
                         '"$DECODED/assets/phase3-engine-registry.json"')
        self.assertIn(registry_copy, BUILD)
        self.assertLess(BUILD.index(registry_copy),
                        BUILD.index('if [ "$INCLUDE_PHASE3_EDEN" = 1 ]; then\n    # Phase 3 stages'))


class Phase3RoutingTest(unittest.TestCase):
    """Switch prefers INTERNAL only when a verified adapter is present."""

    def test_switch_is_its_own_canonical_system_id(self):
        resolver = _read(ROOT / "unified-android" / "src" / "com" / "thorium" /
                         "lucent" / "metadata" / "EngineSystemIdResolver.java")
        # No alias rewrites "switch", so the registry/opt-in id and the route
        # store key are the same string end to end.
        self.assertNotIn('"switch"', resolver)
        self.assertIn("return alias == null ? normalized : alias;", resolver)

    def test_the_router_falls_through_to_the_native_adapter_catalog(self):
        block = ROUTER[ROUTER.index("private static String engineIdForSystem"):]
        self.assertIn("InternalEngineCatalog.availableForSystem", block)
        self.assertIn("Phase2QualificationCatalog.libraryEngineIdForSystem", block)
        self.assertIn(
            "NativeAdapterCatalog.libraryEngineIdForSystem(context, normalized)",
            block)
        self.assertLess(
            block.index("Phase2QualificationCatalog.libraryEngineIdForSystem"),
            block.index("NativeAdapterCatalog.libraryEngineIdForSystem"))

    def test_internal_is_preferred_when_present_and_external_otherwise(self):
        self.assertIn("return internalAvailable ? INTERNAL : EXTERNAL;", ROUTE_STORE)
        # An explicit INTERNAL choice still degrades to EXTERNAL with no engine.
        self.assertIn("if (INTERNAL.equals(stored)) return internalAvailable ? INTERNAL : EXTERNAL;",
                      ROUTE_STORE)
        self.assertIn("if (INTERNAL.equals(normalized) && !hasInternalEngine(context, canonical)) return false;",
                      ROUTE_STORE)

    def test_launch_command_emits_the_internal_am_start_when_internal_wins(self):
        self.assertIn("return GameLaunchRouter.metadataCommand(context, canonical);",
                      ROUTE_STORE)
        self.assertIn("InWindowGameHost.ACTION_LAUNCH", ROUTER)
        # ImportManager is what actually writes launch: lines into metadata, and
        # it delegates the whole decision to EngineRouteStore.
        self.assertIn("return EngineRouteStore.launchCommand(context, system);",
                      IMPORT_MANAGER)

    def test_switch_keeps_a_real_external_route_when_no_adapter_is_bundled(self):
        self.assertIn('put("switch", contentUri("eden", "Eden"', EMULATOR_CATALOG)
        self.assertIn("EmulatorCatalog.externalLaunchCommand(", ROUTE_STORE)

    def test_the_catalog_gate_is_present_plus_hash_and_never_auto_selects(self):
        self.assertIn("context.getApplicationInfo().nativeLibraryDir", CATALOG)
        self.assertIn("InternalEngineCatalog.verifiedSha256(context, core)", CATALOG)
        self.assertIn('optIn.optBoolean("autoSelect", true)', CATALOG)
        self.assertIn("readAssetOrNull(context, OPT_IN)", CATALOG)
        self.assertIn("if (optInRaw == null) return result;", CATALOG)
        self.assertIn('"liblucent_native_adapter_" +', CATALOG)


class Phase3SystemDirectoryTest(unittest.TestCase):
    """Eden fails closed without a validated key/firmware directory."""

    def test_the_session_resolves_the_directory_from_reported_capabilities(self):
        self.assertIn("NativeAdapterSystemDirectory.resolve(appContext,", SESSION)
        self.assertIn("entry.id, request.systemId, capabilities.requiredFirmware)",
                      SESSION)
        # describe() must run before the resolve so requiredFirmware is real.
        self.assertLess(SESSION.index("capabilities = created.describe();"),
                        SESSION.index("NativeAdapterSystemDirectory.resolve("))
        # ...and the resolved directory is what reaches the adapter.
        self.assertIn("created.loadContent(system, saveDirectory, game.getPath());",
                      SESSION)

    def test_the_root_is_the_app_private_per_engine_directory(self):
        self.assertIn('context.getDir("engine-system", Context.MODE_PRIVATE), engine)',
                      SYSTEM_DIR)

    def test_an_engine_without_declared_firmware_gets_only_the_empty_root(self):
        self.assertIn("if (requiredFirmware <= 0) return root;", SYSTEM_DIR)

    def test_an_engine_with_no_audited_profile_fails_closed(self):
        self.assertIn("No user firmware profile is available for", SYSTEM_DIR)

    def test_missing_user_keys_or_firmware_fail_closed(self):
        self.assertIn('"A user-supplied " + REQUIRED_KEY + " is required', SYSTEM_DIR)
        self.assertIn("A user-supplied Switch firmware archive is required",
                      SYSTEM_DIR)
        self.assertIn(
            "Switch keys and system firmware are required but were not installed",
            SYSTEM_DIR)

    def test_the_eden_layout_matches_what_the_adapter_reads(self):
        # Common::FS::SetAppDirectory(root) makes Eden read keys/ and
        # nand/system/Contents/registered/ underneath it.
        self.assertIn('KEYS_DIRECTORY = "keys"', SYSTEM_DIR)
        self.assertIn('FIRMWARE_DIRECTORY = "nand/system/Contents/registered"',
                      SYSTEM_DIR)
        self.assertIn('REQUIRED_KEY = "prod.keys"', SYSTEM_DIR)
        adapter = ADAPTER_PATCH.read_text(encoding="utf-8")
        self.assertIn("Common::FS::SetAppDirectory(std::string(request->system_directory));",
                      adapter)
        self.assertIn("no validated key/firmware directory was supplied", adapter)

    def test_user_files_are_read_from_storage_and_never_from_assets(self):
        self.assertIn("Environment.getExternalStorageDirectory()", SYSTEM_DIR)
        self.assertIn('addDirectory(result, volume, "Games/switch");', SYSTEM_DIR)
        self.assertNotIn("getAssets()", SYSTEM_DIR)

    def test_firmware_extraction_cannot_escape_the_private_directory(self):
        # Only the entry's base name is ever used, and the parent is re-checked.
        self.assertIn("if (!registered.equals(destination.getParentFile())) continue;",
                      SYSTEM_DIR)
        self.assertIn("String base = name.substring(name.lastIndexOf('/') + 1);",
                      SYSTEM_DIR)

    def test_a_split_nca_is_concatenated_rather_than_truncated(self):
        # A NAND-derived archive stores one NCA as <id>.nca/00, /01, ... Writing
        # only the last fragment would install a silently corrupt firmware file.
        self.assertIn("writeFragments(zip, fragments, destination);", SYSTEM_DIR)
        self.assertIn("java.util.Collections.sort(fragments, (left, right) ->",
                      SYSTEM_DIR)

    def test_an_installed_firmware_set_is_not_reinstalled_every_launch(self):
        self.assertIn('FIRMWARE_MARKER = ".lucent-firmware-source"', SYSTEM_DIR)
        self.assertIn("if (countFirmware(registered) > 0 &&", SYSTEM_DIR)


if __name__ == "__main__":
    unittest.main()
