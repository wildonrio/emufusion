/* Recording Vulkan boundary for test_vulkan_semaphore_reuse.py. */
#include "lucent_android_vulkan_backend.h"
#include "lucent_libretro_vulkan.h"
#include <assert.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <android/log.h>
#define H(type, value) ((type)(uintptr_t)(value))
#define ID(handle) ((unsigned)(uintptr_t)(handle))
/* PRODUCTION_TYPES */
/* PRODUCTION_HELPERS */

static unsigned acquire_calls[2], acquire_image[256], acquire_target[256];
static VkFence acquire_busy[256];
static bool acquire_ready[256], present_busy[256];
static unsigned presented_sem[2][8];
static int acquire_reuse_errors, present_reuse_errors, core_calls, submit_calls;
static bool fence_ready[256], fail_wait, fail_submit;
static VkResult present_result;
static unsigned order[2][8] = {{0,1,2,2,1,0,2,0}, {2,0,1,1,2,0,1,0}};

VkResult vkAcquireNextImageKHR(VkDevice d, VkSwapchainKHR swapchain, uint64_t timeout,
        VkSemaphore semaphore, VkFence fence, uint32_t *index) {
    unsigned t = ID(swapchain) - 1, s = ID(semaphore);
    assert(t < 2 && !fence && timeout == UINT64_MAX);
    if (acquire_busy[s]) ++acquire_reuse_errors;
    *index = order[t][acquire_calls[t]++ % 8];
    acquire_image[s] = *index;
    acquire_target[s] = t;
    acquire_ready[s] = true;
    return VK_SUCCESS;
}
VkResult vkWaitForFences(VkDevice d, uint32_t n, const VkFence *fences,
                         VkBool32 all, uint64_t timeout) {
    assert(n == 1 && all && timeout == UINT64_MAX);
    if (fail_wait) return VK_ERROR_DEVICE_LOST;
    fence_ready[ID(*fences)] = true;
    for (unsigned i = 0; i < 256; ++i)
        if (acquire_busy[i] == *fences) acquire_busy[i] = VK_NULL_HANDLE;
    /* Submission fences do NOT retire pending presentation waits. */
    return VK_SUCCESS;
}
VkResult vkResetFences(VkDevice d, uint32_t n, const VkFence *fences) {
    assert(n == 1); fence_ready[ID(*fences)] = false; return VK_SUCCESS;
}
VkResult vkQueueSubmit(VkQueue q, uint32_t count, const VkSubmitInfo *submit,
                       VkFence fence) {
    assert(count == 1 && submit->commandBufferCount);
    ++submit_calls;
    if (fail_submit) return VK_ERROR_DEVICE_LOST;
    for (unsigned i = 0; i < submit->waitSemaphoreCount; ++i) {
        unsigned s = ID(submit->pWaitSemaphores[i]);
        if (acquire_ready[s]) {
            unsigned old = presented_sem[acquire_target[s]][acquire_image[s]];
            present_busy[old] = false;
            acquire_ready[s] = false;
            acquire_busy[s] = fence;
        }
    }
    for (unsigned i = 0; i < submit->signalSemaphoreCount; ++i)
        if (present_busy[ID(submit->pSignalSemaphores[i])]) ++present_reuse_errors;
    return VK_SUCCESS;
}
VkResult vkQueuePresentKHR(VkQueue q, const VkPresentInfoKHR *present) {
    assert(present->waitSemaphoreCount == 1);
    unsigned s = ID(*present->pWaitSemaphores);
    present_busy[s] = true;
    for (unsigned i = 0; i < present->swapchainCount; ++i)
        presented_sem[ID(present->pSwapchains[i])-1][present->pImageIndices[i]] = s;
    return present_result;
}
bool lucent_retro_run_frame(lucent_retro_host *host, char *error, size_t size) {
    lucent_android_vulkan_backend *b = (void *)host;
    /* The core can wait on its recycled index; never reset before retro_run. */
    assert(fence_ready[ID(b->fences[b->current_index])]);
    ++core_calls;
    return true;
}
bool lucent_retro_get_hw_info(lucent_retro_host *host, lucent_retro_hw_info *info) {
    memset(info, 0, sizeof(*info)); info->frame_width = 640; info->frame_height = 480;
    return true;
}
enum { LUCENT_SCREEN_TOP, LUCENT_SCREEN_FULL, LUCENT_SCREEN_BOTTOM };
static bool record_present_commands(lucent_android_vulkan_backend *b,
        unsigned width, unsigned height, int crop, char *error, size_t size) { return true; }
static bool record_present_commands_for_target(lucent_android_vulkan_backend *b,
        VkCommandBuffer command, VkImage image, bool initialized, VkExtent2D extent,
        unsigned width, unsigned height, int crop, bool rotation, char *error, size_t size) {
    return true;
}
static bool stamp_core_frame_timestamp(lucent_android_vulkan_backend *b,
        uint64_t sequence, int64_t *stamp) { *stamp = 0; return false; }
/* PRODUCTION_RUN */

static void init(lucent_android_vulkan_backend *b, bool dual) {
    memset(b, 0, sizeof(*b));
    memset(acquire_calls, 0, sizeof(acquire_calls));
    memset(acquire_busy, 0, sizeof(acquire_busy));
    memset(acquire_ready, 0, sizeof(acquire_ready));
    memset(present_busy, 0, sizeof(present_busy));
    memset(presented_sem, 0, sizeof(presented_sem));
    memset(fence_ready, 1, sizeof(fence_ready));
    acquire_reuse_errors = present_reuse_errors = core_calls = submit_calls = 0;
    fail_wait = fail_submit = false; present_result = VK_SUCCESS;
    b->host = (void *)b; b->swapchain = H(VkSwapchainKHR, 1); b->image_count = 3;
    b->context.device = H(VkDevice, 1);
    b->secondary.swapchain = dual ? H(VkSwapchainKHR, 2) : VK_NULL_HANDLE;
    b->secondary.image_count = 3;
    for (unsigned i = 0; i < 3; ++i) {
        b->fences[i] = H(VkFence, 10+i);
        b->image_available[i] = H(VkSemaphore, 20+i);
        b->render_finished[i] = H(VkSemaphore, 30+i);
        b->secondary.fences[i] = H(VkFence, 40+i);
        b->secondary.image_available[i] = H(VkSemaphore, 50+i);
        b->secondary.render_finished[i] = H(VkSemaphore, 60+i);
    }
}
int main(void) {
    lucent_android_vulkan_backend b;
    char error[256]; bool presented;
    for (unsigned dual = 0; dual < 2; ++dual) {
        for (unsigned suboptimal = 0; suboptimal < 2; ++suboptimal) {
            init(&b, dual);
            present_result = suboptimal ? VK_SUBOPTIMAL_KHR : VK_SUCCESS;
            for (unsigned i = 0; i < 64; ++i) {
                assert(lucent_android_vulkan_run_and_present(&b, &presented, error, sizeof(error)));
                assert(presented && b.presented_sequence == i+1);
            }
            assert(present_reuse_errors == 0);
            assert(acquire_reuse_errors == 0);
            assert(core_calls == 64 && submit_calls == (dual ? 128 : 64));
        }
    }
    init(&b, false); fail_wait = true;
    assert(!lucent_android_vulkan_run_and_present(&b, &presented, error, sizeof(error)));
    assert(!presented && core_calls == 0);
    init(&b, false);
    for (unsigned i = 0; i < 3; ++i)
        assert(lucent_android_vulkan_run_and_present(&b, &presented, error, sizeof(error)));
    fail_wait = true;
    assert(!lucent_android_vulkan_run_and_present(&b, &presented, error, sizeof(error)));
    assert(!presented && core_calls == 3 && acquire_calls[0] == 3);
    assert(strstr(error, "acquire semaphore"));
    init(&b, false); fail_submit = true;
    assert(!lucent_android_vulkan_run_and_present(&b, &presented, error, sizeof(error)));
    assert(!presented && b.presented_sequence == 0);
    puts("nonroundrobin primary/secondary, delayed present, suboptimal, errors PASS");
}
