"""Execute the complete-build wrapper and test missing-engine packaging failures."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'unified-android/tools'
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('portable_bundle', TOOLS / 'verify_portable_bundle.py')
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)
WRAPPER = ROOT / 'unified-android/build-portable.sh'
FLAGS = ('LUCENT_INCLUDE_EXPERIMENTAL_CORES', 'LUCENT_AUTOSELECT_EXPERIMENTAL_CORES',
         'LUCENT_INCLUDE_PHASE2_PPSSPP', 'LUCENT_INCLUDE_PHASE3_EDEN',
         'LUCENT_INCLUDE_PHASE3_CEMU', 'LUCENT_INCLUDE_PHASE3_APS3E',
         'LUCENT_REQUIRE_PORTABLE_BUNDLE')

def payload():
    """Minimal catalog fixture for completeness only; not real ELF/runtime evidence."""
    entries = {'lib/arm64-v8a/' + name: b'fixture' for name in V.SUPPORT_LIBRARIES}
    for number, module in V.PHASES.items():
        enabled, registry, artifacts = {}, {}, {}
        for system, (phase, engine) in V.REQUIRED.items():
            if phase != number:
                continue
            library = 'liblucent_' + engine.replace('-', '_') + '.so'
            enabled.setdefault(engine, dict(id=engine, libraryName=library, libraryRouteSystems=[]))['libraryRouteSystems'].append(system)
            registry.setdefault(engine, dict(id=engine, systems=[]))['systems'].append(system)
            artifacts[engine] = dict(engineId=engine, fileName=library)
            entries['lib/arm64-v8a/' + library] = b'fixture'
        entries[module.OPT_IN] = dict(autoSelect=number == 1, engines=list(enabled.values()))
        entries[module.REGISTRY] = dict(engines=list(registry.values()))
        entries[module.ARTIFACTS] = dict(artifacts=list(artifacts.values()))
    return entries

def zipped(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for name, value in entries.items():
            archive.writestr(name, json.dumps(value) if isinstance(value, dict) else value)
    return out

class PortableCompletenessTest(unittest.TestCase):
    def check_entries(self, entries):
        with zipfile.ZipFile(zipped(entries)) as archive:
            return V.coverage_errors(archive)

    def test_complete_owned_system_catalog(self):
        self.assertEqual(len(V.REQUIRED), 20)
        self.assertEqual(V.REQUIRED['pcenginecd'], (1, 'beetle-pce-fast'))
        self.assertEqual(V.REQUIRED['switch'], (3, 'eden'))
        self.assertEqual(V.REQUIRED['wiiu'], (3, 'cemu'))
        self.assertEqual(self.check_entries(payload()), [])

    def test_each_required_engine_cannot_be_omitted(self):
        for phase, engine in set(V.REQUIRED.values()):
            with self.subTest(engine=engine):
                entries = payload()
                key = V.PHASES[phase].ARTIFACTS
                entries[key]['artifacts'] = [r for r in entries[key]['artifacts'] if r['engineId'] != engine]
                self.assertTrue(any('required internal ' + engine in e for e in self.check_entries(entries)))

    def test_binary_presence_is_required_not_just_metadata(self):
        entries = payload()
        del entries['lib/arm64-v8a/liblucent_eden.so']
        self.assertIn('switch: packaged eden library is missing', self.check_entries(entries))

    def test_phase1_auto_selection_is_required(self):
        entries = payload()
        entries[V.phase1.OPT_IN]['autoSelect'] = False
        self.assertTrue(any('disabled for normal-library' in e for e in self.check_entries(entries)))

    def test_every_normal_library_route_is_required(self):
        for system, (phase, engine) in V.REQUIRED.items():
            with self.subTest(system=system):
                entries = payload()
                module = V.PHASES[phase]
                asset = module.REGISTRY if phase == 1 else module.OPT_IN
                row = next(r for r in entries[asset]['engines'] if r['id'] == engine)
                row['systems' if phase == 1 else 'libraryRouteSystems'].remove(system)
                self.assertIn(f'{system}: {engine} has no normal-library route', self.check_entries(entries))

    def test_support_hosts_and_hooks_are_required(self):
        for name in V.SUPPORT_LIBRARIES:
            entries = payload()
            del entries['lib/arm64-v8a/' + name]
            self.assertIn('missing internal host/driver support: ' + name, self.check_entries(entries))

    def test_duplicates_are_not_ambiguous_success(self):
        entries = payload()
        row = entries[V.phase3.OPT_IN]['engines'][0]
        entries[V.phase3.OPT_IN]['engines'].append(copy.deepcopy(row))
        with self.assertRaises(ValueError):
            self.check_entries(entries)

    def test_existing_phase_gate_failure_is_not_bypassed(self):
        with tempfile.TemporaryDirectory() as temp:
            apk = Path(temp) / 'fixture.apk'
            apk.write_bytes(zipped(payload()).getvalue())
            with patch.object(V.phase1, 'verify', return_value=[]), \
                 patch.object(V.phase2, 'verify', return_value=['native payload hash mismatch']), \
                 patch.object(V.phase3, 'verify', return_value=[]):
                self.assertEqual(V.verify(apk), ['Phase 2: native payload hash mismatch'])

class PortableWrapperTest(unittest.TestCase):
    def run_wrapper(self, overrides=None):
        with tempfile.TemporaryDirectory(prefix='portable-wrapper-') as temp:
            folder = Path(temp)
            (folder / 'build-portable.sh').write_bytes(WRAPPER.read_bytes())
            recorded = (*FLAGS, 'LUCENT_REUSE_QUALIFICATION_CORES', 'LUCENT_REUSE_PHASE2_PPSSPP',
                        'LUCENT_REQUIRE_16K_ALIGNMENT', 'LUCENT_SIGNING_PROFILE',
                        'LUCENT_SOURCE_FRONTEND_DIR', 'LUCENT_SOURCE_FRONTEND_LOCK')
            fake = folder / 'build.sh'
            fake.write_text('#!/bin/sh\n' + '\n'.join(
                'printf "' + flag + '=%s\\n" "${' + flag + '-unset}"' for flag in recorded)
                + '\nexit "${PORTABLE_TEST_EXIT:-0}"\n')
            fake.chmod(0o755)
            env = {k: v for k, v in os.environ.items() if not k.startswith('LUCENT_')}
            env.update(overrides or {})
            return subprocess.run(['sh', str(folder / 'build-portable.sh')], env=env,
                                  capture_output=True, text=True)

    def test_default_profile_enables_all_routes(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in FLAGS:
            self.assertIn(name + '=1\n', result.stdout)
        self.assertIn('LUCENT_REUSE_PHASE2_PPSSPP=1\n', result.stdout)
        self.assertIn('LUCENT_SIGNING_PROFILE=unset\n', result.stdout)
        self.assertRegex(result.stdout, r'LUCENT_SOURCE_FRONTEND_DIR=.*/build/source-frontend\n')
        self.assertRegex(result.stdout, r'LUCENT_SOURCE_FRONTEND_LOCK=.*/source-frontend-artifact-lock.json\n')

    def test_explicit_source_kit_is_preserved(self):
        result = self.run_wrapper({'LUCENT_SOURCE_FRONTEND_DIR': '/explicit kit',
                                   'LUCENT_SOURCE_FRONTEND_LOCK': '/explicit lock'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('LUCENT_SOURCE_FRONTEND_DIR=/explicit kit\n', result.stdout)
        self.assertIn('LUCENT_SOURCE_FRONTEND_LOCK=/explicit lock\n', result.stdout)

    def test_partial_source_kit_is_not_silently_completed(self):
        # The underlying build's paired-input preflight rejects these values.
        for flag in ('LUCENT_SOURCE_FRONTEND_DIR', 'LUCENT_SOURCE_FRONTEND_LOCK'):
            result = self.run_wrapper({flag: '/explicit'})
            other = 'LUCENT_SOURCE_FRONTEND_LOCK' if flag.endswith('DIR') else 'LUCENT_SOURCE_FRONTEND_DIR'
            self.assertIn(flag + '=/explicit\n', result.stdout)
            self.assertIn(other + '=unset\n', result.stdout)

    def test_reduced_or_invalid_flags_fail_before_build(self):
        for flag in FLAGS:
            for value in ('0', '', 'true'):
                with self.subTest(flag=flag, value=value):
                    result = self.run_wrapper({flag: value})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, '')
                    self.assertIn(flag, result.stderr)

    def test_explicit_rebuild_and_failure_propagation(self):
        result = self.run_wrapper({'LUCENT_REUSE_PHASE2_PPSSPP': '0', 'PORTABLE_TEST_EXIT': '17'})
        self.assertEqual(result.returncode, 17)
        self.assertIn('LUCENT_REUSE_PHASE2_PPSSPP=0\n', result.stdout)

    def test_release_alignment_cannot_be_disabled(self):
        good = self.run_wrapper({'LUCENT_SIGNING_PROFILE': 'release'})
        self.assertEqual(good.returncode, 0)
        self.assertIn('LUCENT_REQUIRE_16K_ALIGNMENT=1\n', good.stdout)
        bad = self.run_wrapper({'LUCENT_SIGNING_PROFILE': 'release', 'LUCENT_REQUIRE_16K_ALIGNMENT': '0'})
        self.assertNotEqual(bad.returncode, 0)
        self.assertEqual(bad.stdout, '')

    def test_build_invokes_completeness_before_immutable_publication(self):
        code = (ROOT / 'unified-android/build.sh').read_text()
        start = code.index('if [ "${LUCENT_REQUIRE_PORTABLE_BUNDLE:-0}" = 1 ]; then')
        end = code.index('\nfi', start)
        self.assertIn('verify_portable_bundle.py', code[start:end])
        self.assertLess(start, code.index('OUTPUT_SHA='))
        subprocess.run(['sh', '-n', str(WRAPPER)], check=True)

class RepackedManifestTest(unittest.TestCase):
    def test_actual_debug_override_replaces_existing_attribute_once(self):
        build = (ROOT / 'unified-android/build.sh').read_text()
        start = build.index('if [ "${LUCENT_DEBUGGABLE:-0}" = 1 ]')
        block = build[start:build.index('\nfi', start)]
        self.assertIn('|| [ "$INCLUDE_LSFG_FRAMEGEN" = 1 ]; then', block)
        self.assertEqual(build.count('android:debuggable="true"'), 1,
                         'diagnostic and LSFG flags must share one attribute writer')
        expression = re.search(r"perl -0pi -e '([^']+)'", block).group(1)
        for existing in ('', ' android:debuggable="false"', '\n android:debuggable="true"'):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as temp:
                manifest = Path(temp) / 'AndroidManifest.xml'
                manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
                    '<application android:label="EmuFusion"' + existing + '><activity android:name="Main" />'
                    '</application></manifest>')
                for _ in range(2):
                    subprocess.run(['perl', '-0pi', '-e', expression, str(manifest)], check=True)
                    app = ET.fromstring(manifest.read_text()).find('application')
                    self.assertEqual(app.attrib['{http://schemas.android.com/apk/res/android}debuggable'], 'true')
                    self.assertEqual(app.attrib['{http://schemas.android.com/apk/res/android}label'], 'EmuFusion')
                    self.assertEqual(len(app.findall('activity')), 1)

    def test_actual_legacy_permission_removal_handles_decoder_whitespace(self):
        build = (ROOT / 'unified-android/build.sh').read_text()
        expressions = re.findall(r"perl -0pi -e '([^']+)'", build)
        expression = next(e for e in expressions if 'QUERY_ALL_PACKAGES' in e)
        for gap in ('', ' ', '\n    ', '\t'):
            with self.subTest(gap=repr(gap)), tempfile.TemporaryDirectory() as temp:
                manifest = Path(temp) / 'AndroidManifest.xml'
                manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
                    '<uses-permission android:name="android.permission.QUERY_ALL_PACKAGES"' + gap + '/>'
                    '<uses-permission android:name="android.permission.KILL_BACKGROUND_PROCESSES"' + gap + '/>'
                    '<uses-permission android:name="android.permission.INTERNET" />'
                    '<queries><package android:name="dev.eden.eden_emulator" /></queries></manifest>')
                subprocess.run(['perl', '-0pi', '-e', expression, str(manifest)], check=True)
                result = manifest.read_text()
                self.assertNotIn('QUERY_ALL_PACKAGES', result)
                self.assertNotIn('KILL_BACKGROUND_PROCESSES', result)
                self.assertIn('android.permission.INTERNET', result)
                self.assertIn('<queries><package android:name="dev.eden.eden_emulator" /></queries>', result)

@unittest.skipUnless(os.environ.get('EMU_PORTABLE_APK'), 'explicit immutable APK needed for integration test')
class RealApkCompletenessTest(unittest.TestCase):
    def test_phase3_subset_used_to_pass_but_full_profile_rejects_it(self):
        apk = Path(os.environ['EMU_PORTABLE_APK'])
        self.assertEqual(V.verify(apk), [])
        with tempfile.TemporaryDirectory(prefix='portable-subset-') as temp:
            reduced = Path(temp) / 'missing-switch.apk'
            with zipfile.ZipFile(apk) as old, zipfile.ZipFile(reduced, 'w') as new:
                for item in old.infolist():
                    if item.filename.startswith('META-INF/') or item.filename in {
                        'lib/arm64-v8a/liblucent_native_adapter_eden.so',
                        'assets/phase3-eden-source-lock.json', 'assets/phase3-eden-lucent-adapter.cpp'}:
                        continue
                    data = old.read(item.filename)
                    if item.filename == V.phase3.ARTIFACTS:
                        manifest = json.loads(data)
                        manifest['artifacts'] = [r for r in manifest['artifacts'] if r['engineId'] != 'eden']
                        data = json.dumps(manifest).encode()
                    new.writestr(item, data)
            # A reduced diagnostic bundle remains valid for the old subset gate.
            self.assertEqual(V.phase3.verify(reduced), [])
            errors = V.verify(reduced)
            self.assertIn('switch: required internal eden is absent from Phase 3', errors)
            print('Real APK missing-Switch regression rejected; baseline SHA256=' +
                  hashlib.sha256(apk.read_bytes()).hexdigest())

if __name__ == '__main__':
    unittest.main()
