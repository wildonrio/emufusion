#ifndef LUCENT_LIBRETRO_HOST_H
#define LUCENT_LIBRETRO_HOST_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct lucent_retro_host lucent_retro_host;

#define LUCENT_RETRO_HW_OPTIONS_VERSION 2u

enum lucent_retro_source_timeline_policy {
    LUCENT_RETRO_SOURCE_TIMELINE_DEFAULT = 0u,
    /* A patched Mupen core renders normally on every GLideN64 VI update but
     * exports whether this exact carrier run crossed a real VI-origin
     * boundary. The host accepts only marked callbacks and preserves skipped
     * libretro-run ordinals in the producer timestamp. This bit is only set
     * when the user has actually requested frame generation. */
    LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_VI_ORIGIN = 1u << 0,
    /* A frontend-FBO GLideN64 target clears its whole backing allocation to
     * a sentinel color and the core then writes only its actual VI rectangle
     * into it (F-Zero X and Ocarina of Time write different sub-rectangles
     * of the same allocation), leaving an unwanted sentinel-colored border.
     * This bit asks the GLES backend to probe the sentinel padding and crop
     * to the real content bounds. It is independent of the VI-origin
     * callback filter above -- that filter exists only to support frame
     * generation -- so this bit is set for every mupen64plus-next session
     * regardless of frame-generation mode. Both bits used to be folded into
     * a single value gated on frame generation, which meant the crop never
     * engaged for ordinary Frame Generation Off play, the overwhelming
     * majority of N64 sessions (2026-09-06 "blue edges" fix). */
    LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS = 1u << 1
};

enum lucent_retro_hw_context_capability {
    LUCENT_RETRO_HW_GLES2 = 1u << 0,
    LUCENT_RETRO_HW_GLES3 = 1u << 1,
    LUCENT_RETRO_HW_GLES_VERSION = 1u << 2,
    LUCENT_RETRO_HW_VULKAN = 1u << 3
};

enum lucent_retro_hw_feature {
    LUCENT_RETRO_HW_DEPTH = 1u << 0,
    LUCENT_RETRO_HW_STENCIL = 1u << 1,
    LUCENT_RETRO_HW_CACHE_CONTEXT = 1u << 2,
    LUCENT_RETRO_HW_DEBUG_CONTEXT = 1u << 3,
    LUCENT_RETRO_HW_SHARED_CONTEXT = 1u << 4
};

typedef void (*lucent_retro_proc_address)(void);
typedef uintptr_t (*lucent_retro_get_current_framebuffer)(void *userdata);
typedef lucent_retro_proc_address (*lucent_retro_get_proc_address)(
        void *userdata, const char *symbol);

/* Copied at host creation; callers retain ownership of userdata and the
 * optional render_interface. A non-NULL options block is still fail-closed
 * unless every capability needed by a core has an explicit backend hook. */
typedef struct lucent_retro_hw_options {
    size_t struct_size;
    unsigned api_version;
    uint32_t context_capabilities;
    uint32_t feature_capabilities;
    uint32_t preferred_context;
    unsigned max_gles_major;
    unsigned max_gles_minor;
    void *userdata;
    lucent_retro_get_current_framebuffer get_current_framebuffer;
    lucent_retro_get_proc_address get_proc_address;
    const void *render_interface;
    uint32_t source_timeline_policy;
} lucent_retro_hw_options;

typedef struct lucent_retro_hw_info {
    bool negotiated;
    bool context_ready;
    unsigned context_type;
    unsigned version_major;
    unsigned version_minor;
    bool depth;
    bool stencil;
    bool bottom_left_origin;
    bool cache_context;
    bool debug_context;
    uint64_t frame_sequence;
    unsigned frame_width;
    unsigned frame_height;
    uint32_t source_timeline_policy;
} lucent_retro_hw_info;

/* Optional final-render geometry, queried on the render thread after retro_run.
 * Seven words: version(1), x, y, width, height, target_width, target_height.
 * Coordinates are framebuffer pixels with bottom-left origin. This is the
 * core's final video rectangle, including black pixels inside that rectangle,
 * never a color-derived crop. False means retain the existing core contract. */
bool lucent_retro_get_hw_active_rect(lucent_retro_host *host, uint32_t rect[7]);

typedef struct lucent_retro_video_info {
    unsigned width;
    unsigned height;
    size_t pitch;
    unsigned pixel_format;
    size_t byte_size;
    uint64_t sequence;
} lucent_retro_video_info;

typedef struct lucent_retro_av_info {
    unsigned base_width;
    unsigned base_height;
    float aspect_ratio;
    double frames_per_second;
    double sample_rate;
    /* Render capacity may exceed both logical geometry and the display fit. */
    unsigned max_width;
    unsigned max_height;
} lucent_retro_av_info;

lucent_retro_host *lucent_retro_create(const char *core_path,
                                       const char *trusted_root,
                                       const char *system_directory,
                                       const char *save_directory,
                                       char *error, size_t error_size);
lucent_retro_host *lucent_retro_create_with_options(
        const char *core_path, const char *trusted_root,
        const char *system_directory, const char *save_directory,
        const lucent_retro_hw_options *hw_options,
        char *error, size_t error_size);
/* Creates a host with the same reviewed hardware contract plus the one
 * frontend-wide compatibility preference currently exposed by EmuFusion.
 * Existing callers deliberately retain the default-on profile through
 * lucent_retro_create[_with_options](). */
lucent_retro_host *lucent_retro_create_with_preferences(
        const char *core_path, const char *trusted_root,
        const char *system_directory, const char *save_directory,
        const lucent_retro_hw_options *hw_options,
        bool widescreen_enhancements_enabled,
        char *error, size_t error_size);
bool lucent_retro_load_game(lucent_retro_host *host, const char *game_path,
                            char *error, size_t error_size);
/**
 * Select the controller a core should emulate on a port. Loading a game resets
 * port 0 to a plain RetroPad; systems whose device is not a RetroPad must call
 * this afterwards. Dolphin, for example, only attaches a Wii Nunchuk when the
 * port device is RETRO_DEVICE_WIIMOTE_NC, and games that require the extension
 * (Super Mario Galaxy 2) accept no input until it is set.
 */
bool lucent_retro_set_controller_port_device(lucent_retro_host *host,
                                             unsigned port, unsigned device,
                                             char *error, size_t error_size);
/**
 * Power-cycles the loaded content in place (libretro retro_reset). Battery
 * save RAM stays in core memory across the call, exactly as a console reset
 * button leaves a cartridge untouched. Fails closed with no loaded game.
 */
bool lucent_retro_reset(lucent_retro_host *host, char *error,
                        size_t error_size);
/**
 * Clears every cheat the core is holding (libretro retro_cheat_reset).
 *
 * Cheats are core state, not content state: they survive a reset and must be
 * cleared explicitly, so EmuFusion re-applies the whole enabled set after this
 * rather than trying to toggle individual slots off. Fails closed with no
 * loaded game.
 */
bool lucent_retro_cheat_reset(lucent_retro_host *host, char *error,
                              size_t error_size);
/**
 * Installs one cheat in a core slot (libretro retro_cheat_set).
 *
 * `index` is the core's slot number; applying the enabled set in order from
 * zero is what keeps slots stable across toggles. `code` is the raw code
 * string in whatever format the core parses (Game Genie, raw address:value,
 * multi-line separated by '+'), passed through untouched because only the core
 * knows its own dialect. A null or empty code is rejected rather than handed
 * to the core.
 */
bool lucent_retro_cheat_set(lucent_retro_host *host, unsigned index,
                            bool enabled, const char *code, char *error,
                            size_t error_size);
bool lucent_retro_unload_game(lucent_retro_host *host,
                              char *error, size_t error_size);
bool lucent_retro_game_loaded(const lucent_retro_host *host);
bool lucent_retro_run_frame(lucent_retro_host *host, char *error,
                            size_t error_size);
/* Duration of PCM generated by the last completed retro_run, independent of
 * how much has been drained, muted, or evicted. Zero means no PCM this step.
 * Only render-driven hosts explicitly opting into audio pacing use this. */
uint64_t lucent_retro_last_run_audio_duration_ns(lucent_retro_host *host);
void lucent_retro_set_paused(lucent_retro_host *host, bool paused);
bool lucent_retro_set_joypad_button(lucent_retro_host *host, unsigned port,
                                    unsigned button, bool pressed);
bool lucent_retro_set_analog_axis(lucent_retro_host *host, unsigned port,
                                  unsigned index, unsigned id, int16_t value);
bool lucent_retro_set_pointer(lucent_retro_host *host, unsigned port,
                              int16_t x, int16_t y, bool pressed);
bool lucent_retro_latest_video_info(const lucent_retro_host *host,
                                    lucent_retro_video_info *info);
/* Copies the active byte_size bytes; a larger reusable destination is valid. */
bool lucent_retro_copy_video_frame(const lucent_retro_host *host, void *buffer,
                                   size_t size);
size_t lucent_retro_drain_audio(lucent_retro_host *host, int16_t *samples,
                                size_t max_frames);
bool lucent_retro_get_av_info(lucent_retro_host *host,
                              lucent_retro_av_info *info);
/* Paces a near-standard console clock at an exact panel divisor and applies
 * the identical ratio to PCM resampling. This changes neither the core's
 * declared AV contract nor the immutable AudioTrack sink rate. */
/* The clock the core is actually paced at: declared fps times the
 * synchronized/paced multiplier, or 0 before a game is loaded.  Source
 * timestamps must be stamped on this clock, never on the declared one. */
double lucent_retro_synchronized_video_hz(lucent_retro_host *host);

bool lucent_retro_set_synchronized_video_rate(
        lucent_retro_host *host, double declared_hz, double synchronized_hz,
        char *error, size_t error_size);
bool lucent_retro_get_hw_info(lucent_retro_host *host,
                              lucent_retro_hw_info *info);
/* Returns the core-owned context negotiation interface registered during
 * load_game. The pointer remains owned by the core and is only valid for the
 * lifetime of the loaded session. */
const void *lucent_retro_hw_context_negotiation_interface(
        lucent_retro_host *host);
/* Supplies Android's process JavaVM to a core that embeds native Android
 * helpers. Most libretro cores do not need it; the exact pinned Play! build
 * exports its Framework setter but is loaded with dlopen, so Android cannot
 * invoke an application-style JNI_OnLoad on its behalf. */
bool lucent_retro_supply_android_java_vm(lucent_retro_host *host, void *java_vm,
                                         char *error, size_t error_size);
/* Supplies the current frontend surface size to cores that expose Lucent's
 * optional direct-framebuffer sizing hook. Normal libretro cores ignore it. */
bool lucent_retro_supply_output_size(lucent_retro_host *host,
                                     unsigned width, unsigned height,
                                     char *error, size_t error_size);
/* Supplies a frontend-owned OpenGL framebuffer to an exact core adapter that
 * exports Lucent's optional lifecycle hook. Normal libretro cores ignore it. */
bool lucent_retro_supply_frontend_framebuffer(lucent_retro_host *host,
                                              unsigned framebuffer,
                                              char *error,
                                              size_t error_size);
bool lucent_retro_hw_context_reset(lucent_retro_host *host,
                                   char *error, size_t error_size);
bool lucent_retro_hw_context_destroy(lucent_retro_host *host,
                                     char *error, size_t error_size);
/* Marks an unexpectedly lost GPU context unavailable without invoking the
 * core's context_destroy callback against a dead EGL/Vulkan context. The next
 * successfully-created context must be followed by hw_context_reset(). */
bool lucent_retro_hw_context_lost(lucent_retro_host *host,
                                  char *error, size_t error_size);
size_t lucent_retro_serialize_size(lucent_retro_host *host);
/* Allocates and serializes a state while holding the host lock across the
 * core's size query and serialization call. Some otherwise usable cores lazily
 * change their advertised state size between independent calls; JNI callers
 * must use this atomic form instead of query/allocate/serialize. The caller
 * owns the returned buffer and must free it. */
bool lucent_retro_serialize_alloc(lucent_retro_host *host, void **buffer,
                                  size_t *size, char *error,
                                  size_t error_size);
bool lucent_retro_serialize(lucent_retro_host *host, void *buffer, size_t size,
                            char *error, size_t error_size);
bool lucent_retro_unserialize(lucent_retro_host *host, const void *buffer,
                              size_t size, char *error, size_t error_size);
const char *lucent_retro_library_name(const lucent_retro_host *host);
const char *lucent_retro_library_version(const lucent_retro_host *host);
unsigned lucent_retro_api_version(const lucent_retro_host *host);
size_t lucent_retro_save_ram_size(lucent_retro_host *host);
bool lucent_retro_read_save_ram(lucent_retro_host *host, void *buffer,
                                size_t size);
bool lucent_retro_write_save_ram(lucent_retro_host *host, const void *buffer,
                                 size_t size);
void lucent_retro_destroy(lucent_retro_host *host);

#endif
