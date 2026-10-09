import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "unified-android" / "tools" / "verify_one_app_apk.py"
SPEC = importlib.util.spec_from_file_location("one_app_verifier", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


MANIFEST = '''
E: manifest
  A: package="com.thorium.preview" (Raw: "com.thorium.preview")
  E: uses-permission
    A: android:name="android.permission.RECORD_AUDIO" (Raw: "android.permission.RECORD_AUDIO")
  E: application
    A: android:label="EmuFusion" (Raw: "EmuFusion")
    A: android:name="com.thorium.preview.LucentApplication" (Raw: "com.thorium.preview.LucentApplication")
    E: activity
      A: android:name="org.pegasus_frontend.android.MainActivity" (Raw: "org.pegasus_frontend.android.MainActivity")
      A: android:launchMode(0x0101001d)=(type 0x10)0x2
      E: intent-filter
        E: action
          A: android:name="android.intent.action.MAIN" (Raw: "android.intent.action.MAIN")
        E: category
          A: android:name="android.intent.category.LAUNCHER" (Raw: "android.intent.category.LAUNCHER")
    E: activity
      A: android:name="com.thorium.preview.PreviewActivity" (Raw: "com.thorium.preview.PreviewActivity")
      A: android:exported(0x01010010)=(type 0x12)0x0
      A: android:taskAffinity="com.thorium.preview.preview" (Raw: "com.thorium.preview.preview")
      A: android:excludeFromRecents(0x01010017)=(type 0x12)0xffffffff
    E: activity
      A: android:name="com.thorium.preview.BrowserActivity" (Raw: "com.thorium.preview.BrowserActivity")
      A: android:exported(0x01010010)=(type 0x12)0x0
    E: activity
      A: android:name="com.thorium.preview.VoiceFeedbackActivity" (Raw: "com.thorium.preview.VoiceFeedbackActivity")
      A: android:exported(0x01010010)=(type 0x12)0x0
      A: android:excludeFromRecents(0x01010017)=(type 0x12)0xffffffff
      A: android:noHistory(0x01010016)=(type 0x12)0xffffffff
    E: activity
      A: android:name="com.thorium.preview.FrontendRestartActivity" (Raw: "com.thorium.preview.FrontendRestartActivity")
      A: android:exported(0x01010010)=(type 0x12)0x0
      A: android:excludeFromRecents(0x01010017)=(type 0x12)0xffffffff
      A: android:noHistory(0x01010016)=(type 0x12)0xffffffff
      A: android:process=":frontend_restart" (Raw: ":frontend_restart")
    E: service
      A: android:name="com.thorium.preview.ExternalStopAccessibilityService" (Raw: "com.thorium.preview.ExternalStopAccessibilityService")
      A: android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE" (Raw: "android.permission.BIND_ACCESSIBILITY_SERVICE")
      A: android:exported(0x01010010)=(type 0x12)0xffffffff
      E: intent-filter
        E: action
          A: android:name="android.accessibilityservice.AccessibilityService" (Raw: "android.accessibilityservice.AccessibilityService")
      E: meta-data
        A: android:name="android.accessibilityservice" (Raw: "android.accessibilityservice")
        A: android:resource(0x01010025)=@0x7f120000
'''


class OneAppApkVerifierTest(unittest.TestCase):
    def test_accepts_exact_lucent_activity_boundary(self):
        self.assertEqual([], MODULE.verify_manifest(MANIFEST))

    def test_internal_lsfg_plus_label_requires_explicit_expected_identity(self):
        plus = MANIFEST.replace('android:label="EmuFusion"',
                                'android:label="EmuFusion+"')
        self.assertTrue(any("application label" in error
                            for error in MODULE.verify_manifest(plus)))
        self.assertEqual([], MODULE.verify_manifest(plus, "EmuFusion+"))

    def test_rejects_second_game_activity(self):
        value = MANIFEST + '''
    E: activity
      A: android:name="com.thorium.preview.game.LucentGameActivity" (Raw: "com.thorium.preview.game.LucentGameActivity")
'''
        errors = MODULE.verify_manifest(value)
        self.assertTrue(any(
            "Activities outside the Lucent boundary" in error for error in errors))

    def test_rejects_external_emulator_launcher(self):
        value = MANIFEST.replace(
            "com.thorium.preview.BrowserActivity",
            "org.dolphinemu.dolphinemu.ui.main.MainActivity",
        )
        errors = MODULE.verify_manifest(value)
        self.assertTrue(any(
            "Activities outside the Lucent boundary" in error for error in errors))

    def test_frontend_restart_bridge_is_exact_and_fail_closed(self):
        self.assertFalse(any("frontend restart bridge" in error
                             for error in MODULE.verify_manifest(MANIFEST)))
        self.assertTrue(any(
            "frontend restart bridge must use its dedicated app process" in error
            for error in MODULE.verify_manifest(
                MANIFEST.replace(':frontend_restart', ':wrong-process'))
        ))
        self.assertTrue(any(
            "frontend restart bridge must be non-exported" in error
            for error in MODULE.verify_manifest(
                MANIFEST.replace(
                    'android:name="com.thorium.preview.FrontendRestartActivity" '
                    '(Raw: "com.thorium.preview.FrontendRestartActivity")\n'
                    '      A: android:exported(0x01010010)=(type 0x12)0x0',
                    'android:name="com.thorium.preview.FrontendRestartActivity" '
                    '(Raw: "com.thorium.preview.FrontendRestartActivity")\n'
                    '      A: android:exported(0x01010010)=(type 0x12)0xffffffff')
        )))

    def test_exact_apk_requires_frontend_restart_implementation(self):
        apk = self._apk_with_dex(b"not-the-restart-bridge")
        self.assertTrue(MODULE.verify_frontend_restart_payload(apk))
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr(
                "classes2.dex",
                b"Lcom/thorium/preview/FrontendRestartActivity;",
            )
        self.assertEqual([], MODULE.verify_frontend_restart_payload(apk))

    def test_voice_feedback_manifest_and_payload_are_atomic(self):
        self.assertFalse(any("voice-feedback" in error
                             for error in MODULE.verify_manifest(MANIFEST)))
        missing = self._apk_with_dex(b"ordinary")
        self.assertTrue(MODULE.verify_voice_feedback_payload(missing))
        complete = self._apk_with_dex(
            b"Lcom/thorium/preview/VoiceFeedbackActivity;"
            b"Lcom/thorium/preview/VoiceFeedbackManager;"
            b"Landroid/speech/SpeechRecognizer;"
            b"wildonrio/emufusion"
        )
        self.assertEqual([], MODULE.verify_voice_feedback_payload(complete))

    def test_allows_nonexported_external_route_trampoline(self):
        value = MANIFEST + '''
    E: activity
      A: android:name="com.thorium.preview.RomLaunchActivity" (Raw: "com.thorium.preview.RomLaunchActivity")
      A: android:exported(0x01010010)=(type 0x12)0x0
      A: android:excludeFromRecents(0x01010005)=(type 0x12)0xffffffff
'''
        errors = MODULE.verify_manifest(value)
        self.assertFalse(any(
            "outside the Lucent boundary" in error or "trampoline" in error
            for error in errors))

    def test_lsfg_self_test_activity_is_exact_and_conditional(self):
        value = MANIFEST.replace(
            'A: android:name="com.thorium.preview.LucentApplication" '
            '(Raw: "com.thorium.preview.LucentApplication")',
            'A: android:name="com.thorium.preview.LucentApplication" '
            '(Raw: "com.thorium.preview.LucentApplication")\n'
            '    A: android:debuggable(0x0101000f)=(type 0x12)0xffffffff',
        ) + '''
    E: activity
      A: android:name="com.thorium.preview.game.LsfgQualificationSelfTestActivity" (Raw: "com.thorium.preview.game.LsfgQualificationSelfTestActivity")
      A: android:exported(0x01010010)=(type 0x12)0xffffffff
      A: android:excludeFromRecents(0x01010017)=(type 0x12)0xffffffff
      A: android:noHistory(0x01010016)=(type 0x12)0xffffffff
      A: android:taskAffinity="com.thorium.preview.lsfg.selftest" (Raw: "com.thorium.preview.lsfg.selftest")
'''
        self.assertEqual([], MODULE.verify_manifest(value))
        self.assertTrue(any(
            "explicitly debuggable" in error
            for error in MODULE.verify_manifest(value.replace(
                '    A: android:debuggable(0x0101000f)=(type 0x12)0xffffffff\n',
                ''))
        ))

    def test_lsfg_self_test_manifest_dex_and_native_are_atomic(self):
        activity = MODULE.LSFG_SELF_TEST_ACTIVITY
        descriptor = ("L" + activity.replace(".", "/") + ";").encode()
        apk = self._apk_with_dex(descriptor)
        with zipfile.ZipFile(apk, "a") as archive:
            archive.writestr(MODULE.LSFG_QUALIFICATION_LIBRARY, b"ELF")
        xml = MANIFEST + f'''\n    E: activity
      A: android:name="{activity}" (Raw: "{activity}")
'''
        self.assertEqual([], MODULE.verify_lsfg_self_test_boundary(apk, xml))

        missing_native = self._apk_with_dex(descriptor)
        self.assertTrue(MODULE.verify_lsfg_self_test_boundary(
            missing_native, xml))

        native_without_activity = self._apk_with_dex(b"ordinary")
        with zipfile.ZipFile(native_without_activity, "a") as archive:
            archive.writestr(MODULE.LSFG_QUALIFICATION_LIBRARY, b"ELF")
        self.assertTrue(MODULE.verify_lsfg_self_test_boundary(
            native_without_activity, MANIFEST))

    def test_rejects_exported_external_route_trampoline(self):
        value = MANIFEST + '''
    E: activity
      A: android:name="com.thorium.preview.RomLaunchActivity" (Raw: "com.thorium.preview.RomLaunchActivity")
      A: android:exported(0x01010010)=(type 0x12)0xffffffff
'''
        self.assertTrue(any(
            "trampoline must be non-exported" in error
            for error in MODULE.verify_manifest(value)))

    def test_rejects_legacy_external_app_authority(self):
        value = MANIFEST.replace(
            "  E: application",
            '  E: uses-permission\n'
            '    A: android:name="android.permission.QUERY_ALL_PACKAGES" '
            '(Raw: "android.permission.QUERY_ALL_PACKAGES")\n'
            "  E: application",
        )
        errors = MODULE.verify_manifest(value)
        self.assertTrue(any("QUERY_ALL_PACKAGES" in error for error in errors))

    def test_rejects_obsolete_exported_menu_receiver(self):
        with_receiver = MANIFEST + '''
    E: receiver
      A: android:name="com.thorium.preview.GameLaunchReceiver" (Raw: "com.thorium.preview.GameLaunchReceiver")
      A: android:exported(0x01010010)=(type 0x12)0xffffffff
'''
        self.assertTrue(any(
            "obsolete exported GameLaunchReceiver" in error
            for error in MODULE.verify_manifest(with_receiver)
        ))

    def test_rejects_missing_or_unprivileged_external_stop_service(self):
        without = MANIFEST[:MANIFEST.index("    E: service\n")]
        self.assertTrue(any(
            "exactly one same-package" in error
            for error in MODULE.verify_manifest(without)
        ))
        unprivileged = MANIFEST.replace(
            "android.permission.BIND_ACCESSIBILITY_SERVICE",
            "android.permission.INTERNET",
        )
        self.assertTrue(any(
            "lacks BIND_ACCESSIBILITY_SERVICE" in error
            for error in MODULE.verify_manifest(unprivileged)
        ))

    def test_exact_apk_requires_external_stop_code_and_configuration(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        apk = Path(temporary.name) / "lucent.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("classes.dex", b"not-the-stop-contract")
        errors = MODULE.verify_external_stop_payload(apk)
        self.assertTrue(any("configuration" in error for error in errors), errors)
        self.assertTrue(any("ExternalStopAccessibilityService" in error
                            for error in errors), errors)

        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr(
                "classes.dex",
                b"Lcom/thorium/preview/ExternalStopAccessibilityService;"
                b"Lcom/thorium/preview/ExternalEmulationSession;",
            )
            archive.writestr("res/xml/external_stop_accessibility.xml", b"binary")
        self.assertEqual([], MODULE.verify_external_stop_payload(apk))

    def test_exact_apk_requires_qml_preserving_frontend_patch(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        apk = Path(temporary.name) / "lucent.apk"
        payload = bytearray(
            MODULE.FRONTEND_LAUNCH_PATCH_OFFSET +
            len(MODULE.FRONTEND_LAUNCH_PATCH)
        )
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr(
                "lib/arm64-v8a/libpegasus-fe_arm64-v8a.so", payload
            )
        self.assertTrue(any(
            "does not preserve QML" in error
            for error in MODULE.verify_frontend_launch_lifecycle(apk)
        ))
        payload[
            MODULE.FRONTEND_LAUNCH_PATCH_OFFSET:
            MODULE.FRONTEND_LAUNCH_PATCH_OFFSET +
            len(MODULE.FRONTEND_LAUNCH_PATCH)
        ] = MODULE.FRONTEND_LAUNCH_PATCH
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr(
                "lib/arm64-v8a/libpegasus-fe_arm64-v8a.so", payload
            )
        self.assertEqual([], MODULE.verify_frontend_launch_lifecycle(apk))

    def test_branding_policy_has_natural_equal_length_replacements(self):
        for before, after in MODULE._branding_replacements().items():
            self.assertEqual(len(before), len(after))
            self.assertNotIn("  ", after)
            self.assertFalse(after.endswith(" "))

    def _apk_with_dex(self, dex: bytes) -> Path:
        apk = Path(tempfile.mkdtemp()) / "sample.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("classes.dex", dex)
        return apk

    def test_eden_jni_shim_classes_are_allowed(self):
        """The exact classes Eden's JNI_OnLoad resolves are EmuFusion's own."""
        dex = b"".join(name.encode()
                       for name in sorted(MODULE.ALLOWED_EMULATOR_SHIM_CLASSES))
        self.assertEqual([], MODULE.verify_dex(self._apk_with_dex(dex)))

    def test_other_yuzu_frontend_classes_still_rejected(self):
        """The allowlist must not blind the guard to real vendored code."""
        dex = (b"Lorg/yuzu/yuzu_emu/NativeLibrary;"
               b"Lorg/yuzu/yuzu_emu/activities/EmulationActivity;")
        errors = MODULE.verify_dex(self._apk_with_dex(dex))
        self.assertTrue(any("EmulationActivity" in error for error in errors),
                        errors)
        self.assertFalse(any("NativeLibrary" in error for error in errors),
                         errors)

    def test_every_allowed_shim_has_a_source_file(self):
        """An allowlist entry with no stub behind it is an unclaimed hole."""
        stubs = ROOT / "unified-android" / "stubs"
        for descriptor in MODULE.ALLOWED_EMULATOR_SHIM_CLASSES:
            outer = descriptor[1:-1].split("$")[0]
            self.assertTrue((stubs / (outer + ".java")).is_file(),
                            f"{descriptor} has no stub under {stubs}")

    def test_other_forbidden_packages_have_no_exemptions(self):
        """Only Eden needed this; nothing else may quietly acquire one."""
        for descriptor in MODULE.ALLOWED_EMULATOR_SHIM_CLASSES:
            self.assertTrue(descriptor.startswith("Lorg/yuzu/yuzu_emu/"),
                            descriptor)


if __name__ == "__main__":
    unittest.main()
