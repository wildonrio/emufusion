"""Compile the shipped cache and guard the frame-pool/descriptor integration."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / 'engines/patches/armsx2-libretro-descriptor-batch.patch'
FEEDBACK = ROOT / 'engines/patches/armsx2-libretro-input-attachment.patch'


def new_file(patch, name):
    section = patch.split('+++ b/pcsx2/GS/Renderers/Vulkan/' + name + '\n', 1)[1]
    return '\n'.join(line[1:] for line in section.splitlines()
                     if line.startswith('+') and not line.startswith('+++')) + '\n'


class Ps2DescriptorBatchTest(unittest.TestCase):
    def test_real_cache_allocation_reset_capacity_and_failures(self):
        clang = shutil.which('clang++')
        self.assertIsNotNone(clang, 'C++ compiler required for the cache regression')
        with tempfile.TemporaryDirectory(prefix='emufusion-ps2-descriptors-') as tmp:
            directory = Path(tmp)
            (directory / 'FrameDescriptorBatchCache.h').write_text(new_file(
                PATCH.read_text(), 'FrameDescriptorBatchCache.h'))
            executable = directory / 'test'
            subprocess.run([clang, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-g', '-I', str(directory),
                str(ROOT / 'unified-android/native/tests/ps2_descriptor_batch_test.cpp'),
                '-o', str(executable)], check=True, capture_output=True)
            subprocess.run([str(executable)], check=True, capture_output=True)

    def test_reset_only_after_success_without_changing_gpu_fence_logic(self):
        patch = PATCH.read_text()
        self.assertIn('+\t\telse\n+\t\t\tresources.descriptor_batches.Reset();', patch)
        self.assertIn('LOG_VULKAN_ERROR(res, "vkResetDescriptorPool failed: ");', patch)
        self.assertNotIn('WaitForCommandBufferCompletion', patch)
        self.assertNotIn('vkResetFences', patch)
        self.assertIn('FrameDescriptorBatchCache descriptor_batches;', patch)
        self.assertNotIn('EMUFUSION_DESCRIPTOR_QA', patch)
        self.assertNotIn('debug.emufusion', patch)
        self.assertNotIn('__android_log_print', patch)

    def test_capacity_matches_existing_pool_contract(self):
        existing = (ROOT / 'engines/patches/armsx2-libretro-android-build.patch').read_text()
        # The bound is present in the pinned upstream source, not changed by this patch.
        header = new_file(PATCH.read_text(), 'FrameDescriptorBatchCache.h')
        self.assertIn('Capacity = 8192;', header)
        self.assertIn('BatchSize = 32;', header)
        self.assertNotIn('MAX_FRAME_TEXTURE_SETS', existing)

    def test_feedback_layout_and_writes_share_one_predicate(self):
        additions = '\n'.join(line[1:] for line in FEEDBACK.read_text().splitlines()
                              if line.startswith('+') and not line.startswith('+++'))
        self.assertEqual(4, additions.count('UseInputAttachmentDescriptors()'))
        self.assertIn('m_features.texture_barrier && !UseFeedbackLoopLayout() && !IsDeviceAdreno()', additions)
        self.assertNotIn('vendorID == 0x13B5', additions)

    def test_feedback_predicate_preserves_qualcomm_and_sampled_paths(self):
        additions = '\n'.join(line[1:] for line in FEEDBACK.read_text().splitlines()
                              if line.startswith('+') and not line.startswith('+++'))
        expression, = re.findall(r'return (.*);', additions)
        # Exercise the exact expression emitted by the production patch.
        expression = expression.replace('m_features.texture_barrier', 'barrier')
        expression = expression.replace('UseFeedbackLoopLayout()', 'feedback')
        expression = expression.replace('IsDeviceAdreno()', 'adreno')
        expression = expression.replace('&&', ' and ').replace('!', ' not ')
        for barrier in (False, True):
            for feedback in (False, True):
                for adreno in (False, True):
                    self.assertEqual(barrier and not feedback and not adreno,
                                     eval(expression, {'__builtins__': {}}, locals()))


if __name__ == '__main__':
    unittest.main()
