import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCHER = (ROOT / "unified-android" / "tools" /
           "patch_qt_android_gamepad_null_guard.py")
BUILD = (ROOT / "unified-android" / "build.sh").read_text(encoding="utf-8")

SPEC = importlib.util.spec_from_file_location("qt_gamepad_guard", PATCHER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

VERIFY_SPEC = importlib.util.spec_from_file_location(
    "one_app_verifier",
    ROOT / "unified-android" / "tools" / "verify_one_app_apk.py",
)
assert VERIFY_SPEC and VERIFY_SPEC.loader
VERIFIER = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFIER)


class QtAndroidGamepadNullGuardTest(unittest.TestCase):
    def fixture(self) -> bytearray:
        size = max(offset + len(expected)
                   for offset, expected, _replacement in MODULE.PATCHES)
        data = bytearray(size)
        data[:6] = b"\x7fELF\x02\x01"
        for offset, expected, _replacement in MODULE.PATCHES:
            data[offset:offset + len(expected)] = expected
        return data

    def write_fixture(self, directory: Path) -> Path:
        path = directory / "libplugins_gamepads_androidgamepad.so"
        data = self.fixture()
        path.write_bytes(data)
        MODULE.INPUT_SHA256 = hashlib.sha256(data).hexdigest()
        return path

    def test_patch_inserts_both_qapp_null_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_fixture(Path(temp))
            before, after = MODULE.patch(path)
            self.assertNotEqual(before, after)
            data = path.read_bytes()
            for offset, _expected, replacement in MODULE.PATCHES:
                self.assertEqual(data[offset:offset + len(replacement)], replacement)

    def test_repeat_application_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_fixture(Path(temp))
            MODULE.patch(path)
            with self.assertRaisesRegex(ValueError, "already applied"):
                MODULE.patch(path)

    def test_drift_fails_closed_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_fixture(Path(temp))
            data = bytearray(path.read_bytes())
            data[MODULE.PATCHES[0][0]] ^= 0x01
            path.write_bytes(data)
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "unexpected.*checksum"):
                MODULE.patch(path)
            self.assertEqual(path.read_bytes(), before)

    def test_build_applies_guard_to_pinned_plugin(self):
        self.assertIn("patch_qt_android_gamepad_null_guard.py", BUILD)
        self.assertIn(
            "libplugins_gamepads_androidgamepad_arm64-v8a.so", BUILD
        )

    def test_exact_apk_verifier_rejects_unpatched_plugin(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            plugin = self.write_fixture(directory)
            apk = directory / "candidate.apk"
            member = (
                "lib/arm64-v8a/"
                "libplugins_gamepads_androidgamepad_arm64-v8a.so"
            )
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr(member, plugin.read_bytes())
            self.assertTrue(VERIFIER.verify_qt_gamepad_null_guard(apk))
            MODULE.patch(plugin)
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr(member, plugin.read_bytes())
            self.assertEqual(VERIFIER.verify_qt_gamepad_null_guard(apk), [])


if __name__ == "__main__":
    unittest.main()
