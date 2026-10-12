/*
 * EmuFusion Phase 3 native-adapter ABI.
 *
 * Phase 3 systems (Wii U/Cemu, Switch/Yuzu-derived, PS3/RPCSX) have no libretro
 * core. Each is a standalone C++/Vulkan emulator engine. To emulate them INSIDE
 * EmuFusion (one app, one window, EmuFusion-owned surfaces/input/audio/save) each
 * engine is built as a shared library that exports exactly one symbol,
 * `emufusion_native_adapter_entry`, returning a const vtable of function pointers.
 * EmuFusion's host (emufusion_native_adapter_host.c) loads that library, drives it
 * through this vtable, and never opens the engine's own Activity or UI.
 *
 * The contract mirrors handover docs/HANDOVER-2026-08-07.md section 8.1:
 *   probe -> load -> start -> pause/resume -> input/audio/video
 *   flush persistent save -> serialize/restore if safe -> stop -> capabilities
 *
 * This header defines ONLY the boundary. It contains no engine implementation
 * and no third-party frontend code. An adapter that cannot honor a call must
 * fail closed (return false / a negative count), never fake success.
 */
#ifndef EMUFUSION_NATIVE_ADAPTER_H
#define EMUFUSION_NATIVE_ADAPTER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define EMUFUSION_NATIVE_ADAPTER_ABI_VERSION 2u

/* Optional emufusion_native_adapter_timing_capabilities_v1() export bits. These
 * extend discovery without changing the v1 vtable or requiring old adapters
 * to implement new entry points. Submission timing alone is not content ID. */
#define EMUFUSION_NATIVE_TIMING_BASE_CLOCK_CORRECTION 1u
#define EMUFUSION_NATIVE_TIMING_SUBMISSION_TIMESTAMPS 2u
#define EMUFUSION_NATIVE_TIMING_AUTHORITATIVE_SOURCE_TIMELINE 4u

/* Opaque per-session engine instance owned by the adapter. */
typedef struct emufusion_native_engine emufusion_native_engine;

/* How an adapter accepts its rendering target. EmuFusion owns the ANativeWindow
 * (from a Java Surface) and the audio sink; the adapter renders into the window
 * via its own Vulkan device and hands PCM back through the audio callback. */
typedef enum {
    EMUFUSION_NATIVE_RENDER_VULKAN_WINDOW = 1
} emufusion_native_render_kind;

/* Honest capability report. EmuFusion NEVER advertises a capability the engine
 * lacks: if reliable, deterministic full-state serialization is unavailable
 * (common for Wii U/Switch/PS3), has_quick_resume is false and EmuFusion exposes
 * only "flush normal saves and exit", not a fake Quick Resume snapshot. */
typedef struct {
    uint32_t abi_version;          /* must equal EMUFUSION_NATIVE_ADAPTER_ABI_VERSION */
    const char *engine_id;         /* e.g. "cemu" — matches the EmuFusion registry id */
    const char *engine_version;    /* pinned upstream version string */
    bool has_quick_resume;         /* true only if serialize/unserialize is safe */
    bool has_persistent_save;      /* normal game-save flush is supported */
    bool dual_screen;              /* Wii U GamePad / Switch handheld second view */
    uint32_t required_firmware;    /* count of user-supplied firmware/key blobs */
    uint32_t max_controllers;      /* how many set_control() controller_index
                                     * values 0..max_controllers-1 this engine
                                     * actually honors. Never advertised above
                                     * what the engine truly supports; an
                                     * adapter with no multi-controller support
                                     * reports exactly 1, never 0. */
} emufusion_native_capabilities;

/* User-supplied, hash-validated firmware/keys/content. EmuFusion validates and
 * passes read-only paths; the adapter must never download or bundle these. */
typedef struct {
    const char *system_directory;  /* validated firmware/keys/NAND root */
    const char *save_directory;    /* EmuFusion-owned per-title save root */
    const char *content_path;      /* the user's game file/dir */
} emufusion_native_load_request;

/* Audio: the adapter calls this with interleaved stereo s16 frames as they are
 * produced. EmuFusion owns the AudioTrack. Returns frames consumed. */
typedef size_t (*emufusion_native_audio_sink)(
        void *sink_ctx, const int16_t *frames, size_t frame_count);

/* Video present target for the primary (TV) and optional lower (GamePad) view.
 * EmuFusion supplies validated ANativeWindow handles; a null lower window means a
 * single-screen device (Wii U GamePad view is composited or omitted). */
typedef struct {
    emufusion_native_render_kind kind;
    void *primary_window;          /* ANativeWindow* — TV output, display 0 */
    void *lower_window;            /* ANativeWindow* or NULL — GamePad, display 4 */
    emufusion_native_audio_sink audio_sink;
    void *audio_sink_ctx;
} emufusion_native_io;

/* Canonical EmuFusion controls (superset; the adapter maps what its system uses).
 * Values are stable across ABI v1. */
typedef enum {
    EMUFUSION_PAD_A, EMUFUSION_PAD_B, EMUFUSION_PAD_X, EMUFUSION_PAD_Y,
    EMUFUSION_PAD_L, EMUFUSION_PAD_R, EMUFUSION_PAD_ZL, EMUFUSION_PAD_ZR,
    EMUFUSION_PAD_DPAD_UP, EMUFUSION_PAD_DPAD_DOWN, EMUFUSION_PAD_DPAD_LEFT, EMUFUSION_PAD_DPAD_RIGHT,
    EMUFUSION_PAD_START, EMUFUSION_PAD_SELECT, EMUFUSION_PAD_HOME,
    EMUFUSION_PAD_LSTICK_X, EMUFUSION_PAD_LSTICK_Y, EMUFUSION_PAD_RSTICK_X, EMUFUSION_PAD_RSTICK_Y,
    EMUFUSION_PAD_TOUCH_X, EMUFUSION_PAD_TOUCH_Y, EMUFUSION_PAD_TOUCH_PRESSED,
    /* Local Cemu presentation control, not guest input or a netplay control.
     * On a single-screen host: 0 = TV, 1 = GamePad. Existing ordinals and the
     * vtable are unchanged; only the updated, pinned Cemu adapter uses this. */
    EMUFUSION_PAD_SCREEN_VIEW,
    /* Stick clicks are independent digital buttons, not axis movement.
     * Append only: ordinals 0..22 remain compatible with existing adapters. */
    EMUFUSION_PAD_L3, EMUFUSION_PAD_R3
} emufusion_native_control;

/* The adapter vtable. Every function is required; a no-op is expressed by a
 * function that returns the documented failure value. All calls for one engine
 * instance are serialized by EmuFusion on a single render-owner thread, except
 * describe(), which must be pure and callable before create(). */
typedef struct {
    uint32_t abi_version;

    /* Pure, side-effect-free capability probe. Callable before create(). */
    void (*describe)(emufusion_native_capabilities *out);

    /* Allocate a session. Returns NULL on failure. */
    emufusion_native_engine *(*create)(void);

    /* Validate + load content and firmware. Returns false (fail closed) if the
     * content is unsupported or firmware/keys are missing/invalid. */
    bool (*load)(emufusion_native_engine *engine,
                 const emufusion_native_load_request *request,
                 char *error, size_t error_size);

    /* Bind EmuFusion-owned render/audio IO. Returns false if the engine cannot
     * initialize its Vulkan device against the supplied window(s). */
    bool (*start)(emufusion_native_engine *engine, const emufusion_native_io *io,
                  char *error, size_t error_size);

    /* Advance emulation and present one frame. Returns false on a fatal engine
     * error (EmuFusion then fails the session rather than hiding a black screen). */
    bool (*run_frame)(emufusion_native_engine *engine);

    /* controller_index selects which local/remote player this value belongs
     * to (0 is always the primary/local player). An adapter whose describe()
     * reports max_controllers == 1 must ignore any index other than 0 (fail
     * closed by treating it as a no-op, never by aliasing it onto player 0's
     * state). */
    void (*set_control)(emufusion_native_engine *engine, uint32_t controller_index,
                        emufusion_native_control control, float value);

    void (*pause)(emufusion_native_engine *engine);
    void (*resume)(emufusion_native_engine *engine);

    /* Flush normal game saves durably. Returns false if a save could not be
     * committed (EmuFusion must not report a clean exit in that case). */
    bool (*flush_save)(emufusion_native_engine *engine);

    /* Optional full-state serialize. If has_quick_resume is false these must
     * return 0 / false. serialize returns bytes written (0 = unavailable);
     * a NULL out buffer with capacity 0 returns the required size. */
    size_t (*serialize_size)(emufusion_native_engine *engine);
    size_t (*serialize)(emufusion_native_engine *engine, void *out, size_t capacity);
    bool (*unserialize)(emufusion_native_engine *engine, const void *data, size_t size);

    /* Recreate rendering after an Android surface loss. Returns false if the
     * engine cannot re-bind (EmuFusion then tears down safely). */
    bool (*surface_recreated)(emufusion_native_engine *engine,
                              const emufusion_native_io *io);

    /* Synchronous, bounded stop: the render owner has already quiesced. The
     * adapter must release its Vulkan device/surfaces before returning. */
    void (*stop)(emufusion_native_engine *engine);

    /* Free the session. The pointer is invalid afterward. */
    void (*destroy)(emufusion_native_engine *engine);
} emufusion_native_adapter;

/* The single exported entry point every adapter shared library must provide.
 * Returns a pointer to a static, immutable vtable, or NULL if the library is
 * incompatible. EmuFusion verifies vtable->abi_version before any other call. */
const emufusion_native_adapter *emufusion_native_adapter_entry(void);

typedef const emufusion_native_adapter *(*emufusion_native_adapter_entry_fn)(void);
#define EMUFUSION_NATIVE_ADAPTER_ENTRY_SYMBOL "emufusion_native_adapter_entry"

#ifdef __cplusplus
}
#endif

#endif /* EMUFUSION_NATIVE_ADAPTER_H */
