#ifndef LUCENT_ANDROID_VULKAN_BACKEND_H
#define LUCENT_ANDROID_VULKAN_BACKEND_H

#include "lucent_libretro_host.h"

#include <android/native_window.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct lucent_android_vulkan_backend lucent_android_vulkan_backend;

typedef struct lucent_android_vulkan_info {
    bool surface_attached;
    unsigned width;
    unsigned height;
    unsigned swapchain_images;
    uint64_t presented_sequence;
} lucent_android_vulkan_info;

lucent_android_vulkan_backend *lucent_android_vulkan_create(
        char *error, size_t error_size);
/* Render-owner configuration. Defaults Off; rebinds start a fresh FG timeline. */
bool lucent_android_vulkan_set_fg_timestamp(
        lucent_android_vulkan_backend *backend, bool secondary, bool enabled,
        char *error, size_t error_size);
bool lucent_android_vulkan_set_presentation_aspect(
        lucent_android_vulkan_backend *backend, float aspect,
        char *error, size_t error_size);
bool lucent_android_vulkan_set_secondary_rotation(
        lucent_android_vulkan_backend *backend, unsigned clockwise_degrees,
        char *error, size_t error_size);
bool lucent_android_vulkan_get_host_options(
        lucent_android_vulkan_backend *backend,
        lucent_retro_hw_options *options,
        char *error, size_t error_size);
bool lucent_android_vulkan_attach(
        lucent_android_vulkan_backend *backend, lucent_retro_host *host,
        ANativeWindow *window, char *error, size_t error_size);
bool lucent_android_vulkan_attach_secondary(
        lucent_android_vulkan_backend *backend, ANativeWindow *window,
        char *error, size_t error_size);
bool lucent_android_vulkan_run_and_present(
        lucent_android_vulkan_backend *backend, bool *presented,
        char *error, size_t error_size);
bool lucent_android_vulkan_detach(
        lucent_android_vulkan_backend *backend,
        char *error, size_t error_size);
bool lucent_android_vulkan_detach_secondary(
        lucent_android_vulkan_backend *backend,
        char *error, size_t error_size);
bool lucent_android_vulkan_get_info(
        const lucent_android_vulkan_backend *backend,
        lucent_android_vulkan_info *info);
void lucent_android_vulkan_destroy(lucent_android_vulkan_backend *backend);

#endif
