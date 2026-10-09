"""Execute the production submit/present path against delayed Vulkan ownership.

GPU submission completion deliberately does NOT complete presentation. Drivers
may return images out of frame-slot order. This is an API-boundary regression,
not a real-driver validation or performance result.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'unified-android/native'
SOURCE = NATIVE / 'lucent_android_vulkan_backend.c'


def function(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def harness(source):
    structs = source[source.index('#define LUCENT_VK_MAX_IMAGES'):
                     source.index('static void set_error(')]
    helpers = '\n'.join(function(source, signature) for signature in (
        'static void set_error(', 'static bool claim_render_thread(',
        'static void queue_lock(', 'static void queue_unlock('))
    if 'static bool wait_acquire_slot(' in source:
        helpers += function(source, 'static bool wait_acquire_slot(')
    return (NATIVE / 'tests/vulkan_semaphore_reuse_test.c').read_text().replace(
        '/* PRODUCTION_TYPES */', structs).replace(
        '/* PRODUCTION_HELPERS */', helpers).replace(
        '/* PRODUCTION_RUN */', function(source,
            'bool lucent_android_vulkan_run_and_present('))


def execute(source, directory):
    includes = Path(os.environ.get('VULKAN_HEADERS', '/opt/homebrew/include'))
    c = directory / 'probe.c'
    binary = directory / 'probe'
    c.write_text(harness(source))
    result = subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-parameter', '-fsanitize=address,undefined',
        '-I' + str(includes), '-I' + str(NATIVE / 'include'),
        '-I' + str(NATIVE / 'tests/fake-android'), str(c), '-o', str(binary)],
        capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)


class VulkanSemaphoreReuseTest(unittest.TestCase):
    def test_delayed_nonroundrobin_single_and_dual_presentation(self):
        with tempfile.TemporaryDirectory(prefix='vulkan-reuse-') as folder:
            result = execute(SOURCE.read_text(), Path(folder))
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_frame_slot_present_semaphore_mutation_is_rejected(self):
        for owner in ('backend', 'target'):
            with self.subTest(owner=owner):
                source = SOURCE.read_text().replace(
                    owner + '->render_finished[' + owner + '->current_index]',
                    owner + '->render_finished[' + owner + '->frame_slot]')
                with tempfile.TemporaryDirectory(prefix='vulkan-reuse-mutant-') as folder:
                    result = execute(source, Path(folder))
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn('present_reuse_errors == 0', result.stderr)

    def test_acquire_slot_wait_mutation_is_rejected(self):
        source = SOURCE.read_text()
        helper = function(source, 'static bool wait_acquire_slot(')
        mutant = helper[:helper.index('{')] + '{ return true; }'
        with tempfile.TemporaryDirectory(prefix='vulkan-acquire-mutant-') as folder:
            result = execute(source.replace(helper, mutant), Path(folder))
            self.assertNotEqual(0, result.returncode)
            self.assertIn('acquire_reuse_errors == 0', result.stderr)

    def test_destroy_forgets_borrowed_acquire_fences(self):
        source = SOURCE.read_text()
        for name, owner in (('destroy_swapchain', 'backend'),
                            ('destroy_secondary_swapchain', 'target')):
            body = function(source, 'static void ' + name + '(')
            self.assertIn('memset(' + owner + '->acquire_pending, 0,', body)


if __name__ == '__main__':
    unittest.main()
