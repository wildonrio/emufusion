/*
 * Minimal ABI-complete declarations used by Lucent's independent libretro
 * frontend. The libretro API is MIT licensed. Canonical upstream header:
 * https://github.com/libretro/RetroArch/blob/master/libretro-common/include/libretro.h
 *
 * Lucent implements the environment commands needed by its software cores and
 * its fail-closed Phase 2 hardware-negotiation boundary. Keeping these ABI
 * declarations local does not import RetroArch or any RetroArch frontend code.
 */
#ifndef LUCENT_LIBRETRO_H
#define LUCENT_LIBRETRO_H

#include <stdbool.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define RETRO_API_VERSION 1
#define RETRO_DEVICE_JOYPAD 1
#define RETRO_DEVICE_ANALOG 5
#define RETRO_DEVICE_POINTER 6
#define RETRO_DEVICE_ID_JOYPAD_START 3
#define RETRO_DEVICE_ID_JOYPAD_A 8
#define RETRO_DEVICE_ID_JOYPAD_R3 15
#define RETRO_DEVICE_ID_JOYPAD_MASK 256
#define RETRO_DEVICE_INDEX_ANALOG_LEFT 0
#define RETRO_DEVICE_INDEX_ANALOG_RIGHT 1
#define RETRO_DEVICE_INDEX_ANALOG_BUTTON 2
#define RETRO_DEVICE_ID_ANALOG_X 0
#define RETRO_DEVICE_ID_ANALOG_Y 1
#define RETRO_DEVICE_ID_POINTER_X 0
#define RETRO_DEVICE_ID_POINTER_Y 1
#define RETRO_DEVICE_ID_POINTER_PRESSED 2
#define RETRO_MEMORY_SAVE_RAM 0
#define RETRO_HW_FRAME_BUFFER_VALID ((void *)-1)
#define RETRO_ENVIRONMENT_EXPERIMENTAL 0x10000

enum retro_pixel_format {
    RETRO_PIXEL_FORMAT_0RGB1555 = 0,
    RETRO_PIXEL_FORMAT_XRGB8888 = 1,
    RETRO_PIXEL_FORMAT_RGB565 = 2
};

enum retro_environment_command {
    RETRO_ENVIRONMENT_GET_OVERSCAN = 2,
    RETRO_ENVIRONMENT_GET_CAN_DUPE = 3,
    RETRO_ENVIRONMENT_SET_MESSAGE = 6,
    RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL = 8,
    RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY = 9,
    RETRO_ENVIRONMENT_SET_PIXEL_FORMAT = 10,
    RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS = 11,
    RETRO_ENVIRONMENT_SET_KEYBOARD_CALLBACK = 12,
    RETRO_ENVIRONMENT_SET_DISK_CONTROL_INTERFACE = 13,
    RETRO_ENVIRONMENT_SET_HW_RENDER = 14,
    RETRO_ENVIRONMENT_GET_VARIABLE = 15,
    RETRO_ENVIRONMENT_SET_VARIABLES = 16,
    RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE = 17,
    RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME = 18,
    RETRO_ENVIRONMENT_GET_LIBRETRO_PATH = 19,
    RETRO_ENVIRONMENT_SET_FRAME_TIME_CALLBACK = 21,
    RETRO_ENVIRONMENT_SET_AUDIO_CALLBACK = 22,
    RETRO_ENVIRONMENT_GET_RUMBLE_INTERFACE = 23,
    RETRO_ENVIRONMENT_GET_INPUT_DEVICE_CAPABILITIES = 24,
    RETRO_ENVIRONMENT_GET_LOG_INTERFACE = 27,
    RETRO_ENVIRONMENT_GET_PERF_INTERFACE = 28,
    RETRO_ENVIRONMENT_GET_LOCATION_INTERFACE = 29,
    RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY = 30,
    RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY = 31,
    RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO = 32,
    RETRO_ENVIRONMENT_SET_SUBSYSTEM_INFO = 34,
    RETRO_ENVIRONMENT_SET_CONTROLLER_INFO = 35,
    RETRO_ENVIRONMENT_SET_MEMORY_MAPS = 36,
    RETRO_ENVIRONMENT_SET_GEOMETRY = 37,
    RETRO_ENVIRONMENT_GET_USERNAME = 38,
    RETRO_ENVIRONMENT_GET_LANGUAGE = 39,
    RETRO_ENVIRONMENT_GET_CURRENT_SOFTWARE_FRAMEBUFFER = 40,
    RETRO_ENVIRONMENT_GET_HW_RENDER_INTERFACE =
            (41 | RETRO_ENVIRONMENT_EXPERIMENTAL),
    RETRO_ENVIRONMENT_SET_SUPPORT_ACHIEVEMENTS = 42,
    RETRO_ENVIRONMENT_SET_HW_RENDER_CONTEXT_NEGOTIATION_INTERFACE =
            (43 | RETRO_ENVIRONMENT_EXPERIMENTAL),
    RETRO_ENVIRONMENT_SET_HW_SHARED_CONTEXT =
            (44 | RETRO_ENVIRONMENT_EXPERIMENTAL),
    RETRO_ENVIRONMENT_GET_VFS_INTERFACE = 45,
    RETRO_ENVIRONMENT_GET_LED_INTERFACE = 46,
    RETRO_ENVIRONMENT_GET_AUDIO_VIDEO_ENABLE = 47,
    RETRO_ENVIRONMENT_GET_MIDI_INTERFACE = 48,
    RETRO_ENVIRONMENT_GET_FASTFORWARDING = 49,
    RETRO_ENVIRONMENT_GET_TARGET_REFRESH_RATE = 50,
    RETRO_ENVIRONMENT_GET_INPUT_BITMASKS = 51,
    RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION = 52,
    RETRO_ENVIRONMENT_SET_CORE_OPTIONS = 53,
    RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL = 54,
    RETRO_ENVIRONMENT_SET_CORE_OPTIONS_DISPLAY = 55,
    RETRO_ENVIRONMENT_GET_PREFERRED_HW_RENDER = 56,
    RETRO_ENVIRONMENT_GET_DISK_CONTROL_INTERFACE_VERSION = 57,
    RETRO_ENVIRONMENT_SET_DISK_CONTROL_EXT_INTERFACE = 58,
    RETRO_ENVIRONMENT_GET_MESSAGE_INTERFACE_VERSION = 59,
    RETRO_ENVIRONMENT_SET_MESSAGE_EXT = 60,
    RETRO_ENVIRONMENT_GET_INPUT_MAX_USERS = 61,
    RETRO_ENVIRONMENT_SET_AUDIO_BUFFER_STATUS_CALLBACK = 62,
    RETRO_ENVIRONMENT_SET_MINIMUM_AUDIO_LATENCY = 63,
    RETRO_ENVIRONMENT_SET_FASTFORWARDING_OVERRIDE = 64,
    RETRO_ENVIRONMENT_SET_CONTENT_INFO_OVERRIDE = 65,
    RETRO_ENVIRONMENT_GET_GAME_INFO_EXT = 66,
    RETRO_ENVIRONMENT_SET_CORE_OPTIONS_V2 = 67,
    RETRO_ENVIRONMENT_SET_CORE_OPTIONS_V2_INTL = 68,
    RETRO_ENVIRONMENT_GET_HW_RENDER_CONTEXT_NEGOTIATION_INTERFACE_SUPPORT =
            (73 | RETRO_ENVIRONMENT_EXPERIMENTAL)
};

struct retro_game_geometry {
    unsigned base_width;
    unsigned base_height;
    unsigned max_width;
    unsigned max_height;
    float aspect_ratio;
};

struct retro_system_timing {
    double fps;
    double sample_rate;
};

struct retro_system_av_info {
    struct retro_game_geometry geometry;
    struct retro_system_timing timing;
};

struct retro_system_info {
    const char *library_name;
    const char *library_version;
    const char *valid_extensions;
    bool need_fullpath;
    bool block_extract;
};

struct retro_game_info {
    const char *path;
    const void *data;
    size_t size;
    const char *meta;
};

struct retro_variable {
    const char *key;
    const char *value;
};

struct retro_message {
    const char *msg;
    unsigned frames;
};

enum retro_log_level {
    RETRO_LOG_DEBUG = 0,
    RETRO_LOG_INFO,
    RETRO_LOG_WARN,
    RETRO_LOG_ERROR,
    RETRO_LOG_DUMMY = INT_MAX
};

typedef void (*retro_log_printf_t)(enum retro_log_level level,
                                   const char *format, ...);

struct retro_log_callback {
    retro_log_printf_t log;
};

typedef void (*retro_proc_address_t)(void);
typedef void (*retro_hw_context_reset_t)(void);
typedef uintptr_t (*retro_hw_get_current_framebuffer_t)(void);
typedef retro_proc_address_t (*retro_hw_get_proc_address_t)(const char *symbol);

enum retro_hw_context_type {
    RETRO_HW_CONTEXT_NONE = 0,
    RETRO_HW_CONTEXT_OPENGL = 1,
    RETRO_HW_CONTEXT_OPENGLES2 = 2,
    RETRO_HW_CONTEXT_OPENGL_CORE = 3,
    RETRO_HW_CONTEXT_OPENGLES3 = 4,
    RETRO_HW_CONTEXT_OPENGLES_VERSION = 5,
    RETRO_HW_CONTEXT_VULKAN = 6,
    RETRO_HW_CONTEXT_D3D11 = 7,
    RETRO_HW_CONTEXT_D3D10 = 8,
    RETRO_HW_CONTEXT_D3D12 = 9,
    RETRO_HW_CONTEXT_D3D9 = 10,
    RETRO_HW_CONTEXT_DUMMY = INT_MAX
};

struct retro_hw_render_callback {
    enum retro_hw_context_type context_type;
    retro_hw_context_reset_t context_reset;
    retro_hw_get_current_framebuffer_t get_current_framebuffer;
    retro_hw_get_proc_address_t get_proc_address;
    bool depth;
    bool stencil;
    bool bottom_left_origin;
    unsigned version_major;
    unsigned version_minor;
    bool cache_context;
    retro_hw_context_reset_t context_destroy;
    bool debug_context;
};

enum retro_hw_render_interface_type {
    RETRO_HW_RENDER_INTERFACE_VULKAN = 0,
    RETRO_HW_RENDER_INTERFACE_D3D9 = 1,
    RETRO_HW_RENDER_INTERFACE_D3D10 = 2,
    RETRO_HW_RENDER_INTERFACE_D3D11 = 3,
    RETRO_HW_RENDER_INTERFACE_D3D12 = 4,
    RETRO_HW_RENDER_INTERFACE_GSKIT_PS2 = 5,
    RETRO_HW_RENDER_INTERFACE_DUMMY = INT_MAX
};

struct retro_hw_render_interface {
    enum retro_hw_render_interface_type interface_type;
    unsigned interface_version;
};

enum retro_hw_render_context_negotiation_interface_type {
    RETRO_HW_RENDER_CONTEXT_NEGOTIATION_INTERFACE_VULKAN = 0,
    RETRO_HW_RENDER_CONTEXT_NEGOTIATION_INTERFACE_DUMMY = INT_MAX
};

struct retro_hw_render_context_negotiation_interface {
    enum retro_hw_render_context_negotiation_interface_type interface_type;
    unsigned interface_version;
};

typedef bool (*retro_environment_t)(unsigned cmd, void *data);
typedef void (*retro_video_refresh_t)(const void *data, unsigned width,
                                      unsigned height, size_t pitch);
typedef void (*retro_audio_sample_t)(int16_t left, int16_t right);
typedef size_t (*retro_audio_sample_batch_t)(const int16_t *data, size_t frames);
typedef void (*retro_input_poll_t)(void);
typedef int16_t (*retro_input_state_t)(unsigned port, unsigned device,
                                      unsigned index, unsigned id);

#ifdef __cplusplus
}
#endif
#endif
