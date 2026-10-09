#include "include/lucent_android_gles_backend.h"
#include "include/libretro.h"
#include "include/lucent_presentation_resume.h"

#if !defined(__ANDROID__)
#error "lucent_android_gles_backend.c is Android-only"
#endif

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <android/log.h>
#include <android/native_window.h>
#include <dlfcn.h>
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct lucent_gles_resume_frame {
    EGLuint64KHR id;
    bool pending;
} lucent_gles_resume_frame;

typedef struct lucent_gles_resume_warmup {
    bool required;
    bool collecting;
    unsigned submitted;
    int64_t started_ns;
    EGLnsecsANDROID interval_ns;
    PFNEGLGETNEXTFRAMEIDANDROIDPROC next_id;
    PFNEGLGETFRAMETIMESTAMPSANDROIDPROC timestamps;
    lucent_gles_resume_frame frames[16];
    lucent_presentation_resume cadence;
} lucent_gles_resume_warmup;

struct lucent_android_gles_backend {
    EGLDisplay display;
    EGLConfig config;
    EGLContext context;
    EGLSurface surface;
    ANativeWindow *window;
    lucent_retro_host *host;
    pthread_t render_thread;
    bool render_thread_set;
    unsigned max_major;
    unsigned max_minor;
    uint32_t context_capabilities;
    uint32_t feature_capabilities;
    unsigned active_major;
    unsigned active_minor;
    unsigned depth_bits;
    unsigned stencil_bits;
    GLuint framebuffer;
    GLuint color_texture;
    GLuint depth_stencil_buffer;
    unsigned framebuffer_width;
    unsigned framebuffer_height;
    unsigned content_width;
    unsigned content_height;
    int destination_x;
    int destination_y;
    unsigned destination_width;
    unsigned destination_height;
    uint32_t last_active_rect[7];
    unsigned configured_presentation_path;
    unsigned presentation_path;
    float presentation_aspect;
    uint64_t presented_sequence;
    bool has_presented_game_frame;
    lucent_gles_resume_warmup resume_warmup;
    bool fg_timestamp_enabled;
    bool direct_timestamp_bypass_logged;
    /* SurfaceTexture.getTimestamp() is only a source-timeline timestamp when
     * the EGL producer explicitly supplies EGL_ANDROID_presentation_time.
     * Anchor the core's immutable hardware-frame ordinal to a monotonic epoch,
     * then derive every later timestamp from retro_get_system_av_info. Android
     * callback/swap jitter must never become temporal interpolation phase. */
    EGLBoolean (*presentation_time_android)(
            EGLDisplay, EGLSurface, EGLnsecsANDROID);
    uint64_t timestamp_base_sequence;
    EGLnsecsANDROID timestamp_base_ns;
    EGLnsecsANDROID timestamp_last_ns;
    double timestamp_source_hz;
    bool timestamp_timeline_ready;
    bool timestamp_failure_logged;
    unsigned framebuffer_callback_diagnostics;
    unsigned frame_pixel_diagnostics;
    unsigned framebuffer_blit_diagnostics;
    bool presentation_geometry_logged;
    unsigned content_bounds_probe_count;
    unsigned content_bounds_stable_count;
    bool content_bounds_valid;
    unsigned content_source_x;
    unsigned content_source_y;
    unsigned content_source_width;
    unsigned content_source_height;
};

enum {
    LUCENT_GLES_PRESENTATION_UNKNOWN = LUCENT_ANDROID_GLES_PRESENT_AUTO,
    LUCENT_GLES_PRESENTATION_FRONTEND_FBO =
            LUCENT_ANDROID_GLES_PRESENT_FRONTEND_FBO,
    LUCENT_GLES_PRESENTATION_DIRECT_WINDOW =
            LUCENT_ANDROID_GLES_PRESENT_DIRECT_WINDOW
};

static const GLubyte framebuffer_sentinel[4] = {23u, 179u, 241u, 255u};

static bool is_framebuffer_sentinel(const GLubyte *pixel) {
    return pixel && memcmp(pixel, framebuffer_sentinel,
                           sizeof(framebuffer_sentinel)) == 0;
}

static void set_error(char *buffer, size_t size, const char *format, ...) {
    va_list arguments;
    if (!buffer || !size) return;
    va_start(arguments, format);
    vsnprintf(buffer, size, format, arguments);
    va_end(arguments);
}

static bool on_render_thread(const lucent_android_gles_backend *backend) {
    return backend && backend->render_thread_set &&
            pthread_equal(backend->render_thread, pthread_self());
}

static bool claim_render_thread(lucent_android_gles_backend *backend,
                                char *error, size_t error_size) {
    if (!backend) {
        set_error(error, error_size, "GLES backend is required");
        return false;
    }
    if (!backend->render_thread_set) {
        backend->render_thread = pthread_self();
        backend->render_thread_set = true;
        return true;
    }
    if (!on_render_thread(backend)) {
        set_error(error, error_size, "GLES lifecycle must stay on its render thread");
        return false;
    }
    return true;
}

bool lucent_android_gles_set_fg_timestamp(
        lucent_android_gles_backend *backend, bool enabled,
        char *error, size_t error_size) {
    if (!claim_render_thread(backend, error, error_size)) return false;
    backend->fg_timestamp_enabled = enabled;
    /* Every binding gets a fresh epoch, even if its mode is unchanged. */
    backend->timestamp_timeline_ready = false;
    backend->timestamp_last_ns = 0;
    backend->timestamp_failure_logged = false;
    backend->direct_timestamp_bypass_logged = false;
    return true;
}

static bool choose_config(lucent_android_gles_backend *backend,
                          unsigned major, unsigned depth, unsigned stencil,
                          EGLConfig *config, char *error, size_t error_size) {
    EGLint count = 0;
    EGLint renderable = major >= 3 ? EGL_OPENGL_ES3_BIT_KHR : EGL_OPENGL_ES2_BIT;
    const EGLint attributes[] = {
        EGL_SURFACE_TYPE, EGL_WINDOW_BIT | EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, renderable,
        EGL_RED_SIZE, 8,
        EGL_GREEN_SIZE, 8,
        EGL_BLUE_SIZE, 8,
        EGL_ALPHA_SIZE, 8,
        EGL_DEPTH_SIZE, (EGLint)depth,
        EGL_STENCIL_SIZE, (EGLint)stencil,
        EGL_NONE
    };
    if (!eglChooseConfig(backend->display, attributes, config, 1, &count) || count != 1) {
        set_error(error, error_size,
                  "no Android EGL config for GLES %u depth=%u stencil=%u (0x%x)",
                  major, depth, stencil, eglGetError());
        return false;
    }
    return true;
}

static EGLContext create_context(EGLDisplay display, EGLConfig config,
                                 unsigned major, unsigned minor) {
    if (minor) {
        const EGLint versioned[] = {
            EGL_CONTEXT_MAJOR_VERSION_KHR, (EGLint)major,
            EGL_CONTEXT_MINOR_VERSION_KHR, (EGLint)minor,
            EGL_NONE
        };
        return eglCreateContext(display, config, EGL_NO_CONTEXT, versioned);
    }
    {
        const EGLint basic[] = {
            EGL_CONTEXT_CLIENT_VERSION, (EGLint)major,
            EGL_NONE
        };
        return eglCreateContext(display, config, EGL_NO_CONTEXT, basic);
    }
}

static void parse_gles_version(const char *version, unsigned fallback_major,
                               unsigned *major, unsigned *minor) {
    unsigned parsed_major = 0;
    unsigned parsed_minor = 0;
    if (version) {
        const char *digits = version;
        while (*digits && (*digits < '0' || *digits > '9')) digits++;
        if (sscanf(digits, "%u.%u", &parsed_major, &parsed_minor) != 2)
            parsed_major = 0;
    }
    *major = parsed_major ? parsed_major : fallback_major;
    *minor = parsed_major ? parsed_minor : 0;
}

static bool probe_context(lucent_android_gles_backend *backend,
                          unsigned requested_major, unsigned requested_minor,
                          unsigned *actual_major, unsigned *actual_minor) {
    EGLConfig config = NULL;
    EGLContext context = EGL_NO_CONTEXT;
    EGLSurface surface = EGL_NO_SURFACE;
    const EGLint pbuffer[] = { EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE };
    const GLubyte *version;
    if (!choose_config(backend, requested_major, 0, 0, &config, NULL, 0))
        return false;
    context = create_context(backend->display, config, requested_major,
                             requested_minor);
    if (context == EGL_NO_CONTEXT) return false;
    surface = eglCreatePbufferSurface(backend->display, config, pbuffer);
    if (surface == EGL_NO_SURFACE ||
            !eglMakeCurrent(backend->display, surface, surface, context)) goto fail;
    version = glGetString(GL_VERSION);
    parse_gles_version((const char *)version, requested_major,
                       actual_major, actual_minor);
    eglMakeCurrent(backend->display, EGL_NO_SURFACE, EGL_NO_SURFACE,
                   EGL_NO_CONTEXT);
    eglDestroySurface(backend->display, surface);
    eglDestroyContext(backend->display, context);
    return true;
fail:
    eglMakeCurrent(backend->display, EGL_NO_SURFACE, EGL_NO_SURFACE,
                   EGL_NO_CONTEXT);
    if (surface != EGL_NO_SURFACE) eglDestroySurface(backend->display, surface);
    eglDestroyContext(backend->display, context);
    return false;
}

static uintptr_t current_framebuffer(void *userdata) {
    lucent_android_gles_backend *backend =
            (lucent_android_gles_backend *)userdata;
    uintptr_t result;
    /* Some valid hardware cores (notably PPSSPP) ask for the frontend FBO
     * while configuring a deferred render target, before that worker has made
     * the frontend EGL context current.  A framebuffer name is context-owned
     * data rather than an operation; returning the already-created name is
     * safe here.  Every operation that creates, reads, blits, or destroys that
     * FBO remains render-thread/current-context guarded.
     */
    if (!backend) return 0;
    result = (!backend->host || backend->surface == EGL_NO_SURFACE ||
            backend->configured_presentation_path ==
                    LUCENT_GLES_PRESENTATION_DIRECT_WINDOW) ?
            0 : (uintptr_t)backend->framebuffer;
    if (backend->framebuffer_callback_diagnostics < 4u) {
        __android_log_print(ANDROID_LOG_INFO, "LucentGlesBackend",
                "frontend framebuffer callback value=%lu policy=%u "
                "surface=%s renderThread=%s",
                (unsigned long)result,
                backend->configured_presentation_path,
                backend->surface == EGL_NO_SURFACE ? "none" : "ready",
                on_render_thread(backend) ? "yes" : "no");
        backend->framebuffer_callback_diagnostics++;
    }
    return result;
}

static void abandon_framebuffer(lucent_android_gles_backend *backend) {
    if (!backend) return;
    backend->framebuffer = 0;
    backend->color_texture = 0;
    backend->depth_stencil_buffer = 0;
    backend->framebuffer_width = 0;
    backend->framebuffer_height = 0;
    backend->content_width = 0;
    backend->content_height = 0;
    backend->destination_x = 0;
    backend->destination_y = 0;
    backend->destination_width = 0;
    backend->destination_height = 0;
    memset(backend->last_active_rect, 0, sizeof(backend->last_active_rect));
    backend->presentation_path = backend->configured_presentation_path;
    backend->presentation_geometry_logged = false;
    backend->content_bounds_probe_count = 0;
    backend->content_bounds_stable_count = 0;
    backend->content_bounds_valid = false;
    backend->content_source_x = 0;
    backend->content_source_y = 0;
    backend->content_source_width = 0;
    backend->content_source_height = 0;
}

static void delete_framebuffer(lucent_android_gles_backend *backend) {
    if (!backend) return;
    if (backend->depth_stencil_buffer)
        glDeleteRenderbuffers(1, &backend->depth_stencil_buffer);
    if (backend->color_texture)
        glDeleteTextures(1, &backend->color_texture);
    if (backend->framebuffer)
        glDeleteFramebuffers(1, &backend->framebuffer);
    abandon_framebuffer(backend);
}

static unsigned align_up_16(unsigned value) {
    return value > UINT32_MAX - 15u ? value : (value + 15u) & ~15u;
}

static bool plausible_aspect(float aspect) {
    return isfinite(aspect) && aspect > 0.1f && aspect < 10.0f;
}

/* Hardware libretro cores render into a frontend-owned framebuffer.  Rendering
 * directly into Android's window framebuffer leaves a native-size image in
 * one corner because the core is not responsible for presentation scaling.
 * Keep render capacity separate from the centered Android destination. */
static bool create_framebuffer(lucent_android_gles_backend *backend,
                               lucent_retro_host *host,
                               unsigned window_width, unsigned window_height,
                               char *error, size_t error_size) {
    lucent_retro_av_info av;
    lucent_retro_hw_info hw;
    float aspect;
    GLenum attachment;
    GLenum format;
    if (!backend || !host) {
        set_error(error, error_size, "GLES framebuffer scaling requires a live host");
        return false;
    }
    if (!window_width || !window_height) {
        set_error(error, error_size, "Android window reported an empty surface");
        return false;
    }
    if (backend->active_major < 3) {
        set_error(error, error_size,
                  "GLES framebuffer scaling requires GLES3 (active %u.%u)",
                  backend->active_major, backend->active_minor);
        return false;
    }
    memset(&av, 0, sizeof(av));
    if (!lucent_retro_get_av_info(host, &av)) {
        set_error(error, error_size, "core AV geometry is unavailable");
        return false;
    }
    aspect = plausible_aspect(backend->presentation_aspect) ?
            backend->presentation_aspect :
            (plausible_aspect(av.aspect_ratio) ? av.aspect_ratio :
             (av.base_height ?
                    (float)av.base_width / (float)av.base_height : 1.0f));
    backend->content_height = window_height;
    backend->content_width = (unsigned)(window_height * aspect + 0.5f);
    if (backend->content_width > window_width) {
        backend->content_width = window_width;
        backend->content_height =
                (unsigned)((float)window_width / aspect + 0.5f);
    }
    if (!backend->content_width) backend->content_width = 1;
    if (!backend->content_height) backend->content_height = 1;
    backend->destination_width = backend->content_width;
    backend->destination_height = backend->content_height;
    backend->destination_x = ((int)window_width -
            (int)backend->destination_width) / 2;
    backend->destination_y = ((int)window_height -
            (int)backend->destination_height) / 2;
    backend->framebuffer_width = backend->content_width;
    backend->framebuffer_height = backend->content_height;
    /* GLideN64 reports its selected render target as base/max AV geometry.
     * Its final VI copy does not expand to the display-sized allocation.
     * Inflating a640x480 target to a960x720 fit makes the bounded sentinel
     * probe reject valid game pixels until its600-frame timeout, then expose
     * the untouched border. Allocate the declared core capacity instead;
     * display scaling still uses the independent destination above. Other
     * cores retain their existing window-sized minimum contracts. */
    memset(&hw, 0, sizeof(hw));
    if (lucent_retro_get_hw_info(host, &hw) &&
            (hw.source_timeline_policy &
             LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS) &&
            (av.base_width || av.max_width) &&
            (av.base_height || av.max_height)) {
        backend->framebuffer_width = 0;
        backend->framebuffer_height = 0;
    }
    /* The display fit is not the core's render extent. PPSSPP's 4x output is
     * 1920x1088 even when its aspect-correct destination is 1906x1080, and
     * remains that size on a smaller Android surface. Allocate at least the
     * declared capacity before context_reset; otherwise the GPU clips the
     * right/bottom edges before our final proportional blit can see them.
     * Flycast keeps base geometry at 640x480 while max geometry reserves its
     * higher internal resolution (including rotation). That square capacity
     * is not the source or destination rectangle: presentation still uses the
     * submitted image/viewport and the core's display aspect ratio.
     * Do not infer allocation from a post-run scratch GL viewport. */
    if (av.base_width > backend->framebuffer_width)
        backend->framebuffer_width = av.base_width;
    if (av.base_height > backend->framebuffer_height)
        backend->framebuffer_height = av.base_height;
    if (av.max_width > backend->framebuffer_width)
        backend->framebuffer_width = av.max_width;
    if (av.max_height > backend->framebuffer_height)
        backend->framebuffer_height = av.max_height;
    backend->framebuffer_height = align_up_16(backend->framebuffer_height);

    glGenTextures(1, &backend->color_texture);
    glBindTexture(GL_TEXTURE_2D, backend->color_texture);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8,
                 (GLsizei)backend->framebuffer_width,
                 (GLsizei)backend->framebuffer_height, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glGenFramebuffers(1, &backend->framebuffer);
    glBindFramebuffer(GL_FRAMEBUFFER, backend->framebuffer);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, backend->color_texture, 0);
    if (backend->depth_bits || backend->stencil_bits) {
        glGenRenderbuffers(1, &backend->depth_stencil_buffer);
        glBindRenderbuffer(GL_RENDERBUFFER, backend->depth_stencil_buffer);
        if (backend->depth_bits && backend->stencil_bits) {
            format = GL_DEPTH24_STENCIL8;
            attachment = GL_DEPTH_STENCIL_ATTACHMENT;
        } else if (backend->depth_bits) {
            format = GL_DEPTH_COMPONENT16;
            attachment = GL_DEPTH_ATTACHMENT;
        } else {
            format = GL_STENCIL_INDEX8;
            attachment = GL_STENCIL_ATTACHMENT;
        }
        glRenderbufferStorage(GL_RENDERBUFFER, format,
                              (GLsizei)backend->framebuffer_width,
                              (GLsizei)backend->framebuffer_height);
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, attachment,
                                  GL_RENDERBUFFER,
                                  backend->depth_stencil_buffer);
    }
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
        set_error(error, error_size, "cannot create complete GLES core framebuffer");
        delete_framebuffer(backend);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        return false;
    }
    /* A hardware core may either honor get_current_framebuffer() or render
     * directly into Android framebuffer zero. Seed the private FBO with an
     * unlikely marker so the first submitted frame can distinguish those two
     * valid libretro behaviors without a per-engine name check. */
    glViewport(0, 0, (GLsizei)backend->framebuffer_width,
               (GLsizei)backend->framebuffer_height);
    glClearColor((GLfloat)framebuffer_sentinel[0] / 255.0f,
                 (GLfloat)framebuffer_sentinel[1] / 255.0f,
                 (GLfloat)framebuffer_sentinel[2] / 255.0f,
                 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glBindTexture(GL_TEXTURE_2D, 0);
    glBindRenderbuffer(GL_RENDERBUFFER, 0);
    return true;
}

static bool frontend_framebuffer_was_rendered(
        const lucent_android_gles_backend *backend) {
    static const unsigned sample_numerators[][2] = {
        {1, 1}, {1, 2}, {1, 3}, {2, 1}, {2, 2},
        {2, 3}, {3, 1}, {3, 2}, {3, 3}
    };
    GLubyte pixel[4];
    size_t i;
    if (!backend || !backend->framebuffer_width ||
            !backend->content_height) return false;
    for (i = 0; i < sizeof(sample_numerators) / sizeof(sample_numerators[0]); i++) {
        GLint x = (GLint)((uint64_t)backend->framebuffer_width *
                sample_numerators[i][0] / 4u);
        GLint y = (GLint)((uint64_t)backend->content_height *
                sample_numerators[i][1] / 4u);
        memset(pixel, 0, sizeof(pixel));
        glReadPixels(x, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
        if (memcmp(pixel, framebuffer_sentinel, sizeof(pixel)) != 0) return true;
    }
    return false;
}

/* GLideN64 renders each title's complete VI image into a title-sized region
 * of the frontend FBO. The surrounding allocation is not game video: it keeps
 * the exact sentinel written by create_framebuffer(). Ocarina and F-Zero use
 * different VI regions, so treating the entire allocation as source both
 * exposes the cyan sentinel and makes their apparent image sizes differ.
 *
 * Probe three horizontal and three vertical lines during startup. A core's
 * own black borders count as content because they are not the sentinel; only
 * pixels the core never touched are excluded. The bounded startup probe is
 * then frozen, avoiding readback stalls during gameplay. Returns -1 for a
 * completely untouched frame, 0 when content exists but no safe large bounds
 * can yet be established, and 1 for usable complete bounds. */
static int probe_frontend_content_bounds(
        lucent_android_gles_backend *backend,
        unsigned *source_x, unsigned *source_y,
        unsigned *source_width, unsigned *source_height) {
    GLubyte *rows;
    GLubyte *columns;
    unsigned left;
    unsigned right;
    unsigned bottom;
    unsigned top;
    bool row_content = false;
    bool column_content = false;
    unsigned sample;
    unsigned probe_width;
    unsigned probe_height;
    if (!backend || !source_x || !source_y || !source_width || !source_height ||
            !backend->framebuffer_width || !backend->framebuffer_height) return 0;
    /* content_width/height describe the final display fit, not the source.
     * A 720p phone can receive a 1440x1080 VI target: probing only 960x720
     * falsely treats the readback's edge as the game's edge and permanently
     * crops the right/top pixels. Inspect the actual allocation, including
     * its sentinel padding, independently of the window dimensions. */
    probe_width = backend->framebuffer_width;
    probe_height = backend->framebuffer_height;
    rows = (GLubyte *)calloc((size_t)probe_width * 3u, 4u);
    columns = (GLubyte *)calloc((size_t)probe_height * 3u, 4u);
    if (!rows || !columns) {
        free(rows);
        free(columns);
        return 0;
    }
    for (sample = 0; sample < 3u; ++sample) {
        unsigned numerator = sample + 1u;
        glReadPixels(0,
                     (GLint)((uint64_t)probe_height * numerator / 4u),
                     (GLsizei)probe_width, 1,
                     GL_RGBA, GL_UNSIGNED_BYTE,
                     rows + (size_t)sample * probe_width * 4u);
        glReadPixels((GLint)((uint64_t)probe_width * numerator / 4u), 0,
                     1, (GLsizei)probe_height,
                     GL_RGBA, GL_UNSIGNED_BYTE,
                     columns + (size_t)sample * probe_height * 4u);
    }
    /* A sample line entirely inside the sentinel band (its own height/width
     * offset falls outside the title's active rectangle -- physically
     * observed on Banjo-Kazooie, whose VI target sits well below and right
     * of this allocation's origin, so the 1/4-height row is 100% sentinel)
     * scans to a degenerate zero-width result: sample_left reaches
     * probe_width and sample_right collapses to meet it. Folding that
     * degenerate row into the max(left)/min(right) combination as if it
     * were real evidence zeroes out the whole axis even though the other
     * two sample rows saw the actual picture, which is exactly the "still
     * has blue/sentinel edges" symptom. Only rows/columns that actually
     * found content contribute to the combined bound; an axis where every
     * sample degenerated still correctly reports no content below. */
    right = probe_width;
    left = 0;
    {
        bool any_row_content = false;
        for (sample = 0; sample < 3u; ++sample) {
            GLubyte *row = rows + (size_t)sample * probe_width * 4u;
            unsigned sample_left = 0u;
            unsigned sample_right = probe_width;
            while (sample_left < probe_width &&
                    is_framebuffer_sentinel(row + (size_t)sample_left * 4u))
                ++sample_left;
            while (sample_right > sample_left &&
                    is_framebuffer_sentinel(
                            row + (size_t)(sample_right - 1u) * 4u))
                --sample_right;
            if (sample_right <= sample_left) continue;
            if (!any_row_content) { left = 0u; right = probe_width; }
            any_row_content = true;
            if (sample_left > left) left = sample_left;
            if (sample_right < right) right = sample_right;
        }
        if (!any_row_content) { left = 0u; right = 0u; }
    }
    bottom = 0;
    top = probe_height;
    {
        bool any_column_content = false;
        for (sample = 0; sample < 3u; ++sample) {
            GLubyte *column = columns +
                    (size_t)sample * probe_height * 4u;
            unsigned sample_bottom = 0;
            unsigned sample_top = probe_height;
            while (sample_bottom < probe_height &&
                    is_framebuffer_sentinel(
                            column + (size_t)sample_bottom * 4u)) ++sample_bottom;
            while (sample_top > sample_bottom &&
                    is_framebuffer_sentinel(
                            column + (size_t)(sample_top - 1u) * 4u)) --sample_top;
            if (sample_top <= sample_bottom) continue;
            if (!any_column_content) {
                bottom = 0u;
                top = probe_height;
            }
            any_column_content = true;
            if (sample_bottom > bottom) bottom = sample_bottom;
            if (sample_top < top) top = sample_top;
        }
        if (!any_column_content) { bottom = 0u; top = 0u; }
    }
    row_content = right > left;
    column_content = top > bottom;
    if (!row_content && !column_content) {
        free(rows);
        free(columns);
        return -1;
    }
    if (!row_content || !column_content ||
            (right - left) * 3u < probe_width * 2u ||
            (top - bottom) * 3u < probe_height * 2u) {
        free(rows);
        free(columns);
        return 0;
    }
    /* Only untouched allocation is padding. Black pixels are part of the
     * submitted image: a cutscene may later replace them with gameplay/HUD.
     * Freezing a black-trimmed startup rectangle cropped Ocarina after its
     * introduction. Preserve these pixels regardless of symmetry or color. */
    free(rows);
    free(columns);
    *source_x = left;
    *source_y = bottom;
    *source_width = right - left;
    *source_height = top - bottom;
    return 1;
}

/* Bounded qualification telemetry.  This samples what the frontend is about
 * to present; it does not alter the screenshot oracle or infer success from a
 * core callback.  Sampling at startup and again near three and six seconds
 * catches cores whose first video callback arrives after initial boot work,
 * while remaining bounded to three records per surface. */
static void log_framebuffer_pixels(lucent_android_gles_backend *backend,
                                   uint64_t frame_sequence) {
    GLubyte window_pixel[4] = {0, 0, 0, 0};
    GLubyte frontend_pixel[4] = {0, 0, 0, 0};
    GLint window_x;
    GLint window_y;
    GLint frontend_x;
    GLint frontend_y;
    if (!backend || backend->frame_pixel_diagnostics >= 3u || !backend->window)
        return;
    if ((backend->frame_pixel_diagnostics == 1u && frame_sequence < 180u) ||
            (backend->frame_pixel_diagnostics == 2u && frame_sequence < 360u))
        return;
    window_x = ANativeWindow_getWidth(backend->window) / 2;
    window_y = ANativeWindow_getHeight(backend->window) / 2;
    glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
    glReadPixels(window_x, window_y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE,
                 window_pixel);
    if (backend->framebuffer && backend->framebuffer_width &&
            backend->content_height) {
        frontend_x = (GLint)(backend->framebuffer_width / 2u);
        frontend_y = (GLint)(backend->content_height / 2u);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, backend->framebuffer);
        glReadPixels(frontend_x, frontend_y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE,
                     frontend_pixel);
    }
    __android_log_print(ANDROID_LOG_INFO, "LucentGlesBackend",
            "pre-swap pixels sequence=%llu policy=%u path=%u window=%u,%u,%u,%u "
            "frontend=%u,%u,%u,%u fbo=%u",
            (unsigned long long)frame_sequence,
            backend->configured_presentation_path, backend->presentation_path,
            window_pixel[0], window_pixel[1], window_pixel[2], window_pixel[3],
            frontend_pixel[0], frontend_pixel[1], frontend_pixel[2],
            frontend_pixel[3], backend->framebuffer);
    backend->frame_pixel_diagnostics++;
}

/* TextureView is an Android-composited layer even when Java marks it opaque.
 * PPSSPP legitimately writes RGB with alpha zero, which a dedicated opaque
 * Activity surface displays correctly but SurfaceTexture composition treats
 * as transparent.  Gameplay owns this complete layer, so normalize only the
 * destination alpha channel after presentation while preserving RGB and the
 * core's relevant GL state. */
static void force_opaque_surface_alpha(void) {
    GLfloat prior_clear[4];
    GLboolean prior_mask[4];
    GLboolean scissor_enabled;
    glGetFloatv(GL_COLOR_CLEAR_VALUE, prior_clear);
    glGetBooleanv(GL_COLOR_WRITEMASK, prior_mask);
    scissor_enabled = glIsEnabled(GL_SCISSOR_TEST);
    if (scissor_enabled) glDisable(GL_SCISSOR_TEST);
    glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_TRUE);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glClearColor(prior_clear[0], prior_clear[1], prior_clear[2], prior_clear[3]);
    glColorMask(prior_mask[0], prior_mask[1], prior_mask[2], prior_mask[3]);
    if (scissor_enabled) glEnable(GL_SCISSOR_TEST);
}

static lucent_retro_proc_address get_proc_address(void *userdata,
                                                  const char *symbol) {
    lucent_android_gles_backend *backend =
            (lucent_android_gles_backend *)userdata;
    __eglMustCastToProperFunctionPointerType address;
    void *fallback;
    lucent_retro_proc_address result = NULL;
    if (!backend || !backend->host || !on_render_thread(backend) ||
            backend->surface == EGL_NO_SURFACE || !symbol) return NULL;
    address = eglGetProcAddress(symbol);
    if (address) memcpy(&result, &address, sizeof(result));
    if (result) return result;
    fallback = dlsym(RTLD_DEFAULT, symbol);
    if (fallback) memcpy(&result, &fallback, sizeof(result));
    return result;
}

static void *resolve_egl_symbol(const char *symbol) {
    __eglMustCastToProperFunctionPointerType address;
    void *result = NULL;
    if (!symbol) return NULL;
    address = eglGetProcAddress(symbol);
    if (address) memcpy(&result, &address, sizeof(result));
    if (!result) result = dlsym(RTLD_DEFAULT, symbol);
    return result;
}

static bool stamp_core_frame_timestamp(
        lucent_android_gles_backend *backend,
        uint64_t frame_sequence) {
    lucent_retro_av_info av;
    long double offset_ns;
    EGLnsecsANDROID timestamp;
    void *address;
    double stamp_hz;
    memset(&av, 0, sizeof(av));
    if (!backend || !backend->host || backend->surface == EGL_NO_SURFACE)
        return false;
    if (!backend->presentation_time_android) {
        address = resolve_egl_symbol("eglPresentationTimeANDROID");
        if (address)
            memcpy(&backend->presentation_time_android, &address,
                   sizeof(backend->presentation_time_android));
    }
    if (!backend->presentation_time_android ||
            !lucent_retro_get_av_info(backend->host, &av) ||
            !isfinite(av.frames_per_second) ||
            av.frames_per_second <= 1.0 || av.frames_per_second >= 1000.0) {
        if (!backend->timestamp_failure_logged) {
            __android_log_print(ANDROID_LOG_ERROR, "LucentGlesBackend",
                    "immutable source timestamp unavailable sequence=%llu fps=%.9f",
                    (unsigned long long)frame_sequence,
                    av.frames_per_second);
            backend->timestamp_failure_logged = true;
        }
        return false;
    }
    /* Stamp on the clock the core is paced at (declared x synchronized or
     * paced multiplier), not the declared clock.  A 59.94-declared core
     * paced at the synchronized 60.00 otherwise emits stamps that lag real
     * time by 1001 ppm, forcing the resampler to skip one generated frame
     * every second (GameCube/PSP runs, 2026-09-01).  A clock change re-bases
     * the timeline continuously from the last stamp below. */
    stamp_hz = lucent_retro_synchronized_video_hz(backend->host);
    if (!isfinite(stamp_hz) || stamp_hz <= 1.0 || stamp_hz >= 1000.0)
        stamp_hz = av.frames_per_second;
    if (!backend->timestamp_timeline_ready ||
            fabs(backend->timestamp_source_hz - stamp_hz) > 1e-9 ||
            frame_sequence < backend->timestamp_base_sequence) {
        struct timespec now;
        EGLnsecsANDROID period_ns = (EGLnsecsANDROID)llround(
                1000000000.0 / stamp_hz);
        backend->timestamp_base_sequence = frame_sequence;
        if (backend->timestamp_timeline_ready && backend->timestamp_last_ns > 0) {
            backend->timestamp_base_ns = backend->timestamp_last_ns +
                    (period_ns > 0 ? period_ns : 1);
        } else if (clock_gettime(CLOCK_MONOTONIC, &now) == 0) {
            backend->timestamp_base_ns =
                    (EGLnsecsANDROID)now.tv_sec * 1000000000LL + now.tv_nsec;
        } else {
            /* SurfaceTexture timelines do not require an absolute zero. */
            backend->timestamp_base_ns = 1000000000LL;
        }
        backend->timestamp_source_hz = stamp_hz;
        backend->timestamp_timeline_ready = true;
    }
    offset_ns = (long double)(frame_sequence -
            backend->timestamp_base_sequence) * 1000000000.0L /
            (long double)backend->timestamp_source_hz;
    if (offset_ns < 0.0L || offset_ns > (long double)INT64_MAX -
            (long double)backend->timestamp_base_ns) return false;
    timestamp = backend->timestamp_base_ns +
            (EGLnsecsANDROID)(offset_ns + 0.5L);
    if (timestamp <= backend->timestamp_last_ns)
        timestamp = backend->timestamp_last_ns + 1;
    if (!backend->presentation_time_android(
            backend->display, backend->surface, timestamp)) {
        if (!backend->timestamp_failure_logged) {
            __android_log_print(ANDROID_LOG_ERROR, "LucentGlesBackend",
                    "eglPresentationTimeANDROID failed sequence=%llu error=0x%x",
                    (unsigned long long)frame_sequence, eglGetError());
            backend->timestamp_failure_logged = true;
        }
        return false;
    }
    backend->timestamp_last_ns = timestamp;
    return true;
}

lucent_android_gles_backend *lucent_android_gles_create(
        char *error, size_t error_size) {
    lucent_android_gles_backend *backend =
            (lucent_android_gles_backend *)calloc(1, sizeof(*backend));
    unsigned major = 0, minor = 0;
    unsigned gles3_major = 0, gles3_minor = 0;
    bool has_gles2;
    bool has_gles3;
    if (!backend) {
        set_error(error, error_size, "out of memory creating Android GLES backend");
        return NULL;
    }
    backend->display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    backend->context = EGL_NO_CONTEXT;
    backend->surface = EGL_NO_SURFACE;
    if (backend->display == EGL_NO_DISPLAY ||
            !eglInitialize(backend->display, NULL, NULL) ||
            !eglBindAPI(EGL_OPENGL_ES_API)) {
        set_error(error, error_size, "cannot initialize Android EGL (0x%x)",
                  eglGetError());
        lucent_android_gles_destroy(backend);
        return NULL;
    }
    has_gles2 = probe_context(backend, 2, 0, &major, &minor) && major >= 2;
    has_gles3 = probe_context(backend, 3, 0, &gles3_major, &gles3_minor) &&
            gles3_major >= 3;
    if (has_gles2)
        backend->context_capabilities |= LUCENT_RETRO_HW_GLES2;
    if (has_gles3) {
        backend->context_capabilities |= LUCENT_RETRO_HW_GLES3;
        backend->max_major = gles3_major;
        /* A GLES 3 context created with CLIENT_VERSION may expose 3.1/3.2,
         * but Lucent advertises versioned GLES only after the exact KHR
         * major/minor creation path is independently proven. */
        backend->max_minor = 0;
        minor = gles3_minor;
        if (gles3_minor >= 2 && probe_context(backend, 3, 2, &major, &minor) &&
                (major > 3 || (major == 3 && minor >= 2))) {
            backend->max_major = major;
            backend->max_minor = minor;
            backend->context_capabilities |= LUCENT_RETRO_HW_GLES_VERSION;
        } else if (gles3_minor >= 1 &&
                probe_context(backend, 3, 1, &major, &minor) &&
                (major > 3 || (major == 3 && minor >= 1))) {
            backend->max_major = major;
            backend->max_minor = minor;
            backend->context_capabilities |= LUCENT_RETRO_HW_GLES_VERSION;
        }
    } else if (has_gles2) {
        backend->max_major = major;
        backend->max_minor = minor;
    } else {
        set_error(error, error_size, "Android EGL exposes no usable GLES2 context");
        lucent_android_gles_destroy(backend);
        return NULL;
    }
    {
        EGLConfig feature_config = NULL;
        bool depth = choose_config(backend, backend->max_major, 16, 0,
                                   &feature_config, NULL, 0);
        bool stencil = depth && choose_config(backend, backend->max_major,
                                              24, 8, &feature_config, NULL, 0);
        if ((backend->context_capabilities & LUCENT_RETRO_HW_GLES2) &&
                backend->max_major >= 3) {
            depth = depth && choose_config(backend, 2, 16, 0,
                                           &feature_config, NULL, 0);
            stencil = stencil && choose_config(backend, 2, 24, 8,
                                               &feature_config, NULL, 0);
        }
        if (depth) backend->feature_capabilities |= LUCENT_RETRO_HW_DEPTH;
        if (stencil) backend->feature_capabilities |= LUCENT_RETRO_HW_STENCIL;
    }
    /* RETRO_HW_RENDER's cache_context flag is a lifecycle policy request, not
     * a demand that an EGLContext survive an unrecoverable Android surface or
     * driver loss. Lucent keeps the in-window Surface and its EGLContext alive
     * for the entire foreground game session. On an actual Surface replacement
     * it performs the required ordered context_destroy -> EGL teardown -> new
     * EGL context -> context_reset transition; on EGL_CONTEXT_LOST it omits the
     * unsafe destroy callback and resets the core after recovery. That is the
     * complete libretro contract used by GLideN64/Mupen64Plus-Next, so advertise
     * cache_context while continuing to reject debug requests that the backend
     * does not implement. */
    backend->feature_capabilities |= LUCENT_RETRO_HW_CACHE_CONTEXT;
    /* Shared contexts are genuinely supported, not merely advertised. A core
     * that asks for them creates its own worker contexts from the display and
     * context that are current on the render thread, so Lucent's obligations
     * are: (1) choose a config that can back an off-screen worker surface --
     * choose_config always requests EGL_PBUFFER_BIT alongside EGL_WINDOW_BIT;
     * (2) keep one context current on the render thread while the core runs,
     * which the single render-owner thread guarantees; and (3) signal the
     * ordered context_destroy -> context_reset transition whenever the context
     * is replaced, which the surface-loss path already does, so a core can
     * rebuild its worker contexts. Refusing this stalled Dolphin: with no
     * shader-compiler worker it fell back to draw-skipping and then blocked
     * inside retro_run waiting on a compile that could never be signalled. */
    backend->feature_capabilities |= LUCENT_RETRO_HW_SHARED_CONTEXT;
    return backend;
}

bool lucent_android_gles_get_host_options(
        lucent_android_gles_backend *backend,
        lucent_retro_hw_options *options,
        char *error, size_t error_size) {
    if (!backend || !options || backend->display == EGL_NO_DISPLAY ||
            backend->host || backend->surface != EGL_NO_SURFACE) {
        set_error(error, error_size, "idle initialized GLES backend is required");
        return false;
    }
    memset(options, 0, sizeof(*options));
    options->struct_size = sizeof(*options);
    options->api_version = LUCENT_RETRO_HW_OPTIONS_VERSION;
    options->context_capabilities = backend->context_capabilities;
    options->preferred_context =
            (backend->context_capabilities & LUCENT_RETRO_HW_GLES_VERSION) ?
                    LUCENT_RETRO_HW_GLES_VERSION :
            (backend->context_capabilities & LUCENT_RETRO_HW_GLES3) ?
                    LUCENT_RETRO_HW_GLES3 : LUCENT_RETRO_HW_GLES2;
    /* A matching depth/stencil config is required again during attach. */
    options->feature_capabilities = backend->feature_capabilities;
    options->max_gles_major = backend->max_major;
    options->max_gles_minor = backend->max_minor;
    options->userdata = backend;
    options->get_current_framebuffer = current_framebuffer;
    options->get_proc_address = get_proc_address;
    return true;
}

bool lucent_android_gles_set_presentation_policy(
        lucent_android_gles_backend *backend,
        unsigned policy,
        char *error, size_t error_size) {
    if (!backend || backend->host || backend->surface != EGL_NO_SURFACE) {
        set_error(error, error_size,
                  "presentation policy requires an idle GLES backend");
        return false;
    }
    if (policy != LUCENT_ANDROID_GLES_PRESENT_AUTO &&
            policy != LUCENT_ANDROID_GLES_PRESENT_FRONTEND_FBO &&
            policy != LUCENT_ANDROID_GLES_PRESENT_DIRECT_WINDOW) {
        set_error(error, error_size, "unknown GLES presentation policy %u", policy);
        return false;
    }
    backend->configured_presentation_path = policy;
    backend->presentation_path = policy;
    return true;
}

bool lucent_android_gles_set_presentation_aspect(
        lucent_android_gles_backend *backend,
        float aspect,
        char *error, size_t error_size) {
    if (!backend) {
        set_error(error, error_size, "GLES backend is required");
        return false;
    }
    if (backend->window || backend->surface != EGL_NO_SURFACE) {
        set_error(error, error_size,
                  "GLES presentation aspect must be set before attach");
        return false;
    }
    if (!plausible_aspect(aspect)) {
        set_error(error, error_size,
                  "GLES presentation aspect must be finite and between 0.1 and 10");
        return false;
    }
    backend->presentation_aspect = aspect;
    return true;
}

bool lucent_android_gles_attach(
        lucent_android_gles_backend *backend,
        lucent_retro_host *host,
        void *native_window,
        char *error, size_t error_size) {
    lucent_retro_hw_info info;
    EGLint visual_id = 0;
    unsigned major;
    unsigned minor;
    unsigned depth;
    unsigned stencil;
    unsigned window_width;
    unsigned window_height;
    bool direct_fit_required;
    if (!claim_render_thread(backend, error, error_size) || !host || !native_window ||
            backend->host || backend->surface != EGL_NO_SURFACE) {
        if (backend && (backend->host || backend->surface != EGL_NO_SURFACE))
            set_error(error, error_size, "GLES backend already has an attached surface");
        else if (backend && (!host || !native_window))
            set_error(error, error_size, "host and ANativeWindow are required");
        return false;
    }
    if (!lucent_retro_get_hw_info(host, &info) || !info.negotiated ||
            info.context_ready ||
            (info.context_type != RETRO_HW_CONTEXT_OPENGLES2 &&
             info.context_type != RETRO_HW_CONTEXT_OPENGLES3 &&
             info.context_type != RETRO_HW_CONTEXT_OPENGLES_VERSION)) {
        set_error(error, error_size, "loaded core did not negotiate an unattached GLES context");
        return false;
    }
    major = info.context_type == RETRO_HW_CONTEXT_OPENGLES2 ? 2 :
            (info.version_major ? info.version_major : 3);
    minor = info.context_type == RETRO_HW_CONTEXT_OPENGLES_VERSION ?
            info.version_minor : 0;
    if (major > backend->max_major ||
            (major == backend->max_major && minor > backend->max_minor)) {
        set_error(error, error_size, "core requested GLES %u.%u beyond probed %u.%u",
                  major, minor, backend->max_major, backend->max_minor);
        return false;
    }
    depth = info.depth ? (info.stencil ? 24 : 16) : 0;
    stencil = info.stencil ? 8 : 0;
    if (!choose_config(backend, major, depth, stencil, &backend->config,
                       error, error_size)) return false;
    if (!eglGetConfigAttrib(backend->display, backend->config,
                            EGL_NATIVE_VISUAL_ID, &visual_id)) {
        set_error(error, error_size, "cannot query Android EGL visual (0x%x)",
                  eglGetError());
        return false;
    }
    backend->window = (ANativeWindow *)native_window;
    ANativeWindow_acquire(backend->window);
    if (ANativeWindow_setBuffersGeometry(backend->window, 0, 0, visual_id) != 0) {
        set_error(error, error_size, "ANativeWindow rejected EGL visual %d", visual_id);
        goto fail;
    }
    backend->surface = eglCreateWindowSurface(backend->display, backend->config,
                                              backend->window, NULL);
    backend->context = create_context(backend->display, backend->config,
                                      major, minor);
    if (backend->surface == EGL_NO_SURFACE || backend->context == EGL_NO_CONTEXT ||
            !eglMakeCurrent(backend->display, backend->surface, backend->surface,
                            backend->context)) {
        set_error(error, error_size, "cannot create/make-current Android GLES %u.%u (0x%x)",
                  major, minor, eglGetError());
        goto fail;
    }
    backend->host = host;
    memset(&backend->resume_warmup, 0, sizeof(backend->resume_warmup));
    backend->resume_warmup.required = backend->has_presented_game_frame;
    parse_gles_version((const char *)glGetString(GL_VERSION), major,
                       &backend->active_major, &backend->active_minor);
    backend->depth_bits = depth;
    backend->stencil_bits = stencil;
    backend->presented_sequence = info.frame_sequence;
    window_width = (unsigned)ANativeWindow_getWidth(backend->window);
    window_height = (unsigned)ANativeWindow_getHeight(backend->window);
    direct_fit_required = backend->configured_presentation_path ==
            LUCENT_GLES_PRESENTATION_DIRECT_WINDOW &&
            plausible_aspect(backend->presentation_aspect) && window_height &&
            fabsf(backend->presentation_aspect -
                    (float)window_width / (float)window_height) > 0.001f;
    if ((backend->configured_presentation_path !=
            LUCENT_GLES_PRESENTATION_DIRECT_WINDOW || direct_fit_required) &&
            !create_framebuffer(
                    backend, host, window_width, window_height,
                    error, error_size)) goto fail;
    if (direct_fit_required)
        glViewport(0, 0, (GLsizei)window_width, (GLsizei)window_height);
    if (!lucent_retro_supply_output_size(
            host, window_width, window_height,
            error, error_size)) goto fail;
    if (!lucent_retro_hw_context_reset(host, error, error_size)) goto fail;
    if (!lucent_retro_supply_frontend_framebuffer(
            host, backend->configured_presentation_path ==
                    LUCENT_GLES_PRESENTATION_DIRECT_WINDOW ?
                    0u : backend->framebuffer,
            error, error_size)) goto fail;
    __android_log_print(ANDROID_LOG_INFO, "LucentGlesBackend",
            "hardware context reset complete type=%u GLES=%u.%u depth=%u stencil=%u "
            "cache=%u presentation=%u surface=%dx%d",
            info.context_type, backend->active_major, backend->active_minor,
            backend->depth_bits, backend->stencil_bits,
            info.cache_context ? 1u : 0u, backend->presentation_path,
            ANativeWindow_getWidth(backend->window),
            ANativeWindow_getHeight(backend->window));
    return true;
fail:
    backend->host = NULL;
    delete_framebuffer(backend);
    eglMakeCurrent(backend->display, EGL_NO_SURFACE, EGL_NO_SURFACE,
                   EGL_NO_CONTEXT);
    if (backend->context != EGL_NO_CONTEXT)
        eglDestroyContext(backend->display, backend->context);
    if (backend->surface != EGL_NO_SURFACE)
        eglDestroySurface(backend->display, backend->surface);
    backend->context = EGL_NO_CONTEXT;
    backend->surface = EGL_NO_SURFACE;
    if (backend->window) ANativeWindow_release(backend->window);
    backend->window = NULL;
    backend->active_major = backend->active_minor = 0;
    return false;
}

/* A few valid cores render only to framebuffer zero. When Java's resolved
 * display aspect differs from the Android surface, copy that already-rendered
 * image through the private aspect-sized target, then publish it centered.
 * The core still receives framebuffer zero, so this changes presentation only
 * and does not alter its rendering contract. */
static bool fit_direct_window_frame(
        lucent_android_gles_backend *backend, const GLint core_viewport[4],
        char *error, size_t error_size) {
    GLfloat prior_clear[4];
    GLboolean prior_mask[4];
    GLboolean scissor_enabled;
    GLenum first_read_status;
    GLenum first_draw_status;
    GLenum second_read_status;
    GLenum second_draw_status;
    GLenum blit_error;
    GLint source_x = 0;
    GLint source_y = 0;
    GLint source_width;
    GLint source_height;
    const GLint window_width = ANativeWindow_getWidth(backend->window);
    const GLint window_height = ANativeWindow_getHeight(backend->window);
    if (!backend->framebuffer || !backend->content_width ||
            !backend->content_height) return true;
    source_width = window_width;
    source_height = window_height;
    if (core_viewport[0] >= 0 && core_viewport[1] >= 0 &&
            core_viewport[2] > 0 && core_viewport[3] > 0 &&
            core_viewport[0] + core_viewport[2] <= window_width &&
            core_viewport[1] + core_viewport[3] <= window_height) {
        source_x = core_viewport[0];
        source_y = core_viewport[1];
        source_width = core_viewport[2];
        source_height = core_viewport[3];
    }
    /* The viewport is the core's complete submitted image. Never trim it to
     * make its pixel rectangle resemble a frontend-selected display aspect;
     * the final blit may apply the core's declared pixel aspect, but every
     * source row and column remains present. */
    glGetFloatv(GL_COLOR_CLEAR_VALUE, prior_clear);
    glGetBooleanv(GL_COLOR_WRITEMASK, prior_mask);
    scissor_enabled = glIsEnabled(GL_SCISSOR_TEST);
    if (scissor_enabled) glDisable(GL_SCISSOR_TEST);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);

    glBindFramebuffer(GL_READ_FRAMEBUFFER, 0);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, backend->framebuffer);
    first_read_status = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER);
    first_draw_status = glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER);
    glBlitFramebuffer(source_x, source_y,
                      source_x + source_width, source_y + source_height,
                      0, 0, (GLint)backend->content_width,
                      (GLint)backend->content_height,
                      GL_COLOR_BUFFER_BIT, GL_LINEAR);

    glBindFramebuffer(GL_READ_FRAMEBUFFER, backend->framebuffer);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
    second_read_status = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER);
    second_draw_status = glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glBlitFramebuffer(0, 0, (GLint)backend->content_width,
                      (GLint)backend->content_height,
                      (GLint)backend->destination_x,
                      (GLint)backend->destination_y,
                      (GLint)(backend->destination_x +
                              backend->destination_width),
                      (GLint)(backend->destination_y +
                              backend->destination_height),
                      GL_COLOR_BUFFER_BIT, GL_LINEAR);
    blit_error = glGetError();

    glClearColor(prior_clear[0], prior_clear[1], prior_clear[2], prior_clear[3]);
    glColorMask(prior_mask[0], prior_mask[1], prior_mask[2], prior_mask[3]);
    if (scissor_enabled) glEnable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    if (first_read_status != GL_FRAMEBUFFER_COMPLETE ||
            first_draw_status != GL_FRAMEBUFFER_COMPLETE ||
            second_read_status != GL_FRAMEBUFFER_COMPLETE ||
            second_draw_status != GL_FRAMEBUFFER_COMPLETE ||
            blit_error != GL_NO_ERROR) {
        set_error(error, error_size,
                  "direct-window aspect fit failed (read=0x%x/0x%x draw=0x%x/0x%x gl=0x%x)",
                  first_read_status, second_read_status,
                  first_draw_status, second_draw_status, blit_error);
        return false;
    }
    return true;
}

bool lucent_android_gles_make_current(
        lucent_android_gles_backend *backend,
        char *error, size_t error_size) {
    if (!claim_render_thread(backend, error, error_size) || !backend->host ||
            backend->surface == EGL_NO_SURFACE || backend->context == EGL_NO_CONTEXT) {
        if (backend && !backend->host)
            set_error(error, error_size, "GLES surface is not attached");
        return false;
    }
    if (!eglMakeCurrent(backend->display, backend->surface, backend->surface,
                        backend->context)) {
        EGLint failure = eglGetError();
        if (failure == EGL_CONTEXT_LOST) {
            lucent_retro_hw_context_lost(backend->host, NULL, 0);
            set_error(error, error_size,
                      "Android EGL context lost while making GLES current");
        } else {
            set_error(error, error_size,
                      "cannot make Android GLES context current (0x%x)", failure);
        }
        return false;
    }
    return true;
}

static int64_t resume_monotonic_ns(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return 0;
    return (int64_t)now.tv_sec * 1000000000LL + now.tv_nsec;
}

static void finish_resume_warmup(lucent_android_gles_backend *backend,
                                  const char *reason) {
    lucent_gles_resume_warmup *warmup = &backend->resume_warmup;
    if (warmup->collecting)
        eglSurfaceAttrib(backend->display, backend->surface,
                         EGL_TIMESTAMPS_ANDROID, EGL_FALSE);
    if (warmup->required && reason)
        __android_log_print(ANDROID_LOG_INFO, "LucentGLESResume",
                "warmup=%s submitted=%u elapsedMs=%.3f intervalNs=%lld",
                reason, warmup->submitted,
                warmup->started_ns ? (resume_monotonic_ns() - warmup->started_ns) / 1e6 : 0.0,
                (long long)warmup->interval_ns);
    memset(warmup, 0, sizeof(*warmup));
}

bool lucent_android_gles_prepare_resume(
        lucent_android_gles_backend *backend, bool *ready,
        char *error, size_t error_size) {
    if (ready) *ready = false;
    if (!ready || !claim_render_thread(backend, error, error_size)) return false;
    lucent_gles_resume_warmup *warmup = &backend->resume_warmup;
    if (!warmup->required) { *ready = true; return true; }
    if (!lucent_android_gles_make_current(backend, error, error_size)) return false;
    if (backend->fg_timestamp_enabled) {
        finish_resume_warmup(backend, "fg-bypass");
        *ready = true;
        return true;
    }
    if (!warmup->collecting) {
        if (backend->active_major < 3) {
            finish_resume_warmup(backend, "gles2-fallback");
            *ready = true;
            return true;
        }
        const char *extensions = eglQueryString(backend->display, EGL_EXTENSIONS);
        PFNEGLGETFRAMETIMESTAMPSUPPORTEDANDROIDPROC supported =
            (PFNEGLGETFRAMETIMESTAMPSUPPORTEDANDROIDPROC)
                eglGetProcAddress("eglGetFrameTimestampSupportedANDROID");
        PFNEGLGETCOMPOSITORTIMINGANDROIDPROC timing =
            (PFNEGLGETCOMPOSITORTIMINGANDROIDPROC)
                eglGetProcAddress("eglGetCompositorTimingANDROID");
        warmup->next_id = (PFNEGLGETNEXTFRAMEIDANDROIDPROC)
            eglGetProcAddress("eglGetNextFrameIdANDROID");
        warmup->timestamps = (PFNEGLGETFRAMETIMESTAMPSANDROIDPROC)
            eglGetProcAddress("eglGetFrameTimestampsANDROID");
        EGLint name = EGL_COMPOSITE_INTERVAL_ANDROID;
        if (!extensions || !strstr(extensions, "EGL_ANDROID_get_frame_timestamps") ||
                !supported || !timing || !warmup->next_id || !warmup->timestamps ||
                !supported(backend->display, backend->surface, EGL_DISPLAY_PRESENT_TIME_ANDROID) ||
                !eglSurfaceAttrib(backend->display, backend->surface, EGL_TIMESTAMPS_ANDROID, EGL_TRUE)) {
            finish_resume_warmup(backend, "unsupported-fallback");
            *ready = true;
            return true;
        }
        warmup->collecting = true;
        warmup->started_ns = resume_monotonic_ns();
        /* Android Surface::getCompositorTiming requires collection enabled,
         * even though the interval may be queried before the first swap. */
        if (!timing(backend->display, backend->surface, 1, &name, &warmup->interval_ns) ||
                warmup->interval_ns < 1000000 || warmup->interval_ns > 100000000) {
            finish_resume_warmup(backend, "compositor-interval-unavailable");
            *ready = true;
            return true;
        }
    }
    int64_t now = resume_monotonic_ns();
    if (!now || now - warmup->started_ns >= 2000000000LL || warmup->submitted >= 120) {
        finish_resume_warmup(backend, "timeout-unqualified");
        *ready = true;
        return true;
    }
    EGLint name = EGL_DISPLAY_PRESENT_TIME_ANDROID;
    /* Process in submission order, including when the fixed ring wraps.
     * Failed/dropped IDs never block progress on newer, displayed frames. */
    unsigned first = warmup->submitted > 16 ? warmup->submitted - 16 : 0;
    for (unsigned i = first; i < warmup->submitted; ++i) {
        lucent_gles_resume_frame *frame = &warmup->frames[i % 16];
        if (!frame->pending) continue;
        EGLnsecsANDROID presented = EGL_TIMESTAMP_PENDING_ANDROID;
        bool ok = warmup->timestamps(backend->display, backend->surface,
                                    frame->id, 1, &name, &presented);
        if (ok && presented == EGL_TIMESTAMP_PENDING_ANDROID) continue;
        frame->pending = false;
        if (ok && lucent_presentation_resume_observe(&warmup->cadence, frame->id,
                presented, resume_monotonic_ns(), warmup->interval_ns)) {
            finish_resume_warmup(backend, "physical-cadence-ready");
            *ready = true;
            return true;
        }
    }
    lucent_gles_resume_frame *frame = &warmup->frames[warmup->submitted % 16];
    if (!warmup->next_id(backend->display, backend->surface, &frame->id)) {
        finish_resume_warmup(backend, "frame-id-unavailable");
        *ready = true;
        return true;
    }
    GLint prior_read = 0, prior_draw = 0;
    GLfloat prior_clear[4];
    GLboolean prior_mask[4];
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &prior_read);
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &prior_draw);
    glGetFloatv(GL_COLOR_CLEAR_VALUE, prior_clear);
    glGetBooleanv(GL_COLOR_WRITEMASK, prior_mask);
    GLboolean scissor = glIsEnabled(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
    if (scissor) glDisable(GL_SCISSOR_TEST);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glClearColor(prior_clear[0], prior_clear[1], prior_clear[2], prior_clear[3]);
    glColorMask(prior_mask[0], prior_mask[1], prior_mask[2], prior_mask[3]);
    if (scissor) glEnable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, (GLuint)prior_read);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, (GLuint)prior_draw);
    if (!eglSwapBuffers(backend->display, backend->surface)) {
        EGLint failure = eglGetError();
        finish_resume_warmup(backend, "swap-failed");
        if (failure == EGL_CONTEXT_LOST) {
            lucent_retro_hw_context_lost(backend->host, NULL, 0);
            set_error(error, error_size, "Android EGL context lost during resume warmup");
        } else set_error(error, error_size, "Android EGL resume warmup swap failed (0x%x)", failure);
        return false;
    }
    frame->pending = true;
    ++warmup->submitted;
    return true;
}

static bool present_current_frame(
        lucent_android_gles_backend *backend,
        bool *presented,
        char *error, size_t error_size) {
    lucent_retro_hw_info info;
    unsigned source_width;
    unsigned source_height;
    GLint source_x = 0;
    GLint source_y = 0;
    GLint core_viewport[4] = {0, 0, 0, 0};
    bool core_viewport_valid;
    uint32_t active_rect[7] = {0};
    bool has_active_rect = false;
    int destination_x, destination_y;
    unsigned destination_width, destination_height;
    EGLint failure;
    if (presented) *presented = false;
    if (!presented || !lucent_android_gles_make_current(backend, error, error_size))
        return false;
    if (!lucent_retro_get_hw_info(backend->host, &info) || !info.context_ready) {
        set_error(error, error_size, "core hardware context is not ready");
        return false;
    }
    if (info.frame_sequence == backend->presented_sequence) return true;
    destination_x = backend->destination_x;
    destination_y = backend->destination_y;
    destination_width = backend->destination_width;
    destination_height = backend->destination_height;
    log_framebuffer_pixels(backend, info.frame_sequence);
    if (backend->presentation_path == LUCENT_GLES_PRESENTATION_UNKNOWN) {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, backend->framebuffer);
        backend->presentation_path = frontend_framebuffer_was_rendered(backend) ?
                LUCENT_GLES_PRESENTATION_FRONTEND_FBO :
                LUCENT_GLES_PRESENTATION_DIRECT_WINDOW;
    }
    glGetIntegerv(GL_VIEWPORT, core_viewport);
    core_viewport_valid =
            core_viewport[0] == 0 && core_viewport[1] == 0 &&
            core_viewport[2] > 0 && core_viewport[3] > 0 &&
            (unsigned)core_viewport[2] <= backend->framebuffer_width &&
            (unsigned)core_viewport[3] <= backend->framebuffer_height &&
            (!info.frame_width || (unsigned)core_viewport[2] >= info.frame_width) &&
            (!info.frame_height || (unsigned)core_viewport[3] >= info.frame_height);
    /* A hardware core's video callback dimensions are not uniformly defined.
     * Flycast reports the actual rendered target, while PPSSPP reports the
     * guest's logical 480x272 image even after rendering its final image into
     * the frontend-provided 1920x1080 target.  Treat a substantially smaller
     * callback size as logical geometry and blit the complete frontend target;
     * otherwise retain the exact reported dimensions (important for cores
     * whose internal render target is deliberately smaller than the backing
     * texture). */
    source_width = info.frame_width && backend->framebuffer_width &&
            info.frame_width <= backend->framebuffer_width &&
            info.frame_width * 2u >= backend->content_width ?
            info.frame_width : backend->content_width;
    source_height = info.frame_height && backend->framebuffer_height &&
            info.frame_height <= backend->framebuffer_height &&
            info.frame_height * 2u >= backend->content_height ?
            info.frame_height : backend->content_height;
    /* Integer-scaled hardware cores can report logical callback geometry
     * while drawing a larger image into the lower-left of the frontend FBO.
     * Some cores report logical sizes despite an integer-scaled GL viewport.
     * Dolphin's current adapter already reports its scaled 1280x1056 output.
     * Blitting the complete 1920x1080 allocation includes unwritten
     * padding and clips the game's right edge. Prefer the actual post-run
     * viewport when it is a valid origin-anchored region of our FBO. */
    if (backend->presentation_path == LUCENT_GLES_PRESENTATION_FRONTEND_FBO &&
            core_viewport_valid) {
        source_width = (unsigned)core_viewport[2];
        source_height = (unsigned)core_viewport[3];
    }
    /* A core can leave either a scratch viewport (Mupen was observed at
     * 2880x2880 for a 1440x1088 FBO) or a nominally valid 1440x1080 viewport
     * while writing a smaller VI rectangle. Derive the core-written source
     * rectangle from the untouched sentinel during bounded startup in both
     * cases. This is
     * title-dynamic source geometry: F-Zero and Ocarina may write different
     * rectangles, while both still land in the core-declared display aspect
     * without clipping or exposing allocation pixels. The core's display
     * aspect, not the ratio of its often non-square source pixels, remains
     * authoritative. */
    /* This is a GLideN64-specific contract, not generic image detection.
     * Dolphin clears its entire backing FBO, including padding outside its
     * reported output. Treating those cleared pixels as video both overrides
     * correct callback dimensions on wake and can delay cold presentation for
     * 600 callbacks. Other cores retain the callback/viewport geometry above. */
    /* Patched cores can report the actual final VI copy without GPU readback.
     * Preserve its display-pixel proportions while fitting the active rectangle,
     * rather than forcing a smaller active picture back into nominal 4:3. */
    if (backend->presentation_path == LUCENT_GLES_PRESENTATION_FRONTEND_FBO &&
            (info.source_timeline_policy &
             LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS) &&
            lucent_retro_get_hw_active_rect(backend->host, active_rect) &&
            active_rect[5] <= backend->framebuffer_width &&
            active_rect[6] <= backend->framebuffer_height &&
            backend->content_width && backend->content_height) {
        const double aspect = (double)active_rect[3] * backend->content_width *
                active_rect[6] / ((double)active_rect[4] * backend->content_height *
                                  active_rect[5]);
        const int window_width = ANativeWindow_getWidth(backend->window);
        const int window_height = ANativeWindow_getHeight(backend->window);
        if (plausible_aspect((float)aspect) && window_width > 0 && window_height > 0) {
            has_active_rect = true;
            source_x = (GLint)active_rect[1];
            source_y = (GLint)active_rect[2];
            source_width = active_rect[3];
            source_height = active_rect[4];
            destination_height = (unsigned)window_height;
            destination_width = (unsigned)(window_height * aspect + 0.5);
            if (destination_width > (unsigned)window_width) {
                destination_width = (unsigned)window_width;
                destination_height = (unsigned)(window_width / aspect + 0.5);
            }
            if (!destination_width) destination_width = 1u;
            if (!destination_height) destination_height = 1u;
            destination_x = (window_width - (int)destination_width) / 2;
            destination_y = (window_height - (int)destination_height) / 2;
            if (memcmp(backend->last_active_rect, active_rect, sizeof(active_rect))) {
                memcpy(backend->last_active_rect, active_rect, sizeof(active_rect));
                backend->presentation_geometry_logged = false;
            }
        }
    }
    if (!has_active_rect &&
            backend->presentation_path == LUCENT_GLES_PRESENTATION_FRONTEND_FBO &&
            (info.source_timeline_policy &
                    LUCENT_RETRO_SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS)) {
        if (backend->content_bounds_stable_count < 4u &&
                backend->content_bounds_probe_count < 600u) {
            unsigned detected_x = 0;
            unsigned detected_y = 0;
            unsigned detected_width = 0;
            unsigned detected_height = 0;
            int detected;
            glBindFramebuffer(GL_READ_FRAMEBUFFER, backend->framebuffer);
            detected = probe_frontend_content_bounds(
                    backend, &detected_x, &detected_y,
                    &detected_width, &detected_height);
            backend->content_bounds_probe_count++;
            if (detected > 0) {
                bool changed = !backend->content_bounds_valid ||
                        backend->content_source_x != detected_x ||
                        backend->content_source_y != detected_y ||
                        backend->content_source_width != detected_width ||
                        backend->content_source_height != detected_height;
                backend->content_bounds_stable_count = changed ? 1u :
                        backend->content_bounds_stable_count + 1u;
                backend->content_bounds_valid = true;
                backend->content_source_x = detected_x;
                backend->content_source_y = detected_y;
                backend->content_source_width = detected_width;
                backend->content_source_height = detected_height;
                if (changed) {
                    __android_log_print(ANDROID_LOG_INFO, "LucentGlesBackend",
                            "title-dynamic source bounds=%u,%u,%ux%u "
                            "allocation=%ux%u probe=%u",
                            detected_x, detected_y, detected_width,
                            detected_height, backend->framebuffer_width,
                            backend->framebuffer_height,
                            backend->content_bounds_probe_count);
                }
            } else if (backend->content_bounds_probe_count < 600u) {
                backend->content_bounds_stable_count = 0u;
                /* Do not publish the untouched diagnostic allocation or a
                 * tiny boot glyph. The next core frame will be checked, with
                 * a hard ten-second/600-callback bound so a broken probe
                 * cannot hang. Mupen may submit twelve untouched callbacks
                 * before the restored title writes its first real VI image. */
                glBindFramebuffer(GL_FRAMEBUFFER, 0);
                backend->presented_sequence = info.frame_sequence;
                return true;
            }
        }
        if (backend->content_bounds_valid &&
                (!core_viewport_valid ||
                 backend->content_source_x != 0u ||
                 backend->content_source_y != 0u ||
                 backend->content_source_width != backend->content_width ||
                 backend->content_source_height != backend->content_height)) {
            source_x = (GLint)backend->content_source_x;
            source_y = (GLint)backend->content_source_y;
            source_width = backend->content_source_width;
            source_height = backend->content_source_height;
        }
    }
    if (!backend->presentation_geometry_logged) {
        bool source_padding = backend->presentation_path ==
                LUCENT_GLES_PRESENTATION_FRONTEND_FBO &&
                core_viewport[0] == 0 && core_viewport[1] == 0 &&
                core_viewport[2] > 0 && core_viewport[3] > 0 &&
                (source_width > (unsigned)core_viewport[2] ||
                 source_height > (unsigned)core_viewport[3]);
        __android_log_print(ANDROID_LOG_INFO, "LucentGlesBackend",
                "presentation geometry source=%d,%d,%ux%u viewport=%d,%d,%dx%d "
                "fbo=%ux%u destination=%d,%d,%ux%u sourcePadding=%u",
                source_x, source_y, source_width, source_height,
                core_viewport[0], core_viewport[1],
                core_viewport[2], core_viewport[3], backend->framebuffer_width,
                backend->framebuffer_height, destination_x,
                destination_y, destination_width,
                destination_height, source_padding ? 1u : 0u);
        backend->presentation_geometry_logged = true;
    }
    if (backend->presentation_path == LUCENT_GLES_PRESENTATION_FRONTEND_FBO) {
        GLfloat prior_clear[4];
        GLboolean prior_mask[4];
        GLboolean scissor_enabled;
        GLenum read_status;
        GLenum draw_status;
        GLenum preexisting_error = GL_NO_ERROR;
        GLenum blit_error;
        GLenum pending_error;
        GLubyte source_left[4] = {0, 0, 0, 0};
        GLubyte source_center[4] = {0, 0, 0, 0};
        GLubyte source_right[4] = {0, 0, 0, 0};

        /* Dolphin's OGL backend deliberately leaves scissor testing enabled.
         * glBlitFramebuffer obeys that scissor, so presenting without
         * neutralizing it clips the 1440-wide destination at the core's
         * 1280px backbuffer boundary and exposes uninitialized window rows.
         * Clear all of framebuffer zero and disable the scissor only for the
         * ownership handoff, then restore every state value we touched. */
        glGetFloatv(GL_COLOR_CLEAR_VALUE, prior_clear);
        glGetBooleanv(GL_COLOR_WRITEMASK, prior_mask);
        scissor_enabled = glIsEnabled(GL_SCISSOR_TEST);
        while ((pending_error = glGetError()) != GL_NO_ERROR)
            preexisting_error = pending_error;
        if (scissor_enabled) glDisable(GL_SCISSOR_TEST);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, backend->framebuffer);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
        read_status = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER);
        draw_status = glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER);
        if (backend->framebuffer_blit_diagnostics < 3u) {
            GLint sample_y = source_height > 1u ?
                    (GLint)(source_height / 2u) : 0;
            glReadPixels(1, sample_y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE,
                         source_left);
            glReadPixels((GLint)(source_width / 2u), sample_y, 1, 1,
                         GL_RGBA, GL_UNSIGNED_BYTE, source_center);
            glReadPixels(source_width > 1u ? (GLint)source_width - 2 : 0,
                         sample_y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE,
                         source_right);
        }
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        glBlitFramebuffer(source_x, source_y,
                          source_x + (GLint)source_width,
                          source_y + (GLint)source_height,
                          (GLint)destination_x,
                          (GLint)destination_y,
                          (GLint)(destination_x + destination_width),
                          (GLint)(destination_y + destination_height),
                          GL_COLOR_BUFFER_BIT, GL_LINEAR);
        blit_error = glGetError();
        glClearColor(prior_clear[0], prior_clear[1], prior_clear[2], prior_clear[3]);
        glColorMask(prior_mask[0], prior_mask[1], prior_mask[2], prior_mask[3]);
        if (scissor_enabled) glEnable(GL_SCISSOR_TEST);
        if (read_status != GL_FRAMEBUFFER_COMPLETE ||
                draw_status != GL_FRAMEBUFFER_COMPLETE ||
                blit_error != GL_NO_ERROR) {
            __android_log_print(ANDROID_LOG_ERROR, "LucentGlesBackend",
                    "frontend blit failed readStatus=0x%x drawStatus=0x%x "
                    "glError=0x%x scissorWasEnabled=%u",
                    read_status, draw_status, blit_error,
                    scissor_enabled ? 1u : 0u);
            glBindFramebuffer(GL_FRAMEBUFFER, 0);
            set_error(error, error_size,
                    "frontend FBO presentation failed (read=0x%x draw=0x%x gl=0x%x)",
                    read_status, draw_status, blit_error);
            return false;
        }
        if (backend->framebuffer_blit_diagnostics < 3u) {
            __android_log_print(ANDROID_LOG_INFO, "LucentGlesBackend",
                    "frontend blit complete sequence=%llu scissorWasEnabled=%u "
                    "readStatus=0x%x drawStatus=0x%x preexistingGlError=0x%x "
                    "glError=0x%x "
                    "sourceLeft=%u,%u,%u,%u sourceCenter=%u,%u,%u,%u "
                    "sourceRight=%u,%u,%u,%u",
                    (unsigned long long)info.frame_sequence,
                    scissor_enabled ? 1u : 0u, read_status, draw_status,
                    preexisting_error, blit_error,
                    source_left[0], source_left[1], source_left[2], source_left[3],
                    source_center[0], source_center[1], source_center[2],
                    source_center[3], source_right[0], source_right[1],
                    source_right[2], source_right[3]);
            backend->framebuffer_blit_diagnostics++;
        }
    }
    if (backend->presentation_path == LUCENT_GLES_PRESENTATION_DIRECT_WINDOW &&
            !fit_direct_window_frame(backend, core_viewport,
                                     error, error_size)) return false;
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    force_opaque_surface_alpha();
    /* Only an FG-owned SurfaceTexture needs a synthetic source timeline.
     * On a physical display this is a presentation deadline, so Off must
     * bypass both timestamp calculation and EGL presentation-time calls. */
    if (backend->fg_timestamp_enabled) {
        stamp_core_frame_timestamp(backend, info.frame_sequence);
    } else if (!backend->direct_timestamp_bypass_logged) {
        __android_log_print(ANDROID_LOG_INFO, "LucentGLES",
                "Direct surface: FG source timestamp bypassed");
        backend->direct_timestamp_bypass_logged = true;
    }
    if (!eglSwapBuffers(backend->display, backend->surface)) {
        failure = eglGetError();
        if (failure == EGL_CONTEXT_LOST) {
            lucent_retro_hw_context_lost(backend->host, NULL, 0);
            set_error(error, error_size, "Android EGL context lost during swap");
        } else {
            set_error(error, error_size, "Android EGL swap failed (0x%x)", failure);
        }
        return false;
    }
    backend->presented_sequence = info.frame_sequence;
    *presented = true;
    backend->has_presented_game_frame = true;
    return true;
}

bool lucent_android_gles_present_if_ready(
        lucent_android_gles_backend *backend, bool *presented,
        char *error, size_t error_size) {
    GLint prior_read = 0;
    GLint prior_draw = 0;
    lucent_retro_hw_info info;
    if (presented) *presented = false;
    if (!presented || !lucent_android_gles_make_current(backend, error, error_size))
        return false;
    /* The core owns this context between presents. Dolphin caches its FBO
     * binding, so leaving framebuffer zero bound redirects its next draws
     * without updating that cache. Save before diagnostics or any blit and
     * restore BOTH bindings, including early-return/error paths. */
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &prior_read);
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &prior_draw);
    const bool result = present_current_frame(backend, presented, error, error_size);
    if (lucent_retro_get_hw_info(backend->host, &info) && info.context_ready) {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, (GLuint)prior_read);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, (GLuint)prior_draw);
    }
    return result;
}

/* A resize notification keeps the same live Android Surface; only its buffer
 * geometry changed. Rebuild Lucent-owned presentation state inside the
 * existing EGL context. This deliberately performs no core
 * context_destroy/context_reset and no EGL teardown: a duplicate attach or
 * resize notification must never pay the destructive recreate price, which
 * double-resets cores such as Mupen64Plus-Next and crashes before gameplay
 * (2026-08-21 F-Zero X evidence). Genuine surface replacement still goes
 * through detach -> attach below. */
bool lucent_android_gles_surface_resized(
        lucent_android_gles_backend *backend,
        char *error, size_t error_size) {
    unsigned window_width;
    unsigned window_height;
    bool direct_fit_required;
    if (!backend || !backend->host || !backend->window ||
            backend->surface == EGL_NO_SURFACE) {
        set_error(error, error_size, "attached GLES backend is required for resize");
        return false;
    }
    if (!claim_render_thread(backend, error, error_size)) return false;
    if (!lucent_android_gles_make_current(backend, error, error_size)) return false;
    window_width = (unsigned)ANativeWindow_getWidth(backend->window);
    window_height = (unsigned)ANativeWindow_getHeight(backend->window);
    direct_fit_required = backend->configured_presentation_path ==
            LUCENT_GLES_PRESENTATION_DIRECT_WINDOW &&
            plausible_aspect(backend->presentation_aspect) && window_height &&
            fabsf(backend->presentation_aspect -
                    (float)window_width / (float)window_height) > 0.001f;
    delete_framebuffer(backend);
    if ((backend->configured_presentation_path !=
            LUCENT_GLES_PRESENTATION_DIRECT_WINDOW || direct_fit_required) &&
            !create_framebuffer(
                    backend, backend->host, window_width, window_height,
                    error, error_size)) return false;
    if (direct_fit_required)
        glViewport(0, 0, (GLsizei)window_width, (GLsizei)window_height);
    if (!lucent_retro_supply_output_size(
            backend->host, window_width, window_height,
            error, error_size)) return false;
    return lucent_retro_supply_frontend_framebuffer(
            backend->host,
            backend->configured_presentation_path ==
                    LUCENT_GLES_PRESENTATION_DIRECT_WINDOW ?
                    0u : backend->framebuffer,
            error, error_size);
}

bool lucent_android_gles_detach(
        lucent_android_gles_backend *backend,
        char *error, size_t error_size) {
    bool ok = true;
    if (!claim_render_thread(backend, error, error_size)) return false;
    lucent_android_gles_set_fg_timestamp(backend, false, NULL, 0);
    finish_resume_warmup(backend, "cancelled");
    if (!backend->host) return true;
    if (!lucent_android_gles_make_current(backend, error, error_size)) {
        lucent_retro_hw_context_lost(backend->host, NULL, 0);
        abandon_framebuffer(backend);
        ok = false;
    } else {
        if (!lucent_retro_hw_context_destroy(backend->host, error, error_size))
            ok = false;
        if (!lucent_retro_supply_frontend_framebuffer(
                backend->host, 0, error, error_size)) ok = false;
    }
    if (eglGetCurrentContext() == backend->context)
        delete_framebuffer(backend);
    eglMakeCurrent(backend->display, EGL_NO_SURFACE, EGL_NO_SURFACE,
                   EGL_NO_CONTEXT);
    if (backend->surface != EGL_NO_SURFACE)
        eglDestroySurface(backend->display, backend->surface);
    if (backend->context != EGL_NO_CONTEXT)
        eglDestroyContext(backend->display, backend->context);
    backend->surface = EGL_NO_SURFACE;
    backend->context = EGL_NO_CONTEXT;
    backend->host = NULL;
    if (backend->window) ANativeWindow_release(backend->window);
    backend->window = NULL;
    backend->config = NULL;
    backend->active_major = backend->active_minor = 0;
    backend->depth_bits = backend->stencil_bits = 0;
    return ok;
}

bool lucent_android_gles_get_info(
        const lucent_android_gles_backend *backend,
        lucent_android_gles_info *info) {
    if (!backend || !info) return false;
    memset(info, 0, sizeof(*info));
    info->display_ready = backend->display != EGL_NO_DISPLAY;
    info->surface_attached = backend->host &&
            backend->surface != EGL_NO_SURFACE &&
            backend->context != EGL_NO_CONTEXT;
    info->max_gles_major = backend->max_major;
    info->max_gles_minor = backend->max_minor;
    info->active_gles_major = backend->active_major;
    info->active_gles_minor = backend->active_minor;
    info->depth_bits = backend->depth_bits;
    info->stencil_bits = backend->stencil_bits;
    info->presented_sequence = backend->presented_sequence;
    return true;
}

void lucent_android_gles_destroy(lucent_android_gles_backend *backend) {
    if (!backend) return;
    /* A wrong-thread destructor cannot safely invalidate callback userdata or
     * terminate a display that is current elsewhere. Fail closed by retaining
     * the backend; integration must return to the render thread and detach. */
    if (backend->host && !on_render_thread(backend)) return;
    if (backend->host) lucent_android_gles_detach(backend, NULL, 0);
    if (backend->display != EGL_NO_DISPLAY) eglTerminate(backend->display);
    free(backend);
}
