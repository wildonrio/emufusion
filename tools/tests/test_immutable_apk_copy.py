"""Execute the build's real final-copy block, including partial-copy failures."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ImmutableApkCopyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='immutable-apk-test-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'mutable.apk'
        self.source.write_bytes(b'verified signed package\n' * 256)
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.target = self.folder / (self.digest + '.apk')
        code = (ROOT / 'unified-android/build.sh').read_text()
        start = code.index('if [ -f "$IMMUTABLE_OUTPUT" ]; then')
        self.block = code[start:code.index('\nif [ "$SIGNING_PROFILE" = debug ]; then', start)]
        binaries = self.folder / 'bin'
        binaries.mkdir()
        # Exercise APFS failure/fallback deterministically on any host.
        cp = binaries / 'cp'
        cp.write_text('''#!/bin/sh
if [ "$1" = -c ]; then exit 1; fi
case "$COPY_TEST_MODE" in
  fail) printf partial > "$2"; exit 28 ;;
  corrupt) printf corrupted > "$2"; exit 0 ;;
esac
exec /bin/cp "$@"
''')
        cp.chmod(0o755)
        self.env = dict(os.environ, BUILD_DIR=str(self.folder), OUTPUT=str(self.source),
                        IMMUTABLE_OUTPUT=str(self.target), OUTPUT_SHA=self.digest,
                        PATH=str(binaries) + os.pathsep + os.environ['PATH'])

    def run_copy(self, mode=''):
        return subprocess.run(['sh', '-eu', '-c', self.block],
                              env=dict(self.env, COPY_TEST_MODE=mode),
                              text=True, capture_output=True)

    def test_copy_is_verified_and_temporary_removed(self):
        result = self.run_copy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(list(self.folder.glob('.immutable-apk.*')), [])
        self.source.write_bytes(b'next build')
        self.assertEqual(hashlib.sha256(self.target.read_bytes()).hexdigest(), self.digest)

    def test_existing_exact_artifact_is_not_rewritten(self):
        self.target.write_bytes(self.source.read_bytes())
        inode = self.target.stat().st_ino
        result = self.run_copy('fail')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.stat().st_ino, inode)

    def test_existing_collision_is_preserved_and_rejected(self):
        self.target.write_bytes(b'pre-existing collision')
        result = self.run_copy()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('artifact collision', result.stderr)
        self.assertEqual(self.target.read_bytes(), b'pre-existing collision')

    def test_partial_copy_never_gets_hash_named_path(self):
        result = self.run_copy('fail')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.folder.glob('.immutable-apk.*')), [])
        retry = self.run_copy()
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())

    def test_successful_but_corrupted_copy_is_rejected(self):
        result = self.run_copy('corrupt')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.folder.glob('.immutable-apk.*')), [])


class PackagingCleanupTest(unittest.TestCase):
    def test_success_discards_only_regenerable_assembly_directories(self):
        code = (ROOT / 'unified-android/build.sh').read_text()
        start = code.index('# Successful assembly scratch is not a cache:')
        # Exercise the scratch cleanup itself. The following retention hook has
        # its own policy/lock tests and must not run against this fake build.
        cleanup = code[start:code.index('# Publishing changes the newest-per-flavor set.', start)]
        with tempfile.TemporaryDirectory() as folder:
            build = Path(folder)
            disposable = ['work', 'classes', 'stub-classes', 'dex']
            retained = ['deps', 'native', 'source-frontend', 'retention-receipts']
            for name in disposable + retained:
                (build / name).mkdir()
                (build / name / 'fixture').write_bytes(b'keep or regenerate')
            (build / 'signed.apk').write_bytes(b'verified')
            result = subprocess.run(['sh', '-eu', '-c', cleanup],
                env=dict(os.environ, BUILD_DIR=str(build)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in disposable:
                self.assertFalse((build / name).exists(), name)
            for name in retained:
                self.assertEqual((build / name / 'fixture').read_bytes(), b'keep or regenerate')
            self.assertEqual((build / 'signed.apk').read_bytes(), b'verified')

    def test_real_exit_trap_removes_only_packaging_intermediates(self):
        code = (ROOT / 'unified-android/build.sh').read_text()
        start = code.index('cleanup_build_lock() {')
        end = code.index('\n# Bound historical APK disk use', start)
        cleanup = code[start:end]
        for termination, expected in [('exit 0', 0), ('exit 7', 7),
                                      ('kill -TERM $$', 143)]:
            with self.subTest(termination=termination), tempfile.TemporaryDirectory() as folder:
                build = Path(folder)
                lock = build / '.lucent-build-lock'
                lock.mkdir()
                (lock / 'pid').write_text('fixture')
                disposable = ['lucent-unified-unsigned.apk', 'lucent-unified-aligned.apk']
                retained = ['signed.apk', 'rollback.apk', 'libcore.so', 'save.bin', 'build.log']
                for name in disposable + retained:
                    (build / name).write_bytes(b'fixture')
                result = subprocess.run(['sh', '-eu', '-c', cleanup + '\n' + termination],
                    env=dict(os.environ, BUILD_DIR=str(build), BUILD_LOCK=str(lock)),
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertFalse(lock.exists())
                for name in disposable:
                    self.assertFalse((build / name).exists(), name)
                for name in retained:
                    self.assertEqual((build / name).read_bytes(), b'fixture', name)


if __name__ == '__main__':
    unittest.main()
