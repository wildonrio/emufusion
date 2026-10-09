/*
 * EmuFusion Phase 1A libretro operability probe.
 *
 * This is a deliberately small, non-interactive frontend used only by QA. It
 * loads the exact Android ARM64 core artifact that EmuFusion would load and
 * exercises video, audio, input, save RAM, and state serialization callbacks.
 */
#include "libretro.h"

#include <dlfcn.h>
#include <errno.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned (*retro_api_version_fn)(void);
typedef void (*retro_init_fn)(void);
typedef void (*retro_deinit_fn)(void);
typedef void (*retro_get_system_info_fn)(struct retro_system_info *);
typedef void (*retro_get_system_av_info_fn)(struct retro_system_av_info *);
typedef void (*retro_set_environment_fn)(retro_environment_t);
typedef void (*retro_set_video_refresh_fn)(retro_video_refresh_t);
typedef void (*retro_set_audio_sample_fn)(retro_audio_sample_t);
typedef void (*retro_set_audio_sample_batch_fn)(retro_audio_sample_batch_t);
typedef void (*retro_set_input_poll_fn)(retro_input_poll_t);
typedef void (*retro_set_input_state_fn)(retro_input_state_t);
typedef void (*retro_set_controller_port_device_fn)(unsigned, unsigned);
typedef bool (*retro_load_game_fn)(const struct retro_game_info *);
typedef void (*retro_unload_game_fn)(void);
typedef void (*retro_run_fn)(void);
typedef size_t (*retro_serialize_size_fn)(void);
typedef bool (*retro_serialize_fn)(void *, size_t);
typedef bool (*retro_unserialize_fn)(const void *, size_t);
typedef void *(*retro_get_memory_data_fn)(unsigned);
typedef size_t (*retro_get_memory_size_fn)(unsigned);

static const char *g_system_dir;
static const char *g_save_dir;
static enum retro_pixel_format g_pixel_format = RETRO_PIXEL_FORMAT_0RGB1555;
static unsigned g_video_callbacks;
static unsigned g_video_nonzero_callbacks;
static size_t g_video_last_nonzero_bytes;
static size_t g_video_max_nonzero_bytes;
static unsigned g_audio_callbacks;
static uint64_t g_audio_frames;
static unsigned g_input_polls;
static unsigned g_input_states;
static unsigned g_last_width;
static unsigned g_last_height;
static bool g_button_pressed;

struct retro_log_callback_qa {
    void (*log)(int level, const char *fmt, ...);
};

static void qa_log(int level, const char *fmt, ...)
{
    (void)level;
    va_list ap;
    va_start(ap, fmt);
    fputs("core: ", stderr);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
}

static bool environment_cb(unsigned cmd, void *data)
{
    switch (cmd) {
    case RETRO_ENVIRONMENT_GET_CAN_DUPE:
    case RETRO_ENVIRONMENT_GET_INPUT_BITMASKS:
        *(bool *)data = true;
        return true;
    case RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
    case RETRO_ENVIRONMENT_GET_CORE_ASSETS_DIRECTORY:
        *(const char **)data = g_system_dir;
        return true;
    case RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
        *(const char **)data = g_save_dir;
        return true;
    case RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:
        g_pixel_format = *(const enum retro_pixel_format *)data;
        return g_pixel_format == RETRO_PIXEL_FORMAT_0RGB1555 ||
               g_pixel_format == RETRO_PIXEL_FORMAT_XRGB8888 ||
               g_pixel_format == RETRO_PIXEL_FORMAT_RGB565;
    case RETRO_ENVIRONMENT_GET_VARIABLE: {
        struct retro_variable *variable = (struct retro_variable *)data;
        if (variable->key &&
            strcmp(variable->key, "dosbox_pure_savestate") == 0 &&
            getenv("LUCENT_PROBE_DOSBOX_REWIND")) {
            variable->value = "rewind";
            return true;
        }
        variable->value = NULL;
        return false;
    }
    case RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:
        *(bool *)data = false;
        return true;
    case RETRO_ENVIRONMENT_GET_LOG_INTERFACE:
        ((struct retro_log_callback_qa *)data)->log = qa_log;
        return true;
    case RETRO_ENVIRONMENT_GET_INPUT_DEVICE_CAPABILITIES:
        *(uint64_t *)data = (UINT64_C(1) << RETRO_DEVICE_JOYPAD) |
                            (UINT64_C(1) << RETRO_DEVICE_ANALOG);
        return true;
    case RETRO_ENVIRONMENT_GET_LANGUAGE:
        *(unsigned *)data = 0; /* English */
        return true;
    case RETRO_ENVIRONMENT_GET_AUDIO_VIDEO_ENABLE:
        *(int *)data = 3;
        return true;
    case RETRO_ENVIRONMENT_GET_FASTFORWARDING:
        *(bool *)data = false;
        return true;
    case RETRO_ENVIRONMENT_GET_TARGET_REFRESH_RATE:
        *(float *)data = 60.0f;
        return true;
    case RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION:
        *(unsigned *)data = 0;
        return true;
    case RETRO_ENVIRONMENT_GET_MESSAGE_INTERFACE_VERSION:
        *(unsigned *)data = 1;
        return true;
    case RETRO_ENVIRONMENT_GET_INPUT_MAX_USERS:
        *(unsigned *)data = 4;
        return true;
    case RETRO_ENVIRONMENT_SET_VARIABLES:
    case RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:
    case RETRO_ENVIRONMENT_SET_CONTROLLER_INFO:
    case RETRO_ENVIRONMENT_SET_MEMORY_MAPS:
    case RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME:
    case RETRO_ENVIRONMENT_SET_SUPPORT_ACHIEVEMENTS:
    case RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL:
    case RETRO_ENVIRONMENT_SET_MESSAGE:
    case RETRO_ENVIRONMENT_SET_MESSAGE_EXT:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS_DISPLAY:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS_V2:
    case RETRO_ENVIRONMENT_SET_CORE_OPTIONS_V2_INTL:
    case RETRO_ENVIRONMENT_SET_SUBSYSTEM_INFO:
        return true;
    default:
        return false;
    }
}

static void video_cb(const void *data, unsigned width, unsigned height,
                     size_t pitch)
{
    ++g_video_callbacks;
    if (width) g_last_width = width;
    if (height) g_last_height = height;
    if (data && data != RETRO_HW_FRAME_BUFFER_VALID && pitch && height) {
        const uint8_t *bytes = (const uint8_t *)data;
        size_t size = pitch * (size_t)height;
        size_t nonzero = 0;
        for (size_t index = 0; index < size; ++index) {
            if (bytes[index] != 0) ++nonzero;
        }
        g_video_last_nonzero_bytes = nonzero;
        if (nonzero > g_video_max_nonzero_bytes) g_video_max_nonzero_bytes = nonzero;
        if (nonzero) ++g_video_nonzero_callbacks;
    }
}

static void audio_sample_cb(int16_t left, int16_t right)
{
    (void)left;
    (void)right;
    ++g_audio_callbacks;
    ++g_audio_frames;
}

static size_t audio_batch_cb(const int16_t *data, size_t frames)
{
    (void)data;
    ++g_audio_callbacks;
    g_audio_frames += frames;
    return frames;
}

static void input_poll_cb(void)
{
    ++g_input_polls;
}

static int16_t input_state_cb(unsigned port, unsigned device,
                              unsigned index, unsigned id)
{
    (void)index;
    ++g_input_states;
    if (port == 0 && device == RETRO_DEVICE_JOYPAD && id == 8)
        return g_button_pressed ? 1 : 0;
    if (port == 0 && device == RETRO_DEVICE_JOYPAD &&
        id == RETRO_DEVICE_ID_JOYPAD_MASK)
        return g_button_pressed ? (int16_t)(1u << 8) : 0;
    return 0;
}

static void *load_symbol(void *handle, const char *name)
{
    void *symbol = dlsym(handle, name);
    if (!symbol) {
        fprintf(stderr, "missing required symbol %s: %s\n", name, dlerror());
        exit(3);
    }
    return symbol;
}

static bool read_file(const char *path, void **data, size_t *size)
{
    FILE *file = fopen(path, "rb");
    if (!file) return false;
    if (fseek(file, 0, SEEK_END) != 0) { fclose(file); return false; }
    long length = ftell(file);
    if (length < 0 || fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return false;
    }
    void *buffer = malloc((size_t)length ? (size_t)length : 1);
    if (!buffer) { fclose(file); return false; }
    if ((size_t)length && fread(buffer, 1, (size_t)length, file) != (size_t)length) {
        free(buffer);
        fclose(file);
        return false;
    }
    fclose(file);
    *data = buffer;
    *size = (size_t)length;
    return true;
}

static const char *json_bool(bool value) { return value ? "true" : "false"; }

static void dump_state_if_requested(const char *suffix, const void *data, size_t size)
{
    const char *prefix = getenv("LUCENT_PROBE_STATE_DUMP");
    if (!prefix || !*prefix) return;
    char path[1024];
    if (snprintf(path, sizeof(path), "%s.%s", prefix, suffix) < 0) return;
    FILE *file = fopen(path, "wb");
    if (!file) return;
    fwrite(data, 1, size, file);
    fclose(file);
}

int main(int argc, char **argv)
{
    if (argc != 6 && argc != 7) {
        fprintf(stderr, "usage: %s CORE ROM SYSTEM_DIR SAVE_DIR FRAMES [STATE_CYCLES]\n", argv[0]);
        return 2;
    }
    const char *core_path = argv[1];
    const char *rom_path = argv[2];
    g_system_dir = argv[3];
    g_save_dir = argv[4];
    unsigned frames = (unsigned)strtoul(argv[5], NULL, 10);
    if (frames < 8) frames = 8;
    unsigned state_cycles_requested = argc == 7 ? (unsigned)strtoul(argv[6], NULL, 10) : 1;
    if (state_cycles_requested < 1) state_cycles_requested = 1;

    void *handle = dlopen(core_path, RTLD_NOW | RTLD_LOCAL);
    if (!handle) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 3;
    }

#define LOAD_FN(type, variable, name) type variable = (type)load_symbol(handle, name)
    LOAD_FN(retro_api_version_fn, api_version, "retro_api_version");
    LOAD_FN(retro_init_fn, init, "retro_init");
    LOAD_FN(retro_deinit_fn, deinit, "retro_deinit");
    LOAD_FN(retro_get_system_info_fn, get_system_info, "retro_get_system_info");
    LOAD_FN(retro_get_system_av_info_fn, get_system_av_info, "retro_get_system_av_info");
    LOAD_FN(retro_set_environment_fn, set_environment, "retro_set_environment");
    LOAD_FN(retro_set_video_refresh_fn, set_video_refresh, "retro_set_video_refresh");
    LOAD_FN(retro_set_audio_sample_fn, set_audio_sample, "retro_set_audio_sample");
    LOAD_FN(retro_set_audio_sample_batch_fn, set_audio_batch, "retro_set_audio_sample_batch");
    LOAD_FN(retro_set_input_poll_fn, set_input_poll, "retro_set_input_poll");
    LOAD_FN(retro_set_input_state_fn, set_input_state, "retro_set_input_state");
    LOAD_FN(retro_set_controller_port_device_fn, set_controller, "retro_set_controller_port_device");
    LOAD_FN(retro_load_game_fn, load_game, "retro_load_game");
    LOAD_FN(retro_unload_game_fn, unload_game, "retro_unload_game");
    LOAD_FN(retro_run_fn, run, "retro_run");
    LOAD_FN(retro_serialize_size_fn, serialize_size_fn, "retro_serialize_size");
    LOAD_FN(retro_serialize_fn, serialize, "retro_serialize");
    LOAD_FN(retro_unserialize_fn, unserialize, "retro_unserialize");
    LOAD_FN(retro_get_memory_data_fn, get_memory_data, "retro_get_memory_data");
    LOAD_FN(retro_get_memory_size_fn, get_memory_size, "retro_get_memory_size");
#undef LOAD_FN

    struct retro_system_info info = {0};
    struct retro_system_av_info av = {0};
    void *rom_data = NULL;
    size_t rom_size = 0;
    bool loaded = false;
    bool serialize_ok = false;
    bool unserialize_ok = false;
    bool state_equal = false;
    bool state_canonicalized = false;
    unsigned state_canonicalization_passes = 0;
    size_t state_difference_bytes = 0;
    size_t state_first_difference = 0;
    unsigned state_cycles_completed = 0;
    bool sram_writable = false;
    bool input_effect_checked = false;
    bool input_effect = false;
    size_t state_size = 0;
    size_t sram_size = 0;

    set_environment(environment_cb);
    /* Mesen and Mesen-S allocate their callback-owning objects in retro_init.
     * libretro permits these setters after initialization, so initialize first
     * instead of relying on the more common (but not universal) order. */
    init();
    set_video_refresh(video_cb);
    set_audio_sample(audio_sample_cb);
    set_audio_batch(audio_batch_cb);
    set_input_poll(input_poll_cb);
    set_input_state(input_state_cb);
    get_system_info(&info);

    if (api_version() == RETRO_API_VERSION &&
        (info.need_fullpath || read_file(rom_path, &rom_data, &rom_size))) {
        struct retro_game_info game = {
            .path = rom_path,
            .data = info.need_fullpath ? NULL : rom_data,
            .size = info.need_fullpath ? 0 : rom_size,
            .meta = NULL,
        };
        loaded = load_game(&game);
    }

    if (loaded) {
        set_controller(0, RETRO_DEVICE_JOYPAD);
        get_system_av_info(&av);
        for (unsigned i = 0; i < frames; ++i) {
            g_button_pressed = i == 2;
            run();
        }
        g_button_pressed = false;

        sram_size = get_memory_size(RETRO_MEMORY_SAVE_RAM);
        uint8_t *sram = (uint8_t *)get_memory_data(RETRO_MEMORY_SAVE_RAM);
        if (sram && sram_size) {
            uint8_t original = sram[0];
            uint8_t changed = (uint8_t)(original ^ 0x5a);
            sram[0] = changed;
            sram_writable = sram[0] == changed;
            sram[0] = original;
        }

        state_size = serialize_size_fn();
        if (state_size) {
            void *before = malloc(state_size);
            void *after = malloc(state_size);
            void *canonical = malloc(state_size);
            if (before && after && canonical) {
                serialize_ok = serialize(before, state_size);
                for (unsigned i = 0; i < 3; ++i) run();
                for (unsigned cycle = 0; serialize_ok && cycle < state_cycles_requested; ++cycle) {
                    unserialize_ok = unserialize(before, state_size);
                    if (!unserialize_ok || !serialize(after, state_size)) break;
                    state_equal = memcmp(before, after, state_size) == 0;
                    if (!state_equal && cycle == 0) {
                        dump_state_if_requested("before", before, state_size);
                        dump_state_if_requested("after", after, state_size);
                        for (size_t i = 0; i < state_size; ++i) {
                            if (((uint8_t *)before)[i] != ((uint8_t *)after)[i]) {
                                if (state_difference_bytes == 0)
                                    state_first_difference = i;
                                ++state_difference_bytes;
                            }
                        }
                        /* Some cores canonicalize live input, renderer, or
                         * scheduler fields over several load/save passes.
                         * Accept only a finite fixed point, then require the
                         * ordinary exact-equality gate from that point. */
                        for (unsigned pass = 1; pass <= 64 && !state_equal; ++pass) {
                            if (!unserialize(after, state_size) ||
                                !serialize(canonical, state_size))
                                break;
                            state_canonicalization_passes = pass;
                            if (memcmp(after, canonical, state_size) == 0) {
                                memcpy(before, after, state_size);
                                state_equal = true;
                                state_canonicalized = true;
                                break;
                            }
                            memcpy(after, canonical, state_size);
                        }
                        dump_state_if_requested("canonical", canonical, state_size);
                    }
                    if (!state_equal) break;
                    ++state_cycles_completed;
                }
                if (serialize_ok && unserialize_ok && state_equal &&
                    state_cycles_completed == state_cycles_requested &&
                    serialize(before, state_size)) {
                    /* Replay an identical interval from the exact same state
                     * with and without joypad A held. Callback counts alone do
                     * not prove that a core consumed input; differing final
                     * serialized states do. */
                    input_effect_checked = true;
                    g_button_pressed = false;
                    if (unserialize(before, state_size)) {
                        for (unsigned frame = 0; frame < 30; ++frame) run();
                        if (serialize(after, state_size) &&
                            unserialize(before, state_size)) {
                            g_button_pressed = true;
                            for (unsigned frame = 0; frame < 30; ++frame) run();
                            g_button_pressed = false;
                            if (serialize(canonical, state_size))
                                input_effect = memcmp(after, canonical, state_size) != 0;
                        }
                    }
                    g_button_pressed = false;
                    unserialize(before, state_size);
                }
            }
            free(before);
            free(after);
            free(canonical);
        }
    }

    /* A lone non-black startup callback can hide a core that spends the whole
     * sampled session on a blank frame. Permit short boot transitions, but
     * require visible pixels in at least 90% of delivered frames. */
    bool callbacks_ok = g_video_callbacks > 0 &&
                        (uint64_t)g_video_nonzero_callbacks * 10 >=
                            (uint64_t)g_video_callbacks * 9 &&
                        g_audio_frames > 0 &&
                        g_input_polls > 0 && g_input_states > 0;
    bool state_ok = state_size > 0 && serialize_ok && unserialize_ok && state_equal &&
                    state_cycles_completed == state_cycles_requested;
    bool input_effect_required = getenv("LUCENT_PROBE_REQUIRE_INPUT_EFFECT") != NULL;
    bool passed = loaded && callbacks_ok && state_ok &&
                  (!input_effect_required || (input_effect_checked && input_effect));

    printf("{\"result\":\"%s\",\"library\":\"%s\",\"version\":\"%s\","
           "\"needFullpath\":%s,\"load\":%s,\"framesRequested\":%u,"
           "\"videoCallbacks\":%u,\"audioCallbacks\":%u,\"audioFrames\":%llu,"
           "\"videoNonzeroCallbacks\":%u,\"videoLastNonzeroBytes\":%zu,"
           "\"videoMaxNonzeroBytes\":%zu,"
           "\"inputPolls\":%u,\"inputStates\":%u,"
           "\"inputEffectRequired\":%s,\"inputEffectChecked\":%s,"
           "\"inputEffect\":%s,"
           "\"width\":%u,\"height\":%u,"
           "\"fps\":%.6f,\"sampleRate\":%.6f,\"pixelFormat\":%u,"
           "\"sramSize\":%zu,\"sramWritable\":%s,\"serializeSize\":%zu,"
           "\"serialize\":%s,\"unserialize\":%s,\"stateRoundTripEqual\":%s,"
           "\"stateCyclesRequested\":%u,\"stateCyclesCompleted\":%u,"
           "\"stateCanonicalized\":%s,\"stateCanonicalizationPasses\":%u,"
           "\"stateDifferenceBytes\":%zu,"
           "\"stateFirstDifference\":%zu}\n",
           passed ? "PASS" : "FAIL", info.library_name ? info.library_name : "",
           info.library_version ? info.library_version : "", json_bool(info.need_fullpath),
           json_bool(loaded), frames, g_video_callbacks, g_audio_callbacks,
           (unsigned long long)g_audio_frames, g_video_nonzero_callbacks,
           g_video_last_nonzero_bytes, g_video_max_nonzero_bytes,
           g_input_polls, g_input_states,
           json_bool(input_effect_required), json_bool(input_effect_checked),
           json_bool(input_effect),
           g_last_width, g_last_height, av.timing.fps, av.timing.sample_rate,
           (unsigned)g_pixel_format, sram_size, json_bool(sram_writable), state_size,
           json_bool(serialize_ok), json_bool(unserialize_ok), json_bool(state_equal),
           state_cycles_requested, state_cycles_completed,
           json_bool(state_canonicalized), state_canonicalization_passes,
           state_difference_bytes, state_first_difference);

    if (loaded) unload_game();
    deinit();
    free(rom_data);
    dlclose(handle);
    return passed ? 0 : 1;
}
