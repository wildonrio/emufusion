"""Execute patched Dolphin allocation/reset methods against a recording Vulkan driver.

This is allocation/lifetime logic coverage, not an actual GPU synchronization test.
The actual Android core build separately compiles the full integration.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'engines/build/sources/dolphin-0ff12a5a2835762e0665afe6a161a648b433f996'
PATCH = ROOT / 'docs/qa/android-portability-2026-10-04-dolphin-descriptors/descriptor-batches.patch'
# Use the normal build's pinned dependency cache, not a disposable QA clone.
HEADERS = ROOT / 'engines/build/sources/Externals-Vulkan-Headers-39f924b810e561fd86b2558b6711ca68d4363f68/include'
REL = Path('Source/Core/VideoBackends/Vulkan')


def pool_constants():
    """Use the pinned core's real descriptor-pool geometry, not fixture guesses."""
    common = (SOURCE / 'Source/Core/VideoCommon/Constants.h').read_text()
    vulkan = (SOURCE / REL / 'Constants.h').read_text()
    def declaration(text, name):
        matches = re.findall(r'constexpr u32 ' + name + r' = \d+;', text)
        assert len(matches) == 1, name
        return matches[0]
    return ('namespace VideoCommon { ' +
            declaration(common, 'MAX_PIXEL_SHADER_SAMPLERS') + ' ' +
            declaration(common, 'MAX_COMPUTE_SHADER_SAMPLERS') + ' }\n' +
            declaration(vulkan, 'NUM_UTILITY_PIXEL_SAMPLERS') + '\n')


def block(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def harness(cpp, header):
    structures = '\n'.join(block(header, 'struct ' + name) + ';' for name in
                           ('DescriptorSetBatch', 'FrameResources'))
    functions = '\n'.join(block(cpp, signature) for signature in (
        'VkDescriptorPool CommandBufferManager::CreateDescriptorPool(',
        'VkDescriptorSet CommandBufferManager::AllocateDescriptorSet(',
        'void CommandBufferManager::ResetDescriptorPools('))
    return r'''
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <deque>
#include <map>
#include <set>
#include <vector>
using u32 = uint32_t;
template<class T> T handle(uintptr_t n) { return reinterpret_cast<T>(n); }
struct Context { VkDevice GetDevice() { return handle<VkDevice>(1); } } context;
static auto* g_vulkan_context = &context;
''' + pool_constants() + r'''
static int errors, creates, resets, destroys;
#define LOG_VULKAN_ERROR(...) (++errors)
struct Pool { u32 remaining; };
struct Allocation { VkDescriptorPool pool; u32 count; VkDescriptorSetLayout layout; };
static std::map<VkDescriptorPool, Pool> pools;
static std::map<VkDescriptorSet, VkDescriptorSetLayout> sets;
static std::vector<Allocation> calls;
static std::deque<VkResult> injected;
static bool fail_create, pending_gpu;
static uintptr_t next_pool=100, next_set=10000;
static VkResult vkCreateDescriptorPool(VkDevice, const VkDescriptorPoolCreateInfo* info,
                                      const VkAllocationCallbacks*, VkDescriptorPool* pool) {
  ++creates;
  if (fail_create) return VK_ERROR_OUT_OF_DEVICE_MEMORY;
  *pool=handle<VkDescriptorPool>(next_pool++);
  pools[*pool]={info->maxSets};
  assert(info->flags == 0 && info->poolSizeCount == 5);
  return VK_SUCCESS;
}
static VkResult vkAllocateDescriptorSets(VkDevice, const VkDescriptorSetAllocateInfo* info,
                                        VkDescriptorSet* out) {
  assert(pools.contains(info->descriptorPool));
  assert(info->descriptorSetCount == 1 || info->descriptorSetCount == 32);
  calls.push_back({info->descriptorPool, info->descriptorSetCount, info->pSetLayouts[0]});
  for (u32 i=0;i<info->descriptorSetCount;i++) {
    assert(info->pSetLayouts[i] == info->pSetLayouts[0]);
    out[i]=VK_NULL_HANDLE;
  }
  VkResult result=VK_SUCCESS;
  if (!injected.empty()) { result=injected.front(); injected.pop_front(); }
  if (result != VK_SUCCESS) {
    // Drivers may overwrite output even on failure; these handles are invalid.
    for (u32 i=0;i<info->descriptorSetCount;i++) out[i]=handle<VkDescriptorSet>(999999);
    return result;
  }
  auto& pool=pools.at(info->descriptorPool);
  if (pool.remaining < info->descriptorSetCount) return VK_ERROR_OUT_OF_POOL_MEMORY;
  pool.remaining -= info->descriptorSetCount;
  for (u32 i=0;i<info->descriptorSetCount;i++) {
    out[i]=handle<VkDescriptorSet>(next_set++);
    sets[out[i]]=info->pSetLayouts[i];
  }
  return VK_SUCCESS;
}
static VkResult vkResetDescriptorPool(VkDevice, VkDescriptorPool pool, VkDescriptorPoolResetFlags flags) {
  assert(!pending_gpu && flags == 0);
  ++resets; pools.at(pool).remaining=1024;
  return VK_SUCCESS;
}
static void vkDestroyDescriptorPool(VkDevice, VkDescriptorPool pool, const VkAllocationCallbacks*) {
  assert(!pending_gpu && pools.erase(pool) == 1); ++destroys;
}
class CommandBufferManager {
public:
  const u32 DESCRIPTOR_SETS_PER_POOL=1024;
''' + structures + r'''
  std::array<FrameResources,3> m_frame_resources;
  u32 m_current_frame=0;
  u32 m_descriptor_set_count=1024;
  FrameResources& GetCurrentFrameResources() { return m_frame_resources[m_current_frame]; }
  VkDescriptorPool CreateDescriptorPool(u32);
  VkDescriptorSet AllocateDescriptorSet(VkDescriptorSetLayout);
  void ResetDescriptorPools();
};
''' + functions + r'''
static void fresh_driver() {
  errors=creates=resets=destroys=0;
  pools.clear(); sets.clear(); calls.clear(); injected.clear();
  fail_create=pending_gpu=false;
}
int main() {
  const auto a=handle<VkDescriptorSetLayout>(2), b=handle<VkDescriptorSetLayout>(3);
  {
    fresh_driver(); CommandBufferManager m; std::set<VkDescriptorSet> issued;
    for (int i=0;i<32;i++) {
      auto s=m.AllocateDescriptorSet(a); assert(s && sets.at(s)==a && issued.insert(s).second);
    }
    assert(calls.size()==1 && creates==1); // 32 logical allocations, one driver call.
    auto other=m.AllocateDescriptorSet(b); assert(sets.at(other)==b && calls.size()==2);
    auto next=m.AllocateDescriptorSet(a); assert(sets.at(next)==a && calls.size()==3);
    m.m_current_frame=1;
    auto frame1=m.AllocateDescriptorSet(a);
    assert(frame1 != next && calls.size()==4 && creates==2);
    m.m_current_frame=0;
    auto cached=m.AllocateDescriptorSet(a); assert(calls.size()==4 && cached != next);
    m.ResetDescriptorPools(); assert(resets==1 && m.GetCurrentFrameResources().descriptor_set_batches.empty());
    auto renewed=m.AllocateDescriptorSet(a); assert(renewed != cached && calls.size()==5);
    m.m_current_frame=1; m.AllocateDescriptorSet(a); assert(calls.size()==5); // Other frame survives.
  }
  {
    fresh_driver(); CommandBufferManager m;
    auto pool=m.CreateDescriptorPool(3);
    m.GetCurrentFrameResources().descriptor_pools.push_back(pool);
    for (int i=0;i<3;i++) assert(m.AllocateDescriptorSet(a));
    assert(calls.size()==6 && creates==1); // Each failed 32-batch falls back to one.
    assert(m.AllocateDescriptorSet(a));
    assert(calls.size()==9 && creates==2); // Full pool, then exactly one new pool.
    assert(m.GetCurrentFrameResources().descriptor_pools.size()==2);
    m.ResetDescriptorPools();
    assert(destroys==2 && creates==3);
    assert(m.GetCurrentFrameResources().descriptor_pools.size()==1);
    assert(m.GetCurrentFrameResources().current_descriptor_pool_index==0);
    assert(m.GetCurrentFrameResources().descriptor_set_batches.empty());
    assert(m.AllocateDescriptorSet(b));
  }
  for (auto error : {VK_ERROR_OUT_OF_HOST_MEMORY, VK_ERROR_OUT_OF_DEVICE_MEMORY,
                     VK_ERROR_UNKNOWN}) {
    fresh_driver(); CommandBufferManager m;
    injected.push_back(error);
    assert(m.AllocateDescriptorSet(a)==VK_NULL_HANDLE);
    assert(calls.size()==1 && creates==1 && errors==1); // No recursive pool growth.
    assert(m.AllocateDescriptorSet(a)); // Subsequent valid allocation is not a poisoned cache.
  }
  for (auto error : {VK_ERROR_OUT_OF_POOL_MEMORY, VK_ERROR_FRAGMENTED_POOL}) {
    fresh_driver(); CommandBufferManager m;
    injected={error, VK_SUCCESS};
    assert(m.AllocateDescriptorSet(a));
    assert(calls.size()==2 && calls[0].count==32 && calls[1].count==1 && creates==1);
    fresh_driver(); CommandBufferManager n;
    injected={error, error};
    assert(n.AllocateDescriptorSet(a)==VK_NULL_HANDLE);
    assert(calls.size()==2 && creates==1); // Even a fresh unusable pool cannot recurse forever.
  }
  {
    fresh_driver(); CommandBufferManager m; fail_create=true;
    assert(m.AllocateDescriptorSet(a)==VK_NULL_HANDLE);
    assert(calls.empty() && creates==1 && m.m_descriptor_set_count==1024);
  }
  {
    fresh_driver(); CommandBufferManager m;
    auto& r=m.GetCurrentFrameResources();
    r.descriptor_pools={m.CreateDescriptorPool(0),m.CreateDescriptorPool(32)};
    assert(m.AllocateDescriptorSet(a));
    assert(creates==2 && calls.size()==3 && r.current_descriptor_pool_index==1);
  }
}
'''


class DolphinDescriptorBatchesTest(unittest.TestCase):
    def test_pool_geometry_matches_pinned_core(self):
        constants = pool_constants()
        self.assertIn('MAX_PIXEL_SHADER_SAMPLERS = 16;', constants)
        self.assertIn('MAX_COMPUTE_SHADER_SAMPLERS = 8;', constants)
        self.assertIn('NUM_UTILITY_PIXEL_SAMPLERS = 8;', constants)

    def test_actual_methods_and_frame_reset_integration(self):
        # Uncommitted, build-Mac-only input (see tools/run_ci_tests.py).
        for needed in (HEADERS, SOURCE, PATCH):
            if not needed.exists():
                self.skipTest("local-only input absent: " + str(needed))
        self.assertTrue(HEADERS.is_dir())
        with tempfile.TemporaryDirectory(prefix='dolphin-descriptor-batch-') as directory:
            directory = Path(directory)
            for name in ('CommandBufferManager.cpp', 'CommandBufferManager.h'):
                target = directory / REL / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((SOURCE / REL / name).read_bytes())
            subprocess.run(['patch', '-p1', '--batch', '-i', str(PATCH)], cwd=directory,
                           check=True, capture_output=True)
            cpp = (directory / REL / 'CommandBufferManager.cpp').read_text()
            header = (directory / REL / 'CommandBufferManager.h').read_text()
            submit = block(cpp, 'void CommandBufferManager::SubmitCommandBuffer(bool ')
            advance = block(submit, 'if (advance_to_next_frame)')
            self.assertGreater(advance.index('ResetDescriptorPools();'),
                               advance.index('WaitForCommandBufferCompletion(cmd_buffer_index);'))
            self.assertEqual(cpp.count('ResetDescriptorPools();'), 1)
            test = directory / 'test.cpp'
            test.write_text(harness(cpp, header))
            binary = directory / 'test'
            result = subprocess.run(['clang++', '-std=c++20', '-Wall', '-Wextra',
                                     '-fsanitize=address,undefined', '-I', str(HEADERS),
                                     str(test), '-o', str(binary)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            run = subprocess.run([str(binary)], capture_output=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr.decode())


if __name__ == '__main__':
    unittest.main()
