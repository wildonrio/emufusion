// Android GPU test for the exact extracted Dolphin allocation/reset methods.
// No app data, identifiers, ROMs, network, or display surface is accessed.
#include <vulkan/vulkan.h>
#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "descriptor_shader0.h"
#include "descriptor_shader1.h"

using u32 = uint32_t;
static void check(VkResult result) {
  if (result != VK_SUCCESS) { std::fprintf(stderr, "Vulkan error %d\n", result); std::exit(2); }
}
static u32 allocation_calls;
static VkResult last_allocation_result=VK_SUCCESS;
static VkResult tracked_allocate(VkDevice device, const VkDescriptorSetAllocateInfo* info,
                                 VkDescriptorSet* sets) {
  ++allocation_calls;
  auto result=vkAllocateDescriptorSets(device, info, sets);
  last_allocation_result=result;
  if (result!=VK_SUCCESS || allocation_calls%1024==0)
    std::fprintf(stderr,"phase=allocation call=%u count=%u result=%d\n",
                 allocation_calls,info->descriptorSetCount,result);
  return result;
}
struct Context { VkDevice device; VkDevice GetDevice() { return device; } } context;
static auto* g_vulkan_context = &context;
#include "descriptor_constants.h"
#define LOG_VULKAN_ERROR(result, ...) check(result)
#define vkAllocateDescriptorSets tracked_allocate
#include "descriptor_methods.h"
#undef vkAllocateDescriptorSets

static u32 SETS=1057, ROUNDS=6;
constexpr u32 SLOTS=3;
struct Gpu {
  VkInstance instance{};
  VkPhysicalDevice physical{};
  VkDevice device{};
  VkQueue queue{};
  u32 family{};
  VkDescriptorSetLayout layouts[2]{};
  VkPipelineLayout pipeline_layouts[2]{};
  VkPipeline pipelines[2]{};
  VkShaderModule shaders[2]{};
  VkCommandPool commands{};
  VkCommandBuffer cmd[SLOTS]{};
  VkFence fences[SLOTS]{};
  VkBuffer buffer{};
  VkDeviceMemory memory{};
  unsigned char* mapped{};
  VkDeviceSize stride{};

  Gpu() {
    std::fprintf(stderr,"phase=instance\n");
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.pApplicationName="EmuFusion descriptor correctness probe";
    app.apiVersion=VK_API_VERSION_1_1;
    VkInstanceCreateInfo instance_info{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    instance_info.pApplicationInfo=&app;
    check(vkCreateInstance(&instance_info,nullptr,&instance));
    u32 count=0; check(vkEnumeratePhysicalDevices(instance,&count,nullptr)); assert(count);
    std::vector<VkPhysicalDevice> devices(count);
    check(vkEnumeratePhysicalDevices(instance,&count,devices.data())); physical=devices[0];
    vkGetPhysicalDeviceQueueFamilyProperties(physical,&count,nullptr);
    std::vector<VkQueueFamilyProperties> families(count);
    vkGetPhysicalDeviceQueueFamilyProperties(physical,&count,families.data());
    for (family=0;family<count;++family) if (families[family].queueFlags&VK_QUEUE_COMPUTE_BIT) break;
    assert(family<count);
    float priority=1;
    VkDeviceQueueCreateInfo queue_info{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    queue_info.queueFamilyIndex=family; queue_info.queueCount=1; queue_info.pQueuePriorities=&priority;
    VkDeviceCreateInfo device_info{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    device_info.queueCreateInfoCount=1; device_info.pQueueCreateInfos=&queue_info;
    check(vkCreateDevice(physical,&device_info,nullptr,&device));
    context.device=device; vkGetDeviceQueue(device,family,0,&queue);
    std::fprintf(stderr,"phase=pipelines\n");
    for (u32 i=0;i<2;++i) {
      VkDescriptorSetLayoutBinding binding{i,VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,nullptr};
      VkDescriptorSetLayoutCreateInfo layout_info{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
      layout_info.bindingCount=1; layout_info.pBindings=&binding;
      check(vkCreateDescriptorSetLayout(device,&layout_info,nullptr,&layouts[i]));
      VkPushConstantRange push{VK_SHADER_STAGE_COMPUTE_BIT,0,4};
      VkPipelineLayoutCreateInfo pipeline_info{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
      pipeline_info.setLayoutCount=1; pipeline_info.pSetLayouts=&layouts[i];
      pipeline_info.pushConstantRangeCount=1; pipeline_info.pPushConstantRanges=&push;
      check(vkCreatePipelineLayout(device,&pipeline_info,nullptr,&pipeline_layouts[i]));
      VkShaderModuleCreateInfo shader_info{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
      shader_info.codeSize=i?sizeof(shader1):sizeof(shader0); shader_info.pCode=i?shader1:shader0;
      check(vkCreateShaderModule(device,&shader_info,nullptr,&shaders[i]));
      VkComputePipelineCreateInfo compute{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
      compute.stage.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
      compute.stage.stage=VK_SHADER_STAGE_COMPUTE_BIT; compute.stage.module=shaders[i];
      compute.stage.pName="main"; compute.layout=pipeline_layouts[i];
      check(vkCreateComputePipelines(device,VK_NULL_HANDLE,1,&compute,nullptr,&pipelines[i]));
    }
    VkCommandPoolCreateInfo pool{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    pool.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT; pool.queueFamilyIndex=family;
    check(vkCreateCommandPool(device,&pool,nullptr,&commands));
    VkCommandBufferAllocateInfo alloc{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    alloc.commandPool=commands; alloc.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY; alloc.commandBufferCount=SLOTS;
    check(vkAllocateCommandBuffers(device,&alloc,cmd));
    VkFenceCreateInfo fence{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    for (auto& f:fences) check(vkCreateFence(device,&fence,nullptr,&f));
    VkPhysicalDeviceProperties properties{}; vkGetPhysicalDeviceProperties(physical,&properties);
    stride=std::max(VkDeviceSize(4),properties.limits.minStorageBufferOffsetAlignment);
    VkBufferCreateInfo buffer_info{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    buffer_info.size=stride*SETS*SLOTS; buffer_info.usage=VK_BUFFER_USAGE_STORAGE_BUFFER_BIT;
    buffer_info.sharingMode=VK_SHARING_MODE_EXCLUSIVE;
    check(vkCreateBuffer(device,&buffer_info,nullptr,&buffer));
    VkMemoryRequirements requirements{}; vkGetBufferMemoryRequirements(device,buffer,&requirements);
    VkPhysicalDeviceMemoryProperties memories{}; vkGetPhysicalDeviceMemoryProperties(physical,&memories);
    u32 memory_type=0;
    constexpr auto flags=VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    for (;memory_type<memories.memoryTypeCount;++memory_type)
      if ((requirements.memoryTypeBits&(1u<<memory_type)) &&
          (memories.memoryTypes[memory_type].propertyFlags&flags)==flags) break;
    assert(memory_type<memories.memoryTypeCount);
    VkMemoryAllocateInfo memory_info{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    memory_info.allocationSize=requirements.size; memory_info.memoryTypeIndex=memory_type;
    check(vkAllocateMemory(device,&memory_info,nullptr,&memory));
    check(vkBindBufferMemory(device,buffer,memory,0));
    check(vkMapMemory(device,memory,0,VK_WHOLE_SIZE,0,reinterpret_cast<void**>(&mapped)));
    std::fprintf(stderr,"phase=initialized\n");
  }

  ~Gpu() {
    check(vkDeviceWaitIdle(device)); vkUnmapMemory(device,memory);
    vkDestroyBuffer(device,buffer,nullptr); vkFreeMemory(device,memory,nullptr);
    for (auto fence:fences) vkDestroyFence(device,fence,nullptr);
    vkDestroyCommandPool(device,commands,nullptr);
    for (u32 i=0;i<2;++i) {
      vkDestroyPipeline(device,pipelines[i],nullptr); vkDestroyShaderModule(device,shaders[i],nullptr);
      vkDestroyPipelineLayout(device,pipeline_layouts[i],nullptr);
      vkDestroyDescriptorSetLayout(device,layouts[i],nullptr);
    }
    vkDestroyDevice(device,nullptr); vkDestroyInstance(instance,nullptr);
  }

  static u32 expected(u32 round,u32 index) { return 0x12340000u + round*SETS + index; }
  void verify(u32 slot,u32 round) {
    check(vkWaitForFences(device,1,&fences[slot],VK_TRUE,20000000000ULL));
    for (u32 i=0;i<SETS;++i) {
      u32 actual; std::memcpy(&actual,mapped+(slot*SETS+i)*stride,4);
      if (actual!=expected(round,i)) {
        std::fprintf(stderr,"Mismatch slot=%u round=%u index=%u got=%u expected=%u\n",
                     slot,round,i,actual,expected(round,i)); std::exit(3);
      }
    }
  }

  template<class Manager> u32 run(const char* mode) {
    Manager manager; allocation_calls=0;
    auto start=std::chrono::steady_clock::now();
    for (u32 round=0;round<ROUNDS;++round) {
      std::fprintf(stderr,"mode=%s round=%u phase=begin\n",mode,round);
      u32 slot=round%SLOTS; manager.m_current_frame=slot;
      if (round>=SLOTS) {
        verify(slot,round-SLOTS);
        // Reset only AFTER this frame's submitted descriptor consumers finish.
        manager.ResetDescriptorPools();
      }
      check(vkResetFences(device,1,&fences[slot]));
      check(vkResetCommandBuffer(cmd[slot],0));
      VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
      check(vkBeginCommandBuffer(cmd[slot],&begin));
      for (u32 i=0;i<SETS;++i) {
        u32 layout=i%2;
        last_allocation_result=VK_SUCCESS;
        auto set=manager.AllocateDescriptorSet(layouts[layout]); assert(set!=VK_NULL_HANDLE);
        if (last_allocation_result!=VK_SUCCESS) {
          std::fprintf(stderr,"FAIL: allocator accepted failed output handle result=%d index=%u\n",
                       last_allocation_result,i);
          std::exit(4); // Never submit invalid descriptors during a negative control.
        }
        auto offset=(slot*SETS+i)*stride;
        std::memset(mapped+offset,0,4);
        VkDescriptorBufferInfo data{buffer,offset,4};
        VkWriteDescriptorSet write{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
        write.dstSet=set; write.dstBinding=layout; write.descriptorCount=1;
        write.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER; write.pBufferInfo=&data;
        vkUpdateDescriptorSets(device,1,&write,0,nullptr);
        vkCmdBindPipeline(cmd[slot],VK_PIPELINE_BIND_POINT_COMPUTE,pipelines[layout]);
        vkCmdBindDescriptorSets(cmd[slot],VK_PIPELINE_BIND_POINT_COMPUTE,
                               pipeline_layouts[layout],0,1,&set,0,nullptr);
        u32 value=expected(round,i);
        vkCmdPushConstants(cmd[slot],pipeline_layouts[layout],VK_SHADER_STAGE_COMPUTE_BIT,0,4,&value);
        vkCmdDispatch(cmd[slot],1,1,1);
      }
      VkMemoryBarrier barrier{VK_STRUCTURE_TYPE_MEMORY_BARRIER};
      barrier.srcAccessMask=VK_ACCESS_SHADER_WRITE_BIT; barrier.dstAccessMask=VK_ACCESS_HOST_READ_BIT;
      vkCmdPipelineBarrier(cmd[slot],VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,VK_PIPELINE_STAGE_HOST_BIT,
                           0,1,&barrier,0,nullptr,0,nullptr);
      check(vkEndCommandBuffer(cmd[slot]));
      std::fprintf(stderr,"mode=%s round=%u phase=recorded\n",mode,round);
      VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO}; submit.commandBufferCount=1;
      submit.pCommandBuffers=&cmd[slot]; check(vkQueueSubmit(queue,1,&submit,fences[slot]));
    }
    for (u32 round=ROUNDS-SLOTS;round<ROUNDS;++round) verify(round%SLOTS,round);
    check(vkDeviceWaitIdle(device));
    for (auto& resources:manager.m_frame_resources)
      for (auto pool:resources.descriptor_pools) vkDestroyDescriptorPool(device,pool,nullptr);
    auto elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::printf("{\"mode\":\"%s\",\"valuesVerified\":%u,\"allocationCalls\":%u,\"seconds\":%.6f}\n",
                mode,SETS*ROUNDS,allocation_calls,elapsed); std::fflush(stdout);
    return allocation_calls;
  }
};
int main(int argc,char** argv) {
  if (argc>=3) { SETS=std::strtoul(argv[1],nullptr,10); ROUNDS=std::strtoul(argv[2],nullptr,10); }
  assert(SETS>=1 && SETS<=5000 && ROUNDS>=SLOTS && ROUNDS<=24);
  Gpu gpu;
  if (argc>=4 && std::strcmp(argv[3],"fixed")==0)
    gpu.run<fixed::CommandBufferManager>("fixed");
  else if (argc>=4 && std::strcmp(argv[3],"baseline")==0)
    gpu.run<baseline::CommandBufferManager>("baseline");
  else if (argc>=4 && std::strcmp(argv[3],"batch")==0)
    gpu.run<candidate::CommandBufferManager>("batch");
  else if (argc>=4 && std::strcmp(argv[3],"compare")==0) {
    // Both paths require VK_SUCCESS. The known-broken original is a separate
    // negative control and must not prevent the batch overflow test from running.
    auto corrected=gpu.run<fixed::CommandBufferManager>("fixed");
    auto batch=gpu.run<candidate::CommandBufferManager>("batch");
    if (SETS>=32) assert(batch<corrected/10);
  }
  else {
    auto original=gpu.run<baseline::CommandBufferManager>("baseline");
    auto batch=gpu.run<candidate::CommandBufferManager>("batch");
    if (SETS>=32) assert(batch<original/10);
  }
  std::puts("PASS: descriptor values and fence-delayed pool reuse match on actual GPU");
}
