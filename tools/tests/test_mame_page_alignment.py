"""Execute the real MAME build invocation against a minimal link fixture."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NDK = Path('/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk/ndk/27.0.12077973')
spec = importlib.util.spec_from_file_location('alignment', ROOT/'unified-android/tools/verify_elf_alignment.py')
alignment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alignment)

class MamePageAlignmentTest(unittest.TestCase):
    def test_real_recipe_passes_alignment_to_upstream_make(self):
        cc = NDK/'toolchains/llvm/prebuilt/darwin-x86_64/bin/aarch64-linux-android24-clang'
        if not cc.exists(): self.skipTest('Exact NDK unavailable')
        branch = (ROOT/'engines/build_core.sh').read_text().split('    mame)\n',1)[1]
        start = branch.index('        ANDROID_NDK_HOME=')
        end = branch.index('PYTHON_EXECUTABLE=python3',start)+len('PYTHON_EXECUTABLE=python3')
        with tempfile.TemporaryDirectory(prefix='mame-page-fixture-') as folder:
            source = Path(folder)
            (source/'fixture.c').write_text('int core_fixture(void) { return 42; }\n')
            (source/'Makefile.libretro').write_text('.PHONY: all clean\nall:\n\t$(CC) -shared -fPIC fixture.c $(LDOPTS) -o fixture.so\nclean:\n\t@:\n')
            env = dict(os.environ, NDK_DIR=str(NDK), source=folder, CC=str(cc),
                       platform='android-arm64',subtarget='lucent',sources='fixture.c',LUCENT_BUILD_JOBS='1')
            subprocess.run(['sh','-eu','-c',branch[start:end]], env=env, check=True, capture_output=True)
            self.assertGreaterEqual(min(alignment.load_alignments((source/'fixture.so').read_bytes())),16384)

if __name__ == '__main__': unittest.main()
