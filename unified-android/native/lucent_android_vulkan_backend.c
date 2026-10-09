#define VK_USE_PLATFORM_ANDROID_KHR 1

#include "include/lucent_android_vulkan_backend.h"
#include "include/lucent_libretro_vulkan.h"
#include "include/lucent_surface_fit.h"

#if !defined(__ANDROID__)
#error "lucent_android_vulkan_backend.c is Android-only"
#endif

#include <android/native_window.h>
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <android/log.h>

#define LUCENT_VK_MAX_IMAGES 8u
#define LUCENT_VK_MAX_WAIT_SEMAPHORES 8u
#define LUCENT_VK_MAX_CORE_COMMANDS 8u

typedef struct lucent_vulkan_secondary_target {
    ANativeWindow *window;
    VkSurfaceKHR surface;
    VkSwapchainKHR swapchain;
    VkFormat swapchain_format;
    VkExtent2D extent;
    uint32_t image_count;
    VkImage images[LUCENT_VK_MAX_IMAGES];
    VkCommandPool command_pool;
    VkCommandBuffer command_buffers[LUCENT_VK_MAX_IMAGES];
    VkFence fences[LUCENT_VK_MAX_IMAGES];
    VkSemaphore image_available[LUCENT_VK_MAX_IMAGES];
    VkFence acquire_pending[LUCENT_VK_MAX_IMAGES]; /* borrowed submit fences */
    VkSemaphore render_finished[LUCENT_VK_MAX_IMAGES];
    bool image_initialized[LUCENT_VK_MAX_IMAGES];
    uint32_t current_index;
    uint32_t frame_slot;
} lucent_vulkan_secondary_target;

struct lucent_android_vulkan_backend {
    pthread_t render_thread;
    bool render_thread_set;
    pthread_mutex_t queue_mutex;
    bool queue_mutex_ready;
    ANativeWindow *window;
    lucent_retro_host *host;
    VkInstance instance;
    VkSurfaceKHR surface;
    struct retro_vulkan_context context;
    const struct retro_hw_render_context_negotiation_interface_vulkan *negotiation;
    struct retro_hw_render_interface_vulkan interface;
    VkSwapchainKHR swapchain;
    VkFormat swapchain_format;
    VkExtent2D extent;
    uint32_t image_count;
    VkImage images[LUCENT_VK_MAX_IMAGES];
    VkCommandPool command_pool;
    VkCommandBuffer command_buffers[LUCENT_VK_MAX_IMAGES];
    VkFence fences[LUCENT_VK_MAX_IMAGES];
    VkSemaphore image_available[LUCENT_VK_MAX_IMAGES];
    VkFence acquire_pending[LUCENT_VK_MAX_IMAGES]; /* borrowed submit fences */
    VkSemaphore render_finished[LUCENT_VK_MAX_IMAGES];
    bool image_initialized[LUCENT_VK_MAX_IMAGES];
    uint32_t current_index;
    uint32_t frame_slot;
    bool current_acquired;
    struct retro_vulkan_image core_image;
    bool has_core_image;
    VkSemaphore core_wait_semaphores[LUCENT_VK_MAX_WAIT_SEMAPHORES];
    uint32_t core_wait_count;
    uint32_t core_src_queue_family;
    VkCommandBuffer core_commands[LUCENT_VK_MAX_CORE_COMMANDS];
    uint32_t core_command_count;
    VkSemaphore core_signal_semaphore;
    uint64_t presented_sequence;
    /* Immutable source timestamps (2026-09-01): Vulkan-runtime cores
     * (ARMSX2/Azahar/Flycast/Dolphin-Wii) presented with real-time buffer
     * stamps, so the frame generator measured 1.6 percent RMS period jitter
     * and never qualified a clock (PS2 run ps2-b30).  VK_GOOGLE_display_timing
     * lets the Android loader stamp each buffer with desiredPresentTime,
     * which SurfaceTexture reports as the producer timestamp; the stamp is
     * the same ideal lattice the GLES backend emits: sequence x 1/stamp_hz on
     * the clock the core is paced at. */
    bool display_timing_enabled;
    bool display_timing_logged;
    bool fg_timestamp_enabled[2]; /* primary, secondary; calloc defaults Off */
    uint64_t timestamp_sequence;
    uint64_t timestamp_base_sequence;
    int64_t timestamp_base_ns;
    int64_t timestamp_last_ns;
    double timestamp_source_hz;
    bool timestamp_timeline_ready;
    float presentation_aspect;
    bool secondary_clockwise_quarter_turn;
    lucent_vulkan_secondary_target secondary;
};

static void set_error(char *buffer, size_t size, const char *format, ...) {
    va_list arguments;
    if (!buffer || !size) return;
    va_start(arguments, format);
    vsnprintf(buffer, size, format, arguments);
    va_end(arguments);
}

static bool claim_render_thread(lucent_android_vulkan_backend *backend,
                                char *error, size_t error_size) {
    if (!backend) {
        set_error(error, error_size, "Vulkan backend is required");
        return false;
    }
    if (!backend->render_thread_set) {
        backend->render_thread = pthread_self();
        backend->render_thread_set = true;
        return true;
    }
    if (!pthread_equal(backend->render_thread, pthread_self())) {
        set_error(error, error_size,
                  "Vulkan lifecycle must stay on its render thread");
        return false;
    }
    return true;
}

static void queue_lock(void *handle) {
    lucent_android_vulkan_backend *backend =
            (lucent_android_vulkan_backend *)handle;
    if (backend && backend->queue_mutex_ready)
        pthread_mutex_lock(&backend->queue_mutex);
}

static void queue_unlock(void *handle) {
    lucent_android_vulkan_backend *backend =
            (lucent_android_vulkan_backend *)handle;
    if (backend && backend->queue_mutex_ready)
        pthread_mutex_unlock(&backend->queue_mutex);
}

static void set_image(void *handle, const struct retro_vulkan_image *image,
                      uint32_t num_semaphores, const VkSemaphore *semaphores,
                      uint32_t src_queue_family) {
    lucent_android_vulkan_backend *backend =
            (lucent_android_vulkan_backend *)handle;
    uint32_t count;
    if (!backend) return;
    backend->has_core_image = image && image->create_info.image != VK_NULL_HANDLE;
    if (!backend->has_core_image) {
        memset(&backend->core_image, 0, sizeof(backend->core_image));
        backend->core_wait_count = 0;
        return;
    }
    backend->core_image = *image;
    count = num_semaphores > LUCENT_VK_MAX_WAIT_SEMAPHORES ?
            LUCENT_VK_MAX_WAIT_SEMAPHORES : num_semaphores;
    if (count && semaphores)
        memcpy(backend->core_wait_semaphores, semaphores,
               count * sizeof(VkSemaphore));
    backend->core_wait_count = semaphores ? count : 0;
    backend->core_src_queue_family = src_queue_family;
}

static uint32_t get_sync_index(void *handle) {
    lucent_android_vulkan_backend *backend =
            (lucent_android_vulkan_backend *)handle;
    return backend ? backend->current_index : 0;
}

static uint32_t get_sync_index_mask(void *handle) {
    lucent_android_vulkan_backend *backend =
            (lucent_android_vulkan_backend *)handle;
    if (!backend || !backend->image_count) return 0;
    return backend->image_count >= 32 ? UINT32_MAX :
            ((1u << backend->image_count) - 1u);
}

static void set_command_buffers(void *handle, uint32_t num_cmd,
                                const VkCommandBuffer *commands) {
    lucent_android_vulkan_backend *backend =
            (lucent_android_vulkan_backend *)handle;
    uint32_t count;
    if (!backend) return;
    count = num_cmd > LUCENT_VK_MAX_CORE_COMMANDS ?
            LUCENT_VK_MAX_CORE_COMMANDS : num_cmd;
    if (count && commands)
        memcpy(backend->core_commands, commands,
               count * sizeof(VkCommandBuffer));
    backend->core_command_count = commands ? count : 0;
}

static void wait_sync_index(void *handle) {
    lucent_android_vulkan_backend *backend =
            (lucent_android_vulkan_backend *)handle;
    if (!backend || !backend->context.device ||
            backend->current_index >= backend->image_count) return;
    vkWaitForFences(backend->context.device, 1,
                    &backend->fences[backend->current_index],
                    VK_TRUE, UINT64_MAX);
}

static void set_signal_semaphore(void *handle, VkSemaphore semaphore) {
    lucent_android_vulkan_backend *backend =
            (lucent_android_vulkan_backend *)handle;
    if (backend) backend->core_signal_semaphore = semaphore;
}

static bool choose_gpu(VkInstance instance, VkSurfaceKHR surface,
                       VkPhysicalDevice *gpu, uint32_t *family,
                       char *error, size_t error_size) {
    VkPhysicalDevice devices[16];
    uint32_t count = 16;
    uint32_t index;
    (void)instance;
    if (vkEnumeratePhysicalDevices(instance, &count, devices) != VK_SUCCESS ||
            !count) {
        set_error(error, error_size, "Android Vulkan has no physical device");
        return false;
    }
    if (count > 16) count = 16;
    for (index = 0; index < count; index++) {
        VkQueueFamilyProperties properties[32];
        uint32_t family_count = 32;
        uint32_t candidate;
        vkGetPhysicalDeviceQueueFamilyProperties(devices[index], &family_count,
                                                  properties);
        if (family_count > 32) family_count = 32;
        for (candidate = 0; candidate < family_count; candidate++) {
            VkBool32 present = VK_FALSE;
            if ((properties[candidate].queueFlags &
                    (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT)) !=
                    (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT)) continue;
            if (vkGetPhysicalDeviceSurfaceSupportKHR(
                    devices[index], candidate, surface, &present) == VK_SUCCESS &&
                    present) {
                *gpu = devices[index];
                *family = candidate;
                return true;
            }
        }
    }
    set_error(error, error_size,
              "no Vulkan graphics/compute queue can present to Android");
    return false;
}

static bool create_instance_and_surface(
        lucent_android_vulkan_backend *backend,
        char *error, size_t error_size) {
    const char *extensions[] = {
        VK_KHR_SURFACE_EXTENSION_NAME,
        VK_KHR_ANDROID_SURFACE_EXTENSION_NAME
    };
    VkApplicationInfo fallback = {
        VK_STRUCTURE_TYPE_APPLICATION_INFO, NULL, "Lucent", 1,
        "Lucent", 1, VK_API_VERSION_1_1
    };
    VkApplicationInfo application = fallback;
    VkInstanceCreateInfo create_info = {
        VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, NULL, 0,
        NULL, 0, NULL, 2, extensions
    };
    VkAndroidSurfaceCreateInfoKHR surface_info = {
        VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR,
        NULL, 0, backend->window
    };
    if (backend->negotiation && backend->negotiation->get_application_info) {
        const VkApplicationInfo *requested =
                backend->negotiation->get_application_info();
        if (requested) application = *requested;
    }
    /* Keep the frontend's existing Vulkan 1.1 floor when a legacy core asks
     * for 1.0. Libretro explicitly permits this promotion. Android can expose
     * non-NULL loader trampolines for 1.1 queries on a 1.0 instance even though
     * their driver dispatch entries are NULL (Dolphin Properties2 crash).
     * Copy the core-owned structure; never mutate its static application info.
     * Higher core requirements and all other application fields are preserved.
     */
    if (application.apiVersion < VK_API_VERSION_1_1)
        application.apiVersion = VK_API_VERSION_1_1;
    create_info.pApplicationInfo = &application;
    if (vkCreateInstance(&create_info, NULL, &backend->instance) != VK_SUCCESS) {
        set_error(error, error_size, "cannot create Android Vulkan instance");
        return false;
    }
    if (vkCreateAndroidSurfaceKHR(backend->instance, &surface_info, NULL,
                                  &backend->surface) != VK_SUCCESS) {
        set_error(error, error_size, "cannot create Android Vulkan surface");
        return false;
    }
    return true;
}

static bool create_surface_only(lucent_android_vulkan_backend *backend,
                                char *error, size_t error_size) {
    VkAndroidSurfaceCreateInfoKHR surface_info = {
        VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR,
        NULL, 0, backend->window
    };
    if (!backend->instance || vkCreateAndroidSurfaceKHR(
            backend->instance, &surface_info, NULL,
            &backend->surface) != VK_SUCCESS) {
        set_error(error, error_size, "cannot recreate Android Vulkan surface");
        return false;
    }
    return true;
}

static bool gpu_supports_extension(VkPhysicalDevice gpu, const char *name) {
    VkExtensionProperties *properties;
    uint32_t count = 0;
    uint32_t index;
    bool found = false;
    if (vkEnumerateDeviceExtensionProperties(gpu, NULL, &count, NULL) !=
            VK_SUCCESS || count == 0) return false;
    properties = (VkExtensionProperties *)calloc(count, sizeof(*properties));
    if (!properties) return false;
    if (vkEnumerateDeviceExtensionProperties(gpu, NULL, &count, properties) ==
            VK_SUCCESS) {
        for (index = 0; index < count; ++index) {
            if (strcmp(properties[index].extensionName, name) == 0) {
                found = true;
                break;
            }
        }
    }
    free(properties);
    return found;
}

static bool negotiate_device(lucent_android_vulkan_backend *backend,
                             char *error, size_t error_size) {
    const char *required_extensions[] = {
        VK_KHR_SWAPCHAIN_EXTENSION_NAME,
        VK_GOOGLE_DISPLAY_TIMING_EXTENSION_NAME
    };
    unsigned required_count = 1;
    VkPhysicalDevice gpu = VK_NULL_HANDLE;
    uint32_t family = 0;
    VkPhysicalDeviceFeatures features;
    VkBool32 present = VK_FALSE;
    memset(&features, 0, sizeof(features));
    if (!backend->negotiation || backend->negotiation->interface_version < 1 ||
            !backend->negotiation->create_device) {
        set_error(error, error_size,
                  "core did not register Vulkan device negotiation");
        return false;
    }
    if (!choose_gpu(backend->instance, backend->surface, &gpu, &family,
                    error, error_size)) return false;
    memset(&backend->context, 0, sizeof(backend->context));
    backend->display_timing_enabled = false;
    if (gpu_supports_extension(gpu, VK_GOOGLE_DISPLAY_TIMING_EXTENSION_NAME))
        required_count = 2;
    if (required_count == 2 && (!backend->negotiation->create_device(
            &backend->context, backend->instance, gpu, backend->surface,
            vkGetInstanceProcAddr, required_extensions, required_count,
            NULL, 0, &features) ||
            backend->context.device == VK_NULL_HANDLE)) {
        /* A core that refuses the timing extension still gets its device;
         * the frame generator then sees real-time stamps as before. */
        __android_log_print(ANDROID_LOG_WARN, "LucentVulkanBackend",
                "core rejected %s; retrying device negotiation without it",
                VK_GOOGLE_DISPLAY_TIMING_EXTENSION_NAME);
        memset(&backend->context, 0, sizeof(backend->context));
        required_count = 1;
    }
    if (required_count == 1 && (!backend->negotiation->create_device(
            &backend->context, backend->instance, gpu, backend->surface,
            vkGetInstanceProcAddr, required_extensions, required_count,
            NULL, 0, &features) ||
            backend->context.gpu == VK_NULL_HANDLE ||
            backend->context.device == VK_NULL_HANDLE ||
            backend->context.queue == VK_NULL_HANDLE)) {
        set_error(error, error_size, "core failed Vulkan device negotiation");
        return false;
    }
    if (backend->context.gpu == VK_NULL_HANDLE ||
            backend->context.queue == VK_NULL_HANDLE) {
        set_error(error, error_size, "core failed Vulkan device negotiation");
        return false;
    }
    backend->display_timing_enabled = required_count == 2;
    backend->timestamp_timeline_ready = false;
    backend->timestamp_sequence = 0;
    backend->timestamp_last_ns = 0;
    if (vkGetPhysicalDeviceSurfaceSupportKHR(
            backend->context.gpu,
            backend->context.presentation_queue_family_index,
            backend->surface, &present) != VK_SUCCESS || !present) {
        set_error(error, error_size,
                  "negotiated Vulkan queue cannot present to Android");
        return false;
    }
    backend->interface.instance = backend->instance;
    backend->interface.gpu = backend->context.gpu;
    backend->interface.device = backend->context.device;
    backend->interface.get_device_proc_addr = vkGetDeviceProcAddr;
    backend->interface.get_instance_proc_addr = vkGetInstanceProcAddr;
    backend->interface.queue = backend->context.queue;
    backend->interface.queue_index = backend->context.queue_family_index;
    return true;
}

static bool choose_surface_format(VkPhysicalDevice gpu, VkSurfaceKHR surface,
                                  VkSurfaceFormatKHR *chosen) {
    VkSurfaceFormatKHR formats[32];
    uint32_t count = 32;
    uint32_t index;
    if (vkGetPhysicalDeviceSurfaceFormatsKHR(gpu, surface, &count, formats) !=
            VK_SUCCESS || !count) return false;
    if (count > 32) count = 32;
    *chosen = formats[0];
    for (index = 0; index < count; index++) {
        if ((formats[index].format == VK_FORMAT_R8G8B8A8_UNORM ||
             formats[index].format == VK_FORMAT_B8G8R8A8_UNORM) &&
            formats[index].colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR) {
            *chosen = formats[index];
            break;
        }
    }
    return true;
}

static bool create_swapchain(lucent_android_vulkan_backend *backend,
                             char *error, size_t error_size) {
    VkSurfaceCapabilitiesKHR capabilities;
    VkSurfaceFormatKHR format;
    VkSwapchainCreateInfoKHR info;
    uint32_t desired;
    uint32_t index;
    if (vkGetPhysicalDeviceSurfaceCapabilitiesKHR(
            backend->context.gpu, backend->surface, &capabilities) != VK_SUCCESS ||
            !choose_surface_format(backend->context.gpu, backend->surface,
                                   &format)) {
        set_error(error, error_size, "cannot query Android Vulkan swapchain");
        return false;
    }
    if (!(capabilities.supportedUsageFlags & VK_IMAGE_USAGE_TRANSFER_DST_BIT)) {
        set_error(error, error_size,
                  "Android swapchain does not support transfer presentation");
        return false;
    }
    backend->extent = capabilities.currentExtent;
    if (backend->extent.width == UINT32_MAX) {
        backend->extent.width = (uint32_t)ANativeWindow_getWidth(backend->window);
        backend->extent.height = (uint32_t)ANativeWindow_getHeight(backend->window);
        if (backend->extent.width < capabilities.minImageExtent.width)
            backend->extent.width = capabilities.minImageExtent.width;
        if (backend->extent.width > capabilities.maxImageExtent.width)
            backend->extent.width = capabilities.maxImageExtent.width;
        if (backend->extent.height < capabilities.minImageExtent.height)
            backend->extent.height = capabilities.minImageExtent.height;
        if (backend->extent.height > capabilities.maxImageExtent.height)
            backend->extent.height = capabilities.maxImageExtent.height;
    }
    /* Extra primary FIFO capacity added one refresh of measured queue delay
     * on Thor. Request the supported minimum; enumerate the actual count below
     * because the driver may allocate more than requested. */
    desired = capabilities.minImageCount;
    if (capabilities.maxImageCount && desired > capabilities.maxImageCount)
        desired = capabilities.maxImageCount;
    if (desired > LUCENT_VK_MAX_IMAGES) desired = LUCENT_VK_MAX_IMAGES;
    memset(&info, 0, sizeof(info));
    info.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR;
    info.surface = backend->surface;
    info.minImageCount = desired;
    info.imageFormat = format.format;
    info.imageColorSpace = format.colorSpace;
    info.imageExtent = backend->extent;
    info.imageArrayLayers = 1;
    info.imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    info.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
    /* EmuFusion records the primary transfer in the Android Surface's logical
     * landscape coordinates. Thor reports a portrait-native currentTransform;
     * advertising that transform without pre-rotating our blit publishes the
     * image sideways. This was first proven on Azahar and then independently
     * reproduced when Wii moved to Dolphin's Vulkan interface. Identity tells
     * Android that the buffer is already in the Surface coordinate space.
     * Fail closed rather than silently rotating any Vulkan-backed system. */
    if (!(capabilities.supportedTransforms &
            VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR)) {
        set_error(error, error_size,
                  "primary surface lacks identity pre-transform");
        return false;
    }
    info.preTransform = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR;
    if (capabilities.supportedCompositeAlpha &
            VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR)
        info.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    else if (capabilities.supportedCompositeAlpha &
            VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR)
        info.compositeAlpha = VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR;
    else if (capabilities.supportedCompositeAlpha &
            VK_COMPOSITE_ALPHA_POST_MULTIPLIED_BIT_KHR)
        info.compositeAlpha = VK_COMPOSITE_ALPHA_POST_MULTIPLIED_BIT_KHR;
    else
        info.compositeAlpha = VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR;
    info.presentMode = VK_PRESENT_MODE_FIFO_KHR;
    info.clipped = VK_TRUE;
    if (vkCreateSwapchainKHR(backend->context.device, &info, NULL,
                             &backend->swapchain) != VK_SUCCESS) {
        set_error(error, error_size, "cannot create Android Vulkan swapchain");
        return false;
    }
    backend->image_count = LUCENT_VK_MAX_IMAGES;
    if (vkGetSwapchainImagesKHR(backend->context.device, backend->swapchain,
                                &backend->image_count, backend->images) !=
            VK_SUCCESS || !backend->image_count ||
            backend->image_count > LUCENT_VK_MAX_IMAGES) {
        set_error(error, error_size, "cannot enumerate Vulkan swapchain images");
        return false;
    }
    __android_log_print(ANDROID_LOG_INFO, "LucentVulkanBackend",
            "QA primary FIFO minImages=%u maxImages=%u requested=%u actual=%u",
            capabilities.minImageCount, capabilities.maxImageCount, desired,
            backend->image_count);
    backend->swapchain_format = format.format;
    backend->frame_slot = 0;
    {
        VkCommandPoolCreateInfo pool = {
            VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, NULL,
            VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
            backend->context.queue_family_index
        };
        VkCommandBufferAllocateInfo allocation;
        if (vkCreateCommandPool(backend->context.device, &pool, NULL,
                                &backend->command_pool) != VK_SUCCESS) {
            set_error(error, error_size, "cannot create Vulkan command pool");
            return false;
        }
        memset(&allocation, 0, sizeof(allocation));
        allocation.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        allocation.commandPool = backend->command_pool;
        allocation.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        allocation.commandBufferCount = backend->image_count;
        if (vkAllocateCommandBuffers(backend->context.device, &allocation,
                                     backend->command_buffers) != VK_SUCCESS) {
            set_error(error, error_size, "cannot allocate Vulkan command buffers");
            return false;
        }
    }
    for (index = 0; index < backend->image_count; index++) {
        VkFenceCreateInfo fence = {
            VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, NULL,
            VK_FENCE_CREATE_SIGNALED_BIT
        };
        VkSemaphoreCreateInfo semaphore = {
            VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO, NULL, 0
        };
        if (vkCreateFence(backend->context.device, &fence, NULL,
                          &backend->fences[index]) != VK_SUCCESS ||
            vkCreateSemaphore(backend->context.device, &semaphore, NULL,
                              &backend->image_available[index]) != VK_SUCCESS ||
            vkCreateSemaphore(backend->context.device, &semaphore, NULL,
                              &backend->render_finished[index]) != VK_SUCCESS) {
            set_error(error, error_size,
                      "cannot create Vulkan frame synchronization");
            return false;
        }
    }
    return true;
}

static void destroy_swapchain(lucent_android_vulkan_backend *backend) {
    uint32_t index;
    if (!backend || !backend->context.device) return;
    for (index = 0; index < backend->image_count; index++) {
        if (backend->fences[index])
            vkDestroyFence(backend->context.device, backend->fences[index], NULL);
        if (backend->image_available[index])
            vkDestroySemaphore(backend->context.device,
                               backend->image_available[index], NULL);
        if (backend->render_finished[index])
            vkDestroySemaphore(backend->context.device,
                               backend->render_finished[index], NULL);
    }
    if (backend->command_pool)
        vkDestroyCommandPool(backend->context.device,
                             backend->command_pool, NULL);
    if (backend->swapchain)
        vkDestroySwapchainKHR(backend->context.device,
                              backend->swapchain, NULL);
    backend->swapchain = VK_NULL_HANDLE;
    backend->command_pool = VK_NULL_HANDLE;
    backend->image_count = 0;
    backend->frame_slot = 0;
    memset(backend->fences, 0, sizeof(backend->fences));
    memset(backend->image_available, 0, sizeof(backend->image_available));
    memset(backend->acquire_pending, 0, sizeof(backend->acquire_pending));
    memset(backend->render_finished, 0, sizeof(backend->render_finished));
    memset(backend->image_initialized, 0, sizeof(backend->image_initialized));
}

static bool create_secondary_swapchain(
        lucent_android_vulkan_backend *backend,
        char *error, size_t error_size) {
    lucent_vulkan_secondary_target *target = &backend->secondary;
    VkSurfaceCapabilitiesKHR capabilities;
    VkSurfaceFormatKHR format;
    VkSwapchainCreateInfoKHR info;
    uint32_t desired;
    uint32_t index;
    if (vkGetPhysicalDeviceSurfaceCapabilitiesKHR(
            backend->context.gpu, target->surface, &capabilities) != VK_SUCCESS ||
            !choose_surface_format(backend->context.gpu, target->surface, &format)) {
        set_error(error, error_size, "cannot query secondary Vulkan swapchain");
        return false;
    }
    if (!(capabilities.supportedUsageFlags & VK_IMAGE_USAGE_TRANSFER_DST_BIT)) {
        set_error(error, error_size,
                  "secondary swapchain does not support transfer presentation");
        return false;
    }
    target->extent = capabilities.currentExtent;
    if (target->extent.width == UINT32_MAX) {
        target->extent.width = (uint32_t)ANativeWindow_getWidth(target->window);
        target->extent.height = (uint32_t)ANativeWindow_getHeight(target->window);
        if (target->extent.width < capabilities.minImageExtent.width)
            target->extent.width = capabilities.minImageExtent.width;
        if (target->extent.width > capabilities.maxImageExtent.width)
            target->extent.width = capabilities.maxImageExtent.width;
        if (target->extent.height < capabilities.minImageExtent.height)
            target->extent.height = capabilities.minImageExtent.height;
        if (target->extent.height > capabilities.maxImageExtent.height)
            target->extent.height = capabilities.maxImageExtent.height;
    }
    desired = capabilities.minImageCount + 1;
    if (capabilities.maxImageCount && desired > capabilities.maxImageCount)
        desired = capabilities.maxImageCount;
    if (desired > LUCENT_VK_MAX_IMAGES) desired = LUCENT_VK_MAX_IMAGES;
    memset(&info, 0, sizeof(info));
    info.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR;
    info.surface = target->surface;
    info.minImageCount = desired;
    info.imageFormat = format.format;
    info.imageColorSpace = format.colorSpace;
    info.imageExtent = target->extent;
    info.imageArrayLayers = 1;
    info.imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    info.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
    if (backend->secondary_clockwise_quarter_turn) {
        /* The lower SurfaceControl carries BUFFER_TRANSFORM_ROTATE_90. Do not
         * let Vulkan pre-rotate the swapchain back to the display's current
         * transform, or the two transforms cancel and Azahar stays sideways.
         * Identity is mandatory for this reviewed path; fail closed if the
         * consumer cannot honor it. */
        if (!(capabilities.supportedTransforms &
                VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR)) {
            set_error(error, error_size,
                      "secondary clockwise surface lacks identity pre-transform");
            return false;
        }
        info.preTransform = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR;
    } else {
        info.preTransform = capabilities.currentTransform;
    }
    if (capabilities.supportedCompositeAlpha & VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR)
        info.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    else if (capabilities.supportedCompositeAlpha &
            VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR)
        info.compositeAlpha = VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR;
    else if (capabilities.supportedCompositeAlpha &
            VK_COMPOSITE_ALPHA_POST_MULTIPLIED_BIT_KHR)
        info.compositeAlpha = VK_COMPOSITE_ALPHA_POST_MULTIPLIED_BIT_KHR;
    else info.compositeAlpha = VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR;
    info.presentMode = VK_PRESENT_MODE_FIFO_KHR;
    info.clipped = VK_TRUE;
    if (vkCreateSwapchainKHR(backend->context.device, &info, NULL,
                             &target->swapchain) != VK_SUCCESS) {
        set_error(error, error_size, "cannot create secondary Vulkan swapchain");
        return false;
    }
    __android_log_print(ANDROID_LOG_INFO, "LucentVulkanBackend",
            "secondary swapchain window=%dx%d extent=%ux%u logical=%ux%u "
            "currentTransform=0x%x preTransform=0x%x",
            ANativeWindow_getWidth(target->window),
            ANativeWindow_getHeight(target->window),
            target->extent.width, target->extent.height,
            backend->secondary_clockwise_quarter_turn ?
                    target->extent.height : target->extent.width,
            backend->secondary_clockwise_quarter_turn ?
                    target->extent.width : target->extent.height,
            (unsigned)capabilities.currentTransform, (unsigned)info.preTransform);
    target->image_count = LUCENT_VK_MAX_IMAGES;
    if (vkGetSwapchainImagesKHR(backend->context.device, target->swapchain,
                                &target->image_count, target->images) != VK_SUCCESS ||
            !target->image_count || target->image_count > LUCENT_VK_MAX_IMAGES) {
        set_error(error, error_size, "cannot enumerate secondary swapchain images");
        return false;
    }
    target->swapchain_format = format.format;
    {
        VkCommandPoolCreateInfo pool = {
            VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, NULL,
            VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
            backend->context.queue_family_index
        };
        VkCommandBufferAllocateInfo allocation;
        if (vkCreateCommandPool(backend->context.device, &pool, NULL,
                                &target->command_pool) != VK_SUCCESS) {
            set_error(error, error_size, "cannot create secondary command pool");
            return false;
        }
        memset(&allocation, 0, sizeof(allocation));
        allocation.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        allocation.commandPool = target->command_pool;
        allocation.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        allocation.commandBufferCount = target->image_count;
        if (vkAllocateCommandBuffers(backend->context.device, &allocation,
                                     target->command_buffers) != VK_SUCCESS) {
            set_error(error, error_size,
                      "cannot allocate secondary command buffers");
            return false;
        }
    }
    for (index = 0; index < target->image_count; index++) {
        VkFenceCreateInfo fence = {
            VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, NULL,
            VK_FENCE_CREATE_SIGNALED_BIT
        };
        VkSemaphoreCreateInfo semaphore = {
            VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO, NULL, 0
        };
        if (vkCreateFence(backend->context.device, &fence, NULL,
                          &target->fences[index]) != VK_SUCCESS ||
            vkCreateSemaphore(backend->context.device, &semaphore, NULL,
                              &target->image_available[index]) != VK_SUCCESS ||
            vkCreateSemaphore(backend->context.device, &semaphore, NULL,
                              &target->render_finished[index]) != VK_SUCCESS) {
            set_error(error, error_size,
                      "cannot create secondary frame synchronization");
            return false;
        }
    }
    return true;
}

static void destroy_secondary_swapchain(lucent_android_vulkan_backend *backend) {
    lucent_vulkan_secondary_target *target;
    uint32_t index;
    if (!backend || !backend->context.device) return;
    target = &backend->secondary;
    for (index = 0; index < target->image_count; index++) {
        if (target->fences[index])
            vkDestroyFence(backend->context.device, target->fences[index], NULL);
        if (target->image_available[index])
            vkDestroySemaphore(backend->context.device,
                               target->image_available[index], NULL);
        if (target->render_finished[index])
            vkDestroySemaphore(backend->context.device,
                               target->render_finished[index], NULL);
    }
    if (target->command_pool)
        vkDestroyCommandPool(backend->context.device, target->command_pool, NULL);
    if (target->swapchain)
        vkDestroySwapchainKHR(backend->context.device, target->swapchain, NULL);
    target->swapchain = VK_NULL_HANDLE;
    target->command_pool = VK_NULL_HANDLE;
    target->image_count = 0;
    target->frame_slot = 0;
    memset(target->fences, 0, sizeof(target->fences));
    memset(target->image_available, 0, sizeof(target->image_available));
    memset(target->acquire_pending, 0, sizeof(target->acquire_pending));
    memset(target->render_finished, 0, sizeof(target->render_finished));
    memset(target->image_initialized, 0, sizeof(target->image_initialized));
}

static void image_barrier(VkCommandBuffer command, VkImage image,
                          VkImageLayout old_layout, VkImageLayout new_layout,
                          VkAccessFlags src_access, VkAccessFlags dst_access,
                          uint32_t src_family, uint32_t dst_family) {
    VkImageMemoryBarrier barrier;
    memset(&barrier, 0, sizeof(barrier));
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.srcAccessMask = src_access;
    barrier.dstAccessMask = dst_access;
    barrier.oldLayout = old_layout;
    barrier.newLayout = new_layout;
    barrier.srcQueueFamilyIndex = src_family;
    barrier.dstQueueFamilyIndex = dst_family;
    barrier.image = image;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.layerCount = 1;
    vkCmdPipelineBarrier(command,
                         VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
                         VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
                         0, 0, NULL, 0, NULL, 1, &barrier);
}

enum lucent_screen_crop {
    LUCENT_SCREEN_FULL = 0,
    LUCENT_SCREEN_TOP = 1,
    LUCENT_SCREEN_BOTTOM = 2
};

typedef struct lucent_source_region {
    unsigned x;
    unsigned y;
    unsigned width;
    unsigned height;
} lucent_source_region;

/* Resolve the actual core layout rather than treating every dual-screen image
 * as two vertical halves. A clockwise secondary is the reviewed Azahar path:
 * lucent_libretro_host forces SideScreen, whose source is 400x240 + 320x240
 * horizontally (720x240 at 1x). Other dual-screen cores retain their audited
 * top-bottom composite. */
static bool resolve_source_region(
        const lucent_android_vulkan_backend *backend,
        unsigned source_width, unsigned source_height,
        enum lucent_screen_crop crop, lucent_source_region *region,
        char *error, size_t error_size) {
    if (!backend || !region || !source_width || !source_height) {
        set_error(error, error_size, "invalid Vulkan source geometry");
        return false;
    }
    memset(region, 0, sizeof(*region));
    if (crop == LUCENT_SCREEN_FULL) {
        region->width = source_width;
        region->height = source_height;
        return true;
    }
    if (backend->secondary_clockwise_quarter_turn) {
        /* SideScreen has a 3:1 canvas. Use integer fractions so every
         * resolution factor keeps the shared edge exact and consumes every
         * source column once: top [0, 5/9), bottom [5/9, 1). */
        if ((uint64_t)source_width != (uint64_t)source_height * 3u) {
            set_error(error, error_size,
                      "Azahar SideScreen must be 3:1, got %ux%u",
                      source_width, source_height);
            return false;
        }
        unsigned top_width = (unsigned)(((uint64_t)source_width * 5u) / 9u);
        if (!top_width || top_width >= source_width) {
            set_error(error, error_size, "invalid Azahar SideScreen split");
            return false;
        }
        region->x = crop == LUCENT_SCREEN_BOTTOM ? top_width : 0u;
        region->width = crop == LUCENT_SCREEN_BOTTOM ?
                source_width - top_width : top_width;
        region->height = source_height;
        return true;
    }
    /* The stacked DS image is top-first like the software path (melonDS
     * composes TopBottom with the top screen at y=0 and the touch screen at
     * y=source_height/2), so the bottom crop starts at source_height / 2.
     * The exchanged form put the DS top screen on the Thor lower panel in
     * harness run nds-b57 (2026-09-01).  UNVERIFIED on a device: melonds-ds
     * is pinned to the software renderer, so this Vulkan path is unused. */
    region->y = crop == LUCENT_SCREEN_BOTTOM ? source_height / 2u : 0u;
    region->width = source_width;
    region->height = source_height / 2u;
    if (!region->height) {
        set_error(error, error_size, "dual-screen source is too short");
        return false;
    }
    return true;
}

static bool record_present_commands_for_target(
        lucent_android_vulkan_backend *backend, VkCommandBuffer command,
        VkImage destination_image, bool destination_initialized,
        VkExtent2D destination_extent, unsigned source_width,
        unsigned source_height, enum lucent_screen_crop crop,
        bool scaled_portrait_surface,
        char *error, size_t error_size) {
    VkCommandBufferBeginInfo begin = {
        VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, NULL,
        VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, NULL
    };
    VkImageLayout source_layout = VK_IMAGE_LAYOUT_UNDEFINED;
    VkImage source = VK_NULL_HANDLE;
    VkClearColorValue opaque_black;
    VkImageSubresourceRange whole_image;
    if (vkResetCommandBuffer(command, 0) != VK_SUCCESS ||
            vkBeginCommandBuffer(command, &begin) != VK_SUCCESS) {
        set_error(error, error_size, "cannot begin Vulkan presentation commands");
        return false;
    }
    image_barrier(command, destination_image,
                  destination_initialized ?
                        VK_IMAGE_LAYOUT_PRESENT_SRC_KHR : VK_IMAGE_LAYOUT_UNDEFINED,
                  VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                  0, VK_ACCESS_TRANSFER_WRITE_BIT,
                  VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED);
    /* Swapchain images are recycled, and an aspect-preserving blit only covers
     * the letterboxed destination rectangle.  Without an unconditional clear
     * the pillarbox/letterbox rows keep whatever the recycled buffer held: the
     * never-written initial content (transparent, so the Lucent library behind
     * the gameplay window shows through) or a stale band left by an earlier,
     * wider core output size.  Clear the complete image to opaque black on
     * every frame so presentation owns every pixel it publishes. */
    memset(&opaque_black, 0, sizeof(opaque_black));
    opaque_black.float32[3] = 1.0f;
    memset(&whole_image, 0, sizeof(whole_image));
    whole_image.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    whole_image.levelCount = 1;
    whole_image.layerCount = 1;
    vkCmdClearColorImage(command, destination_image,
                         VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                         &opaque_black, 1, &whole_image);
    if (backend->has_core_image && source_width && source_height) {
        /* Clear and blit overlap in the destination. Command order alone
         * does not resolve their transfer-write/transfer-write hazard: the
         * clear must finish before the game image overwrites the active area.
         * Keep the layout; this is a memory dependency, not a transition. */
        image_barrier(command, destination_image,
                      VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                      VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                      VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_TRANSFER_WRITE_BIT,
                      VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED);
        VkImageBlit blit;
        uint32_t destination_width;
        uint32_t destination_height;
        lucent_source_region source_region;
        unsigned source_x;
        unsigned source_y;
        unsigned cropped_width;
        unsigned cropped_height;
        int32_t destination_x;
        int32_t destination_y;
        source = backend->core_image.create_info.image;
        source_layout = backend->core_image.image_layout;
        if (source_layout != VK_IMAGE_LAYOUT_GENERAL &&
                source_layout != VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL) {
            image_barrier(command, source, source_layout,
                          VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                          VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
                          VK_ACCESS_SHADER_WRITE_BIT,
                          VK_ACCESS_TRANSFER_READ_BIT,
                          VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED);
        }
        lucent_retro_av_info av;
        float aspect = 0.0f;
        if (!resolve_source_region(backend, source_width, source_height, crop,
                                   &source_region, error, error_size)) return false;
        source_x = source_region.x;
        source_y = source_region.y;
        cropped_width = source_region.width;
        cropped_height = source_region.height;
        /* Scale by the DISPLAY aspect, not by the core image's pixel shape.
         * Console pixels are rarely square -- a PS2 640x448 image was drawn on
         * a 4:3 television -- so fitting source_width/cropped_height stretches
         * the picture wider than it is tall, which is the same fault the
         * frontend's own presentation was corrected for. A crop is half the
         * picture and the core's number describes the whole of it, so only a
         * full-frame present may use it. This mirrors what the GLES backend
         * already does in create_framebuffer(). */
        memset(&av, 0, sizeof(av));
        if (crop == LUCENT_SCREEN_FULL &&
                isfinite(backend->presentation_aspect) &&
                backend->presentation_aspect > 0.1f &&
                backend->presentation_aspect < 10.0f)
            aspect = backend->presentation_aspect;
        if (aspect <= 0.0f && crop == LUCENT_SCREEN_FULL && backend->host &&
                lucent_retro_get_av_info(backend->host, &av) &&
                isfinite(av.aspect_ratio) &&
                av.aspect_ratio > 0.1f && av.aspect_ratio < 10.0f)
            aspect = av.aspect_ratio;
        if (aspect <= 0.0f)
            aspect = (float)cropped_width / (float)cropped_height;
        /* The primary panel follows EmuFusion's full-height rule.  A secondary
         * DS/3DS touch screen is different: cropping its left/right edges hides
         * UI and touch targets, so the complete crop must be contained inside
         * that physical panel with black bars where necessary. */
        if (crop != LUCENT_SCREEN_FULL && scaled_portrait_surface) {
            lucent_surface_rect fitted;
            /* The reviewed lower SurfaceView has a portrait producer but a
             * landscape logical View. SurfaceControl already supplies the
             * working orientation; the composed image is independently
             * scaled from producer axes into that View. Fit the logical View
             * first, then map the rectangle back, without rotating the blit.
             * Thor: 1080x1240 producer -> 1240x1080 View; the 4:3 image needs
             * 1080x1068 producer pixels to compose as 1240x930, not 1240x705. */
            if (!lucent_surface_fit(destination_extent.width,
                    destination_extent.height, destination_extent.height,
                    destination_extent.width, aspect, &fitted)) {
                set_error(error, error_size,
                          "invalid scaled portrait Vulkan destination geometry");
                return false;
            }
            destination_width = fitted.width;
            destination_height = fitted.height;
        } else if (crop != LUCENT_SCREEN_FULL) {
            destination_width = destination_extent.width;
            destination_height =
                    (uint32_t)((float)destination_width / aspect + 0.5f);
            if (destination_height > destination_extent.height) {
                destination_height = destination_extent.height;
                destination_width =
                        (uint32_t)((float)destination_height * aspect + 0.5f);
            }
        } else {
            destination_height = destination_extent.height;
            destination_width = (uint32_t)((float)destination_height * aspect + 0.5f);
            if (destination_width > destination_extent.width) {
                /* A too-wide frame cannot be simultaneously full-height and
                 * wholly on-screen. Containment is the only non-destructive
                 * answer: preserve every source pixel and letterbox. */
                destination_width = destination_extent.width;
                destination_height = (uint32_t)(
                        (float)destination_width / aspect + 0.5f);
            }
        }
        if (!destination_width) destination_width = 1u;
        if (!destination_height) destination_height = 1u;
        destination_x = (int32_t)(destination_extent.width - destination_width) / 2;
        destination_y = (int32_t)(destination_extent.height - destination_height) / 2;
        memset(&blit, 0, sizeof(blit));
        blit.srcSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        blit.srcSubresource.layerCount = 1;
        blit.srcOffsets[0].x = (int32_t)source_x;
        blit.srcOffsets[1].x = (int32_t)(source_x + cropped_width);
        blit.srcOffsets[0].y = (int32_t)source_y;
        blit.srcOffsets[1].y = (int32_t)(source_y + cropped_height);
        blit.srcOffsets[1].z = 1;
        blit.dstSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        blit.dstSubresource.layerCount = 1;
        blit.dstOffsets[0].x = destination_x;
        blit.dstOffsets[0].y = destination_y;
        blit.dstOffsets[1].x = destination_x + (int32_t)destination_width;
        blit.dstOffsets[1].y = destination_y + (int32_t)destination_height;
        blit.dstOffsets[1].z = 1;
        vkCmdBlitImage(command, source,
                       source_layout == VK_IMAGE_LAYOUT_GENERAL ?
                            VK_IMAGE_LAYOUT_GENERAL :
                            VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                       destination_image,
                       VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                       1, &blit, VK_FILTER_LINEAR);
        if (source_layout != VK_IMAGE_LAYOUT_GENERAL &&
                source_layout != VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL) {
            image_barrier(command, source,
                          VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, source_layout,
                          VK_ACCESS_TRANSFER_READ_BIT,
                          VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
                          VK_ACCESS_SHADER_READ_BIT,
                          VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED);
        }
    }
    image_barrier(command, destination_image,
                  VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                  VK_IMAGE_LAYOUT_PRESENT_SRC_KHR,
                  VK_ACCESS_TRANSFER_WRITE_BIT, 0,
                  VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED);
    if (vkEndCommandBuffer(command) != VK_SUCCESS) {
        set_error(error, error_size, "cannot end Vulkan presentation commands");
        return false;
    }
    return true;
}

static bool record_present_commands(lucent_android_vulkan_backend *backend,
                                    unsigned source_width,
                                    unsigned source_height,
                                    enum lucent_screen_crop crop,
                                    char *error, size_t error_size) {
    return record_present_commands_for_target(backend,
            backend->command_buffers[backend->current_index],
            backend->images[backend->current_index],
            backend->image_initialized[backend->current_index], backend->extent,
            source_width, source_height, crop, false, error, error_size);
}

lucent_android_vulkan_backend *lucent_android_vulkan_create(
        char *error, size_t error_size) {
    lucent_android_vulkan_backend *backend =
            (lucent_android_vulkan_backend *)calloc(1, sizeof(*backend));
    if (!backend) {
        set_error(error, error_size, "out of memory creating Vulkan backend");
        return NULL;
    }
    if (pthread_mutex_init(&backend->queue_mutex, NULL) != 0) {
        set_error(error, error_size, "cannot create Vulkan queue mutex");
        free(backend);
        return NULL;
    }
    backend->queue_mutex_ready = true;
    backend->interface.interface_type = RETRO_HW_RENDER_INTERFACE_VULKAN;
    backend->interface.interface_version =
            RETRO_HW_RENDER_INTERFACE_VULKAN_VERSION;
    backend->interface.handle = backend;
    backend->interface.set_image = set_image;
    backend->interface.get_sync_index = get_sync_index;
    backend->interface.get_sync_index_mask = get_sync_index_mask;
    backend->interface.set_command_buffers = set_command_buffers;
    backend->interface.wait_sync_index = wait_sync_index;
    backend->interface.lock_queue = queue_lock;
    backend->interface.unlock_queue = queue_unlock;
    backend->interface.set_signal_semaphore = set_signal_semaphore;
    return backend;
}

bool lucent_android_vulkan_set_fg_timestamp(
        lucent_android_vulkan_backend *backend, bool secondary, bool enabled,
        char *error, size_t error_size) {
    if (!backend) {
        set_error(error, error_size, "Vulkan backend is required");
        return false;
    }
    backend->fg_timestamp_enabled[secondary ? 1 : 0] = enabled;
    backend->timestamp_timeline_ready = false;
    backend->timestamp_last_ns = 0;
    backend->display_timing_logged = false;
    return true;
}

bool lucent_android_vulkan_set_presentation_aspect(
        lucent_android_vulkan_backend *backend, float aspect,
        char *error, size_t error_size) {
    if (!backend) {
        set_error(error, error_size, "Vulkan backend is required");
        return false;
    }
    if (backend->window) {
        set_error(error, error_size,
                  "Vulkan presentation aspect must be set before attach");
        return false;
    }
    if (!isfinite(aspect) || aspect <= 0.1f || aspect >= 10.0f) {
        set_error(error, error_size,
                  "Vulkan presentation aspect must be finite and between 0.1 and 10");
        return false;
    }
    backend->presentation_aspect = aspect;
    return true;
}

bool lucent_android_vulkan_set_secondary_rotation(
        lucent_android_vulkan_backend *backend, unsigned clockwise_degrees,
        char *error, size_t error_size) {
    if (!backend) {
        set_error(error, error_size, "Vulkan backend is required");
        return false;
    }
    if (backend->secondary.surface || backend->secondary.swapchain) {
        set_error(error, error_size,
                  "secondary rotation must be set before attach");
        return false;
    }
    if (clockwise_degrees != 0u && clockwise_degrees != 90u) {
        set_error(error, error_size,
                  "secondary rotation must be 0 or 90 degrees clockwise");
        return false;
    }
    backend->secondary_clockwise_quarter_turn = clockwise_degrees == 90u;
    return true;
}

bool lucent_android_vulkan_get_host_options(
        lucent_android_vulkan_backend *backend,
        lucent_retro_hw_options *options,
        char *error, size_t error_size) {
    if (!backend || !options) {
        set_error(error, error_size, "Vulkan backend and options are required");
        return false;
    }
    memset(options, 0, sizeof(*options));
    options->struct_size = sizeof(*options);
    options->api_version = LUCENT_RETRO_HW_OPTIONS_VERSION;
    options->context_capabilities = LUCENT_RETRO_HW_VULKAN;
    options->feature_capabilities = LUCENT_RETRO_HW_CACHE_CONTEXT;
    options->preferred_context = LUCENT_RETRO_HW_VULKAN;
    options->userdata = backend;
    options->render_interface = &backend->interface;
    return true;
}

bool lucent_android_vulkan_attach(
        lucent_android_vulkan_backend *backend, lucent_retro_host *host,
        ANativeWindow *window, char *error, size_t error_size) {
    lucent_retro_hw_info info;
    if (!backend || !host || !window ||
            !claim_render_thread(backend, error, error_size)) return false;
    if (backend->window) {
        set_error(error, error_size, "Vulkan surface is already attached");
        return false;
    }
    if (!lucent_retro_get_hw_info(host, &info) || !info.negotiated ||
            info.context_type != RETRO_HW_CONTEXT_VULKAN) {
        set_error(error, error_size, "loaded core did not negotiate Vulkan");
        return false;
    }
    backend->negotiation =
            (const struct retro_hw_render_context_negotiation_interface_vulkan *)
            lucent_retro_hw_context_negotiation_interface(host);
    backend->host = host;
    backend->window = window;
    ANativeWindow_acquire(window);
    if (backend->context.device) {
        if (!create_surface_only(backend, error, error_size) ||
                !create_swapchain(backend, error, error_size)) {
            lucent_android_vulkan_detach(backend, NULL, 0);
            return false;
        }
        return true;
    }
    if (!create_instance_and_surface(backend, error, error_size) ||
            !negotiate_device(backend, error, error_size) ||
            !create_swapchain(backend, error, error_size) ||
            !lucent_retro_hw_context_reset(host, error, error_size)) {
        lucent_android_vulkan_detach(backend, NULL, 0);
        return false;
    }
    return true;
}

bool lucent_android_vulkan_attach_secondary(
        lucent_android_vulkan_backend *backend, ANativeWindow *window,
        char *error, size_t error_size) {
    lucent_vulkan_secondary_target *target;
    VkAndroidSurfaceCreateInfoKHR surface_info;
    VkBool32 present = VK_FALSE;
    if (!backend || !window || !claim_render_thread(backend, error, error_size))
        return false;
    if (!backend->window || !backend->instance || !backend->context.device) {
        set_error(error, error_size,
                  "primary Vulkan surface must be attached first");
        return false;
    }
    target = &backend->secondary;
    if (target->window) {
        set_error(error, error_size,
                  "secondary Vulkan surface is already attached");
        return false;
    }
    target->window = window;
    ANativeWindow_acquire(window);
    memset(&surface_info, 0, sizeof(surface_info));
    surface_info.sType = VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR;
    surface_info.window = window;
    if (vkCreateAndroidSurfaceKHR(backend->instance, &surface_info, NULL,
                                  &target->surface) != VK_SUCCESS) {
        set_error(error, error_size,
                  "cannot create secondary Android Vulkan surface");
        goto failure;
    }
    if (vkGetPhysicalDeviceSurfaceSupportKHR(
            backend->context.gpu,
            backend->context.presentation_queue_family_index,
            target->surface, &present) != VK_SUCCESS || !present) {
        set_error(error, error_size,
                  "negotiated Vulkan queue cannot present to the secondary display");
        goto failure;
    }
    if (!create_secondary_swapchain(backend, error, error_size)) goto failure;
    return true;

failure:
    destroy_secondary_swapchain(backend);
    if (target->surface)
        vkDestroySurfaceKHR(backend->instance, target->surface, NULL);
    target->surface = VK_NULL_HANDLE;
    ANativeWindow_release(target->window);
    target->window = NULL;
    return false;
}

/* Ideal-lattice source stamp, mirroring lucent_android_gles_backend.c:
 * sequence x 1/stamp_hz on the clock the core is paced at (declared x
 * synchronized/paced multiplier).  A clock change re-bases the timeline
 * continuously from the last stamp.  Every present takes one lattice slot:
 * the render loop is paced per run, so a run without a new core frame is a
 * duplicate on its own slot (the generator classifies it by pixels/ordinal)
 * rather than a stamp collision. */
static bool stamp_core_frame_timestamp(
        lucent_android_vulkan_backend *backend, uint64_t frame_sequence,
        int64_t *stamp_out) {
    double stamp_hz;
    long double offset_ns;
    int64_t timestamp;
    uint64_t sequence;
    lucent_retro_av_info av;
    memset(&av, 0, sizeof(av));
    if (!backend || !backend->host || !stamp_out) return false;
    stamp_hz = lucent_retro_synchronized_video_hz(backend->host);
    if (!isfinite(stamp_hz) || stamp_hz <= 1.0 || stamp_hz >= 1000.0) {
        if (!lucent_retro_get_av_info(backend->host, &av) ||
                !isfinite(av.frames_per_second) ||
                av.frames_per_second <= 1.0 || av.frames_per_second >= 1000.0)
            return false;
        stamp_hz = av.frames_per_second;
    }
    sequence = frame_sequence > backend->timestamp_sequence ?
            frame_sequence : backend->timestamp_sequence + 1u;
    if (!backend->timestamp_timeline_ready ||
            fabs(backend->timestamp_source_hz - stamp_hz) > 1e-9 ||
            sequence < backend->timestamp_base_sequence) {
        struct timespec now;
        int64_t period_ns = (int64_t)llround(1000000000.0 / stamp_hz);
        backend->timestamp_base_sequence = sequence;
        if (backend->timestamp_timeline_ready && backend->timestamp_last_ns > 0) {
            backend->timestamp_base_ns = backend->timestamp_last_ns +
                    (period_ns > 0 ? period_ns : 1);
        } else if (clock_gettime(CLOCK_MONOTONIC, &now) == 0) {
            backend->timestamp_base_ns =
                    (int64_t)now.tv_sec * 1000000000LL + now.tv_nsec;
        } else {
            backend->timestamp_base_ns = 1000000000LL;
        }
        backend->timestamp_source_hz = stamp_hz;
        backend->timestamp_timeline_ready = true;
    }
    offset_ns = (long double)(sequence - backend->timestamp_base_sequence) *
            1000000000.0L / (long double)backend->timestamp_source_hz;
    if (offset_ns < 0.0L || offset_ns > (long double)INT64_MAX -
            (long double)backend->timestamp_base_ns) return false;
    timestamp = backend->timestamp_base_ns + (int64_t)(offset_ns + 0.5L);
    if (timestamp <= backend->timestamp_last_ns)
        timestamp = backend->timestamp_last_ns + 1;
    backend->timestamp_last_ns = timestamp;
    backend->timestamp_sequence = sequence;
    *stamp_out = timestamp;
    return true;
}

/* An acquire semaphore belongs to a rotating CPU slot, not to an image whose
 * index is still unknown. Finish its previous queue wait BEFORE passing it to
 * AcquireNextImage again. Waiting only on the subsequently acquired image's
 * fence is both too late and potentially the wrong submission. */
static bool wait_acquire_slot(VkDevice device, VkFence *pending,
                              char *error, size_t error_size) {
    if (*pending == VK_NULL_HANDLE) return true;
    if (vkWaitForFences(device, 1, pending, VK_TRUE, UINT64_MAX) != VK_SUCCESS) {
        set_error(error, error_size, "cannot recycle Vulkan acquire semaphore");
        return false;
    }
    *pending = VK_NULL_HANDLE;
    return true;
}

bool lucent_android_vulkan_run_and_present(
        lucent_android_vulkan_backend *backend, bool *presented,
        char *error, size_t error_size) {
    VkResult result;
    VkPresentTimesInfoGOOGLE present_times;
    VkPresentTimeGOOGLE present_time[2];
    VkPipelineStageFlags wait_stages[1 + LUCENT_VK_MAX_WAIT_SEMAPHORES];
    VkSemaphore wait_semaphores[1 + LUCENT_VK_MAX_WAIT_SEMAPHORES];
    VkSemaphore signal_semaphores[2];
    VkCommandBuffer submits[1 + LUCENT_VK_MAX_CORE_COMMANDS];
    VkSubmitInfo submit;
    VkSubmitInfo secondary_submit;
    VkPresentInfoKHR present;
    VkSwapchainKHR present_swapchains[2];
    uint32_t present_indices[2];
    VkPipelineStageFlags secondary_wait_stages[2] = {
        VK_PIPELINE_STAGE_TRANSFER_BIT,
        VK_PIPELINE_STAGE_TRANSFER_BIT
    };
    VkSemaphore secondary_waits[2];
    VkCommandBuffer secondary_command;
    lucent_retro_hw_info hw_info;
    uint32_t wait_count;
    uint32_t signal_count = 1;
    uint32_t submit_count = 0;
    uint32_t present_count = 1;
    bool has_secondary;
    if (presented) *presented = false;
    if (!backend || !backend->host || !backend->swapchain ||
            !claim_render_thread(backend, error, error_size)) return false;
    has_secondary = backend->secondary.swapchain != VK_NULL_HANDLE;
    if (!wait_acquire_slot(backend->context.device,
            &backend->acquire_pending[backend->frame_slot], error, error_size))
        return false;
    result = vkAcquireNextImageKHR(backend->context.device, backend->swapchain,
                                   UINT64_MAX,
                                   backend->image_available[backend->frame_slot],
                                   VK_NULL_HANDLE,
                                   &backend->current_index);
    if (result != VK_SUCCESS && result != VK_SUBOPTIMAL_KHR) {
        set_error(error, error_size, "Vulkan surface lost or out of date (%d)",
                  (int)result);
        return false;
    }
    backend->current_acquired = true;
    if (backend->current_index >= backend->image_count) {
        set_error(error, error_size, "Vulkan returned an invalid swapchain index");
        return false;
    }
    if (vkWaitForFences(backend->context.device, 1,
                        &backend->fences[backend->current_index],
                        VK_TRUE, UINT64_MAX) != VK_SUCCESS) {
        set_error(error, error_size, "cannot recycle Vulkan frame fence");
        return false;
    }
    if (has_secondary) {
        lucent_vulkan_secondary_target *target = &backend->secondary;
        if (!wait_acquire_slot(backend->context.device,
                &target->acquire_pending[target->frame_slot], error, error_size))
            return false;
        result = vkAcquireNextImageKHR(
                backend->context.device, target->swapchain, UINT64_MAX,
                target->image_available[target->frame_slot], VK_NULL_HANDLE,
                &target->current_index);
        if ((result != VK_SUCCESS && result != VK_SUBOPTIMAL_KHR) ||
                target->current_index >= target->image_count) {
            set_error(error, error_size,
                      "secondary Vulkan surface lost or out of date (%d)",
                      (int)result);
            return false;
        }
        if (vkWaitForFences(backend->context.device, 1,
                            &target->fences[target->current_index],
                            VK_TRUE, UINT64_MAX) != VK_SUCCESS) {
            set_error(error, error_size,
                      "cannot recycle secondary Vulkan frame fence");
            return false;
        }
    }
    /*
     * Keep the recycled fence signalled while the core records this frame.
     * A Vulkan libretro core may call wait_sync_index() from retro_run() to
     * ensure that the frontend has finished using this sync slot.  Resetting
     * here creates a self-deadlock: wait_sync_index() then waits for the
     * submission that cannot happen until retro_run() returns.  Reset only
     * after the core has returned and immediately before the queue submit that
     * will signal the fence again.
     */
    if (!lucent_retro_run_frame(backend->host, error, error_size) ||
            !lucent_retro_get_hw_info(backend->host, &hw_info) ||
            !record_present_commands(backend, hw_info.frame_width,
                                     hw_info.frame_height,
                                     has_secondary ? LUCENT_SCREEN_TOP :
                                                     LUCENT_SCREEN_FULL,
                                     error, error_size)) return false;
    if (has_secondary) {
        lucent_vulkan_secondary_target *target = &backend->secondary;
        if (!record_present_commands_for_target(
                backend, target->command_buffers[target->current_index],
                target->images[target->current_index],
                target->image_initialized[target->current_index], target->extent,
                hw_info.frame_width, hw_info.frame_height,
                LUCENT_SCREEN_BOTTOM,
                backend->secondary_clockwise_quarter_turn,
                error, error_size)) return false;
    }
    wait_semaphores[0] = backend->image_available[backend->frame_slot];
    wait_stages[0] = VK_PIPELINE_STAGE_TRANSFER_BIT;
    wait_count = 1;
    while (wait_count <= backend->core_wait_count) {
        wait_semaphores[wait_count] =
                backend->core_wait_semaphores[wait_count - 1];
        wait_stages[wait_count] = VK_PIPELINE_STAGE_TRANSFER_BIT;
        wait_count++;
    }
    while (submit_count < backend->core_command_count) {
        submits[submit_count] = backend->core_commands[submit_count];
        submit_count++;
    }
    submits[submit_count++] = backend->command_buffers[backend->current_index];
    /* Presentation completion is NOT covered by a queue-submit fence. Reuse
     * the semaphore associated with the acquired IMAGE: this submit waits on
     * its acquisition, which orders after the previous presentation wait.
     * See Khronos Vulkan Guide, "Swapchain Semaphore Reuse". */
    signal_semaphores[0] = backend->render_finished[backend->current_index];
    if (backend->core_signal_semaphore) {
        signal_semaphores[signal_count++] = backend->core_signal_semaphore;
        backend->core_signal_semaphore = VK_NULL_HANDLE;
    }
    memset(&submit, 0, sizeof(submit));
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.waitSemaphoreCount = wait_count;
    submit.pWaitSemaphores = wait_semaphores;
    submit.pWaitDstStageMask = wait_stages;
    submit.commandBufferCount = submit_count;
    submit.pCommandBuffers = submits;
    submit.signalSemaphoreCount = signal_count;
    submit.pSignalSemaphores = signal_semaphores;
    memset(&secondary_submit, 0, sizeof(secondary_submit));
    if (has_secondary) {
        lucent_vulkan_secondary_target *target = &backend->secondary;
        secondary_waits[0] = target->image_available[target->frame_slot];
        secondary_waits[1] = backend->render_finished[backend->current_index];
        secondary_command = target->command_buffers[target->current_index];
        secondary_submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        secondary_submit.waitSemaphoreCount = 2;
        secondary_submit.pWaitSemaphores = secondary_waits;
        secondary_submit.pWaitDstStageMask = secondary_wait_stages;
        secondary_submit.commandBufferCount = 1;
        secondary_submit.pCommandBuffers = &secondary_command;
        secondary_submit.signalSemaphoreCount = 1;
        secondary_submit.pSignalSemaphores =
                &target->render_finished[target->current_index];
    }
    memset(&present, 0, sizeof(present));
    present.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
    present.waitSemaphoreCount = 1;
    present_swapchains[0] = backend->swapchain;
    present_indices[0] = backend->current_index;
    if (has_secondary) {
        lucent_vulkan_secondary_target *target = &backend->secondary;
        present.pWaitSemaphores = &target->render_finished[target->current_index];
        present_swapchains[1] = target->swapchain;
        present_indices[1] = target->current_index;
        present_count = 2;
    } else {
        present.pWaitSemaphores = &backend->render_finished[backend->current_index];
    }
    present.swapchainCount = present_count;
    present.pSwapchains = present_swapchains;
    present.pImageIndices = present_indices;
    const bool tag_primary = backend->fg_timestamp_enabled[0];
    const bool tag_secondary = has_secondary && backend->fg_timestamp_enabled[1];
    if ((tag_primary || tag_secondary) && backend->display_timing_enabled) {
        int64_t stamp = 0;
        if (stamp_core_frame_timestamp(backend, hw_info.frame_sequence,
                                       &stamp)) {
            memset(&present_times, 0, sizeof(present_times));
            memset(present_time, 0, sizeof(present_time));
            if (tag_primary) {
                present_time[0].presentID = (uint32_t)backend->timestamp_sequence;
                present_time[0].desiredPresentTime = (uint64_t)stamp;
            }
            if (tag_secondary) {
                present_time[1].presentID = (uint32_t)backend->timestamp_sequence;
                present_time[1].desiredPresentTime = (uint64_t)stamp;
            }
            present_times.sType = VK_STRUCTURE_TYPE_PRESENT_TIMES_INFO_GOOGLE;
            present_times.swapchainCount = present_count;
            present_times.pTimes = present_time;
            present_times.pNext = present.pNext;
            present.pNext = &present_times;
        }
        if (!backend->display_timing_logged) {
            backend->display_timing_logged = true;
            __android_log_print(ANDROID_LOG_INFO, "LucentVulkanBackend",
                    "immutable source timestamps via %s stampHz=%.6f "
                    "firstStampNs=%lld",
                    VK_GOOGLE_DISPLAY_TIMING_EXTENSION_NAME,
                    backend->timestamp_source_hz, (long long)stamp);
        }
    } else if ((tag_primary || tag_secondary) && !backend->display_timing_logged) {
        backend->display_timing_logged = true;
        __android_log_print(ANDROID_LOG_WARN, "LucentVulkanBackend",
                "immutable source timestamps unavailable: %s not enabled",
                VK_GOOGLE_DISPLAY_TIMING_EXTENSION_NAME);
    } else if (!backend->display_timing_logged) {
        backend->display_timing_logged = true;
        __android_log_print(ANDROID_LOG_INFO, "LucentVulkanBackend",
                "Direct presentation: FG source timestamp processing bypassed");
    }
    queue_lock(backend);
    result = vkResetFences(backend->context.device, 1,
                           &backend->fences[backend->current_index]);
    if (result == VK_SUCCESS)
        result = vkQueueSubmit(backend->context.queue, 1, &submit,
                               backend->fences[backend->current_index]);
    if (result == VK_SUCCESS)
        backend->acquire_pending[backend->frame_slot] =
                backend->fences[backend->current_index];
    if (result == VK_SUCCESS && has_secondary) {
        lucent_vulkan_secondary_target *target = &backend->secondary;
        result = vkResetFences(backend->context.device, 1,
                               &target->fences[target->current_index]);
        if (result == VK_SUCCESS)
            result = vkQueueSubmit(backend->context.queue, 1, &secondary_submit,
                                   target->fences[target->current_index]);
        if (result == VK_SUCCESS)
            target->acquire_pending[target->frame_slot] =
                    target->fences[target->current_index];
    }
    if (result == VK_SUCCESS)
        result = vkQueuePresentKHR(backend->context.presentation_queue, &present);
    if (result == VK_SUCCESS || result == VK_SUBOPTIMAL_KHR)
        backend->frame_slot = (backend->frame_slot + 1u) % backend->image_count;
    if ((result == VK_SUCCESS || result == VK_SUBOPTIMAL_KHR) && has_secondary)
        backend->secondary.frame_slot = (backend->secondary.frame_slot + 1u) %
                backend->secondary.image_count;
    queue_unlock(backend);
    backend->core_wait_count = 0;
    backend->core_command_count = 0;
    backend->current_acquired = false;
    if (result != VK_SUCCESS && result != VK_SUBOPTIMAL_KHR) {
        set_error(error, error_size, "Vulkan presentation failed (%d)",
                  (int)result);
        return false;
    }
    backend->image_initialized[backend->current_index] = true;
    if (has_secondary)
        backend->secondary.image_initialized[
                backend->secondary.current_index] = true;
    backend->presented_sequence++;
    if (presented) *presented = true;
    return true;
}

bool lucent_android_vulkan_detach_secondary(
        lucent_android_vulkan_backend *backend,
        char *error, size_t error_size) {
    lucent_vulkan_secondary_target *target;
    if (!backend || !claim_render_thread(backend, error, error_size)) return false;
    target = &backend->secondary;
    if (!target->window) return true;
    if (backend->context.device) vkDeviceWaitIdle(backend->context.device);
    destroy_secondary_swapchain(backend);
    if (target->surface)
        vkDestroySurfaceKHR(backend->instance, target->surface, NULL);
    target->surface = VK_NULL_HANDLE;
    ANativeWindow_release(target->window);
    target->window = NULL;
    return true;
}

bool lucent_android_vulkan_detach(
        lucent_android_vulkan_backend *backend,
        char *error, size_t error_size) {
    if (!backend || !claim_render_thread(backend, error, error_size)) return false;
    if (!backend->window) return true;
    if (backend->context.device) vkDeviceWaitIdle(backend->context.device);
    if (!lucent_android_vulkan_detach_secondary(backend, error, error_size))
        return false;
    destroy_swapchain(backend);
    if (backend->surface)
        vkDestroySurfaceKHR(backend->instance, backend->surface, NULL);
    ANativeWindow_release(backend->window);
    backend->window = NULL;
    backend->surface = VK_NULL_HANDLE;
    backend->has_core_image = false;
    return true;
}

bool lucent_android_vulkan_get_info(
        const lucent_android_vulkan_backend *backend,
        lucent_android_vulkan_info *info) {
    if (!backend || !info) return false;
    memset(info, 0, sizeof(*info));
    info->surface_attached = backend->window != NULL;
    info->width = backend->extent.width;
    info->height = backend->extent.height;
    info->swapchain_images = backend->image_count;
    info->presented_sequence = backend->presented_sequence;
    return true;
}

void lucent_android_vulkan_destroy(lucent_android_vulkan_backend *backend) {
    lucent_retro_hw_info info;
    if (!backend) return;
    if (backend->window) lucent_android_vulkan_detach(backend, NULL, 0);
    if (backend->host && lucent_retro_get_hw_info(backend->host, &info) &&
            info.context_ready)
        lucent_retro_hw_context_destroy(backend->host, NULL, 0);
    if (backend->context.device) vkDeviceWaitIdle(backend->context.device);
    if (backend->negotiation && backend->negotiation->destroy_device)
        backend->negotiation->destroy_device();
    if (backend->context.device)
        vkDestroyDevice(backend->context.device, NULL);
    if (backend->instance)
        vkDestroyInstance(backend->instance, NULL);
    if (backend->queue_mutex_ready)
        pthread_mutex_destroy(&backend->queue_mutex);
    free(backend);
}
