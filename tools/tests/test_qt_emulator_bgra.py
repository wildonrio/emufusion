"""Exercise exact Qt patch decisions and round-trip against pinned archives."""
import re
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'unified-android/build/qt-5.15.10-16k'
CASES=[('qtbase','src/gui/opengl/qopenglfunctions.cpp','qtbase-android-emulator-bgra.patch'),
       ('qtbase','src/gui/opengl/qopengltextureuploader.cpp','qtbase-android-emulator-texture-upload.patch'),
       ('qtdeclarative','src/quick/scenegraph/util/qsgopenglatlastexture.cpp','qtdeclarative-android-emulator-bgra.patch')]

class QtEmulatorBgraTest(unittest.TestCase):
    def test_patches_round_trip_and_execute_renderer_decision(self):
        for module,relative,patch_name in CASES:
            with self.subTest(module=module), tempfile.TemporaryDirectory() as temp:
                target=Path(temp)/relative
                target.parent.mkdir(parents=True)
                with tarfile.open(WORK/'downloads'/f'{module}-everywhere-opensource-src-5.15.10.tar.xz') as archive:
                    member,=[m for m in archive.getmembers() if m.name.endswith('/'+relative)]
                    original=archive.extractfile(member).read()
                target.write_bytes(original)
                patch=ROOT/'unified-android/tools'/patch_name
                result=subprocess.run(['patch','-f','-p1','-i',str(patch)],cwd=temp,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                source=target.read_text()
                declaration,=re.findall(r'const bool brokenEmulatorBgra = ([^;]+);',source)
                # Execute the production predicate, including null and real
                # device renderers; keep existing known-broken Samsung behavior.
                fixture='''#include <cstring>
bool check(const char *renderer, bool samsung) {
    const bool brokenEmulatorBgra = '''+declaration+''';
    return samsung || brokenEmulatorBgra;
}
int main() {
    if(!check("Android Emulator OpenGL ES Translator (Apple M1 Max)",false))return 1;
    if(check("ANGLE (SwiftShader Device)",false))return 2;
    if(check("Adreno (TM) 740",false))return 3;
    if(check("Mali-G715",false))return 4;
    if(check(nullptr,false))return 5;
    if(!check("other",true))return 6;
    return 0;
}
'''
                binary=Path(temp)/'test'
                subprocess.run(['/usr/bin/clang++','-std=c++11','-x','c++','-','-o',str(binary)],input=fixture,text=True,check=True,capture_output=True)
                subprocess.run([str(binary)],check=True,capture_output=True)
                if relative.endswith('qopengltextureuploader.cpp'):
                    self.assertRegex(source,r'if \(brokenEmulatorBgra\)\s+break;')
                    self.assertIn('image.convertToFormat(targetFormat)',source)
                elif module=='qtbase':
                    self.assertIn('if (wrongfullyReportsBgra8888Support || brokenEmulatorBgra)',source)
                else:
                    self.assertNotIn('static bool wrongfullyReportsBgra8888Support = deviceName',source)
                    self.assertIn('wrongfullyReportsBgra8888Support = wrongfullyReportsBgra8888Support || brokenEmulatorBgra;',source)
                subprocess.run(['patch','-f','-R','-p1','-i',str(patch)],cwd=temp,check=True,capture_output=True)
                self.assertEqual(target.read_bytes(),original)

    def test_normal_builds_apply_both_patches(self):
        base=(ROOT/'unified-android/tools/build_qt_base_android.sh').read_text()
        self.assertEqual(base.count('apply_source_patch qtbase-android-emulator-bgra.patch'),2)
        self.assertEqual(base.count('apply_source_patch qtbase-android-emulator-texture-upload.patch'),2)
        module=(ROOT/'unified-android/tools/build_qt_module_android.sh').read_text()
        self.assertIn('"$MODULE" = qtdeclarative',module)
        self.assertIn('qtdeclarative-android-emulator-bgra.patch',module)

if __name__=='__main__': unittest.main()
