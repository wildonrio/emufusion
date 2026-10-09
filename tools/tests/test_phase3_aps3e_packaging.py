"""Pinned host gates for the qualification-only internal PS3 adapter."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMIT = "b5ae1af50d5e2f3b705506e7380a4504e086840b"
LIBRARY = "liblucent_native_adapter_aps3e.so"
STAGED = ROOT / "engines" / "build" / "arm64-v8a" / LIBRARY
LOCK_PATH = ROOT / "engines" / "aps3e-source-lock.json"
ADAPTER_PATH = ROOT / "engines" / "patches" / "aps3e-lucent-adapter.cpp"
TAGGED_POINTER_PATCH = (ROOT / "engines" / "patches" /
                        "aps3e-android-tagged-atomic-ptr.patch")
REGISTRY = json.loads((ROOT / "engines" / "phase3-registry.json").read_text())
OPT_IN = json.loads((ROOT / "engines" / "phase3-qualification-opt-in.json").read_text())
LOCK = json.loads(LOCK_PATH.read_text())
BUILD = (ROOT / "unified-android" / "build.sh").read_text()
HOST = (ROOT / "unified-android" / "native" /
        "lucent_native_adapter_host.c").read_text()
HOST_HEADER = (ROOT / "unified-android" / "native" / "include" /
               "lucent_native_adapter_host.h").read_text()
SYSTEM_DIR = (ROOT / "unified-android" / "src" / "com" / "thorium" /
              "preview" / "game" / "NativeAdapterSystemDirectory.java").read_text()
SESSION = (ROOT / "unified-android" / "src" / "com" / "thorium" /
           "preview" / "game" / "NativeAdapterEngineSession.java").read_text()
DEVICE_QA = (ROOT / "docs" / "phase3-aps3e-device-qa.md").read_text()

spec = importlib.util.spec_from_file_location(
    "phase3_verifier", ROOT / "unified-android" / "tools" /
    "verify_phase3_apk.py")
VERIFIER = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(VERIFIER)


def row(rows, key, value):
    matches = [item for item in rows if item.get(key) == value]
    assert len(matches) == 1
    return matches[0]


class Aps3eIdentityTest(unittest.TestCase):
    def test_registry_opt_in_and_lock_share_one_exact_identity(self):
        registry = row(REGISTRY["engines"], "id", "aps3e")
        enabled = row(OPT_IN["engines"], "id", "aps3e")
        self.assertEqual(COMMIT, registry["source"]["commit"])
        self.assertEqual(COMMIT, enabled["commit"])
        self.assertEqual(COMMIT, LOCK["core"]["commit"])
        self.assertEqual(["ps3"], registry["systems"])
        self.assertEqual(["ps3"], enabled["libraryRouteSystems"])
        self.assertFalse(registry["shipped"])
        self.assertTrue(all(value is False for value in registry["gates"].values()))

    def test_source_archive_and_build_are_pinned_without_overclaiming(self):
        self.assertEqual(
            "37fb172d3cd115aa13b29571710f8223c19783ead44cd174f64d686911533ee1",
            LOCK["core"]["archiveSha256"])
        self.assertEqual(102044362, LOCK["core"]["archiveBytes"])
        self.assertEqual("PASS", LOCK["build"]["sourceBuildResult"])
        self.assertFalse(LOCK["reproducible"])
        self.assertFalse(LOCK["dependencies"]["completeLicenseAudit"])

    def test_every_recorded_patch_is_the_checked_in_file(self):
        for patch in LOCK["patches"]:
            target = ROOT / patch["path"]
            self.assertTrue(target.is_file(), target)
            self.assertEqual(patch["bytes"], target.stat().st_size)
            self.assertEqual(patch["sha256"],
                             hashlib.sha256(target.read_bytes()).hexdigest())

    def test_staged_release_adapter_matches_the_lock(self):
        # Uncommitted, build-Mac-only input (see tools/run_ci_tests.py).
        for needed in (STAGED,):
            if not needed.exists():
                self.skipTest("local-only input absent: " + str(needed))
        self.assertTrue(STAGED.is_file())
        self.assertEqual(LOCK["artifact"]["bytes"], STAGED.stat().st_size)
        self.assertEqual(LOCK["artifact"]["sha256"],
                         hashlib.sha256(STAGED.read_bytes()).hexdigest())
        self.assertEqual("0x4000", LOCK["artifact"]["ptLoadAlignment"])
        self.assertEqual("lucent_native_adapter_entry",
                         LOCK["artifact"]["requiredExport"])

    def test_adapter_exposes_ps3_lifecycle_controls_and_savestate(self):
        source = ADAPTER_PATH.read_text()
        self.assertIn('out->engine_id = "aps3e";', source)
        self.assertIn("out->required_firmware = 1;", source)
        self.assertIn("Emu.Kill(false, true);", source)
        self.assertIn("Emu.BootGame(incoming.string()", source)
        self.assertIn("case LUCENT_PAD_A: return kCross;", source)
        self.assertIn("case LUCENT_PAD_B: return kCircle;", source)
        self.assertIn("android_get_device_api_level()", source)
        self.assertIn("lucent_native_adapter_set_java_vm", source)
        self.assertIn("version != 1u || !java_vm", source)
        self.assertIn("g_jvm = static_cast<JavaVM*>(java_vm);", source)

    def test_firmware_install_target_and_fd_ownership_fail_closed(self):
        source = ADAPTER_PATH.read_text()
        sentinel = 'flash / "vsh/etc/version.txt"'
        create = "std::filesystem::create_directories(flash, ec)"
        install = "ae::install_firmware(fd)"
        self.assertIn(sentinel, source)
        self.assertIn(create, source)
        self.assertIn("if (!created_flash)", source)
        self.assertIn("PS3 firmware installation is incomplete", source)
        self.assertLess(source.index(create), source.index(install))
        self.assertIn("std::filesystem::remove_all(flash, cleanup_error)", source)
        self.assertGreaterEqual(
            source.count("std::filesystem::remove_all(flash, cleanup_error)"), 4)
        self.assertIn("if (!readable_file(firmware_version))", source)
        # fs::file::from_fd owns the descriptor; the adapter must not close it
        # after ownership transfer or risk closing a newly-reused fd.
        install_block = source[source.index(install):source.index(
            "if (!std::filesystem::exists(engine->content_path", source.index(install))]
        self.assertNotIn("close(fd)", install_block)

    def test_android_atomic_pointer_preserves_tag_and_bounds_borrows(self):
        source = TAGGED_POINTER_PATCH.read_text()
        self.assertIn(
            "#if defined(__ANDROID__) && UINTPTR_MAX == UINT64_MAX", source)
        self.assertIn("tag_mask = 0xff00000000000000ull", source)
        self.assertIn("middle_address_mask = 0x00ffff0000000000ull", source)
        self.assertIn("low_address_mask = 0x000000ffffffffffull", source)
        self.assertIn("metadata_bits = 16", source)
        self.assertIn("ensure(utils::android_tagged_ptr::can_pack(raw))", source)
        self.assertGreaterEqual(
            source.count("ensure((val & c_ref_mask) != c_ref_mask)"), 3)

        raw = 0xb400006e71f18c90
        address_mask = 0x000000ffffffffff
        tag_mask = 0xff00000000000000
        encoded = (raw & tag_mask) | ((raw & address_mask) << 16)
        decoded = (encoded & tag_mask) | ((encoded >> 16) & address_mask)
        self.assertEqual(raw, decoded)
        self.assertEqual(0, encoded & 0xffff)
        self.assertEqual(0, raw & 0x00ffff0000000000)
        self.assertNotEqual(0, 0xb401006e71f18c90 & 0x00ffff0000000000)

    def test_atomic_pointer_paths_use_helpers_and_non_android_is_unchanged(self):
        source = TAGGED_POINTER_PATCH.read_text()
        added = "\n".join(line[1:] for line in source.splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
        self.assertIn("metadata_bits = 16", source)
        self.assertIn("return raw << c_ref_size;", source)
        self.assertIn("return val >> c_ref_size;", source)
        for helper in ("encode_pointer(ptr)", "decode_pointer(val)",
                       "same_pointer(val, prev)", "same_pointer(val, _old)",
                       "ptr_to(old.m_val.raw())", "to_val(exch.m_ptr)"):
            self.assertIn(helper, source)
        for stale in ("val >> c_ref_size == prev >> c_ref_size",
                      "_new << c_ref_size",
                      "reinterpret_cast<T*>(m_val >> c_ref_size)"):
            self.assertNotIn(stale, added)

    def test_android_lock_free_queue_uses_the_same_tagged_layout(self):
        source = TAGGED_POINTER_PATCH.read_text()
        self.assertIn("utils::android_tagged_ptr::unpack(value)", source)
        self.assertIn("utils::android_tagged_ptr::pack(raw)", source)
        self.assertIn("m_head.compare_exchange(oldv, store(item))", source)
        self.assertGreaterEqual(
            source.count("ensure(utils::android_tagged_ptr::can_pack(raw))"), 2)

        raw = 0xb400006e71f18c90
        packed = (raw & 0xff00000000000000) | (
            (raw & 0x000000ffffffffff) << 16)
        unpacked = (packed & 0xff00000000000000) | (
            (packed >> 16) & 0x000000ffffffffff)
        self.assertEqual(raw, unpacked)

        # The non-Android branch retains the pinned 48+16 encoding exactly.
        self.assertIn("return reinterpret_cast<u64>(item) << 16;", source)
        self.assertIn(
            "return reinterpret_cast<lf_queue_item<T>*>(value >> 16);", source)

    def test_versioned_java_vm_handoff_precedes_activity_jni_fallback(self):
        self.assertIn('"lucent_native_adapter_set_java_vm"', HOST_HEADER)
        self.assertIn("LUCENT_NATIVE_ADAPTER_JAVA_VM_VERSION 1u", HOST_HEADER)
        setter = HOST.index("setter_symbol = dlsym")
        fallback = HOST.index('on_load_symbol = dlsym(library, "JNI_OnLoad")')
        self.assertLess(setter, fallback)
        self.assertIn("if (!accepted)", HOST[setter:fallback])
        self.assertIn("adapter rejected JavaVM handoff version", HOST[setter:fallback])
        self.assertIn("version = on_load((JavaVM *)adapter_java_vm, NULL);",
                      HOST[fallback:])

    def test_device_checkpoint_binds_exact_partial_evidence_without_shipping(self):
        for identity in (
                "38e7d4da6b92042d06740030b39d54fd543cc75138f6f7ad5d62cdc347743980",
                "2a5573bb9d0524f1a6296a775f30f4abbd03bb31a44e435d019bbfaf19b21767",
                "80948c636546759b69703a3e0f94a82a56eeb05d",
                "99c044293290d0338ffee4ea7d21f993523b1b69012af7f09ae719efe2c9d464",
                "1544e5ca7de6a56663b28ed706d2500cba009b54573922f3a2dfd576ec30c8e5",
                "53610a67cbe5a340a5f817e4e02e79c32dcd8039c1fb8fbfda95b6b7f59d2185",
                "native-pixel-refined-regional-flow-v21-content-unique"):
            self.assertIn(identity, DEVICE_QA)
        self.assertIn("Frame generation is **not qualified**", DEVICE_QA)
        self.assertIn("Physical AYN controls", DEVICE_QA)
        self.assertIn("device media volume was `0/15`", DEVICE_QA)
        registry = row(REGISTRY["engines"], "id", "aps3e")
        self.assertFalse(registry["shipped"])
        self.assertTrue(all(value is False for value in registry["gates"].values()))
        self.assertNotIn("not present on the Thor", registry["blocker"])


class Aps3eRuntimeGateTest(unittest.TestCase):
    def test_aps3e_environment_is_fail_closed_before_dlopen(self):
        self.assertIn('if (!"aps3e".equals(engine)) return null;', SYSTEM_DIR)
        self.assertIn('PS3_LAYOUT.matches(engine, normalize(systemId))', SYSTEM_DIR)
        self.assertIn('File root = engineRoot(context, engine, qualificationSession);', SYSTEM_DIR)
        self.assertIn('new File(root, "logs")', SYSTEM_DIR)
        self.assertIn('new File(root, "config")', SYSTEM_DIR)
        self.assertIn('new File(root, "cache")', SYSTEM_DIR)
        self.assertIn('Os.setenv("APS3E_DATA_DIR", root.getCanonicalPath(), true);',
                      SYSTEM_DIR)
        self.assertIn('Os.setenv("APS3E_GLOBAL_CONFIG_YAML_PATH",', SYSTEM_DIR)
        self.assertIn('Integer.toString(Build.VERSION.SDK_INT)', SYSTEM_DIR)

        prepare = SESSION.index("NativeAdapterSystemDirectory.prepareForOpen")
        dlopen = SESSION.index("new NativeAdapterHost(entry.coreFile, trusted)")
        self.assertLess(prepare, dlopen)
        guarded = SESSION.rfind('if ("aps3e".equals(entry.id))', 0, prepare)
        self.assertGreaterEqual(guarded, 0)
        self.assertIn('logLaunchPhase("adapter-preopen-environment"',
                      SESSION[guarded:dlopen])
        # No other Phase 3 engine gets process-global aPS3e paths.
        self.assertNotIn('"eden".equals(entry.id)', SESSION[guarded:dlopen])
        self.assertNotIn('"cemu".equals(entry.id)', SESSION[guarded:dlopen])

    def test_internal_ps3_requires_owner_firmware_and_never_assets(self):
        self.assertIn('PS3_UPDATE = "PS3UPDAT.PUP"', SYSTEM_DIR)
        self.assertIn('"aps3e", new String[] {"ps3"}', SYSTEM_DIR)
        self.assertIn('new RuntimeFile(PS3_UPDATE, PS3_UPDATE, true, "Games/ps3/Firmware")',
                      SYSTEM_DIR)
        self.assertIn("hasPs3Update(file)", SYSTEM_DIR)
        self.assertNotIn("getAssets()", SYSTEM_DIR)
        enabled = row(OPT_IN["engines"], "id", "aps3e")
        self.assertFalse(enabled["userSuppliedRuntimeInputs"]["bundledInApk"])

    def test_build_in_ps3_default_uses_the_general_verifier(self):
        self.assertIn("INCLUDE_PHASE3_APS3E=${LUCENT_INCLUDE_PHASE3_APS3E:-1}", BUILD)
        self.assertIn('if [ "$INCLUDE_PHASE3_APS3E" = 1 ]; then', BUILD)
        self.assertIn('"$DECODED/assets/phase3-aps3e-source-lock.json"', BUILD)
        self.assertIn('"$DECODED/assets/phase3-aps3e-lucent-adapter.cpp"', BUILD)
        self.assertIn('"$DECODED/assets/LICENSE-GPL-2.0-APS3E.txt"', BUILD)
        verifier = BUILD.index('python3 "$PROJECT_DIR/tools/verify_phase3_apk.py"')
        guard = BUILD.rindex('if [ "$INCLUDE_PHASE3_ANY" = 1 ]; then', 0, verifier)
        self.assertLess(guard, verifier)

    def _payload(self, *, include_firmware=False):
        binary = STAGED.read_bytes()
        identity = {
            "engineId": "aps3e", "fileName": LIBRARY,
            "sourceCommit": COMMIT,
            "sha256": hashlib.sha256(binary).hexdigest(),
        }
        payload = {
            "assets/phase3-engine-registry.json": json.dumps(REGISTRY).encode(),
            "assets/phase3-qualification-opt-in.json": json.dumps(OPT_IN).encode(),
            "assets/phase3-engine-artifacts.json": json.dumps({
                "schemaVersion": 1, "artifacts": [identity]}).encode(),
            "assets/phase3-aps3e-source-lock.json": json.dumps(LOCK).encode(),
            "assets/phase3-aps3e-lucent-adapter.cpp": ADAPTER_PATH.read_bytes(),
            "assets/LICENSE-GPL-2.0-APS3E.txt":
                (ROOT / "engines" / "compliance" / "aps3e" /
                 "GPL-2.0-only.txt").read_bytes(),
            "lib/arm64-v8a/" + LIBRARY: binary,
        }
        if include_firmware:
            payload["assets/PS3UPDAT.PUP"] = b"forbidden"
        return payload

    def _verify(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "phase3.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                for name, data in payload.items():
                    archive.writestr(name, data)
            return VERIFIER.verify(apk)

    def test_aps3e_only_qualification_payload_verifies(self):
        self.assertEqual([], self._verify(self._payload()))

    def test_ps3_firmware_inside_the_apk_is_rejected(self):
        errors = self._verify(self._payload(include_firmware=True))
        self.assertTrue(any("keys/firmware are unexpectedly bundled" in error
                            for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
