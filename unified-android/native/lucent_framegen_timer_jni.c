#include <jni.h>
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned int GLbitfield;
typedef unsigned char GLboolean;

/* The host sanitizer harness deliberately provides a minimal GLES2/EGL
 * surface. Keep extension ABI types explicit instead of depending on optional
 * platform gl2ext.h declarations. */
#ifndef GL_RGBA
#define GL_RGBA 0x1908
#endif
#ifndef GL_UNSIGNED_BYTE
#define GL_UNSIGNED_BYTE 0x1401
#endif
#ifndef GL_VERSION
#define GL_VERSION 0x1F02
#endif
#ifndef GL_PACK_ALIGNMENT
#define GL_PACK_ALIGNMENT 0x0D05
#endif
#ifndef EGL_EXTENSIONS
#define EGL_EXTENSIONS 0x3055
#endif
#ifndef EGL_DRAW
#define EGL_DRAW 0x3059
#endif
#ifndef EGL_TIMESTAMPS_ANDROID
#define EGL_TIMESTAMPS_ANDROID 0x3430
#endif
#ifndef EGL_DISPLAY_PRESENT_TIME_ANDROID
#define EGL_DISPLAY_PRESENT_TIME_ANDROID 0x343A
#endif
#ifndef EGL_RENDERING_COMPLETE_TIME_ANDROID
#define EGL_RENDERING_COMPLETE_TIME_ANDROID 0x3435
#define EGL_COMPOSITION_LATCH_TIME_ANDROID 0x3436
#define EGL_FIRST_COMPOSITION_START_TIME_ANDROID 0x3437
#define EGL_FIRST_COMPOSITION_GPU_FINISHED_TIME_ANDROID 0x3439
#endif
#ifndef EGL_BAD_ACCESS
#define EGL_BAD_ACCESS 0x3002
#endif
#define EGL_TIMESTAMP_PENDING_ANDROID ((int64_t)-2)
#define EGL_TIMESTAMP_INVALID_ANDROID ((int64_t)-1)
extern EGLDisplay eglGetCurrentDisplay(void);
extern EGLSurface eglGetCurrentSurface(EGLint);
extern const char *eglQueryString(EGLDisplay, EGLint);
extern EGLBoolean eglSurfaceAttrib(EGLDisplay, EGLSurface, EGLint, EGLint);
extern void glReadPixels(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void *);
extern void glFlush(void);
extern void glPixelStorei(GLenum, GLint);

#define GL_TIME_ELAPSED_EXT 0x88BF
#define GL_GPU_DISJOINT_EXT 0x8FBB
#define GL_QUERY_RESULT_EXT 0x8866
#define GL_QUERY_RESULT_AVAILABLE_EXT 0x8867
#define RING_SIZE 96
#define RESULT_FIELDS 12
#define STATUS_OK 0
#define STATUS_CONTEXT 1
#define STATUS_DISJOINT 2
#define STATUS_AVAILABILITY_GL_ERROR 3
#define STATUS_RESULT_GL_ERROR 4
#define STATUS_ELAPSED_OVERFLOW 5
#define STATUS_ZERO_ELAPSED 6
#define STATUS_DISJOINT_GL_ERROR 7
#define GL_ANY_SAMPLES_PASSED_EXT 0x8C2F
#define SIGNATURE_RING_SIZE 4
#define SIGNATURE_RESULT_FIELDS 8
#define SIGNATURE_CAP_CONTEXT 1
#define SIGNATURE_CAP_API 2
#define SIGNATURE_CAP_FUNCTIONS 4
#define SIGNATURE_CAP_QUERIES 8
#define SIGNATURE_CAP_SELF_TEST 16
#define SIGNATURE_CAP_READY 31
#define SIGNATURE_STATUS_CONTEXT 1
#define SIGNATURE_STATUS_AVAILABILITY_ERROR 2
#define SIGNATURE_STATUS_RESULT_ERROR 3
#define GL_PIXEL_PACK_BUFFER 0x88EB
#define GL_PIXEL_PACK_BUFFER_BINDING 0x88ED
#define GL_PACK_ROW_LENGTH 0x0D02
#define GL_PACK_SKIP_ROWS 0x0D03
#define GL_PACK_SKIP_PIXELS 0x0D04
#define GL_STREAM_READ 0x88E1
#define GL_MAP_READ_BIT 0x0001
#define GL_SYNC_GPU_COMMANDS_COMPLETE 0x9117
#define GL_ALREADY_SIGNALED 0x911A
#define GL_TIMEOUT_EXPIRED 0x911B
#define GL_CONDITION_SATISFIED 0x911C
#define GL_WAIT_FAILED 0x911D
#define PROOF_ATLAS_RING_MAX 4
#define PROOF_ATLAS_CAP_CONTEXT 1
#define PROOF_ATLAS_CAP_FUNCTIONS 2
#define PROOF_ATLAS_CAP_OBJECTS 4
#define PROOF_ATLAS_CAP_STATE_TEST 8
#define PROOF_ATLAS_CAP_ENQUEUE 16
#define PROOF_ATLAS_CAP_COMPLETE 32
#define PROOF_ATLAS_STATUS_OK 0
#define PROOF_ATLAS_STATUS_CONTEXT 1
#define PROOF_ATLAS_STATUS_GL_ERROR 2
#define PROOF_ATLAS_STATUS_RING_FULL 3
#define PROOF_ATLAS_STATUS_FENCE 4
#define PROOF_ATLAS_STATUS_WAIT 5
#define PROOF_ATLAS_STATUS_MAP 6
#define PROOF_ATLAS_STATUS_UNMAP 7
#define PROOF_ATLAS_RESULT_FIELDS 15
#define PROOF_ATLAS_POLL_STAGE_NONE 0
#define PROOF_ATLAS_POLL_STAGE_DRAIN 1
#define PROOF_ATLAS_POLL_STAGE_WAIT 2
#define PROOF_ATLAS_POLL_STAGE_GET_BINDING 3
#define PROOF_ATLAS_POLL_STAGE_BIND 4
#define PROOF_ATLAS_POLL_STAGE_MAP 5
#define PROOF_ATLAS_POLL_STAGE_UNMAP 6
#define PROOF_ATLAS_POLL_STAGE_RESTORE_BINDING 7
#define PHYSICAL_PRESENT_RING_SIZE 64
#define PHYSICAL_PRESENT_RESULT_FIELDS 10
#define PHYSICAL_READY_TIMESTAMP_COUNT 4
#define PHYSICAL_PRESENT_POLL_NONE 0
#define PHYSICAL_PRESENT_POLL_READY 1
#define PHYSICAL_PRESENT_POLL_DROPPED 2
#define PHYSICAL_PRESENT_POLL_UNAVAILABLE 3
#define PHYSICAL_PRESENT_STATUS_ARGUMENT -1
#define PHYSICAL_PRESENT_STATUS_CONTEXT -2
#define PHYSICAL_PRESENT_STATUS_EGL -3
#define PHYSICAL_PRESENT_STATUS_ORDER -4
#define PHYSICAL_PRESENT_STATUS_RING_FULL -5
#define PHYSICAL_PRESENT_STATUS_TIMESTAMP -6

typedef void (*gen_queries_fn)(GLsizei, GLuint *);
typedef void (*delete_queries_fn)(GLsizei, const GLuint *);
typedef void (*begin_query_fn)(GLenum, GLuint);
typedef void (*end_query_fn)(GLenum);
typedef void (*get_query_fn)(GLuint, GLenum, GLuint *);
typedef void (*get_query64_fn)(GLuint, GLenum, uint64_t *);
typedef void (*gen_buffers_fn)(GLsizei, GLuint *);
typedef void (*delete_buffers_fn)(GLsizei, const GLuint *);
typedef void (*bind_buffer_fn)(GLenum, GLuint);
typedef void (*buffer_data_fn)(GLenum, intptr_t, const void *, GLenum);
typedef void *(*fence_sync_fn)(GLenum, GLbitfield);
typedef GLenum (*client_wait_sync_fn)(void *, GLbitfield, uint64_t);
typedef void (*delete_sync_fn)(void *);
typedef void *(*map_buffer_range_fn)(GLenum, intptr_t, intptr_t, GLbitfield);
typedef GLboolean (*unmap_buffer_fn)(GLenum);
typedef EGLBoolean (*get_next_frame_id_fn)(EGLDisplay, EGLSurface, uint64_t *);
typedef EGLBoolean (*get_frame_timestamp_supported_fn)(EGLDisplay, EGLSurface,
        EGLint);
typedef EGLBoolean (*get_frame_timestamps_fn)(EGLDisplay, EGLSurface, uint64_t,
        EGLint, const EGLint *, int64_t *);
typedef struct signature_slot {
    GLuint query;
    int active;
    int pending;
    int64_t sequence;
} signature_slot;

typedef struct timer_slot {
    GLuint query;
    int stage;
    int active;
    int pending;
    int64_t sequence;
} timer_slot;

typedef struct proof_atlas_slot {
    GLuint pbo;
    void *fence;
    int pending;
    int64_t proof_sequence;
    int64_t present_ordinal;
} proof_atlas_slot;

typedef struct framegen_timer {
    EGLContext context;
    EGLDisplay display;
    gen_queries_fn gen;
    delete_queries_fn del;
    begin_query_fn begin;
    end_query_fn end;
    get_query_fn get;
    get_query64_fn get64;
    gen_queries_fn signature_gen;
    delete_queries_fn signature_del;
    begin_query_fn signature_begin;
    end_query_fn signature_end;
    get_query_fn signature_get;
    timer_slot slots[RING_SIZE];
    int cursor;
    int active_slot;
    int disjoint_count;
    int signature_supported;
    int signature_capability;
    int signature_cursor;
    int active_signature_slot;
    signature_slot signatures[SIGNATURE_RING_SIZE];
    gen_buffers_fn proof_gen_buffers;
    delete_buffers_fn proof_delete_buffers;
    bind_buffer_fn proof_bind_buffer;
    buffer_data_fn proof_buffer_data;
    fence_sync_fn proof_fence_sync;
    client_wait_sync_fn proof_client_wait_sync;
    delete_sync_fn proof_delete_sync;
    map_buffer_range_fn proof_map_buffer_range;
    unmap_buffer_fn proof_unmap_buffer;
    proof_atlas_slot proof_atlas[PROOF_ATLAS_RING_MAX];
    int proof_atlas_ring_size;
    int proof_atlas_cursor;
    int proof_atlas_width;
    int proof_atlas_height;
    int proof_atlas_bytes;
    int proof_atlas_capability;
} framegen_timer;

typedef struct physical_present_slot {
    uint64_t frame_id;
    int scans_per_output;
    int64_t panel_period_ns;
    int resolved_status;
    int64_t resolved_present_ns;
    EGLint resolved_error;
    int64_t ready_timestamps[PHYSICAL_READY_TIMESTAMP_COUNT];
} physical_present_slot;

typedef struct physical_present_tracker {
    EGLDisplay display;
    EGLSurface surface;
    EGLContext context;
    get_next_frame_id_fn next_frame_id;
    get_frame_timestamp_supported_fn timestamp_supported;
    get_frame_timestamps_fn frame_timestamps;
    physical_present_slot slots[PHYSICAL_PRESENT_RING_SIZE];
    int head;
    int count;
    int has_last_frame_id;
    uint64_t last_frame_id;
    int64_t last_present_ns;
    unsigned ready_timestamp_supported_mask;
    int collect_ready_timestamps;
} physical_present_tracker;

static const EGLint physical_ready_timestamp_names[PHYSICAL_READY_TIMESTAMP_COUNT] = {
    EGL_RENDERING_COMPLETE_TIME_ANDROID,
    EGL_COMPOSITION_LATCH_TIME_ANDROID,
    EGL_FIRST_COMPOSITION_START_TIME_ANDROID,
    EGL_FIRST_COMPOSITION_GPU_FINISHED_TIME_ANDROID
};

static int gles_major_version(void) {
    const char *version = (const char *)glGetString(GL_VERSION);
    int major = 0;
    return version && sscanf(version, "OpenGL ES %d", &major) == 1 ? major : 0;
}

static void *resolve_gl_symbol(const char *name) {
    __eglMustCastToProperFunctionPointerType address = eglGetProcAddress(name);
    void *result = NULL;
    if (address) memcpy(&result, &address, sizeof(result));
    if (!result) result = dlsym(RTLD_DEFAULT, name);
    return result;
}

static void *resolve_egl_symbol(const char *name) {
    __eglMustCastToProperFunctionPointerType address = eglGetProcAddress(name);
    void *result = NULL;
    if (address) memcpy(&result, &address, sizeof(result));
    if (!result) result = dlsym(RTLD_DEFAULT, name);
    return result;
}

static int has_extension(const char *list, const char *wanted) {
    size_t n = strlen(wanted);
    if (!list || !*wanted || strchr(wanted, ' ')) return 0;
    for (const char *p = list; (p = strstr(p, wanted)); p += n) {
        if ((p == list || p[-1] == ' ') && (p[n] == '\0' || p[n] == ' ')) return 1;
    }
    return 0;
}

static framegen_timer *from(jlong value) {
    return (framegen_timer *)(intptr_t)value;
}

static physical_present_tracker *physical_from(jlong value) {
    return (physical_present_tracker *)(intptr_t)value;
}

static int physical_context_matches(const physical_present_tracker *tracker) {
    return tracker && eglGetCurrentDisplay() == tracker->display &&
            eglGetCurrentSurface(EGL_DRAW) == tracker->surface &&
            eglGetCurrentContext() == tracker->context;
}

static int drain_egl_errors(void) {
    int count = 0;
    while (eglGetError() != EGL_SUCCESS) {
        if (++count == 32) return 0;
    }
    return 1;
}

static int drain_gl_errors(void) {
    int count = 0;
    while (glGetError() != GL_NO_ERROR) {
        if (++count == 32) return 0;
    }
    return 1;
}

int lucent_framegen_timer_poll_raw(jlong handle, jlong current_pair_sequence,
        jlong current_warp_sequence, jlong *rows, int capacity);
int lucent_framegen_signature_poll_raw(jlong handle, int64_t current_sequence,
        jlong *row, int capacity);
int lucent_framegen_signature_begin_raw(jlong handle, int64_t sequence);
int lucent_framegen_signature_end_raw(jlong handle);

static int write_result(jlong *rows, int capacity, int count, int status,
        int slot_index, const timer_slot *slot, jlong current_pair,
        jlong current_warp, GLuint available, uint64_t elapsed, jlong queue_age,
        int context_ok, int disjoint) {
    if (!rows || capacity - count < RESULT_FIELDS) return -1;
    rows[count++] = status;
    rows[count++] = slot_index;
    rows[count++] = slot ? slot->query : 0;
    rows[count++] = slot ? slot->stage : 0;
    rows[count++] = slot ? slot->sequence : 0;
    rows[count++] = current_pair;
    rows[count++] = current_warp;
    rows[count++] = available;
    rows[count++] = elapsed <= INT64_MAX ? (jlong)elapsed : -1;
    rows[count++] = queue_age;
    rows[count++] = context_ok;
    rows[count++] = disjoint;
    return count;
}

JNIEXPORT jlong JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeCreate(JNIEnv *env, jclass type) {
    (void)env; (void)type;
    EGLContext context = eglGetCurrentContext();
    if (context == EGL_NO_CONTEXT) return 0;
    const char *extensions = (const char *)glGetString(GL_EXTENSIONS);
    if (!has_extension(extensions, "GL_EXT_disjoint_timer_query")) return 0;
    framegen_timer *timer = calloc(1, sizeof(*timer));
    if (!timer) return 0;
    timer->context = context;
    timer->display = eglGetCurrentDisplay();
    timer->active_slot = -1;
    timer->active_signature_slot = -1;
    timer->gen = (gen_queries_fn)eglGetProcAddress("glGenQueriesEXT");
    timer->del = (delete_queries_fn)eglGetProcAddress("glDeleteQueriesEXT");
    timer->begin = (begin_query_fn)eglGetProcAddress("glBeginQueryEXT");
    timer->end = (end_query_fn)eglGetProcAddress("glEndQueryEXT");
    timer->get = (get_query_fn)eglGetProcAddress("glGetQueryObjectuivEXT");
    timer->get64 = (get_query64_fn)eglGetProcAddress("glGetQueryObjectui64vEXT");
    if (!timer->gen || !timer->del || !timer->begin || !timer->end || !timer->get ||
            !timer->get64) {
        free(timer); return 0;
    }
    GLuint queries[RING_SIZE] = {0};
    timer->gen(RING_SIZE, queries);
    for (int i = 0; i < RING_SIZE; ++i) {
        if (!queries[i]) {
            timer->del(RING_SIZE, queries); free(timer); return 0;
        }
        timer->slots[i].query = queries[i];
    }
    timer->signature_capability = SIGNATURE_CAP_CONTEXT;
    if (gles_major_version() >= 3) {
        timer->signature_gen = (gen_queries_fn)resolve_gl_symbol("glGenQueries");
        timer->signature_del = (delete_queries_fn)resolve_gl_symbol("glDeleteQueries");
        timer->signature_begin = (begin_query_fn)resolve_gl_symbol("glBeginQuery");
        timer->signature_end = (end_query_fn)resolve_gl_symbol("glEndQuery");
        timer->signature_get = (get_query_fn)resolve_gl_symbol("glGetQueryObjectuiv");
        timer->signature_capability |= SIGNATURE_CAP_API;
    } else if (has_extension(extensions, "GL_EXT_occlusion_query_boolean")) {
        timer->signature_gen = timer->gen;
        timer->signature_del = timer->del;
        timer->signature_begin = timer->begin;
        timer->signature_end = timer->end;
        timer->signature_get = timer->get;
        timer->signature_capability |= SIGNATURE_CAP_API;
    }
    if (timer->signature_gen && timer->signature_del && timer->signature_begin &&
            timer->signature_end && timer->signature_get) {
        timer->signature_capability |= SIGNATURE_CAP_FUNCTIONS;
        GLuint signature_queries[SIGNATURE_RING_SIZE] = {0};
        timer->signature_gen(SIGNATURE_RING_SIZE, signature_queries);
        int complete = 1;
        for (int i = 0; i < SIGNATURE_RING_SIZE; ++i) {
            timer->signatures[i].query = signature_queries[i];
            if (!signature_queries[i]) complete = 0;
        }
        if (complete) {
            GLuint empty_result = 1;
            timer->signature_capability |= SIGNATURE_CAP_QUERIES;
            if (drain_gl_errors()) {
                timer->signature_begin(GL_ANY_SAMPLES_PASSED_EXT,
                        signature_queries[0]);
                GLenum begin_error = glGetError();
                timer->signature_end(GL_ANY_SAMPLES_PASSED_EXT);
                GLenum end_error = glGetError();
                if (begin_error == GL_NO_ERROR && end_error == GL_NO_ERROR) {
                    timer->signature_get(signature_queries[0], GL_QUERY_RESULT_EXT,
                            &empty_result);
                    if (glGetError() == GL_NO_ERROR && empty_result == 0) {
                        timer->signature_capability |= SIGNATURE_CAP_SELF_TEST;
                        timer->signature_supported = 1;
                    }
                }
            }
            drain_gl_errors();
            if (!timer->signature_supported)
                timer->signature_del(SIGNATURE_RING_SIZE, signature_queries);
        } else {
            timer->signature_del(SIGNATURE_RING_SIZE, signature_queries);
        }
    }
    return (jlong)(intptr_t)timer;
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeSignatureSupported(JNIEnv *env,
        jclass type, jlong handle) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    return timer && timer->signature_supported &&
            eglGetCurrentContext() == timer->context ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeSignatureCapability(JNIEnv *env,
        jclass type, jlong handle) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    if (!timer) return 0;
    int capability = timer->signature_capability;
    if (eglGetCurrentContext() != timer->context)
        capability &= ~SIGNATURE_CAP_CONTEXT;
    return capability;
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeBeginSignature(JNIEnv *env,
        jclass type, jlong handle, jlong sequence) {
    (void)env; (void)type;
    return lucent_framegen_signature_begin_raw(handle, sequence) ? JNI_TRUE : JNI_FALSE;
}

int lucent_framegen_signature_begin_raw(jlong handle, int64_t sequence) {
    framegen_timer *timer = from(handle);
    if (!timer || !timer->signature_supported || sequence <= 0 ||
            timer->active_signature_slot >= 0 ||
            eglGetCurrentContext() != timer->context) return 0;
    signature_slot *slot = &timer->signatures[timer->signature_cursor];
    if (slot->pending || slot->active || !slot->query || !drain_gl_errors()) return 0;
    timer->signature_begin(GL_ANY_SAMPLES_PASSED_EXT, slot->query);
    if (glGetError() != GL_NO_ERROR) {
        timer->signature_end(GL_ANY_SAMPLES_PASSED_EXT);
        drain_gl_errors();
        return 0;
    }
    slot->active = 1;
    slot->sequence = sequence;
    timer->active_signature_slot = timer->signature_cursor;
    return 1;
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeEndSignature(JNIEnv *env,
        jclass type, jlong handle) {
    (void)env; (void)type;
    return lucent_framegen_signature_end_raw(handle) ? JNI_TRUE : JNI_FALSE;
}

int lucent_framegen_signature_end_raw(jlong handle) {
    framegen_timer *timer = from(handle);
    if (!timer || timer->active_signature_slot < 0 ||
            eglGetCurrentContext() != timer->context) return 0;
    int index = timer->active_signature_slot;
    signature_slot *slot = &timer->signatures[index];
    timer->signature_end(GL_ANY_SAMPLES_PASSED_EXT);
    timer->active_signature_slot = -1;
    slot->active = 0;
    if (glGetError() != GL_NO_ERROR) {
        drain_gl_errors();
        return 0;
    }
    slot->pending = 1;
    timer->signature_cursor = (timer->signature_cursor + 1) % SIGNATURE_RING_SIZE;
    return 1;
}

JNIEXPORT jlongArray JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativePollSignature(JNIEnv *env,
        jclass type, jlong handle, jlong current_sequence) {
    (void)type;
    jlong row[SIGNATURE_RESULT_FIELDS] = {0};
    int count = lucent_framegen_signature_poll_raw(handle, current_sequence,
            row, SIGNATURE_RESULT_FIELDS);
    if (count < 0) count = SIGNATURE_RESULT_FIELDS;
    jlongArray result = (*env)->NewLongArray(env, count);
    if (result && count) (*env)->SetLongArrayRegion(env, result, 0, count, row);
    return result;
}

int lucent_framegen_signature_poll_raw(jlong handle, int64_t current_sequence,
        jlong *row, int capacity) {
    framegen_timer *timer = from(handle);
    if (!row || capacity < SIGNATURE_RESULT_FIELDS) return -1;
    memset(row, 0, SIGNATURE_RESULT_FIELDS * sizeof(*row));
    if (!timer || !timer->signature_supported ||
            eglGetCurrentContext() != timer->context) {
        row[0] = SIGNATURE_STATUS_CONTEXT;
        row[7] = 1;
        return SIGNATURE_RESULT_FIELDS;
    }
    signature_slot *oldest = NULL;
    int oldest_index = -1;
    for (int i = 0; i < SIGNATURE_RING_SIZE; ++i) {
        signature_slot *slot = &timer->signatures[i];
        if (slot->pending && (!oldest || slot->sequence < oldest->sequence)) {
            oldest = slot;
            oldest_index = i;
        }
    }
    if (!oldest) return 0;
    if (!drain_gl_errors()) {
        row[0] = SIGNATURE_STATUS_AVAILABILITY_ERROR;
        row[1] = oldest->sequence;
        row[3] = oldest_index;
        row[4] = oldest->query;
        row[7] = 1;
        return SIGNATURE_RESULT_FIELDS;
    }
    GLuint available = 0;
    timer->signature_get(oldest->query, GL_QUERY_RESULT_AVAILABLE_EXT, &available);
    if (glGetError() != GL_NO_ERROR) {
        row[0] = SIGNATURE_STATUS_AVAILABILITY_ERROR;
        row[1] = oldest->sequence;
        row[3] = oldest_index;
        row[4] = oldest->query;
        row[7] = 1;
        return SIGNATURE_RESULT_FIELDS;
    }
    if (!available) return 0;
    GLuint unique = 0;
    timer->signature_get(oldest->query, GL_QUERY_RESULT_EXT, &unique);
    if (glGetError() != GL_NO_ERROR) {
        row[0] = SIGNATURE_STATUS_RESULT_ERROR;
        row[1] = oldest->sequence;
        row[3] = oldest_index;
        row[4] = oldest->query;
        row[5] = available;
        row[7] = 1;
        return SIGNATURE_RESULT_FIELDS;
    }
    row[0] = STATUS_OK;
    row[1] = oldest->sequence;
    row[2] = unique ? 1 : 0;
    row[3] = oldest_index;
    row[4] = oldest->query;
    row[5] = available;
    row[6] = current_sequence >= oldest->sequence ?
            current_sequence - oldest->sequence : -1;
    row[7] = 1;
    oldest->pending = 0;
    return SIGNATURE_RESULT_FIELDS;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativePendingSignatures(JNIEnv *env,
        jclass type, jlong handle) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    int count = 0;
    if (timer) for (int i = 0; i < SIGNATURE_RING_SIZE; ++i)
        count += timer->signatures[i].pending || timer->signatures[i].active;
    return count;
}

static void release_proof_atlas(framegen_timer *timer) {
    if (!timer || !timer->proof_atlas_ring_size) return;
    int current = eglGetCurrentContext() == timer->context;
    for (int i = 0; i < timer->proof_atlas_ring_size; ++i) {
        if (current && timer->proof_atlas[i].fence && timer->proof_delete_sync)
            timer->proof_delete_sync(timer->proof_atlas[i].fence);
        timer->proof_atlas[i].fence = NULL;
        timer->proof_atlas[i].pending = 0;
    }
    if (current && timer->proof_delete_buffers) {
        GLuint buffers[PROOF_ATLAS_RING_MAX] = {0};
        for (int i = 0; i < timer->proof_atlas_ring_size; ++i)
            buffers[i] = timer->proof_atlas[i].pbo;
        timer->proof_delete_buffers(timer->proof_atlas_ring_size, buffers);
    }
    memset(timer->proof_atlas, 0, sizeof(timer->proof_atlas));
    timer->proof_atlas_ring_size = 0;
    timer->proof_atlas_cursor = 0;
    timer->proof_atlas_capability = 0;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeConfigureProofAtlas(JNIEnv *env,
        jclass type, jlong handle, jint width, jint height, jint byte_count,
        jint ring_size) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    if (!timer || eglGetCurrentContext() != timer->context ||
            gles_major_version() < 3 || width <= 0 || height <= 0 ||
            byte_count <= 0 || ring_size != PROOF_ATLAS_RING_MAX ||
            (int64_t)width * height * 4 != byte_count) return 0;
    release_proof_atlas(timer);
    timer->proof_atlas_capability = PROOF_ATLAS_CAP_CONTEXT;
    timer->proof_gen_buffers = (gen_buffers_fn)resolve_gl_symbol("glGenBuffers");
    timer->proof_delete_buffers = (delete_buffers_fn)resolve_gl_symbol("glDeleteBuffers");
    timer->proof_bind_buffer = (bind_buffer_fn)resolve_gl_symbol("glBindBuffer");
    timer->proof_buffer_data = (buffer_data_fn)resolve_gl_symbol("glBufferData");
    timer->proof_fence_sync = (fence_sync_fn)resolve_gl_symbol("glFenceSync");
    timer->proof_client_wait_sync = (client_wait_sync_fn)resolve_gl_symbol("glClientWaitSync");
    timer->proof_delete_sync = (delete_sync_fn)resolve_gl_symbol("glDeleteSync");
    timer->proof_map_buffer_range = (map_buffer_range_fn)resolve_gl_symbol("glMapBufferRange");
    timer->proof_unmap_buffer = (unmap_buffer_fn)resolve_gl_symbol("glUnmapBuffer");
    if (!timer->proof_gen_buffers || !timer->proof_delete_buffers ||
            !timer->proof_bind_buffer || !timer->proof_buffer_data ||
            !timer->proof_fence_sync || !timer->proof_client_wait_sync ||
            !timer->proof_delete_sync || !timer->proof_map_buffer_range ||
            !timer->proof_unmap_buffer) return timer->proof_atlas_capability;
    timer->proof_atlas_capability |= PROOF_ATLAS_CAP_FUNCTIONS;
    GLuint buffers[PROOF_ATLAS_RING_MAX] = {0};
    timer->proof_gen_buffers(ring_size, buffers);
    if (glGetError() != GL_NO_ERROR) return timer->proof_atlas_capability;
    for (int i = 0; i < ring_size; ++i) {
        if (!buffers[i]) {
            timer->proof_delete_buffers(ring_size, buffers);
            return timer->proof_atlas_capability;
        }
        timer->proof_atlas[i].pbo = buffers[i];
    }
    /* From this point release_proof_atlas owns every generated object, even
     * when a later state/allocation check fails part-way through setup. */
    timer->proof_atlas_ring_size = ring_size;
    timer->proof_atlas_capability |= PROOF_ATLAS_CAP_OBJECTS;
    GLint old_binding = 0;
    glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING, &old_binding);
    if (glGetError() != GL_NO_ERROR) {
        int capability = timer->proof_atlas_capability;
        release_proof_atlas(timer);
        return capability;
    }
    for (int i = 0; i < ring_size; ++i) {
        timer->proof_bind_buffer(GL_PIXEL_PACK_BUFFER, buffers[i]);
        timer->proof_buffer_data(GL_PIXEL_PACK_BUFFER, byte_count, NULL, GL_STREAM_READ);
        if (glGetError() != GL_NO_ERROR) {
            timer->proof_bind_buffer(GL_PIXEL_PACK_BUFFER, (GLuint)old_binding);
            int capability = timer->proof_atlas_capability;
            release_proof_atlas(timer);
            return capability;
        }
    }
    timer->proof_bind_buffer(GL_PIXEL_PACK_BUFFER, (GLuint)old_binding);
    if (glGetError() != GL_NO_ERROR) {
        int capability = timer->proof_atlas_capability;
        release_proof_atlas(timer);
        return capability;
    }
    timer->proof_atlas_capability |= PROOF_ATLAS_CAP_STATE_TEST;
    timer->proof_atlas_width = width;
    timer->proof_atlas_height = height;
    timer->proof_atlas_bytes = byte_count;
    return timer->proof_atlas_capability;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeProofAtlasCapability(JNIEnv *env,
        jclass type, jlong handle) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    return timer ? timer->proof_atlas_capability : 0;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeEnqueueProofAtlas(JNIEnv *env,
        jclass type, jlong handle, jlong proof_sequence, jlong present_ordinal) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    if (!timer || eglGetCurrentContext() != timer->context ||
            timer->proof_atlas_capability < 15 || proof_sequence <= 0 ||
            present_ordinal <= 0) return PROOF_ATLAS_STATUS_CONTEXT;
    proof_atlas_slot *slot = &timer->proof_atlas[timer->proof_atlas_cursor];
    if (slot->pending || slot->fence) return PROOF_ATLAS_STATUS_RING_FULL;
    if (!drain_gl_errors()) return PROOF_ATLAS_STATUS_GL_ERROR;
    GLint old_binding = 0, old_alignment = 0, old_row_length = 0;
    GLint old_skip_rows = 0, old_skip_pixels = 0;
    glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING, &old_binding);
    glGetIntegerv(GL_PACK_ALIGNMENT, &old_alignment);
    glGetIntegerv(GL_PACK_ROW_LENGTH, &old_row_length);
    glGetIntegerv(GL_PACK_SKIP_ROWS, &old_skip_rows);
    glGetIntegerv(GL_PACK_SKIP_PIXELS, &old_skip_pixels);
    if (glGetError() != GL_NO_ERROR) return PROOF_ATLAS_STATUS_GL_ERROR;
    timer->proof_bind_buffer(GL_PIXEL_PACK_BUFFER, slot->pbo);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glPixelStorei(GL_PACK_ROW_LENGTH, 0);
    glPixelStorei(GL_PACK_SKIP_ROWS, 0);
    glPixelStorei(GL_PACK_SKIP_PIXELS, 0);
    glReadPixels(0, 0, timer->proof_atlas_width, timer->proof_atlas_height,
            GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    void *fence = timer->proof_fence_sync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
    glPixelStorei(GL_PACK_ALIGNMENT, old_alignment);
    glPixelStorei(GL_PACK_ROW_LENGTH, old_row_length);
    glPixelStorei(GL_PACK_SKIP_ROWS, old_skip_rows);
    glPixelStorei(GL_PACK_SKIP_PIXELS, old_skip_pixels);
    timer->proof_bind_buffer(GL_PIXEL_PACK_BUFFER, (GLuint)old_binding);
    if (glGetError() != GL_NO_ERROR || !fence) {
        if (fence) timer->proof_delete_sync(fence);
        return fence ? PROOF_ATLAS_STATUS_GL_ERROR : PROOF_ATLAS_STATUS_FENCE;
    }
    glFlush();
    slot->fence = fence;
    slot->pending = 1;
    slot->proof_sequence = proof_sequence;
    slot->present_ordinal = present_ordinal;
    timer->proof_atlas_capability |= PROOF_ATLAS_CAP_ENQUEUE;
    timer->proof_atlas_cursor =
            (timer->proof_atlas_cursor + 1) % timer->proof_atlas_ring_size;
    return PROOF_ATLAS_STATUS_OK;
}

int lucent_framegen_proof_atlas_poll_raw(jlong handle,
        jlong current_present_ordinal, void *destination,
        int destination_capacity, jlong *row, int row_capacity) {
    framegen_timer *timer = from(handle);
    if (!row || row_capacity < PROOF_ATLAS_RESULT_FIELDS) return -1;
    memset(row, 0, sizeof(jlong) * PROOF_ATLAS_RESULT_FIELDS);
    proof_atlas_slot *oldest = NULL;
    int oldest_index = -1;
    if (timer) for (int i = 0; i < timer->proof_atlas_ring_size; ++i) {
        proof_atlas_slot *slot = &timer->proof_atlas[i];
        if (slot->pending && (!oldest ||
                slot->proof_sequence < oldest->proof_sequence)) {
            oldest = slot; oldest_index = i;
        }
    }
    if (!oldest) return 0;
    row[1] = oldest_index;
    row[2] = oldest->pbo;
    row[3] = oldest->proof_sequence;
    row[4] = oldest->present_ordinal;
    row[5] = timer ? timer->proof_atlas_bytes : 0;
    row[6] = current_present_ordinal >= oldest->present_ordinal ?
            current_present_ordinal - oldest->present_ordinal : -1;
    row[8] = timer && eglGetCurrentContext() == timer->context;
    row[11] = destination_capacity;
    row[12] = timer ? timer->proof_atlas_bytes : 0;
    row[13] = timer ? timer->proof_atlas_capability : 0;
    if (timer) for (int i = 0; i < timer->proof_atlas_ring_size; ++i)
        if (timer->proof_atlas[i].pending) ++row[14];
    if (!timer || !row[8]) row[0] = PROOF_ATLAS_STATUS_CONTEXT;
    else if (!drain_gl_errors()) {
        row[0] = PROOF_ATLAS_STATUS_GL_ERROR;
        row[9] = PROOF_ATLAS_POLL_STAGE_DRAIN;
        row[10] = -1;
    }
    else {
        GLenum wait = timer->proof_client_wait_sync(oldest->fence, 0, 0);
        row[7] = wait;
        if (wait == GL_TIMEOUT_EXPIRED) return 0;
        if (wait != GL_ALREADY_SIGNALED && wait != GL_CONDITION_SATISFIED) {
            row[0] = PROOF_ATLAS_STATUS_WAIT;
            row[9] = PROOF_ATLAS_POLL_STAGE_WAIT;
        } else {
            GLint old_binding = 0;
            glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING, &old_binding);
            GLenum error = glGetError();
            if (error != GL_NO_ERROR) {
                row[0] = PROOF_ATLAS_STATUS_GL_ERROR;
                row[9] = PROOF_ATLAS_POLL_STAGE_GET_BINDING;
                row[10] = error;
            } else {
                timer->proof_bind_buffer(GL_PIXEL_PACK_BUFFER, oldest->pbo);
                error = glGetError();
                if (error != GL_NO_ERROR) {
                    row[0] = PROOF_ATLAS_STATUS_GL_ERROR;
                    row[9] = PROOF_ATLAS_POLL_STAGE_BIND;
                    row[10] = error;
                } else {
                    void *mapped = destination &&
                            destination_capacity >= timer->proof_atlas_bytes ?
                            timer->proof_map_buffer_range(GL_PIXEL_PACK_BUFFER, 0,
                                    timer->proof_atlas_bytes, GL_MAP_READ_BIT) : NULL;
                    error = glGetError();
                    if (error != GL_NO_ERROR) {
                        row[0] = PROOF_ATLAS_STATUS_GL_ERROR;
                        row[9] = PROOF_ATLAS_POLL_STAGE_MAP;
                        row[10] = error;
                    } else if (!mapped) {
                        row[0] = PROOF_ATLAS_STATUS_MAP;
                        row[9] = PROOF_ATLAS_POLL_STAGE_MAP;
                    } else {
                        memcpy(destination, mapped, timer->proof_atlas_bytes);
                        GLboolean unmapped = timer->proof_unmap_buffer(
                                GL_PIXEL_PACK_BUFFER);
                        error = glGetError();
                        if (error != GL_NO_ERROR) {
                            row[0] = PROOF_ATLAS_STATUS_GL_ERROR;
                            row[9] = PROOF_ATLAS_POLL_STAGE_UNMAP;
                            row[10] = error;
                        } else if (!unmapped) {
                            row[0] = PROOF_ATLAS_STATUS_UNMAP;
                            row[9] = PROOF_ATLAS_POLL_STAGE_UNMAP;
                        } else {
                            row[0] = PROOF_ATLAS_STATUS_OK;
                            timer->proof_atlas_capability |= PROOF_ATLAS_CAP_COMPLETE;
                        }
                    }
                }
                timer->proof_bind_buffer(GL_PIXEL_PACK_BUFFER, (GLuint)old_binding);
                error = glGetError();
                if (error != GL_NO_ERROR && row[0] == PROOF_ATLAS_STATUS_OK) {
                    row[0] = PROOF_ATLAS_STATUS_GL_ERROR;
                    row[9] = PROOF_ATLAS_POLL_STAGE_RESTORE_BINDING;
                    row[10] = error;
                }
            }
        }
    }
    if (row[8] && (row[0] != PROOF_ATLAS_STATUS_OK ||
            row[7] == GL_ALREADY_SIGNALED || row[7] == GL_CONDITION_SATISFIED)) {
        /* PBO storage is persistent for the configured ring lifetime. Only
         * retire this request's transient ownership; clearing the whole slot
         * would erase pbo and make the fifth enqueue bind buffer zero. */
        timer->proof_delete_sync(oldest->fence);
        oldest->fence = NULL;
        oldest->pending = 0;
        oldest->proof_sequence = 0;
        oldest->present_ordinal = 0;
    }
    return PROOF_ATLAS_RESULT_FIELDS;
}

JNIEXPORT jlongArray JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativePollProofAtlas(JNIEnv *env,
        jclass type, jlong handle, jlong current_present_ordinal,
        jobject destination) {
    (void)type;
    jlong row[PROOF_ATLAS_RESULT_FIELDS] = {0};
    void *target = destination ? (*env)->GetDirectBufferAddress(env, destination) : NULL;
    jlong capacity = destination ?
            (*env)->GetDirectBufferCapacity(env, destination) : -1;
    int count = lucent_framegen_proof_atlas_poll_raw(handle,
            current_present_ordinal, target,
            capacity > INT32_MAX ? INT32_MAX : (int)capacity,
            row, PROOF_ATLAS_RESULT_FIELDS);
    if (count <= 0) return (*env)->NewLongArray(env, 0);
    jlongArray result = (*env)->NewLongArray(env, PROOF_ATLAS_RESULT_FIELDS);
    if (result) (*env)->SetLongArrayRegion(env, result, 0,
            PROOF_ATLAS_RESULT_FIELDS, row);
    return result;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativePendingProofAtlases(JNIEnv *env,
        jclass type, jlong handle) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle); int count = 0;
    if (timer) for (int i = 0; i < timer->proof_atlas_ring_size; ++i)
        count += timer->proof_atlas[i].pending;
    return count;
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeBegin(JNIEnv *env, jclass type,
        jlong handle, jint stage, jlong sequence) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    if (!timer || eglGetCurrentContext() != timer->context || timer->active_slot >= 0 ||
            stage < 1 || stage > 6) return JNI_FALSE;
    timer_slot *slot = &timer->slots[timer->cursor];
    if (slot->pending || slot->active) return JNI_FALSE;
    /* A stale error must not be attributed to this query.  Conversely, once
     * glBeginQueryEXT succeeds far enough to make the query active, every
     * error path must explicitly end it before releasing the slot. */
    if (!drain_gl_errors()) return JNI_FALSE;
    slot->stage = stage; slot->sequence = sequence; slot->active = 1;
    timer->begin(GL_TIME_ELAPSED_EXT, slot->query);
    if (glGetError() != GL_NO_ERROR) {
        timer->end(GL_TIME_ELAPSED_EXT);
        drain_gl_errors();
        slot->active = 0;
        return JNI_FALSE;
    }
    timer->active_slot = timer->cursor;
    timer->cursor = (timer->cursor + 1) % RING_SIZE;
    return JNI_TRUE;
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeEnd(JNIEnv *env, jclass type,
        jlong handle) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    if (!timer || eglGetCurrentContext() != timer->context || timer->active_slot < 0)
        return JNI_FALSE;
    int index = timer->active_slot;
    timer->end(GL_TIME_ELAPSED_EXT);
    timer->active_slot = -1;
    timer->slots[index].active = 0;
    if (glGetError() != GL_NO_ERROR) return JNI_FALSE;
    timer->slots[index].pending = 1;
    return JNI_TRUE;
}

JNIEXPORT jlongArray JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativePoll(JNIEnv *env, jclass type,
        jlong handle, jlong current_pair_sequence, jlong current_warp_sequence) {
    (void)type;
    jlong rows[(RING_SIZE + 1) * RESULT_FIELDS];
    int count = 0;
    count = lucent_framegen_timer_poll_raw(handle, current_pair_sequence,
            current_warp_sequence, rows, (RING_SIZE + 1) * RESULT_FIELDS);
    if (count < 0) count = 0;
    jlongArray result = (*env)->NewLongArray(env, count);
    if (result && count) (*env)->SetLongArrayRegion(env, result, 0, count, rows);
    return result;
}

int lucent_framegen_timer_poll_raw(jlong handle, jlong current_pair_sequence,
        jlong current_warp_sequence, jlong *rows, int capacity) {
    framegen_timer *timer = from(handle);
    int count = 0;
    if (!timer || !rows || capacity < RESULT_FIELDS) return -1;
    if (eglGetCurrentContext() != timer->context)
        return write_result(rows, capacity, 0, STATUS_CONTEXT, -1, NULL,
                current_pair_sequence, current_warp_sequence, 0, 0, 0, 0, 0);
    GLint disjoint = 0;
    if (!drain_gl_errors())
        return write_result(rows, capacity, 0, STATUS_DISJOINT_GL_ERROR, -1, NULL,
                current_pair_sequence, current_warp_sequence, 0, 0, 0, 1, 0);
    glGetIntegerv(GL_GPU_DISJOINT_EXT, &disjoint);
    if (glGetError() != GL_NO_ERROR)
        return write_result(rows, capacity, 0, STATUS_DISJOINT_GL_ERROR, -1, NULL,
                current_pair_sequence, current_warp_sequence, 0, 0, 0, 1, 0);
    if (disjoint) {
        ++timer->disjoint_count;
        for (int i = 0; i < RING_SIZE; ++i) timer->slots[i].pending = 0;
        return write_result(rows, capacity, 0, STATUS_DISJOINT, -1, NULL,
                current_pair_sequence, current_warp_sequence, 0, 0, 0, 1, 1);
    } else {
        for (int i = 0; i < RING_SIZE; ++i) {
            timer_slot *slot = &timer->slots[i];
            if (!slot->pending) continue;
            GLuint available = 0;
            if (!drain_gl_errors())
                return write_result(rows, capacity, count,
                        STATUS_AVAILABILITY_GL_ERROR, i, slot,
                        current_pair_sequence, current_warp_sequence, 0, 0, 0, 1, 0);
            timer->get(slot->query, GL_QUERY_RESULT_AVAILABLE_EXT, &available);
            if (glGetError() != GL_NO_ERROR)
                return write_result(rows, capacity, count,
                        STATUS_AVAILABILITY_GL_ERROR, i, slot,
                        current_pair_sequence, current_warp_sequence, available,
                        0, 0, 1, 0);
            if (!available) continue;
            uint64_t elapsed = 0;
            if (!drain_gl_errors())
                return write_result(rows, capacity, count, STATUS_RESULT_GL_ERROR,
                        i, slot, current_pair_sequence, current_warp_sequence,
                        available, 0, 0, 1, 0);
            timer->get64(slot->query, GL_QUERY_RESULT_EXT, &elapsed);
            if (glGetError() != GL_NO_ERROR)
                return write_result(rows, capacity, count, STATUS_RESULT_GL_ERROR,
                        i, slot, current_pair_sequence, current_warp_sequence,
                        available, elapsed, 0, 1, 0);
            jlong current = slot->stage == 6 ? current_warp_sequence :
                    current_pair_sequence;
            jlong queue_age = current >= slot->sequence ?
                    current - slot->sequence : 0;
            if (elapsed > INT64_MAX) {
                slot->pending = 0;
                return write_result(rows, capacity, count, STATUS_ELAPSED_OVERFLOW,
                        i, slot, current_pair_sequence, current_warp_sequence,
                        available, elapsed, queue_age, 1, 0);
            }
            slot->pending = 0;
            int status = elapsed == 0 ? STATUS_ZERO_ELAPSED : STATUS_OK;
            count = write_result(rows, capacity, count, status, i, slot,
                    current_pair_sequence, current_warp_sequence, available,
                    elapsed, queue_age, 1, 0);
            if (count < 0 || status != STATUS_OK) return count;
        }
    }
    return count;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeTakeDisjointCount(JNIEnv *env,
        jclass type, jlong handle) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    if (!timer) return 0;
    int value = timer->disjoint_count; timer->disjoint_count = 0; return value;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativePendingCount(JNIEnv *env,
        jclass type, jlong handle) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle); int count = 0;
    if (timer) for (int i = 0; i < RING_SIZE; ++i) count += timer->slots[i].pending;
    return count;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeDiscard(JNIEnv *env, jclass type,
        jlong handle) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    if (!timer) return;
    if (timer->active_slot >= 0 && eglGetCurrentContext() == timer->context)
        timer->end(GL_TIME_ELAPSED_EXT);
    timer->active_slot = -1;
    if (timer->active_signature_slot >= 0 &&
            eglGetCurrentContext() == timer->context)
        timer->signature_end(GL_ANY_SAMPLES_PASSED_EXT);
    for (int i = 0; i < RING_SIZE; ++i) {
        timer->slots[i].active = 0;
        timer->slots[i].pending = 0;
    }
    for (int i = 0; i < SIGNATURE_RING_SIZE; ++i) {
        timer->signatures[i].active = 0;
        timer->signatures[i].pending = 0;
    }
    timer->active_signature_slot = -1;
    if (eglGetCurrentContext() == timer->context)
        release_proof_atlas(timer);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_game_DenseGpuTimer_nativeDestroy(JNIEnv *env, jclass type,
        jlong handle) {
    (void)env; (void)type;
    framegen_timer *timer = from(handle);
    if (!timer) return;
    GLuint queries[RING_SIZE];
    for (int i = 0; i < RING_SIZE; ++i) queries[i] = timer->slots[i].query;
    if (eglGetCurrentContext() == timer->context) {
        release_proof_atlas(timer);
        if (timer->signature_supported) {
            GLuint signature_queries[SIGNATURE_RING_SIZE];
            for (int i = 0; i < SIGNATURE_RING_SIZE; ++i)
                signature_queries[i] = timer->signatures[i].query;
            timer->signature_del(SIGNATURE_RING_SIZE, signature_queries);
        }
        timer->del(RING_SIZE, queries);
    }
    free(timer);
}

/* EGL_ANDROID_get_frame_timestamps is the only in-process signal in this
 * renderer that identifies when one of its buffers actually began physical
 * scanout.  This tracker is deliberately separate from the qualification-only
 * GPU timer: direct presentation needs truthful delivered-FPS evidence too. */
jlong lucent_physical_present_create_raw(void) {
    EGLDisplay display = eglGetCurrentDisplay();
    EGLSurface surface = eglGetCurrentSurface(EGL_DRAW);
    EGLContext context = eglGetCurrentContext();
    if (display == EGL_NO_DISPLAY || surface == EGL_NO_SURFACE ||
            context == EGL_NO_CONTEXT)
        return 0;
    const char *extensions = eglQueryString(display, EGL_EXTENSIONS);
    if (!has_extension(extensions, "EGL_ANDROID_get_frame_timestamps"))
        return 0;

    physical_present_tracker *tracker =
            (physical_present_tracker *)calloc(1, sizeof(*tracker));
    if (!tracker) return 0;
    tracker->display = display;
    tracker->surface = surface;
    tracker->context = context;
    tracker->next_frame_id = (get_next_frame_id_fn)
            resolve_egl_symbol("eglGetNextFrameIdANDROID");
    tracker->timestamp_supported = (get_frame_timestamp_supported_fn)
            resolve_egl_symbol("eglGetFrameTimestampSupportedANDROID");
    tracker->frame_timestamps = (get_frame_timestamps_fn)
            resolve_egl_symbol("eglGetFrameTimestampsANDROID");
    if (!tracker->next_frame_id || !tracker->timestamp_supported ||
            !tracker->frame_timestamps) {
        free(tracker);
        return 0;
    }
    if (!drain_egl_errors() ||
            !tracker->timestamp_supported(display, surface,
                    EGL_DISPLAY_PRESENT_TIME_ANDROID) ||
            eglGetError() != EGL_SUCCESS) {
        free(tracker);
        return 0;
    }
    if (!drain_egl_errors() ||
            !eglSurfaceAttrib(display, surface, EGL_TIMESTAMPS_ANDROID,
                    EGL_TRUE) ||
            eglGetError() != EGL_SUCCESS) {
        free(tracker);
        return 0;
    }
    /* Optional readiness evidence must never disable truthful scanout cadence.
     * Query capability per token: unsupported names cause BAD_PARAMETER when
     * requested through eglGetFrameTimestampsANDROID. Bits match the Java
     * GpuPhysicalHeadroomLedger contract. */
    for (int i = 0; i < PHYSICAL_READY_TIMESTAMP_COUNT; ++i) {
        if (!drain_egl_errors()) continue;
        EGLBoolean supported = tracker->timestamp_supported(display, surface,
                physical_ready_timestamp_names[i]);
        EGLint error = eglGetError();
        if (supported && error == EGL_SUCCESS)
            tracker->ready_timestamp_supported_mask |= 1U << i;
    }
    (void)drain_egl_errors();
    return (jlong)(intptr_t)tracker;
}

static void physical_collect_optional_ready(physical_present_tracker *tracker,
        physical_present_slot *slot) {
    EGLint wanted[PHYSICAL_READY_TIMESTAMP_COUNT];
    int indices[PHYSICAL_READY_TIMESTAMP_COUNT];
    int64_t values[PHYSICAL_READY_TIMESTAMP_COUNT];
    int count = 0;
    for (int i = 0; i < PHYSICAL_READY_TIMESTAMP_COUNT; ++i) {
        slot->ready_timestamps[i] = EGL_TIMESTAMP_INVALID_ANDROID;
        if (tracker->collect_ready_timestamps &&
                (tracker->ready_timestamp_supported_mask & (1U << i))) {
            indices[count] = i;
            wanted[count] = physical_ready_timestamp_names[i];
            values[count++] = EGL_TIMESTAMP_INVALID_ANDROID;
        }
    }
    if (!count || !drain_egl_errors()) return;
    EGLBoolean queried = tracker->frame_timestamps(tracker->display,
            tracker->surface, slot->frame_id, count, wanted, values);
    EGLint error = eglGetError();
    if (!queried || error != EGL_SUCCESS) {
        (void)drain_egl_errors();
        return;
    }
    /* Retain raw sentinels and supported zero GPU-finished exactly. Optional
     * PENDING must not delay delivery of a known physical-present timestamp;
     * that row simply cannot earn recovery. Never replace it with poll time. */
    for (int i = 0; i < count; ++i)
        slot->ready_timestamps[indices[i]] = values[i];
}

int lucent_physical_present_ready_enabled_raw(jlong handle, int enabled) {
    physical_present_tracker *tracker = physical_from(handle);
    if (!physical_context_matches(tracker)) return 0;
    tracker->collect_ready_timestamps = enabled != 0;
    return 1;
}

int lucent_physical_present_next_raw(jlong handle, uint64_t *frame_id) {
    physical_present_tracker *tracker = physical_from(handle);
    if (!tracker || !frame_id) return PHYSICAL_PRESENT_STATUS_ARGUMENT;
    if (!physical_context_matches(tracker)) return PHYSICAL_PRESENT_STATUS_CONTEXT;
    uint64_t value = 0;
    if (!drain_egl_errors() ||
            !tracker->next_frame_id(tracker->display, tracker->surface, &value) ||
            eglGetError() != EGL_SUCCESS)
        return PHYSICAL_PRESENT_STATUS_EGL;
    *frame_id = value;
    return 1;
}

int lucent_physical_present_commit_raw(jlong handle, uint64_t frame_id,
        int scans_per_output, int64_t panel_period_ns) {
    physical_present_tracker *tracker = physical_from(handle);
    if (!tracker || scans_per_output < 0 || panel_period_ns <= 0)
        return PHYSICAL_PRESENT_STATUS_ARGUMENT;
    if (!physical_context_matches(tracker)) return PHYSICAL_PRESENT_STATUS_CONTEXT;
    if (tracker->count >= PHYSICAL_PRESENT_RING_SIZE)
        return PHYSICAL_PRESENT_STATUS_RING_FULL;
    if (tracker->has_last_frame_id && frame_id <= tracker->last_frame_id)
        return PHYSICAL_PRESENT_STATUS_ORDER;
    int tail = (tracker->head + tracker->count) % PHYSICAL_PRESENT_RING_SIZE;
    tracker->slots[tail].frame_id = frame_id;
    tracker->slots[tail].scans_per_output = scans_per_output;
    tracker->slots[tail].panel_period_ns = panel_period_ns;
    tracker->last_frame_id = frame_id;
    tracker->has_last_frame_id = 1;
    ++tracker->count;
    return 1;
}

int lucent_physical_present_poll_raw(jlong handle, jlong *row, int capacity) {
    physical_present_tracker *tracker = physical_from(handle);
    if (!tracker || !row || capacity < 5)
        return PHYSICAL_PRESENT_STATUS_ARGUMENT;
    if (!physical_context_matches(tracker)) return PHYSICAL_PRESENT_STATUS_CONTEXT;
    if (tracker->count == 0) return PHYSICAL_PRESENT_POLL_NONE;
    const EGLint wanted = EGL_DISPLAY_PRESENT_TIME_ANDROID;
    /* Do not let one compositor-pending frame hide every newer timestamp
     * until the driver's finite history expires. Query every unresolved ID
     * without waiting and cache any terminal result. The extension explicitly
     * permits repeated polling of a PENDING event and does not guarantee that
     * timestamp publication is ordered by frame ID, so a newer READY result
     * must not retire an older PENDING result. Results are still delivered
     * strictly in submission order below; a permanently unresolved head will
     * fail closed through the driver's finite-history EGL_BAD_ACCESS result or
     * the fixed-capacity commit ring, never through a fabricated timestamp. */
    for (int offset = 0; offset < tracker->count; ++offset) {
        int index = (tracker->head + offset) % PHYSICAL_PRESENT_RING_SIZE;
        physical_present_slot *candidate = &tracker->slots[index];
        if (candidate->resolved_status == 0) {
            int64_t value = EGL_TIMESTAMP_PENDING_ANDROID;
            if (!drain_egl_errors()) return PHYSICAL_PRESENT_STATUS_EGL;
            EGLBoolean queried = tracker->frame_timestamps(tracker->display,
                    tracker->surface, candidate->frame_id, 1, &wanted, &value);
            EGLint query_error = eglGetError();
            if (!queried || query_error != EGL_SUCCESS) {
                if (query_error != EGL_BAD_ACCESS)
                    return PHYSICAL_PRESENT_STATUS_EGL;
                candidate->resolved_status =
                        PHYSICAL_PRESENT_POLL_UNAVAILABLE;
                candidate->resolved_error = query_error;
            } else if (value != EGL_TIMESTAMP_PENDING_ANDROID) {
                candidate->resolved_status =
                        value == EGL_TIMESTAMP_INVALID_ANDROID ?
                                PHYSICAL_PRESENT_POLL_DROPPED :
                                PHYSICAL_PRESENT_POLL_READY;
                candidate->resolved_present_ns = value;
                if (candidate->resolved_status == PHYSICAL_PRESENT_POLL_READY)
                    physical_collect_optional_ready(tracker, candidate);
            }
        }
    }

    physical_present_slot *slot = &tracker->slots[tracker->head];
    if (slot->resolved_status == 0)
        return PHYSICAL_PRESENT_POLL_NONE;

    row[0] = (jlong)slot->frame_id;
    row[1] = (jlong)slot->resolved_present_ns;
    row[2] = slot->scans_per_output;
    row[3] = slot->panel_period_ns;
    row[4] = slot->resolved_status == PHYSICAL_PRESENT_POLL_UNAVAILABLE ?
            slot->resolved_error : tracker->count - 1;
    /* Keep the raw five-field ABI usable by existing cadence-only callers. */
    if (capacity >= PHYSICAL_PRESENT_RESULT_FIELDS) {
        row[5] = tracker->ready_timestamp_supported_mask;
        for (int i = 0; i < PHYSICAL_READY_TIMESTAMP_COUNT; ++i)
            row[6 + i] = slot->resolved_status == PHYSICAL_PRESENT_POLL_READY ?
                    slot->ready_timestamps[i] : EGL_TIMESTAMP_INVALID_ANDROID;
    }
    int resolved_status = slot->resolved_status;
    int64_t resolved_present_ns = slot->resolved_present_ns;
    memset(slot, 0, sizeof(*slot));
    tracker->head = (tracker->head + 1) % PHYSICAL_PRESENT_RING_SIZE;
    --tracker->count;
    if (resolved_status == PHYSICAL_PRESENT_POLL_UNAVAILABLE ||
            resolved_status == PHYSICAL_PRESENT_POLL_DROPPED)
        return resolved_status;
    if (resolved_status != PHYSICAL_PRESENT_POLL_READY ||
            resolved_present_ns <= 0 ||
            resolved_present_ns <= tracker->last_present_ns)
        return PHYSICAL_PRESENT_STATUS_TIMESTAMP;
    tracker->last_present_ns = resolved_present_ns;
    return PHYSICAL_PRESENT_POLL_READY;
}

int lucent_physical_present_pending_raw(jlong handle) {
    physical_present_tracker *tracker = physical_from(handle);
    return tracker ? tracker->count : 0;
}

void lucent_physical_present_destroy_raw(jlong handle) {
    physical_present_tracker *tracker = physical_from(handle);
    if (!tracker) return;
    if (physical_context_matches(tracker)) {
        drain_egl_errors();
        (void)eglSurfaceAttrib(tracker->display, tracker->surface,
                EGL_TIMESTAMPS_ANDROID, EGL_FALSE);
        (void)eglGetError();
    }
    free(tracker);
}

/* Optional prospective timing. Failure never tears down actual-present tracking.
 * Output is published atomically only when every requested value is valid. */
int lucent_physical_compositor_timing_raw(jlong handle, jlong *output, int capacity) {
    physical_present_tracker *tracker = (physical_present_tracker *)(intptr_t)handle;
    if (!output || capacity < 3 || !physical_context_matches(tracker)) return 0;
    typedef EGLBoolean (*query_fn)(EGLDisplay, EGLSurface, EGLint,
            const EGLint *, int64_t *);
    get_frame_timestamp_supported_fn supported = (get_frame_timestamp_supported_fn)
            resolve_egl_symbol("eglGetCompositorTimingSupportedANDROID");
    query_fn query = (query_fn)resolve_egl_symbol("eglGetCompositorTimingANDROID");
    if (!supported || !query) return 0;
    const EGLint names[3] = {0x3431, 0x3432, 0x3433};
    for (int i = 0; i < 3; ++i) {
        if (!drain_egl_errors()) return 0;
        EGLBoolean ok = supported(tracker->display, tracker->surface, names[i]);
        EGLint error = eglGetError();
        if (!ok || error != EGL_SUCCESS) return 0;
    }
    int64_t values[3] = {0, 0, 0};
    EGLBoolean ok = query(tracker->display, tracker->surface, 3, names, values);
    EGLint error = eglGetError();
    if (!ok || error != EGL_SUCCESS || values[0] <= 0 ||
            values[1] <= 0 || values[2] < 0 ||
            values[0] > INT64_MAX - values[2]) return 0;
    for (int i = 0; i < 3; ++i) output[i] = (jlong)values[i];
    return 1;
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_game_PhysicalPresentationTracker_nativeCompositorTiming(
        JNIEnv *env, jclass type, jlong handle, jlongArray output) {
    (void)type;
    if (!env || !output || (*env)->GetArrayLength(env, output) < 3) return JNI_FALSE;
    jlong values[3];
    if (!lucent_physical_compositor_timing_raw(handle, values, 3)) return JNI_FALSE;
    (*env)->SetLongArrayRegion(env, output, 0, 3, values);
    return JNI_TRUE;
}

JNIEXPORT jlong JNICALL
Java_com_thorium_preview_game_PhysicalPresentationTracker_nativeCreate(
        JNIEnv *env, jclass type) {
    (void)env; (void)type;
    return lucent_physical_present_create_raw();
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_PhysicalPresentationTracker_nativeNext(
        JNIEnv *env, jclass type, jlong handle, jlongArray output) {
    (void)type;
    if (!env || !output || (*env)->GetArrayLength(env, output) < 1)
        return PHYSICAL_PRESENT_STATUS_ARGUMENT;
    uint64_t frame_id = 0;
    int status = lucent_physical_present_next_raw(handle, &frame_id);
    if (status > 0) {
        jlong value = (jlong)frame_id;
        (*env)->SetLongArrayRegion(env, output, 0, 1, &value);
    }
    return status;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_PhysicalPresentationTracker_nativeCommit(
        JNIEnv *env, jclass type, jlong handle, jlong frame_id,
        jint scans_per_output, jlong panel_period_ns) {
    (void)env; (void)type;
    return lucent_physical_present_commit_raw(handle, (uint64_t)frame_id,
            scans_per_output, panel_period_ns);
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_PhysicalPresentationTracker_nativePoll(
        JNIEnv *env, jclass type, jlong handle, jlongArray output) {
    (void)type;
    if (!env || !output || (*env)->GetArrayLength(env, output) < PHYSICAL_PRESENT_RESULT_FIELDS)
        return PHYSICAL_PRESENT_STATUS_ARGUMENT;
    jlong row[PHYSICAL_PRESENT_RESULT_FIELDS] = {0};
    int status = lucent_physical_present_poll_raw(handle, row, PHYSICAL_PRESENT_RESULT_FIELDS);
    if (status > 0)
        (*env)->SetLongArrayRegion(env, output, 0, PHYSICAL_PRESENT_RESULT_FIELDS, row);
    return status;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_PhysicalPresentationTracker_nativePending(
        JNIEnv *env, jclass type, jlong handle) {
    (void)env; (void)type;
    return lucent_physical_present_pending_raw(handle);
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_game_PhysicalPresentationTracker_nativeSetReadyTimingEnabled(
        JNIEnv *env, jclass type, jlong handle, jboolean enabled) {
    (void)env; (void)type;
    return lucent_physical_present_ready_enabled_raw(handle, enabled != JNI_FALSE) ?
            JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_game_PhysicalPresentationTracker_nativeDestroy(
        JNIEnv *env, jclass type, jlong handle) {
    (void)env; (void)type;
    lucent_physical_present_destroy_raw(handle);
}
