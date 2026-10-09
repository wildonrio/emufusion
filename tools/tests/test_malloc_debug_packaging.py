"""Exercise the real opt-in branch and wrapper; not allocator/device qualification."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("malloc_debug", ROOT / "unified-android/tools/enable_malloc_debug.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MANIFEST = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.thorium.preview">
<uses-sdk android:targetSdkVersion="30"/>
<!-- Keep component attributes and formatting. -->
<application android:label="EmuFusion" android:debuggable='false' android:extractNativeLibs="false">
<activity android:name=".MainActivity" android:exported="true"/>
</application></manifest>'''


class MallocDebugPackagingTest(unittest.TestCase):
    def trace_stage(self, folder):
        path = self.stage(folder)
        (path / 'lib/x86_64/untouched.so').unlink()
        (path / 'lib/x86_64').rmdir()
        library = path / 'input-tracer.so'
        library.write_bytes(b'\x7fELF\x02\x01\x01' + bytes(9) + b'\x03\x00\xb7\x00' + bytes(44))
        return path, library

    def test_opt_in_trace_payload_and_wrapper_idempotence(self):
        with tempfile.TemporaryDirectory() as folder:
            path, library = self.trace_stage(folder)
            MODULE.enable(path, library)
            MODULE.enable(path, library)
            native = path / 'lib/arm64-v8a'
            self.assertEqual(library.read_bytes(), (native / 'libemufusion_free_trace.so').read_bytes())
            wrapper = (native / 'wrap.sh').read_text()
            self.assertIn('EMUFUSION_FREE_TRACE_DIR=/data/user/0/com.thorium.preview/files', wrapper)
            self.assertIn('${LD_PRELOAD:+:$LD_PRELOAD}', wrapper)
            self.assertTrue(wrapper.endswith('exec logwrapper "$@"\n'))
            self.assertEqual(b'native payload', (native / 'untouched.so').read_bytes())

    def test_bad_trace_inputs_leave_staging_unchanged(self):
        for failure in ('elf', 'abi', 'package', 'conflict'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                path, library = self.trace_stage(folder)
                if failure == 'elf':
                    library.write_bytes(b'not a library')
                elif failure == 'abi':
                    (path / 'lib/x86_64').mkdir()
                    (path / 'lib/x86_64/other.so').write_bytes(b'other')
                elif failure == 'package':
                    (path / 'AndroidManifest.xml').write_text(MANIFEST.replace('com.thorium.preview', 'other.app'))
                else:
                    (path / 'lib/arm64-v8a/libemufusion_free_trace.so').write_bytes(b'existing')
                original = (path / 'AndroidManifest.xml').read_bytes()
                with self.assertRaises(ValueError):
                    MODULE.enable(path, library)
                self.assertEqual(original, (path / 'AndroidManifest.xml').read_bytes())
                self.assertFalse((path / 'lib/arm64-v8a/wrap.sh').exists())

    def stage(self, folder):
        path = Path(folder)
        (path / "AndroidManifest.xml").write_text(MANIFEST)
        for abi in ("arm64-v8a", "x86_64"):
            native = path / "lib" / abi / "untouched.so"
            native.parent.mkdir(parents=True)
            native.write_bytes(b"native payload")
        return path

    def test_manifest_idempotence_and_preservation(self):
        updated = MODULE.manifest_for_debug(MANIFEST)
        self.assertEqual(updated, MODULE.manifest_for_debug(updated))
        parsed = ET.fromstring(updated)
        for name, value in MODULE.ATTRIBUTES.items():
            self.assertEqual(value, parsed.find('application').get(MODULE.ANDROID + name))
            self.assertEqual(1, updated.count('android:' + name + '='))
        self.assertEqual('30', parsed.find('uses-sdk').get(MODULE.ANDROID + 'targetSdkVersion'))
        # Bytes outside the opening tag are unchanged, including comment/activity.
        self.assertEqual(MANIFEST.split('<application')[0], updated.split('<application')[0])
        self.assertEqual(MANIFEST.split('>\n<activity')[1], updated.split('>\n<activity')[1])

    def test_packages_every_existing_abi_without_changing_native_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.stage(folder)
            MODULE.enable(path)
            MODULE.enable(path)
            for abi in ('arm64-v8a', 'x86_64'):
                wrapper = path / 'lib' / abi / 'wrap.sh'
                self.assertEqual(MODULE.WRAPPER.read_bytes(), wrapper.read_bytes())
                self.assertEqual(0o755, wrapper.stat().st_mode & 0o777)
                self.assertEqual(b'native payload', wrapper.with_name('untouched.so').read_bytes())

    def test_conflicts_refused_without_partial_manifest_or_wrapper_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.stage(folder)
            wrapper = path / 'lib/x86_64/wrap.sh'
            wrapper.write_text('existing user wrapper')
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                MODULE.enable(path)
            self.assertEqual(MANIFEST, (path / 'AndroidManifest.xml').read_text())
            self.assertFalse((path / 'lib/arm64-v8a/wrap.sh').exists())
            self.assertEqual('existing user wrapper', wrapper.read_text())

    def test_invalid_manifest_and_missing_abi_refused(self):
        for value in ('<broken', '<manifest/>', MANIFEST.replace('<application ', '<application android:gwpAsanMode="always" ')):
            with self.assertRaises((ValueError, ET.ParseError)):
                MODULE.manifest_for_debug(value)
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / 'AndroidManifest.xml'
            manifest.write_text(MANIFEST)
            with self.assertRaisesRegex(ValueError, 'no native ABI'):
                MODULE.enable(folder)
            self.assertEqual(MANIFEST, manifest.read_text())

    def test_real_wrapper_preserves_argv_and_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            logwrapper = Path(folder) / 'logwrapper'
            logwrapper.write_text('#!/bin/sh\nexec "$@"\n')
            logwrapper.chmod(0o755)
            environment = dict(os.environ, PATH=folder + os.pathsep + os.environ['PATH'])
            args = ['argument with spaces', '*', '--flag=x']
            command = [sys.executable, '-c', 'import os,sys,json; print(json.dumps([os.environ["LIBC_DEBUG_MALLOC_OPTIONS"],sys.argv[1:]]))', *args]
            result = subprocess.run(['sh', str(MODULE.WRAPPER), *command], env=environment, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(['guard=32 free_track=64 free_track_backtrace_num_frames=0 backtrace_full abort_on_error', args], json.loads(result.stdout))
            self.assertNotIn('LIBC_DEBUG_MALLOC_OPTIONS', environment)

    def test_actual_build_branch_is_opt_in(self):
        build = (ROOT / 'unified-android/build.sh').read_text()
        start = build.index('if [ "${LUCENT_MALLOC_DEBUG:-0}" = 1 ]; then')
        branch = build[start:build.index('\nfi', start)+3]
        for flag in (None, '0', '1'):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as folder:
                path = self.stage(folder)
                environment = dict(os.environ, PROJECT_DIR=str(ROOT / 'unified-android'), DECODED=folder)
                environment.pop('LUCENT_MALLOC_DEBUG', None)
                if flag is not None:
                    environment['LUCENT_MALLOC_DEBUG'] = flag
                result = subprocess.run(['sh', '-eu', '-c', branch], env=environment, capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(flag == '1', (path / 'lib/arm64-v8a/wrap.sh').exists())
                expected = MODULE.manifest_for_debug(MANIFEST) if flag == '1' else MANIFEST
                self.assertEqual(expected, (path / 'AndroidManifest.xml').read_text())

    def test_invalid_or_combined_flags_fail_before_build_work(self):
        build = (ROOT / 'unified-android/build.sh').read_text()
        start = build.index('case "${LUCENT_GWP_ASAN:-0}" in')
        end = build.index('\n# An earlier build', start)
        self.assertLess(end, build.index('mkdir -p "$BUILD_DIR"'))
        for flags in ({'LUCENT_MALLOC_DEBUG': 'yes'}, {'LUCENT_MALLOC_DEBUG': '2'},
                      {'LUCENT_MALLOC_DEBUG': '1', 'LUCENT_GWP_ASAN': '1'},
                      {'LUCENT_MALLOC_FREE_TRACE_LIBRARY': '/some/library.so'}):
            result = subprocess.run(['sh', '-eu', '-c', build[start:end]], env=flags, capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode)

    def test_actual_late_lsfg_manifest_branch_composes_without_duplicate_debuggable(self):
        build = (ROOT / 'unified-android/build.sh').read_text()
        # The LSFG qualification APK's debuggable edit now shares the single
        # LUCENT_DEBUGGABLE manifest branch; it must still precede malloc_debug.
        start = build.index('if [ "${LUCENT_DEBUGGABLE:-0}" = 1 ] || [ "$INCLUDE_LSFG_FRAMEGEN" = 1 ]; then')
        end = build.index('\nfi', start) + 3
        self.assertIn('android:debuggable="true"', build[start:end])
        diagnostic_start = build.index('if [ "${LUCENT_MALLOC_DEBUG:-0}" = 1 ]; then')
        diagnostic_end = build.index('\nfi', diagnostic_start) + 3
        self.assertLess(end, diagnostic_start)
        branch = build[start:end] + '\n' + build[diagnostic_start:diagnostic_end]
        # Pinned base APK has no debuggable attribute before the LSFG edit;
        # apktool may instead emit an explicit debuggable="false".
        for base in (MANIFEST.replace(" android:debuggable='false'", ''),
                     MANIFEST.replace("android:debuggable='false'", 'android:debuggable="false"')):
            with self.subTest(base=base), tempfile.TemporaryDirectory() as folder:
                path = self.stage(folder)
                (path / 'AndroidManifest.xml').write_text(base)
                environment = dict(os.environ, PROJECT_DIR=str(ROOT / 'unified-android'), DECODED=folder,
                                   INCLUDE_LSFG_FRAMEGEN='1', LUCENT_MALLOC_DEBUG='1')
                environment.pop('LUCENT_DEBUGGABLE', None)
                result = subprocess.run(['sh', '-eu', '-c', branch], env=environment, capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stderr)
                text = (path / 'AndroidManifest.xml').read_text()
                self.assertEqual(1, text.count('android:debuggable='))
                self.assertEqual('true', ET.fromstring(text).find('application').get(MODULE.ANDROID + 'debuggable'))
                self.assertTrue((path / 'lib/arm64-v8a/wrap.sh').exists())


if __name__ == '__main__':
    unittest.main()
