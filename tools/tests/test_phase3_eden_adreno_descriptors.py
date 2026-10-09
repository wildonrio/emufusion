"""Execute the actual driver-workaround block; no device/crash PASS implied."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TREE = ROOT / 'engines/build/switch-src/eden'
DEVICE = TREE / 'src/video_core/vulkan_common/vulkan_device.cpp'


class AdrenoDescriptorTest(unittest.TestCase):
    def test_exact_driver_policy_executes_and_preserves_other_versions(self):
        source = DEVICE.read_text()
        match = re.search(r'    // EmuFusion: begin observed Adreno push-descriptor workaround\n(.*?)'
                          r'    // EmuFusion: end observed Adreno push-descriptor workaround', source, re.S)
        self.assertIsNotNone(match, 'missing evidence-scoped driver workaround')
        program = r'''
#include <cassert>
#include <cstdint>
#include <set>
#include <string>
#define VK_MAKE_VERSION(a,b,c) ((uint32_t(a)<<22)|(uint32_t(b)<<12)|uint32_t(c))
#define VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME "VK_KHR_push_descriptor"
#define LOG_WARNING(...) ((void)0)
struct Device {
    struct { bool push_descriptor; } extensions;
    struct { struct { uint32_t driverVersion; } properties; } properties;
    std::set<std::string> loaded_extensions;
    void RemoveExtension(bool& flag, const std::string& name) {
        flag=false; loaded_extensions.erase(name);
    }
    void Apply(bool is_qualcomm) {
''' + match.group(1) + r'''
    }
};
int main() {
    for (bool qualcomm : {false,true}) for (bool supported : {false,true}) {
        for (auto version : {VK_MAKE_VERSION(512,676,52), VK_MAKE_VERSION(512,676,53),
                             VK_MAKE_VERSION(512,676,54), VK_MAKE_VERSION(512,677,53)}) {
            Device d; d.extensions.push_descriptor=supported;
            d.properties.properties.driverVersion=version;
            d.loaded_extensions.insert("unrelated_extension");
            if (supported) d.loaded_extensions.insert(VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME);
            d.Apply(qualcomm);
            const bool expected=supported && !(qualcomm && version==VK_MAKE_VERSION(512,676,53));
            assert(d.extensions.push_descriptor==expected);
            assert(d.loaded_extensions.count(VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME)==expected);
            assert(d.loaded_extensions.count("unrelated_extension")==1);
        }
    }
}
'''
        compiler = shutil.which('clang++') or shutil.which('c++')
        self.assertIsNotNone(compiler)
        with tempfile.TemporaryDirectory(prefix='eden-adreno-descriptors-') as folder:
            path = Path(folder)
            (path / 'test.cpp').write_text(program)
            subprocess.run([compiler, '-std=c++17', str(path / 'test.cpp'), '-o', str(path / 'test')], check=True)
            subprocess.run([str(path / 'test')], check=True, timeout=10)

    def test_both_pipeline_types_use_existing_descriptor_set_fallback(self):
        helper = (TREE / 'src/video_core/renderer_vulkan/pipeline_helper.h').read_text()
        can_push = helper.split('bool CanUsePushDescriptor() const noexcept {', 1)[1].split('\n    }', 1)[0]
        self.assertIn('!device->IsKhrPushDescriptorSupported()', can_push)
        for name in ('vk_graphics_pipeline.cpp', 'vk_compute_pipeline.cpp'):
            source = (TREE / 'src/video_core/renderer_vulkan' / name).read_text()
            self.assertIn('uses_push_descriptor = builder.CanUsePushDescriptor()', source)
            self.assertIn('descriptor_allocator.Commit()', source)
            self.assertIn('UpdateDescriptorSet(', source)
            self.assertIn('BindDescriptorSets(', source)


if __name__ == '__main__':
    unittest.main()
