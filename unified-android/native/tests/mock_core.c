#include "../include/libretro.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static retro_environment_t environment;
static retro_video_refresh_t video;
static retro_audio_sample_t audio;
static retro_audio_sample_batch_t audio_batch;
static retro_input_poll_t input_poll;
static retro_input_state_t input_state;
static uint32_t counter;
static uint8_t save_ram[8];
static bool oversized_state;
static bool changing_state_size;
static size_t state_size_queries;
static size_t last_advertised_state_size;
static bool oversized_save_ram;
static bool initialized;
static bool callback_before_init;
static double reported_sample_rate = 48000.0;
static const char *software_default;
static const char *puae_kickstart;
static bool prepare_exit_result = true;
static unsigned prepare_exit_count;
static unsigned unload_count;
static unsigned reset_count;
static unsigned port_device_count;
static unsigned last_port;
static unsigned last_device;

#if defined(LUCENT_MOCK_DLCLOSE_MARKER)
__attribute__((destructor)) static void record_mock_dso_finalized(void) {
    const char *path = getenv("LUCENT_MOCK_DLCLOSE_MARKER_PATH");
    FILE *marker;
    if (!path || !path[0]) return;
    marker = fopen(path, "wb");
    if (!marker) return;
    fputs("finalized\n", marker);
    fclose(marker);
}
#endif

/* Test-only probes resolved by the host harness through dlopen/dlsym. */
void lucent_mock_emit_video(unsigned width, unsigned height, size_t pitch) {
    uint32_t pixels[8] = {0};
    if (video) video(pixels, width, height, pitch);
}
void lucent_mock_emit_audio(size_t frames) {
    size_t index;
    if (!audio) return;
    for (index = 0; index < frames; index++)
        audio((int16_t)index, (int16_t)-((int16_t)index));
}
bool lucent_mock_probe_null_environment(void) {
    return environment && environment(RETRO_ENVIRONMENT_GET_CAN_DUPE, NULL);
}
bool lucent_mock_overscan_enabled(void) {
    bool enabled = true;
    return !environment ||
            !environment(RETRO_ENVIRONMENT_GET_OVERSCAN, &enabled) || enabled;
}
bool lucent_mock_callbacks_were_set_before_init(void) { return callback_before_init; }
void lucent_mock_set_oversized_state(bool value) { oversized_state = value; }
void lucent_mock_set_changing_state_size(bool value) {
    changing_state_size = value;
    state_size_queries = 0;
    last_advertised_state_size = 0;
}
void lucent_mock_set_oversized_save_ram(bool value) { oversized_save_ram = value; }
void lucent_mock_set_sample_rate(double value) { reported_sample_rate = value; }
bool lucent_mock_change_runtime_sample_rate(double value) {
    struct retro_system_av_info info;
    if (!environment) return false;
    memset(&info, 0, sizeof(info));
    info.geometry.base_width = 1;
    info.geometry.base_height = 1;
    info.geometry.max_width = 1;
    info.geometry.max_height = 1;
    info.timing.fps = 60.0;
    info.timing.sample_rate = value;
    return environment(RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO, &info);
}
void lucent_mock_set_prepare_exit_result(bool value) { prepare_exit_result = value; }
unsigned lucent_mock_prepare_exit_count(void) { return prepare_exit_count; }
unsigned lucent_mock_unload_count(void) { return unload_count; }
unsigned lucent_mock_reset_count(void) { return reset_count; }
unsigned lucent_mock_port_device_count(void) { return port_device_count; }
unsigned lucent_mock_last_port(void) { return last_port; }
unsigned lucent_mock_last_device(void) { return last_device; }
int16_t lucent_mock_pointer_state(unsigned id) {
    return input_state ? input_state(0, RETRO_DEVICE_POINTER, 0, id) : 0;
}
const char *lucent_mock_option_value(const char *key) {
    struct retro_variable current;
    if (!key || !environment) return NULL;
    current.key = key;
    current.value = NULL;
    return environment(RETRO_ENVIRONMENT_GET_VARIABLE, &current) ?
            current.value : NULL;
}

void retro_init(void) {
    struct retro_variable definitions[] = {
        { "lucent_software_test", "Software default; preferred|other" },
        { "puae_kickstart", "Kickstart ROM; auto|aros" },
        { "dolphin_widescreen", "Wii widescreen; disabled|enabled" },
        { "dolphin_widescreen_hack", "Widescreen hack; disabled|enabled" },
        { "dolphin_aspect_ratio", "Aspect ratio; 3|0|1|2" },
        { "dolphin_osd_enabled", "On-Screen Display; enabled|disabled" },
        { "dolphin_efb_scale", "Internal resolution; 2|1|3|4" },
        { "mupen64plus-aspect", "Aspect ratio; 4:3|16:9|16:9 adjusted" },
        { "swanstation_GPU_WidescreenHack", "Widescreen hack; false|true" },
        { "swanstation_Display_AspectRatio", "Aspect ratio; 4:3|16:9|Native" },
        { "reicast_widescreen_cheats", "Widescreen cheats; disabled|enabled" },
        { "reicast_widescreen_hack", "Widescreen hack; disabled|enabled" },
        { "armsx2_aspect_ratio", "Aspect ratio; Auto 4:3/3:2|4:3|16:9|Stretch" },
        { "armsx2_widescreen_patches", "Widescreen patches; disabled|enabled" },
        { "mesen_aspect_ratio", "Aspect ratio; Auto|No Stretching|NTSC|PAL|4:3|16:9" },
        { "mupen64plus-169screensize", "16:9 size; 640x360|1920x1080|3840x2160" },
        { "dolphin_cheats_enabled", "Internal cheats; disabled|enabled" },
        { "ppsspp_cheats", "Internal cheats; disabled|enabled" },
        { "citra_resolution_factor", "Internal resolution; 4|1|2|3|5" },
        { NULL, NULL },
    };
    struct retro_variable current = { "lucent_software_test", NULL };
    struct retro_variable kickstart = { "puae_kickstart", NULL };
    initialized = true;
    if (environment && environment(RETRO_ENVIRONMENT_SET_VARIABLES, definitions) &&
            environment(RETRO_ENVIRONMENT_GET_VARIABLE, &current))
        software_default = current.value;
    if (environment && environment(RETRO_ENVIRONMENT_GET_VARIABLE, &kickstart))
        puae_kickstart = kickstart.value;
}
void retro_deinit(void) { initialized = false; }
unsigned retro_api_version(void) { return RETRO_API_VERSION; }
void retro_get_system_info(struct retro_system_info *info) {
    memset(info, 0, sizeof(*info));
    info->library_name = "Lucent Mock Core";
    info->library_version = "1";
    info->valid_extensions = "mock";
    info->need_fullpath = false;
}
void retro_get_system_av_info(struct retro_system_av_info *info) {
    memset(info, 0, sizeof(*info));
    info->geometry.base_width = 1;
    info->geometry.base_height = 1;
    info->geometry.max_width = 1;
    info->geometry.max_height = 1;
    info->timing.fps = 60.0;
    info->timing.sample_rate = reported_sample_rate;
}
void retro_set_environment(retro_environment_t callback) { environment = callback; }
void retro_set_video_refresh(retro_video_refresh_t callback) {
    if (!initialized) callback_before_init = true;
    video = callback;
}
void retro_set_audio_sample(retro_audio_sample_t callback) {
    if (!initialized) callback_before_init = true;
    audio = callback;
}
void retro_set_audio_sample_batch(retro_audio_sample_batch_t callback) {
    if (!initialized) callback_before_init = true;
    audio_batch = callback;
}
void retro_set_input_poll(retro_input_poll_t callback) {
    if (!initialized) callback_before_init = true;
    input_poll = callback;
}
void retro_set_input_state(retro_input_state_t callback) {
    if (!initialized) callback_before_init = true;
    input_state = callback;
}
void retro_set_controller_port_device(unsigned port, unsigned device) {
    port_device_count++;
    last_port = port;
    last_device = device;
}
void retro_reset(void) {
    reset_count++;
    counter = 0;
}
void retro_run(void) {
    uint16_t pixel;
    int16_t samples[2];
    bool can_dupe = false;
    if (environment) environment(RETRO_ENVIRONMENT_GET_CAN_DUPE, &can_dupe);
    if (input_poll) input_poll();
    counter += input_state && input_state(0, RETRO_DEVICE_JOYPAD, 0, 0) ? 10 : 1;
    if (input_state &&
            input_state(0, RETRO_DEVICE_ANALOG, RETRO_DEVICE_INDEX_ANALOG_LEFT,
                        RETRO_DEVICE_ID_ANALOG_X) == 12345 &&
            input_state(0, RETRO_DEVICE_ANALOG, RETRO_DEVICE_INDEX_ANALOG_LEFT,
                        RETRO_DEVICE_ID_ANALOG_Y) == -23456) counter += 100;
    if (input_state &&
            input_state(1, RETRO_DEVICE_ANALOG, RETRO_DEVICE_INDEX_ANALOG_RIGHT,
                        RETRO_DEVICE_ID_ANALOG_X) == -32768) counter += 1000;
    pixel = (uint16_t)counter;
    samples[0] = (int16_t)counter;
    samples[1] = (int16_t)-((int16_t)counter);
    if (video) video(&pixel, 1, 1, sizeof(pixel));
    if (audio) audio(0, 0);
    if (audio_batch) audio_batch(samples, 1);
}
size_t retro_serialize_size(void) {
    if (oversized_state) return (512u * 1024u * 1024u) + 1u;
    last_advertised_state_size = changing_state_size && (state_size_queries++ & 1u)
            ? sizeof(counter) + 4u : sizeof(counter);
    return last_advertised_state_size;
}
bool retro_serialize(void *data, size_t size) {
    size_t required = changing_state_size ? last_advertised_state_size : sizeof(counter);
    if (size != required || size < sizeof(counter)) return false;
    memcpy(data, &counter, sizeof(counter));
    if (size > sizeof(counter))
        memset((uint8_t *)data + sizeof(counter), 0, size - sizeof(counter));
    return true;
}
bool retro_unserialize(const void *data, size_t size) {
    if (size != sizeof(counter)) return false;
    memcpy(&counter, data, size);
    return true;
}
void retro_cheat_reset(void) {}
void retro_cheat_set(unsigned index, bool enabled, const char *code) {
    (void)index; (void)enabled; (void)code;
}
bool retro_load_game(const struct retro_game_info *game) {
#if defined(LUCENT_MOCK_REJECT_GAME)
    (void)game;
    return false;
#else
    if (!game || !game->data || game->size == 0) return false;
    counter = ((const uint8_t *)game->data)[0];
    return true;
#endif
}
bool retro_load_game_special(unsigned type, const struct retro_game_info *games, size_t count) {
    (void)type; (void)games; (void)count; return false;
}
bool retro_lucent_prepare_exit_autosave(void) {
    prepare_exit_count++;
    return prepare_exit_result;
}
void retro_unload_game(void) { unload_count++; }
unsigned retro_get_region(void) { return 0; }
void *retro_get_memory_data(unsigned id) {
    return id == RETRO_MEMORY_SAVE_RAM ? save_ram : NULL;
}
size_t retro_get_memory_size(unsigned id) {
    if (id != RETRO_MEMORY_SAVE_RAM) return 0;
    return oversized_save_ram ? (64u * 1024u * 1024u) + 1u : sizeof(save_ram);
}
