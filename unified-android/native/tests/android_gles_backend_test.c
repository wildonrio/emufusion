#include "../include/lucent_android_gles_backend.h"
#include "../include/libretro.h"
#include <android/native_window.h>
#include <GLES3/gl3.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#define CHECK(value, message) do { \
    if (!(value)) { fprintf(stderr, "%s: %s\n", message, error); return 1; } \
} while (0)

typedef unsigned (*fn_count)(void);
typedef int16_t (*fn_pointer_state)(unsigned);
typedef void (*fn_video_size)(unsigned, unsigned);
typedef void (*fn_render_capacity)(unsigned, unsigned, unsigned, unsigned);
void lucent_fake_egl_lose_next_swap(void);
void lucent_fake_egl_completion_support(int enabled);
int lucent_fake_egl_completion_enabled(void);
void lucent_fake_egl_hold_completions(int hold);
void lucent_fake_egl_complete_last_frames(unsigned count, int64_t interval_ns);
unsigned lucent_fake_egl_swap_count(void);
unsigned lucent_fake_egl_presentation_time_count(void);
int64_t lucent_fake_egl_presentation_time_last(void);
int64_t lucent_fake_egl_presentation_time_delta(void);
unsigned lucent_fake_gles_blit_count(void);
unsigned lucent_fake_gles_opaque_alpha_clear_count(void);
int lucent_fake_gles_last_blit_source_x1(void);
int lucent_fake_gles_last_blit_source_y1(void);
int lucent_fake_gles_last_blit_source_x0(void);
int lucent_fake_gles_last_blit_source_y0(void);
int lucent_fake_gles_previous_blit_source_x0(void);
int lucent_fake_gles_previous_blit_source_y0(void);
int lucent_fake_gles_previous_blit_source_x1(void);
int lucent_fake_gles_previous_blit_source_y1(void);
int lucent_fake_gles_last_blit_destination_x0(void);
int lucent_fake_gles_last_blit_destination_y0(void);
int lucent_fake_gles_last_blit_destination_x1(void);
int lucent_fake_gles_last_blit_destination_y1(void);
void lucent_fake_gles_set_scissor_enabled(int enabled);
int lucent_fake_gles_scissor_enabled(void);
unsigned lucent_fake_gles_bound_framebuffer(void);
void lucent_fake_gles_set_viewport(int x, int y, int width, int height);
int lucent_fake_gles_texture_width(void);
int lucent_fake_gles_texture_height(void);
void lucent_fake_gles_set_sentinel_bounds(int enabled);
void lucent_fake_gles_set_written_rect(int left, int bottom, int right, int top);
unsigned lucent_fake_gles_bounds_readbacks(void);
unsigned lucent_fake_window_acquire_count(void);
unsigned lucent_fake_window_release_count(void);
void lucent_fake_window_set_size(int32_t width, int32_t height);

typedef struct thread_probe {
    lucent_android_gles_backend *backend;
    bool accepted;
} thread_probe;

static void *wrong_thread_make_current(void *userdata) {
    thread_probe *probe = (thread_probe *)userdata;
    char ignored[128] = {0};
    probe->accepted = lucent_android_gles_make_current(
            probe->backend, ignored, sizeof(ignored));
    return NULL;
}

static void *wrong_thread_set_fg_timestamp(void *userdata) {
    thread_probe *probe = (thread_probe *)userdata;
    char ignored[128] = {0};
    probe->accepted = lucent_android_gles_set_fg_timestamp(
            probe->backend, true, ignored, sizeof(ignored));
    return NULL;
}

static int64_t monotonic_ns(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return -1;
    return (int64_t)now.tv_sec * 1000000000LL + now.tv_nsec;
}

int main(int argc, char **argv) {
    char error[512] = {0};
    lucent_android_gles_backend *backend;
    lucent_retro_hw_options options;
    lucent_retro_hw_info hw;
    lucent_android_gles_info backend_info;
    lucent_retro_host *host;
    ANativeWindow window = {1};
    bool presented = false;
    pthread_t thread;
    thread_probe probe;
    void *core_library;
    fn_count reset_count;
    fn_count destroy_count;
    fn_count variable_default_ok;
    fn_count frontend_framebuffer;
    fn_pointer_state pointer_state;
    fn_video_size set_video_size;
    fn_video_size set_geometry;
    fn_render_capacity set_render_capacity;
    lucent_retro_av_info av;
    uint32_t state = 0;
    uint32_t restored = 42;
    int16_t audio_samples[4] = {1, 1, 1, 1};
    int16_t mupen_audio_samples[12] = {0};
    uint8_t save_ram[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    uint8_t save_copy[8] = {0};
    unsigned direct_swap_baseline;
    unsigned direct_blit_baseline;
    if (argc != 7) {
        fprintf(stderr, "usage: android_gles_backend_test CORE MUPEN_CORE "
                        "ROOT SYSTEM SAVE GAME\n");
        return 2;
    }
    backend = lucent_android_gles_create(error, sizeof(error));
    CHECK(backend, "Android GLES backend probe failed");
    CHECK(lucent_android_gles_get_info(backend, &backend_info) &&
          backend_info.display_ready && backend_info.max_gles_major == 3 &&
          backend_info.max_gles_minor == 2 && !backend_info.surface_attached,
          "probed Android GLES metadata mismatch");
    CHECK(lucent_android_gles_get_host_options(backend, &options,
                                               error, sizeof(error)),
          "Android GLES host options failed");
    /* Shared contexts are supported (the config carries EGL_PBUFFER_BIT and a
     * core builds its worker contexts from the render thread's current
     * context); debug contexts remain unimplemented and must stay refused. */
    CHECK((options.context_capabilities & LUCENT_RETRO_HW_GLES_VERSION) &&
          !(options.context_capabilities & LUCENT_RETRO_HW_VULKAN) &&
          (options.feature_capabilities & LUCENT_RETRO_HW_CACHE_CONTEXT) &&
          (options.feature_capabilities & LUCENT_RETRO_HW_SHARED_CONTEXT) &&
          !(options.feature_capabilities & LUCENT_RETRO_HW_DEBUG_CONTEXT),
          "Android GLES capability gates mismatch");
    core_library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    CHECK(core_library, "hardware mock core could not be inspected");
    reset_count = (fn_count)dlsym(core_library, "lucent_hw_mock_reset_count");
    destroy_count = (fn_count)dlsym(core_library, "lucent_hw_mock_destroy_count");
    variable_default_ok = (fn_count)dlsym(
            core_library, "lucent_hw_mock_variable_default_ok");
    frontend_framebuffer = (fn_count)dlsym(
            core_library, "lucent_hw_mock_frontend_framebuffer");
    pointer_state = (fn_pointer_state)dlsym(
            core_library, "lucent_hw_mock_pointer_state");
    set_video_size = (fn_video_size)dlsym(
            core_library, "lucent_hw_mock_set_video_size");
    CHECK(reset_count && destroy_count && variable_default_ok &&
          frontend_framebuffer && pointer_state && set_video_size,
          "hardware lifecycle probes missing");
    host = lucent_retro_create_with_options(argv[1], argv[3], argv[4], argv[5],
                                            &options, error, sizeof(error));
    CHECK(host, "hardware host creation failed");
    CHECK(variable_default_ok() == 1,
          "hardware core option defaults were not retained");
    CHECK(lucent_retro_load_game(host, argv[6], error, sizeof(error)),
          "hardware mock game load failed");
    CHECK(lucent_retro_set_pointer(host, 0, -12345, 23456, true) &&
          pointer_state(RETRO_DEVICE_ID_POINTER_X) == -12345 &&
          pointer_state(RETRO_DEVICE_ID_POINTER_Y) == 23456 &&
          pointer_state(RETRO_DEVICE_ID_POINTER_PRESSED) == 1,
          "hardware GLES pointer input did not reach the core");
    CHECK(lucent_retro_get_av_info(host, &av) && av.frames_per_second == 60.0 &&
          av.sample_rate == 48000.0 && av.base_width == 4 && av.base_height == 4,
          "hardware AV information was unavailable");
    CHECK(lucent_retro_serialize_size(host) == 0 &&
          !lucent_retro_serialize(host, &state, sizeof(state), error, sizeof(error)) &&
          !lucent_retro_unserialize(host, &restored, sizeof(restored),
                                    error, sizeof(error)),
          "hardware state callbacks were allowed before context attach");
    error[0] = '\0';
    CHECK(lucent_retro_save_ram_size(host) == sizeof(save_ram) &&
          lucent_retro_write_save_ram(host, save_ram, sizeof(save_ram)) &&
          lucent_retro_read_save_ram(host, save_copy, sizeof(save_copy)) &&
          memcmp(save_ram, save_copy, sizeof(save_ram)) == 0,
          "hardware save RAM round-trip failed");
    CHECK(lucent_android_gles_attach(backend, host, &window, error, sizeof(error)),
          "Android GLES window attach failed");
    CHECK(reset_count() == 1 && frontend_framebuffer() == 42 &&
          lucent_android_gles_get_info(backend, &backend_info) &&
          backend_info.surface_attached,
          "Android GLES reset/attach lifecycle mismatch");
    CHECK(lucent_retro_serialize_size(host) == sizeof(state) &&
          lucent_retro_serialize(host, &state, sizeof(state), error, sizeof(error)) &&
          state == 7,
          "hardware state serialization after attach failed");
    CHECK(lucent_retro_unserialize(host, &restored, sizeof(restored),
                                   error, sizeof(error)) &&
          lucent_retro_serialize(host, &state, sizeof(state), error, sizeof(error)) &&
          state == restored,
          "hardware state restore after attach failed");
    probe.backend = backend;
    probe.accepted = true;
    CHECK(pthread_create(&thread, NULL, wrong_thread_make_current, &probe) == 0 &&
          pthread_join(thread, NULL) == 0 && !probe.accepted,
          "wrong-thread EGL access was not rejected");
    CHECK(pthread_create(&thread, NULL, wrong_thread_set_fg_timestamp, &probe) == 0 &&
          pthread_join(thread, NULL) == 0 && !probe.accepted,
          "wrong-thread FG timestamp ownership was not rejected");
    CHECK(lucent_android_gles_set_fg_timestamp(backend, true, error, sizeof(error)),
          "FG source timestamp opt-in failed");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)),
          "hardware core did not produce its first frame");
    /* Model Dolphin's integer-scaled core viewport inside a larger frontend
     * allocation and its normal OGL state, which leaves scissor testing on.
     * Presentation must blit only the complete written region without letting
     * the core's scissor clip the Android destination, then restore it. */
    lucent_fake_gles_set_viewport(0, 0, 720, 1000);
    lucent_fake_gles_set_scissor_enabled(1);
    /* A state-caching core may leave different read and draw targets. */
    glBindFramebuffer(GL_READ_FRAMEBUFFER, 71);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 72);
    CHECK(lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          presented && lucent_fake_egl_swap_count() == 1 &&
          lucent_fake_gles_blit_count() == 1 &&
          lucent_fake_gles_opaque_alpha_clear_count() == 1 &&
          lucent_fake_gles_last_blit_source_x1() == 720 &&
          lucent_fake_gles_last_blit_source_y1() == 1000 &&
          lucent_fake_gles_scissor_enabled() == 1 &&
          lucent_fake_gles_bound_framebuffer() == 72,
          "new hardware frame was not presented exactly once");
    GLint restored_read = 0;
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &restored_read);
    CHECK(restored_read == 71, "presentation did not restore the core read FBO");
    CHECK(lucent_fake_egl_presentation_time_count() == 1 &&
          lucent_fake_egl_presentation_time_last() > 0,
          "first hardware frame did not receive an immutable core timestamp");
    CHECK(lucent_retro_drain_audio(host, audio_samples, 2) == 2 &&
          audio_samples[0] == 0 && audio_samples[1] == 0 &&
          audio_samples[2] == 0 && audio_samples[3] == 0,
          "hardware audio transport did not drain stereo PCM");
    CHECK(lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          !presented && lucent_fake_egl_swap_count() == 1,
          "stale hardware frame triggered a duplicate swap");
    /* A resize keeps the same live Surface identity. It must refresh
     * Lucent's presentation geometry inside the live context without any
     * core context_destroy/context_reset: the destructive path is what
     * double-reset Mupen64Plus-Next into a pre-gameplay SIGSEGV
     * (2026-08-21 F-Zero X). */
    lucent_fake_window_set_size(1280, 720);
    CHECK(lucent_android_gles_surface_resized(backend, error, sizeof(error)) &&
          reset_count() == 1 && destroy_count() == 0,
          "same-surface resize performed a destructive core context transition");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          presented &&
          lucent_fake_gles_last_blit_destination_x0() == 280 &&
          lucent_fake_gles_last_blit_destination_x1() == 1000 &&
          lucent_fake_gles_last_blit_destination_y1() == 720,
          "resized backend kept stale presentation geometry");
    CHECK(lucent_fake_egl_presentation_time_count() == 2 &&
          lucent_fake_egl_presentation_time_delta() == 16666667,
          "60-Hz core sequence did not produce an exact timestamp grid");
    lucent_fake_window_set_size(1920, 1080);
    lucent_fake_egl_lose_next_swap();
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
          !lucent_android_gles_present_if_ready(backend, &presented,
                                                error, sizeof(error)) &&
          lucent_retro_get_hw_info(host, &hw) && !hw.context_ready &&
          destroy_count() == 0,
          "EGL_CONTEXT_LOST did not fail closed without core cleanup");
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
          "lost Android GLES surface did not detach cleanly");
    CHECK(lucent_android_gles_attach(backend, host, &window, error, sizeof(error)) &&
          reset_count() == 2,
          "replacement Android GLES context did not reset the core");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) && presented,
          "replacement Android GLES context did not present");
    unsigned timestamp_baseline = lucent_fake_egl_presentation_time_count();
    CHECK(timestamp_baseline == 3,
          "replacement direct surface inherited FG timestamps");
    for (unsigned frame = 0; frame < 10000; ++frame) {
        CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
              lucent_android_gles_present_if_ready(backend, &presented,
                                                   error, sizeof(error)) && presented,
              "Off frame did not present");
    }
    CHECK(lucent_fake_egl_presentation_time_count() == timestamp_baseline,
          "Off executed EGL FG timestamp work during 10000 frames");
    int64_t rebind_before = monotonic_ns();
    CHECK(lucent_android_gles_set_fg_timestamp(backend, true, error, sizeof(error)) &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) && presented,
          "FG re-enable did not present");
    CHECK(rebind_before > 0 &&
          lucent_fake_egl_presentation_time_last() >= rebind_before &&
          lucent_fake_egl_presentation_time_last() <= monotonic_ns(),
          "FG re-enable retained the old timestamp epoch");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) && presented &&
          lucent_fake_egl_presentation_time_count() == timestamp_baseline + 2 &&
          lucent_fake_egl_presentation_time_delta() == 16666667,
          "FG re-enable did not restore the source grid");
    CHECK(lucent_android_gles_set_fg_timestamp(backend, false, error, sizeof(error)) &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) && presented &&
          lucent_fake_egl_presentation_time_count() == timestamp_baseline + 2,
          "FG-to-Off transition retained timestamp work");
    rebind_before = monotonic_ns();
    CHECK(lucent_android_gles_set_fg_timestamp(backend, true, error, sizeof(error)) &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) && presented &&
          lucent_fake_egl_presentation_time_last() >= rebind_before &&
          lucent_fake_egl_presentation_time_last() <= monotonic_ns(),
          "Off-to-FG rebind did not establish a fresh timestamp epoch");
    rebind_before = monotonic_ns();
    CHECK(lucent_android_gles_set_fg_timestamp(backend, true, error, sizeof(error)) &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) && presented &&
          lucent_fake_egl_presentation_time_last() >= rebind_before &&
          lucent_fake_egl_presentation_time_last() <= monotonic_ns(),
          "same-mode FG rebind retained the previous Surface epoch");
    timestamp_baseline = lucent_fake_egl_presentation_time_count();
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)) &&
          frontend_framebuffer() == 0 &&
          destroy_count() == 1 &&
          lucent_fake_window_acquire_count() == 2 &&
          lucent_fake_window_release_count() == 2,
          "orderly EGL detach/window ownership mismatch");
    lucent_retro_destroy(host);
    lucent_android_gles_destroy(backend);

    /* PPSSPP renders its declared integer-scaled output independently of the
     * Android destination. At 4x, 1920x1088 must fit in the render allocation
     * even though the aspect-fitted destination is only 1906x1080 (or smaller
     * on another device). Repeat after detach/rebind, as Quick Resume exposed
     * the clipped 1920-wide viewport on Thor. */
    set_geometry = (fn_video_size)dlsym(core_library, "lucent_hw_mock_set_geometry");
    CHECK(set_geometry, "mock geometry setter unavailable");
    for (unsigned smaller = 0; smaller < 2; smaller++) {
        error[0] = '\0';
        const int panel_width = smaller ? 1280 : 1920;
        const int panel_height = smaller ? 720 : 1080;
        const int drawn_width = smaller ? 1271 : 1906;
        const int left = (panel_width - drawn_width) / 2;
        lucent_fake_window_set_size(panel_width, panel_height);
        backend = lucent_android_gles_create(error, sizeof(error));
        CHECK(backend && lucent_android_gles_get_host_options(
                        backend, &options, error, sizeof(error)),
              "PSP-sized host setup failed");
        host = lucent_retro_create_with_options(argv[1], argv[3], argv[4], argv[5],
                                                &options, error, sizeof(error));
        CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)),
              "PSP-sized mock load failed");
        set_geometry(1920, 1088);
        set_video_size(1920, 1088);
        for (unsigned rebind = 0; rebind < 2; rebind++) {
            CHECK(lucent_android_gles_attach(backend, host, &window, error, sizeof(error)),
                  "PSP-sized attach/rebind failed");
            CHECK(lucent_fake_gles_texture_width() >= 1920 &&
                  lucent_fake_gles_texture_height() >= 1088,
                  "frontend render allocation clips the core-declared output");
            CHECK(lucent_retro_run_frame(host, error, sizeof(error)),
                  "PSP-sized core run failed");
            lucent_fake_gles_set_viewport(0, 0, 1920, 1088);
            CHECK(lucent_android_gles_present_if_ready(backend, &presented,
                                                        error, sizeof(error)) &&
                  presented &&
                  lucent_fake_gles_last_blit_source_x0() == 0 &&
                  lucent_fake_gles_last_blit_source_y0() == 0 &&
                  lucent_fake_gles_last_blit_source_x1() == 1920 &&
                  lucent_fake_gles_last_blit_source_y1() == 1088 &&
                  lucent_fake_gles_last_blit_destination_x0() == left &&
                  lucent_fake_gles_last_blit_destination_x1() == left + drawn_width &&
                  lucent_fake_gles_last_blit_destination_y0() == 0 &&
                  lucent_fake_gles_last_blit_destination_y1() == panel_height,
                  "PSP output was clipped, padded or stretched during presentation");
            CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
                  "PSP-sized detach failed");
        }
        lucent_retro_destroy(host);
        lucent_android_gles_destroy(backend);
    }
    /* Flycast declares a 640x480 logical base, a larger maximum FBO capacity,
     * and submits actual 1440x1080 frames. Capacity is not display geometry:
     * allocate the maximum, but never blit its unwritten square padding. */
    set_render_capacity = (fn_render_capacity)dlsym(
            core_library, "lucent_hw_mock_set_render_capacity");
    CHECK(set_render_capacity, "mock render capacity setter unavailable");
    for (unsigned smaller = 0; smaller < 2; smaller++) {
        const int panel_width = smaller ? 1280 : 1920;
        const int panel_height = smaller ? 720 : 1080;
        const int drawn_width = panel_height * 4 / 3;
        const int left = (panel_width - drawn_width) / 2;
        lucent_fake_window_set_size(panel_width, panel_height);
        backend = lucent_android_gles_create(error, sizeof(error));
        CHECK(backend && lucent_android_gles_get_host_options(
                        backend, &options, error, sizeof(error)),
              "maximum-capacity host setup failed");
        host = lucent_retro_create_with_options(argv[1], argv[3], argv[4], argv[5],
                                                &options, error, sizeof(error));
        CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)),
              "maximum-capacity mock load failed");
        set_render_capacity(640, 480, 1920, 1920);
        for (unsigned rebind = 0; rebind < 2; rebind++) {
            CHECK(lucent_android_gles_attach(backend, host, &window, error, sizeof(error)),
                  "maximum-capacity attach/rebind failed");
            CHECK(lucent_fake_gles_texture_width() >= 1920 &&
                  lucent_fake_gles_texture_height() >= 1920,
                  "frontend render allocation ignores core maximum geometry");
            for (unsigned scaled = 0; scaled < 2; scaled++) {
                const int width = scaled ? 1440 : 640;
                const int height = scaled ? 1080 : 480;
                set_video_size(width, height);
                CHECK(lucent_retro_run_frame(host, error, sizeof(error)),
                      "maximum-capacity core run failed");
                lucent_fake_gles_set_viewport(0, 0, width, height);
                CHECK(lucent_android_gles_present_if_ready(backend, &presented,
                                                            error, sizeof(error)) &&
                      presented &&
                      lucent_fake_gles_last_blit_source_x0() == 0 &&
                      lucent_fake_gles_last_blit_source_y0() == 0 &&
                      lucent_fake_gles_last_blit_source_x1() == width &&
                      lucent_fake_gles_last_blit_source_y1() == height &&
                      lucent_fake_gles_last_blit_destination_x0() == left &&
                      lucent_fake_gles_last_blit_destination_x1() == left + drawn_width &&
                      lucent_fake_gles_last_blit_destination_y0() == 0 &&
                      lucent_fake_gles_last_blit_destination_y1() == panel_height,
                      "maximum-capacity output was clipped, padded or stretched");
            }
            CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
                  "maximum-capacity detach failed");
        }
        lucent_retro_destroy(host);
        lucent_android_gles_destroy(backend);
    }
    set_video_size(4, 4);
    lucent_fake_window_set_size(1920, 1080);

    /* Dolphin clears all of the backing FBO, but reports a smaller complete
     * output rectangle and leaves a non-origin scratch viewport. Cleared
     * pixels outside the callback dimensions are not additional game video.
     * Both first presentation and context recreation must use the callback,
     * without running N64's pixel probe or waiting through 600 callbacks. */
    error[0] = '\0';
    backend = lucent_android_gles_create(error, sizeof(error));
    CHECK(backend && lucent_android_gles_set_presentation_policy(
                    backend, LUCENT_ANDROID_GLES_PRESENT_FRONTEND_FBO,
                    error, sizeof(error)) &&
          lucent_android_gles_set_presentation_aspect(
                    backend, 4.0f / 3.0f, error, sizeof(error)) &&
          lucent_android_gles_get_host_options(backend, &options,
                                               error, sizeof(error)),
          "callback-geometry policy setup failed");
    host = lucent_retro_create_with_options(argv[1], argv[3], argv[4], argv[5],
                                            &options, error, sizeof(error));
    CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)),
          "callback-geometry core load failed");
    set_video_size(1280, 1056);
    for (unsigned cycle = 0; cycle < 2; ++cycle) {
        unsigned bounds_reads = lucent_fake_gles_bounds_readbacks();
        direct_swap_baseline = lucent_fake_egl_swap_count();
        CHECK(lucent_android_gles_attach(backend, host, &window, error, sizeof(error)) &&
              lucent_retro_run_frame(host, error, sizeof(error)),
              "callback-geometry attach/run failed");
        lucent_fake_gles_set_viewport(0, 160, 1216, 896);
        CHECK(lucent_android_gles_present_if_ready(backend, &presented,
                                                   error, sizeof(error)) &&
              presented && lucent_fake_egl_swap_count() == direct_swap_baseline + 1 &&
              lucent_fake_gles_bounds_readbacks() == bounds_reads &&
              lucent_fake_gles_last_blit_source_x0() == 0 &&
              lucent_fake_gles_last_blit_source_y0() == 0 &&
              lucent_fake_gles_last_blit_source_x1() == 1280 &&
              lucent_fake_gles_last_blit_source_y1() == 1056 &&
              lucent_fake_gles_last_blit_destination_x0() == 240 &&
              lucent_fake_gles_last_blit_destination_x1() == 1680 &&
              lucent_fake_gles_last_blit_destination_y1() == 1080,
              "pixel probe overrode callback geometry or delayed first presentation");
        CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
              "callback-geometry detach failed");
    }
    set_video_size(4, 4);
    lucent_retro_destroy(host);
    lucent_android_gles_destroy(backend);

    /* N64's 1440x1080 VI target is independent of the phone's 960x720
     * presentation fit. The sentinel probe must inspect the full allocation,
     * or it freezes a plausible but truncated lower-left source rectangle. */
    {
        void *mupen_library = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
        CHECK(mupen_library, "phone N64 core inspection failed");
        fn_render_capacity set_capacity = (fn_render_capacity)dlsym(
                mupen_library, "lucent_hw_mock_set_render_capacity");
        CHECK(set_capacity, "phone N64 geometry setter missing");
        /* A native-resolution target can be smaller than the display fit.
         * Allocation must follow the declared core extent; otherwise the
         * sentinel probe rejects a real frame for600callbacks on a phone. */
        for (unsigned mode = 0; mode < 4; ++mode) {
            const int panel_height = mode < 2 ? 720 : 1080;
            const int panel_width = panel_height * 16 / 9;
            const int width = mode % 2 ? 640 : 320;
            const int height = width * 3 / 4;
            const int destination_width = panel_height * 4 / 3;
            const int left = (panel_width - destination_width) / 2;
            lucent_fake_window_set_size(panel_width, panel_height);
            backend = lucent_android_gles_create(error, sizeof(error));
            CHECK(backend && lucent_android_gles_set_presentation_policy(
                    backend, LUCENT_ANDROID_GLES_PRESENT_FRONTEND_FBO, error, sizeof(error)) &&
                  lucent_android_gles_set_presentation_aspect(
                    backend, 4.0f / 3.0f, error, sizeof(error)) &&
                  lucent_android_gles_get_host_options(backend, &options, error, sizeof(error)),
                  "native N64 backend setup failed");
            options.source_timeline_policy = LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS;
            options.preferred_context = LUCENT_RETRO_HW_GLES3;
            host = lucent_retro_create_with_options(argv[2], argv[3], argv[4], argv[5],
                                                   &options, error, sizeof(error));
            CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)),
                  "native N64 load failed");
            set_capacity(width, height, width, height);
            lucent_fake_gles_set_sentinel_bounds(1);
            lucent_fake_gles_set_written_rect(8, 8, width - 8, height - 8);
            for (unsigned rebind = 0; rebind < 2; ++rebind) {
                CHECK(lucent_android_gles_attach(backend, host, &window, error, sizeof(error)) &&
                      lucent_fake_gles_texture_width() == width &&
                      lucent_fake_gles_texture_height() == height,
                      "N64 allocation inflated native core capacity to display size");
                CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
                      lucent_retro_run_frame(host, error, sizeof(error)) &&
                      lucent_retro_run_frame(host, error, sizeof(error)), "native N64 run failed");
                lucent_fake_gles_set_viewport(0, 0, width, height);
                CHECK(lucent_android_gles_present_if_ready(backend, &presented, error, sizeof(error)) &&
                      presented && lucent_fake_gles_last_blit_source_x0() == 8 &&
                      lucent_fake_gles_last_blit_source_y0() == 8 &&
                      lucent_fake_gles_last_blit_source_x1() == width - 8 &&
                      lucent_fake_gles_last_blit_source_y1() == height - 8 &&
                      lucent_fake_gles_last_blit_destination_x0() == left &&
                      lucent_fake_gles_last_blit_destination_x1() == left + destination_width &&
                      lucent_fake_gles_last_blit_destination_y0() == 0 &&
                      lucent_fake_gles_last_blit_destination_y1() == panel_height,
                      "native N64 first image delayed, cropped or fitted incorrectly");
                CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
                      "native N64 detach failed");
            }
            lucent_retro_destroy(host);
            lucent_android_gles_destroy(backend);
        }
        for (unsigned smaller = 0; smaller < 2; ++smaller) {
            const int panel_height = smaller ? 720 : 1080;
            const int panel_width = smaller ? 1280 : 1920;
            const int drawn_width = panel_height * 4 / 3;
            const int left = (panel_width - drawn_width) / 2;
            lucent_fake_window_set_size(panel_width, panel_height);
            backend = lucent_android_gles_create(error, sizeof(error));
            CHECK(backend && lucent_android_gles_set_presentation_policy(
                            backend, LUCENT_ANDROID_GLES_PRESENT_FRONTEND_FBO,
                            error, sizeof(error)) &&
                  lucent_android_gles_set_presentation_aspect(
                            backend, 4.0f / 3.0f, error, sizeof(error)) &&
                  lucent_android_gles_get_host_options(backend, &options,
                                                         error, sizeof(error)),
                  "phone N64 backend setup failed");
            options.source_timeline_policy =
                    LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS;
            options.preferred_context = LUCENT_RETRO_HW_GLES3;
            host = lucent_retro_create_with_options(argv[2], argv[3], argv[4],
                                                    argv[5], &options,
                                                    error, sizeof(error));
            CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)),
                  "phone N64 core load failed");
            set_capacity(1440, 1080, 1440, 1080);
            lucent_fake_gles_set_sentinel_bounds(2);
            for (unsigned rebind = 0; rebind < 2; ++rebind) {
                CHECK(lucent_android_gles_attach(backend, host, &window,
                                                  error, sizeof(error)) &&
                      lucent_retro_run_frame(host, error, sizeof(error)) &&
                      lucent_retro_run_frame(host, error, sizeof(error)) &&
                      lucent_retro_run_frame(host, error, sizeof(error)),
                      "phone N64 attach/run failed");
                lucent_fake_gles_set_viewport(0, 0, 1440, 1080);
                CHECK(lucent_android_gles_present_if_ready(backend, &presented,
                                                            error, sizeof(error)) &&
                      presented &&
                      lucent_fake_gles_last_blit_source_x0() == 100 &&
                      lucent_fake_gles_last_blit_source_y0() == 50 &&
                      lucent_fake_gles_last_blit_source_x1() == 1340 &&
                      lucent_fake_gles_last_blit_source_y1() == 1030 &&
                      lucent_fake_gles_last_blit_destination_x0() == left &&
                      lucent_fake_gles_last_blit_destination_x1() == left + drawn_width &&
                      lucent_fake_gles_last_blit_destination_y0() == 0 &&
                      lucent_fake_gles_last_blit_destination_y1() == panel_height,
                      "phone N64 probe clipped full VI image to display-fit dimensions");
                CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
                      "phone N64 detach failed");
            }
            lucent_retro_destroy(host);
            lucent_android_gles_destroy(backend);
        }
        dlclose(mupen_library);
        lucent_fake_gles_set_sentinel_bounds(0);
        lucent_fake_window_set_size(1920, 1080);
    }

    /* GLideN64 can leave a scratch viewport larger than the frontend FBO and
     * render a title-specific VI rectangle inside it. Only the untouched cyan
     * sentinel may be excluded; the complete written rectangle is then fitted
     * to the core-declared display aspect. */
    direct_swap_baseline = lucent_fake_egl_swap_count();
    direct_blit_baseline = lucent_fake_gles_blit_count();
    backend = lucent_android_gles_create(error, sizeof(error));
    CHECK(backend && lucent_android_gles_set_presentation_policy(
                    backend, LUCENT_ANDROID_GLES_PRESENT_FRONTEND_FBO,
                    error, sizeof(error)) &&
          lucent_android_gles_set_presentation_aspect(
                    backend, 4.0f / 3.0f, error, sizeof(error)) &&
          lucent_android_gles_get_host_options(backend, &options,
                                               error, sizeof(error)),
          "title-dynamic frontend-FBO policy setup failed");
    /* Content-bounds cropping is independent of the VI-origin callback
     * filter tested below: it must engage even with the VI-origin bit
     * clear, i.e. with frame generation off (2026-09-06 "blue edges" fix). */
    options.source_timeline_policy =
            LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS;
    options.preferred_context = LUCENT_RETRO_HW_GLES3;
    host = lucent_retro_create_with_options(argv[2], argv[3], argv[4], argv[5],
                                            &options, error, sizeof(error));
    lucent_fake_gles_set_sentinel_bounds(2);
    CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)),
          "title-dynamic core load failed");
    {
        void *mupen_library = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
        CHECK(mupen_library, "title-dynamic core inspection failed");
        fn_render_capacity set_capacity = (fn_render_capacity)dlsym(
                mupen_library, "lucent_hw_mock_set_render_capacity");
        CHECK(set_capacity, "title-dynamic geometry setter missing");
        set_capacity(1440, 1080, 1440, 1080);
        dlclose(mupen_library);
    }
    CHECK(lucent_android_gles_attach(backend, host, &window, error, sizeof(error)) &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          (lucent_fake_gles_set_viewport(0, 0, 2880, 2880), true) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          presented && lucent_fake_egl_swap_count() == direct_swap_baseline + 1 &&
          lucent_fake_gles_blit_count() == direct_blit_baseline + 1 &&
          lucent_fake_gles_last_blit_source_x0() == 100 &&
          lucent_fake_gles_last_blit_source_y0() == 50 &&
          lucent_fake_gles_last_blit_source_x1() == 1340 &&
          lucent_fake_gles_last_blit_source_y1() == 1030 &&
          lucent_fake_gles_last_blit_destination_x0() == 240 &&
          lucent_fake_gles_last_blit_destination_y0() == 0 &&
          lucent_fake_gles_last_blit_destination_x1() == 1680 &&
          lucent_fake_gles_last_blit_destination_y1() == 1080,
          "title-dynamic frontend bounds exposed sentinel or changed aspect");
    /* Ocarina can spend many frames in a letterboxed cutscene, then draw its
     * HUD into those previously black rows. Freeze only untouched allocation
     * bounds, never black image pixels, even after the startup probe settles. */
    unsigned letterbox_presentations = 0;
    unsigned gameplay_presentations = 0;
    for (unsigned transition_frame = 0; transition_frame < 24; ++transition_frame) {
        if (transition_frame == 15) {
            CHECK(letterbox_presentations >= 4,
                  "letterbox bounds must settle before gameplay transition");
            lucent_fake_gles_set_sentinel_bounds(1);
        }
        CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
              lucent_android_gles_present_if_ready(backend, &presented,
                                                   error, sizeof(error)),
              "letterbox-to-gameplay presentation failed");
        if (presented) {
            if (transition_frame < 15) ++letterbox_presentations;
            else ++gameplay_presentations;
            CHECK(lucent_fake_gles_last_blit_source_x0() == 100 &&
                  lucent_fake_gles_last_blit_source_y0() == 50 &&
                  lucent_fake_gles_last_blit_source_x1() == 1340 &&
                  lucent_fake_gles_last_blit_source_y1() == 1030,
                  "startup black bands cropped later gameplay pixels");
        }
    }
    CHECK(gameplay_presentations >= 2,
          "gameplay transition must verify multiple presented frames");
    {
        /* A core's actual final VI rectangle can change long after startup.
         * It supersedes the settled sentinel probe, preserving display pixel
         * proportions, including legitimate black pixels inside the rectangle. */
        typedef void (*fn_active_rect)(const uint32_t *);
        void *mupen_library = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
        CHECK(mupen_library, "active-rectangle core inspection failed");
        fn_active_rect set_rect = (fn_active_rect)dlsym(
                mupen_library, "lucent_hw_mock_set_active_rect");
        CHECK(set_rect, "active-rectangle mock setter missing");
        uint32_t rectangles[][7] = {
            {1, 24, 40, 1392, 1000, 1440, 1080},
            {1, 0, 0, 1440, 1080, 1440, 1080},
            {1, 0, 240, 1440, 600, 1440, 1080}
        };
        const int destinations[][4] = {
            {208, 0, 1711, 1080}, {240, 0, 1680, 1080}, {0, 140, 1920, 940}
        };
        unsigned readbacks = lucent_fake_gles_bounds_readbacks();
        for (unsigned mode = 0; mode < 3; ++mode) {
            set_rect(rectangles[mode]);
            CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
                  lucent_retro_run_frame(host, error, sizeof(error)) &&
                  lucent_retro_run_frame(host, error, sizeof(error)) &&
                  lucent_android_gles_present_if_ready(backend, &presented,
                                                       error, sizeof(error)) && presented,
                  "active VI mode change did not present");
            CHECK(lucent_fake_gles_last_blit_source_x0() == (int)rectangles[mode][1] &&
                  lucent_fake_gles_last_blit_source_y0() == (int)rectangles[mode][2] &&
                  lucent_fake_gles_last_blit_source_x1() == (int)(rectangles[mode][1] + rectangles[mode][3]) &&
                  lucent_fake_gles_last_blit_source_y1() == (int)(rectangles[mode][2] + rectangles[mode][4]) &&
                  lucent_fake_gles_last_blit_destination_x0() == destinations[mode][0] &&
                  lucent_fake_gles_last_blit_destination_y0() == destinations[mode][1] &&
                  lucent_fake_gles_last_blit_destination_x1() == destinations[mode][2] &&
                  lucent_fake_gles_last_blit_destination_y1() == destinations[mode][3] &&
                  lucent_fake_gles_bounds_readbacks() == readbacks,
                  "active VI fit stretched/cropped pixels or performed bounds readback");
        }
        uint32_t invalid[7] = {1, UINT32_MAX, 0, 1440, 1080, 1440, 1080};
        uint32_t queried[7] = {0};
        set_rect(invalid);
        CHECK(!lucent_retro_get_hw_active_rect(host, queried),
              "overflowing active rectangle accepted");
        invalid[1] = 0;
        invalid[0] = 2;
        set_rect(invalid);
        CHECK(!lucent_retro_get_hw_active_rect(host, queried),
              "unknown active-rectangle ABI accepted");
        set_rect(rectangles[0]);
        CHECK(lucent_android_gles_detach(backend, error, sizeof(error)) &&
              !lucent_retro_get_hw_active_rect(host, queried),
              "detached context exposed stale active rectangle");
        dlclose(mupen_library);
    }
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
          "title-dynamic frontend-FBO detach failed");
    lucent_fake_gles_set_sentinel_bounds(0);
    lucent_retro_destroy(host);
    lucent_android_gles_destroy(backend);

    /* A direct-window engine must receive framebuffer zero and swap without
     * Lucent overwriting the core's window image. */
    direct_swap_baseline = lucent_fake_egl_swap_count();
    direct_blit_baseline = lucent_fake_gles_blit_count();
    backend = lucent_android_gles_create(error, sizeof(error));
    CHECK(backend && lucent_android_gles_set_presentation_policy(
                    backend, LUCENT_ANDROID_GLES_PRESENT_DIRECT_WINDOW,
                    error, sizeof(error)) &&
          lucent_android_gles_get_host_options(backend, &options,
                                               error, sizeof(error)),
          "direct-window GLES policy setup failed");
    host = lucent_retro_create_with_options(argv[1], argv[3], argv[4], argv[5],
                                            &options, error, sizeof(error));
    CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)) &&
          lucent_android_gles_attach(backend, host, &window, error, sizeof(error)) &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          presented && lucent_fake_egl_swap_count() == direct_swap_baseline + 1 &&
          lucent_fake_gles_blit_count() == direct_blit_baseline,
          "direct-window core was not presented without a frontend blit");
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
          "direct-window GLES detach failed");
    lucent_retro_destroy(host);
    lucent_android_gles_destroy(backend);

    /* A direct-window core whose resolved display aspect differs from its
     * Surface is copied through a private target and centered, while still
     * receiving framebuffer zero. */
    direct_swap_baseline = lucent_fake_egl_swap_count();
    direct_blit_baseline = lucent_fake_gles_blit_count();
    backend = lucent_android_gles_create(error, sizeof(error));
    CHECK(backend && lucent_android_gles_set_presentation_policy(
                    backend, LUCENT_ANDROID_GLES_PRESENT_DIRECT_WINDOW,
                    error, sizeof(error)) &&
          lucent_android_gles_set_presentation_aspect(
                    backend, 4.0f / 3.0f, error, sizeof(error)) &&
          lucent_android_gles_get_host_options(backend, &options,
                                               error, sizeof(error)),
          "fitted direct-window GLES policy setup failed");
    host = lucent_retro_create_with_options(argv[1], argv[3], argv[4], argv[5],
                                            &options, error, sizeof(error));
    CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)) &&
          lucent_android_gles_attach(backend, host, &window, error, sizeof(error)) &&
          frontend_framebuffer() == 0 &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          (lucent_fake_gles_set_viewport(0, 0, 1280, 1056), true) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          presented && lucent_fake_egl_swap_count() == direct_swap_baseline + 1 &&
          lucent_fake_gles_blit_count() == direct_blit_baseline + 2 &&
          lucent_fake_gles_last_blit_destination_x0() == 240 &&
          lucent_fake_gles_last_blit_destination_y0() == 0 &&
          lucent_fake_gles_last_blit_destination_x1() == 1680 &&
          lucent_fake_gles_last_blit_destination_y1() == 1080 &&
          lucent_fake_gles_previous_blit_source_x0() == 0 &&
          lucent_fake_gles_previous_blit_source_y0() == 0 &&
          lucent_fake_gles_previous_blit_source_x1() == 1280 &&
          lucent_fake_gles_previous_blit_source_y1() == 1056,
          "direct-window 4:3 frame was not fitted to 1920x1080");
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
          "fitted direct-window GLES detach failed");
    lucent_retro_destroy(host);
    lucent_android_gles_destroy(backend);

    /* An unusually wide aspect is contained wholly inside the Surface. The
     * complete 2:1 picture is 1920x960 and is vertically centred; no source
     * pixel may be pushed beyond the physical panel and clipped. */
    direct_swap_baseline = lucent_fake_egl_swap_count();
    direct_blit_baseline = lucent_fake_gles_blit_count();
    backend = lucent_android_gles_create(error, sizeof(error));
    CHECK(backend && lucent_android_gles_set_presentation_policy(
                    backend, LUCENT_ANDROID_GLES_PRESENT_DIRECT_WINDOW,
                    error, sizeof(error)) &&
          lucent_android_gles_set_presentation_aspect(
                    backend, 2.0f, error, sizeof(error)) &&
          lucent_android_gles_get_host_options(backend, &options,
                                               error, sizeof(error)),
          "full-height wide GLES policy setup failed");
    host = lucent_retro_create_with_options(argv[1], argv[3], argv[4], argv[5],
                                            &options, error, sizeof(error));
    CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)) &&
          lucent_android_gles_attach(backend, host, &window, error, sizeof(error)) &&
          frontend_framebuffer() == 0 &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          presented && lucent_fake_egl_swap_count() == direct_swap_baseline + 1 &&
          lucent_fake_gles_blit_count() == direct_blit_baseline + 2 &&
          lucent_fake_gles_last_blit_destination_x0() == 0 &&
          lucent_fake_gles_last_blit_destination_y0() == 60 &&
          lucent_fake_gles_last_blit_destination_x1() == 1920 &&
          lucent_fake_gles_last_blit_destination_y1() == 1020,
          "wide direct-window frame was clipped instead of wholly contained");
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
          "full-height wide GLES detach failed");
    lucent_retro_destroy(host);
    lucent_android_gles_destroy(backend);

    /* Mupen64Plus-Next's GLideN64 path asks for GLES3 + depth +
     * cache_context. Prove that the cache flag is the only additional gate,
     * then exercise the complete attach/frame/detach lifecycle. This keeps the
     * production host fail-closed for debug/shared contexts rather than
     * weakening negotiation generically. */
    backend = lucent_android_gles_create(error, sizeof(error));
    CHECK(backend && lucent_android_gles_get_host_options(
                    backend, &options, error, sizeof(error)),
          "Mupen GLES host options failed");
    options.preferred_context = LUCENT_RETRO_HW_GLES3;
    options.feature_capabilities &= ~LUCENT_RETRO_HW_CACHE_CONTEXT;
    host = lucent_retro_create_with_options(argv[2], argv[3], argv[4], argv[5],
                                            &options, error, sizeof(error));
    CHECK(host && !lucent_retro_load_game(host, argv[6], error, sizeof(error)),
          "Mupen cache-context request bypassed the capability gate");
    lucent_retro_destroy(host);

    options.feature_capabilities |= LUCENT_RETRO_HW_CACHE_CONTEXT;
    host = lucent_retro_create_with_options(argv[2], argv[3], argv[4], argv[5],
                                            &options, error, sizeof(error));
    CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)) &&
          lucent_android_gles_attach(backend, host, &window, error, sizeof(error)) &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          presented && lucent_retro_get_hw_info(host, &hw) &&
          hw.frame_sequence == 1,
          "default Mupen VI-update policy stopped presenting each core run");
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
          "default Mupen VI-update detach failed");
    lucent_retro_destroy(host);

    options.source_timeline_policy =
            LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_VI_ORIGIN;
    host = lucent_retro_create_with_options(argv[2], argv[3], argv[4], argv[5],
                                            &options, error, sizeof(error));
    CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)) &&
          lucent_retro_get_hw_info(host, &hw) && hw.negotiated &&
          hw.context_type == RETRO_HW_CONTEXT_OPENGLES3 && hw.depth &&
          !hw.stencil && hw.cache_context && !hw.debug_context,
          "Mupen GLES3/depth/cache negotiation failed");
    direct_swap_baseline = lucent_fake_egl_swap_count();
    CHECK(lucent_android_gles_attach(backend, host, &window, error, sizeof(error)),
          "Mupen-shaped GLES core did not attach");
    CHECK(lucent_fake_egl_presentation_time_count() == timestamp_baseline,
          "new direct backends did not default to Off");
    CHECK(lucent_android_gles_set_fg_timestamp(backend, true, error, sizeof(error)),
          "sparse Mupen FG source timestamp opt-in failed");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          !presented &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          !presented &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          presented && lucent_retro_get_hw_info(host, &hw) &&
          hw.frame_sequence == 3 &&
          lucent_fake_egl_swap_count() == direct_swap_baseline + 1,
          "VI-origin source boundary did not preserve core-run ordinal 3");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          !presented &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          !presented &&
          lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented,
                                               error, sizeof(error)) &&
          presented && lucent_retro_get_hw_info(host, &hw) &&
          hw.frame_sequence == 6 &&
          lucent_fake_egl_presentation_time_delta() == 50000000,
          "sparse Mupen presents were compressed off the 60-Hz core timeline");
    CHECK(lucent_retro_drain_audio(host, mupen_audio_samples, 6) == 6,
          "VI-origin video selection changed the 60-Hz emulation/audio cadence");
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)),
          "Mupen-shaped orderly GLES detach failed");
    lucent_retro_destroy(host);
    lucent_android_gles_destroy(backend);
    /* Keep the first instrumented mock DSO resident until the second one is
     * gone. macOS ASan otherwise reuses the exact mapping while retaining the
     * first DSO's global-redzone metadata, producing a false positive in the
     * shared variadic log callback. */
    /* Real backend warmup: one swap per call, no guest/audio counters, complete
     * GL-state restoration, and temporary timestamp collection only. */
    backend = lucent_android_gles_create(error, sizeof(error));
    CHECK(backend && lucent_android_gles_get_host_options(backend, &options, error, sizeof(error)), "warmup create");
    host = lucent_retro_create_with_options(argv[1], argv[3], argv[4], argv[5], &options, error, sizeof(error));
    CHECK(host && lucent_retro_load_game(host, argv[6], error, sizeof(error)) &&
          lucent_android_gles_attach(backend, host, &window, error, sizeof(error)), "warmup attach");
    bool resume_ready = false;
    unsigned swaps_before = lucent_fake_egl_swap_count();
    CHECK(lucent_android_gles_prepare_resume(backend, &resume_ready, error, sizeof(error)) &&
          resume_ready && lucent_fake_egl_swap_count() == swaps_before, "cold launch must not warm up");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)) &&
          lucent_android_gles_present_if_ready(backend, &presented, error, sizeof(error)) && presented &&
          lucent_android_gles_detach(backend, error, sizeof(error)) &&
          lucent_android_gles_attach(backend, host, &window, error, sizeof(error)), "warmup rebind");
    lucent_fake_egl_completion_support(1);
    lucent_fake_egl_hold_completions(1);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, 71);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 72);
    glClearColor(.1f, .2f, .3f, .4f);
    glColorMask(GL_TRUE, GL_FALSE, GL_TRUE, GL_FALSE);
    lucent_fake_gles_set_scissor_enabled(1);
    CHECK(lucent_retro_serialize(host, &state, sizeof(state), error, sizeof(error)), "warmup state before");
    uint32_t state_before_warmup = state;
    CHECK(lucent_retro_get_hw_info(host, &hw), "warmup frame info before");
    uint64_t sequence_before_warmup = hw.frame_sequence;
    swaps_before = lucent_fake_egl_swap_count();
    CHECK(lucent_android_gles_prepare_resume(backend, &resume_ready, error, sizeof(error)) &&
          !resume_ready && lucent_fake_egl_swap_count() == swaps_before + 1 &&
          lucent_fake_egl_completion_enabled(), "warmup must yield after one non-game swap");
    /* The host scheduler is not a display: macOS can coalesce a17ms sleep
     * into25ms. Explicit scanout completions also test pending-query handling. */
    for (unsigned attempt = 0; attempt < 2; ++attempt)
        CHECK(lucent_android_gles_prepare_resume(backend, &resume_ready, error, sizeof(error)) &&
              !resume_ready, "pending presentation is not readiness");
    lucent_fake_egl_complete_last_frames(3, 16666667);
    CHECK(lucent_android_gles_prepare_resume(backend, &resume_ready, error, sizeof(error)), "warmup step");
    CHECK(resume_ready && !lucent_fake_egl_completion_enabled(), "consecutive presents finish and disable collection");
    CHECK(lucent_retro_serialize(host, &state, sizeof(state), error, sizeof(error)) && state == state_before_warmup &&
          lucent_retro_get_hw_info(host, &hw) && hw.frame_sequence == sequence_before_warmup,
          "warmup advanced guest state/frame sequence");
    GLint read_after = 0, draw_after = 0;
    GLfloat clear_after[4]; GLboolean mask_after[4];
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &read_after);
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &draw_after);
    glGetFloatv(GL_COLOR_CLEAR_VALUE, clear_after);
    glGetBooleanv(GL_COLOR_WRITEMASK, mask_after);
    CHECK(read_after == 71 && draw_after == 72 && lucent_fake_gles_scissor_enabled() &&
          clear_after[0] == .1f && clear_after[3] == .4f && !mask_after[1] && !mask_after[3], "warmup changed cached GL state");
    swaps_before = lucent_fake_egl_swap_count();
    CHECK(lucent_android_gles_prepare_resume(backend, &resume_ready, error, sizeof(error)) &&
          resume_ready && lucent_fake_egl_swap_count() == swaps_before, "ordinary frames must bypass warmup");
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)) &&
          lucent_android_gles_attach(backend, host, &window, error, sizeof(error)) &&
          lucent_android_gles_prepare_resume(backend, &resume_ready, error, sizeof(error)) && !resume_ready &&
          lucent_android_gles_detach(backend, error, sizeof(error)) && !lucent_fake_egl_completion_enabled(),
          "detach must cancel pending warmup and disable collection");
    CHECK(lucent_android_gles_attach(backend, host, &window, error, sizeof(error)), "timeout rebind");
    lucent_fake_egl_hold_completions(1);
    swaps_before = lucent_fake_egl_swap_count();
    for (unsigned attempt = 0; attempt < 120; ++attempt)
        CHECK(lucent_android_gles_prepare_resume(backend, &resume_ready, error, sizeof(error)) &&
              !resume_ready, "unresolved presents incorrectly qualified readiness");
    CHECK(lucent_android_gles_prepare_resume(backend, &resume_ready, error, sizeof(error)) &&
          resume_ready && !lucent_fake_egl_completion_enabled() &&
          lucent_fake_egl_swap_count() == swaps_before + 120,
          "unresolved driver timestamps can hang resume indefinitely");
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)), "timeout detach");
    lucent_fake_egl_hold_completions(0);
    CHECK(lucent_android_gles_attach(backend, host, &window, error, sizeof(error)) &&
          lucent_android_gles_set_fg_timestamp(backend, true, error, sizeof(error)), "FG warmup setup");
    swaps_before = lucent_fake_egl_swap_count();
    CHECK(lucent_android_gles_prepare_resume(backend, &resume_ready, error, sizeof(error)) && resume_ready &&
          lucent_fake_egl_swap_count() == swaps_before, "FG must never receive placeholder frames");
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)) &&
          lucent_android_gles_attach(backend, host, &window, error, sizeof(error)), "unsupported driver rebind");
    lucent_fake_egl_completion_support(0);
    CHECK(lucent_android_gles_prepare_resume(backend, &resume_ready, error, sizeof(error)) && resume_ready &&
          lucent_fake_egl_swap_count() == swaps_before, "unsupported driver must retain working legacy path");
    CHECK(lucent_android_gles_detach(backend, error, sizeof(error)), "warmup final detach");
    lucent_retro_destroy(host);
    lucent_android_gles_destroy(backend);
    dlclose(core_library);
    puts("Android EGL/GLES attach, present, loss, recovery, and detach passed");
    return 0;
}
