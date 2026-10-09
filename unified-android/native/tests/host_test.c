#include "../include/lucent_libretro_host.h"
#include "../include/libretro.h"

#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(value, message) do { if (!(value)) { fprintf(stderr, "%s: %s\n", message, error); return 1; } } while (0)

static uint32_t state_value(lucent_retro_host *host, char *error, size_t error_size) {
    uint32_t state = 0;
    if (lucent_retro_serialize_size(host) != sizeof(state) ||
            !lucent_retro_serialize(host, &state, sizeof(state), error, error_size)) return UINT32_MAX;
    return state;
}

typedef void (*fn_emit_video)(unsigned, unsigned, size_t);
typedef void (*fn_emit_audio)(size_t);
typedef bool (*fn_probe_null_environment)(void);
typedef void (*fn_set_boolean)(bool);
typedef void (*fn_set_double)(double);
typedef bool (*fn_change_double)(double);
typedef const char *(*fn_option_value)(const char *);
typedef unsigned (*fn_count)(void);
typedef int16_t (*fn_pointer_state)(unsigned);

typedef struct stress_context {
    lucent_retro_host *host;
    int failed;
} stress_context;

static void *run_stress(void *opaque) {
    stress_context *context = (stress_context *)opaque;
    char error[128] = {0};
    unsigned index;
    for (index = 0; index < 2000; index++)
        if (!lucent_retro_run_frame(context->host, error, sizeof(error))) {
            context->failed = 1;
            break;
        }
    return NULL;
}

static void *input_media_stress(void *opaque) {
    stress_context *context = (stress_context *)opaque;
    unsigned index;
    int16_t samples[8];
    for (index = 0; index < 2000; index++) {
        lucent_retro_video_info info;
        uint16_t pixel;
        if (!lucent_retro_set_joypad_button(context->host, 0, 0, (index & 1u) != 0) ||
                !lucent_retro_set_analog_axis(context->host, 0,
                    RETRO_DEVICE_INDEX_ANALOG_LEFT, RETRO_DEVICE_ID_ANALOG_X,
                    (int16_t)index)) {
            context->failed = 1;
            break;
        }
        if (lucent_retro_latest_video_info(context->host, &info) && info.byte_size == 2 &&
                !lucent_retro_copy_video_frame(context->host, &pixel, sizeof(pixel))) {
            context->failed = 1;
            break;
        }
        lucent_retro_drain_audio(context->host, samples, 4);
    }
    return NULL;
}

int main(int argc, char **argv) {
    char error[512] = {0};
    uint32_t saved;
    lucent_retro_video_info video;
    lucent_retro_av_info av;
    lucent_retro_hw_info hardware;
    uint16_t pixel = 0;
    int16_t audio[8] = {0};
    int16_t runtime_rate_audio[16] = {0};
    int16_t high_rate_audio[16] = {0};
    int16_t timing_audio[2048] = {0};
    uint8_t save_ram[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    uint8_t save_copy[8] = {0};
    int16_t *overflow_audio = NULL;
    void *mock_library = NULL;
    fn_emit_video emit_video;
    fn_emit_audio emit_audio;
    fn_probe_null_environment probe_null_environment;
    fn_probe_null_environment overscan_enabled;
    fn_probe_null_environment callbacks_were_set_before_init;
    fn_set_boolean set_oversized_state;
    fn_set_boolean set_changing_state_size;
    fn_set_boolean set_oversized_save_ram;
    fn_set_double set_sample_rate;
    fn_change_double change_runtime_sample_rate;
    fn_option_value option_value;
    fn_set_boolean set_prepare_exit_result;
    fn_count prepare_exit_count;
    fn_count unload_count;
    fn_count reset_count;
    fn_count port_device_count;
    fn_count last_port;
    fn_count last_device;
    fn_pointer_state pointer_state;
    if (argc != 6) {
        fprintf(stderr, "usage: host_test CORE TRUSTED_ROOT SYSTEM_DIR SAVE_DIR GAME\n");
        return 2;
    }
    lucent_retro_host *host = lucent_retro_create(argv[1], argv[2], argv[3], argv[4], error, sizeof(error));
    CHECK(host, "create failed");
    mock_library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    CHECK(mock_library, "could not reopen mock core for probes");
    emit_video = (fn_emit_video)dlsym(mock_library, "lucent_mock_emit_video");
    emit_audio = (fn_emit_audio)dlsym(mock_library, "lucent_mock_emit_audio");
    probe_null_environment = (fn_probe_null_environment)dlsym(
            mock_library, "lucent_mock_probe_null_environment");
    overscan_enabled = (fn_probe_null_environment)dlsym(
            mock_library, "lucent_mock_overscan_enabled");
    callbacks_were_set_before_init = (fn_probe_null_environment)dlsym(
            mock_library, "lucent_mock_callbacks_were_set_before_init");
    set_oversized_state = (fn_set_boolean)dlsym(
            mock_library, "lucent_mock_set_oversized_state");
    set_changing_state_size = (fn_set_boolean)dlsym(
            mock_library, "lucent_mock_set_changing_state_size");
    set_oversized_save_ram = (fn_set_boolean)dlsym(
            mock_library, "lucent_mock_set_oversized_save_ram");
    set_sample_rate = (fn_set_double)dlsym(
            mock_library, "lucent_mock_set_sample_rate");
    change_runtime_sample_rate = (fn_change_double)dlsym(
            mock_library, "lucent_mock_change_runtime_sample_rate");
    option_value = (fn_option_value)dlsym(
            mock_library, "lucent_mock_option_value");
    set_prepare_exit_result = (fn_set_boolean)dlsym(
            mock_library, "lucent_mock_set_prepare_exit_result");
    prepare_exit_count = (fn_count)dlsym(
            mock_library, "lucent_mock_prepare_exit_count");
    unload_count = (fn_count)dlsym(mock_library, "lucent_mock_unload_count");
    reset_count = (fn_count)dlsym(mock_library, "lucent_mock_reset_count");
    port_device_count = (fn_count)dlsym(
            mock_library, "lucent_mock_port_device_count");
    last_port = (fn_count)dlsym(mock_library, "lucent_mock_last_port");
    last_device = (fn_count)dlsym(mock_library, "lucent_mock_last_device");
    pointer_state = (fn_pointer_state)dlsym(
            mock_library, "lucent_mock_pointer_state");
    CHECK(emit_video && emit_audio && probe_null_environment && overscan_enabled &&
            callbacks_were_set_before_init &&
            set_oversized_state && set_changing_state_size &&
            set_oversized_save_ram && set_sample_rate &&
            change_runtime_sample_rate && option_value &&
            set_prepare_exit_result && prepare_exit_count && unload_count &&
            reset_count && port_device_count && last_port && last_device &&
            pointer_state,
            "mock safety probes are missing");
    CHECK(!lucent_retro_reset(host, error, sizeof(error)),
          "reset was accepted before a game was loaded");
    CHECK(!lucent_retro_set_controller_port_device(host, 0, 1, error, sizeof(error)),
          "controller port device was accepted before a game was loaded");
    CHECK(option_value("lucent_software_test") &&
            strcmp(option_value("lucent_software_test"), "preferred") == 0,
            "software core option defaults were not retained");
    CHECK(option_value("puae_kickstart") &&
            strcmp(option_value("puae_kickstart"),
                    strstr(argv[1], "lucent_core_puae") ? "aros" : "auto") == 0,
            "PUAE curated AROS profile was not applied exactly");
    CHECK(option_value("dolphin_widescreen") &&
            strcmp(option_value("dolphin_widescreen"), "enabled") == 0 &&
            strcmp(option_value("dolphin_widescreen_hack"), "disabled") == 0 &&
            strcmp(option_value("dolphin_aspect_ratio"), "3") == 0,
            "Dolphin native-only widescreen profile was not applied exactly");
    CHECK(option_value("dolphin_osd_enabled") &&
            strcmp(option_value("dolphin_osd_enabled"), "disabled") == 0,
            "Dolphin diagnostic OSD must be disabled by default");
    CHECK(option_value("dolphin_efb_scale") &&
            strcmp(option_value("dolphin_efb_scale"), "1") == 0,
            "Dolphin must start at native resolution on unknown Android GPUs");
    CHECK(strcmp(option_value("mupen64plus-aspect"), "4:3") == 0,
            "Mupen native 4:3 profile was not applied exactly");
    CHECK(strcmp(option_value("swanstation_GPU_WidescreenHack"), "false") == 0 &&
            strcmp(option_value("swanstation_Display_AspectRatio"), "4:3") == 0,
            "SwanStation original 4:3 profile was not applied exactly");
    CHECK(strcmp(option_value("reicast_widescreen_cheats"), "disabled") == 0 &&
            strcmp(option_value("reicast_widescreen_hack"), "disabled") == 0,
            "Flycast generic widescreen transforms were not disabled");
    CHECK(strcmp(option_value("armsx2_aspect_ratio"), "Auto 4:3/3:2") == 0 &&
            strcmp(option_value("armsx2_widescreen_patches"), "disabled") == 0,
            "ARMSX2 native automatic aspect profile was not applied exactly");
    CHECK(strcmp(option_value("mesen_aspect_ratio"), "Auto") == 0,
            "Mesen region-correct automatic aspect was not applied exactly");
    CHECK(strcmp(option_value("dolphin_cheats_enabled"), "enabled") == 0 &&
            strcmp(option_value("ppsspp_cheats"), "enabled") == 0,
            "Dolphin/PPSSPP internal cheat support was not enabled for live cheats");
    CHECK(strcmp(option_value("mupen64plus-169screensize"), "640x360") == 0,
            "Mupen 16:9 size must keep the core default without an override");
    CHECK(option_value("citra_resolution_factor") &&
            strcmp(option_value("citra_resolution_factor"), "1") == 0,
            "3DS portable default must not force sixteen times native pixels");
    CHECK(!callbacks_were_set_before_init(),
            "callbacks were registered before retro_init");
    CHECK(!probe_null_environment(), "null environment payload was accepted");
    CHECK(!overscan_enabled(),
          "frontend must explicitly crop overscan, not expose the raw signal"
          " (2026-09-06: exposing it showed as an unwanted black band on the"
          " Thor's flat panel)");
    {
        lucent_retro_host *second = lucent_retro_create(
                argv[1], argv[2], argv[3], argv[4], error, sizeof(error));
        CHECK(!second, "second simultaneous core session was accepted");
    }
    CHECK(lucent_retro_api_version(host) == 1, "API validation failed");
    CHECK(strcmp(lucent_retro_library_name(host), "Lucent Mock Core") == 0, "system info failed");
    CHECK(strcmp(lucent_retro_library_version(host), "1") == 0, "version info failed");
    CHECK(lucent_retro_get_hw_info(host, &hardware) && !hardware.negotiated &&
          !hardware.context_ready && hardware.frame_sequence == 0,
          "software host reported a hardware context");
    CHECK(!lucent_retro_hw_context_reset(host, error, sizeof(error)) &&
          !lucent_retro_hw_context_destroy(host, error, sizeof(error)),
          "software host accepted hardware lifecycle calls");
    CHECK(lucent_retro_load_game(host, argv[5], error, sizeof(error)), "load failed");
    CHECK(lucent_retro_get_av_info(host, &av), "AV info unavailable");
    CHECK(av.frames_per_second == 60.0 && av.sample_rate == 48000.0 &&
          av.base_width == 1 && av.base_height == 1, "AV info mismatch");
    CHECK(lucent_retro_set_synchronized_video_rate(
                    host, 61.0, 60.0, error, sizeof(error)),
          "SNES display synchronization was rejected");
    emit_audio(600);
    CHECK(lucent_retro_drain_audio(host, timing_audio, 1024) > 600,
          "slower synchronized SNES clock did not upsample PCM");
    CHECK(lucent_retro_set_synchronized_video_rate(
                    host, 59.0, 60.0, error, sizeof(error)),
          "GBA display synchronization was rejected");
    emit_audio(600);
    CHECK(lucent_retro_drain_audio(host, timing_audio, 1024) < 600,
          "faster synchronized GBA clock did not downsample PCM");
    CHECK(lucent_retro_set_synchronized_video_rate(
                    host, 60.0988, 60.0, error, sizeof(error)),
          "exact SNES display synchronization was rejected");
    emit_audio(700);
    CHECK(lucent_retro_drain_audio(host, timing_audio, 1024) == 701,
          "exact SNES correction did not preserve PCM duration");
    CHECK(lucent_retro_set_synchronized_video_rate(
                    host, 59.7275, 60.0, error, sizeof(error)),
          "exact GBA display synchronization was rejected");
    emit_audio(700);
    CHECK(lucent_retro_drain_audio(host, timing_audio, 1024) == 696,
          "exact GBA correction did not preserve PCM duration");
    CHECK(lucent_retro_set_synchronized_video_rate(
                    host, 60.0, 60.0, error, sizeof(error)),
          "native display timing could not be restored");
    CHECK(lucent_retro_set_synchronized_video_rate(
                    host, 59.7275, 60.0, error, sizeof(error)),
          "display audio trim setup failed");
    emit_audio(1);
    CHECK(lucent_retro_drain_audio(host, timing_audio, 1024) == 0,
          "downsampler must retain the first fractional sample");
    CHECK(lucent_retro_set_synchronized_video_rate(
                    host, 59.7275, 60.001, error, sizeof(error)),
          "live display audio trim failed");
    emit_audio(1);
    CHECK(lucent_retro_drain_audio(host, timing_audio, 1024) == 1,
          "live display trim discarded pending fractional PCM");
    CHECK(lucent_retro_set_synchronized_video_rate(
                    host, 60.0, 60.0, error, sizeof(error)),
          "native timing restore after live trim failed");
    CHECK(change_runtime_sample_rate(96000.0),
          "runtime audio-rate change was rejected");
    CHECK(lucent_retro_get_av_info(host, &av) && av.sample_rate == 48000.0,
          "runtime input-rate change replaced the established Android sink rate");
    emit_audio(16);
    CHECK(lucent_retro_drain_audio(host, runtime_rate_audio, 8) == 8,
          "runtime 2x input audio was not downsampled to the established sink");
    CHECK(change_runtime_sample_rate(48000.0),
          "runtime audio rate could not return to its established sink rate");
    CHECK(lucent_retro_set_joypad_button(host, 0, 0, true), "button setter failed");
    CHECK(lucent_retro_set_analog_axis(host, 0, RETRO_DEVICE_INDEX_ANALOG_LEFT,
                                      RETRO_DEVICE_ID_ANALOG_X, 12345),
          "left X setter failed");
    CHECK(lucent_retro_set_analog_axis(host, 0, RETRO_DEVICE_INDEX_ANALOG_LEFT,
                                      RETRO_DEVICE_ID_ANALOG_Y, -23456),
          "left Y setter failed");
    CHECK(lucent_retro_set_analog_axis(host, 1, RETRO_DEVICE_INDEX_ANALOG_RIGHT,
                                      RETRO_DEVICE_ID_ANALOG_X, INT16_MIN),
          "port 1 right X setter failed");
    CHECK(!lucent_retro_set_analog_axis(host, 8, RETRO_DEVICE_INDEX_ANALOG_LEFT,
                                       RETRO_DEVICE_ID_ANALOG_X, 1),
          "invalid analog port was accepted");
    CHECK(lucent_retro_set_pointer(host, 0, -12345, 23456, true),
          "pointer setter failed");
    CHECK(!lucent_retro_set_pointer(host, 8, 0, 0, false),
          "invalid pointer port was accepted");
    CHECK(pointer_state(RETRO_DEVICE_ID_POINTER_X) == -12345 &&
          pointer_state(RETRO_DEVICE_ID_POINTER_Y) == 23456 &&
          pointer_state(RETRO_DEVICE_ID_POINTER_PRESSED) == 1,
          "pointer input did not reach core");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)), "run failed");
    CHECK(state_value(host, error, sizeof(error)) == 1117,
          "digital or signed analog input did not reach core");
    CHECK(lucent_retro_latest_video_info(host, &video), "video info unavailable");
    CHECK(video.width == 1 && video.height == 1 && video.pitch == 2 &&
          video.byte_size == 2 && video.sequence == 1, "video metadata mismatch");
    CHECK(lucent_retro_copy_video_frame(host, &pixel, sizeof(pixel)) && pixel == 1117,
          "video pixels mismatch");
    {
        uint16_t reusable[2] = {0, 0x5a5a};
        CHECK(lucent_retro_copy_video_frame(host, reusable, sizeof(reusable)) &&
              reusable[0] == 1117 && reusable[1] == 0x5a5a,
              "larger reusable video destination was rejected or overwritten");
    }
    {
        uint64_t sequence = video.sequence;
        emit_video(2, 1, 2); /* Two 16-bit pixels require a four-byte pitch. */
        CHECK(lucent_retro_latest_video_info(host, &video) && video.sequence == sequence,
              "undersized video pitch replaced the last valid frame");
        emit_video(8193, 1, 16386);
        CHECK(lucent_retro_latest_video_info(host, &video) && video.sequence == sequence,
              "oversized video geometry replaced the last valid frame");
        emit_video(1, 1, 128u * 1024u + 1u);
        CHECK(lucent_retro_latest_video_info(host, &video) && video.sequence == sequence,
              "oversized video pitch replaced the last valid frame");
    }
    CHECK(lucent_retro_drain_audio(host, audio, SIZE_MAX) == 0,
          "overflowing audio request was accepted");
    CHECK(lucent_retro_drain_audio(host, audio, 4) == 2,
          "single and batch audio callbacks were not drained");
    CHECK(audio[0] == 0 && audio[1] == 0 && audio[2] == 1117 && audio[3] == -1117,
          "audio PCM mismatch");
    emit_audio(140000);
    overflow_audio = (int16_t *)calloc(262144u, sizeof(int16_t));
    CHECK(overflow_audio, "audio stress allocation failed");
    CHECK(lucent_retro_drain_audio(host, overflow_audio, 140000) == 131072,
          "audio ring did not retain its bounded newest-frame capacity");
    CHECK(overflow_audio[0] == 8928 && overflow_audio[1] == -8928,
          "audio ring did not discard the oldest overflow samples");
    free(overflow_audio);
    overflow_audio = NULL;
    {
        pthread_t runner;
        pthread_t input_media;
        stress_context run_context = {host, 0};
        stress_context input_context = {host, 0};
        CHECK(pthread_create(&runner, NULL, run_stress, &run_context) == 0,
              "frame stress thread creation failed");
        CHECK(pthread_create(&input_media, NULL, input_media_stress, &input_context) == 0,
              "input/media stress thread creation failed");
        CHECK(pthread_join(runner, NULL) == 0 && pthread_join(input_media, NULL) == 0,
              "native stress thread join failed");
        CHECK(!run_context.failed && !input_context.failed,
              "concurrent native frame/input/media stress failed");
        CHECK(lucent_retro_set_joypad_button(host, 0, 0, false),
              "stress button cleanup failed");
        CHECK(lucent_retro_set_analog_axis(host, 0, RETRO_DEVICE_INDEX_ANALOG_LEFT,
                  RETRO_DEVICE_ID_ANALOG_X, 0), "stress analog cleanup failed");
    }
    saved = state_value(host, error, sizeof(error));
    set_changing_state_size(true);
    {
        size_t first_size = lucent_retro_serialize_size(host);
        uint8_t legacy_buffer[8] = {0};
        void *allocated_state = NULL;
        size_t allocated_size = 0;
        CHECK(first_size == sizeof(saved), "changing-size mock first query mismatch");
        CHECK(!lucent_retro_serialize(host, legacy_buffer, first_size,
                    error, sizeof(error)),
              "legacy two-query serialization unexpectedly accepted size drift");
        CHECK(lucent_retro_serialize_alloc(host, &allocated_state,
                    &allocated_size, error, sizeof(error)) &&
              allocated_size == sizeof(saved) &&
              memcmp(allocated_state, &saved, sizeof(saved)) == 0,
              "atomic serialization did not tolerate core size drift");
        free(allocated_state);
    }
    set_changing_state_size(false);
    {
        void *allocated_state = NULL;
        size_t allocated_size = 0;
        CHECK(lucent_retro_serialize_alloc(host, &allocated_state,
                    &allocated_size, error, sizeof(error)) &&
              allocated_size == sizeof(saved) &&
              memcmp(allocated_state, &saved, sizeof(saved)) == 0,
              "atomic allocated state serialization failed");
        free(allocated_state);
    }
    lucent_retro_set_paused(host, true);
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)), "paused run failed");
    CHECK(state_value(host, error, sizeof(error)) == saved, "pause did not stop execution");
    lucent_retro_set_paused(host, false);
    CHECK(lucent_retro_set_joypad_button(host, 0, 0, false), "button clear failed");
    CHECK(lucent_retro_set_analog_axis(host, 0, RETRO_DEVICE_INDEX_ANALOG_LEFT,
                                      RETRO_DEVICE_ID_ANALOG_X, 0),
          "analog clear failed");
    CHECK(lucent_retro_set_analog_axis(host, 0, RETRO_DEVICE_INDEX_ANALOG_LEFT,
                                      RETRO_DEVICE_ID_ANALOG_Y, 0),
          "analog clear failed");
    CHECK(lucent_retro_set_analog_axis(host, 1, RETRO_DEVICE_INDEX_ANALOG_RIGHT,
                                      RETRO_DEVICE_ID_ANALOG_X, 0),
          "analog clear failed");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)), "resume run failed");
    CHECK(state_value(host, error, sizeof(error)) == saved + 1, "resume did not execute");
    CHECK(lucent_retro_unserialize(host, &saved, sizeof(saved), error, sizeof(error)), "restore failed");
    CHECK(state_value(host, error, sizeof(error)) == saved, "restored state mismatch");
    set_oversized_state(true);
    CHECK(lucent_retro_serialize_size(host) == 0, "oversized serialized state was exposed");
    {
        void *allocated_state = (void *)1;
        size_t allocated_size = 1;
        CHECK(!lucent_retro_serialize_alloc(host, &allocated_state,
                    &allocated_size, error, sizeof(error)) &&
              allocated_state == NULL && allocated_size == 0,
              "oversized allocated serialized state was accepted");
    }
    CHECK(!lucent_retro_unserialize(host, &saved,
              (size_t)(512u * 1024u * 1024u) + 1u, error, sizeof(error)),
          "oversized serialized state was accepted");
    set_oversized_state(false);
    CHECK(lucent_retro_save_ram_size(host) == sizeof(save_ram), "save RAM size mismatch");
    CHECK(lucent_retro_write_save_ram(host, save_ram, sizeof(save_ram)), "save RAM write failed");
    CHECK(lucent_retro_read_save_ram(host, save_copy, sizeof(save_copy)) &&
          memcmp(save_ram, save_copy, sizeof(save_ram)) == 0, "save RAM round-trip failed");
    set_oversized_save_ram(true);
    CHECK(lucent_retro_save_ram_size(host) == 0, "oversized save RAM was exposed");
    set_oversized_save_ram(false);
    {
        /* Loading already selected a plain RetroPad on port 0. */
        unsigned selections = port_device_count();
        CHECK(selections >= 1 && last_port() == 0 &&
              last_device() == RETRO_DEVICE_JOYPAD,
              "load did not reset port 0 to a plain RetroPad");
        CHECK(lucent_retro_set_controller_port_device(host, 0, 0x301u,
                  error, sizeof(error)),
              "Wii Nunchuk port device was rejected");
        CHECK(port_device_count() == selections + 1 && last_port() == 0 &&
              last_device() == 0x301u,
              "port device did not reach the core unchanged");
        CHECK(!lucent_retro_set_controller_port_device(host, 8, 0x301u,
                  error, sizeof(error)),
              "out-of-range controller port was accepted");
        CHECK(port_device_count() == selections + 1,
              "rejected controller port still reached the core");
    }
    {
        unsigned resets = reset_count();
        uint8_t after_reset[8] = {0};
        CHECK(lucent_retro_run_frame(host, error, sizeof(error)),
              "pre-reset frame failed");
        CHECK(state_value(host, error, sizeof(error)) != 0,
              "mock core had nothing to power-cycle");
        CHECK(lucent_retro_reset(host, error, sizeof(error)), "reset failed");
        CHECK(reset_count() == resets + 1, "retro_reset was not invoked");
        CHECK(state_value(host, error, sizeof(error)) == 0,
              "reset did not power-cycle core state");
        /* A soft reset is the console's reset button: battery-backed save RAM
         * must survive it, which is why the Java session no longer restores a
         * disk copy over it. */
        CHECK(lucent_retro_read_save_ram(host, after_reset, sizeof(after_reset)) &&
              memcmp(save_ram, after_reset, sizeof(save_ram)) == 0,
              "reset erased battery-backed save RAM");
    }
    set_prepare_exit_result(false);
    CHECK(!lucent_retro_unload_game(host, error, sizeof(error)),
          "failed exit autosave did not reject unload");
    CHECK(prepare_exit_count() == 1 && unload_count() == 0,
          "failed exit autosave reached retro_unload_game");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)),
          "failed exit autosave did not keep the game runnable");
    set_prepare_exit_result(true);
    CHECK(lucent_retro_unload_game(host, error, sizeof(error)),
          "successful exit autosave did not unload");
    CHECK(prepare_exit_count() == 2 && unload_count() == 1,
          "successful exit autosave ordering mismatch");
    CHECK(!lucent_retro_run_frame(host, error, sizeof(error)),
          "unloaded game remained runnable");
    {
        unsigned resets = reset_count();
        CHECK(!lucent_retro_reset(host, error, sizeof(error)),
              "unloaded game accepted a reset");
        CHECK(reset_count() == resets, "rejected reset still reached the core");
        CHECK(!lucent_retro_set_controller_port_device(host, 0, 0x301u,
                  error, sizeof(error)),
              "unloaded game accepted a controller port device");
    }
    CHECK(!lucent_retro_reset(NULL, error, sizeof(error)),
          "null host accepted a reset");
    lucent_retro_destroy(host);
    set_sample_rate(2097152.0);
    host = lucent_retro_create(argv[1], argv[2], argv[3], argv[4], error, sizeof(error));
    CHECK(host, "host could not be recreated after teardown");
    CHECK(lucent_retro_load_game(host, argv[5], error, sizeof(error)),
          "high-rate mock load failed");
    CHECK(lucent_retro_get_av_info(host, &av) && av.sample_rate == 48000.0,
          "high-rate core was not normalized to Android output rate");
    emit_audio(437);
    CHECK(lucent_retro_drain_audio(host, high_rate_audio, 8) == 8,
          "high-rate core audio was not downsampled into the bounded ring");
    CHECK(high_rate_audio[0] == 21 && high_rate_audio[1] == -21,
          "high-rate downsampler did not average its source window");
    CHECK(lucent_retro_unload_game(host, error, sizeof(error)),
          "high-rate mock unload failed");
    lucent_retro_destroy(host);

    /* mGBA starts its Android session at 32,768 Hz, then games can raise the
     * production rate to 65,536/131,072/262,144 Hz through SOUNDBIAS. The
     * already-created AudioTrack cannot follow those runtime changes. Prove
     * every real ratio preserves the established sink and drains exactly one
     * 32 kHz output frame for each ratio-sized source window. */
    set_sample_rate(32768.0);
    host = lucent_retro_create(argv[1], argv[2], argv[3], argv[4], error, sizeof(error));
    CHECK(host, "GBA-rate host could not be recreated after teardown");
    CHECK(lucent_retro_load_game(host, argv[5], error, sizeof(error)),
          "GBA-rate mock load failed");
    CHECK(lucent_retro_get_av_info(host, &av) && av.sample_rate == 32768.0,
          "GBA-rate sink did not start at 32,768 Hz");
    CHECK(change_runtime_sample_rate(65536.0),
          "GBA 2x runtime audio-rate change was rejected");
    emit_audio(16);
    CHECK(lucent_retro_get_av_info(host, &av) && av.sample_rate == 32768.0 &&
          lucent_retro_drain_audio(host, runtime_rate_audio, 8) == 8,
          "GBA 2x input did not preserve and feed the 32,768 Hz sink");
    CHECK(change_runtime_sample_rate(131072.0),
          "GBA 4x runtime audio-rate change was rejected");
    emit_audio(32);
    CHECK(lucent_retro_get_av_info(host, &av) && av.sample_rate == 32768.0 &&
          lucent_retro_drain_audio(host, runtime_rate_audio, 8) == 8,
          "GBA 4x input did not preserve and feed the 32,768 Hz sink");
    CHECK(change_runtime_sample_rate(262144.0),
          "GBA 8x runtime audio-rate change was rejected");
    emit_audio(64);
    CHECK(lucent_retro_get_av_info(host, &av) && av.sample_rate == 32768.0 &&
          lucent_retro_drain_audio(host, runtime_rate_audio, 8) == 8,
          "GBA 8x input did not preserve and feed the 32,768 Hz sink");
    CHECK(change_runtime_sample_rate(32768.0),
          "GBA runtime audio rate could not return to its sink rate");
    emit_audio(8);
    CHECK(lucent_retro_drain_audio(host, runtime_rate_audio, 8) == 8,
          "GBA native-rate audio did not recover after resampled operation");
    CHECK(lucent_retro_unload_game(host, error, sizeof(error)),
          "GBA-rate mock unload failed");
    lucent_retro_destroy(host);

    host = lucent_retro_create_with_preferences(
            argv[1], argv[2], argv[3], argv[4], NULL, false,
            error, sizeof(error));
    CHECK(host, "widescreen-off host could not be created");
    CHECK(strcmp(option_value("dolphin_widescreen"), "disabled") == 0 &&
            strcmp(option_value("dolphin_widescreen_hack"), "disabled") == 0 &&
            strcmp(option_value("dolphin_aspect_ratio"), "3") == 0,
            "Dolphin widescreen-off profile was not restored exactly");
    CHECK(strcmp(option_value("dolphin_osd_enabled"), "disabled") == 0,
            "Dolphin OSD default must not depend on the widescreen preference");
    CHECK(strcmp(option_value("mupen64plus-aspect"), "4:3") == 0,
            "Mupen 4:3 profile was not restored exactly");
    CHECK(strcmp(option_value("swanstation_GPU_WidescreenHack"), "false") == 0 &&
            strcmp(option_value("swanstation_Display_AspectRatio"), "4:3") == 0,
            "SwanStation original 4:3 profile was not retained exactly");
    CHECK(strcmp(option_value("reicast_widescreen_cheats"), "disabled") == 0 &&
            strcmp(option_value("reicast_widescreen_hack"), "disabled") == 0,
            "Flycast widescreen-off profile was not restored exactly");
    CHECK(strcmp(option_value("armsx2_aspect_ratio"), "Auto 4:3/3:2") == 0 &&
            strcmp(option_value("armsx2_widescreen_patches"), "disabled") == 0,
            "ARMSX2 automatic aspect profile was not restored exactly");
    lucent_retro_destroy(host);

    /* Launch-time overrides: <system>/lucent-core-overrides.txt flips only the
     * keys it names, only to tokens the core advertises, and disappears with
     * the file. This is the channel the Java WidescreenHackPolicy writes. */
    {
        char override_path[4096];
        FILE *override_file;
        snprintf(override_path, sizeof(override_path),
                "%s/lucent-core-overrides.txt", argv[3]);
        override_file = fopen(override_path, "wb");
        CHECK(override_file, "could not write the override file");
        fputs("# generated by host_test\r\n"
              "\r\n"
              "mupen64plus-aspect = 16:9 adjusted\r\n"
              "mupen64plus-169screensize=1920x1080\n"
              "swanstation_GPU_WidescreenHack=true\n"
              "swanstation_Display_AspectRatio=16:9\n"
              "armsx2_aspect_ratio=21:9\n"
              "dolphin_widescreen=disabled\n"
              "dolphin_osd_enabled=enabled\n"
              "dolphin_efb_scale=2\n"
              "citra_resolution_factor=2\n"
              "not a key=enabled\n"
              "lucent_unknown_key=whatever\n"
              "dolphin_cheats_enabled=disabled\n", override_file);
        fclose(override_file);
        host = lucent_retro_create_with_preferences(
                argv[1], argv[2], argv[3], argv[4], NULL, true,
                error, sizeof(error));
        CHECK(host, "override host could not be created");
        CHECK(strcmp(option_value("mupen64plus-aspect"), "16:9 adjusted") == 0 &&
                strcmp(option_value("mupen64plus-169screensize"), "1920x1080") == 0,
                "override file did not flip the Mupen widescreen keys");
        CHECK(strcmp(option_value("swanstation_GPU_WidescreenHack"), "true") == 0 &&
                strcmp(option_value("swanstation_Display_AspectRatio"), "16:9") == 0,
                "override file did not flip the SwanStation widescreen keys");
        CHECK(strcmp(option_value("armsx2_aspect_ratio"), "Auto 4:3/3:2") == 0,
                "an override token the core does not advertise must be ignored");
        CHECK(strcmp(option_value("dolphin_widescreen"), "disabled") == 0,
                "override file must win over the preference-driven default");
        CHECK(strcmp(option_value("dolphin_osd_enabled"), "enabled") == 0,
                "explicit diagnostic OSD override must remain available");
        CHECK(strcmp(option_value("citra_resolution_factor"), "2") == 0,
                "explicit supported 3DS upscaling must remain available");
        CHECK(strcmp(option_value("dolphin_efb_scale"), "2") == 0,
                "explicit supported Dolphin upscaling must remain available");
        CHECK(strcmp(option_value("dolphin_cheats_enabled"), "disabled") == 0,
                "override file must be able to flip a Lucent default back");
        CHECK(strcmp(option_value("reicast_widescreen_hack"), "disabled") == 0 &&
                strcmp(option_value("armsx2_widescreen_patches"), "disabled") == 0,
                "keys absent from the override file must keep their defaults");
        CHECK(!option_value("lucent_unknown_key"),
                "an override must never declare a variable the core lacks");
        lucent_retro_destroy(host);
        CHECK(remove(override_path) == 0, "could not remove the override file");
        host = lucent_retro_create_with_preferences(
                argv[1], argv[2], argv[3], argv[4], NULL, true,
                error, sizeof(error));
        CHECK(host, "post-override host could not be created");
        CHECK(strcmp(option_value("mupen64plus-aspect"), "4:3") == 0 &&
                strcmp(option_value("swanstation_GPU_WidescreenHack"), "false") == 0 &&
                strcmp(option_value("citra_resolution_factor"), "1") == 0 &&
                strcmp(option_value("dolphin_efb_scale"), "1") == 0 &&
                strcmp(option_value("dolphin_cheats_enabled"), "enabled") == 0,
                "removing the override file did not restore the defaults");
        CHECK(strcmp(option_value("dolphin_osd_enabled"), "disabled") == 0,
                "Dolphin OSD must return to disabled after diagnostic override removal");
        lucent_retro_destroy(host);
    }
    dlclose(mock_library);
    puts("libretro host lifecycle and state round-trip passed");
    return 0;
}
