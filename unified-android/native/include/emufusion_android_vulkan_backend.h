#ifndef EMUFUSION_ANDROID_VULKAN_BACKEND_H
#define EMUFUSION_ANDROID_VULKAN_BACKEND_H

#include "emufusion_libretro_host.h"

#include <android/native_window.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct emufusion_android_vulkan_backend emufusion_android_vulkan_backend;

typedef struct emufusion_android_vulkan_info {
    bool surface_attached;
    unsigned width;
    unsigned height;
    unsigned swapchain_images;
    uint64_t presented_sequence;
} emufusion_android_vulkan_info;

emufusion_android_vulkan_backend *emufusion_android_vulkan_create(
        char *error, size_t error_size);
/* Render-owner configuration. Defaults Off; rebinds start a fresh FG timeline. */
bool emufusion_android_vulkan_set_fg_timestamp(
        emufusion_android_vulkan_backend *backend, bool secondary, bool enabled,
        char *error, size_t error_size);
bool emufusion_android_vulkan_set_presentation_aspect(
        emufusion_android_vulkan_backend *backend, float aspect,
        char *error, size_t error_size);
bool emufusion_android_vulkan_set_secondary_rotation(
        emufusion_android_vulkan_backend *backend, unsigned clockwise_degrees,
        char *error, size_t error_size);
bool emufusion_android_vulkan_get_host_options(
        emufusion_android_vulkan_backend *backend,
        emufusion_retro_hw_options *options,
        char *error, size_t error_size);
bool emufusion_android_vulkan_attach(
        emufusion_android_vulkan_backend *backend, emufusion_retro_host *host,
        ANativeWindow *window, char *error, size_t error_size);
bool emufusion_android_vulkan_attach_secondary(
        emufusion_android_vulkan_backend *backend, ANativeWindow *window,
        char *error, size_t error_size);
bool emufusion_android_vulkan_run_and_present(
        emufusion_android_vulkan_backend *backend, bool *presented,
        char *error, size_t error_size);
bool emufusion_android_vulkan_detach(
        emufusion_android_vulkan_backend *backend,
        char *error, size_t error_size);
bool emufusion_android_vulkan_detach_secondary(
        emufusion_android_vulkan_backend *backend,
        char *error, size_t error_size);
bool emufusion_android_vulkan_get_info(
        const emufusion_android_vulkan_backend *backend,
        emufusion_android_vulkan_info *info);
void emufusion_android_vulkan_destroy(emufusion_android_vulkan_backend *backend);

#endif
