#include "../include/libretro.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifndef LUCENT_MOCK_HW_VULKAN
#define LUCENT_MOCK_HW_VULKAN 0
#endif
#ifndef LUCENT_MOCK_ANDROID_GLES
#define LUCENT_MOCK_ANDROID_GLES 0
#endif
#ifndef LUCENT_MOCK_MUPEN_GLES
#define LUCENT_MOCK_MUPEN_GLES 0
#endif
#ifndef LUCENT_MOCK_ARMSX2
#define LUCENT_MOCK_ARMSX2 0
#endif

/* The deliberately small host-test libretro header does not carry the full
 * optional descriptor definition.  This is its ABI shape and, importantly,
 * begins with integers rather than pointer fields. */
struct lucent_mock_input_descriptor {
    unsigned port;
    unsigned device;
    unsigned index;
    unsigned id;
    const char *description;
};

static retro_environment_t environment;
static retro_video_refresh_t video;
static retro_audio_sample_t audio;
static retro_audio_sample_batch_t audio_batch;
static retro_input_poll_t input_poll;
static retro_input_state_t input_state;
static unsigned video_width = 4;
static unsigned video_height = 4;
void lucent_hw_mock_set_video_size(unsigned width, unsigned height) {
    video_width = width;
    video_height = height;
}
void lucent_hw_mock_set_geometry(unsigned width, unsigned height) {
    struct retro_game_geometry geometry = {width, height, width, height,
            height ? (float)width / height : 0.0f};
    environment(RETRO_ENVIRONMENT_SET_GEOMETRY, &geometry);
}
void lucent_hw_mock_set_render_capacity(unsigned width, unsigned height,
                                        unsigned max_width, unsigned max_height) {
    struct retro_system_av_info info = {
        {width, height, max_width, max_height,
         height ? (float)width / height : 0.0f},
        {60.0, 48000.0}
    };
    environment(RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO, &info);
}
static struct retro_hw_render_callback hardware;
static const struct retro_hw_render_interface *render_interface;
static uint32_t counter;
static uint32_t run_count;
static uint8_t save_ram[8];
static unsigned reset_count;
static unsigned destroy_count;
static unsigned state_call_count;
static unsigned game_reset_count;
static unsigned port_device_count;
static unsigned last_port;
static unsigned last_device;
static bool preferred_ok;
static bool interface_ok;
static bool shared_ok;
static bool backend_hooks_ok;
static bool variable_default_ok;
static unsigned supplied_frontend_framebuffer;

static void context_reset(void) {
    reset_count++;
#if LUCENT_MOCK_HW_VULKAN
    backend_hooks_ok = render_interface &&
            render_interface->interface_type == RETRO_HW_RENDER_INTERFACE_VULKAN &&
            render_interface->interface_version == 1;
#else
    backend_hooks_ok = hardware.get_current_framebuffer &&
#if LUCENT_MOCK_ANDROID_GLES
            hardware.get_current_framebuffer() != 0 &&
#else
            hardware.get_current_framebuffer() == (uintptr_t)0x1234u &&
#endif
            hardware.get_proc_address &&
            hardware.get_proc_address("lucent_mock_symbol") != NULL;
#endif
}

static void context_destroy(void) { destroy_count++; }

unsigned lucent_hw_mock_reset_count(void) { return reset_count; }
unsigned lucent_hw_mock_destroy_count(void) { return destroy_count; }
unsigned lucent_hw_mock_state_call_count(void) { return state_call_count; }
unsigned lucent_hw_mock_game_reset_count(void) { return game_reset_count; }
unsigned lucent_hw_mock_port_device_count(void) { return port_device_count; }
unsigned lucent_hw_mock_last_port(void) { return last_port; }
unsigned lucent_hw_mock_last_device(void) { return last_device; }
bool lucent_hw_mock_preferred_ok(void) { return preferred_ok; }
bool lucent_hw_mock_interface_ok(void) { return interface_ok; }
bool lucent_hw_mock_shared_ok(void) { return shared_ok; }
bool lucent_hw_mock_backend_hooks_ok(void) { return backend_hooks_ok; }
bool lucent_hw_mock_variable_default_ok(void) { return variable_default_ok; }
bool retro_lucent_mupen_current_run_has_vi_origin_change(void) {
    return LUCENT_MOCK_MUPEN_GLES && run_count != 0u && run_count % 3u == 0u;
}
int16_t lucent_hw_mock_pointer_state(unsigned id) {
    return input_state ? input_state(0, RETRO_DEVICE_POINTER, 0, id) : 0;
}
unsigned lucent_hw_mock_frontend_framebuffer(void) {
    return supplied_frontend_framebuffer;
}
void lucent_set_frontend_framebuffer(unsigned framebuffer) {
    supplied_frontend_framebuffer = framebuffer;
}

static uint32_t *mock_active_rect;
void lucent_hw_mock_set_active_rect(const uint32_t *rect) {
    if (mock_active_rect) memcpy(mock_active_rect, rect, 7u * sizeof(uint32_t));
}
bool retro_lucent_get_hw_active_rect(uint32_t *rect, unsigned count) {
    if (!rect || count != 7u || !mock_active_rect || !mock_active_rect[0]) return false;
    memcpy(rect, mock_active_rect, 7u * sizeof(uint32_t));
    return true;
}
void retro_init(void) { mock_active_rect = calloc(7u, sizeof(uint32_t)); }
void retro_deinit(void) { free(mock_active_rect); mock_active_rect = NULL; }
unsigned retro_api_version(void) { return RETRO_API_VERSION; }
void retro_get_system_info(struct retro_system_info *info) {
    memset(info, 0, sizeof(*info));
    info->library_name = LUCENT_MOCK_HW_VULKAN
            ? "Lucent Vulkan Mock Core" : LUCENT_MOCK_MUPEN_GLES
            ? "Lucent Mupen GLES Mock Core" : "Lucent GLES Mock Core";
    info->library_version = "1";
    info->valid_extensions = "mock";
    info->need_fullpath = false;
}
void retro_get_system_av_info(struct retro_system_av_info *info) {
    memset(info, 0, sizeof(*info));
    info->geometry.base_width = 4;
    info->geometry.base_height = 4;
    info->geometry.max_width = 4;
    info->geometry.max_height = 4;
    info->timing.fps = 60.0;
    info->timing.sample_rate = 48000.0;
}
void retro_set_environment(retro_environment_t callback) {
    environment = callback;
#if LUCENT_MOCK_ANDROID_GLES || LUCENT_MOCK_MUPEN_GLES
    if (environment) {
        const struct lucent_mock_input_descriptor descriptors[] = {
            { 0, RETRO_DEVICE_JOYPAD, 0, 6,
              "D-Pad Left" },
            { 0 },
        };
        unsigned performance_level = 12;
        struct retro_log_callback logger = { NULL };
        struct retro_variable definitions[] = {
            { "lucent_hw_test", "Lucent hardware test; preferred|other" },
            { "ppsspp_internal_resolution",
              "Rendering Resolution; 480x272|960x544|1920x1088" },
            { "ppsspp_cropto16x9", "Crop to 16x9; disabled|enabled" },
            { "reicast_internal_resolution",
              "Internal Resolution; 640x480|1280x960|1440x1080" },
            { "mupen64plus-EnableOverscan",
              "Overscan; Disabled|Enabled" },
            { "mupen64plus-OverscanTop",
              "Overscan Offset (Top); 0|8|12|18|22" },
            { "mupen64plus-OverscanBottom",
              "Overscan Offset (Bottom); 0|8|12|18|22" },
            { "dolphin_ir_mode",
              "Wiimote IR Mode; 0|1|2" },
            { "armsx2_blending_accuracy",
              "Blending Accuracy; Minimum|Basic|Medium|High|Full|Maximum" },
            { NULL, NULL },
        };
        struct retro_variable current = { "lucent_hw_test", NULL };
        struct retro_variable resolution = {
            "ppsspp_internal_resolution", NULL
        };
        struct retro_variable crop = { "ppsspp_cropto16x9", NULL };
        struct retro_variable dreamcast_resolution = {
            "reicast_internal_resolution", NULL
        };
        struct retro_variable n64_overscan = {
            "mupen64plus-EnableOverscan", NULL
        };
        struct retro_variable n64_overscan_top = {
            "mupen64plus-OverscanTop", NULL
        };
        struct retro_variable n64_overscan_bottom = {
            "mupen64plus-OverscanBottom", NULL
        };
        struct retro_variable dolphin_ir_mode = { "dolphin_ir_mode", NULL };
        struct retro_variable armsx2_blending = {
            "armsx2_blending_accuracy", NULL
        };
        variable_default_ok = environment(RETRO_ENVIRONMENT_GET_LOG_INTERFACE,
                                          &logger) && logger.log != NULL;
        if (variable_default_ok)
            logger.log(RETRO_LOG_DEBUG, "Lucent mock core initialized: %d\n", 1);
        variable_default_ok = variable_default_ok && environment(
                    RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS,
                    (void *)descriptors) &&
                environment(RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL,
                            &performance_level) &&
                environment(RETRO_ENVIRONMENT_SET_VARIABLES,
                                          definitions) &&
                environment(RETRO_ENVIRONMENT_GET_VARIABLE, &current) &&
                current.value && strcmp(current.value, "preferred") == 0 &&
                environment(RETRO_ENVIRONMENT_GET_VARIABLE, &resolution) &&
                resolution.value && strcmp(resolution.value, "480x272") == 0 &&
                environment(RETRO_ENVIRONMENT_GET_VARIABLE, &crop) &&
                crop.value && strcmp(crop.value, "disabled") == 0 &&
                environment(RETRO_ENVIRONMENT_GET_VARIABLE,
                            &dreamcast_resolution) &&
                dreamcast_resolution.value &&
                strcmp(dreamcast_resolution.value, "640x480") == 0 &&
                environment(RETRO_ENVIRONMENT_GET_VARIABLE, &n64_overscan) &&
                n64_overscan.value &&
                strcmp(n64_overscan.value, "Disabled") == 0 &&
                environment(RETRO_ENVIRONMENT_GET_VARIABLE,
                            &n64_overscan_top) &&
                n64_overscan_top.value &&
                strcmp(n64_overscan_top.value, "0") == 0 &&
                environment(RETRO_ENVIRONMENT_GET_VARIABLE,
                            &n64_overscan_bottom) &&
                n64_overscan_bottom.value &&
                strcmp(n64_overscan_bottom.value, "0") == 0 &&
                environment(RETRO_ENVIRONMENT_GET_VARIABLE,
                            &dolphin_ir_mode) &&
                dolphin_ir_mode.value && strcmp(dolphin_ir_mode.value, "2") == 0 &&
                environment(RETRO_ENVIRONMENT_GET_VARIABLE,
                            &armsx2_blending) &&
                armsx2_blending.value && strcmp(armsx2_blending.value,
#if LUCENT_MOCK_ARMSX2
                                                "Full"
#else
                                                "Minimum"
#endif
                                                ) == 0;
    }
#endif
}
void retro_set_video_refresh(retro_video_refresh_t callback) { video = callback; }
void retro_set_audio_sample(retro_audio_sample_t callback) { audio = callback; }
void retro_set_audio_sample_batch(retro_audio_sample_batch_t callback) {
    audio_batch = callback;
}
void retro_set_input_poll(retro_input_poll_t callback) { input_poll = callback; }
void retro_set_input_state(retro_input_state_t callback) { input_state = callback; }
void retro_set_controller_port_device(unsigned port, unsigned device) {
    port_device_count++;
    last_port = port;
    last_device = device;
}
void retro_reset(void) {
    game_reset_count++;
    counter = 0;
    run_count = 0;
}
void retro_run(void) {
    int16_t samples[2] = {0, 0};
    counter++;
    run_count++;
    if (input_poll) input_poll();
    if (input_state) (void)input_state(0, RETRO_DEVICE_JOYPAD, 0, 0);
    if (video) video(RETRO_HW_FRAME_BUFFER_VALID, video_width, video_height, 0);
    if (audio) audio(0, 0);
    if (audio_batch) audio_batch(samples, 1);
}
size_t retro_serialize_size(void) {
    state_call_count++;
    return sizeof(counter);
}
bool retro_serialize(void *data, size_t size) {
    state_call_count++;
    if (!data || size != sizeof(counter)) return false;
    memcpy(data, &counter, size);
    return true;
}
bool retro_unserialize(const void *data, size_t size) {
    state_call_count++;
    if (!data || size != sizeof(counter)) return false;
    memcpy(&counter, data, size);
    return true;
}
void retro_cheat_reset(void) {}
void retro_cheat_set(unsigned index, bool enabled, const char *code) {
    (void)index;
    (void)enabled;
    (void)code;
}
bool retro_load_game(const struct retro_game_info *game) {
    enum retro_hw_context_type preferred = RETRO_HW_CONTEXT_NONE;
    if (!game || !game->data || !game->size || !environment) return false;
    memset(&hardware, 0, sizeof(hardware));
#if LUCENT_MOCK_HW_VULKAN
    hardware.context_type = RETRO_HW_CONTEXT_VULKAN;
#else
#if LUCENT_MOCK_MUPEN_GLES
    /* Exact GLideN64 negotiation shape in pinned Mupen64Plus-Next:
     * GLES3, depth, no stencil/debug/shared context, cache_context. */
    hardware.context_type = RETRO_HW_CONTEXT_OPENGLES3;
    hardware.depth = true;
    hardware.cache_context = true;
#elif LUCENT_MOCK_ANDROID_GLES
    hardware.context_type = RETRO_HW_CONTEXT_OPENGLES_VERSION;
    hardware.version_major = 3;
    hardware.version_minor = 1;
#else
    hardware.context_type = RETRO_HW_CONTEXT_OPENGLES3;
    hardware.depth = true;
    hardware.stencil = true;
    hardware.bottom_left_origin = true;
    hardware.cache_context = true;
    hardware.debug_context = true;
#endif
#endif
    hardware.context_reset = context_reset;
    hardware.context_destroy = context_destroy;
    preferred_ok = environment(RETRO_ENVIRONMENT_GET_PREFERRED_HW_RENDER, &preferred) &&
            preferred == hardware.context_type;
    shared_ok =
#if LUCENT_MOCK_ANDROID_GLES || LUCENT_MOCK_MUPEN_GLES
            true;
#else
            environment(RETRO_ENVIRONMENT_SET_HW_SHARED_CONTEXT, NULL);
#endif
    if (!preferred_ok || !shared_ok ||
            !environment(RETRO_ENVIRONMENT_SET_HW_RENDER, &hardware)) return false;
#if LUCENT_MOCK_HW_VULKAN
    interface_ok = environment(RETRO_ENVIRONMENT_GET_HW_RENDER_INTERFACE,
                               &render_interface) && render_interface &&
            render_interface->interface_type == RETRO_HW_RENDER_INTERFACE_VULKAN &&
            render_interface->interface_version == 1;
    if (!interface_ok) return false;
#else
    interface_ok = !environment(RETRO_ENVIRONMENT_GET_HW_RENDER_INTERFACE,
                                &render_interface);
#endif
    counter = ((const uint8_t *)game->data)[0];
    run_count = 0;
    return interface_ok;
}
bool retro_load_game_special(unsigned type, const struct retro_game_info *games,
                             size_t count) {
    (void)type;
    (void)games;
    (void)count;
    return false;
}
void retro_unload_game(void) {}
unsigned retro_get_region(void) { return 0; }
void *retro_get_memory_data(unsigned id) {
    return id == RETRO_MEMORY_SAVE_RAM ? save_ram : NULL;
}
size_t retro_get_memory_size(unsigned id) {
    return id == RETRO_MEMORY_SAVE_RAM ? sizeof(save_ram) : 0;
}
