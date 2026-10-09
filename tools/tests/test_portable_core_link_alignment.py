"""Execute each recipe's actual CMake arguments with the Android linker.

This small fixture checks that both shared and module libraries receive the
page-size policy, independently of the heavier owned-ROM runtime qualification.
"""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ.get('ANDROID_SDK_ROOT', '/Users/tyleryoung/Code/cemu/Cemu-0.5/android-sdk'))
CMAKE = SDK / 'cmake/3.31.6/bin/cmake'
NDK = SDK / 'ndk/27.0.12077973'
SPEC = importlib.util.spec_from_file_location('elf_alignment', ROOT / 'unified-android/tools/verify_elf_alignment.py')
ELF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ELF)


class PortableCoreLinkAlignmentTest(unittest.TestCase):
    def test_actual_recipe_cmake_options_align_both_library_types(self):
        if not CMAKE.is_file() or not NDK.is_dir():
            self.skipTest('Android NDK 27/CMake fixture toolchain unavailable')
        recipe = (ROOT / 'engines/build_core.sh').read_text()
        for engine in ('melonds-ds', 'swanstation', 'flycast', 'mgba', 'applewin', 'ppsspp', 'play'):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source, build = root / 'source', root / 'build'
                source.mkdir()
                (source / 'fixture.c').write_text('int portable_fixture(void) { return 42; }\n')
                (source / 'CMakeLists.txt').write_text(
                    'cmake_minimum_required(VERSION 3.20)\nproject(PageFixture C)\n'
                    'add_library(shared SHARED fixture.c)\nadd_library(module MODULE fixture.c)\n')
                branch = recipe.split('    ' + engine + ')\n', 1)[1].split('\n        ;;', 1)[0]
                if engine in ('flycast', 'ppsspp', 'play'):
                    configure = re.search(r' +"\$' + engine + r'_cmake" -S .*?(?=\n        LC_ALL=C)', branch, re.S).group(0)
                else:
                    configure = re.search(r'        (?:SOURCE_DATE_EPOCH=0 )?"\$CMAKE" -S .*?(?=\n        (?:GIT_CEILING_DIRECTORIES=.*?\n        )?(?:SOURCE_DATE_EPOCH=0 )?"\$CMAKE" --build)', branch, re.S).group(0)
                env = dict(os.environ, CMAKE=str(CMAKE), NINJA='/opt/homebrew/bin/ninja',
                           NDK_DIR=str(NDK), ABI='arm64-v8a', API='23',
                           source=str(source), staged_source=str(source), canonical_source=str(source), build=str(build), stage=str(build),
                           mgba_path_flags='', flycast_cmake=str(CMAKE), flycast_ninja='/opt/homebrew/bin/ninja',
                           flycast_ndk_dir=str(NDK), flycast_api='24', path_map_flags='',
                           ppsspp_cmake=str(CMAKE), ppsspp_ninja='/opt/homebrew/bin/ninja',
                           ppsspp_ndk_dir=str(NDK), ppsspp_use_ffmpeg='ON',
                           play_cmake=str(CMAKE), play_ninja='/opt/homebrew/bin/ninja', play_ndk_dir=str(NDK))
                subprocess.run(['sh', '-eu', '-c', configure], env=env, check=True, capture_output=True)
                actual_build = build / 'out' if engine in ('flycast', 'play') else build
                subprocess.run([str(CMAKE), '--build', str(actual_build)], check=True, capture_output=True)
                for name in ('shared', 'module'):
                    alignments = ELF.load_alignments((actual_build / ('lib' + name + '.so')).read_bytes())
                    self.assertGreaterEqual(min(alignments), 16384, (engine, name, alignments))


if __name__ == '__main__':
    unittest.main()
