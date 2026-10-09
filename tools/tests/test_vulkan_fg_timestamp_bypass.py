"""Execute the actual Vulkan FG timestamp branch; no GPU correctness claim."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class VulkanFgTimestampBypassTest(unittest.TestCase):
    def test_actual_configuration_and_present_branch(self):
        source = (ROOT / 'unified-android/native/lucent_android_vulkan_backend.c').read_text()
        configure = source[source.index('bool lucent_android_vulkan_set_fg_timestamp('):
                           source.index('bool lucent_android_vulkan_set_presentation_aspect(')]
        start = source.index('    const bool tag_primary =')
        block = source[start:source.index('    queue_lock(backend);', start)]
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define VK_STRUCTURE_TYPE_PRESENT_TIMES_INFO_GOOGLE 1
#define __android_log_print(...) ((void)0)
typedef struct {
 bool fg_timestamp_enabled[2], timestamp_timeline_ready, display_timing_logged;
 bool display_timing_enabled;
 int64_t timestamp_last_ns;
 uint64_t timestamp_sequence;
} lucent_android_vulkan_backend;
typedef struct { uint32_t presentID; uint64_t desiredPresentTime; } Time;
typedef struct { int sType; const void* pNext; uint32_t swapchainCount; const Time* pTimes; } Times;
static unsigned clock_calls;
static void set_error(char* buffer, size_t size, const char* message) {
 if (buffer && size) buffer[0] = message[0];
}
static bool stamp_core_frame_timestamp(lucent_android_vulkan_backend* backend,
 uint64_t sequence, int64_t* stamp) {
 ++clock_calls; backend->timestamp_sequence=sequence; *stamp=123456789;
 return true;
}
''' + configure + r'''
static void present_frame(lucent_android_vulkan_backend* backend, bool has_secondary) {
 int sentinel=7;
 struct { const void* pNext; } present={&sentinel};
 struct { uint64_t frame_sequence; } hw_info={42};
 Times present_times;
 Time present_time[2];
 uint32_t present_count=has_secondary?2:1;
 unsigned before=clock_calls;
''' + block + r'''
 bool tagged = backend->display_timing_enabled &&
  (backend->fg_timestamp_enabled[0] || (has_secondary && backend->fg_timestamp_enabled[1]));
 assert(clock_calls-before == (unsigned)tagged);
 if (!tagged) { assert(present.pNext==&sentinel); return; }
 assert(present.pNext==&present_times && present_times.pNext==&sentinel);
 assert(present_times.swapchainCount==present_count);
 for (unsigned i=0;i<present_count;++i) {
  assert(present_time[i].desiredPresentTime==(backend->fg_timestamp_enabled[i]?123456789u:0u));
  assert(present_time[i].presentID==(backend->fg_timestamp_enabled[i]?42u:0u));
 }
}
int main(void) {
 lucent_android_vulkan_backend b={0};
 b.display_timing_enabled=true;
 for (unsigned i=0;i<10000;++i) present_frame(&b,true);
 assert(clock_calls==0);
 for (unsigned mask=0;mask<16;++mask) {
  b.display_timing_enabled=(mask&1)!=0;
  assert(lucent_android_vulkan_set_fg_timestamp(&b,false,(mask&2)!=0,0,0));
  assert(lucent_android_vulkan_set_fg_timestamp(&b,true,(mask&4)!=0,0,0));
  present_frame(&b,(mask&8)!=0);
 }
 // Even a same-mode surface rebind must not inherit the previous timeline.
 b.timestamp_timeline_ready=true; b.timestamp_last_ns=77; b.display_timing_logged=true;
 assert(lucent_android_vulkan_set_fg_timestamp(&b,false,true,0,0));
 assert(!b.timestamp_timeline_ready && b.timestamp_last_ns==0 && !b.display_timing_logged);
 assert(lucent_android_vulkan_set_fg_timestamp(&b,false,false,0,0));
 assert(lucent_android_vulkan_set_fg_timestamp(&b,true,false,0,0));
 present_frame(&b,true);
 assert(!lucent_android_vulkan_set_fg_timestamp(0,false,true,0,0));
}
'''
        with tempfile.TemporaryDirectory(prefix='vulkan-fg-bypass-') as temp:
            path = Path(temp)
            (path / 'test.c').write_text(harness)
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', str(path / 'test.c'),
                            '-o', str(path / 'test')], check=True)
            subprocess.run([str(path / 'test')], check=True, timeout=15)

    def test_java_configures_actual_surface_before_native_attach(self):
        source = (ROOT / 'unified-android/src/com/thorium/preview/ExperimentalVulkanLibretroHost.java').read_text()
        for name, native, secondary in [
            ('attachSurface', 'nativeAttachSurfaceVulkan', 'false'),
            ('recreateSurface', 'nativeRecreateSurfaceVulkan', 'false'),
            ('attachSecondarySurface', 'nativeAttachSecondarySurfaceVulkan', 'true')]:
            body = source.split('void ' + name + '(Surface surface) {', 1)[1].split('\n    }', 1)[0]
            self.assertLess(body.index('configureFgTimestamp(surface, ' + secondary + ')'),
                            body.index(native + '(handle, surface)'))
        self.assertIn('FrameGenerationRendererRegistry.isFrameGenerationInput(surface)', source)
        self.assertIn('configureFgTimestamp(null, false)', source)
        self.assertIn('configureFgTimestamp(null, true)', source)


if __name__ == '__main__':
    unittest.main()
