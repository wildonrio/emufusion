"""Regression coverage for the isolated ARM interpreter MMIO correction."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / 'docs/qa/android-portability-2026-10-06-ps3-ppu-interpreter'
PATCH = ROOT / 'engines/patches/aps3e-ppu-interpreter-mmio.patch'
RELATIVE = Path('app/src/main/cpp/rpcs3/rpcs3/Emu/Cell')
SPEC = importlib.util.spec_from_file_location('mmio_prepare', QA / 'prepare_mmio.py')
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


class InterpreterMMIOTests(unittest.TestCase):
    def test_patch_matches_compiled_candidate_and_roundtrips(self):
        original = PREPARE.SOURCE.read_bytes()
        with tempfile.TemporaryDirectory(prefix='aps3e-mmio-patch-') as directory:
            root = Path(directory)
            target = root / RELATIVE / 'PPUInterpreter.cpp'
            target.parent.mkdir(parents=True)
            target.write_bytes(original)
            command = ['git', 'apply', '--unsafe-paths']
            subprocess.run([*command, str(PATCH)], cwd=root, check=True)
            self.assertEqual(target.read_text(), PREPARE.transform(original))
            header = target.parent / 'ppu_interpreter_mmio.h'
            self.assertEqual(header.read_bytes(), (QA / header.name).read_bytes())
            again = subprocess.run([*command, '--check', str(PATCH)], cwd=root,
                                   capture_output=True)
            self.assertNotEqual(again.returncode, 0)
            subprocess.run([*command, '--reverse', str(PATCH)], cwd=root, check=True)
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse(header.exists())

    def test_actual_header_old_failure_new_pass_nonarm_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='aps3e-mmio-code-') as directory:
            for name, flags, expected in (
                ('old', ['-DARCH_ARM64', '-DOLD_DIRECT_MEMORY'], 2),
                ('new', ['-DARCH_ARM64'], 0),
                ('nonarm', [], 2),
            ):
                binary = Path(directory) / name
                subprocess.run(['clang++', '-std=c++20', '-O1', '-Wall', '-Wextra',
                    '-fsanitize=address,undefined', *flags, str(QA / 'mmio_test.cpp'),
                    '-o', str(binary)], check=True)
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertIn('checks passed' if expected == 0 else 'unmapped MMIO',
                              result.stdout if expected == 0 else result.stderr)

    def test_exec_out_does_not_double_quote_shell_expression(self):
        fixture = ROOT / 'docs/qa/android-portability-2026-10-06-ps3-ppu-mmio/device.py'
        tree = ast.parse(fixture.read_text())
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == 'native_bytes')
        calls = []
        class Device:
            PKG = 'test.package'
        namespace = {'d': Device, 'raw': lambda *args: calls.append(args) or b'log bytes'}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(fixture), 'exec'), namespace)
        command = 'head -c 1234 log.txt | tail -c 512'
        self.assertEqual(namespace['native_bytes'](command), b'log bytes')
        self.assertEqual(calls, [('exec-out', 'run-as', 'test.package', 'sh', '-c', command)])
        namespace['raw'] = lambda *args: b'sh: command: inaccessible or not found\n'
        with self.assertRaisesRegex(AssertionError, 'shell error'):
            namespace['native_bytes'](command)


if __name__ == '__main__':
    unittest.main()
