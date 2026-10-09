#include <cassert>
#include <cstdint>
#include <set>
#include <vector>
using VkDevice = std::uint64_t;
using VkDescriptorPool = std::uint64_t;
using VkDescriptorSetLayout = std::uint64_t;
using VkDescriptorSet = std::uint64_t;
using VkResult = int;
constexpr std::uint64_t VK_NULL_HANDLE = 0;
constexpr int VK_SUCCESS = 0, VK_ERROR_OUT_OF_POOL_MEMORY = -1,
    VK_ERROR_FRAGMENTED_POOL = -2, VK_ERROR_DEVICE_LOST = -3;
constexpr int VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO = 34;
struct VkDescriptorSetAllocateInfo {
    int sType;
    const void* pNext;
    VkDescriptorPool descriptorPool;
    std::uint32_t descriptorSetCount;
    const VkDescriptorSetLayout* pSetLayouts;
};
#include "FrameDescriptorBatchCache.h"

int main() {
    FrameDescriptorBatchCache cache;
    std::uint64_t next = 1;
    unsigned calls = 0;
    std::vector<VkDescriptorSetLayout> layout_by_handle{0};
    auto allocate = [&](VkDevice device, const VkDescriptorSetAllocateInfo* info, VkDescriptorSet* output) {
        assert(device == 9 && info->descriptorPool == 7 && !info->pNext);
        calls++;
        for (unsigned i = 0; i < info->descriptorSetCount; i++) {
            assert(info->pSetLayouts[i] == info->pSetLayouts[0]);
            output[i] = next++;
            layout_by_handle.push_back(info->pSetLayouts[i]);
        }
        return VK_SUCCESS;
    };
    std::set<VkDescriptorSet> used;
    for (unsigned i = 0; i < 96; i++) {
        auto set = cache.AllocateSet(9, 7, 10 + i % 3, allocate);
        assert(set && used.insert(set).second);
        assert(layout_by_handle.at(set) == 10 + i % 3);
    }
    assert(calls == 3 && used.size() == 96);
    // An extra layout must not return any set belonging to the three cached layouts.
    assert(used.insert(cache.AllocateSet(9, 7, 99, allocate)).second && calls == 4);
    cache.Reset();
    assert(used.insert(cache.AllocateSet(9, 7, 10, allocate)).second && calls == 5);
    assert(cache.GetStatistics().requests == 98);

    FrameDescriptorBatchCache full;
    unsigned start_calls = calls;
    for (unsigned i = 0; i < full.Capacity; i++)
        assert(full.AllocateSet(9, 7, 10, allocate) != VK_NULL_HANDLE);
    assert(calls - start_calls == full.Capacity / full.BatchSize);
    assert(full.AllocateSet(9, 7, 10, allocate) == VK_NULL_HANDLE);
    assert(calls - start_calls == full.Capacity / full.BatchSize);
    full.Reset();
    assert(full.AllocateSet(9, 7, 10, allocate) != VK_NULL_HANDLE);

    // At capacity, cached sets in another layout are still valid and consumable.
    FrameDescriptorBatchCache mixed;
    used.clear();
    assert(used.insert(mixed.AllocateSet(9, 7, 10, allocate)).second);
    for (unsigned i = 0; i < mixed.Capacity - mixed.BatchSize; i++)
        assert(used.insert(mixed.AllocateSet(9, 7, 11, allocate)).second);
    const auto before_cached = calls;
    for (unsigned i = 1; i < mixed.BatchSize; i++)
        assert(used.insert(mixed.AllocateSet(9, 7, 10, allocate)).second);
    assert(calls == before_cached && used.size() == mixed.Capacity);
    assert(mixed.AllocateSet(9, 7, 10, allocate) == VK_NULL_HANDLE);

    // Batch exhaustion falls back to one; poisoned outputs from failed calls
    // never enter the cache. Device loss is not retried or hidden.
    FrameDescriptorBatchCache failing;
    unsigned fail_calls = 0;
    auto fail_then_one = [&](VkDevice, const VkDescriptorSetAllocateInfo* info, VkDescriptorSet* output) {
        fail_calls++;
        for (unsigned i = 0; i < info->descriptorSetCount; i++) output[i] = 9999;
        if (info->descriptorSetCount > 1) return VK_ERROR_OUT_OF_POOL_MEMORY;
        output[0] = 123;
        return VK_SUCCESS;
    };
    assert(failing.AllocateSet(9, 7, 10, fail_then_one) == 123 && fail_calls == 2);
    auto lost = [&](VkDevice, const VkDescriptorSetAllocateInfo* info, VkDescriptorSet* output) {
        fail_calls++;
        for (unsigned i = 0; i < info->descriptorSetCount; i++) output[i] = 9999;
        return VK_ERROR_DEVICE_LOST;
    };
    assert(failing.AllocateSet(9, 7, 10, lost) == VK_NULL_HANDLE && fail_calls == 3);
    assert(failing.AllocateSet(9, 7, 10, allocate) != 9999);
    FrameDescriptorBatchCache baseline;
    start_calls = calls;
    for (unsigned i = 0; i < 100; i++) assert(baseline.AllocateSet(9, 7, 10, allocate, 1));
    assert(calls - start_calls == 100);

    // A nearly-full pool must reduce the requested batch rather than allocate
    // past maxSets. Cached handles for other layouts remain consumable at capacity.
    FrameDescriptorBatchCache edge;
    for (unsigned i = 0; i < edge.Capacity - 1; i++)
        assert(edge.AllocateSet(9, 7, 10, allocate, 1));
    assert(edge.AllocateSet(9, 7, 11, allocate, 32));
    assert(edge.GetStatistics().allocated == edge.Capacity);
    assert(edge.AllocateSet(9, 7, 11, allocate, 32) == VK_NULL_HANDLE);

    FrameDescriptorBatchCache poison;
    unsigned poison_calls = 0;
    auto always_fragmented = [&](VkDevice, const VkDescriptorSetAllocateInfo* info, VkDescriptorSet* output) {
        poison_calls++;
        for (unsigned i = 0; i < info->descriptorSetCount; i++) output[i] = 9999;
        return VK_ERROR_FRAGMENTED_POOL;
    };
    assert(poison.AllocateSet(9, 7, 10, always_fragmented) == VK_NULL_HANDLE);
    assert(poison_calls == 2 && poison.GetStatistics().allocated == 0);
    assert(poison.AllocateSet(9, 7, 10, allocate) != 9999);
}
