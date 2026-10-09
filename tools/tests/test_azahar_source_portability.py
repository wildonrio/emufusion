"""Compile the actual pinned error formatter against both Android signatures."""
from pathlib import Path
import importlib.util
import json
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'engines/build/sources/azahar-b42d0916ba9799297ae0e27c07d56801da1b5de5'
BIN = Path('/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk/ndk/27.0.12077973/toolchains/llvm/prebuilt/darwin-x86_64/bin')
SPEC = importlib.util.spec_from_file_location('build_azahar', ROOT / 'engines/tools/build_azahar.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)

class AzaharAndroidSourceTest(unittest.TestCase):
    def test_publish_keeps_known_old_core_and_preserves_unknown_edits(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            candidate, target = folder / 'new.so', folder / 'azahar_libretro.so'
            candidate.write_bytes(b'new verified core')
            target.write_bytes(b'old upstream core')
            old = BUILDER.digest(target)
            lock = {'sourceBuild': {'artifactSha256': BUILDER.digest(candidate)},
                    'referenceReleaseArtifact': {'memberSha256': old}}
            BUILDER.publish_artifact(candidate, target, lock)
            self.assertEqual(b'new verified core', target.read_bytes())
            self.assertEqual(b'old upstream core', target.with_name(target.name + '.previous-' + old).read_bytes())
            candidate.write_bytes(b'new verified core')
            target.write_bytes(b'another agent build')
            with self.assertRaisesRegex(ValueError, 'Unknown Azahar output'):
                BUILDER.publish_artifact(candidate, target, lock)
            self.assertEqual(b'another agent build', target.read_bytes())
            self.assertTrue(candidate.exists())

    def test_publish_rejects_untested_binary_before_replacing_known_old_core(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            candidate, target = folder / 'new.so', folder / 'azahar_libretro.so'
            candidate.write_bytes(b'untested core')
            target.write_bytes(b'old core')
            lock = {'sourceBuild': {'artifactSha256': '0' * 64},
                    'referenceReleaseArtifact': {'memberSha256': BUILDER.digest(target)}}
            with self.assertRaisesRegex(ValueError, 'differs from tested artifact'):
                BUILDER.publish_artifact(candidate, target, lock)
            self.assertEqual(b'old core', target.read_bytes())

    def source_fixture(self, temp):
        source = temp / 'source'
        (source / 'src/common').mkdir(parents=True)
        target = source / 'src/common/error.cpp'
        target.write_bytes((SOURCE / 'src/common/error.cpp').read_bytes())
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        subprocess.run(['git', '-C', str(source), 'add', 'src'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=QA',
            '-c', 'user.email=qa@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        lock = json.loads((ROOT / 'engines/azahar-source-lock.json').read_text())
        lock['core']['commit'] = BUILDER.git(source, 'rev-parse', 'HEAD')
        lock['dependencies'] = []
        return source, target, lock

    def test_source_recipe_accepts_only_the_exact_patch_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as name:
            source, target, lock = self.source_fixture(Path(name))
            BUILDER.verify_source(source, lock)
            expected = target.read_bytes()
            BUILDER.verify_source(source, lock)
            self.assertEqual(expected, target.read_bytes())
            target.write_bytes(expected + b'\n// another agent edit\n')
            modified = target.read_bytes()
            with self.assertRaisesRegex(ValueError, 'Unexpected edits'):
                BUILDER.verify_source(source, lock)
            self.assertEqual(modified, target.read_bytes())

    def test_source_recipe_rejects_changed_commit_and_dependency_set(self):
        with tempfile.TemporaryDirectory() as name:
            source, target, lock = self.source_fixture(Path(name))
            original = target.read_bytes()
            commit = lock['core']['commit']
            lock['core']['commit'] = '0' * 40
            with self.assertRaisesRegex(ValueError, 'source commit differs'):
                BUILDER.verify_source(source, lock)
            lock['core']['commit'] = commit
            lock['dependencies'] = [{'path': 'externals/missing', 'commit': '1' * 40}]
            with self.assertRaisesRegex(ValueError, 'dependency set differs'):
                BUILDER.verify_source(source, lock)
            self.assertEqual(original, target.read_bytes())

    def test_normal_recipe_builds_and_never_extracts_the_old_4k_core(self):
        recipe = (ROOT / 'engines/build_core.sh').read_text().split('    azahar)', 1)[1].split('    play)', 1)[0]
        self.assertIn('engines/tools/build_azahar.py', recipe)
        self.assertNotIn('unzip', recipe)
        self.assertNotIn('fetch_file', recipe)

    def test_error_formatter_handles_api21_and_api23_libretro(self):
        if not SOURCE.is_dir() or not BIN.is_dir():
            self.skipTest('Pinned Azahar source and Android NDK unavailable')
        with tempfile.TemporaryDirectory() as name:
            temp = Path(name)
            dest = temp / 'src/common'
            dest.mkdir(parents=True)
            for file in ('error.cpp', 'error.h'):
                (dest / file).write_bytes((SOURCE / 'src/common' / file).read_bytes())
            def compile(api):
                return subprocess.run([str(BIN / f'aarch64-linux-android{api}-clang++'),
                    '-std=gnu++20', '-DHAVE_LIBRETRO', '-I' + str(temp / 'src'),
                    '-c', str(dest / 'error.cpp'), '-o', str(temp / f'error{api}.o')],
                    capture_output=True, text=True)
            old = compile(23)
            self.assertNotEqual(old.returncode, 0)
            self.assertIn("cannot initialize a variable of type 'int'", old.stderr)
            subprocess.run(['patch', '-p1', '-i', str(ROOT / 'engines/patches/azahar-android-strerror.patch')],
                cwd=temp, check=True, capture_output=True)
            for api, symbol in ((21, 'strerror_r'), (23, '__gnu_strerror_r')):
                with self.subTest(api=api):
                    result = compile(api)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    names = subprocess.check_output([str(BIN / 'llvm-nm'), '-u', str(temp / f'error{api}.o')], text=True)
                    self.assertIn('U ' + symbol + '\n', names)

if __name__ == '__main__':
    unittest.main()
