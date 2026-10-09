"""Execute the actual image-request selection, not a copied policy model.

This covers supported request bounds, not driver allocation or GPU latency;
those require the separately recorded device captures.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'unified-android/native/lucent_android_vulkan_backend.c'


def harness(source):
    bodies = []
    for name in ('create_swapchain', 'create_secondary_swapchain'):
        function = source.split('static bool ' + name + '(', 1)[1]
        start = function.index('    desired = capabilities.minImageCount')
        end = function.index('    memset(&info, 0, sizeof(info));', start)
        bodies.append(function[start:end])
    return r'''
#include <assert.h>
#include <stdint.h>
#define LUCENT_VK_MAX_IMAGES 8
typedef struct { uint32_t minImageCount, maxImageCount; } Caps;
static uint32_t primary(Caps capabilities) {
 uint32_t desired;
''' + bodies[0] + r'''
 return desired;
}
static uint32_t secondary(Caps capabilities) {
 uint32_t desired;
''' + bodies[1] + r'''
 return desired;
}
int main(void) {
 for (uint32_t low=1; low<=LUCENT_VK_MAX_IMAGES; ++low) {
  for (uint32_t high=0; high<=64; ++high) {
   if (high && high<low) continue;
   Caps caps={low,high};
   assert(primary(caps)==low);
   uint32_t expected=low+1;
   if (high && expected>high) expected=high;
   if (expected>LUCENT_VK_MAX_IMAGES) expected=LUCENT_VK_MAX_IMAGES;
   assert(secondary(caps)==expected);
  }
 }
}
'''


def execute(source, folder, label):
    c_file = folder / (label + '.c')
    binary = folder / label
    c_file.write_text(harness(source))
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(c_file), '-o', str(binary)],
                   check=True, capture_output=True)
    return subprocess.run([str(binary)], capture_output=True, timeout=15)


class VulkanMinimumQueueTest(unittest.TestCase):
    def test_primary_requests_minimum_secondary_remains_unchanged(self):
        source = SOURCE.read_text()
        with tempfile.TemporaryDirectory(prefix='vulkan-minimum-') as temp:
            result = execute(source, Path(temp), 'actual')
            self.assertEqual(0, result.returncode, result.stderr.decode())

    def test_extra_primary_image_regression_is_detected(self):
        source = SOURCE.read_text()
        anchor = 'desired = capabilities.minImageCount;'
        self.assertEqual(1, source.count(anchor))
        mutant = source.replace(anchor, 'desired = capabilities.minImageCount + 1;', 1)
        with tempfile.TemporaryDirectory(prefix='vulkan-minimum-mutant-') as temp:
            result = execute(mutant, Path(temp), 'extra_image')
            self.assertNotEqual(0, result.returncode)
            self.assertIn(b'primary(caps)==low', result.stderr)


if __name__ == '__main__':
    unittest.main()
