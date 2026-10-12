import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "unified-android" / "tools" / "verify_menu_route_closure.py"
SPEC = importlib.util.spec_from_file_location("menu_route_closure", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class MenuRouteClosureTest(unittest.TestCase):
    def make_apk(self, *, include_core=True, correct_hash=True,
                 auto_select=True, core=b"exact-test-core",
                 include_libcxx=False) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory()
        apk = Path(temporary.name) / "lucent.apk"
        expected = hashlib.sha256(core).hexdigest()
        if not correct_hash:
            expected = "0" * 64
        registry = {
            "schemaVersion": 1,
            "engines": [{
                "id": "mesen", "status": "experimental", "shipped": False,
                "systems": ["nes"], "state": {"qualified": False},
                "build": {"reproducible": False},
            }],
        }
        opt_in = {
            "schemaVersion": 1, "qualificationOnly": True,
            "autoSelect": auto_select,
            "engines": [{
                "id": "mesen", "commit": "1" * 40,
                "libraryName": "liblucent_core_mesen.so",
            }],
        }
        artifacts = {
            "schemaVersion": 1,
            "artifacts": [{
                "engineId": "mesen", "fileName": "liblucent_core_mesen.so",
                "sha256": expected, "sourceCommit": "1" * 40,
            }],
        }
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("assets/engine-registry.json", json.dumps(registry))
            archive.writestr("assets/engine-qualification-opt-in.json", json.dumps(opt_in))
            archive.writestr("assets/engine-artifacts.json", json.dumps(artifacts))
            archive.writestr("classes.dex", b"dex\n035\0")
            if include_core:
                archive.writestr("lib/arm64-v8a/liblucent_core_mesen.so", core)
            if include_libcxx:
                archive.writestr("lib/arm64-v8a/libc++_shared.so",
                                 b"\x7fELFruntime")
        return temporary, apk

    def verify(self, apk: Path, bootstrap=(True, "factory present")):
        routes = {MODULE.Route("nes", "mesen")}
        with mock.patch.object(MODULE, "dex_bootstrap_evidence",
                               return_value=bootstrap):
            return MODULE.verify(apk, routes, Path("unused-dexdump"))

    def test_extracts_installed_metadata_route_without_exposing_game_paths(self):
        command = (
            'am start '
            '-a com.thorium.preview.LAUNCH_INTERNAL_GAME '
            '-n com.thorium.preview/org.pegasus_frontend.android.MainActivity '
            '--es path "{file.path}" --es system nes --es engine_id mesen'
        )
        routes = MODULE.routes_from_text(
            command + '\n'
            'file: /storage/emulated/0/Games/nes/private-title.nes\n'
        )
        self.assertEqual(routes, {MODULE.Route("nes", "mesen")})
        self.assertEqual(MODULE.invalid_launch_lines(command), [])
        self.assertEqual(MODULE.launcher_audit(command)[0]["kind"],
                         "intercepted-same-activity-start")

    def test_cross_user_flag_is_rejected_for_app_uid_menu_execution(self):
        command = (
            "am start --user 0 "
            "-a com.thorium.preview.LAUNCH_INTERNAL_GAME "
            "-n com.thorium.preview/org.pegasus_frontend.android.MainActivity "
            "--es system nes --es engine_id mesen"
        )
        failure = MODULE.invalid_launch_lines(command)[0]
        self.assertIn("forbidden cross-user", failure["reason"])

    def test_same_activity_start_without_internal_action_is_stale(self):
        command = (
            "am start -n com.thorium.preview/"
            "org.pegasus_frontend.android.MainActivity "
            "--es system nes --es engine_id mesen"
        )
        audit = MODULE.launcher_audit(command)
        self.assertEqual(audit[0]["kind"], "stale-am-start")
        self.assertFalse(audit[0]["pass"])

    def test_prior_broadcast_route_is_recorded_as_stale_for_migration(self):
        command = (
            "am broadcast -a com.thorium.preview.LAUNCH_INTERNAL_GAME "
            "-n com.thorium.preview/com.thorium.preview.GameLaunchReceiver "
            "--es system nes --es engine_id mesen"
        )
        audit = MODULE.launcher_audit(command)
        self.assertEqual(audit[0]["kind"], "stale-am-broadcast")
        self.assertFalse(audit[0]["pass"])

    def test_external_view_routes_accept_any_scheme(self):
        # Install pages (https/market) and emulator deep links (dolphinemu://)
        # are all legitimate external VIEW routes.
        for uri in ("https://github.com/x/releases",
                    "market://details?id=com.PceEmu",
                    "dolphinemu://game?path=/storage/emulated/0/g.rvz"):
            command = "am start -a android.intent.action.VIEW -d " + uri
            audit = MODULE.launcher_audit(command)
            self.assertEqual(audit[0]["kind"], "external-route", uri)
            self.assertTrue(audit[0]["pass"], uri)
            self.assertEqual([], MODULE.invalid_launch_lines(command), uri)

    def test_external_component_route_is_now_accepted(self):
        # Per-system EXTERNAL routing: a direct am-start into a foreign
        # emulator component is a valid product route.
        command = 'am start -n com.example.external/.Game --es path /private/game.rom'
        audit = MODULE.launcher_audit(command)
        self.assertEqual(audit[0]["kind"], "external-route")
        self.assertTrue(audit[0]["pass"])
        self.assertEqual([], MODULE.invalid_launch_lines(command))

    def test_incomplete_launcher_is_rejected_with_path_redacted(self):
        # A bare am-broadcast is neither the internal route nor an external one.
        command = 'am broadcast -n com.example.external/.Game --es path /private/game.rom'
        failures = MODULE.invalid_launch_lines(command)
        self.assertEqual(len(failures), 1)
        self.assertNotIn("private", json.dumps(failures))

    def test_stale_same_activity_am_start_route_is_rejected(self):
        stale = (
            "am start -n com.thorium.preview/"
            "org.pegasus_frontend.android.MainActivity "
            "--es path {file.path} --es system nes --es engine_id mesen"
        )
        failures = MODULE.invalid_launch_lines(stale)
        self.assertEqual(len(failures), 1)
        self.assertIn("internal launch action", failures[0]["reason"])

    def test_device_scan_skips_absent_metadata_roots_and_quotes_remote_program(self):
        command = MODULE.device_route_command()
        self.assertIn('[ -d "$root" ] || continue', command)
        self.assertIn('find "$root"', command)
        self.assertIn("! -path '*/backups/*'", command)
        self.assertIn("/^game:/{header=0; next}", command)
        route = (
            "am start -a com.thorium.preview.LAUNCH_INTERNAL_GAME "
            "-n com.thorium.preview/org.pegasus_frontend.android.MainActivity "
            "--es path {file.path} --es system nes --es engine_id mesen\n"
        )
        completed = unittest.mock.Mock(stdout=route)
        with unittest.mock.patch.object(MODULE.subprocess, "run",
                                        return_value=completed) as invoked:
            result = MODULE.device_route_text(Path("/tmp/adb"), "thor-test")
        self.assertEqual(result, route)
        argv = invoked.call_args.args[0]
        self.assertEqual(argv[:4], ["/tmp/adb", "-s", "thor-test", "shell"])
        self.assertEqual(len(argv), 5)
        self.assertTrue(argv[4].startswith("sh -c "))
        self.assertIn("continue", argv[4])
        self.assertTrue(invoked.call_args.kwargs["check"])

    def test_host_only_metadata_simulates_candidate_routes_from_shortnames(self):
        temporary, apk = self.make_apk()
        self.addCleanup(temporary.cleanup)
        metadata = """collection: Nintendo Entertainment System
shortname: nes
game: A Game
collection: PlayStation 3
shortname: ps3
game: A Future Game
"""
        systems = MODULE.collection_shortnames(metadata)
        self.assertEqual(systems, {"nes", "ps3"})
        with unittest.mock.patch.object(MODULE, "dex_bootstrap_evidence",
                                        return_value=(True, "factory present")), \
                unittest.mock.patch.object(MODULE, "dex_alias_contract_evidence",
                                            return_value=(True, "aliases present")):
            routes, report = MODULE.simulate_candidate_routes(
                apk, systems, Path("unused-dexdump")
            )
        self.assertEqual(routes, {MODULE.Route("nes", "mesen")})
        self.assertEqual(report["unsupportedPhase3Systems"], ["ps3"])
        self.assertEqual(report["unsupportedOtherSystems"], [])
        self.assertEqual(report["mode"], "candidate-GameLaunchRouter-simulation")

    def test_live_shortname_alias_contract(self):
        self.assertEqual(MODULE.canonical_system_id("gc"), "gamecube")
        self.assertEqual(MODULE.canonical_system_id("n3ds"), "3ds")
        self.assertEqual(MODULE.canonical_system_id("genesis"), "megadrive")
        self.assertEqual(MODULE.canonical_system_id("nds"), "nds")

    def test_collection_header_parser_ignores_game_body_and_launch_parser_still_works(self):
        metadata = """collection: NES
shortname: nes
launch: am start -a com.thorium.preview.LAUNCH_INTERNAL_GAME -n com.thorium.preview/org.pegasus_frontend.android.MainActivity --es system nes --es engine_id mesen
game: Private Title
launch: external-command-owned-by-game
"""
        self.assertEqual(MODULE.collection_shortnames(metadata), {"nes"})
        self.assertEqual(MODULE.routes_from_text(metadata),
                         {MODULE.Route("nes", "mesen")})

    def test_locked_alias_map_and_required_live_shortname_routes(self):
        self.assertEqual(MODULE.alias_map_sha256(),
                         MODULE.SYSTEM_SHORTNAME_ALIASES_SHA256)
        self.assertEqual(MODULE.canonical_system_id("gc"), "gamecube")
        self.assertEqual(MODULE.canonical_system_id("n3ds"), "3ds")
        self.assertEqual(MODULE.canonical_system_id("genesis"), "megadrive")
        pairs = [
            ("phase1", MODULE.Route("megadrive", "blastem")),
            ("phase2", MODULE.Route("gamecube", "dolphin")),
            ("phase2", MODULE.Route("3ds", "azahar")),
        ]
        qualified = {
            "routes": [{"system": route.system, "engine": route.engine,
                        "pass": True} for _phase, route in pairs]
        }
        with unittest.mock.patch.object(MODULE, "dex_alias_contract_evidence",
                                        return_value=(True, "aliases present")), \
                unittest.mock.patch.object(MODULE, "candidate_route_pairs",
                                            return_value=pairs), \
                unittest.mock.patch.object(MODULE, "verify",
                                            return_value=([], qualified)):
            routes, report = MODULE.simulate_candidate_routes(
                Path("candidate.apk"), {"gc", "n3ds", "genesis"},
                Path("dexdump"),
            )
        self.assertEqual(routes, {
            MODULE.Route("gamecube", "dolphin"),
            MODULE.Route("3ds", "azahar"),
            MODULE.Route("megadrive", "blastem"),
        })
        self.assertEqual(report["aliasContractFailures"], [])
        self.assertTrue(all(row["pass"] for row in report["requiredAliasRoutes"]))

    def test_exact_apk_alias_dex_gate_rejects_router_without_canonical_call(self):
        temporary, apk = self.make_apk()
        self.addCleanup(temporary.cleanup)
        literals = "\n".join(
            f'0000: const-string v0, "{value}"'
            for pair in MODULE.SYSTEM_SHORTNAME_ALIASES.items() for value in pair
        )
        good = f"""Class descriptor  : 'Lcom/thorium/preview/GameLaunchRouter;'
    #0 : (in Lcom/thorium/preview/GameLaunchRouter;)
[0000] com.thorium.preview.GameLaunchRouter.metadataCommand:
0000: invoke-static {{v0}}, Lcom/thorium/emufusion/metadata/EngineSystemIdResolver;.canonical:(Ljava/lang/String;)Ljava/lang/String;
  Virtual methods   -
Class #997 -
Class descriptor  : 'Lcom/thorium/emufusion/metadata/MetadataGameLaunchCommand;'
0000: const-string v0, "am start -a "
0002: const-string v1, "org.pegasus_frontend.android.MainActivity"
  Virtual methods   -
Class #998 -
Class descriptor  : 'Lcom/thorium/preview/InProcessGameLaunchCommand;'
0000: invoke-static {{v0, v1}}, Lcom/thorium/preview/game/InWindowGameHost;.handleIntent:(Landroid/app/Activity;Landroid/content/Intent;)Z
  Virtual methods   -
Class #998 -
Class descriptor  : 'Lorg/pegasus_frontend/android/MainActivity;'
[0000] org.pegasus_frontend.android.MainActivity.launchAmCommand:
0000: invoke-static {{v0}}, Lcom/thorium/preview/InProcessGameLaunchCommand;.tryLaunch:([Ljava/lang/String;)Z
  Virtual methods   -
Class #998 -
Class descriptor  : 'Lcom/thorium/emufusion/metadata/EngineSystemIdResolver;'
{literals}
  Virtual methods   -
Class #999 -
"""
        completed = unittest.mock.Mock(stdout=good.encode("utf-8"))
        with unittest.mock.patch.object(MODULE.subprocess, "run",
                                        return_value=completed):
            passed, _ = MODULE.dex_alias_contract_evidence(apk, Path("dexdump"))
        self.assertTrue(passed)
        bad = good.replace(";.canonical:", ";.normalize:")
        completed.stdout = bad.encode("utf-8")
        with unittest.mock.patch.object(MODULE.subprocess, "run",
                                        return_value=completed):
            passed, detail = MODULE.dex_alias_contract_evidence(apk, Path("dexdump"))
        self.assertFalse(passed)
        self.assertIn("does not invoke", detail)

        stale = good.replace(
            "Lcom/thorium/preview/InProcessGameLaunchCommand;.tryLaunch:",
            "Lcom/thorium/preview/InProcessGameLaunchCommand;.notIntercepted:",
        )
        completed.stdout = stale.encode("utf-8")
        with unittest.mock.patch.object(MODULE.subprocess, "run",
                                        return_value=completed):
            passed, detail = MODULE.dex_alias_contract_evidence(apk, Path("dexdump"))
        self.assertFalse(passed)
        self.assertIn("interception hook", detail)

    def test_exact_registered_core_and_factory_pass(self):
        temporary, apk = self.make_apk()
        self.addCleanup(temporary.cleanup)
        errors, report = self.verify(apk)
        self.assertEqual(errors, [])
        self.assertTrue(report["pass"])

    def test_missing_core_fails_before_device_launch(self):
        temporary, apk = self.make_apk(include_core=False)
        self.addCleanup(temporary.cleanup)
        errors, _ = self.verify(apk)
        self.assertTrue(any("core library is absent" in error for error in errors))

    def test_core_hash_mismatch_fails_before_device_launch(self):
        temporary, apk = self.make_apk(correct_hash=False)
        self.addCleanup(temporary.cleanup)
        errors, _ = self.verify(apk)
        self.assertTrue(any("core hash differs" in error for error in errors))

    def test_missing_bootstrap_factory_fails_before_device_launch(self):
        temporary, apk = self.make_apk()
        self.addCleanup(temporary.cleanup)
        errors, _ = self.verify(apk, (False, "factory absent"))
        self.assertTrue(any("bootstrap factory" in error for error in errors))

    def test_qualification_auto_select_false_rejects_stale_menu_route(self):
        temporary, apk = self.make_apk(auto_select=False)
        self.addCleanup(temporary.cleanup)
        errors, _ = self.verify(apk)
        self.assertTrue(any("not eligible for a normal menu route" in error
                            for error in errors))

    def test_packaged_libcxx_abi_mismatch_fails_before_device_launch(self):
        temporary, apk = self.make_apk(
            core=b"\x7fELFcore", include_libcxx=True
        )
        self.addCleanup(temporary.cleanup)
        missing = b"                 U _ZTTNSt6__ndk118basic_stringstreamIcE\n"
        provided = b"0000000000000000 T _ZNSt6__ndk16vectorIiE3popEv\n"
        runs = [mock.Mock(returncode=0, stdout=missing),
                mock.Mock(returncode=0, stdout=provided)]
        with mock.patch.object(MODULE, "llvm_nm_tool", return_value=Path("llvm-nm")), \
                mock.patch.object(MODULE.subprocess, "run", side_effect=runs):
            with zipfile.ZipFile(apk) as archive:
                passed, detail = MODULE.libcxx_abi_evidence(
                    archive, "lib/arm64-v8a/liblucent_core_mesen.so"
                )
        self.assertFalse(passed)
        self.assertIn("runtime ABI misses 1 required symbol", detail)

    def test_packaged_libcxx_exact_symbol_closure_passes(self):
        temporary, apk = self.make_apk(
            core=b"\x7fELFcore", include_libcxx=True
        )
        self.addCleanup(temporary.cleanup)
        symbol = "_ZTTNSt6__ndk118basic_stringstreamIcE"
        runs = [mock.Mock(returncode=0, stdout=f" U {symbol}\n".encode()),
                mock.Mock(returncode=0,
                          stdout=f"0000 T {symbol}\n".encode())]
        with mock.patch.object(MODULE, "llvm_nm_tool", return_value=Path("llvm-nm")), \
                mock.patch.object(MODULE.subprocess, "run", side_effect=runs):
            with zipfile.ZipFile(apk) as archive:
                passed, detail = MODULE.libcxx_abi_evidence(
                    archive, "lib/arm64-v8a/liblucent_core_mesen.so"
                )
        self.assertTrue(passed)
        self.assertIn("resolves 1", detail)


if __name__ == "__main__":
    unittest.main()
