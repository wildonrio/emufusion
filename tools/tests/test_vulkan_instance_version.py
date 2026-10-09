"""Execute the actual instance-creation function against a recording Vulkan API."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "unified-android/native/lucent_android_vulkan_backend.c"


def harness(source):
    body = source.split("static bool create_instance_and_surface(", 1)[1]
    body = "static bool create_instance_and_surface(" + body.split(
        "static bool create_surface_only(", 1)[0]
    return r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define VK_API_VERSION_1_0 (1u << 22)
#define VK_API_VERSION_1_1 (VK_API_VERSION_1_0 | (1u << 12))
#define VK_API_VERSION_1_2 (VK_API_VERSION_1_0 | (2u << 12))
#define VK_STRUCTURE_TYPE_APPLICATION_INFO 0
#define VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO 1
#define VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR 2
#define VK_KHR_SURFACE_EXTENSION_NAME "VK_KHR_surface"
#define VK_KHR_ANDROID_SURFACE_EXTENSION_NAME "VK_KHR_android_surface"
#define VK_SUCCESS 0
typedef struct {
    int sType; const void *pNext; const char *pApplicationName;
    uint32_t applicationVersion; const char *pEngineName;
    uint32_t engineVersion, apiVersion;
} VkApplicationInfo;
typedef struct {
    int sType; const void *pNext; uint32_t flags;
    const VkApplicationInfo *pApplicationInfo;
    uint32_t enabledLayerCount; const char *const *ppEnabledLayerNames;
    uint32_t enabledExtensionCount; const char *const *ppEnabledExtensionNames;
} VkInstanceCreateInfo;
typedef struct { int sType; const void *pNext; uint32_t flags; void *window; }
    VkAndroidSurfaceCreateInfoKHR;
typedef struct { const VkApplicationInfo *(*get_application_info)(void); } Negotiation;
typedef struct { Negotiation *negotiation; void *window; int instance, surface; }
    lucent_android_vulkan_backend;
static VkApplicationInfo recorded, requested;
static int create_result, surface_calls;
static bool null_request;
static const VkApplicationInfo *get_app(void) {
    return null_request ? NULL : &requested;
}
static void set_error(char *error, size_t size, const char *message) {
    if (size) { strncpy(error, message, size - 1); error[size - 1] = 0; }
}
static int vkCreateInstance(const VkInstanceCreateInfo *info, const void *allocator,
                            int *instance) {
    assert(!allocator && info->enabledExtensionCount == 2);
    recorded = *info->pApplicationInfo; *instance = 123;
    return create_result;
}
static int vkCreateAndroidSurfaceKHR(int instance,
        const VkAndroidSurfaceCreateInfoKHR *info, const void *allocator, int *surface) {
    assert(instance == 123 && !allocator && info->window == (void *)42);
    ++surface_calls; *surface = 456; return VK_SUCCESS;
}
''' + body + r'''
int main(void) {
    Negotiation negotiation = { get_app };
    lucent_android_vulkan_backend backend = { NULL, (void *)42, 0, 0 };
    char error[128] = {0};
    assert(create_instance_and_surface(&backend, error, sizeof(error)));
    assert(recorded.apiVersion == VK_API_VERSION_1_1);
    backend.negotiation = &negotiation;
    null_request = true;
    assert(create_instance_and_surface(&backend, error, sizeof(error)));
    assert(recorded.apiVersion == VK_API_VERSION_1_1);
    null_request = false;
    uint32_t versions[] = {0, VK_API_VERSION_1_0, VK_API_VERSION_1_1, VK_API_VERSION_1_2};
    for (unsigned i = 0; i < sizeof(versions)/sizeof(versions[0]); ++i) {
        requested = (VkApplicationInfo){0, (void *)99, "Core", 5, "Engine", 2, versions[i]};
        VkApplicationInfo before = requested;
        assert(create_instance_and_surface(&backend, error, sizeof(error)));
        assert(recorded.apiVersion == (versions[i] < VK_API_VERSION_1_1 ?
                                      VK_API_VERSION_1_1 : versions[i]));
        assert(recorded.pNext == before.pNext);
        assert(recorded.pApplicationName == before.pApplicationName);
        assert(recorded.applicationVersion == before.applicationVersion);
        assert(recorded.pEngineName == before.pEngineName);
        assert(recorded.engineVersion == before.engineVersion);
        assert(memcmp(&requested, &before, sizeof(before)) == 0);
    }
    create_result = -9;
    int previous_surfaces = surface_calls;
    assert(!create_instance_and_surface(&backend, error, sizeof(error)));
    assert(surface_calls == previous_surfaces);
    assert(strstr(error, "cannot create Android Vulkan instance"));
}
'''


class VulkanInstanceVersionTest(unittest.TestCase):
    def test_core_cannot_lower_frontend_floor_or_lose_its_higher_requirement(self):
        with tempfile.TemporaryDirectory(prefix="vulkan-instance-version-") as folder:
            c = Path(folder) / "test.c"
            binary = Path(folder) / "test"
            c.write_text(harness(SOURCE.read_text()))
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", str(c), "-o", str(binary)],
                           check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=15)


if __name__ == "__main__":
    unittest.main()
