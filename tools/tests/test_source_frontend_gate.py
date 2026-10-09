"""Fail-closed cohort identity tests; these do not assert gameplay acceptance."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'unified-android/tools'))
import verify_source_frontend as gate
import verify_one_app_apk as one_app
import stage_source_frontend as staging
import install_source_frontend as installation

class SourceFrontendGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='emufusion-cohort-gate-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.apk, self.lock = self.folder/'candidate.apk', self.folder/'reviewed.json'
        elf = bytearray(120)
        elf[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<Q', elf, 32, 64)
        struct.pack_into('<HH', elf, 54, 56, 1)
        struct.pack_into('<I', elf, 64, 1)
        struct.pack_into('<Q', elf, 112, 16384)
        names = gate.EXTRA | {f'libQt5Fixture{i}_arm64-v8a.so' for i in range(45)}
        self.payloads = {gate.PREFIX+n: bytes(elf) for n in names}
        self.document = dict(format=1, scope='isolated-source-frontend-qualification',
                             payloads={n:hashlib.sha256(v).hexdigest() for n,v in self.payloads.items()})
        self.save()

    def save(self):
        self.lock.write_text(json.dumps(self.document))
        with zipfile.ZipFile(self.apk, 'w') as archive:
            for name, data in self.payloads.items():
                archive.writestr(name, data)

    def test_exact_explicit_cohort_passes(self):
        self.assertEqual(gate.verify(self.apk,self.lock), [])

    def test_one_changed_library_rejected(self):
        name = next(iter(self.payloads))
        self.payloads[name] += b'changed'
        self.save()
        self.assertTrue(any('hash mismatch' in e for e in gate.verify(self.apk,self.lock)))

    def test_missing_and_extra_library_rejected(self):
        name = next(iter(self.payloads))
        original = self.payloads.pop(name)
        self.save()
        self.assertTrue(gate.verify(self.apk,self.lock))
        self.payloads[name] = original
        self.payloads[gate.PREFIX+'libqml_unreviewed.so'] = original
        self.save()
        self.assertTrue(gate.verify(self.apk,self.lock))

    def test_partial_or_invalid_lock_rejected(self):
        self.document['payloads'].pop(next(iter(self.payloads)))
        self.save()
        self.assertTrue(gate.verify(self.apk,self.lock))
        self.lock.write_text('not json')
        self.assertTrue(gate.verify(self.apk,self.lock))

    def test_4k_alignment_rejected_even_with_matching_hash(self):
        name = next(iter(self.payloads))
        data = bytearray(self.payloads[name])
        struct.pack_into('<Q', data, 112, 4096)
        self.payloads[name] = bytes(data)
        self.document['payloads'][name] = hashlib.sha256(data).hexdigest()
        self.save()
        self.assertTrue(any('not 16KiB' in e for e in gate.verify(self.apk,self.lock)))

    def test_no_implicit_source_acceptance(self):
        # A lock included in an APK cannot opt out of the old patch checks.
        with zipfile.ZipFile(self.apk, 'a') as archive:
            archive.writestr('assets/source-frontend-lock.json', json.dumps(self.document))
        self.assertTrue(one_app.verify_frontend_launch_lifecycle(self.apk))
        self.assertTrue(one_app.verify_qt_gamepad_null_guard(self.apk))

    def test_source_identity_does_not_skip_other_one_app_checks(self):
        aapt = self.folder/'aapt'
        aapt.touch()
        from types import SimpleNamespace
        with patch.object(one_app.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')), \
             patch.object(one_app,'verify_manifest',return_value=['manifest sentinel']), \
             patch.object(one_app,'verify_dex',return_value=['DEX sentinel']), \
             patch.object(one_app,'verify_branding',return_value=['branding sentinel']), \
             patch.object(one_app,'verify_external_stop_payload',return_value=[]), \
             patch.object(one_app,'verify_frontend_restart_payload',return_value=[]), \
             patch.object(one_app,'verify_voice_feedback_payload',return_value=[]), \
             patch.object(one_app,'verify_lsfg_self_test_boundary',return_value=[]):
            self.assertEqual(one_app.verify(self.apk,aapt,source_frontend_lock=self.lock),
                             ['manifest sentinel','DEX sentinel','branding sentinel'])

    def stage_fixture(self):
        source, decoded = self.folder/'kit', self.folder/'decoded'
        source.mkdir()
        (decoded/gate.PREFIX).mkdir(parents=True)
        for name, data in self.payloads.items():
            (source/Path(name).name).write_bytes(data)
            (decoded/name).write_bytes(b'old frontend')
        (decoded/gate.PREFIX/'liblucent_core_fixture.so').write_bytes(b'unchanged engine')
        return source, decoded

    def test_stage_full_cohort_and_preserve_engines(self):
        source, decoded = self.stage_fixture()
        self.assertEqual(staging.stage(source,self.lock,decoded),49)
        for name,data in self.payloads.items():
            self.assertEqual((decoded/name).read_bytes(),data)
        self.assertEqual((decoded/gate.PREFIX/'liblucent_core_fixture.so').read_bytes(),b'unchanged engine')

    def test_install_generated_kit_and_repeat_without_replacing_it(self):
        source, _ = self.stage_fixture()
        target = self.folder/'build/source-frontend'
        self.assertEqual(installation.install(source, self.lock, target), 'installed')
        before = {p.name:p.stat().st_mtime_ns for p in target.iterdir()}
        self.assertEqual(gate.verify_directory(target, self.lock), [])
        self.assertEqual(installation.install(source, self.lock, target), 'already installed')
        self.assertEqual(before, {p.name:p.stat().st_mtime_ns for p in target.iterdir()})

    def test_install_preserves_unknown_existing_kit(self):
        source, _ = self.stage_fixture()
        target = self.folder/'existing'
        target.mkdir()
        sentinel = target/'libQt5Other.so'
        sentinel.write_bytes(b'other agent artifact')
        with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
            installation.install(source, self.lock, target)
        self.assertEqual(sentinel.read_bytes(), b'other agent artifact')
        self.assertEqual(list(target.iterdir()), [sentinel])

    def test_install_invalid_input_never_creates_destination(self):
        source, _ = self.stage_fixture()
        next(source.iterdir()).write_bytes(b'invalid')
        target = self.folder/'new-kit'
        with self.assertRaises(ValueError):
            installation.install(source, self.lock, target)
        self.assertFalse(target.exists())

    def test_invalid_kit_does_not_partially_change_decoded_files(self):
        for mode in ('missing','changed','extra'):
            with self.subTest(mode=mode):
                source,decoded = self.stage_fixture()
                name=Path(next(iter(self.payloads))).name
                if mode=='missing': (source/name).unlink()
                elif mode=='changed': (source/name).write_bytes(b'changed')
                else: (source/'libQt5Unexpected.so').write_bytes(b'extra')
                before={p.name:p.read_bytes() for p in (decoded/gate.PREFIX).glob('*.so')}
                with self.assertRaises(ValueError): staging.stage(source,self.lock,decoded)
                self.assertEqual({p.name:p.read_bytes() for p in (decoded/gate.PREFIX).glob('*.so')},before)
                import shutil
                shutil.rmtree(source)
                shutil.rmtree(decoded)

    def test_partial_decoded_cohort_rejected(self):
        source,decoded=self.stage_fixture()
        (decoded/next(iter(self.payloads))).unlink()
        with self.assertRaisesRegex(ValueError,'partial migration'):
            staging.stage(source,self.lock,decoded)

    def test_nested_lock_names_rejected_before_staging(self):
        name=next(n for n in self.document['payloads'] if Path(n).name.startswith('libQt5'))
        digest=self.document['payloads'].pop(name)
        self.document['payloads'][gate.PREFIX+'../'+Path(name).name]=digest
        self.save()
        self.assertTrue(gate.verify(self.apk,self.lock))

    def test_build_requires_paired_source_inputs_and_no_release(self):
        build=(ROOT/'unified-android/build.sh').read_text()
        block=build[build.index('SOURCE_FRONTEND_DIR='):build.index('\nexport JAVA_HOME')]
        base={k:v for k,v in os.environ.items() if not k.startswith('LUCENT_SOURCE_FRONTEND') and k!='LUCENT_SIGNING_PROFILE'}
        for variables, expected in [({},0),({'LUCENT_SOURCE_FRONTEND_DIR':'kit'},1),
            ({'LUCENT_SOURCE_FRONTEND_LOCK':'lock'},1),
            ({'LUCENT_SOURCE_FRONTEND_DIR':'kit','LUCENT_SOURCE_FRONTEND_LOCK':'lock'},0),
            ({'LUCENT_SOURCE_FRONTEND_DIR':'kit','LUCENT_SOURCE_FRONTEND_LOCK':'lock','LUCENT_SIGNING_PROFILE':'release'},1)]:
            with self.subTest(variables=variables):
                result=subprocess.run(['sh','-eu','-c',block],env=dict(base,**variables),capture_output=True)
                self.assertEqual(result.returncode,expected,result.stderr)
        self.assertIn('set -- "$@" --source-frontend-lock "$SOURCE_FRONTEND_LOCK"',build)

if __name__ == '__main__':
    unittest.main()
