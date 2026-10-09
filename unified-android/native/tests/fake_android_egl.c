#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <android/native_window.h>
#include <stdbool.h>
#include <string.h>
#include <time.h>

static int display_token, config_token, context_token, surface_token;
static EGLContext current_context;
static EGLint last_error = EGL_SUCCESS;
static unsigned swap_count, acquire_count, release_count;
static int completion_support, completion_enabled;
static int hold_completions;
static int64_t completion_times[256];
void lucent_fake_egl_completion_support(int enabled) { completion_support = enabled; }
int lucent_fake_egl_completion_enabled(void) { return completion_enabled; }
void lucent_fake_egl_hold_completions(int hold) { hold_completions = hold; }
void lucent_fake_egl_complete_last_frames(unsigned count, int64_t interval_ns) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    int64_t latest = (int64_t)now.tv_sec * 1000000000LL + now.tv_nsec;
    for (unsigned age = 0; age < count && age < swap_count && age < 256; ++age)
        completion_times[(swap_count - age) % 256] = latest - age * interval_ns;
    hold_completions = 0;
}
const char *eglQueryString(EGLDisplay display, EGLint name) {
    (void)display; (void)name;
    return completion_support ? "EGL_ANDROID_get_frame_timestamps" : "";
}
EGLBoolean eglSurfaceAttrib(EGLDisplay d, EGLSurface s, EGLint name, EGLint value) {
    (void)d; (void)s;
    if (name != EGL_TIMESTAMPS_ANDROID) return EGL_FALSE;
    completion_enabled = value;
    return EGL_TRUE;
}
static EGLBoolean fake_next_frame(EGLDisplay d, EGLSurface s, EGLuint64KHR *id) {
    (void)d; (void)s; *id = swap_count + 1; return EGL_TRUE;
}
static EGLBoolean fake_frame_time(EGLDisplay d, EGLSurface s, EGLuint64KHR id,
                                  EGLint count, const EGLint *names, EGLnsecsANDROID *times) {
    (void)d; (void)s; (void)names;
    if (count != 1) return EGL_FALSE;
    times[0] = !hold_completions && id <= swap_count ?
            completion_times[id % 256] : EGL_TIMESTAMP_PENDING_ANDROID;
    return EGL_TRUE;
}
static EGLBoolean fake_completion_supported(EGLDisplay d, EGLSurface s, EGLint name) {
    (void)d; (void)s; (void)name; return completion_support;
}
static EGLBoolean fake_compositor_timing(EGLDisplay d, EGLSurface s, EGLint count,
                                        const EGLint *names, EGLnsecsANDROID *times) {
    (void)d; (void)s; (void)names;
    /* Android13 Surface::getCompositorTiming requires timestamp collection. */
    if (count != 1 || !completion_enabled) return EGL_FALSE;
    times[0] = 16666667; return EGL_TRUE;
}
static unsigned blit_count;
static unsigned opaque_alpha_clear_count;
static unsigned presentation_time_count;
static int64_t presentation_time_previous;
static int64_t presentation_time_last;
static GLint last_blit_source_x1;
static GLint last_blit_source_y1;
static GLint last_blit_source_x0;
static GLint last_blit_source_y0;
static GLint previous_blit_source_x0;
static GLint previous_blit_source_y0;
static GLint previous_blit_source_x1;
static GLint previous_blit_source_y1;
static GLint last_blit_destination_x0;
static GLint last_blit_destination_y0;
static GLint last_blit_destination_x1;
static GLint last_blit_destination_y1;
static GLuint bound_framebuffer;
static GLuint bound_read_framebuffer;
static int lose_next_swap;
static GLfloat clear_color[4] = {0, 0, 0, 0};
static GLboolean color_mask[4] = {GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE};
static GLboolean scissor_enabled;
static GLint viewport[4] = {0, 0, 0, 0};
static int sentinel_bounds_enabled;
static GLint sentinel_left = 100, sentinel_bottom = 50;
static GLint sentinel_right = 1340, sentinel_top = 1030;
static unsigned bounds_readbacks;
static GLsizei texture_width, texture_height;
int lucent_fake_gles_texture_width(void) { return texture_width; }
int lucent_fake_gles_texture_height(void) { return texture_height; }
unsigned lucent_fake_gles_bounds_readbacks(void) { return bounds_readbacks; }
static int32_t fake_window_width = 1920;
static int32_t fake_window_height = 1080;
static void fake_symbol(void) {}
static EGLBoolean fake_presentation_time(EGLDisplay d, EGLSurface s,
                                         int64_t timestamp) {
    if (d != &display_token || s != &surface_token || timestamp <= 0)
        return EGL_FALSE;
    presentation_time_previous = presentation_time_last;
    presentation_time_last = timestamp;
    presentation_time_count++;
    return EGL_TRUE;
}

EGLDisplay eglGetDisplay(void *unused) { (void)unused; return &display_token; }
EGLBoolean eglInitialize(EGLDisplay display, EGLint *major, EGLint *minor) {
    (void)major; (void)minor; return display == &display_token;
}
EGLBoolean eglBindAPI(EGLint api) { return api == EGL_OPENGL_ES_API; }
EGLBoolean eglChooseConfig(EGLDisplay display, const EGLint *attributes,
                           EGLConfig *configs, EGLint size, EGLint *count) {
    (void)attributes;
    if (display != &display_token || !configs || size < 1 || !count) return EGL_FALSE;
    configs[0] = &config_token; *count = 1; return EGL_TRUE;
}
EGLContext eglCreateContext(EGLDisplay display, EGLConfig config,
                            EGLContext shared, const EGLint *attributes) {
    (void)shared; (void)attributes;
    return display == &display_token && config == &config_token ?
            &context_token : EGL_NO_CONTEXT;
}
EGLSurface eglCreatePbufferSurface(EGLDisplay display, EGLConfig config,
                                   const EGLint *attributes) {
    (void)attributes;
    return display == &display_token && config == &config_token ?
            &surface_token : EGL_NO_SURFACE;
}
EGLSurface eglCreateWindowSurface(EGLDisplay display, EGLConfig config,
                                  void *window, const EGLint *attributes) {
    (void)attributes;
    return display == &display_token && config == &config_token && window ?
            &surface_token : EGL_NO_SURFACE;
}
EGLBoolean eglMakeCurrent(EGLDisplay display, EGLSurface draw,
                          EGLSurface read, EGLContext context) {
    (void)draw; (void)read;
    if (display != &display_token) return EGL_FALSE;
    current_context = context; return EGL_TRUE;
}
EGLContext eglGetCurrentContext(void) { return current_context; }
EGLBoolean eglDestroySurface(EGLDisplay d, EGLSurface s) {
    return d == &display_token && s == &surface_token;
}
EGLBoolean eglDestroyContext(EGLDisplay d, EGLContext c) {
    return d == &display_token && c == &context_token;
}
EGLBoolean eglGetConfigAttrib(EGLDisplay d, EGLConfig c, EGLint attribute,
                              EGLint *value) {
    if (d != &display_token || c != &config_token ||
            attribute != EGL_NATIVE_VISUAL_ID || !value) return EGL_FALSE;
    *value = 1; return EGL_TRUE;
}
__eglMustCastToProperFunctionPointerType eglGetProcAddress(const char *name) {
    if (name && strcmp(name, "eglGetNextFrameIdANDROID") == 0)
        return (__eglMustCastToProperFunctionPointerType)fake_next_frame;
    if (name && strcmp(name, "eglGetFrameTimestampsANDROID") == 0)
        return (__eglMustCastToProperFunctionPointerType)fake_frame_time;
    if (name && strcmp(name, "eglGetFrameTimestampSupportedANDROID") == 0)
        return (__eglMustCastToProperFunctionPointerType)fake_completion_supported;
    if (name && strcmp(name, "eglGetCompositorTimingANDROID") == 0)
        return (__eglMustCastToProperFunctionPointerType)fake_compositor_timing;
    if (name && strcmp(name, "lucent_mock_symbol") == 0) return fake_symbol;
    if (name && strcmp(name, "eglPresentationTimeANDROID") == 0)
        return (__eglMustCastToProperFunctionPointerType)fake_presentation_time;
    return NULL;
}
EGLBoolean eglSwapBuffers(EGLDisplay d, EGLSurface s) {
    if (d != &display_token || s != &surface_token) return EGL_FALSE;
    if (lose_next_swap) {
        lose_next_swap = 0; last_error = EGL_CONTEXT_LOST; return EGL_FALSE;
    }
    swap_count++;
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    completion_times[swap_count % 256] = (int64_t)now.tv_sec * 1000000000LL + now.tv_nsec;
    return EGL_TRUE;
}
EGLBoolean eglTerminate(EGLDisplay d) { return d == &display_token; }
EGLint eglGetError(void) { EGLint result = last_error; last_error = EGL_SUCCESS; return result; }
const GLubyte *glGetString(unsigned name) {
    static const GLubyte version[] = "OpenGL ES 3.2 Lucent Fake";
    return name == GL_VERSION ? version : NULL;
}
void glGenTextures(GLsizei count, GLuint *textures) {
    if (count > 0 && textures) textures[0] = 41;
}
void glBindTexture(GLenum target, GLuint texture) { (void)target; (void)texture; }
void glTexParameteri(GLenum target, GLenum name, GLint value) {
    (void)target; (void)name; (void)value;
}
void glTexImage2D(GLenum target, GLint level, GLint internal_format,
                  GLsizei width, GLsizei height, GLint border,
                  GLenum format, GLenum type, const void *pixels) {
    (void)target; (void)level; (void)internal_format;
    (void)border; (void)format; (void)type; (void)pixels;
    texture_width = width;
    texture_height = height;
}
void glViewport(GLint x, GLint y, GLsizei width, GLsizei height) {
    viewport[0] = x; viewport[1] = y;
    viewport[2] = width; viewport[3] = height;
}
void glClearColor(GLfloat red, GLfloat green, GLfloat blue, GLfloat alpha) {
    clear_color[0] = red; clear_color[1] = green;
    clear_color[2] = blue; clear_color[3] = alpha;
}
void glClear(GLbitfield mask) {
    if ((mask & GL_COLOR_BUFFER_BIT) && !color_mask[0] && !color_mask[1] &&
            !color_mask[2] && color_mask[3] && clear_color[3] == 1.0f &&
            !scissor_enabled) opaque_alpha_clear_count++;
}
void glGetFloatv(GLenum name, GLfloat *values) {
    if (name == GL_COLOR_CLEAR_VALUE && values)
        memcpy(values, clear_color, sizeof(clear_color));
}
void glGetBooleanv(GLenum name, GLboolean *values) {
    if (name == GL_COLOR_WRITEMASK && values)
        memcpy(values, color_mask, sizeof(color_mask));
}
void glGetIntegerv(GLenum name, GLint *values) {
    if (name == GL_VIEWPORT && values)
        memcpy(values, viewport, sizeof(viewport));
    if (name == GL_READ_FRAMEBUFFER_BINDING && values)
        *values = (GLint)bound_read_framebuffer;
    if (name == GL_DRAW_FRAMEBUFFER_BINDING && values)
        *values = (GLint)bound_framebuffer;
}
GLboolean glIsEnabled(GLenum capability) {
    return capability == GL_SCISSOR_TEST ? scissor_enabled : GL_FALSE;
}
void glDisable(GLenum capability) {
    if (capability == GL_SCISSOR_TEST) scissor_enabled = GL_FALSE;
}
void glEnable(GLenum capability) {
    if (capability == GL_SCISSOR_TEST) scissor_enabled = GL_TRUE;
}
void glColorMask(GLboolean red, GLboolean green, GLboolean blue,
                 GLboolean alpha) {
    color_mask[0] = red; color_mask[1] = green;
    color_mask[2] = blue; color_mask[3] = alpha;
}
void glReadPixels(GLint x, GLint y, GLsizei width, GLsizei height,
                  GLenum format, GLenum type, void *pixels) {
    GLubyte *value = (GLubyte *)pixels;
    GLsizei row;
    GLsizei column;
    (void)format; (void)type;
    if (width > 1 || height > 1) ++bounds_readbacks;
    for (row = 0; row < height; ++row) {
        for (column = 0; column < width; ++column) {
            GLubyte *pixel = value + ((size_t)row * (size_t)width +
                    (size_t)column) * 4u;
            bool sentinel = sentinel_bounds_enabled &&
                    (x + column < sentinel_left || x + column >= sentinel_right ||
                     y + row < sentinel_bottom || y + row >= sentinel_top);
            bool black_band = sentinel_bounds_enabled >= 2 && !sentinel &&
                    (x + column < 140 || x + column >= 1300 ||
                     y + row < 100 || y + row >= 980);
            bool filtered_edge_noise = black_band &&
                    (x + column == 100 || x + column == 1339 ||
                     y + row == 50 || y + row == 1029);
            pixel[0] = sentinel ? 23 : (black_band ?
                    (filtered_edge_noise ? 2 : 0) : 64);
            pixel[1] = sentinel ? 179 : (black_band ?
                    (filtered_edge_noise ? 5 : 0) : 32);
            pixel[2] = sentinel ? 241 : (black_band ?
                    (filtered_edge_noise ? 2 : 0) : 16);
            pixel[3] = 255;
        }
    }
}
void glDeleteTextures(GLsizei count, const GLuint *textures) {
    (void)count; (void)textures;
}
void glGenFramebuffers(GLsizei count, GLuint *framebuffers) {
    if (count > 0 && framebuffers) framebuffers[0] = 42;
}
void glBindFramebuffer(GLenum target, GLuint framebuffer) {
    if (target == GL_FRAMEBUFFER || target == GL_DRAW_FRAMEBUFFER)
        bound_framebuffer = framebuffer;
    if (target == GL_FRAMEBUFFER || target == GL_READ_FRAMEBUFFER)
        bound_read_framebuffer = framebuffer;
}
void glFramebufferTexture2D(GLenum target, GLenum attachment,
                            GLenum texture_target, GLuint texture,
                            GLint level) {
    (void)target; (void)attachment; (void)texture_target;
    (void)texture; (void)level;
}
GLenum glCheckFramebufferStatus(GLenum target) {
    (void)target; return GL_FRAMEBUFFER_COMPLETE;
}
GLenum glGetError(void) { return GL_NO_ERROR; }
void glDeleteFramebuffers(GLsizei count, const GLuint *framebuffers) {
    (void)count; (void)framebuffers;
}
void glGenRenderbuffers(GLsizei count, GLuint *renderbuffers) {
    if (count > 0 && renderbuffers) renderbuffers[0] = 43;
}
void glBindRenderbuffer(GLenum target, GLuint renderbuffer) {
    (void)target; (void)renderbuffer;
}
void glRenderbufferStorage(GLenum target, GLenum format,
                           GLsizei width, GLsizei height) {
    (void)target; (void)format; (void)width; (void)height;
}
void glFramebufferRenderbuffer(GLenum target, GLenum attachment,
                               GLenum renderbuffer_target,
                               GLuint renderbuffer) {
    (void)target; (void)attachment; (void)renderbuffer_target;
    (void)renderbuffer;
}
void glDeleteRenderbuffers(GLsizei count, const GLuint *renderbuffers) {
    (void)count; (void)renderbuffers;
}
void glBlitFramebuffer(GLint source_x0, GLint source_y0,
                       GLint source_x1, GLint source_y1,
                       GLint destination_x0, GLint destination_y0,
                       GLint destination_x1, GLint destination_y1,
                       unsigned mask, GLenum filter) {
    previous_blit_source_x0 = last_blit_source_x0;
    previous_blit_source_y0 = last_blit_source_y0;
    previous_blit_source_x1 = last_blit_source_x1;
    previous_blit_source_y1 = last_blit_source_y1;
    last_blit_source_x0 = source_x0;
    last_blit_source_y0 = source_y0;
    last_blit_source_x1 = source_x1;
    last_blit_source_y1 = source_y1;
    last_blit_destination_x0 = destination_x0;
    last_blit_destination_y0 = destination_y0;
    last_blit_destination_x1 = destination_x1;
    last_blit_destination_y1 = destination_y1;
    (void)mask; (void)filter; blit_count++;
}
void ANativeWindow_acquire(ANativeWindow *window) { if (window) acquire_count++; }
void ANativeWindow_release(ANativeWindow *window) { if (window) release_count++; }
int ANativeWindow_setBuffersGeometry(ANativeWindow *window, int width,
                                     int height, int format) {
    (void)width; (void)height; (void)format; return window ? 0 : -1;
}
int32_t ANativeWindow_getWidth(ANativeWindow *window) {
    (void)window;
    return fake_window_width;
}
int32_t ANativeWindow_getHeight(ANativeWindow *window) {
    (void)window;
    return fake_window_height;
}
void lucent_fake_window_set_size(int32_t width, int32_t height) {
    fake_window_width = width;
    fake_window_height = height;
}
void lucent_fake_egl_lose_next_swap(void) { lose_next_swap = 1; }
unsigned lucent_fake_egl_swap_count(void) { return swap_count; }
unsigned lucent_fake_egl_presentation_time_count(void) {
    return presentation_time_count;
}
int64_t lucent_fake_egl_presentation_time_last(void) {
    return presentation_time_last;
}
int64_t lucent_fake_egl_presentation_time_delta(void) {
    return presentation_time_last - presentation_time_previous;
}
unsigned lucent_fake_gles_blit_count(void) { return blit_count; }
unsigned lucent_fake_gles_opaque_alpha_clear_count(void) {
    return opaque_alpha_clear_count;
}
int lucent_fake_gles_last_blit_source_x1(void) { return last_blit_source_x1; }
int lucent_fake_gles_last_blit_source_y1(void) { return last_blit_source_y1; }
int lucent_fake_gles_last_blit_source_x0(void) { return last_blit_source_x0; }
int lucent_fake_gles_last_blit_source_y0(void) { return last_blit_source_y0; }
int lucent_fake_gles_previous_blit_source_x0(void) {
    return previous_blit_source_x0;
}
int lucent_fake_gles_previous_blit_source_y0(void) {
    return previous_blit_source_y0;
}
int lucent_fake_gles_previous_blit_source_x1(void) {
    return previous_blit_source_x1;
}
int lucent_fake_gles_previous_blit_source_y1(void) {
    return previous_blit_source_y1;
}
int lucent_fake_gles_last_blit_destination_x0(void) {
    return last_blit_destination_x0;
}
int lucent_fake_gles_last_blit_destination_y0(void) {
    return last_blit_destination_y0;
}
int lucent_fake_gles_last_blit_destination_x1(void) {
    return last_blit_destination_x1;
}
int lucent_fake_gles_last_blit_destination_y1(void) {
    return last_blit_destination_y1;
}
void lucent_fake_gles_set_scissor_enabled(int enabled) {
    scissor_enabled = enabled ? GL_TRUE : GL_FALSE;
}
int lucent_fake_gles_scissor_enabled(void) { return scissor_enabled == GL_TRUE; }
unsigned lucent_fake_gles_bound_framebuffer(void) { return bound_framebuffer; }
void lucent_fake_gles_set_viewport(GLint x, GLint y, GLsizei width,
                                   GLsizei height) {
    glViewport(x, y, width, height);
}
void lucent_fake_gles_set_sentinel_bounds(int enabled) {
    sentinel_bounds_enabled = enabled;
    sentinel_left = 100; sentinel_bottom = 50;
    sentinel_right = 1340; sentinel_top = 1030;
}
void lucent_fake_gles_set_written_rect(int left, int bottom, int right, int top) {
    sentinel_left = left; sentinel_bottom = bottom;
    sentinel_right = right; sentinel_top = top;
}
unsigned lucent_fake_window_acquire_count(void) { return acquire_count; }
unsigned lucent_fake_window_release_count(void) { return release_count; }
