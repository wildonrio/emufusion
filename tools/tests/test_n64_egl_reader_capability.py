"""Compile the actual pinned GLInfo capability gate for all build variants."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / 'engines/patches/mupen64plus-next-egl-reader-capability.patch'
REL = 'GLideN64/src/Graphics/OpenGLContext/opengl_GLInfo.cpp'
COMMIT = 'f275caf4b2bfa1e6d1c51636746ea793f3d80320'


class N64EglReaderCapabilityTest(unittest.TestCase):
    def test_recipe_pins_capability_patch(self):
        recipe = (ROOT / 'engines/build_core.sh').read_text().split(
            '    mupen64plus-next)\n', 1)[1].split('    armsx2)', 1)[0]
        self.assertIn(str(PATCH.relative_to(ROOT)), recipe)
        self.assertIn(hashlib.sha256(PATCH.read_bytes()).hexdigest(), recipe)

    def test_actual_gate_matches_compiled_reader(self):
        archive = ROOT / ('engines/build/sources/mupen64plus-next-' + COMMIT + '.tar.gz')
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
            '1810b7bbdc4abfdeee8a9f7f99c4a91dab601a228935802317c25a43d7cf9dbb')
        with tempfile.TemporaryDirectory(prefix='n64-egl-capability-') as temporary:
            work = Path(temporary)
            source = work / REL
            source.parent.mkdir(parents=True)
            with tarfile.open(archive) as tar:
                names = [n for n in tar.getnames() if n.endswith('/' + REL)]
                self.assertEqual(len(names), 1)
                source.write_bytes(tar.extractfile(names[0]).read())
            if not os.environ.get('N64_EGL_TEST_UNPATCHED'):
                result = subprocess.run(['patch', '-p1', '-d', str(work), '-i', str(PATCH)],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # Exercise the selected source's actual gate, not copied expected logic.
            gate = source.read_text().split(
                '\tanisotropic_filtering = Utils::isExtensionSupported(*this, "GL_EXT_texture_filter_anisotropic");\n', 1
            )[1].split('\n\tif (config.frameBufferEmulation.N64DepthCompare', 1)[0]
            harness = r'''
#include <cassert>
enum class Renderer { Other, PowerVR, Tegra, Angle, Intel };
static bool support, publicSupport;
struct GraphicBufferWrapper {
    static bool isSupportAvailable() { return support; }
    static bool isPublicSupportAvailable() { return publicSupport; }
};
namespace graphics { namespace textureTarget { static int TEXTURE_EXTERNAL; } }
#define GL_TEXTURE_2D 3553
static void check(bool advertised, bool gles2, bool gles, Renderer renderer) {
    bool eglImage = advertised, eglImageFramebuffer = false;
    bool isGLES2 = gles2, isGLESX = gles;
''' + gate + r'''
    bool expected = false;
#if defined(EGL) && defined(OS_ANDROID) && !defined(WEBOS)
    expected = advertised && ((gles2 && support) || (gles && publicSupport)) &&
        renderer != Renderer::PowerVR && renderer != Renderer::Tegra && renderer != Renderer::Angle;
#endif
    assert(eglImage == expected);
    assert(eglImageFramebuffer == (expected && !gles2));
}
int main() {
    for (int flags=0; flags<32; ++flags) {
        support = flags & 1; publicSupport = flags & 2;
        for (auto renderer : {Renderer::Other, Renderer::PowerVR, Renderer::Tegra, Renderer::Angle, Renderer::Intel})
            check(flags & 4, flags & 8, flags & 16, renderer);
    }
}
'''
            harness = '#include <initializer_list>\n' + harness
            (work / 'test.cpp').write_text(harness)
            variants = [[], ['EGL'], ['OS_ANDROID'], ['EGL', 'OS_ANDROID'],
                ['EGL', 'OS_ANDROID', 'WEBOS']]
            for defines in variants:
                with self.subTest(defines=defines):
                    result = subprocess.run([shutil.which('clang++'), '-std=c++11', '-O1',
                        '-fsanitize=address,undefined', *['-D' + d for d in defines],
                        str(work / 'test.cpp'), '-o', str(work / 'test')],
                        capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    result = subprocess.run([str(work / 'test')], capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
