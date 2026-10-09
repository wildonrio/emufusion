#define _XOPEN_SOURCE 700

#include "include/lucent_libretro_host.h"
#include "include/libretro.h"

#include <dlfcn.h>
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#if defined(__ANDROID__)
#include <android/dlext.h>
#include <android/log.h>
#endif

#define MAX_PORTS 8
#define MAX_JOYPAD_BUTTONS 16
#define MAX_ANALOG_INDEXES 3
#define MAX_ANALOG_IDS 16
#define AUDIO_RING_SAMPLES (262144u)
#define MAX_VIDEO_DIMENSION 8192u
#define MAX_VIDEO_PITCH_BYTES (128u * 1024u)
#define MAX_VIDEO_FRAME_BYTES (128u * 1024u * 1024u)
#define MAX_GAME_BYTES (1024ull * 1024ull * 1024ull)
#define MAX_STATE_BYTES (512u * 1024u * 1024u)
#define MAX_SAVE_RAM_BYTES (64u * 1024u * 1024u)
#define MAX_CORE_VARIABLES 256u
#define MAX_CORE_VARIABLE_KEY_BYTES 256u
#define MAX_CORE_VARIABLE_VALUE_BYTES 4096u
/* Launch-time core-option overrides written by the Java WidescreenHackPolicy
 * into <system_directory>/lucent-core-overrides.txt (one key=value per line).
 * Mirrors CoreOptionOverrideFile.java: 64 entries, 64 KiB, bounded lines. */
#define CORE_OVERRIDE_FILE_NAME "lucent-core-overrides.txt"
#define MAX_CORE_OVERRIDES 64u
#define MAX_CORE_OVERRIDE_FILE_BYTES (64u * 1024u)
#define MAX_CORE_OVERRIDE_LINE_BYTES 1536u

typedef struct lucent_core_variable {
    char *key;
    char *value;
} lucent_core_variable;

typedef void (*fn_void)(void);
typedef unsigned (*fn_api_version)(void);
typedef void (*fn_get_system_info)(struct retro_system_info *);
typedef void (*fn_get_system_av_info)(struct retro_system_av_info *);
typedef void (*fn_set_environment)(retro_environment_t);
typedef void (*fn_set_video_refresh)(retro_video_refresh_t);
typedef void (*fn_set_audio_sample)(retro_audio_sample_t);
typedef void (*fn_set_audio_sample_batch)(retro_audio_sample_batch_t);
typedef void (*fn_set_input_poll)(retro_input_poll_t);
typedef void (*fn_set_input_state)(retro_input_state_t);
typedef void (*fn_set_controller_port_device)(unsigned, unsigned);
typedef size_t (*fn_serialize_size)(void);
typedef bool (*fn_serialize)(void *, size_t);
typedef bool (*fn_unserialize)(const void *, size_t);
typedef void (*fn_cheat_set)(unsigned, bool, const char *);
typedef bool (*fn_load_game)(const struct retro_game_info *);
typedef bool (*fn_load_game_special)(unsigned, const struct retro_game_info *, size_t);
typedef bool (*fn_prepare_exit)(void);
typedef unsigned (*fn_get_region)(void);
typedef void *(*fn_get_memory_data)(unsigned);
typedef size_t (*fn_get_memory_size)(unsigned);
typedef void (*fn_set_android_java_vm)(void *);
typedef void (*fn_set_output_size)(unsigned, unsigned);
typedef void (*fn_set_frontend_framebuffer)(unsigned);
typedef bool (*fn_mupen_vi_origin_boundary)(void);
typedef bool (*fn_hw_active_rect)(uint32_t *, unsigned);

struct lucent_retro_host {
    void *library;
    char *core_path;
    char *system_directory;
    char *save_directory;
    char *game_bytes;
    size_t game_size;
    bool initialized;
    bool game_loaded;
    /* True only after retro_load_game returned success. Unlike game_loaded,
     * this remains true after an orderly retro_unload_game so teardown can
     * distinguish a completed session from a rejected/partial Dolphin boot. */
    bool completed_game_load;
    bool paused;
    bool support_no_game;
    bool hw_configured;
    bool hw_negotiated;
    bool hw_context_ready;
    bool hw_shared_requested;
    lucent_retro_hw_options hw_options;
    struct retro_hw_render_callback hw_callback;
    const struct retro_hw_render_context_negotiation_interface
            *hw_context_negotiation_interface;
    uint64_t run_sequence;
    uint64_t hw_frame_sequence;
    unsigned hw_frame_width;
    unsigned hw_frame_height;
    enum retro_pixel_format pixel_format;
    struct retro_system_info system_info;
    struct retro_system_av_info current_av_info;
    bool has_av_info;
    uint8_t *video_bytes;
    size_t video_size;
    unsigned video_width;
    unsigned video_height;
    size_t video_pitch;
    uint64_t video_sequence;
    int16_t *audio_ring;
    size_t audio_read;
    size_t audio_count;
    /* PCM produced by the most recent guest step, before queue eviction or
     * draining. Render-driven cores may advance several vblanks per run. */
    uint64_t run_audio_output_samples;
    double audio_input_rate;
    double audio_output_rate;
    /* Wall-clock pacing may make a nominal 59.73/60.10 Hz console run at the
     * panel's exact 60 Hz. Scale the core's PCM clock by the same tiny ratio so
     * AudioTrack neither periodically starves nor overflows. */
    double audio_timing_multiplier;
    double audio_resample_accumulator;
    int64_t audio_resample_left_sum;
    int64_t audio_resample_right_sum;
    size_t audio_resample_sample_count;
    bool audio_upsample_has_previous;
    int16_t audio_upsample_previous_left;
    int16_t audio_upsample_previous_right;
    double audio_upsample_phase;
    uint32_t joypad_mask[MAX_PORTS];
#if defined(__ANDROID__)
    /* Bounded per-host input evidence, retained across context recreation.
     * Separate release/transition budget prevents a held button from using
     * all the callback evidence before its release can be observed. */
    unsigned input_trace_applied_count;
    unsigned input_trace_transition_count;
    unsigned input_trace_sample_count;
    uint64_t input_trace_last_sample_run;
    uint32_t input_trace_read_mask[MAX_PORTS];
    unsigned pointer_trace_applied_count;
    unsigned pointer_trace_callback_count;
    bool pointer_trace_read_pressed[MAX_PORTS];
#endif
    int16_t analog_state[MAX_PORTS][MAX_ANALOG_INDEXES][MAX_ANALOG_IDS];
    int16_t pointer_x[MAX_PORTS];
    int16_t pointer_y[MAX_PORTS];
    bool pointer_pressed[MAX_PORTS];
    lucent_core_variable core_variables[MAX_CORE_VARIABLES];
    bool widescreen_enhancements_enabled;
    size_t core_variable_count;
    lucent_core_variable core_overrides[MAX_CORE_OVERRIDES];
    size_t core_override_count;

    fn_void init;
    fn_void deinit;
    fn_api_version api_version;
    fn_get_system_info get_system_info;
    fn_get_system_av_info get_system_av_info;
    fn_set_environment set_environment;
    fn_set_video_refresh set_video_refresh;
    fn_set_audio_sample set_audio_sample;
    fn_set_audio_sample_batch set_audio_sample_batch;
    fn_set_input_poll set_input_poll;
    fn_set_input_state set_input_state;
    fn_set_controller_port_device set_controller_port_device;
    fn_void reset;
    fn_void run;
    fn_serialize_size serialize_size;
    fn_serialize serialize;
    fn_unserialize unserialize;
    fn_void cheat_reset;
    fn_cheat_set cheat_set;
    fn_load_game load_game;
    fn_load_game_special load_game_special;
    fn_void unload_game;
    fn_prepare_exit prepare_exit;
    fn_get_region get_region;
    fn_get_memory_data get_memory_data;
    fn_get_memory_size get_memory_size;
    fn_mupen_vi_origin_boundary mupen_vi_origin_boundary;
    fn_hw_active_rect hw_active_rect;
};

/* A single in-process game session is intentional for the initial host. Core
 * callbacks have no userdata pointer, so the active host owns their context. */
static lucent_retro_host *active_host;
static pthread_mutex_t host_mutex;
static pthread_once_t host_mutex_once = PTHREAD_ONCE_INIT;
/* A rejected/partial Dolphin mapping cannot safely pass through dlclose: its
 * process-global destructors dereference state that was never fully built.
 * Once such an image is retained, every later Dolphin open must bypass the
 * linker's already-loaded-file lookup and receive independent globals. */
static bool dolphin_mapping_quarantined;
static bool is_dolphin_core_path(const char *path) {
    const char *name;
    if (!path) return false;
    name = strrchr(path, '/');
    name = name ? name + 1 : path;
    return strcmp(name, "liblucent_core_dolphin.so") == 0;
}

static void *load_core_library(const char *path, bool force_fresh) {
#if defined(__ANDROID__)
    if (force_fresh) {
        android_dlextinfo extension;
        memset(&extension, 0, sizeof(extension));
        extension.flags = ANDROID_DLEXT_FORCE_LOAD;
        return android_dlopen_ext(path, RTLD_NOW | RTLD_LOCAL, &extension);
    }
#else
    (void)force_fresh;
#endif
    return dlopen(path, RTLD_NOW | RTLD_LOCAL);
}

static void initialize_host_mutex(void) {
    pthread_mutexattr_t attributes;
    pthread_mutexattr_init(&attributes);
    pthread_mutexattr_settype(&attributes, PTHREAD_MUTEX_RECURSIVE);
    pthread_mutex_init(&host_mutex, &attributes);
    pthread_mutexattr_destroy(&attributes);
}

static void lock_host(void) {
    pthread_once(&host_mutex_once, initialize_host_mutex);
    pthread_mutex_lock(&host_mutex);
}

static void unlock_host(void) { pthread_mutex_unlock(&host_mutex); }

#define RETURN_UNLOCKED(value) do { unlock_host(); return (value); } while (0)

static void set_error(char *buffer, size_t size, const char *format, ...) {
    va_list args;
    if (!buffer || !size) return;
    va_start(args, format);
    vsnprintf(buffer, size, format, args);
    va_end(args);
}

/* A number of otherwise well-behaved cores, including PPSSPP, accept a
 * missing log interface but later call the callback unconditionally.  Supply
 * the standard libretro interface and keep it deliberately frontend-neutral.
 * Android native stderr is not reliably surfaced by logcat on production
 * builds, so route core diagnostics through the platform logger there. */
static void core_log_callback(enum retro_log_level level,
                              const char *format, ...) {
    va_list args;
    if (!format) return;
#if defined(__ANDROID__) && !defined(LUCENT_VERBOSE_CORE_LOGS)
    /* Release gameplay must not synchronously format and write hundreds of
     * per-frame INFO messages. mGBA, for example, logs every DMA start and was
     * producing more than one hundred logcat writes per second on the Thor.
     * Warnings and errors remain lossless; verbose builds can opt back in. */
    if (level == RETRO_LOG_DEBUG || level == RETRO_LOG_INFO) return;
#endif
    va_start(args, format);
#if defined(__ANDROID__)
    {
        char message[4096];
        size_t i;
        int priority = ANDROID_LOG_INFO;
        if (level == RETRO_LOG_DEBUG) priority = ANDROID_LOG_DEBUG;
        else if (level == RETRO_LOG_WARN) priority = ANDROID_LOG_WARN;
        else if (level == RETRO_LOG_ERROR) priority = ANDROID_LOG_ERROR;
        vsnprintf(message, sizeof(message), format, args);
        /* Core metadata occasionally contains raw cartridge bytes (for
         * example an invalid SNES game-code field). Android logcat transports
         * those bytes verbatim, which can corrupt UTF-8 consumers and obscure
         * the actual runtime evidence. Keep line controls and printable ASCII;
         * replace opaque bytes only in diagnostics, never in emulated data. */
        for (i = 0; message[i] != '\0'; i++) {
            unsigned char value = (unsigned char)message[i];
            if ((value < 0x20u && value != '\n' && value != '\r' &&
                    value != '\t') || value >= 0x7fu) message[i] = '?';
        }
        __android_log_print(priority, "LucentLibretroCore", "%s", message);
    }
#else
    (void)level;
    vfprintf(stderr, format, args);
#endif
    va_end(args);
}

static bool path_is_inside(const char *path, const char *root) {
    size_t length = strlen(root);
    return strncmp(path, root, length) == 0 &&
           (root[length - 1] == '/' || path[length] == '/');
}

static retro_proc_address_t hardware_get_proc_address(const char *symbol) {
    if (!active_host || !active_host->hw_negotiated ||
            !active_host->hw_context_ready ||
            !active_host->hw_options.get_proc_address) return NULL;
    return active_host->hw_options.get_proc_address(
            active_host->hw_options.userdata, symbol);
}

static uintptr_t hardware_get_current_framebuffer(void) {
    if (!active_host || !active_host->hw_negotiated ||
            !active_host->hw_context_ready ||
            !active_host->hw_options.get_current_framebuffer) return 0;
    return active_host->hw_options.get_current_framebuffer(
            active_host->hw_options.userdata);
}

static uint32_t context_capability(enum retro_hw_context_type type) {
    switch (type) {
        case RETRO_HW_CONTEXT_OPENGLES2: return LUCENT_RETRO_HW_GLES2;
        case RETRO_HW_CONTEXT_OPENGLES3: return LUCENT_RETRO_HW_GLES3;
        case RETRO_HW_CONTEXT_OPENGLES_VERSION: return LUCENT_RETRO_HW_GLES_VERSION;
        case RETRO_HW_CONTEXT_VULKAN: return LUCENT_RETRO_HW_VULKAN;
        default: return 0;
    }
}

static enum retro_hw_context_type preferred_context(const lucent_retro_host *host) {
    switch (host->hw_options.preferred_context) {
        case LUCENT_RETRO_HW_GLES2: return RETRO_HW_CONTEXT_OPENGLES2;
        case LUCENT_RETRO_HW_GLES3: return RETRO_HW_CONTEXT_OPENGLES3;
        case LUCENT_RETRO_HW_GLES_VERSION: return RETRO_HW_CONTEXT_OPENGLES_VERSION;
        case LUCENT_RETRO_HW_VULKAN: return RETRO_HW_CONTEXT_VULKAN;
        default: return RETRO_HW_CONTEXT_NONE;
    }
}

static const char *hardware_context_name(enum retro_hw_context_type type) {
    switch (type) {
        case RETRO_HW_CONTEXT_OPENGLES2: return "OPENGLES2";
        case RETRO_HW_CONTEXT_OPENGLES3: return "OPENGLES3";
        case RETRO_HW_CONTEXT_OPENGLES_VERSION: return "OPENGLES_VERSION";
        case RETRO_HW_CONTEXT_VULKAN: return "VULKAN";
        default: return "UNSUPPORTED";
    }
}

static const char *hardware_request_rejection(
        lucent_retro_host *host, const struct retro_hw_render_callback *request) {
    uint32_t capability;
    uint32_t features;
    if (!host->hw_configured || host->hw_negotiated || !request ||
            !request->context_reset) return "host state or context_reset callback is invalid";
    features = host->hw_options.feature_capabilities;
    capability = context_capability(request->context_type);
    if (!capability || !(host->hw_options.context_capabilities & capability))
        return "requested graphics context is unavailable";
    if (request->context_type == RETRO_HW_CONTEXT_OPENGLES_VERSION) {
        if (request->version_major < 3 ||
                (request->version_major == 3 && request->version_minor < 1) ||
                request->version_major > host->hw_options.max_gles_major ||
                (request->version_major == host->hw_options.max_gles_major &&
                 request->version_minor > host->hw_options.max_gles_minor))
            return "requested GLES version is unavailable";
    }
    if (request->context_type != RETRO_HW_CONTEXT_VULKAN &&
            (!host->hw_options.get_current_framebuffer ||
             !host->hw_options.get_proc_address))
        return "GLES framebuffer/proc-address hooks are unavailable";
    if (request->depth && !(features & LUCENT_RETRO_HW_DEPTH))
        return "requested depth buffer is unavailable";
    if (request->stencil && !(features & LUCENT_RETRO_HW_STENCIL))
        return "requested stencil buffer is unavailable";
    if (request->stencil && !request->depth)
        return "stencil without depth is invalid";
    if (request->cache_context && !(features & LUCENT_RETRO_HW_CACHE_CONTEXT))
        return "requested cached-context lifecycle is unavailable";
    if (request->debug_context && !(features & LUCENT_RETRO_HW_DEBUG_CONTEXT))
        return "requested debug context is unavailable";
    return NULL;
}

static bool set_hardware_render(struct retro_hw_render_callback *request) {
    const char *rejection;
    if (!active_host) return false;
    rejection = hardware_request_rejection(active_host, request);
    if (rejection) {
        core_log_callback(RETRO_LOG_ERROR,
                "Lucent rejected hardware render request: %s "
                "(type=%u version=%u.%u depth=%u stencil=%u cache=%u debug=%u)\n",
                rejection, request ? (unsigned)request->context_type : 0u,
                request ? request->version_major : 0u,
                request ? request->version_minor : 0u,
                request && request->depth ? 1u : 0u,
                request && request->stencil ? 1u : 0u,
                request && request->cache_context ? 1u : 0u,
                request && request->debug_context ? 1u : 0u);
        return false;
    }
    active_host->hw_callback = *request;
    active_host->hw_callback.get_current_framebuffer =
            hardware_get_current_framebuffer;
    active_host->hw_callback.get_proc_address = hardware_get_proc_address;
    *request = active_host->hw_callback;
    active_host->hw_negotiated = true;
    active_host->hw_context_ready = false;
    active_host->hw_frame_sequence = 0;
    core_log_callback(RETRO_LOG_INFO,
            "hardware render request accepted context=%s type=%u "
            "version=%u.%u depth=%u stencil=%u cacheContext=%u debug=%u\n",
            hardware_context_name(request->context_type),
            (unsigned)request->context_type, request->version_major,
            request->version_minor, request->depth ? 1u : 0u,
            request->stencil ? 1u : 0u, request->cache_context ? 1u : 0u,
            request->debug_context ? 1u : 0u);
    return true;
}

static const char *find_core_variable(const lucent_retro_host *host,
                                      const char *key) {
    size_t index;
    if (!host || !key) return NULL;
    for (index = 0; index < host->core_variable_count; index++)
        if (strcmp(host->core_variables[index].key, key) == 0)
            return host->core_variables[index].value;
    return NULL;
}

static const char *find_option_token(const char *options, const char *wanted,
                                     size_t *size) {
    const char *start = options;
    size_t wanted_size;
    if (!options || !wanted || !size) return NULL;
    wanted_size = strlen(wanted);
    while (*start) {
        const char *end = strchr(start, '|');
        size_t current_size = end ? (size_t)(end - start) : strlen(start);
        if (current_size == wanted_size &&
                memcmp(start, wanted, wanted_size) == 0) {
            *size = current_size;
            return start;
        }
        if (!end) break;
        start = end + 1;
    }
    return NULL;
}

static const char *find_core_override(const lucent_retro_host *host,
                                      const char *key) {
    size_t index;
    if (!host || !key) return NULL;
    for (index = 0; index < host->core_override_count; index++)
        if (strcmp(host->core_overrides[index].key, key) == 0)
            return host->core_overrides[index].value;
    return NULL;
}

static bool core_override_key_is_valid(const char *key, size_t size) {
    size_t index;
    if (!size || size >= MAX_CORE_VARIABLE_KEY_BYTES) return false;
    for (index = 0; index < size; index++) {
        char c = key[index];
        bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.';
        if (!ok) return false;
    }
    return true;
}

static void free_core_overrides(lucent_retro_host *host) {
    size_t index;
    if (!host) return;
    for (index = 0; index < host->core_override_count; index++) {
        free(host->core_overrides[index].key);
        free(host->core_overrides[index].value);
    }
    host->core_override_count = 0;
}

/* Reads <system_directory>/lucent-core-overrides.txt once per host. Missing,
 * oversized, or malformed files are ignored line by line and never fail the
 * launch: the override channel is launch-time only and purely additive to the
 * reviewed defaults in register_core_variable_defaults(). */
static void load_core_overrides(lucent_retro_host *host) {
    char path[4096];
    char line[MAX_CORE_OVERRIDE_LINE_BYTES];
    FILE *file;
    struct stat info;
    if (!host || !host->system_directory) return;
    host->core_override_count = 0;
    if (snprintf(path, sizeof(path), "%s/%s", host->system_directory,
            CORE_OVERRIDE_FILE_NAME) >= (int)sizeof(path)) return;
    if (stat(path, &info) != 0 || !S_ISREG(info.st_mode)) return;
    if (info.st_size > (off_t)MAX_CORE_OVERRIDE_FILE_BYTES) {
        core_log_callback(RETRO_LOG_WARN,
                "core-option override file ignored: larger than %u bytes\n",
                (unsigned)MAX_CORE_OVERRIDE_FILE_BYTES);
        return;
    }
    file = fopen(path, "rb");
    if (!file) return;
    while (fgets(line, sizeof(line), file)) {
        size_t length = strlen(line);
        char *key;
        char *value;
        char *separator;
        size_t key_size;
        size_t value_size;
        lucent_core_variable *entry;
        if (length && line[length - 1] != '\n' && !feof(file)) {
            /* Discard the remainder of an over-long line. */
            int c;
            while ((c = fgetc(file)) != EOF && c != '\n') { }
            continue;
        }
        while (length && (line[length - 1] == '\n' || line[length - 1] == '\r' ||
                line[length - 1] == ' ' || line[length - 1] == '\t'))
            line[--length] = '\0';
        key = line;
        while (*key == ' ' || *key == '\t') key++;
        if (!*key || *key == '#') continue;
        separator = strchr(key, '=');
        if (!separator || separator == key) continue;
        value = separator + 1;
        while (*value == ' ' || *value == '\t') value++;
        while (separator > key && (separator[-1] == ' ' || separator[-1] == '\t'))
            separator--;
        key_size = (size_t)(separator - key);
        value_size = strlen(value);
        if (!core_override_key_is_valid(key, key_size) || !value_size ||
                value_size >= MAX_CORE_VARIABLE_VALUE_BYTES)
            continue;
        {
            size_t index;
            bool control = false;
            for (index = 0; index < value_size; index++)
                if ((unsigned char)value[index] < 0x20 || value[index] == 0x7f)
                    control = true;
            if (control) continue;
        }
        if (host->core_override_count >= MAX_CORE_OVERRIDES) {
            core_log_callback(RETRO_LOG_WARN,
                    "core-option override file truncated at %u entries\n",
                    (unsigned)MAX_CORE_OVERRIDES);
            break;
        }
        entry = &host->core_overrides[host->core_override_count];
        entry->key = (char *)malloc(key_size + 1);
        entry->value = (char *)malloc(value_size + 1);
        if (!entry->key || !entry->value) {
            free(entry->key);
            free(entry->value);
            entry->key = NULL;
            entry->value = NULL;
            break;
        }
        memcpy(entry->key, key, key_size);
        entry->key[key_size] = '\0';
        memcpy(entry->value, value, value_size + 1);
        host->core_override_count++;
    }
    fclose(file);
    if (host->core_override_count)
        core_log_callback(RETRO_LOG_INFO,
                "loaded %u launch-time core-option overrides from %s\n",
                (unsigned)host->core_override_count, path);
}

/* Core-options-v0 declarations put the default first after "; ". Lucent has
 * no RetroArch-style core-options UI, so both software and hardware cores need
 * deterministic values instead of NULL. Engine-specific overrides are kept
 * here as a deliberately tiny, reviewed profile rather than exposing hundreds
 * of emulator knobs to the user. */
static bool register_core_variable_defaults(
        lucent_retro_host *host, const struct retro_variable *variables) {
    const struct retro_variable *variable;
    if (!host || !variables) return true;
    for (variable = variables; variable->key; variable++) {
        const char *options;
        const char *declared_options;
        const char *end;
        size_t key_size;
        size_t value_size;
        lucent_core_variable *entry;
        if (!variable->value || find_core_variable(host, variable->key)) continue;
        if (host->core_variable_count >= MAX_CORE_VARIABLES) return false;
        key_size = strlen(variable->key);
        options = strstr(variable->value, "; ");
        if (!options) return false;
        options += 2;
        declared_options = options;
        end = strchr(options, '|');
        value_size = end ? (size_t)(end - options) : strlen(options);
        /* Start with the core's native PSP default on an unknown Android
         * GPU, not the old unconditional 4x qualification profile. Display
         * fitting preserves 480:272 independently; explicit advertised
         * overrides below may still select a higher internal resolution. */
        if (strcmp(variable->key, "ppsspp_internal_resolution") == 0) {
            const char *profile = find_option_token(
                    options, "480x272", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "ppsspp_cropto16x9") == 0) {
            const char *profile = find_option_token(
                    options, "disabled", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "mesen-s_overscan_vertical") == 0) {
            /* "8px" crops OverscanTop=7/OverscanBottom=8 (15 lines total),
             * taking Mesen-S from its raw 256x239 frame to the reviewed,
             * physically-proven 256x224 active picture (owner directive
             * 2026-09-06: exposing the raw NTSC overscan border showed as an
             * unwanted ~34px black band top and bottom on the Thor's flat
             * panel -- a real CRT's bezel would have clipped it, but nothing
             * here does). "None" was tried and reverted; do not set it again
             * without re-deriving the same regression. */
            const char *profile = find_option_token(options, "8px", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "reicast_internal_resolution") == 0) {
            /* Use Flycast's native default on an unknown Android GPU. The
             * former Thor-sized 1440x1080 target shaded 5.0625 times as many
             * pixels regardless of device capability. Display fitting and
             * the core-reported aspect are independent of this resolution;
             * a supported explicit core-option override can still upscale. */
            const char *profile = find_option_token(
                    options, "640x480", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "mupen64plus-43screensize") == 0) {
            /* Use GLideN64's declared default rather than force a Thor-sized
             * 1080p render target on every GPU. This is internal resolution,
             * not a replacement for the game's reported aspect/active rect. */
            const char *profile = find_option_token(
                    options, "640x480", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "mupen64plus-EnableOverscan") == 0) {
            /* Never discard game pixels. Fixed overscan offsets clipped HUDs
             * and the top/bottom of Ocarina of Time; title-specific inactive
             * borders cannot be inferred safely by a system-wide profile. */
            const char *profile = find_option_token(
                    options, "Disabled", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "mupen64plus-OverscanTop") == 0) {
            const char *profile = find_option_token(options, "0", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "mupen64plus-OverscanBottom") == 0) {
            const char *profile = find_option_token(options, "0", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "mupen64plus-rdp-plugin") == 0) {
            const char *profile = find_option_token(
                    options, "gliden64", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "mupen64plus-rsp-plugin") == 0) {
            const char *profile = find_option_token(options, "hle", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "mupen64plus-ThreadedRenderer") == 0) {
            /* One EGL context stays owned by Lucent's in-window render loop;
             * the core must not create a competing threaded GL context. */
            const char *profile = find_option_token(options, "False", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "mupen64plus-aspect") == 0) {
            /* A generic widescreen transform is not proof that the game
             * officially supports 16:9. The safe system default is native
             * 4:3; genuine anamorphic titles require a future audited
             * per-title override rather than stretching every N64 game. */
            const char *profile = find_option_token(options, "4:3", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "citra_graphics_api") == 0) {
            const char *profile = find_option_token(
                    options, "Vulkan", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "citra_resolution_factor") == 0) {
            /* Start at native resolution on an unknown Android GPU. A fixed
             * Thor-sized 4x target shades sixteen times as many pixels even
             * on single-screen phones. Display fit/aspect are independent;
             * an explicit supported core-option override can still upscale. */
            const char *profile = find_option_token(options, "1", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "dolphin_osd_enabled") == 0) {
            /* The embedded core's default draws diagnostic messages (including
             * Video Info on launch/context recreation) over gameplay. Keep
             * ordinary play clean; core logging and explicit diagnostic
             * overrides remain available independently of this default. */
            const char *profile = find_option_token(options, "disabled", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "dolphin_efb_scale") == 0) {
            /* Unknown Android GPUs must not pay a mandatory 4x pixel cost
             * for the Thor's old 2x EFB profile. Start at native resolution;
             * display fit and native aspect remain independent. A supported
             * explicit core-option override can still opt into upscaling. */
            const char *profile = find_option_token(options, "1", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "dolphin_widescreen") == 0) {
            const char *profile = find_option_token(options,
                    host->widescreen_enhancements_enabled ?
                            "enabled" : "disabled",
                    &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "dolphin_widescreen_hack") == 0) {
            /* Never expand geometry with a generic hack. Dolphin's emulated
             * console widescreen flag above is available only to games that
             * officially read it. */
            const char *profile = find_option_token(options, "disabled", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "dolphin_aspect_ratio") == 0) {
            /* This controls Dolphin's intermediate libretro framebuffer,
             * NOT the final Android display. Fill that transport image (the
             * core's upstream default); the host applies the game-reported
             * 4:3/16:9 aspect exactly once. Auto letterboxes inside the EFB-
             * sized target before the host's anamorphic scaling, compressing
             * Wii images vertically. Do not couple this to widescreen mode:
             * the console flag and game-reported aspect remain authoritative,
             * and the geometry-expanding widescreen hack remains disabled. */
            const char *profile = find_option_token(options, "3", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "dolphin_main_cpu_thread") == 0) {
            /* Dolphin's dual-core libretro frame pump deadlocks in-process.
             * Each retro_run does Core::DoFrameStep() and only then enters
             * FifoManager::RunGpuLoop() on this thread. Whenever the emulated
             * CPU produced no new field during the previous call, DoFrameStep
             * takes its Running branch and calls Core::SetState(Paused) ->
             * CPUManager::SetStepping(true), which blocks on
             * m_state_cpu_idle_cvar until the separate CPU thread goes idle.
             * That CPU thread reaches its idle point only after the GPU thread
             * drains the FIFO or answers a blocking AsyncRequests event, and
             * the GPU thread is this thread, still parked inside SetStepping.
             * Dolphin documents the hazard itself in CPUManager::Break():
             * "We'll deadlock if we synchronize, the CPU may block waiting for
             * our caller to finish."  Both threads then sleep forever with no
             * further core output, which is the GameCube/Wii freeze.
             * Single-core keeps emulation on this one render thread:
             * retro_run runs CPUManager::RunSingleFrame() directly, and
             * GetInitializedVideoGuard puts AsyncRequests in passthrough, so
             * no cross-thread handoff exists to deadlock on. */
            const char *profile = find_option_token(
                    options, "disabled", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "dolphin_ir_mode") == 0) {
            /* EmuFusion supplies a real RETRO_DEVICE_POINTER cursor from the
             * right stick. Pointer-backed mode keeps analog index 1 available
             * for Dolphin's Wiimote tilt group instead of making one channel
             * serve both IR and tilt. There is intentionally no user-facing
             * core-options UI. */
            const char *profile = find_option_token(options, "2", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key,
                          "dolphin_shader_compilation_mode") == 0) {
            /* Lucent owns one EGL context. Do not select an asynchronous mode
             * whose worker requires a second shared context on Android. */
            const char *profile = find_option_token(
                    options, "0", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "dolphin_wait_for_shaders") == 0) {
            /* Prefer a bounded compile pause to visibly missing/black objects
             * while a title's first shaders are created. */
            const char *profile = find_option_token(
                    options, "enabled", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key,
                          "swanstation_GPU_WidescreenHack") == 0) {
            const char *profile = find_option_token(options, "false", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key,
                          "swanstation_Display_AspectRatio") == 0) {
            /* The original PlayStation display target is 4:3. SwanStation's
             * "Native" token means Corrected (Region Native), which reported
             * 1.224:1 for a 320x240 NTSC game on the maintained build and made
             * the picture visibly too narrow. Keep the core's documented 4:3
             * default; the generic widescreen hack remains forbidden. */
            const char *profile = find_option_token(options, "4:3", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key,
                          "reicast_widescreen_cheats") == 0 ||
                   strcmp(variable->key,
                          "reicast_widescreen_hack") == 0) {
            const char *profile = find_option_token(options, "disabled", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "armsx2_aspect_ratio") == 0) {
            const char *profile = find_option_token(options,
                    "Auto 4:3/3:2", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key,
                          "armsx2_widescreen_patches") == 0) {
            const char *profile = find_option_token(options, "disabled", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "mesen_aspect_ratio") == 0) {
            /* Mesen Auto applies the correct NTSC/PAL pixel aspect. A fixed
             * 4:3 frontend box makes NES output too wide. */
            const char *profile = find_option_token(options, "Auto", &value_size);
            if (profile) options = profile;
        } else if (strstr(host->core_path, "lucent_core_armsx2") &&
                strcmp(variable->key, "armsx2_blending_accuracy") == 0) {
            /* Shadow of the Colossus is explicitly tagged by PCSX2 as needing
             * Full blending. Lucent has no core-options UI, so retaining the
             * libretro default Basic guarantees a known-bad configuration for
             * that title. Full is the accuracy-first system default requested
             * by the product contract; per-title performance qualification may
             * later prove a lower safe override, but it must never silently
             * override the core database warning. */
            const char *profile = find_option_token(
                    options, "Full", &value_size);
            if (profile) options = profile;
        } else if (strstr(host->core_path, "lucent_core_melonds_ds") &&
                strcmp(variable->key, "melonds_number_of_screen_layouts") == 0) {
            const char *profile = find_option_token(options, "1", &value_size);
            if (profile) options = profile;
        } else if (strstr(host->core_path, "lucent_core_melonds_ds") &&
                strcmp(variable->key, "melonds_screen_layout1") == 0) {
            const char *profile = find_option_token(
                    options, "top-bottom", &value_size);
            if (profile) options = profile;
        } else if (strstr(host->core_path, "lucent_core_melonds_ds") &&
                strcmp(variable->key, "melonds_touch_mode") == 0) {
            const char *profile = find_option_token(options, "touch", &value_size);
            if (profile) options = profile;
        } else if (strstr(host->core_path, "lucent_core_azahar") &&
                strcmp(variable->key, "citra_layout_option") == 0) {
            /* Keep the two native 3DS viewports independently addressable.
             * Azahar's reviewed SideScreen geometry is exactly 720x240 at 1x:
             * a 400x240 top screen followed by the 320x240 touch screen. The
             * Vulkan frontend crops those explicit rectangles for the Thor's
             * two displays. Do not return to the 400x480 default and infer
             * two equal vertical halves: that was an accidental private ABI,
             * and its lower half stayed black in 292e4245 device evidence. */
            const char *profile = find_option_token(
                    options, "side_by_side", &value_size);
            if (profile) options = profile;
        } else if (strstr(host->core_path, "lucent_core_azahar") &&
                strcmp(variable->key, "citra_enable_touch_touchscreen") == 0) {
            const char *profile = find_option_token(options, "enabled", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "dolphin_cheats_enabled") == 0) {
            /* Dolphin refuses retro_cheat_set with an OSD message unless its
             * internal cheat support is on. Every downloaded Gecko/AR code is
             * an explicit user switch in Lucent's own cheat panel, so the
             * core-level gate must not silently discard them. Restart-time. */
            const char *profile = find_option_token(options, "enabled", &value_size);
            if (profile) options = profile;
        } else if (strcmp(variable->key, "ppsspp_cheats") == 0) {
            /* PPSSPP runs a CWCheat line once and then stops unless internal
             * cheats stay enabled; live toggles need the continuous path. */
            const char *profile = find_option_token(options, "enabled", &value_size);
            if (profile) options = profile;
        } else if (strstr(host->core_path, "lucent_core_puae") &&
                strcmp(variable->key, "puae_kickstart") == 0) {
            /* PUAE contains its GPL-compatible AROS replacement ROM. Make it
             * the explicit baseline instead of probing for or silently using
             * an unaudited user Kickstart. CD32 remains separately gated on
             * user firmware by the Java qualification catalog. */
            const char *profile = find_option_token(options, "aros", &value_size);
            if (profile) options = profile;
        }
        {
            /* Launch-time overrides from <system>/lucent-core-overrides.txt
             * are applied after the reviewed defaults, but only when the
             * requested token is one the core itself advertises. */
            const char *override = find_core_override(host, variable->key);
            if (override) {
                size_t override_size = 0;
                const char *token = find_option_token(
                        declared_options, override, &override_size);
                if (token) {
                    options = token;
                    value_size = override_size;
                    core_log_callback(RETRO_LOG_INFO,
                            "core-option override applied %s=%s\n",
                            variable->key, override);
                } else {
                    core_log_callback(RETRO_LOG_WARN,
                            "core-option override ignored: %s does not "
                            "advertise token '%s'\n", variable->key, override);
                }
            }
        }
        if (!key_size || key_size >= MAX_CORE_VARIABLE_KEY_BYTES ||
                !value_size || value_size >= MAX_CORE_VARIABLE_VALUE_BYTES)
            return false;
        entry = &host->core_variables[host->core_variable_count];
        entry->key = (char *)malloc(key_size + 1);
        entry->value = (char *)malloc(value_size + 1);
        if (!entry->key || !entry->value) {
            free(entry->key);
            free(entry->value);
            entry->key = NULL;
            entry->value = NULL;
            return false;
        }
        memcpy(entry->key, variable->key, key_size + 1);
        memcpy(entry->value, options, value_size);
        entry->value[value_size] = '\0';
        host->core_variable_count++;
    }
    return true;
}

static void reset_audio_resampler(lucent_retro_host *host) {
    if (!host) return;
    host->audio_resample_accumulator = 0.0;
    host->audio_resample_left_sum = 0;
    host->audio_resample_right_sum = 0;
    host->audio_resample_sample_count = 0;
    host->audio_upsample_has_previous = false;
    host->audio_upsample_previous_left = 0;
    host->audio_upsample_previous_right = 0;
    host->audio_upsample_phase = 0.0;
}

static void correct_gearsystem_timing(lucent_retro_host *host) {
    /* This pinned Gearsystem build reports 60/44100 for NTSC Game Gear.
     * Each vblank actually spans 228 * 262 ticks of its 3579545 Hz clock.
     * Its PSG Blip_Buffer uses 16-bit fractional precision: rounding
     * 44100 / 3579545 * 65536 gives 807, so PCM is produced at
     * 807 * 3579545 / 65536 Hz, not exactly 44100 Hz. Correct both clocks
     * before the existing bounded display/audio synchronization is applied.
     * Preserve the already selected 44100 Hz Android sink and core state.
     * The 160x144 geometry identifies the reviewed GG/PSG path; do not
     * extrapolate this to SMS/FM, PAL, or an unreviewed core revision.
     * Evidence: docs/qa/gamegear-current-off-2026-09-11/README.md. */
    if (host->system_info.library_name && host->system_info.library_version &&
            strcmp(host->system_info.library_name, "Gearsystem") == 0 &&
            strcmp(host->system_info.library_version,
                    "3c4cfcf54dfe9e36070815e76ee2bab9e754104f") == 0 &&
            host->current_av_info.geometry.base_width == 160 &&
            host->current_av_info.geometry.base_height == 144 &&
            host->current_av_info.timing.fps == 60.0 &&
            host->current_av_info.timing.sample_rate == 44100.0) {
        host->current_av_info.timing.fps = 3579545.0 / (228.0 * 262.0);
        host->audio_input_rate = 807.0 * 3579545.0 / 65536.0;
    }
}

static void correct_known_core_timing(lucent_retro_host *host) {
    correct_gearsystem_timing(host);
    /* Official Azahar 2125.1.3 reports 60/32728, but each retro_run advances
     * one 4481136-tick GPU vblank and DSP PCM advances once per 8192 ARM11
     * ticks (268111856 Hz). Its immediate libretro audio sink does not
     * resample. Expose the real guest clock so the existing bounded display
     * correction also scales audio; otherwise PCM accumulates at ~93 frames/s
     * at 60 Hz until the Java FIFO drops it. Keep the already chosen integer
     * AudioTrack sink rate, including across runtime layout/AV updates.
     * Pin the reviewed release and metadata tuple, not every future 3DS core.
     * Source/artifact identity: engines/azahar-source-lock.json. */
    if (host->system_info.library_name && host->system_info.library_version &&
            strcmp(host->system_info.library_name, "Azahar") == 0 &&
            strcmp(host->system_info.library_version, "2125.1.3") == 0 &&
            host->current_av_info.timing.fps == 60.0 &&
            host->current_av_info.timing.sample_rate == 32728.0) {
        host->current_av_info.timing.fps = 268111856.0 / 4481136.0;
        host->audio_input_rate = 268111856.0 / 8192.0;
    }
}

static bool environment_callback(unsigned command, void *data) {
    if (!active_host) return false;
    if (!data && command != RETRO_ENVIRONMENT_SET_HW_SHARED_CONTEXT) return false;
    switch (command) {
        case RETRO_ENVIRONMENT_GET_OVERSCAN:
            /* false = crop TV-safe overscan. BlastEm (Genesis/Mega Drive)
             * consults this before publishing its geometry, and a failed
             * query leaves its local result byte undefined -- the response
             * must be explicit either way (see docs/strict-off-physical-qa-
             * 2026-08-30.md). Returning true exposed BlastEm's raw overscan
             * border, which showed as an unwanted black band on the Thor's
             * flat panel the same way Mesen-S's did (owner directive
             * 2026-09-06); do not flip this back to true without re-deriving
             * that regression. */
            *(bool *)data = false;
            return true;
        case RETRO_ENVIRONMENT_GET_CAN_DUPE:
            *(bool *)data = true;
            return true;
        case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
            *(const char **)data = active_host->system_directory;
            return true;
        case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
            *(const char **)data = active_host->save_directory;
            return true;
        case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT: {
            enum retro_pixel_format format = *(const enum retro_pixel_format *)data;
            if (format != RETRO_PIXEL_FORMAT_0RGB1555 &&
                    format != RETRO_PIXEL_FORMAT_RGB565 &&
                    format != RETRO_PIXEL_FORMAT_XRGB8888) return false;
            active_host->pixel_format = format;
            return true;
        }
        case RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME:
            active_host->support_no_game = *(const bool *)data;
            return true;
        case RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO:
        {
            double established_output_rate = active_host->audio_output_rate;
            bool runtime_change = active_host->game_loaded &&
                    established_output_rate >= 8000.0;
            active_host->current_av_info = *(const struct retro_system_av_info *)data;
            active_host->audio_input_rate =
                    active_host->current_av_info.timing.sample_rate;
            /* AudioTrack is created once from the post-load AV information.
             * Cores may subsequently change their production rate (mGBA does
             * this when SOUNDBIAS resolution changes). Preserve that immutable
             * sink rate and let push_audio_frame's ratio-aware downsampler
             * absorb the new input rate instead of feeding a 32 kHz track at
             * 65/131/262 kHz and dropping half or more of the audio. */
            active_host->audio_output_rate = runtime_change
                    ? established_output_rate
                    : (active_host->audio_input_rate > 192000.0
                            ? 48000.0 : active_host->audio_input_rate);
            correct_known_core_timing(active_host);
            reset_audio_resampler(active_host);
            active_host->current_av_info.timing.sample_rate =
                    active_host->audio_output_rate;
            active_host->has_av_info = true;
            return true;
        }
        case RETRO_ENVIRONMENT_SET_GEOMETRY:
            active_host->current_av_info.geometry = *(const struct retro_game_geometry *)data;
            active_host->has_av_info = true;
            return true;
        case RETRO_ENVIRONMENT_GET_VARIABLE:
            ((struct retro_variable *)data)->value = find_core_variable(
                    active_host, ((struct retro_variable *)data)->key);
            return true;
        case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:
            *(bool *)data = false;
            return true;
        case RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION:
            *(unsigned *)data = 0;
            return true;
        case RETRO_ENVIRONMENT_GET_INPUT_BITMASKS:
            return true;
        case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:
            ((struct retro_log_callback *)data)->log = core_log_callback;
            return true;
        case RETRO_ENVIRONMENT_GET_PREFERRED_HW_RENDER:
            if (!active_host->hw_configured) return false;
            *(enum retro_hw_context_type *)data = preferred_context(active_host);
            return *(enum retro_hw_context_type *)data != RETRO_HW_CONTEXT_NONE;
        case RETRO_ENVIRONMENT_SET_HW_RENDER:
            return set_hardware_render((struct retro_hw_render_callback *)data);
        case RETRO_ENVIRONMENT_GET_HW_RENDER_CONTEXT_NEGOTIATION_INTERFACE_SUPPORT: {
            struct retro_hw_render_context_negotiation_interface *interface =
                    (struct retro_hw_render_context_negotiation_interface *)data;
            if (!active_host->hw_configured ||
                    !(active_host->hw_options.context_capabilities &
                      LUCENT_RETRO_HW_VULKAN) ||
                    interface->interface_type !=
                      RETRO_HW_RENDER_CONTEXT_NEGOTIATION_INTERFACE_VULKAN)
                return false;
            /* Lucent implements Vulkan negotiation v1. A v2 core may still
             * register its newer struct; only the v1 prefix is consumed. */
            interface->interface_version = 1;
            return true;
        }
        case RETRO_ENVIRONMENT_SET_HW_RENDER_CONTEXT_NEGOTIATION_INTERFACE: {
            const struct retro_hw_render_context_negotiation_interface *interface =
                    (const struct retro_hw_render_context_negotiation_interface *)data;
            if (!active_host->hw_configured ||
                    !(active_host->hw_options.context_capabilities &
                      LUCENT_RETRO_HW_VULKAN) ||
                    interface->interface_type !=
                      RETRO_HW_RENDER_CONTEXT_NEGOTIATION_INTERFACE_VULKAN ||
                    interface->interface_version < 1)
                return false;
            active_host->hw_context_negotiation_interface = interface;
            return true;
        }
        case RETRO_ENVIRONMENT_GET_HW_RENDER_INTERFACE:
            if (!active_host->hw_negotiated ||
                    active_host->hw_callback.context_type != RETRO_HW_CONTEXT_VULKAN ||
                    !active_host->hw_options.render_interface) return false;
            *(const struct retro_hw_render_interface **)data =
                    (const struct retro_hw_render_interface *)
                    active_host->hw_options.render_interface;
            return true;
        case RETRO_ENVIRONMENT_SET_HW_SHARED_CONTEXT:
            if (!active_host->hw_configured ||
                    !(active_host->hw_options.feature_capabilities &
                      LUCENT_RETRO_HW_SHARED_CONTEXT)) return false;
            active_host->hw_shared_requested = true;
            return true;
        case RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL:
        case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:
            /* These commands use unsigned/input-descriptor payloads, not
             * retro_variable arrays.  Treating them as option declarations
             * corrupts the ABI and made PPSSPP's first input descriptor look
             * like the pointer 0x100000000 on ARM64. */
            return true;
        case RETRO_ENVIRONMENT_SET_VARIABLES:
            return register_core_variable_defaults(
                    active_host, (const struct retro_variable *)data);
        case RETRO_ENVIRONMENT_SET_CONTROLLER_INFO:
        case RETRO_ENVIRONMENT_SET_MEMORY_MAPS:
        case RETRO_ENVIRONMENT_SET_SUPPORT_ACHIEVEMENTS:
            return true;
        case RETRO_ENVIRONMENT_GET_VFS_INTERFACE:
            return false;
        default:
            return false;
    }
}

static void video_callback(const void *data, unsigned width, unsigned height,
                           size_t pitch) {
    size_t size;
    size_t bytes_per_pixel;
    uint8_t *replacement;
    if (!active_host || !data || !width || !height)
        return;
    if (data == RETRO_HW_FRAME_BUFFER_VALID) {
        if (!active_host->hw_negotiated || !active_host->hw_context_ready ||
                width > MAX_VIDEO_DIMENSION || height > MAX_VIDEO_DIMENSION) return;
        if (active_host->hw_options.source_timeline_policy &
                LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_VI_ORIGIN) {
            /* GLideN64 must keep its ordinary vertical-interrupt rendering;
             * suppressing those swaps produced only its startup/clear buffer
             * in Lucent's frontend FBO on the Thor. The patched core instead
             * attests whether this exact retro_run crossed a VI-origin
             * boundary. Ignore unmarked callbacks without fabricating a
             * contiguous callback sequence. */
            if (!active_host->mupen_vi_origin_boundary ||
                    !active_host->mupen_vi_origin_boundary()) return;
            active_host->hw_frame_width = width;
            active_host->hw_frame_height = height;
            if (active_host->run_sequence > active_host->hw_frame_sequence)
                active_host->hw_frame_sequence = active_host->run_sequence;
            return;
        }
        active_host->hw_frame_width = width;
        active_host->hw_frame_height = height;
        /* Preserve the carrier-run ordinal rather than manufacturing a
         * callback-local clock. */
        if (active_host->run_sequence > active_host->hw_frame_sequence)
            active_host->hw_frame_sequence = active_host->run_sequence;
        else if (active_host->hw_frame_sequence != UINT64_MAX)
            active_host->hw_frame_sequence++;
        return;
    }
    if (width > MAX_VIDEO_DIMENSION || height > MAX_VIDEO_DIMENSION ||
            pitch > MAX_VIDEO_PITCH_BYTES) return;
    bytes_per_pixel = active_host->pixel_format == RETRO_PIXEL_FORMAT_XRGB8888 ? 4u : 2u;
    if (width > SIZE_MAX / bytes_per_pixel || pitch < width * bytes_per_pixel) return;
    if (pitch > SIZE_MAX / height) return;
    size = pitch * height;
    if (!size || size > MAX_VIDEO_FRAME_BYTES) return;
    if (size != active_host->video_size) {
        replacement = (uint8_t *)realloc(active_host->video_bytes, size);
        if (!replacement) return;
        active_host->video_bytes = replacement;
        active_host->video_size = size;
    }
    memcpy(active_host->video_bytes, data, size);
    active_host->video_width = width;
    active_host->video_height = height;
    active_host->video_pitch = pitch;
    active_host->video_sequence++;
}

static void push_audio_sample(int16_t sample) {
    size_t write;
    if (!active_host || !active_host->audio_ring) return;
    active_host->run_audio_output_samples++;
    if (active_host->audio_count == AUDIO_RING_SAMPLES) {
        active_host->audio_read = (active_host->audio_read + 1) % AUDIO_RING_SAMPLES;
        active_host->audio_count--;
    }
    write = (active_host->audio_read + active_host->audio_count) % AUDIO_RING_SAMPLES;
    active_host->audio_ring[write] = sample;
    active_host->audio_count++;
}

static void push_audio_frame(int16_t left, int16_t right) {
    double effective_input_rate;
    if (!active_host) return;
    effective_input_rate = active_host->audio_input_rate *
            (active_host->audio_timing_multiplier > 0.0 ?
                    active_host->audio_timing_multiplier : 1.0);
    if (effective_input_rate > active_host->audio_output_rate &&
            active_host->audio_output_rate >= 8000.0) {
        active_host->audio_resample_left_sum += left;
        active_host->audio_resample_right_sum += right;
        active_host->audio_resample_sample_count++;
        active_host->audio_resample_accumulator += active_host->audio_output_rate;
        if (active_host->audio_resample_accumulator < effective_input_rate)
            return;
        active_host->audio_resample_accumulator -= effective_input_rate;
        if (active_host->audio_resample_sample_count > 0) {
            left = (int16_t)(active_host->audio_resample_left_sum /
                    (int64_t)active_host->audio_resample_sample_count);
            right = (int16_t)(active_host->audio_resample_right_sum /
                    (int64_t)active_host->audio_resample_sample_count);
        }
        active_host->audio_resample_left_sum = 0;
        active_host->audio_resample_right_sum = 0;
        active_host->audio_resample_sample_count = 0;
    } else if (effective_input_rate >= 8000.0 &&
            active_host->audio_output_rate > effective_input_rate) {
        double step = effective_input_rate / active_host->audio_output_rate;
        if (!active_host->audio_upsample_has_previous) {
            push_audio_sample(left);
            push_audio_sample(right);
            active_host->audio_upsample_previous_left = left;
            active_host->audio_upsample_previous_right = right;
            active_host->audio_upsample_phase = step;
            active_host->audio_upsample_has_previous = true;
            return;
        }
        while (active_host->audio_upsample_phase <= 1.0) {
            double phase = active_host->audio_upsample_phase;
            int32_t output_left = (int32_t)((1.0 - phase) *
                    active_host->audio_upsample_previous_left + phase * left);
            int32_t output_right = (int32_t)((1.0 - phase) *
                    active_host->audio_upsample_previous_right + phase * right);
            push_audio_sample((int16_t)output_left);
            push_audio_sample((int16_t)output_right);
            active_host->audio_upsample_phase += step;
        }
        active_host->audio_upsample_phase -= 1.0;
        active_host->audio_upsample_previous_left = left;
        active_host->audio_upsample_previous_right = right;
        return;
    }
    push_audio_sample(left);
    push_audio_sample(right);
}

static void audio_sample_callback(int16_t left, int16_t right) {
    push_audio_frame(left, right);
}

static size_t audio_batch_callback(const int16_t *data, size_t frames) {
    size_t index;
    if (!data || frames > SIZE_MAX / 2) return 0;
    for (index = 0; index < frames; index++)
        push_audio_frame(data[index * 2], data[index * 2 + 1]);
    return frames;
}

static void input_poll_callback(void) {}

static int16_t input_state_callback(unsigned port, unsigned device,
                                    unsigned index, unsigned id) {
    if (!active_host || port >= MAX_PORTS) return 0;
    if (device == RETRO_DEVICE_JOYPAD) {
        int16_t result;
        if (id == RETRO_DEVICE_ID_JOYPAD_MASK)
            result = (int16_t)(active_host->joypad_mask[port] & 0xffffu);
        else {
            if (id >= MAX_JOYPAD_BUTTONS) return 0;
            result = (active_host->joypad_mask[port] & (1u << id)) ? 1 : 0;
        }
#if defined(__ANDROID__)
        if (active_host->hw_negotiated &&
                (id == RETRO_DEVICE_ID_JOYPAD_START ||
                 id == RETRO_DEVICE_ID_JOYPAD_A ||
                 id == RETRO_DEVICE_ID_JOYPAD_MASK) &&
                (active_host->input_trace_transition_count < 16u ||
                 active_host->input_trace_sample_count < 32u)) {
            uint32_t tracked = (1u << RETRO_DEVICE_ID_JOYPAD_START) |
                    (1u << RETRO_DEVICE_ID_JOYPAD_A);
            uint32_t queried = id == RETRO_DEVICE_ID_JOYPAD_MASK ?
                    tracked : (1u << id);
            uint32_t mask = active_host->joypad_mask[port];
            bool changed = ((active_host->input_trace_read_mask[port] ^ mask) &
                    queried) != 0;
            const char *kind = NULL;
            active_host->input_trace_read_mask[port] =
                    (active_host->input_trace_read_mask[port] & ~queried) |
                    (mask & queried);
            if (changed && active_host->input_trace_transition_count < 16u) {
                ++active_host->input_trace_transition_count;
                kind = "transition";
            } else if ((mask & queried) &&
                    active_host->input_trace_sample_count < 32u &&
                    active_host->input_trace_last_sample_run !=
                            active_host->run_sequence) {
                ++active_host->input_trace_sample_count;
                active_host->input_trace_last_sample_run = active_host->run_sequence;
                kind = "held-sample";
            }
            if (kind) {
                __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
                        "input callback host=%p run=%llu port=%u device=%u "
                        "index=%u id=%u result=%d mask=0x%04x kind=%s "
                        "transitions=%u/16 samples=%u/32 marker=input-consumed",
                        (void *)active_host,
                        (unsigned long long)active_host->run_sequence,
                        port, device, index, id, (int)result, (unsigned)mask,
                        kind, active_host->input_trace_transition_count,
                        active_host->input_trace_sample_count);
            }
        }
#endif
        return result;
    }
    if (device == RETRO_DEVICE_ANALOG && index < MAX_ANALOG_INDEXES &&
            id < MAX_ANALOG_IDS) {
        if (index < RETRO_DEVICE_INDEX_ANALOG_BUTTON && id > RETRO_DEVICE_ID_ANALOG_Y)
            return 0;
        return active_host->analog_state[port][index][id];
    }
    if (device == RETRO_DEVICE_POINTER) {
        if (id == RETRO_DEVICE_ID_POINTER_X) return active_host->pointer_x[port];
        if (id == RETRO_DEVICE_ID_POINTER_Y) return active_host->pointer_y[port];
        if (id == RETRO_DEVICE_ID_POINTER_PRESSED) {
#if defined(__ANDROID__)
            /* Snapshot the coordinate tuple only on observed press/release
             * edges. Idle/held polling cannot exhaust the release budget. */
            if (active_host->hw_negotiated &&
                    active_host->pointer_trace_callback_count < 12u &&
                    active_host->pointer_trace_read_pressed[port] !=
                            active_host->pointer_pressed[port]) {
                active_host->pointer_trace_read_pressed[port] =
                        active_host->pointer_pressed[port];
                ++active_host->pointer_trace_callback_count;
                __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
                        "pointer callback host=%p run=%llu port=%u index=%u "
                        "x=%d y=%d pressed=%d sample=%u/12 marker=pointer-consumed",
                        (void *)active_host,
                        (unsigned long long)active_host->run_sequence, port, index,
                        (int)active_host->pointer_x[port],
                        (int)active_host->pointer_y[port],
                        active_host->pointer_pressed[port] ? 1 : 0,
                        active_host->pointer_trace_callback_count);
            }
#endif
            return active_host->pointer_pressed[port] ? 1 : 0;
        }
    }
    return 0;
}

static bool resolve_symbol(void *library, const char *name, void *target,
                           char *error, size_t error_size) {
    void *symbol;
    dlerror();
    symbol = dlsym(library, name);
    const char *failure = dlerror();
    if (failure || !symbol) {
        set_error(error, error_size, "required core symbol %s is missing", name);
        return false;
    }
    memcpy(target, &symbol, sizeof(symbol));
    return true;
}

static void resolve_optional_symbol(void *library, const char *name, void *target) {
    void *symbol;
    dlerror();
    symbol = dlsym(library, name);
    if (dlerror()) symbol = NULL;
    memcpy(target, &symbol, sizeof(symbol));
}

#define RESOLVE(host, field, symbol) \
    if (!resolve_symbol((host)->library, symbol, &(host)->field, error, error_size)) goto fail

static bool validate_hw_options(const lucent_retro_hw_options *options,
                                char *error, size_t error_size) {
    const uint32_t contexts = LUCENT_RETRO_HW_GLES2 | LUCENT_RETRO_HW_GLES3 |
            LUCENT_RETRO_HW_GLES_VERSION | LUCENT_RETRO_HW_VULKAN;
    const uint32_t features = LUCENT_RETRO_HW_DEPTH | LUCENT_RETRO_HW_STENCIL |
            LUCENT_RETRO_HW_CACHE_CONTEXT | LUCENT_RETRO_HW_DEBUG_CONTEXT |
            LUCENT_RETRO_HW_SHARED_CONTEXT;
    const struct retro_hw_render_interface *render_interface;
    if (!options) return true;
    if (options->struct_size != sizeof(*options) ||
            options->api_version != LUCENT_RETRO_HW_OPTIONS_VERSION) {
        set_error(error, error_size, "unsupported hardware options layout/version");
        return false;
    }
    if (options->source_timeline_policy &
            ~(uint32_t)(LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_VI_ORIGIN |
                    LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS)) {
        set_error(error, error_size, "unknown source timeline policy");
        return false;
    }
    if (!options->context_capabilities ||
            (options->context_capabilities & ~contexts) ||
            (options->feature_capabilities & ~features) ||
            !options->preferred_context ||
            (options->preferred_context & (options->preferred_context - 1u)) ||
            !(options->context_capabilities & options->preferred_context)) {
        set_error(error, error_size, "hardware capabilities and preferred context are invalid");
        return false;
    }
    if ((options->context_capabilities &
            (LUCENT_RETRO_HW_GLES2 | LUCENT_RETRO_HW_GLES3 |
             LUCENT_RETRO_HW_GLES_VERSION)) &&
            (!options->get_current_framebuffer || !options->get_proc_address)) {
        set_error(error, error_size, "GLES requires framebuffer and proc-address hooks");
        return false;
    }
    if ((options->context_capabilities & LUCENT_RETRO_HW_GLES_VERSION) &&
            (options->max_gles_major < 3 ||
             (options->max_gles_major == 3 && options->max_gles_minor < 1))) {
        set_error(error, error_size, "versioned GLES capability requires GLES 3.1 or newer");
        return false;
    }
    if (options->context_capabilities & LUCENT_RETRO_HW_VULKAN) {
        render_interface = (const struct retro_hw_render_interface *)
                options->render_interface;
        if (!render_interface ||
                render_interface->interface_type != RETRO_HW_RENDER_INTERFACE_VULKAN ||
                !render_interface->interface_version) {
            set_error(error, error_size, "Vulkan requires a versioned Vulkan render interface");
            return false;
        }
    }
    return true;
}

lucent_retro_host *lucent_retro_create_with_preferences(
        const char *core_path, const char *trusted_root,
        const char *system_directory, const char *save_directory,
        const lucent_retro_hw_options *hw_options,
        bool widescreen_enhancements_enabled,
        char *error, size_t error_size) {
    char resolved_core[4096];
    char resolved_root[4096];
    lucent_retro_host *host = NULL;
    lock_host();
    if (!core_path || !trusted_root || !system_directory || !save_directory) {
        set_error(error, error_size, "core, trusted root, system, and save paths are required");
        RETURN_UNLOCKED(NULL);
    }
    if (!validate_hw_options(hw_options, error, error_size)) RETURN_UNLOCKED(NULL);
    if (active_host) {
        set_error(error, error_size, "only one Lucent core session may be active");
        RETURN_UNLOCKED(NULL);
    }
    if (!realpath(core_path, resolved_core) || !realpath(trusted_root, resolved_root)) {
        set_error(error, error_size, "cannot resolve trusted core path: %s", strerror(errno));
        RETURN_UNLOCKED(NULL);
    }
    if (strcmp(resolved_root, "/") == 0 || !path_is_inside(resolved_core, resolved_root)) {
        set_error(error, error_size, "core must be inside Lucent's trusted app-private directory");
        RETURN_UNLOCKED(NULL);
    }
    host = (lucent_retro_host *)calloc(1, sizeof(*host));
    if (!host) {
        set_error(error, error_size, "out of memory creating core host");
        RETURN_UNLOCKED(NULL);
    }
    if (hw_options) {
        host->hw_options = *hw_options;
        host->hw_configured = true;
    }
    host->widescreen_enhancements_enabled =
            widescreen_enhancements_enabled;
    host->core_path = strdup(resolved_core);
    host->system_directory = strdup(system_directory);
    host->save_directory = strdup(save_directory);
    host->pixel_format = RETRO_PIXEL_FORMAT_0RGB1555;
    host->audio_ring = (int16_t *)calloc(AUDIO_RING_SAMPLES, sizeof(int16_t));
    if (!host->core_path || !host->system_directory || !host->save_directory ||
            !host->audio_ring) {
        set_error(error, error_size, "out of memory copying core paths");
        goto fail;
    }
    load_core_overrides(host);
    {
        bool force_fresh_dolphin =
                is_dolphin_core_path(host->core_path) &&
                dolphin_mapping_quarantined;
#if defined(__ANDROID__)
        if (force_fresh_dolphin)
            __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
                    "forcing fresh Dolphin linker image after quarantine");
#endif
        host->library = load_core_library(host->core_path, force_fresh_dolphin);
    }
    if (!host->library) {
        set_error(error, error_size, "cannot load core: %s", dlerror());
        goto fail;
    }
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
            "core library loaded path=%s", host->core_path);
#endif
    RESOLVE(host, init, "retro_init");
    RESOLVE(host, deinit, "retro_deinit");
    RESOLVE(host, api_version, "retro_api_version");
    RESOLVE(host, get_system_info, "retro_get_system_info");
    RESOLVE(host, get_system_av_info, "retro_get_system_av_info");
    RESOLVE(host, set_environment, "retro_set_environment");
    RESOLVE(host, set_video_refresh, "retro_set_video_refresh");
    RESOLVE(host, set_audio_sample, "retro_set_audio_sample");
    RESOLVE(host, set_audio_sample_batch, "retro_set_audio_sample_batch");
    RESOLVE(host, set_input_poll, "retro_set_input_poll");
    RESOLVE(host, set_input_state, "retro_set_input_state");
    RESOLVE(host, set_controller_port_device, "retro_set_controller_port_device");
    RESOLVE(host, reset, "retro_reset");
    RESOLVE(host, run, "retro_run");
    RESOLVE(host, serialize_size, "retro_serialize_size");
    RESOLVE(host, serialize, "retro_serialize");
    RESOLVE(host, unserialize, "retro_unserialize");
    RESOLVE(host, cheat_reset, "retro_cheat_reset");
    RESOLVE(host, cheat_set, "retro_cheat_set");
    RESOLVE(host, load_game, "retro_load_game");
    RESOLVE(host, load_game_special, "retro_load_game_special");
    RESOLVE(host, unload_game, "retro_unload_game");
    resolve_optional_symbol(host->library, "retro_lucent_prepare_exit_autosave",
                            &host->prepare_exit);
    RESOLVE(host, get_region, "retro_get_region");
    RESOLVE(host, get_memory_data, "retro_get_memory_data");
    RESOLVE(host, get_memory_size, "retro_get_memory_size");
    resolve_optional_symbol(
            host->library,
            "retro_lucent_mupen_current_run_has_vi_origin_change",
            &host->mupen_vi_origin_boundary);
    resolve_optional_symbol(host->library, "retro_lucent_get_hw_active_rect",
                            &host->hw_active_rect);
    if ((host->hw_options.source_timeline_policy &
                    LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_VI_ORIGIN) &&
            !host->mupen_vi_origin_boundary) {
        set_error(error, error_size,
                  "Mupen VI-origin timeline marker is unavailable");
        goto fail;
    }
    if (host->api_version() != RETRO_API_VERSION) {
        set_error(error, error_size, "unsupported libretro API %u (expected %u)",
                  host->api_version(), RETRO_API_VERSION);
        goto fail;
    }
    active_host = host;
    host->set_environment(environment_callback);
    host->get_system_info(&host->system_info);
    /*
     * Mesen and Mesen-S allocate the objects used by their callback setters in
     * retro_init(). Register the environment first (cores may query it during
     * initialization), initialize the core, and only then register the media
     * and input callbacks. The Phase 1 core probe uses the same ordering.
     */
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost", "retro_init begin");
#endif
    host->init();
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost", "retro_init complete");
#endif
    host->initialized = true;
    host->set_video_refresh(video_callback);
    host->set_audio_sample(audio_sample_callback);
    host->set_audio_sample_batch(audio_batch_callback);
    host->set_input_poll(input_poll_callback);
    host->set_input_state(input_state_callback);
    RETURN_UNLOCKED(host);

fail:
    lucent_retro_destroy(host);
    RETURN_UNLOCKED(NULL);
}

lucent_retro_host *lucent_retro_create_with_options(
        const char *core_path, const char *trusted_root,
        const char *system_directory, const char *save_directory,
        const lucent_retro_hw_options *hw_options,
        char *error, size_t error_size) {
    return lucent_retro_create_with_preferences(
            core_path, trusted_root, system_directory, save_directory,
            hw_options, true, error, error_size);
}

lucent_retro_host *lucent_retro_create(const char *core_path,
                                       const char *trusted_root,
                                       const char *system_directory,
                                       const char *save_directory,
                                       char *error, size_t error_size) {
    return lucent_retro_create_with_options(
            core_path, trusted_root, system_directory, save_directory,
            NULL, error, error_size);
}

bool lucent_retro_supply_android_java_vm(lucent_retro_host *host, void *java_vm,
                                         char *error, size_t error_size) {
    static const char play_setter_name[] = "lucent_set_android_java_vm";
    fn_set_android_java_vm setter = NULL;
    void *symbol;
    lock_host();
    if (!host || !host->library || !java_vm) {
        set_error(error, error_size, "valid host and JavaVM are required");
        RETURN_UNLOCKED(false);
    }
    dlerror();
    symbol = dlsym(host->library, play_setter_name);
    if (!symbol) {
        /* This hook is optional and deliberately invisible to normal cores. */
#if defined(__ANDROID__)
        __android_log_print(ANDROID_LOG_WARN, "LucentNativeHost",
                "optional Android JavaVM hook unavailable: %s", dlerror());
#else
        fprintf(stderr, "Lucent optional Android JavaVM hook unavailable: %s\n",
                dlerror());
#endif
        RETURN_UNLOCKED(true);
    }
    memcpy(&setter, &symbol, sizeof(setter));
    setter(java_vm);
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
            "supplied Android JavaVM %p to optional core hook %p", java_vm, symbol);
#else
    fprintf(stderr, "Lucent supplied Android JavaVM %p to optional core hook %p\n",
            java_vm, symbol);
#endif
    RETURN_UNLOCKED(true);
}

bool lucent_retro_supply_output_size(lucent_retro_host *host,
                                     unsigned width, unsigned height,
                                     char *error, size_t error_size) {
    static const char setter_name[] = "lucent_set_output_size";
    fn_set_output_size setter = NULL;
    void *symbol;
    lock_host();
    if (!host || !host->library || !width || !height) {
        set_error(error, error_size, "valid host and output size are required");
        RETURN_UNLOCKED(false);
    }
    dlerror();
    symbol = dlsym(host->library, setter_name);
    if (!symbol) RETURN_UNLOCKED(true);
    memcpy(&setter, &symbol, sizeof(setter));
    setter(width, height);
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
            "supplied output size %ux%u to optional core hook", width, height);
#endif
    RETURN_UNLOCKED(true);
}

bool lucent_retro_supply_frontend_framebuffer(lucent_retro_host *host,
                                              unsigned framebuffer,
                                              char *error,
                                              size_t error_size) {
    static const char setter_name[] = "lucent_set_frontend_framebuffer";
    fn_set_frontend_framebuffer setter = NULL;
    void *symbol;
    lock_host();
    if (!host || !host->library) {
        set_error(error, error_size, "valid host is required");
        RETURN_UNLOCKED(false);
    }
    dlerror();
    symbol = dlsym(host->library, setter_name);
    if (!symbol) RETURN_UNLOCKED(true);
    memcpy(&setter, &symbol, sizeof(setter));
    setter(framebuffer);
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
            "supplied frontend framebuffer %u to optional core hook",
            framebuffer);
#endif
    RETURN_UNLOCKED(true);
}

static bool read_game(const char *path, char **bytes, size_t *size,
                      char *error, size_t error_size) {
    struct stat metadata;
    FILE *file;
    if (stat(path, &metadata) != 0 || metadata.st_size < 0) {
        set_error(error, error_size, "cannot stat game: %s", strerror(errno));
        return false;
    }
    if ((uintmax_t)metadata.st_size > SIZE_MAX ||
            (uintmax_t)metadata.st_size > MAX_GAME_BYTES) {
        set_error(error, error_size, "game is too large for this process");
        return false;
    }
    file = fopen(path, "rb");
    if (!file) {
        set_error(error, error_size, "cannot open game: %s", strerror(errno));
        return false;
    }
    *size = (size_t)metadata.st_size;
    *bytes = (char *)malloc(*size ? *size : 1);
    if (!*bytes || (*size && fread(*bytes, 1, *size, file) != *size)) {
        set_error(error, error_size, "cannot read game content");
        free(*bytes);
        *bytes = NULL;
        fclose(file);
        return false;
    }
    fclose(file);
    return true;
}

bool lucent_retro_load_game(lucent_retro_host *host, const char *game_path,
                            char *error, size_t error_size) {
    struct retro_game_info game;
    lock_host();
    if (!host || !game_path || host->game_loaded) {
        set_error(error, error_size, "host must be valid and unloaded before loading a game");
        RETURN_UNLOCKED(false);
    }
    memset(&game, 0, sizeof(game));
    game.path = game_path;
    if (!host->system_info.need_fullpath) {
        if (!read_game(game_path, &host->game_bytes, &host->game_size, error, error_size))
            RETURN_UNLOCKED(false);
        game.data = host->game_bytes;
        game.size = host->game_size;
    }
    active_host = host;
    host->run_sequence = 0;
    /* A host may be reused after an orderly unload. From this point onward a
     * rejection belongs to the new attempt and must not inherit the previous
     * title's successful-load evidence. */
    host->completed_game_load = false;
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
            "retro_load_game begin path=%s needFullpath=%d", game_path,
            host->system_info.need_fullpath ? 1 : 0);
#endif
    if (!host->load_game(&game)) {
        set_error(error, error_size, "core rejected game content");
        free(host->game_bytes);
        host->game_bytes = NULL;
        host->game_size = 0;
        host->hw_negotiated = false;
        host->hw_context_ready = false;
        memset(&host->hw_callback, 0, sizeof(host->hw_callback));
        RETURN_UNLOCKED(false);
    }
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
            "retro_load_game complete");
#endif
    host->game_loaded = true;
    host->completed_game_load = true;
    host->set_controller_port_device(0, RETRO_DEVICE_JOYPAD);
    memset(&host->current_av_info, 0, sizeof(host->current_av_info));
    host->get_system_av_info(&host->current_av_info);
    host->audio_input_rate = host->current_av_info.timing.sample_rate;
    host->audio_output_rate = host->audio_input_rate > 192000.0
            ? 48000.0 : host->audio_input_rate;
    correct_known_core_timing(host);
    host->audio_timing_multiplier = 1.0;
    reset_audio_resampler(host);
    host->current_av_info.timing.sample_rate = host->audio_output_rate;
    host->has_av_info = true;
    RETURN_UNLOCKED(true);
}

bool lucent_retro_set_controller_port_device(lucent_retro_host *host,
                                             unsigned port, unsigned device,
                                             char *error, size_t error_size) {
    lock_host();
    if (!host || !host->game_loaded || !host->set_controller_port_device) {
        set_error(error, error_size, "no loaded core to configure a port on");
        RETURN_UNLOCKED(false);
    }
    if (port >= MAX_PORTS) {
        set_error(error, error_size, "controller port %u is out of range", port);
        RETURN_UNLOCKED(false);
    }
    host->set_controller_port_device(port, device);
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
            "controller port %u device 0x%x", port, device);
#endif
    RETURN_UNLOCKED(true);
}

bool lucent_retro_cheat_reset(lucent_retro_host *host, char *error,
                              size_t error_size) {
    lock_host();
    if (!host || !host->game_loaded || !host->cheat_reset) {
        set_error(error, error_size, "a loaded core session is required");
        RETURN_UNLOCKED(false);
    }
    /*
     * Cores are free to touch memory maps and emit log callbacks from inside
     * cheat calls, so the callback owner must be this host first -- the same
     * contract retro_reset above documents.
     */
    active_host = host;
    host->cheat_reset();
    RETURN_UNLOCKED(true);
}

bool lucent_retro_cheat_set(lucent_retro_host *host, unsigned index,
                            bool enabled, const char *code, char *error,
                            size_t error_size) {
    lock_host();
    if (!host || !host->game_loaded || !host->cheat_set) {
        set_error(error, error_size, "a loaded core session is required");
        RETURN_UNLOCKED(false);
    }
    if (!code || code[0] == '\0') {
        set_error(error, error_size, "a cheat code is required");
        RETURN_UNLOCKED(false);
    }
    active_host = host;
    host->cheat_set(index, enabled, code);
    RETURN_UNLOCKED(true);
}

bool lucent_retro_reset(lucent_retro_host *host, char *error,
                        size_t error_size) {
    lock_host();
    if (!host || !host->game_loaded || !host->reset) {
        set_error(error, error_size, "a loaded core session is required");
        RETURN_UNLOCKED(false);
    }
    /*
     * retro_reset re-enters the frontend the way retro_run does: cores are
     * free to emit a boot frame or flush audio from inside it, so the
     * callback owner must be this host before the call.
     */
    active_host = host;
    host->reset();
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
            "retro_reset complete");
#endif
    RETURN_UNLOCKED(true);
}

bool lucent_retro_unload_game(lucent_retro_host *host,
                              char *error, size_t error_size) {
    lock_host();
    if (!host || !host->game_loaded || !host->unload_game) {
        set_error(error, error_size, "a loaded core session is required");
        RETURN_UNLOCKED(false);
    }
    active_host = host;
    if (host->prepare_exit && !host->prepare_exit()) {
        set_error(error, error_size,
                  "core could not safely save progress; game remains loaded");
        RETURN_UNLOCKED(false);
    }
    host->unload_game();
    host->game_loaded = false;
    host->has_av_info = false;
    free(host->game_bytes);
    host->game_bytes = NULL;
    host->game_size = 0;
    RETURN_UNLOCKED(true);
}

bool lucent_retro_game_loaded(const lucent_retro_host *host) {
    bool loaded;
    lock_host();
    loaded = host && host->game_loaded;
    RETURN_UNLOCKED(loaded);
}

bool lucent_retro_run_frame(lucent_retro_host *host, char *error,
                            size_t error_size) {
    lock_host();
    if (!host || !host->game_loaded) {
        set_error(error, error_size, "cannot run without a loaded game");
        RETURN_UNLOCKED(false);
    }
    if (host->hw_negotiated && !host->hw_context_ready) {
        set_error(error, error_size, "hardware context is not ready");
        RETURN_UNLOCKED(false);
    }
    if (host->paused) RETURN_UNLOCKED(true);
    active_host = host;
    if (host->run_sequence != UINT64_MAX) ++host->run_sequence;
    host->run_audio_output_samples = 0;
    host->run();
    RETURN_UNLOCKED(true);
}

uint64_t lucent_retro_last_run_audio_duration_ns(lucent_retro_host *host) {
    uint64_t duration = 0;
    lock_host();
    if (host && host->game_loaded && isfinite(host->audio_output_rate) &&
            host->audio_output_rate >= 8000.0) {
        /* Count after the existing tiny console/display resampling ratio.
         * Thus this is sink-clock time, not a second gameplay speed change. */
        duration = (uint64_t)((double)(host->run_audio_output_samples / 2) *
                1000000000.0 / host->audio_output_rate);
    }
    RETURN_UNLOCKED(duration);
}

void lucent_retro_set_paused(lucent_retro_host *host, bool paused) {
    lock_host();
    if (host) host->paused = paused;
    unlock_host();
}

bool lucent_retro_set_joypad_button(lucent_retro_host *host, unsigned port,
                                    unsigned button, bool pressed) {
    lock_host();
    if (!host || port >= MAX_PORTS || button >= MAX_JOYPAD_BUTTONS)
        RETURN_UNLOCKED(false);
#if defined(__ANDROID__)
    uint32_t previous_mask = host->joypad_mask[port];
#endif
    if (pressed) host->joypad_mask[port] |= 1u << button;
    else host->joypad_mask[port] &= ~(1u << button);
#if defined(__ANDROID__)
    if (host->hw_negotiated && host->input_trace_applied_count < 16u &&
            (button == RETRO_DEVICE_ID_JOYPAD_START ||
             button == RETRO_DEVICE_ID_JOYPAD_A) &&
            previous_mask != host->joypad_mask[port]) {
        ++host->input_trace_applied_count;
        __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
                "input applied host=%p run=%llu port=%u id=%u pressed=%d "
                "mask=0x%04x event=%u/16 marker=input-applied",
                (void *)host, (unsigned long long)host->run_sequence,
                port, button, pressed ? 1 : 0, (unsigned)host->joypad_mask[port],
                host->input_trace_applied_count);
    }
#endif
    RETURN_UNLOCKED(true);
}

bool lucent_retro_set_analog_axis(lucent_retro_host *host, unsigned port,
                                  unsigned index, unsigned id, int16_t value) {
    lock_host();
    if (!host || port >= MAX_PORTS || index >= MAX_ANALOG_INDEXES ||
            id >= MAX_ANALOG_IDS) RETURN_UNLOCKED(false);
    if (index < RETRO_DEVICE_INDEX_ANALOG_BUTTON && id > RETRO_DEVICE_ID_ANALOG_Y)
        RETURN_UNLOCKED(false);
    host->analog_state[port][index][id] = value;
    RETURN_UNLOCKED(true);
}

bool lucent_retro_set_pointer(lucent_retro_host *host, unsigned port,
                              int16_t x, int16_t y, bool pressed) {
    lock_host();
    if (!host || port >= MAX_PORTS) RETURN_UNLOCKED(false);
#if defined(__ANDROID__)
    bool previous_pressed = host->pointer_pressed[port];
#endif
    host->pointer_x[port] = x;
    host->pointer_y[port] = y;
    host->pointer_pressed[port] = pressed;
#if defined(__ANDROID__)
    if (host->hw_negotiated && host->pointer_trace_applied_count < 12u &&
            previous_pressed != pressed) {
        ++host->pointer_trace_applied_count;
        __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
                "pointer applied host=%p run=%llu port=%u x=%d y=%d "
                "pressed=%d event=%u/12 marker=pointer-applied",
                (void *)host, (unsigned long long)host->run_sequence,
                port, (int)x, (int)y, pressed ? 1 : 0,
                host->pointer_trace_applied_count);
    }
#endif
    RETURN_UNLOCKED(true);
}

bool lucent_retro_latest_video_info(const lucent_retro_host *host,
                                    lucent_retro_video_info *info) {
    lock_host();
    if (!host || !info || !host->video_bytes || !host->video_size)
        RETURN_UNLOCKED(false);
    info->width = host->video_width;
    info->height = host->video_height;
    info->pitch = host->video_pitch;
    info->pixel_format = (unsigned)host->pixel_format;
    info->byte_size = host->video_size;
    info->sequence = host->video_sequence;
    RETURN_UNLOCKED(true);
}

bool lucent_retro_copy_video_frame(const lucent_retro_host *host, void *buffer,
                                   size_t size) {
    lock_host();
    if (!host || !buffer || !host->video_bytes || size < host->video_size)
        RETURN_UNLOCKED(false);
    memcpy(buffer, host->video_bytes, host->video_size);
    RETURN_UNLOCKED(true);
}

size_t lucent_retro_drain_audio(lucent_retro_host *host, int16_t *samples,
                                size_t max_frames) {
    size_t available_samples;
    size_t index;
    lock_host();
    if (!host || !samples || !max_frames || max_frames > SIZE_MAX / 2)
        RETURN_UNLOCKED(0);
    available_samples = host->audio_count - (host->audio_count % 2);
    if (available_samples > max_frames * 2) available_samples = max_frames * 2;
    for (index = 0; index < available_samples; index++) {
        samples[index] = host->audio_ring[host->audio_read];
        host->audio_read = (host->audio_read + 1) % AUDIO_RING_SAMPLES;
    }
    host->audio_count -= available_samples;
    RETURN_UNLOCKED(available_samples / 2);
}

bool lucent_retro_get_av_info(lucent_retro_host *host,
                              lucent_retro_av_info *info) {
    lock_host();
    if (!host || !info || !host->game_loaded) RETURN_UNLOCKED(false);
    if (!host->has_av_info) RETURN_UNLOCKED(false);
    info->base_width = host->current_av_info.geometry.base_width;
    info->base_height = host->current_av_info.geometry.base_height;
    info->max_width = host->current_av_info.geometry.max_width;
    info->max_height = host->current_av_info.geometry.max_height;
    info->aspect_ratio = host->current_av_info.geometry.aspect_ratio;
    info->frames_per_second = host->current_av_info.timing.fps;
    info->sample_rate = host->current_av_info.timing.sample_rate;
    RETURN_UNLOCKED(true);
}

double lucent_retro_synchronized_video_hz(lucent_retro_host *host) {
    double declared;
    double multiplier;
    lock_host();
    if (!host || !host->game_loaded || !host->has_av_info) RETURN_UNLOCKED(0.0);
    declared = host->current_av_info.timing.fps;
    multiplier = host->audio_timing_multiplier > 0.0 ?
            host->audio_timing_multiplier : 1.0;
    RETURN_UNLOCKED(declared * multiplier);
}

bool lucent_retro_set_synchronized_video_rate(
        lucent_retro_host *host, double declared_hz, double synchronized_hz,
        char *error, size_t error_size) {
    lock_host();
    if (!host || !host->game_loaded || !isfinite(declared_hz) ||
            !isfinite(synchronized_hz) || declared_hz <= 1.0 ||
            declared_hz >= 1000.0 || synchronized_hz <= 1.0 ||
            synchronized_hz >= 1000.0) {
        set_error(error, error_size,
                  "valid loaded host and video clocks are required");
        RETURN_UNLOCKED(false);
    }
    double previous = host->audio_timing_multiplier;
    double next = synchronized_hz / declared_hz;
    if (previous != next) {
        double previous_input = host->audio_input_rate * previous;
        double next_input = host->audio_input_rate * next;
        bool same_downsample = previous_input > host->audio_output_rate &&
                next_input > host->audio_output_rate;
        bool same_upsample = previous_input < host->audio_output_rate &&
                next_input < host->audio_output_rate;
        if (same_downsample) {
            /* Preserve the fractional output phase and accumulated PCM when
             * following small measured display-clock trims during gameplay. */
            host->audio_resample_accumulator *= next / previous;
        } else if (!same_upsample) {
            reset_audio_resampler(host);
        }
        host->audio_timing_multiplier = next;
    }
    RETURN_UNLOCKED(true);
}

bool lucent_retro_get_hw_active_rect(lucent_retro_host *host, uint32_t rect[7]) {
    uint32_t value[7] = {0};
    lock_host();
    if (!host || !rect || !host->game_loaded || !host->hw_context_ready ||
            !(host->hw_options.source_timeline_policy &
              LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS) ||
            !host->hw_active_rect || !host->hw_active_rect(value, 7u) ||
            value[0] != 1u || !value[3] || !value[4] ||
            !value[5] || !value[6] || value[1] >= value[5] ||
            value[2] >= value[6] || value[3] > value[5] - value[1] ||
            value[4] > value[6] - value[2]) RETURN_UNLOCKED(false);
    memcpy(rect, value, sizeof(value));
    RETURN_UNLOCKED(true);
}

bool lucent_retro_get_hw_info(lucent_retro_host *host,
                              lucent_retro_hw_info *info) {
    lock_host();
    if (!host || !info) RETURN_UNLOCKED(false);
    memset(info, 0, sizeof(*info));
    info->negotiated = host->hw_negotiated;
    info->context_ready = host->hw_context_ready;
    info->source_timeline_policy = host->hw_options.source_timeline_policy;
    if (host->hw_negotiated) {
        info->context_type = (unsigned)host->hw_callback.context_type;
        info->version_major = host->hw_callback.version_major;
        info->version_minor = host->hw_callback.version_minor;
        info->depth = host->hw_callback.depth;
        info->stencil = host->hw_callback.stencil;
        info->bottom_left_origin = host->hw_callback.bottom_left_origin;
        info->cache_context = host->hw_callback.cache_context;
        info->debug_context = host->hw_callback.debug_context;
        info->frame_sequence = host->hw_frame_sequence;
        info->frame_width = host->hw_frame_width;
        info->frame_height = host->hw_frame_height;
    }
    RETURN_UNLOCKED(true);
}

const void *lucent_retro_hw_context_negotiation_interface(
        lucent_retro_host *host) {
    const void *result;
    lock_host();
    result = host ? (const void *)host->hw_context_negotiation_interface : NULL;
    RETURN_UNLOCKED(result);
}

bool lucent_retro_hw_context_reset(lucent_retro_host *host,
                                   char *error, size_t error_size) {
    lock_host();
    if (!host || !host->game_loaded || !host->hw_negotiated ||
            !host->hw_callback.context_reset) {
        set_error(error, error_size, "a loaded negotiated hardware core is required");
        RETURN_UNLOCKED(false);
    }
    if (host->hw_context_ready) {
        set_error(error, error_size,
                  "hardware context must be destroyed or lost before reset");
        RETURN_UNLOCKED(false);
    }
    active_host = host;
    host->hw_context_ready = true;
    host->hw_callback.context_reset();
    RETURN_UNLOCKED(true);
}

bool lucent_retro_hw_context_destroy(lucent_retro_host *host,
                                     char *error, size_t error_size) {
    lock_host();
    if (!host || !host->hw_negotiated) {
        set_error(error, error_size, "a negotiated hardware core is required");
        RETURN_UNLOCKED(false);
    }
    if (!host->hw_context_ready) RETURN_UNLOCKED(true);
    active_host = host;
    if (host->hw_callback.context_destroy)
        host->hw_callback.context_destroy();
    host->hw_context_ready = false;
    RETURN_UNLOCKED(true);
}

bool lucent_retro_hw_context_lost(lucent_retro_host *host,
                                  char *error, size_t error_size) {
    lock_host();
    if (!host || !host->hw_negotiated) {
        set_error(error, error_size, "a negotiated hardware core is required");
        RETURN_UNLOCKED(false);
    }
    /* context_destroy may execute arbitrary GL/Vulkan work. Calling it after
     * EGL_CONTEXT_LOST (or the Vulkan equivalent) is unsafe, so loss is a
     * distinct transition from an orderly surface detach. */
    host->hw_context_ready = false;
    RETURN_UNLOCKED(true);
}

size_t lucent_retro_serialize_size(lucent_retro_host *host) {
    size_t size;
    lock_host();
    if (!host || !host->game_loaded) RETURN_UNLOCKED(0);
    /* State callbacks can restart a core's graphics worker (PPSSPP does so
     * even while sizing a state). A detached/lost context is not usable just
     * because the guest remains loaded. Software cores have no such gate. */
    if (host->hw_negotiated && !host->hw_context_ready) RETURN_UNLOCKED(0);
    active_host = host;
    size = host->serialize_size();
    RETURN_UNLOCKED(size <= MAX_STATE_BYTES ? size : 0);
}

bool lucent_retro_serialize_alloc(lucent_retro_host *host, void **buffer,
                                  size_t *size, char *error,
                                  size_t error_size) {
    void *bytes;
    size_t required;
    unsigned attempt;
    lock_host();
    if (buffer) *buffer = NULL;
    if (size) *size = 0;
    if (!host || !host->game_loaded || !buffer || !size) {
        set_error(error, error_size, "valid loaded host and output pointers are required");
        RETURN_UNLOCKED(false);
    }
    if (host->hw_negotiated && !host->hw_context_ready) {
        set_error(error, error_size, "hardware context is not ready for state capture");
        RETURN_UNLOCKED(false);
    }
    active_host = host;
    required = host->serialize_size();
    if (!required || required > MAX_STATE_BYTES) {
        set_error(error, error_size, "core does not expose a usable serialized state");
        RETURN_UNLOCKED(false);
    }
    for (attempt = 0; attempt < 3; ++attempt) {
        bytes = malloc(required);
        if (!bytes) {
            set_error(error, error_size, "out of memory serializing core state");
            RETURN_UNLOCKED(false);
        }
        if (host->serialize(bytes, required)) {
            *buffer = bytes;
            *size = required;
            RETURN_UNLOCKED(true);
        }
        free(bytes);
        if (attempt < 2) {
            /* The host lock excludes frontend run calls, but cannot stop a
             * core's own worker. Flycast resumes that worker after sizing
             * a state. Retry only a freshly demonstrated size increase,
             * never a stable-size failure or an unbounded allocation. */
            size_t next = host->serialize_size();
            if (next <= required || next > MAX_STATE_BYTES) break;
#if defined(__ANDROID__)
            __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
                    "State capture size grew from %zu to %zu; retry %u/2",
                    required, next, attempt + 1);
#endif
            required = next;
        }
    }
    set_error(error, error_size, "core failed to serialize state");
    RETURN_UNLOCKED(false);
}

bool lucent_retro_serialize(lucent_retro_host *host, void *buffer, size_t size,
                            char *error, size_t error_size) {
    lock_host();
    size_t required = lucent_retro_serialize_size(host);
    if (!required || !buffer || size != required) {
        set_error(error, error_size, "state buffer size mismatch");
        RETURN_UNLOCKED(false);
    }
    active_host = host;
    if (!host->serialize(buffer, size)) {
        set_error(error, error_size, "core failed to serialize state");
        RETURN_UNLOCKED(false);
    }
    RETURN_UNLOCKED(true);
}

bool lucent_retro_unserialize(lucent_retro_host *host, const void *buffer,
                              size_t size, char *error, size_t error_size) {
    lock_host();
    if (!host || !host->game_loaded || !buffer || !size || size > MAX_STATE_BYTES) {
        set_error(error, error_size, "valid loaded host and state are required");
        RETURN_UNLOCKED(false);
    }
    if (host->hw_negotiated && !host->hw_context_ready) {
        set_error(error, error_size, "hardware context is not ready for state restore");
        RETURN_UNLOCKED(false);
    }
    active_host = host;
    /* The bundled BlastEm defers start_genesis(NULL), including its 68K reset,
     * until the first retro_run. retro_unserialize accepts a cold state but
     * that later reset silently destroys it. Initialize before restoring, not
     * after. Keep this workaround local to BlastEm and only its first run;
     * SRAM bootstrap and in-session rewinds must not gain an extra frame.
     * This stays in the frontend so existing core-identical saves remain
     * compatible. Never display or play the bootstrap frame/PCM. */
    if (host->run_sequence == 0 && host->system_info.library_name &&
            strcmp(host->system_info.library_name, "BlastEm") == 0) {
        host->run_sequence = 1;
        host->run();
        host->audio_read = host->audio_count = 0;
        host->run_audio_output_samples = 0;
        reset_audio_resampler(host);
        host->video_size = 0;
        host->video_sequence = 0;
#if defined(__ANDROID__)
        __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
                "BlastEm cold restore initialized before state load; bootstrap media discarded");
#endif
    }
    if (!host->unserialize(buffer, size)) {
        set_error(error, error_size, "core rejected serialized state");
        RETURN_UNLOCKED(false);
    }
    RETURN_UNLOCKED(true);
}

const char *lucent_retro_library_name(const lucent_retro_host *host) {
    const char *result;
    lock_host();
    result = host && host->system_info.library_name ? host->system_info.library_name : "";
    RETURN_UNLOCKED(result);
}

const char *lucent_retro_library_version(const lucent_retro_host *host) {
    const char *result;
    lock_host();
    result = host && host->system_info.library_version ? host->system_info.library_version : "";
    RETURN_UNLOCKED(result);
}

unsigned lucent_retro_api_version(const lucent_retro_host *host) {
    unsigned result;
    lock_host();
    result = host ? host->api_version() : 0;
    RETURN_UNLOCKED(result);
}

size_t lucent_retro_save_ram_size(lucent_retro_host *host) {
    size_t size;
    lock_host();
    if (!host || !host->game_loaded) RETURN_UNLOCKED(0);
    active_host = host;
    size = host->get_memory_size(RETRO_MEMORY_SAVE_RAM);
    RETURN_UNLOCKED(size <= MAX_SAVE_RAM_BYTES ? size : 0);
}

bool lucent_retro_read_save_ram(lucent_retro_host *host, void *buffer,
                                size_t size) {
    lock_host();
    size_t available = lucent_retro_save_ram_size(host);
    void *source;
    if (!available || available != size || !buffer) RETURN_UNLOCKED(false);
    source = host->get_memory_data(RETRO_MEMORY_SAVE_RAM);
    if (!source) RETURN_UNLOCKED(false);
    memcpy(buffer, source, size);
    RETURN_UNLOCKED(true);
}

bool lucent_retro_write_save_ram(lucent_retro_host *host, const void *buffer,
                                 size_t size) {
    lock_host();
    size_t available = lucent_retro_save_ram_size(host);
    void *destination;
    if (!available || available != size || !buffer) RETURN_UNLOCKED(false);
    destination = host->get_memory_data(RETRO_MEMORY_SAVE_RAM);
    if (!destination) RETURN_UNLOCKED(false);
    memcpy(destination, buffer, size);
    RETURN_UNLOCKED(true);
}

void lucent_retro_destroy(lucent_retro_host *host) {
    size_t variable_index;
    bool quarantine_dolphin;
    if (!host) return;
    lock_host();
    /* Android must call lucent_retro_hw_context_destroy while its EGL/Vulkan
     * context is current. Never invoke core GL/Vulkan cleanup opportunistically
     * here after the Java surface may already have disappeared. */
    host->hw_context_ready = false;
    quarantine_dolphin = host->library && host->initialized &&
            !host->completed_game_load &&
            is_dolphin_core_path(host->core_path);
    if (host->game_loaded && host->unload_game) host->unload_game();
    /* Dolphin's retro_deinit clears process-global objects that its DSO
     * destructors subsequently dereference. Skip only Dolphin's broken
     * retro_deinit. A completed session may still let its DSO finalizers own
     * teardown; a rejected/partial session is quarantined below because its
     * exact Thor tombstone crashed inside those finalizers during dlclose. */
    if (host->initialized && host->deinit &&
            !is_dolphin_core_path(host->core_path))
        host->deinit();
    if (quarantine_dolphin) {
        /* Intentionally leak this one DSO reference until process exit. The
         * retained mapping is poisoned, but its destructors are more dangerous
         * than its bounded address-space cost. Future Dolphin sessions use
         * ANDROID_DLEXT_FORCE_LOAD above and never re-enter these globals. */
        dolphin_mapping_quarantined = true;
#if defined(__ANDROID__)
        __android_log_print(ANDROID_LOG_WARN, "LucentNativeHost",
                "quarantined rejected/partial Dolphin linker image without dlclose");
#endif
    } else if (host->library) {
#if defined(__ANDROID__)
        if (is_dolphin_core_path(host->core_path))
            __android_log_print(ANDROID_LOG_INFO, "LucentNativeHost",
                    "unloading completed Dolphin linker image without retro_deinit");
#endif
        dlclose(host->library);
    }
    if (active_host == host) active_host = NULL;
    free(host->game_bytes);
    free(host->video_bytes);
    free(host->audio_ring);
    free(host->core_path);
    free(host->system_directory);
    free(host->save_directory);
    for (variable_index = 0; variable_index < host->core_variable_count;
            variable_index++) {
        free(host->core_variables[variable_index].key);
        free(host->core_variables[variable_index].value);
    }
    free_core_overrides(host);
    free(host);
    unlock_host();
}
