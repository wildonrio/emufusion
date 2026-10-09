/*
 * Deterministic mock native adapter for Lucent Phase 3 host testing.
 *
 * It implements the full lucent_native_adapter vtable with no real emulation so
 * the host, its vtable/ABI validation, capability gating, the create->load->
 * start->run_frame->flush_save->stop->destroy lifecycle, and every fail-closed
 * path can be proven without the multi-week Cemu core.
 *
 * Test contract for the caller-owned IO:
 *   - primary_window (and lower_window when present) point at a uint32_t. Each
 *     run_frame writes a deterministic checkerboard-ish pattern derived from the
 *     frame counter, so the test can assert the value advanced.
 *   - audio_sink receives a fixed 64-frame stereo tone every run_frame and must
 *     report the frames it consumed.
 *   - flush_save writes a fixed sentinel file, mock-wiiu.sav, into the load
 *     request's save_directory (when one was supplied).
 *
 * Building with -DMOCK_ABI_MISMATCH produces an otherwise-identical adapter that
 * advertises the wrong ABI so the host's fail-closed ABI gate can be exercised.
 */

/* strdup is POSIX; glibc hides it under -std=c11 without this, and the
 * implicit int declaration then truncates the returned pointer. */
#define _POSIX_C_SOURCE 200809L
#include "../include/lucent_native_adapter.h"
#include "../include/lucent_native_source_image.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MOCK_TONE_FRAMES 64u
#define MOCK_PATTERN_BASE 0xC0DE0000u
#define MOCK_SAVE_FILE "mock-wiiu.sav"
static const char MOCK_SENTINEL[] = "LUCENT-MOCK-WIIU-SAVE\n";
#ifndef MOCK_NO_FG_PRESENTATION
static bool mock_fg_presentation;
__attribute__((visibility("default")))
void lucent_native_adapter_set_fg_presentation_v1(bool enabled) {
    mock_fg_presentation = enabled;
}
__attribute__((visibility("default")))
bool lucent_mock_fg_presentation(void) { return mock_fg_presentation; }
#endif

#if defined(MOCK_JAVA_VM_SETTER_SUCCESS) || defined(MOCK_JAVA_VM_SETTER_FAILURE)
__attribute__((visibility("default")))
int lucent_native_adapter_set_java_vm(uint32_t version, void *java_vm) {
#ifdef MOCK_JAVA_VM_SETTER_FAILURE
    (void)version;
    (void)java_vm;
    return 0;
#else
    return version == 1u && java_vm == (void *)(uintptr_t)0x1234u;
#endif
}
#endif

#ifdef MOCK_ABI_MISMATCH
#define MOCK_ABI_VERSION (LUCENT_NATIVE_ADAPTER_ABI_VERSION + 1u)
#else
#define MOCK_ABI_VERSION LUCENT_NATIVE_ADAPTER_ABI_VERSION
#endif

struct lucent_native_engine {
    char *save_directory;
    void *primary_window;
    void *lower_window;
    lucent_native_audio_sink audio_sink;
    void *audio_sink_ctx;
    uint32_t frame_count;
    bool loaded;
    bool started;
    bool paused;
    float last_control_value;
};

/* Optional tier-pacing hooks, exported so the host's dlsym path is proven. */
static double mock_paced_video_hz;

#ifdef MOCK_SOURCE_IMAGE_SIDEBAND
__attribute__((visibility("default")))
uint32_t lucent_native_adapter_source_image_binding_v1(lucent_source_binding_v1 *out, uint32_t size) {
    if (!out || size < sizeof(*out)) return LUCENT_SOURCE_BAD_ARGUMENT;
    memset(out, 0, sizeof(*out));
    out->version = LUCENT_SOURCE_IMAGE_VERSION;
#ifdef MOCK_SOURCE_BAD_BINDING
    out->version = 2;
#endif
    out->struct_size = sizeof(*out);
    out->session_epoch = 11; out->surface_epoch = 12; out->swapchain_epoch = 13;
    return LUCENT_SOURCE_MATCH_ACCEPTED;
}
__attribute__((visibility("default")))
uint32_t lucent_native_adapter_query_source_image_v1(uint64_t session, uint64_t surface,
        uint64_t timestamp, lucent_source_image_v1 *out, uint32_t size) {
    if (!out || size < sizeof(*out)) return LUCENT_SOURCE_BAD_ARGUMENT;
    memset(out, 0, sizeof(*out));
    out->version = LUCENT_SOURCE_IMAGE_VERSION; out->struct_size = sizeof(*out);
    out->state = LUCENT_SOURCE_MATCH_ACCEPTED;
    out->buffer_timestamp_ns = timestamp;
#ifdef MOCK_SOURCE_BAD_ROW
    ++out->buffer_timestamp_ns;
#endif
    out->composition.header.session_epoch = session;
    out->composition.header.surface_epoch = surface;
    out->composition.header.swapchain_epoch = 13;
    out->composition.layers[0].queue_frame_number = 42;
    return LUCENT_SOURCE_MATCH_ACCEPTED;
}
#endif

#ifdef MOCK_TIMING_CAPABILITIES
__attribute__((visibility("default")))
uint32_t lucent_native_adapter_timing_capabilities_v1(void) {
    return MOCK_TIMING_CAPABILITIES;
}
#endif
#ifdef MOCK_PRODUCER_TIMELINE_HZ
__attribute__((visibility("default")))
double lucent_native_adapter_producer_timeline_hz(void) {
    return MOCK_PRODUCER_TIMELINE_HZ;
}
#endif

__attribute__((visibility("default")))
double lucent_native_adapter_declared_video_hz(void) { return 60.0; }

__attribute__((visibility("default")))
bool lucent_native_adapter_set_paced_video_hz(double hz) {
    if (hz > 60.0) return false;
    mock_paced_video_hz = hz > 0.0 ? hz : 0.0;
    return true;
}

static void mock_describe(lucent_native_capabilities *out) {
    if (!out) return;
    out->abi_version = MOCK_ABI_VERSION;
    out->engine_id = "mock-wiiu";
    out->engine_version = "mock-0";
    out->has_quick_resume = false;      /* No reliable full-state serialize. */
    out->has_persistent_save = true;    /* Normal save flush is supported. */
    out->dual_screen = true;            /* Wii U TV + GamePad views. */
    out->required_firmware = 0;
    out->max_controllers = 1;           /* This mock drives only controller_index 0. */
}

static lucent_native_engine *mock_create(void) {
    return (lucent_native_engine *)calloc(1, sizeof(lucent_native_engine));
}

static bool mock_load(lucent_native_engine *engine,
                      const lucent_native_load_request *request,
                      char *error, size_t error_size) {
    if (!engine) return false;
    /* Fail closed when content is absent, mirroring a real firmware/content
     * validation gate. */
    if (!request || !request->content_path || !request->content_path[0]) {
        if (error && error_size) snprintf(error, error_size, "content path is required");
        return false;
    }
    free(engine->save_directory);
    engine->save_directory = request->save_directory && request->save_directory[0]
            ? strdup(request->save_directory) : NULL;
    engine->loaded = true;
    return true;
}

static bool mock_start(lucent_native_engine *engine,
                       const lucent_native_io *io,
                       char *error, size_t error_size) {
    if (!engine || !engine->loaded) return false;
    if (!io || io->kind != LUCENT_NATIVE_RENDER_VULKAN_WINDOW ||
            !io->primary_window) {
        if (error && error_size)
            snprintf(error, error_size, "a Vulkan primary window is required");
        return false;
    }
    engine->primary_window = io->primary_window;
    engine->lower_window = io->lower_window;
    engine->audio_sink = io->audio_sink;
    engine->audio_sink_ctx = io->audio_sink_ctx;
    engine->started = true;
    engine->paused = false;
    return true;
}

static void mock_present(void *window, uint32_t frame, bool lower) {
    if (!window) return;
    /* A deterministic, frame-dependent pattern the test can verify. The lower
     * (GamePad) view is the complement so the two surfaces are distinguishable. */
    uint32_t pattern = MOCK_PATTERN_BASE | (frame & 0xFFFFu);
    if (lower) pattern ^= 0x0000FFFFu;
    *(uint32_t *)window = pattern;
}

static bool mock_run_frame(lucent_native_engine *engine) {
    int16_t tone[MOCK_TONE_FRAMES * 2u];
    unsigned i;
    if (!engine || !engine->started) return false;
    if (engine->paused) return true;
    engine->frame_count++;
    mock_present(engine->primary_window, engine->frame_count, false);
    mock_present(engine->lower_window, engine->frame_count, true);
    for (i = 0; i < MOCK_TONE_FRAMES; i++) {
        tone[i * 2u] = (int16_t)(i * 17u);
        tone[i * 2u + 1u] = (int16_t)-((int16_t)(i * 17u));
    }
    if (engine->audio_sink)
        engine->audio_sink(engine->audio_sink_ctx, tone, MOCK_TONE_FRAMES);
    return true;
}

static void mock_set_control(lucent_native_engine *engine, uint32_t controller_index,
                             lucent_native_control control, float value) {
    (void)controller_index;
    (void)control;
    if (engine) engine->last_control_value = value;
}

static void mock_pause(lucent_native_engine *engine) {
    if (engine) engine->paused = true;
}

static void mock_resume(lucent_native_engine *engine) {
    if (engine) engine->paused = false;
}

static bool mock_flush_save(lucent_native_engine *engine) {
    char path[4096];
    FILE *file;
    if (!engine || !engine->loaded) return false;
    if (!engine->save_directory) return true; /* Nothing to persist to. */
    /* Only the directory is a runtime %s argument; MOCK_SAVE_FILE is
     * compile-time string-literal-concatenated into the format itself. A
     * short literal passed as its own separate %s argument here previously
     * tripped an ASan global-buffer-overflow false positive on this
     * toolchain's vsnprintf once an unrelated struct-layout change (adding
     * lucent_native_capabilities.max_controllers) shifted nearby global
     * string placement -- Apple's libc %s scan for short literals can read
     * in fixed-size chunks past the terminator, which ASan's redzone then
     * flags even though the extra bytes are never used. */
    if ((size_t)snprintf(path, sizeof(path), "%s/" MOCK_SAVE_FILE,
                         engine->save_directory) >= sizeof(path))
        return false;
    file = fopen(path, "wb");
    if (!file) return false;
    if (fwrite(MOCK_SENTINEL, 1, sizeof(MOCK_SENTINEL) - 1u, file) !=
            sizeof(MOCK_SENTINEL) - 1u) {
        fclose(file);
        return false;
    }
    return fclose(file) == 0;
}

/* has_quick_resume is false, so these fail closed exactly as a Wii U engine
 * without reliable full-state serialization must. */
static size_t mock_serialize_size(lucent_native_engine *engine) {
    (void)engine;
    return 0;
}

static size_t mock_serialize(lucent_native_engine *engine, void *out,
                             size_t capacity) {
    (void)engine; (void)out; (void)capacity;
    return 0;
}

static bool mock_unserialize(lucent_native_engine *engine, const void *data,
                             size_t size) {
    (void)engine; (void)data; (void)size;
    return false;
}

static bool mock_surface_recreated(lucent_native_engine *engine,
                                   const lucent_native_io *io) {
    if (!engine || !engine->started) return false;
    if (!io || !io->primary_window) return false;
    engine->primary_window = io->primary_window;
    engine->lower_window = io->lower_window;
    engine->audio_sink = io->audio_sink;
    engine->audio_sink_ctx = io->audio_sink_ctx;
    return true;
}

static void mock_stop(lucent_native_engine *engine) {
    if (!engine) return;
    engine->started = false;
    engine->primary_window = NULL;
    engine->lower_window = NULL;
    engine->audio_sink = NULL;
    engine->audio_sink_ctx = NULL;
}

static void mock_destroy(lucent_native_engine *engine) {
    if (!engine) return;
    free(engine->save_directory);
    free(engine);
}

static const lucent_native_adapter MOCK_ADAPTER = {
    MOCK_ABI_VERSION,
    mock_describe,
    mock_create,
    mock_load,
    mock_start,
    mock_run_frame,
    mock_set_control,
    mock_pause,
    mock_resume,
    mock_flush_save,
    mock_serialize_size,
    mock_serialize,
    mock_unserialize,
    mock_surface_recreated,
    mock_stop,
    mock_destroy,
};

const lucent_native_adapter *lucent_native_adapter_entry(void) {
    return &MOCK_ADAPTER;
}
