#include "../include/lucent_libretro_host.h"
#include "../include/libretro.h"

#include <dlfcn.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

#define CHECK(value, message) do { \
    if (!(value)) { fprintf(stderr, "%s: %s\n", message, error); return 1; } \
} while (0)

typedef unsigned (*fn_count)(void);
typedef bool (*fn_boolean)(void);

static unsigned backend_cookie;

static uintptr_t current_framebuffer(void *userdata) {
    return userdata == &backend_cookie ? (uintptr_t)0x1234u : 0;
}

static void mock_proc(void) {}

static lucent_retro_proc_address get_proc_address(void *userdata,
                                                  const char *symbol) {
    if (userdata != &backend_cookie || !symbol ||
            strcmp(symbol, "lucent_mock_symbol") != 0) return NULL;
    return mock_proc;
}

static void *symbol(void *library, const char *name) {
    void *result;
    dlerror();
    result = dlsym(library, name);
    return dlerror() ? NULL : result;
}

static int check_state_gate(lucent_retro_host *host, fn_count state_calls,
                            bool ready) {
    char error[512] = {0};
    uint32_t state = 0;
    void *allocated = (void *)(uintptr_t)1;
    size_t allocated_size = 99;
    unsigned before = state_calls();
    CHECK(lucent_retro_serialize_size(host) == (ready ? sizeof(state) : 0),
          "state-size readiness did not follow hardware context lifetime");
    CHECK(lucent_retro_serialize_alloc(host, &allocated, &allocated_size,
              error, sizeof(error)) == ready,
          "allocated state capture did not follow hardware context lifetime");
    if (ready) {
        CHECK(allocated && allocated_size == sizeof(state),
              "ready state allocation is invalid");
        free(allocated);
    } else {
        CHECK(!allocated && !allocated_size,
              "unavailable state capture retained caller output pointers");
    }
    CHECK(lucent_retro_serialize(host, &state, sizeof(state), error,
              sizeof(error)) == ready,
          "direct state capture did not follow hardware context lifetime");
    CHECK(lucent_retro_unserialize(host, &state, sizeof(state), error,
              sizeof(error)) == ready,
          "state restore did not follow hardware context lifetime");
    CHECK(state_calls() == before + (ready ? 6u : 0u),
          "unavailable state operation entered a core callback");
    return 0;
}

static int exercise_core(const char *core_path, const char *trusted_root,
                         const char *system_dir, const char *save_dir,
                         const char *game_path, bool vulkan) {
    char error[512] = {0};
    struct retro_hw_render_interface vulkan_interface = {
        RETRO_HW_RENDER_INTERFACE_VULKAN, 1
    };
    lucent_retro_hw_options options;
    lucent_retro_hw_info info;
    lucent_retro_host *host;
    void *library = dlopen(core_path, RTLD_NOW | RTLD_LOCAL);
    fn_count reset_count;
    fn_count destroy_count;
    fn_count state_calls;
    fn_boolean preferred_ok;
    fn_boolean interface_ok;
    fn_boolean shared_ok;
    fn_boolean backend_hooks_ok;
    fn_count game_reset_count;
    fn_count port_device_count;
    fn_count last_port;
    fn_count last_device;
    unsigned reset_before;
    unsigned destroy_before;
    CHECK(library, "could not open hardware mock core");
    reset_count = (fn_count)symbol(library, "lucent_hw_mock_reset_count");
    destroy_count = (fn_count)symbol(library, "lucent_hw_mock_destroy_count");
    state_calls = (fn_count)symbol(library, "lucent_hw_mock_state_call_count");
    game_reset_count = (fn_count)symbol(library,
                                        "lucent_hw_mock_game_reset_count");
    port_device_count = (fn_count)symbol(library,
                                         "lucent_hw_mock_port_device_count");
    last_port = (fn_count)symbol(library, "lucent_hw_mock_last_port");
    last_device = (fn_count)symbol(library, "lucent_hw_mock_last_device");
    preferred_ok = (fn_boolean)symbol(library, "lucent_hw_mock_preferred_ok");
    interface_ok = (fn_boolean)symbol(library, "lucent_hw_mock_interface_ok");
    shared_ok = (fn_boolean)symbol(library, "lucent_hw_mock_shared_ok");
    backend_hooks_ok = (fn_boolean)symbol(library,
                                           "lucent_hw_mock_backend_hooks_ok");
    CHECK(reset_count && destroy_count && state_calls && preferred_ok && interface_ok &&
          shared_ok && backend_hooks_ok && game_reset_count &&
          port_device_count && last_port && last_device,
          "hardware mock probes are missing");
    reset_before = reset_count();
    destroy_before = destroy_count();

    /* The production/JNI creation path supplies no backend and must reject a
     * hardware-only core without affecting software-host behavior. */
    host = lucent_retro_create(core_path, trusted_root, system_dir, save_dir,
                               error, sizeof(error));
    CHECK(host, "default host creation failed");
    CHECK(!lucent_retro_load_game(host, game_path, error, sizeof(error)),
          "hardware core loaded without an explicit backend");
    lucent_retro_destroy(host);

    memset(&options, 0, sizeof(options));
    options.struct_size = sizeof(options);
    options.api_version = LUCENT_RETRO_HW_OPTIONS_VERSION;
    options.context_capabilities = vulkan
            ? LUCENT_RETRO_HW_VULKAN : LUCENT_RETRO_HW_GLES3;
    options.preferred_context = options.context_capabilities;
    options.feature_capabilities = LUCENT_RETRO_HW_SHARED_CONTEXT;
    options.userdata = &backend_cookie;
    options.get_current_framebuffer = current_framebuffer;
    options.get_proc_address = get_proc_address;
    options.render_interface = vulkan ? &vulkan_interface : NULL;

    {
        lucent_retro_hw_options invalid_policy = options;
        /* One past the top of the valid bitmask (VI_ORIGIN | CONTENT_BOUNDS
         * = 3u): an unknown bit must still be rejected. */
        invalid_policy.source_timeline_policy =
                (LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_VI_ORIGIN |
                        LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS) + 1u;
        host = lucent_retro_create_with_options(
                core_path, trusted_root, system_dir, save_dir,
                &invalid_policy, error, sizeof(error));
        CHECK(!host, "unknown source-timeline policy was accepted");
    }

    if (!vulkan) {
        host = lucent_retro_create_with_options(
                core_path, trusted_root, system_dir, save_dir, &options,
                error, sizeof(error));
        CHECK(host, "limited GLES host creation failed");
        CHECK(!lucent_retro_load_game(host, game_path, error, sizeof(error)),
              "GLES depth/stencil/cache/debug request bypassed capability gate");
        lucent_retro_destroy(host);
        options.feature_capabilities |= LUCENT_RETRO_HW_DEPTH |
                LUCENT_RETRO_HW_STENCIL | LUCENT_RETRO_HW_CACHE_CONTEXT |
                LUCENT_RETRO_HW_DEBUG_CONTEXT;
    }

    host = lucent_retro_create_with_options(
            core_path, trusted_root, system_dir, save_dir, &options,
            error, sizeof(error));
    CHECK(host, "hardware host creation failed");
    CHECK(lucent_retro_load_game(host, game_path, error, sizeof(error)),
          "hardware core negotiation failed");
    CHECK(preferred_ok() && interface_ok() && shared_ok(),
          "preferred/shared/render-interface negotiation mismatch");
    CHECK(lucent_retro_get_hw_info(host, &info) && info.negotiated &&
          !info.context_ready && info.frame_sequence == 0,
          "negotiated hardware metadata mismatch");
    CHECK(info.context_type == (unsigned)(vulkan
                  ? RETRO_HW_CONTEXT_VULKAN : RETRO_HW_CONTEXT_OPENGLES3),
          "negotiated hardware context type mismatch");
    CHECK(!lucent_retro_run_frame(host, error, sizeof(error)),
          "hardware frame ran before Android context readiness");
    CHECK(!check_state_gate(host, state_calls, false),
          "state callbacks ran before initial hardware reset");
    CHECK(lucent_retro_hw_context_reset(host, error, sizeof(error)),
          "hardware context reset failed");
    CHECK(reset_count() == reset_before + 1 && backend_hooks_ok(),
          "core reset did not receive the configured backend");
    CHECK(!lucent_retro_hw_context_reset(host, error, sizeof(error)),
          "ready hardware context accepted a duplicate reset");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)),
          "hardware frame failed after context reset");
    CHECK(lucent_retro_get_hw_info(host, &info) && info.context_ready &&
          info.frame_sequence == 1,
          "hardware framebuffer sentinel was not recorded");
    CHECK(!check_state_gate(host, state_calls, true),
          "state callbacks failed with a ready hardware context");
    {
        /* Wii and GameCube run on this hardware path, so the Nunchuk port
         * device and the power cycle must both work here, not only on the
         * software host. */
        unsigned selections = port_device_count();
        unsigned game_resets = game_reset_count();
        CHECK(selections >= 1 && last_port() == 0 &&
              last_device() == RETRO_DEVICE_JOYPAD,
              "hardware load did not reset port 0 to a plain RetroPad");
        CHECK(lucent_retro_set_controller_port_device(host, 0, 0x301u,
                  error, sizeof(error)),
              "hardware host rejected the Wii Nunchuk port device");
        CHECK(port_device_count() == selections + 1 && last_port() == 0 &&
              last_device() == 0x301u,
              "hardware port device did not reach the core unchanged");
        CHECK(lucent_retro_reset(host, error, sizeof(error)),
              "hardware host rejected a reset");
        CHECK(game_reset_count() == game_resets + 1,
              "retro_reset was not invoked on the hardware host");
        CHECK(reset_count() == reset_before + 1,
              "game reset disturbed the hardware context lifecycle");
        CHECK(lucent_retro_run_frame(host, error, sizeof(error)),
              "hardware frame failed after a game reset");
    }
    CHECK(lucent_retro_hw_context_lost(host, error, sizeof(error)),
          "unexpected context-loss transition failed");
    CHECK(lucent_retro_get_hw_info(host, &info) && !info.context_ready,
          "lost context remained ready");
    CHECK(destroy_count() == destroy_before,
          "context loss invoked unsafe destroy callback");
    CHECK(!lucent_retro_run_frame(host, error, sizeof(error)),
          "hardware frame ran after unexpected context loss");
    CHECK(!check_state_gate(host, state_calls, false),
          "state callbacks ran after unexpected context loss");
    CHECK(lucent_retro_hw_context_reset(host, error, sizeof(error)),
          "hardware context reset after loss failed");
    CHECK(reset_count() == reset_before + 2,
          "core reset was not repeated after context loss");
    CHECK(lucent_retro_run_frame(host, error, sizeof(error)),
          "hardware frame failed after loss recovery");
    CHECK(!check_state_gate(host, state_calls, true),
          "state callbacks failed after loss recovery");
    CHECK(lucent_retro_hw_context_destroy(host, error, sizeof(error)),
          "hardware context destroy failed");
    CHECK(destroy_count() == destroy_before + 1,
          "core hardware destroy callback was not invoked");
    CHECK(lucent_retro_get_hw_info(host, &info) && !info.context_ready,
          "destroyed context remained ready");
    CHECK(!lucent_retro_run_frame(host, error, sizeof(error)),
          "hardware frame ran after context destruction");
    CHECK(!check_state_gate(host, state_calls, false),
          "state callbacks ran after orderly context destruction");
    CHECK(lucent_retro_hw_context_destroy(host, error, sizeof(error)),
          "duplicate hardware context destroy failed");
    CHECK(!check_state_gate(host, state_calls, false),
          "state callbacks ran after duplicate context destruction");
    CHECK(lucent_retro_hw_context_reset(host, error, sizeof(error)),
          "hardware wake/reset after orderly destruction failed");
    CHECK(!check_state_gate(host, state_calls, true),
          "state capture/restore failed after orderly detach and wake/reset");
    lucent_retro_destroy(host);
    dlclose(library);
    return 0;
}

int main(int argc, char **argv) {
    char error[512] = {0};
    lucent_retro_hw_options invalid;
    lucent_retro_host *host;
    if (argc != 7) {
        fprintf(stderr, "usage: hw_host_test GLES_CORE VULKAN_CORE TRUSTED_ROOT "
                        "SYSTEM_DIR SAVE_DIR GAME\n");
        return 2;
    }
    memset(&invalid, 0, sizeof(invalid));
    invalid.struct_size = sizeof(invalid);
    invalid.api_version = LUCENT_RETRO_HW_OPTIONS_VERSION;
    invalid.context_capabilities = LUCENT_RETRO_HW_GLES3;
    invalid.preferred_context = LUCENT_RETRO_HW_GLES3;
    host = lucent_retro_create_with_options(
            argv[1], argv[3], argv[4], argv[5], &invalid, error, sizeof(error));
    CHECK(!host, "incomplete GLES backend was accepted");
    CHECK(exercise_core(argv[1], argv[3], argv[4], argv[5], argv[6], false) == 0,
          "GLES hardware foundation failed");
    CHECK(exercise_core(argv[2], argv[3], argv[4], argv[5], argv[6], true) == 0,
          "Vulkan hardware foundation failed");
    puts("libretro GLES/Vulkan negotiation and lifecycle gates passed");
    return 0;
}
