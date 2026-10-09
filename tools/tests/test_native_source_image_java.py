"""Compile Java parser against bytes emitted by the actual C ABI; no device proof."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
JAVA = Path(os.environ.get("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"), "bin")


class NativeSourceImageJavaTest(unittest.TestCase):
    def test_compiled_parser_and_c_abi_fixture(self):
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "C compiler required; do not silently skip")
        self.assertTrue((JAVA / "javac").is_file(), "JDK required; do not silently skip")
        with tempfile.TemporaryDirectory(prefix="source-image-java-") as temporary:
            directory = Path(temporary)
            source = directory / "abi.c"
            source.write_text(r'''
#include "lucent_native_source_image.h"
#include <stddef.h>
#include <stdio.h>
_Static_assert(sizeof(lucent_source_image_v1) == 808, "image layout");
_Static_assert(sizeof(lucent_source_layer_v1) == 88, "layer layout");
_Static_assert(sizeof(lucent_source_binding_v1) == 64, "binding layout");
_Static_assert(offsetof(lucent_source_image_v1, composition) == 40, "composition offset");
_Static_assert(offsetof(lucent_source_composition_v1, layers) == 64, "layers offset");
int main(void) {
    lucent_source_image_v1 image = {0};
    image.version=1; image.struct_size=sizeof(image); image.state=1;
    image.submission_ordinal=1; image.buffer_timestamp_ns=1100;
    image.vk_present_id=1; image.swapchain_image_index=2;
    image.composition.header=(lucent_source_composition_header_v1){11,22,33,0,1,1000,1,1};
    image.composition.retained_layer_count=1;
    image.composition.layers[0]=(lucent_source_layer_v1){
        .queue_epoch=44,.queue_frame_number=1,.guest_requested_timestamp_ns=-700,
        .consumer_id=7,.buffer_slot=1,.raw_swap_interval=2,.normalized_swap_interval=2,
        .flags=1,.width=1280,.height=720,.stride=1280,.pixel_format=1,
        .crop_right=1280,.crop_bottom=720};
    lucent_source_binding_v1 binding={1,sizeof(binding),11,22,33,0,0,0,0};
    return fwrite(&image, sizeof(image), 1, stdout) != 1 ||
           fwrite(&binding, sizeof(binding), 1, stdout) != 1;
}
''')
            native = directory / "abi"
            subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT / "unified-android/native/include"),
                            str(source), "-o", str(native)], check=True, capture_output=True)
            fixture = directory / "fixture.bin"
            fixture.write_bytes(subprocess.run([str(native)], check=True, capture_output=True).stdout)
            subprocess.run([str(JAVA / "javac"), "--release", "8", "-d", str(directory),
                            str(ROOT / "unified-android/src/com/thorium/lucent/video/NativeSourceImage.java"),
                            str(ROOT / "unified-android/test/com/thorium/lucent/video/NativeSourceImageTest.java")],
                           check=True, capture_output=True)
            result = subprocess.run([str(JAVA / "java"), "-cp", str(directory),
                                     "com.thorium.lucent.video.NativeSourceImageTest", str(fixture)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("metadata only; no source authority", result.stdout)


if __name__ == "__main__":
    unittest.main()
