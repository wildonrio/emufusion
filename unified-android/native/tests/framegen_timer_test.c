#include <assert.h>
#include <jni.h>
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#include <stdint.h>
#include <string.h>
typedef unsigned int GLbitfield;
typedef unsigned char GLboolean;

#ifndef EGL_BAD_ACCESS
#define EGL_BAD_ACCESS 0x3002
#endif

static const char *extensions = "GL_EXT_disjoint_timer_query GL_EXT_occlusion_query_boolean";
static const char *version = "OpenGL ES 3.2 Fake";
static int omit_symbol;
static GLuint next_query = 1;
static GLenum error_value;
static EGLint egl_error_value = EGL_SUCCESS;
static GLenum begin_error_value;
static GLenum availability_error_value;
static GLenum result_error_value;
static int began;
static int ended;
static int deleted;
static uint64_t elapsed_value = UINT64_C(0x100000001);
static GLuint held_query;
static int self_test_pending;
static unsigned char proof_bytes[49152];
static GLenum proof_wait = 0x911A;
static int proof_map_null;
static int proof_unmap_ok = 1;
static GLenum proof_bind_error_value;
static EGLContext current_context = (EGLContext)(uintptr_t)0x1234;
static EGLDisplay current_display = (EGLDisplay)(uintptr_t)0x5678;
static EGLSurface current_surface = (EGLSurface)(uintptr_t)0x9abc;
static const char *egl_extensions =
        "EGL_KHR_fence_sync EGL_ANDROID_get_frame_timestamps";
static int frame_timestamp_supported = 1;
static int timestamps_enabled;
static uint64_t next_frame_id = 1;
static int64_t physical_present_ns = -2;
static EGLint physical_timestamp_error = EGL_SUCCESS;
static int physical_timestamp_scripted;
static int64_t physical_present_by_id[128];
static EGLint physical_error_by_id[128];
static unsigned ready_timestamp_supported_mask;
static int64_t ready_timestamp_values[4] = {-1, -1, -1, -1};
static EGLint ready_timestamp_error = EGL_SUCCESS;
static int ready_timestamp_query_count;
static int compositor_supported = 1, compositor_ok = 1, compositor_missing;
static EGLint compositor_error = EGL_SUCCESS;
static int64_t compositor_values[3] = {1000000000, 8333333, 10000000};
static EGLBoolean fake_compositor_supported(EGLDisplay d, EGLSurface s, EGLint name) {
    (void)d; (void)s; assert(name >= 0x3431 && name <= 0x3433);
    return compositor_supported;
}
static EGLBoolean fake_compositor_query(EGLDisplay d, EGLSurface s, EGLint count,
        const EGLint *names, int64_t *values) {
    (void)d; (void)s; assert(count == 3);
    for (int i = 0; i < count; ++i) {
        assert(names[i] == 0x3431 + i); values[i] = compositor_values[i];
    }
    egl_error_value = compositor_error;
    return compositor_ok;
}
EGLDisplay eglGetCurrentDisplay(void) { return (EGLDisplay)(uintptr_t)0x5678; }
EGLSurface eglGetCurrentSurface(EGLint which) {
    (void)which; return current_surface;
}
const char *eglQueryString(EGLDisplay display, EGLint name) {
    (void)display; (void)name; return egl_extensions;
}
EGLint eglGetError(void) {
    EGLint value = egl_error_value;
    egl_error_value = EGL_SUCCESS;
    return value;
}
EGLBoolean eglSurfaceAttrib(EGLDisplay display, EGLSurface surface,
        EGLint attribute, EGLint value) {
    assert(display == current_display && surface == current_surface &&
            attribute == 0x3430 && (value == EGL_TRUE || value == EGL_FALSE));
    timestamps_enabled = value == EGL_TRUE;
    return EGL_TRUE;
}
static EGLBoolean fake_next_frame_id(EGLDisplay display, EGLSurface surface,
        uint64_t *frame_id) {
    assert(display == current_display && surface == current_surface && frame_id);
    *frame_id = next_frame_id++;
    return EGL_TRUE;
}
static EGLBoolean fake_timestamp_supported(EGLDisplay display,
        EGLSurface surface, EGLint timestamp) {
    assert(display == current_display && surface == current_surface);
    if (timestamp == 0x343A)
        return frame_timestamp_supported ? EGL_TRUE : EGL_FALSE;
    int index = timestamp == 0x3435 ? 0 : timestamp == 0x3436 ? 1 :
            timestamp == 0x3437 ? 2 : timestamp == 0x3439 ? 3 : -1;
    assert(index >= 0);
    return (ready_timestamp_supported_mask & (1U << index)) ? EGL_TRUE : EGL_FALSE;
}
static EGLBoolean fake_frame_timestamps(EGLDisplay display, EGLSurface surface,
        uint64_t frame_id, EGLint count, const EGLint *timestamps,
        int64_t *values) {
    assert(display == current_display && surface == current_surface &&
            frame_id > 0 && count > 0 && count <= 4 && timestamps && values && timestamps_enabled);
    if (timestamps[0] != 0x343A) {
        ++ready_timestamp_query_count;
        if (ready_timestamp_error != EGL_SUCCESS) {
            egl_error_value = ready_timestamp_error;
            ready_timestamp_error = EGL_SUCCESS;
            return EGL_FALSE;
        }
        for (int i = 0; i < count; ++i) {
            int index = timestamps[i] == 0x3435 ? 0 : timestamps[i] == 0x3436 ? 1 :
                    timestamps[i] == 0x3437 ? 2 : timestamps[i] == 0x3439 ? 3 : -1;
            assert(index >= 0 && (ready_timestamp_supported_mask & (1U << index)));
            values[i] = ready_timestamp_values[index];
        }
        return EGL_TRUE;
    }
    assert(count == 1);
    if (physical_timestamp_scripted) {
        assert(frame_id < 128);
        if (physical_error_by_id[frame_id] != EGL_SUCCESS) {
            egl_error_value = physical_error_by_id[frame_id];
            physical_error_by_id[frame_id] = EGL_SUCCESS;
            return EGL_FALSE;
        }
        values[0] = physical_present_by_id[frame_id];
        return EGL_TRUE;
    }
    if (physical_timestamp_error != EGL_SUCCESS) {
        egl_error_value = physical_timestamp_error;
        physical_timestamp_error = EGL_SUCCESS;
        return EGL_FALSE;
    }
    values[0] = physical_present_ns;
    return EGL_TRUE;
}
void glReadPixels(GLint x, GLint y, GLsizei width, GLsizei height,
        GLenum format, GLenum type, void *pixels) {
    (void)x; (void)y; (void)width; (void)height; (void)format; (void)type; (void)pixels;
    for (int i = 0; i < 49152; ++i) proof_bytes[i] = (unsigned char)(i * 17 + 3);
}
void glFlush(void) {}
void glPixelStorei(GLenum name, GLint value) { (void)name; (void)value; }
static void fake_bind_buffer(GLenum target, GLuint buffer) {
    assert(target == 0x88EB); (void)buffer;
    if (proof_bind_error_value) error_value = proof_bind_error_value;
}
static void fake_buffer_data(GLenum target, intptr_t size, const void *data,
        GLenum usage) {
    assert(target == 0x88EB && size == 49152 && data == NULL && usage == 0x88E1);
}
static void *fake_fence_sync(GLenum condition, GLbitfield flags) {
    assert(condition == 0x9117 && flags == 0); return (void *)(uintptr_t)0x7777;
}
static GLenum fake_client_wait(void *sync, GLbitfield flags, uint64_t timeout) {
    assert(sync && flags == 0 && timeout == 0); return proof_wait;
}
static void fake_delete_sync(void *sync) { assert(sync != NULL); }
static void *fake_map_buffer(GLenum target, intptr_t offset, intptr_t length,
        GLbitfield access) {
    assert(target == 0x88EB && offset == 0 && length == 49152 && access == 1);
    return proof_map_null ? NULL : proof_bytes;
}
static GLboolean fake_unmap_buffer(GLenum target) {
    assert(target == 0x88EB); return proof_unmap_ok;
}

static void fake_gen(GLsizei count, GLuint *queries) {
    for (int i = 0; i < count; ++i) queries[i] = next_query++;
    if (count == 4) self_test_pending = 1;
}
static void fake_delete(GLsizei count, const GLuint *queries) {
    (void)queries; deleted += count;
}
static void fake_begin(GLenum target, GLuint query) {
    assert(target == 0x88BF || target == 0x8C2F); assert(query != 0); ++began;
    if (begin_error_value) error_value = begin_error_value;
}
static void fake_end(GLenum target) { assert(target == 0x88BF || target == 0x8C2F); ++ended; }
static void fake_get(GLuint query, GLenum name, GLuint *value) {
    *value = name == 0x8867 ? (query == held_query ? 0 : 1) :
            (self_test_pending ? 0 : (query == held_query ? 0 : (query & 1u)));
    if (name != 0x8867 && self_test_pending) self_test_pending = 0;
    if (availability_error_value) error_value = availability_error_value;
}
static void fake_get64(GLuint query, GLenum name, uint64_t *value) {
    (void)query; (void)name; *value = elapsed_value;
    if (result_error_value) error_value = result_error_value;
}

const GLubyte *glGetString(GLenum name) {
    assert(name == GL_EXTENSIONS || name == GL_VERSION);
    return (const GLubyte *)(name == GL_VERSION ? version : extensions);
}
GLenum glGetError(void) { GLenum value = error_value; error_value = 0; return value; }
void glGetIntegerv(GLenum name, GLint *value) { (void)name; *value = 0; }
EGLContext eglGetCurrentContext(void) { return current_context; }
__eglMustCastToProperFunctionPointerType eglGetProcAddress(const char *name) {
    if (!strcmp(name, "eglGetCompositorTimingSupportedANDROID"))
        return compositor_missing ? NULL : (__eglMustCastToProperFunctionPointerType)fake_compositor_supported;
    if (!strcmp(name, "eglGetCompositorTimingANDROID"))
        return compositor_missing ? NULL : (__eglMustCastToProperFunctionPointerType)fake_compositor_query;
    if (omit_symbol && (!strcmp(name, "glGetQueryObjectuivEXT") ||
            !strcmp(name, "glGetQueryObjectui64vEXT"))) return NULL;
    if (!strcmp(name, "glGenQueriesEXT")) return (__eglMustCastToProperFunctionPointerType)fake_gen;
    if (!strcmp(name, "glDeleteQueriesEXT")) return (__eglMustCastToProperFunctionPointerType)fake_delete;
    if (!strcmp(name, "glBeginQueryEXT")) return (__eglMustCastToProperFunctionPointerType)fake_begin;
    if (!strcmp(name, "glEndQueryEXT")) return (__eglMustCastToProperFunctionPointerType)fake_end;
    if (!strcmp(name, "glGetQueryObjectuivEXT")) return (__eglMustCastToProperFunctionPointerType)fake_get;
    if (!strcmp(name, "glGetQueryObjectui64vEXT")) return (__eglMustCastToProperFunctionPointerType)fake_get64;
    if (!strcmp(name, "glGenQueries")) return (__eglMustCastToProperFunctionPointerType)fake_gen;
    if (!strcmp(name, "glDeleteQueries")) return (__eglMustCastToProperFunctionPointerType)fake_delete;
    if (!strcmp(name, "glBeginQuery")) return (__eglMustCastToProperFunctionPointerType)fake_begin;
    if (!strcmp(name, "glEndQuery")) return (__eglMustCastToProperFunctionPointerType)fake_end;
    if (!strcmp(name, "glGetQueryObjectuiv")) return (__eglMustCastToProperFunctionPointerType)fake_get;
    if (!strcmp(name, "glGenBuffers")) return (__eglMustCastToProperFunctionPointerType)fake_gen;
    if (!strcmp(name, "glDeleteBuffers")) return (__eglMustCastToProperFunctionPointerType)fake_delete;
    if (!strcmp(name, "glBindBuffer")) return (__eglMustCastToProperFunctionPointerType)fake_bind_buffer;
    if (!strcmp(name, "glBufferData")) return (__eglMustCastToProperFunctionPointerType)fake_buffer_data;
    if (!strcmp(name, "glFenceSync")) return (__eglMustCastToProperFunctionPointerType)fake_fence_sync;
    if (!strcmp(name, "glClientWaitSync")) return (__eglMustCastToProperFunctionPointerType)fake_client_wait;
    if (!strcmp(name, "glDeleteSync")) return (__eglMustCastToProperFunctionPointerType)fake_delete_sync;
    if (!strcmp(name, "glMapBufferRange")) return (__eglMustCastToProperFunctionPointerType)fake_map_buffer;
    if (!strcmp(name, "glUnmapBuffer")) return (__eglMustCastToProperFunctionPointerType)fake_unmap_buffer;
    if (!strcmp(name, "eglGetNextFrameIdANDROID"))
        return (__eglMustCastToProperFunctionPointerType)fake_next_frame_id;
    if (!strcmp(name, "eglGetFrameTimestampSupportedANDROID"))
        return (__eglMustCastToProperFunctionPointerType)fake_timestamp_supported;
    if (!strcmp(name, "eglGetFrameTimestampsANDROID"))
        return (__eglMustCastToProperFunctionPointerType)fake_frame_timestamps;
    return NULL;
}

jlong Java_com_thorium_preview_game_DenseGpuTimer_nativeCreate(JNIEnv *, jclass);
jboolean Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(JNIEnv *, jclass,
                                                                 jlong, jint, jlong);
jboolean Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(JNIEnv *, jclass, jlong);
void Java_com_thorium_preview_game_DenseGpuTimer_nativeDestroy(JNIEnv *, jclass, jlong);
void Java_com_thorium_preview_game_DenseGpuTimer_nativeDiscard(JNIEnv *, jclass, jlong);
int lucent_framegen_timer_poll_raw(jlong, jlong, jlong, jlong *, int);
int lucent_framegen_signature_begin_raw(jlong, int64_t);
int lucent_framegen_signature_end_raw(jlong);
int lucent_framegen_signature_poll_raw(jlong, int64_t, jlong *, int);
int lucent_framegen_proof_atlas_poll_raw(jlong, jlong, void *, int, jlong *, int);
jint Java_com_thorium_preview_game_DenseGpuTimer_nativeConfigureProofAtlas(
        JNIEnv *, jclass, jlong, jint, jint, jint, jint);
jint Java_com_thorium_preview_game_DenseGpuTimer_nativeProofAtlasCapability(
        JNIEnv *, jclass, jlong);
jint Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(
        JNIEnv *, jclass, jlong, jlong, jlong);
jint Java_com_thorium_preview_game_DenseGpuTimer_nativePendingProofAtlases(
        JNIEnv *, jclass, jlong);
jlong lucent_physical_present_create_raw(void);
int lucent_physical_present_next_raw(jlong, uint64_t *);
int lucent_physical_present_commit_raw(jlong, uint64_t, int, int64_t);
int lucent_physical_present_poll_raw(jlong, jlong *, int);
int lucent_physical_present_pending_raw(jlong);
int lucent_physical_present_ready_enabled_raw(jlong, int);
void lucent_physical_present_destroy_raw(jlong);
int lucent_physical_compositor_timing_raw(jlong, jlong *, int);

int main(void) {
    jlong timing_handle = lucent_physical_present_create_raw();
    assert(timing_handle);
    jlong timing[3] = {7, 8, 9};
    assert(lucent_physical_compositor_timing_raw(timing_handle, timing, 3));
    assert(timing[0] == 1000000000 && timing[1] == 8333333 && timing[2] == 10000000);
    for (int failure = 0; failure < 6; ++failure) {
        compositor_missing = failure == 0;
        compositor_supported = failure != 1;
        compositor_ok = failure != 2;
        compositor_error = failure == 3 ? EGL_BAD_ACCESS : EGL_SUCCESS;
        compositor_values[1] = failure == 4 ? -2 : 8333333;
        compositor_values[2] = failure == 5 ? INT64_MAX : 10000000;
        timing[0] = 7; timing[1] = 8; timing[2] = 9;
        assert(!lucent_physical_compositor_timing_raw(timing_handle, timing, 3));
        assert(timing[0] == 7 && timing[1] == 8 && timing[2] == 9);
    }
    compositor_values[2] = 10000000;
    assert(!lucent_physical_compositor_timing_raw(0, timing, 3));
    assert(!lucent_physical_compositor_timing_raw(timing_handle, timing, 2));
    lucent_physical_present_destroy_raw(timing_handle);
    enum { FIELDS = 12, CAPACITY = 97 * FIELDS };
    jlong rows[CAPACITY];
    /* Physical scanout accounting remains independent of dense qualification.
     * A queried-but-unswapped ID is never committed, pending is nonblocking,
     * compositor drops are explicit, and only strict monotonic scanout times
     * become READY results. */
    egl_extensions = "EGL_KHR_fence_sync";
    assert(lucent_physical_present_create_raw() == 0);
    egl_extensions = "EGL_KHR_fence_sync EGL_ANDROID_get_frame_timestamps";
    frame_timestamp_supported = 0;
    assert(lucent_physical_present_create_raw() == 0);
    frame_timestamp_supported = 1;
    assert(eglGetCurrentDisplay() == current_display);
    assert(eglGetCurrentSurface(0x3059) == current_surface);
    assert(eglGetCurrentContext() == (EGLContext)(uintptr_t)0x1234);
    assert(eglGetProcAddress("eglGetNextFrameIdANDROID") != NULL);
    assert(eglGetProcAddress("eglGetFrameTimestampSupportedANDROID") != NULL);
    assert(eglGetProcAddress("eglGetFrameTimestampsANDROID") != NULL);
    jlong physical = lucent_physical_present_create_raw();
    assert(physical != 0 && timestamps_enabled);
    uint64_t frame_id = 0;
    assert(lucent_physical_present_next_raw(physical, &frame_id) == 1 &&
            frame_id == 1);
    assert(lucent_physical_present_pending_raw(physical) == 0);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 2,
            8448000) == 1);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 2,
            8448000) == -4);
    assert(lucent_physical_present_pending_raw(physical) == 1);
    physical_present_ns = -2;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 0);
    physical_present_ns = 1000000000;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[0] == 1 && rows[1] == 1000000000 && rows[2] == 2 &&
            rows[3] == 8448000 && rows[4] == 0);
    assert(lucent_physical_present_next_raw(physical, &frame_id) == 1 &&
            frame_id == 2);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 1,
            8448000) == 1);
    physical_present_ns = -1;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 2);
    assert(rows[0] == 2 && rows[1] == -1);
    assert(lucent_physical_present_next_raw(physical, &frame_id) == 1 &&
            frame_id == 3);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 1,
            8448000) == 1);
    physical_timestamp_error = EGL_BAD_ACCESS;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 3);
    assert(rows[0] == 3 && rows[1] == 0 && rows[2] == 1 &&
            rows[3] == 8448000 && rows[4] == EGL_BAD_ACCESS);
    assert(lucent_physical_present_pending_raw(physical) == 0);
    assert(lucent_physical_present_next_raw(physical, &frame_id) == 1 &&
            frame_id == 4);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 1,
            8448000) == 1);
    physical_present_ns = 999999999;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == -6);
    current_context = (EGLContext)(uintptr_t)0x9999;
    assert(lucent_physical_present_next_raw(physical, &frame_id) == -2);
    current_context = (EGLContext)(uintptr_t)0x1234;
    lucent_physical_present_destroy_raw(physical);
    assert(!timestamps_enabled);

    /* Timestamp publication is not guaranteed to be ordered by frame ID. A
     * compositor-pending head must not hide already-terminal newer timestamps,
     * but a newer READY result also must not fabricate an outcome for the
     * older frame. Polling remains nonblocking and delivery remains ordered:
     * frame 2 is cached while frame 1 is pending, then frame 1 and cached frame
     * 2 are emitted in submission order once frame 1 becomes READY. */
    memset(physical_present_by_id, 0xff, sizeof(physical_present_by_id));
    for (int index = 0; index < 128; ++index)
        physical_error_by_id[index] = EGL_SUCCESS;
    physical_timestamp_scripted = 1;
    physical = lucent_physical_present_create_raw();
    assert(physical != 0 && timestamps_enabled);
    uint64_t scripted_ids[3];
    for (int index = 0; index < 3; ++index) {
        assert(lucent_physical_present_next_raw(physical,
                &scripted_ids[index]) == 1);
        assert(scripted_ids[index] < 128);
        assert(lucent_physical_present_commit_raw(physical,
                scripted_ids[index], 1, 8448000) == 1);
    }
    physical_present_by_id[scripted_ids[0]] = -2;
    physical_present_by_id[scripted_ids[1]] = 2000000000;
    physical_present_by_id[scripted_ids[2]] = -2;
    int scripted_result = lucent_physical_present_poll_raw(physical, rows,
            CAPACITY);
    assert(scripted_result == 0);
    assert(lucent_physical_present_pending_raw(physical) == 3);
    physical_present_by_id[scripted_ids[0]] = 1000000000;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[0] == (jlong)scripted_ids[0] &&
            rows[1] == 1000000000 && rows[4] == 2);
    assert(lucent_physical_present_pending_raw(physical) == 2);
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[0] == (jlong)scripted_ids[1] &&
            rows[1] == 2000000000 && rows[4] == 1);
    assert(lucent_physical_present_pending_raw(physical) == 1);
    physical_present_by_id[scripted_ids[2]] = 3000000000;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[0] == (jlong)scripted_ids[2] &&
            rows[1] == 3000000000 && rows[4] == 0);
    assert(lucent_physical_present_pending_raw(physical) == 0);
    lucent_physical_present_destroy_raw(physical);
    physical_timestamp_scripted = 0;
    assert(!timestamps_enabled);

    /* A head that really expires from the driver's finite timestamp history
     * is still retired honestly, after which a cached newer READY result is
     * delivered. */
    memset(physical_present_by_id, 0xff, sizeof(physical_present_by_id));
    for (int index = 0; index < 128; ++index)
        physical_error_by_id[index] = EGL_SUCCESS;
    physical_timestamp_scripted = 1;
    physical = lucent_physical_present_create_raw();
    assert(physical != 0 && timestamps_enabled);
    uint64_t expired_ids[2];
    for (int index = 0; index < 2; ++index) {
        assert(lucent_physical_present_next_raw(physical,
                &expired_ids[index]) == 1);
        assert(lucent_physical_present_commit_raw(physical,
                expired_ids[index], 1, 8448000) == 1);
    }
    physical_present_by_id[expired_ids[0]] = -2;
    physical_present_by_id[expired_ids[1]] = 4000000000;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 0);
    physical_error_by_id[expired_ids[0]] = EGL_BAD_ACCESS;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 3);
    assert(rows[0] == (jlong)expired_ids[0] && rows[1] == 0 &&
            rows[4] == EGL_BAD_ACCESS);
    assert(lucent_physical_present_pending_raw(physical) == 1);
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[0] == (jlong)expired_ids[1] &&
            rows[1] == 4000000000 && rows[4] == 0);
    assert(lucent_physical_present_pending_raw(physical) == 0);
    lucent_physical_present_destroy_raw(physical);
    physical_timestamp_scripted = 0;
    assert(!timestamps_enabled);

    physical = lucent_physical_present_create_raw();
    assert(physical != 0 && timestamps_enabled);
    for (int index = 0; index < 64; ++index) {
        assert(lucent_physical_present_next_raw(physical, &frame_id) == 1);
        assert(lucent_physical_present_commit_raw(physical, frame_id, 1,
                8448000) == 1);
    }
    assert(lucent_physical_present_next_raw(physical, &frame_id) == 1);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 1,
            8448000) == -5);
    assert(lucent_physical_present_pending_raw(physical) == 64);
    lucent_physical_present_destroy_raw(physical);
    assert(!timestamps_enabled);

    /* Optional ready times are exact-frame fields, never poll-time substitutes.
     * Unsupported/PENDING/error values cannot alter valid scanout cadence.
     * Off skips all optional per-frame queries even when supported. */
    ready_timestamp_supported_mask = 15;
    ready_timestamp_values[0] = 4996000000LL;
    ready_timestamp_values[1] = 4997000000LL;
    ready_timestamp_values[2] = 4997000000LL;
    ready_timestamp_values[3] = 0; /* Supported display-only composition. */
    physical = lucent_physical_present_create_raw();
    assert(physical != 0);
    assert(lucent_physical_present_next_raw(physical, &frame_id) == 1);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 2, 8333333) == 1);
    physical_present_ns = 5000000000LL;
    int optional_queries_before = ready_timestamp_query_count;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[5] == 15 && rows[6] == -1 && rows[9] == -1);
    assert(ready_timestamp_query_count == optional_queries_before);
    assert(lucent_physical_present_ready_enabled_raw(physical, 1));
    assert(lucent_physical_present_next_raw(physical, &frame_id) == 1);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 2, 8333333) == 1);
    physical_present_ns += 16666666;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[0] == (jlong)frame_id && rows[5] == 15 &&
            rows[6] == 4996000000LL && rows[7] == 4997000000LL &&
            rows[8] == 4997000000LL && rows[9] == 0);
    ready_timestamp_values[0] = -2;
    ready_timestamp_values[3] = -1;
    assert(lucent_physical_present_next_raw(physical, &frame_id) == 1);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 2, 8333333) == 1);
    physical_present_ns += 16666666;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[6] == -2 && rows[9] == -1 && rows[1] == physical_present_ns);
    ready_timestamp_error = EGL_BAD_ACCESS;
    assert(lucent_physical_present_next_raw(physical, &frame_id) == 1);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 2, 8333333) == 1);
    physical_present_ns += 16666666;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[6] == -1 && rows[9] == -1 && rows[1] == physical_present_ns);
    assert(eglGetError() == EGL_SUCCESS);
    assert(lucent_physical_present_ready_enabled_raw(physical, 0));
    optional_queries_before = ready_timestamp_query_count;
    assert(lucent_physical_present_next_raw(physical, &frame_id) == 1);
    assert(lucent_physical_present_commit_raw(physical, frame_id, 2, 8333333) == 1);
    physical_present_ns += 16666666;
    assert(lucent_physical_present_poll_raw(physical, rows, 5) == 1);
    assert(ready_timestamp_query_count == optional_queries_before);
    lucent_physical_present_destroy_raw(physical);
    for (unsigned mask = 0; mask < 16; ++mask) {
        ready_timestamp_supported_mask = mask;
        ready_timestamp_values[0] = 4996000000LL;
        ready_timestamp_values[1] = ready_timestamp_values[2] = 4997000000LL;
        ready_timestamp_values[3] = 0;
        physical = lucent_physical_present_create_raw();
        assert(physical != 0 && lucent_physical_present_ready_enabled_raw(physical, 1));
        assert(lucent_physical_present_next_raw(physical, &frame_id) == 1);
        assert(lucent_physical_present_commit_raw(physical, frame_id, 2, 8333333) == 1);
        assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
        assert(rows[5] == mask);
        for (int field = 0; field < 4; ++field)
            assert(rows[6 + field] == ((mask & (1U << field)) ?
                    ready_timestamp_values[field] : -1));
        lucent_physical_present_destroy_raw(physical);
    }

    /* Publication may arrive out of order. Optional readiness stays attached
     * to the same cached EGL ID, never the latest frame's values. */
    ready_timestamp_supported_mask = 15;
    physical_timestamp_scripted = 1;
    next_frame_id = 1;
    physical_error_by_id[1] = physical_error_by_id[2] = EGL_SUCCESS;
    physical_present_by_id[1] = -2;
    physical_present_by_id[2] = 6000000000LL;
    ready_timestamp_values[0] = 5996000000LL;
    ready_timestamp_values[1] = ready_timestamp_values[2] = 5997000000LL;
    physical = lucent_physical_present_create_raw();
    assert(physical != 0 && lucent_physical_present_ready_enabled_raw(physical, 1));
    for (int frame = 0; frame < 2; ++frame) {
        assert(lucent_physical_present_next_raw(physical, &frame_id) == 1);
        assert(lucent_physical_present_commit_raw(physical, frame_id, 2, 8333333) == 1);
    }
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 0);
    physical_present_by_id[1] = 5000000000LL;
    ready_timestamp_values[0] = 4996000000LL;
    ready_timestamp_values[1] = ready_timestamp_values[2] = 4997000000LL;
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[0] == 1 && rows[1] == 5000000000LL && rows[6] == 4996000000LL);
    assert(lucent_physical_present_poll_raw(physical, rows, CAPACITY) == 1);
    assert(rows[0] == 2 && rows[1] == 6000000000LL && rows[6] == 5996000000LL);
    lucent_physical_present_destroy_raw(physical);
    physical_timestamp_scripted = 0;
    ready_timestamp_supported_mask = 0;

    extensions = "GL_EXT_other";
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeCreate(NULL, NULL) == 0);
    extensions = "GL_EXT_disjoint_timer_query GL_EXT_occlusion_query_boolean";
    omit_symbol = 1;
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeCreate(NULL, NULL) == 0);
    omit_symbol = 0;
    /* ES3 core occlusion queries do not require the ES2 extension string. */
    extensions = "GL_EXT_disjoint_timer_query";
    jlong timer = Java_com_thorium_preview_game_DenseGpuTimer_nativeCreate(NULL, NULL);
    assert(timer != 0);
    assert(lucent_framegen_signature_poll_raw(timer, 0, rows, CAPACITY) == 0);
    assert(lucent_framegen_signature_begin_raw(timer, 1));
    assert(!lucent_framegen_signature_begin_raw(timer, 2));
    assert(lucent_framegen_signature_end_raw(timer));
    assert(lucent_framegen_signature_poll_raw(timer, 1, rows, CAPACITY) == 8);
    assert(rows[0] == 0 && rows[1] == 1 && rows[2] == 1 && rows[6] == 0);
    assert(lucent_framegen_signature_poll_raw(timer, 1, rows, CAPACITY) == 0);
    /* Exact equality produces zero samples; a changed signature produces one.
     * The fake uses query parity to model these two occlusion outcomes. */
    assert(lucent_framegen_signature_begin_raw(timer, 2));
    assert(lucent_framegen_signature_end_raw(timer));
    assert(lucent_framegen_signature_poll_raw(timer, 2, rows, CAPACITY) == 8);
    assert(rows[1] == 2 && rows[2] == 0);
    held_query = 99;
    for (int i = 0; i < 4; ++i) {
        assert(lucent_framegen_signature_begin_raw(timer, 10 + i));
        assert(lucent_framegen_signature_end_raw(timer));
    }
    assert(!lucent_framegen_signature_begin_raw(timer, 14));
    assert(lucent_framegen_signature_poll_raw(timer, 14, rows, CAPACITY) == 0);
    held_query = 0;
    Java_com_thorium_preview_game_DenseGpuTimer_nativeDiscard(NULL, NULL, timer);
    began = 0;
    ended = 0;
    /* A pre-existing error is drained and does not poison a valid begin. */
    error_value = 0x0502;
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 1, 1));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(NULL, NULL, timer));
    assert(began == 1 && ended == 1);
    assert(lucent_framegen_timer_poll_raw(timer, 1, 0, rows, CAPACITY) == FIELDS);
    assert(rows[0] == 0 && rows[3] == 1 && rows[4] == 1);
    /* A post-begin error ends the active query and leaves no orphan, so the
     * same ring slot can be used by the following successful query. */
    begin_error_value = 0x0502;
    assert(!Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 1, 2));
    begin_error_value = 0;
    assert(began == 2 && ended == 2);
    assert(!Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 0, 1));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 1, 3));
    assert(!Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 2, 1));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(NULL, NULL, timer));
    assert(began == 3 && ended == 3);
    int count = lucent_framegen_timer_poll_raw(timer, 7, 0, rows, CAPACITY);
    assert(count == FIELDS);
    assert(rows[0] == 0 && rows[3] == 1 && rows[4] == 3);
    assert((uint64_t)rows[8] == elapsed_value); /* proves no 32-bit wrap */
    assert(rows[9] == 4);
    assert(lucent_framegen_timer_poll_raw(timer, 7, 0, rows, 3) < 0);

    /* Availability may arrive out of submission order. Each result retains
     * its own stage/sequence and the unavailable query remains pending. */
    held_query = 3;
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 1, 4));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(NULL, NULL, timer));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 2, 4));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(NULL, NULL, timer));
    count = lucent_framegen_timer_poll_raw(timer, 4, 0, rows, CAPACITY);
    assert(count == FIELDS && rows[3] == 2 && rows[4] == 4);
    held_query = 0;
    count = lucent_framegen_timer_poll_raw(timer, 4, 0, rows, CAPACITY);
    assert(count == FIELDS && rows[3] == 1 && rows[4] == 4);

    /* Stale GL errors are drained; errors caused by each EXT accessor become
     * explicit diagnostic rows and are never accepted as timing samples. */
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 1, 5));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(NULL, NULL, timer));
    error_value = 0x0502;
    elapsed_value = 999;
    count = lucent_framegen_timer_poll_raw(timer, 5, 0, rows, CAPACITY);
    assert(count == FIELDS && rows[0] == 0 && rows[8] == 999);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 1, 6));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(NULL, NULL, timer));
    availability_error_value = 0x0502;
    count = lucent_framegen_timer_poll_raw(timer, 6, 0, rows, CAPACITY);
    assert(count == FIELDS && rows[0] == 3 && rows[1] >= 0 && rows[2] != 0);
    availability_error_value = 0;
    count = lucent_framegen_timer_poll_raw(timer, 6, 0, rows, CAPACITY);
    assert(count == FIELDS && rows[0] == 0);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 1, 7));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(NULL, NULL, timer));
    result_error_value = 0x0502;
    count = lucent_framegen_timer_poll_raw(timer, 7, 0, rows, CAPACITY);
    assert(count == FIELDS && rows[0] == 4 && rows[8] == 999);
    result_error_value = 0;
    count = lucent_framegen_timer_poll_raw(timer, 7, 0, rows, CAPACITY);
    assert(count == FIELDS && rows[0] == 0);

    /* Pending slots cannot be overwritten when the ring wraps. */
    for (int i = 0; i < 96; ++i) {
        assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
                timer, 1 + i % 6, 10 + i));
        assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(NULL, NULL, timer));
    }
    assert(!Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 1, 200));
    assert(lucent_framegen_timer_poll_raw(timer, 200, 200, rows, CAPACITY) ==
            96 * FIELDS);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            timer, 1, 201));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(NULL, NULL, timer));
    Java_com_thorium_preview_game_DenseGpuTimer_nativeDestroy(NULL, NULL, timer);
    /* A true->false->true qualification epoch cannot inherit an old delayed
     * result: destroying the first timer deletes its query namespace, and the
     * replacement starts with an empty ring and a caller-owned fresh sequence. */
    assert(deleted >= 96);
    jlong replacement = Java_com_thorium_preview_game_DenseGpuTimer_nativeCreate(
            NULL, NULL);
    assert(replacement != 0);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeConfigureProofAtlas(
            NULL, NULL, replacement, 192, 64, 49152, 4) == 15);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(
            NULL, NULL, replacement, 1, 101) == 0);
    unsigned char destination[49152] = {0};
    jlong proof_row[15] = {0};
    proof_wait = 0x911B; /* timeout retains oldest without mapping/deleting */
    assert(lucent_framegen_proof_atlas_poll_raw(replacement, 102, destination,
            sizeof(destination), proof_row, 15) == 0);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativePendingProofAtlases(
            NULL, NULL, replacement) == 1);
    proof_wait = 0x911A;
    /* An unrelated rendering error predating poll belongs to the producer,
     * not this accessor sequence, and must not poison a completed payload. */
    error_value = 0x0502;
    assert(lucent_framegen_proof_atlas_poll_raw(replacement, 103, destination,
            sizeof(destination), proof_row, 15) == 15);
    assert(proof_row[0] == 0 && proof_row[3] == 1 && proof_row[4] == 101 &&
            proof_row[5] == 49152 && proof_row[6] == 2 && proof_row[9] == 0 &&
            proof_row[10] == 0 && proof_row[11] == 49152 &&
            proof_row[12] == 49152 && proof_row[13] == 31 && proof_row[14] == 1);
    assert(!memcmp(destination, proof_bytes, sizeof(destination)));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeProofAtlasCapability(
            NULL, NULL, replacement) == 63);

    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(
            NULL, NULL, replacement, 1000, 103) == 0);
    proof_bind_error_value = 0x0502;
    assert(lucent_framegen_proof_atlas_poll_raw(replacement, 104, destination,
            sizeof(destination), proof_row, 15) == 15);
    assert(proof_row[0] == 2 && proof_row[9] == 4 && proof_row[10] == 0x0502);
    proof_bind_error_value = 0;

    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(
            NULL, NULL, replacement, 2, 104) == 0);
    proof_map_null = 1;
    assert(lucent_framegen_proof_atlas_poll_raw(replacement, 105, destination,
            sizeof(destination), proof_row, 15) == 15 && proof_row[0] == 6);
    proof_map_null = 0;
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(
            NULL, NULL, replacement, 3, 106) == 0);
    proof_unmap_ok = 0;
    assert(lucent_framegen_proof_atlas_poll_raw(replacement, 107, destination,
            sizeof(destination), proof_row, 15) == 15 && proof_row[0] == 7);
    proof_unmap_ok = 1;
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(
            NULL, NULL, replacement, 4, 108) == 0);
    proof_wait = 0x911D;
    assert(lucent_framegen_proof_atlas_poll_raw(replacement, 109, destination,
            sizeof(destination), proof_row, 15) == 15 && proof_row[0] == 5);
    proof_wait = 0x911A;

    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(
            NULL, NULL, replacement, 5, 110) == 0);
    current_context = (EGLContext)(uintptr_t)0x9999;
    assert(lucent_framegen_proof_atlas_poll_raw(replacement, 111, destination,
            sizeof(destination), proof_row, 15) == 15 && proof_row[0] == 1);
    /* Wrong-context poll must leave ownership pending; no GL deletion occurs. */
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativePendingProofAtlases(
            NULL, NULL, replacement) == 1);
    current_context = (EGLContext)(uintptr_t)0x1234;
    Java_com_thorium_preview_game_DenseGpuTimer_nativeDiscard(NULL, NULL, replacement);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeConfigureProofAtlas(
            NULL, NULL, replacement, 192, 64, 49152, 4) == 15);

    /* Two complete laps prove retirement preserves each slot's persistent
     * nonzero PBO instead of silently turning the fifth enqueue into PBO 0. */
    GLuint stable_pbos[4] = {0};
    for (int i = 0; i < 8; ++i) {
        assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(
                NULL, NULL, replacement, 20 + i, 120 + i) == 0);
        assert(lucent_framegen_proof_atlas_poll_raw(replacement, 121 + i,
                destination, sizeof(destination), proof_row, 15) == 15);
        assert(proof_row[0] == 0 && proof_row[2] != 0);
        int slot_index = (int)proof_row[1];
        assert(slot_index >= 0 && slot_index < 4);
        if (i < 4) stable_pbos[slot_index] = (GLuint)proof_row[2];
        else assert(stable_pbos[slot_index] == (GLuint)proof_row[2]);
        assert(Java_com_thorium_preview_game_DenseGpuTimer_nativePendingProofAtlases(
                NULL, NULL, replacement) == 0);
    }

    for (int i = 40; i <= 43; ++i)
        assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(
                NULL, NULL, replacement, i, 110 + i) == 0);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(
            NULL, NULL, replacement, 44, 154) == 3);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativePendingProofAtlases(
            NULL, NULL, replacement) == 4);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeProofAtlasCapability(
            NULL, NULL, replacement) == 63);
    Java_com_thorium_preview_game_DenseGpuTimer_nativeDiscard(NULL, NULL, replacement);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativePendingProofAtlases(
            NULL, NULL, replacement) == 0);
    memset(rows, 0, sizeof(rows));
    assert(lucent_framegen_timer_poll_raw(replacement, 0, 0, rows, CAPACITY) == 0);
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(NULL, NULL,
            replacement, 1, 1));
    assert(Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(NULL, NULL,
            replacement));
    assert(lucent_framegen_timer_poll_raw(replacement, 1, 0, rows,
            CAPACITY) == FIELDS);
    assert(rows[0] == 0 && rows[3] == 1 && rows[4] == 1);
    Java_com_thorium_preview_game_DenseGpuTimer_nativeDestroy(NULL, NULL,
            replacement);
    return 0;
}
