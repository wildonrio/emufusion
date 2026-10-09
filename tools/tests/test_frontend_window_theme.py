"""Exercise the production decoded-manifest/resource patch, not string matches."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("window_theme", ROOT /
    "unified-android/tools/patch_frontend_window_theme.py")
THEME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(THEME)
LOADER = Path('smali/org/qtproject/qt5/android/bindings/QtActivityLoader.smali')
LOADER_TEXT = '''.class public Lorg/qtproject/qt5/android/bindings/QtActivityLoader;
.super Ljava/lang/Object;
.method public onCreate(Landroid/os/Bundle;)V
    .locals 10
    invoke-virtual {v1, v0}, Lorg/qtproject/qt5/android/bindings/QtActivity;->setTheme(I)V

    const/16 v1, 0x8

    invoke-virtual {v0, v1}, Lorg/qtproject/qt5/android/bindings/QtActivity;->requestWindowFeature(I)Z

    # Preserve unrelated delegate boot and theme-extraction machinery.
    invoke-static {}, Lorg/qtproject/qt5/android/QtApplication;->keepBootstrap()V
    return-void
.end method
'''


class FrontendWindowThemeTest(unittest.TestCase):
    def fixture(self, root, attribute='android.theme="@style/PegasusMain"'):
        (root / "res/values").mkdir(parents=True)
        (root / "AndroidManifest.xml").write_text(f'''<manifest xmlns:android="{THEME.ANDROID}" package="com.thorium.preview">
<application android:theme="@style/KeepApplication"><activity android:name="{THEME.ACTIVITY}" {attribute}
android:screenOrientation="userLandscape" android:launchMode="singleTask"><meta-data android:name="keep" android:value="yes"/></activity>
<activity android:name="other.Activity" android:theme="@style/KeepOther"/></application></manifest>''')
        (root / "res/values/styles.xml").write_text('''<resources><style name="PegasusMain">
<item name="android:colorPrimary">@color/pegasus_bg</item>
<item name="android:windowAllowReturnTransitionOverlap">true</item></style>
<style name="KeepOther" parent="@android:style/Theme.Material"><item name="android:windowActionBar">true</item></style></resources>''')
        (root / LOADER).parent.mkdir(parents=True)
        (root / LOADER).write_text(LOADER_TEXT)

    def test_runtime_loader_cannot_replace_custom_theme_or_request_action_bar(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            THEME.patch(root)
            loader = (root / LOADER).read_text()
            self.assertNotIn('->setTheme(I)V', loader)
            self.assertNotIn('->requestWindowFeature(I)Z', loader)
            self.assertIn('->keepBootstrap()V', loader)
            THEME.check(root)
            before = (root / LOADER).read_bytes()
            THEME.patch(root)
            self.assertEqual(before, (root / LOADER).read_bytes())

    def test_resources_alone_do_not_pass_with_original_runtime_loader(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            THEME.patch(root)
            (root / LOADER).write_text(LOADER_TEXT)
            with self.assertRaisesRegex(ValueError, 'loader'):
                THEME.check(root)

    def test_unknown_loader_fails_before_writing_manifest_or_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root / LOADER).write_text(LOADER_TEXT.replace('const/16 v1, 0x8', 'const/16 v1, 0x9'))
            paths = [root / p for p in ('AndroidManifest.xml', 'res/values/styles.xml', LOADER)]
            before = [p.read_bytes() for p in paths]
            with self.assertRaisesRegex(ValueError, 'loader'):
                THEME.patch(root)
            self.assertEqual(before, [p.read_bytes() for p in paths])

    def test_rejects_real_upstream_typo_then_repairs_without_changing_other_ui(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            with self.assertRaisesRegex(ValueError, "namespaced"):
                THEME.check(root)
            THEME.patch(root)
            THEME.check(root)
            manifest, styles, activity, style = THEME.read_targets(root)
            self.assertEqual(activity.get("{" + THEME.ANDROID + "}screenOrientation"), "userLandscape")
            self.assertEqual(activity.get("{" + THEME.ANDROID + "}launchMode"), "singleTask")
            self.assertEqual(activity.find("meta-data").get("{" + THEME.ANDROID + "}value"), "yes")
            self.assertEqual(manifest.find("application").get(THEME.THEME), "@style/KeepApplication")
            self.assertEqual(manifest.findall("./application/activity")[1].get(THEME.THEME), "@style/KeepOther")
            self.assertEqual(style.find("item[@name='android:colorPrimary']").text, "@color/pegasus_bg")
            self.assertEqual(styles.getroot().find("style[@name='KeepOther']").get("parent"), "@android:style/Theme.Material")
            before = [(root / p).read_bytes() for p in ("AndroidManifest.xml", "res/values/styles.xml")]
            THEME.patch(root)
            self.assertEqual(before, [(root / p).read_bytes() for p in ("AndroidManifest.xml", "res/values/styles.xml")])

    def test_namespaced_theme_alone_does_not_disable_inherited_action_bar(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root, 'android:theme="@style/PegasusMain"')
            with self.assertRaisesRegex(ValueError, "inherit"):
                THEME.check(root)
            THEME.patch(root)
            THEME.check(root)

    def test_duplicate_window_items_are_normalized(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            path = root / "res/values/styles.xml"
            tree = ET.parse(path)
            style = tree.getroot().find("style[@name='PegasusMain']")
            for value in ("true", "false"):
                ET.SubElement(style, "item", {"name": "android:windowActionBar"}).text = value
            tree.write(path)
            THEME.patch(root)
            THEME.check(root)

    def test_missing_target_fails_before_writing_either_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            path = root / "res/values/styles.xml"
            path.write_text("<resources/>")
            before = (root / "AndroidManifest.xml").read_bytes()
            with self.assertRaisesRegex(ValueError, "exactly one"):
                THEME.patch(root)
            self.assertEqual(before, (root / "AndroidManifest.xml").read_bytes())
            self.assertEqual(path.read_text(), "<resources/>")


if __name__ == "__main__":
    unittest.main()
