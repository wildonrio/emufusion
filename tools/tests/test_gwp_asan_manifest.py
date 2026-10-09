"""Exercise the diagnostic manifest transformation and actual build branch."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "unified-android/tools/enable_gwp_asan.py"
SPEC = importlib.util.spec_from_file_location("gwp_manifest", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
NS = MODULE.ANDROID
MANIFEST = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.thorium.preview">
<uses-sdk android:targetSdkVersion="30"/>
<!-- Keep this comment and component attributes. -->
<application android:label="EmuFusion" android:debuggable="false">
<activity android:name=".MainActivity" android:exported="true"/>
</application></manifest>'''


class GwpAsanManifestTest(unittest.TestCase):
    def test_idempotent_preserves_every_other_byte(self):
        result = MODULE.enable(MANIFEST)
        self.assertEqual(MANIFEST, result.replace(' android:gwpAsanMode="always"', '', 1))
        self.assertEqual(result, MODULE.enable(result))

    def test_replaces_existing_attribute_without_duplicates(self):
        for quote in ('"', "'"):
            original = MANIFEST.replace('<application ', f'<application android:gwpAsanMode={quote}never{quote} ')
            result = MODULE.enable(original)
            self.assertEqual(1, result.count('android:gwpAsanMode'))
            self.assertEqual('always', ET.fromstring(result).find('application').get(NS+'gwpAsanMode'))

    def test_bad_input_refused(self):
        for value in ('<manifest/>', MANIFEST.replace('</manifest>', '<application/></manifest>'), '<invalid'):
            with self.assertRaises((ValueError, ET.ParseError)):
                MODULE.enable(value)

    def test_real_build_branch_is_opt_in(self):
        build = (ROOT / 'unified-android/build.sh').read_text()
        start = build.index('if [ "${LUCENT_GWP_ASAN:-0}" = 1 ]; then')
        branch = build[start:build.index('\nfi', start)+3]
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder)/'AndroidManifest.xml'
            for value in (None, '0', '1'):
                manifest.write_text(MANIFEST)
                environment = {
                    'PATH': '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin',
                    'PROJECT_DIR': str(ROOT/'unified-android'),
                    'DECODED': folder,
                }
                if value is not None:
                    environment['LUCENT_GWP_ASAN'] = value
                result = subprocess.run(['sh', '-eu', '-c', branch], env=environment,
                                        capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(MODULE.enable(MANIFEST) if value == '1' else MANIFEST, manifest.read_text())

    def test_invalid_flag_fails_before_build_lock_or_work(self):
        build = (ROOT / 'unified-android/build.sh').read_text()
        start = build.index('case "${LUCENT_GWP_ASAN:-0}" in')
        end = build.index('\nesac', start) + len('\nesac')
        self.assertLess(end, build.index('mkdir -p "$BUILD_DIR"'))
        for value in ('yes', '2', '-1'):
            result = subprocess.run(['sh', '-eu', '-c', build[start:end]],
                                    env={'LUCENT_GWP_ASAN': value}, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn('must be 0 or 1', result.stderr)


if __name__ == '__main__':
    unittest.main()
