#include "../include/lucent_native_adapter_host.h"

#include <stdint.h>
#include <dlfcn.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#define CHECK(value, message) do { \
    if (!(value)) { fprintf(stderr, "%s: %s\n", message, error); return 1; } \
} while (0)

/* Caller-owned audio sink: counts the frames the adapter emits. */
typedef struct {
    size_t frames;
    int16_t first_left;
    int16_t first_right;
} audio_capture;

static size_t capture_audio(void *ctx, const int16_t *frames, size_t frame_count) {
    audio_capture *capture = (audio_capture *)ctx;
    if (!capture || !frames || frame_count == 0) return 0;
    if (capture->frames == 0) {
        capture->first_left = frames[0];
        capture->first_right = frames[1];
    }
    capture->frames += frame_count;
    return frame_count;
}

int main(int argc, char **argv) {
    char error[512] = {0};
    lucent_native_adapter_host *host;
    lucent_native_capabilities caps;
    lucent_native_load_request request;
    lucent_native_io io;
    uint32_t primary_window = 0;
    uint32_t lower_window = 0;
    audio_capture audio;
    char sentinel_path[4096];
    FILE *sentinel;
    size_t written = 1;
    uint8_t buffer[8];

    if (argc != 8) {
        fprintf(stderr, "usage: native_adapter_host_test GOOD_ADAPTER "
                        "MISMATCH_ADAPTER SETTER_ADAPTER SETTER_FAILURE_ADAPTER "
                        "TRUSTED_ROOT SAVE_DIR CONTENT\n");
        return 2;
    }

    lucent_native_adapter_supply_java_vm((void *)(uintptr_t)0x1234u);
    host = lucent_native_adapter_open(argv[4], argv[5], error, sizeof(error));
    CHECK(!host, "adapter whose JavaVM setter failed was accepted");
    memset(error, 0, sizeof(error));
    host = lucent_native_adapter_open(argv[3], argv[5], error, sizeof(error));
    CHECK(host, "adapter whose versioned JavaVM setter succeeded was rejected");
    lucent_native_adapter_destroy(host);
    memset(error, 0, sizeof(error));

    /* Fail closed on an ABI-mismatched adapter (the vtable loads and links, but
     * its abi_version is wrong). */
    host = lucent_native_adapter_open(argv[2], argv[5], error, sizeof(error));
    CHECK(!host, "adapter with mismatched ABI was accepted");

    /* A well-formed adapter opens and its cached, honest report is available
     * before create(). */
    host = lucent_native_adapter_open(argv[1], argv[5], error, sizeof(error));
    CHECK(host, "valid adapter failed to open");
    CHECK(lucent_native_adapter_describe(host, &caps, error, sizeof(error)),
          "describe failed before create");
    CHECK(caps.abi_version == LUCENT_NATIVE_ADAPTER_ABI_VERSION,
          "describe reported the wrong ABI");
    CHECK(strcmp(caps.engine_id, "mock-wiiu") == 0, "engine id mismatch");
    CHECK(!caps.has_quick_resume, "mock must not advertise Quick Resume");
    CHECK(caps.has_persistent_save, "mock must advertise persistent save");
    CHECK(caps.dual_screen, "mock must advertise dual screen");
    CHECK(!lucent_native_adapter_has_quick_resume(host) &&
          lucent_native_adapter_has_persistent_save(host) &&
          lucent_native_adapter_dual_screen(host),
          "cached capability accessors disagree with describe");

    /* Calls before create() fail closed. */
    CHECK(!lucent_native_adapter_run_frame(host, error, sizeof(error)),
          "run_frame ran before create");
    CHECK(lucent_native_adapter_declared_video_hz(host) == 0.0,
          "declared video clock reported before content load");
    CHECK(!lucent_native_adapter_set_fg_presentation(host, true),
          "presentation configuration accepted before load");

    CHECK(!lucent_native_adapter_stop(NULL, error, sizeof(error)),
          "stop accepted a missing host");
    CHECK(lucent_native_adapter_stop(host, error, sizeof(error)),
          "cleanup after pre-create preparation failure was rejected");
    CHECK(lucent_native_adapter_stop(host, error, sizeof(error)),
          "pre-create stop is not idempotent");
    lucent_native_adapter_destroy(host);
    host = lucent_native_adapter_open(argv[1], argv[5], error, sizeof(error));
    CHECK(host, "retry after pre-create cleanup failed to open");
    CHECK(lucent_native_adapter_stop(host, error, sizeof(error)),
          "pre-create stop failed before retry");

    CHECK(lucent_native_adapter_create(host, error, sizeof(error)),
          "create failed");
    CHECK(!lucent_native_adapter_create(host, error, sizeof(error)),
          "duplicate create was accepted");

    /* Fail closed on NULL content: a request with no content_path is refused
     * before the adapter is consulted. */
    memset(&request, 0, sizeof(request));
    request.system_directory = argv[5];
    request.save_directory = argv[6];
    request.content_path = NULL;
    CHECK(!lucent_native_adapter_load(host, &request, error, sizeof(error)),
          "adapter loaded NULL content");
    CHECK(!lucent_native_adapter_load(host, NULL, error, sizeof(error)),
          "adapter loaded a NULL request");

    /* start before a successful load fails closed. */
    memset(&io, 0, sizeof(io));
    io.kind = LUCENT_NATIVE_RENDER_VULKAN_WINDOW;
    io.primary_window = &primary_window;
    io.lower_window = &lower_window;
    io.audio_sink = capture_audio;
    memset(&audio, 0, sizeof(audio));
    io.audio_sink_ctx = &audio;
    CHECK(!lucent_native_adapter_start(host, &io, error, sizeof(error)),
          "start ran before content was loaded");

    request.content_path = argv[7];
    CHECK(lucent_native_adapter_load(host, &request, error, sizeof(error)),
          "load failed with valid content");

    /* start requires a primary window. */
    {
        lucent_native_io no_window = io;
        no_window.primary_window = NULL;
        CHECK(!lucent_native_adapter_start(host, &no_window, error, sizeof(error)),
              "start accepted a NULL primary window");
    }
    /* Timing, declarations and mutation remain start-gated. */
    CHECK(lucent_native_adapter_timing_capabilities(host) == 0u,
          "timing capabilities reported before start");
    CHECK(lucent_native_adapter_producer_timeline_hz(host) == 0.0,
          "source timeline reported before start");
    CHECK(lucent_native_adapter_declared_video_hz(host) == 0.0,
          "video declaration reported before start");
    CHECK(!lucent_native_adapter_set_paced_video_hz(host, 40.0),
          "pace accepted before start");
    {
        void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
        CHECK(library, "could not inspect mock presentation state");
        void *symbol = dlsym(library, "lucent_mock_fg_presentation");
        bool (*read_tagging)(void) = NULL;
        CHECK(symbol, "mock presentation reader missing");
        memcpy(&read_tagging, &symbol, sizeof(read_tagging));
        CHECK(!read_tagging(), "presentation tagging must default Off");
        CHECK(lucent_native_adapter_set_fg_presentation(host, true) && read_tagging(),
              "loaded adapter did not enable FG presentation tagging");
        CHECK(lucent_native_adapter_set_fg_presentation(host, false) && !read_tagging(),
              "loaded adapter did not restore Direct presentation tagging");
        dlclose(library);
    }
    CHECK(lucent_native_adapter_start(host, &io, error, sizeof(error)),
          "start failed");

    /* run_frame renders a deterministic pattern to both windows and emits a
     * fixed tone. */
    CHECK(lucent_native_adapter_run_frame(host, error, sizeof(error)),
          "run_frame failed");
    CHECK(primary_window == (0xC0DE0000u | 1u),
          "primary window did not receive the deterministic pattern");
    CHECK(lower_window == ((0xC0DE0000u | 1u) ^ 0x0000FFFFu),
          "lower window did not receive the dual-screen pattern");
    CHECK(audio.frames == 64u && audio.first_left == 0 && audio.first_right == 0,
          "adapter did not emit the fixed tone");
    CHECK(lucent_native_adapter_run_frame(host, error, sizeof(error)),
          "second run_frame failed");
    CHECK(primary_window == (0xC0DE0000u | 2u),
          "primary window pattern is not frame-deterministic");
    CHECK(audio.frames == 128u, "second frame did not emit more audio");

    /* Native dlsym path must enforce the same bounded clock contract as Java. */
    CHECK(lucent_native_adapter_declared_video_hz(host) == 60.0,
          "declared video clock not read from the adapter");
    CHECK(!lucent_native_adapter_set_paced_video_hz(host, 40.0),
          "large load-tier slowdown accepted");
    CHECK(lucent_native_adapter_set_paced_video_hz(host, 59.94),
          "bounded fractional correction refused");
    CHECK(lucent_native_adapter_set_paced_video_hz(host, 59.55),
          "lower inclusive 0.75-percent boundary refused");
    CHECK(!lucent_native_adapter_set_paced_video_hz(host, 59.549999),
          "correction below 0.75-percent boundary accepted");
    CHECK(!lucent_native_adapter_set_paced_video_hz(host, NAN) &&
          !lucent_native_adapter_set_paced_video_hz(host, INFINITY) &&
          !lucent_native_adapter_set_paced_video_hz(host, -1.0),
          "invalid correction accepted");
    CHECK(!lucent_native_adapter_set_paced_video_hz(host, 61.0),
          "pace above the declared clock accepted");
    CHECK(lucent_native_adapter_set_paced_video_hz(host, 0.0),
          "lifting the pace refused");
    CHECK(lucent_native_adapter_timing_capabilities(host) == 0u,
          "old adapter gained invented timing capabilities");
    CHECK(lucent_native_adapter_producer_timeline_hz(host) == 0.0,
          "old adapter gained invented 60-Hz source authority");

    /* pause stops advancement; resume restarts it. */
    CHECK(lucent_native_adapter_pause(host, error, sizeof(error)), "pause failed");
    CHECK(lucent_native_adapter_run_frame(host, error, sizeof(error)),
          "paused run_frame failed");
    CHECK(primary_window == (0xC0DE0000u | 2u), "pause did not stop advancement");
    CHECK(lucent_native_adapter_resume(host, error, sizeof(error)), "resume failed");
    CHECK(lucent_native_adapter_set_control(host, 0u, LUCENT_PAD_A, 1.0f,
                                            error, sizeof(error)),
          "set_control failed while running");
    CHECK(lucent_native_adapter_run_frame(host, error, sizeof(error)),
          "resumed run_frame failed");
    CHECK(primary_window == (0xC0DE0000u | 3u), "resume did not advance");

    /* Quick Resume is refused because the adapter reports it is unavailable —
     * without ever entering the adapter's serialize path. */
    CHECK(lucent_native_adapter_serialize_size(host) == 0,
          "serialize_size exposed a state the adapter cannot guarantee");
    CHECK(!lucent_native_adapter_serialize(host, buffer, sizeof(buffer),
                                           &written, error, sizeof(error)) &&
          written == 0,
          "serialize was not refused without Quick Resume");
    CHECK(!lucent_native_adapter_unserialize(host, buffer, sizeof(buffer),
                                             error, sizeof(error)),
          "unserialize was not refused without Quick Resume");

    /* surface_recreated re-binds the render target. */
    {
        uint32_t new_window = 0;
        lucent_native_io recreated = io;
        recreated.primary_window = &new_window;
        recreated.lower_window = NULL;
        CHECK(lucent_native_adapter_surface_recreated(host, &recreated,
                                                      error, sizeof(error)),
              "surface_recreated failed");
        CHECK(lucent_native_adapter_run_frame(host, error, sizeof(error)),
              "run_frame after surface_recreated failed");
        CHECK(new_window == (0xC0DE0000u | 4u),
              "adapter did not render into the recreated surface");
    }

    /* flush_save writes the sentinel durably. */
    CHECK(lucent_native_adapter_flush_save(host, error, sizeof(error)),
          "flush_save failed");
    if ((size_t)snprintf(sentinel_path, sizeof(sentinel_path),
                         "%s/mock-wiiu.sav", argv[6]) >= sizeof(sentinel_path)) {
        fprintf(stderr, "sentinel path too long\n");
        return 1;
    }
    sentinel = fopen(sentinel_path, "rb");
    CHECK(sentinel, "flush_save did not write the sentinel file");
    fclose(sentinel);

    CHECK(lucent_native_adapter_stop(host, error, sizeof(error)), "stop failed");
    CHECK(lucent_native_adapter_stop(host, error, sizeof(error)),
          "repeated stop was not idempotent");
    CHECK(!lucent_native_adapter_run_frame(host, error, sizeof(error)),
          "run_frame ran after stop");

    lucent_native_adapter_destroy(host);
    puts("native adapter host validation and lifecycle passed");
    return 0;
}
