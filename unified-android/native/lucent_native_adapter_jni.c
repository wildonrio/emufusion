/*
 * JNI bridge for the Lucent Phase 3 native-adapter host.
 *
 * Java <-> host glue for com.thorium.preview.NativeAdapterHost. It mirrors the
 * discipline of lucent_libretro_jni.c: every session call runs on one Java
 * render-owner thread, all failures surface as IllegalStateException, and no
 * capability is faked. Lucent owns the Android Surface(s) and the AudioTrack;
 * this bridge converts each Surface to an ANativeWindow it retains for the
 * adapter and buffers the adapter's PCM into a ring the Java layer drains into
 * its AudioTrack.
 *
 * The real device-level Vulkan window binding arrives with the compiled Cemu
 * adapter. Until then start()/surfaceRecreated() hand the validated
 * ANativeWindow to the host's lucent_native_io unchanged; the lifecycle,
 * signatures, and ownership are already complete.
 */
#include "include/lucent_native_adapter_host.h"

#include <jni.h>
#include <android/native_window.h>
#include <android/native_window_jni.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define ERROR_SIZE 512
#define ADAPTER_AUDIO_RING_SAMPLES (262144u)

/* One in-process adapter session: the host plus the Lucent-owned IO it renders
 * into and the PCM ring it produces. */
typedef struct lucent_adapter_jni_session {
    lucent_native_adapter_host *host;
    ANativeWindow *primary_window;
    ANativeWindow *lower_window;
    /* One failed rebind can leave an adapter borrowing either old or new IO.
     * Retain both sets until adapter destruction, and reject further binds. */
    ANativeWindow *failed_previous_primary;
    ANativeWindow *failed_previous_lower;
    bool window_binding_failed;
    pthread_mutex_t audio_lock;
    int16_t audio_ring[ADAPTER_AUDIO_RING_SAMPLES];
    size_t audio_read;
    size_t audio_count;
} lucent_adapter_jni_session;

static void throw_state(JNIEnv *env, const char *message) {
    jclass type = (*env)->FindClass(env, "java/lang/IllegalStateException");
    if (type) (*env)->ThrowNew(env, type,
            message && *message ? message : "native adapter host failed");
}

static lucent_adapter_jni_session *from_handle(jlong handle) {
    return (lucent_adapter_jni_session *)(intptr_t)handle;
}

/* Adapter audio callback: append interleaved stereo s16 frames, dropping the
 * oldest on overflow so a stalled Java drain never blocks emulation. */
static size_t adapter_audio_sink(void *sink_ctx, const int16_t *frames,
                                 size_t frame_count) {
    lucent_adapter_jni_session *session =
            (lucent_adapter_jni_session *)sink_ctx;
    size_t samples;
    size_t index;
    if (!session || !frames || frame_count == 0 ||
            frame_count > SIZE_MAX / 2) return 0;
    samples = frame_count * 2u;
    pthread_mutex_lock(&session->audio_lock);
    for (index = 0; index < samples; index++) {
        size_t write;
        if (session->audio_count == ADAPTER_AUDIO_RING_SAMPLES) {
            session->audio_read =
                    (session->audio_read + 1) % ADAPTER_AUDIO_RING_SAMPLES;
            session->audio_count--;
        }
        write = (session->audio_read + session->audio_count) %
                ADAPTER_AUDIO_RING_SAMPLES;
        session->audio_ring[write] = frames[index];
        session->audio_count++;
    }
    pthread_mutex_unlock(&session->audio_lock);
    return frame_count;
}

/* Retains an ANativeWindow from a Java Surface; releases any previous one held
 * in *slot. A NULL surface clears the slot (single-screen device). */
static bool bind_window(JNIEnv *env, ANativeWindow **slot, jobject surface,
                        char *error, size_t error_size) {
    ANativeWindow *window = NULL;
    if (surface) {
        window = ANativeWindow_fromSurface(env, surface);
        if (!window) {
            snprintf(error, error_size, "Surface has no valid ANativeWindow");
            return false;
        }
    }
    if (*slot) ANativeWindow_release(*slot);
    *slot = window;
    return true;
}

/* Acquire the complete replacement before publishing either window. The old
 * host references stay alive through the adapter notification. A Vulkan
 * adapter must also retain its old VkSurface until every old swapchain is
 * retired: that loader surface owns the GPU-side ANativeWindow reference. */
static bool bind_replacement_windows(JNIEnv *env,
        lucent_adapter_jni_session *session, jobject primary, jobject lower,
        ANativeWindow **old_primary, ANativeWindow **old_lower,
        char *error, size_t error_size) {
    if (session->window_binding_failed) {
        snprintf(error, error_size, "render window binding failed; restart required");
        return false;
    }
    ANativeWindow *new_primary = NULL;
    ANativeWindow *new_lower = NULL;
    if (!bind_window(env, &new_primary, primary, error, error_size) ||
            !bind_window(env, &new_lower, lower, error, error_size)) {
        if (new_primary) ANativeWindow_release(new_primary);
        if (new_lower) ANativeWindow_release(new_lower);
        return false;
    }
    *old_primary = session->primary_window;
    *old_lower = session->lower_window;
    session->primary_window = new_primary;
    session->lower_window = new_lower;
    return true;
}

static void release_replaced_windows(ANativeWindow *primary, ANativeWindow *lower) {
    if (primary) ANativeWindow_release(primary);
    if (lower) ANativeWindow_release(lower);
}

static void finish_window_binding(lucent_adapter_jni_session *session,
        ANativeWindow *old_primary, ANativeWindow *old_lower, bool success) {
    if (success) {
        release_replaced_windows(old_primary, old_lower);
        return;
    }
    /* A failed adapter callback is not a rollback guarantee. Its render
     * thread may still borrow the old windows, or may have adopted the new
     * ones partially. Keep exactly this one previous pair until destroy has
     * joined/retired the adapter; the failure latch prevents accumulating any
     * further pairs. Throwing a Java exception alone does not stop native work. */
    session->failed_previous_primary = old_primary;
    session->failed_previous_lower = old_lower;
    session->window_binding_failed = true;
}

static void release_windows(lucent_adapter_jni_session *session) {
    release_replaced_windows(session->failed_previous_primary, session->failed_previous_lower);
    session->failed_previous_primary = NULL;
    session->failed_previous_lower = NULL;
    if (session->primary_window) {
        ANativeWindow_release(session->primary_window);
        session->primary_window = NULL;
    }
    if (session->lower_window) {
        ANativeWindow_release(session->lower_window);
        session->lower_window = NULL;
    }
}

static void build_io(lucent_adapter_jni_session *session, lucent_native_io *io) {
    memset(io, 0, sizeof(*io));
    io->kind = LUCENT_NATIVE_RENDER_VULKAN_WINDOW;
    io->primary_window = session->primary_window;
    io->lower_window = session->lower_window;
    io->audio_sink = adapter_audio_sink;
    io->audio_sink_ctx = session;
}

/* Android calls this because Java reaches this library through
 * System.loadLibrary. An adapter is opened with dlopen instead, which never
 * triggers its JNI_OnLoad, so we hand the VM to the host and it performs that
 * call itself once the adapter is mapped. */
JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *reserved) {
    (void)reserved;
    lucent_native_adapter_supply_java_vm(vm);
    return JNI_VERSION_1_6;
}

JNIEXPORT jlong JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeOpen(
        JNIEnv *env, jclass type, jstring adapter_path, jstring trusted_root) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    const char *adapter = NULL;
    const char *root = NULL;
    lucent_adapter_jni_session *session = NULL;
    if (!adapter_path || !trusted_root) {
        throw_state(env, "adapter path and trusted root are required");
        return 0;
    }
    adapter = (*env)->GetStringUTFChars(env, adapter_path, NULL);
    root = (*env)->GetStringUTFChars(env, trusted_root, NULL);
    if (adapter && root) {
        session = (lucent_adapter_jni_session *)calloc(1, sizeof(*session));
        if (session) {
            if (pthread_mutex_init(&session->audio_lock, NULL) != 0) {
                free(session);
                session = NULL;
                snprintf(error, sizeof(error), "cannot create adapter audio lock");
            } else {
                session->host = lucent_native_adapter_open(
                        adapter, root, error, sizeof(error));
                if (!session->host) {
                    pthread_mutex_destroy(&session->audio_lock);
                    free(session);
                    session = NULL;
                }
            }
        } else {
            snprintf(error, sizeof(error), "out of memory creating adapter session");
        }
    }
    if (adapter) (*env)->ReleaseStringUTFChars(env, adapter_path, adapter);
    if (root) (*env)->ReleaseStringUTFChars(env, trusted_root, root);
    if (!session && !(*env)->ExceptionCheck(env)) throw_state(env, error);
    return (jlong)(intptr_t)session;
}

JNIEXPORT jintArray JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeDescribe(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    lucent_native_capabilities caps;
    jint values[6];
    jintArray result;
    if (!session || !lucent_native_adapter_describe(
            session->host, &caps, error, sizeof(error))) {
        throw_state(env, error);
        return NULL;
    }
    values[0] = (jint)caps.abi_version;
    values[1] = caps.has_quick_resume ? 1 : 0;
    values[2] = caps.has_persistent_save ? 1 : 0;
    values[3] = caps.dual_screen ? 1 : 0;
    values[4] = (jint)caps.required_firmware;
    values[5] = (jint)caps.max_controllers;
    result = (*env)->NewIntArray(env, 6);
    if (result) (*env)->SetIntArrayRegion(env, result, 0, 6, values);
    return result;
}

JNIEXPORT jstring JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeEngineId(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    lucent_native_capabilities caps;
    if (!session || !lucent_native_adapter_describe(
            session->host, &caps, error, sizeof(error))) {
        throw_state(env, error);
        return NULL;
    }
    return (*env)->NewStringUTF(env, caps.engine_id ? caps.engine_id : "");
}

/* Reports the engine's averaged emulated-frame rate, or a negative value when
 * the adapter publishes no measurement hook. Deliberately does not throw on an
 * absent hook: a missing measurement is a normal state, not a session error. */
JNIEXPORT jdouble JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeAverageFps(
        JNIEnv *env, jclass type, jlong handle) {
    (void)env;
    (void)type;
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session) return LUCENT_NATIVE_ADAPTER_FPS_UNSUPPORTED;
    return lucent_native_adapter_average_fps(session->host);
}

/* Optional clock and timeline capabilities; missing hooks never fabricate evidence. */
JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeSetFgPresentation(
        JNIEnv *env, jclass type, jlong handle, jboolean enabled) {
    (void)env;
    (void)type;
    lucent_adapter_jni_session *session = from_handle(handle);
    return session && lucent_native_adapter_set_fg_presentation(
            session->host, enabled == JNI_TRUE) ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeTimingCapabilities(
        JNIEnv *env, jclass type, jlong handle) {
    (void)env;
    (void)type;
    lucent_adapter_jni_session *session = from_handle(handle);
    return session ? (jint)lucent_native_adapter_timing_capabilities(session->host) : 0;
}

JNIEXPORT jdouble JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeProducerTimelineHz(
        JNIEnv *env, jclass type, jlong handle) {
    (void)env;
    (void)type;
    lucent_adapter_jni_session *session = from_handle(handle);
    return session ? lucent_native_adapter_producer_timeline_hz(session->host) : 0.0;
}

JNIEXPORT jdouble JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeDeclaredVideoHz(
        JNIEnv *env, jclass type, jlong handle) {
    (void)env;
    (void)type;
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session) return 0.0;
    return lucent_native_adapter_declared_video_hz(session->host);
}

/* Java owns a try-read session lease until this bounded copy returns. Use a
 * stack record and memcpy so sliced direct buffers need no alignment promises. */
JNIEXPORT jint JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeSourceImageBinding(
        JNIEnv *env, jclass type, jlong handle, jobject output) {
    (void)type;
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session) return LUCENT_SOURCE_CLOSED;
    if (!output) return LUCENT_SOURCE_BAD_ARGUMENT;
    void *bytes = (*env)->GetDirectBufferAddress(env, output);
    jlong capacity = (*env)->GetDirectBufferCapacity(env, output);
    if (!bytes || capacity < (jlong)sizeof(lucent_source_binding_v1)) return LUCENT_SOURCE_BAD_ARGUMENT;
    lucent_source_binding_v1 value = {0};
    uint32_t result = lucent_native_adapter_source_image_binding(session->host, &value, sizeof(value));
    memcpy(bytes, &value, sizeof(value));
    return (jint)result;
}

JNIEXPORT jint JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeQuerySourceImage(
        JNIEnv *env, jclass type, jlong handle, jlong session_epoch,
        jlong surface_epoch, jlong timestamp_ns, jobject output) {
    (void)type;
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session) return LUCENT_SOURCE_CLOSED;
    if (!output || session_epoch <= 0 || surface_epoch <= 0 || timestamp_ns <= 0)
        return LUCENT_SOURCE_BAD_ARGUMENT;
    void *bytes = (*env)->GetDirectBufferAddress(env, output);
    jlong capacity = (*env)->GetDirectBufferCapacity(env, output);
    if (!bytes || capacity < (jlong)sizeof(lucent_source_image_v1)) return LUCENT_SOURCE_BAD_ARGUMENT;
    lucent_source_image_v1 value = {0};
    uint32_t result = lucent_native_adapter_query_source_image(session->host,
            (uint64_t)session_epoch, (uint64_t)surface_epoch, (uint64_t)timestamp_ns,
            &value, sizeof(value));
    memcpy(bytes, &value, sizeof(value));
    return (jint)result;
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeSetPacedVideoHz(
        JNIEnv *env, jclass type, jlong handle, jdouble hz) {
    (void)env;
    (void)type;
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session) return JNI_FALSE;
    return lucent_native_adapter_set_paced_video_hz(session->host, hz) ?
            JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeCreate(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session || !lucent_native_adapter_create(
            session->host, error, sizeof(error)))
        throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeLoadContent(
        JNIEnv *env, jclass type, jlong handle, jstring system_directory,
        jstring save_directory, jstring content_path) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    lucent_native_load_request request;
    const char *system = system_directory ?
            (*env)->GetStringUTFChars(env, system_directory, NULL) : NULL;
    const char *save = save_directory ?
            (*env)->GetStringUTFChars(env, save_directory, NULL) : NULL;
    const char *content = content_path ?
            (*env)->GetStringUTFChars(env, content_path, NULL) : NULL;
    bool success;
    memset(&request, 0, sizeof(request));
    request.system_directory = system;
    request.save_directory = save;
    request.content_path = content;
    success = session && lucent_native_adapter_load(
            session->host, &request, error, sizeof(error));
    if (system) (*env)->ReleaseStringUTFChars(env, system_directory, system);
    if (save) (*env)->ReleaseStringUTFChars(env, save_directory, save);
    if (content) (*env)->ReleaseStringUTFChars(env, content_path, content);
    if (!success && !(*env)->ExceptionCheck(env)) throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeStart(
        JNIEnv *env, jclass type, jlong handle, jobject primary_surface,
        jobject lower_surface) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    lucent_native_io io;
    ANativeWindow *old_primary = NULL;
    ANativeWindow *old_lower = NULL;
    if (!session) {
        throw_state(env, "adapter session is unavailable");
        return;
    }
    if (!bind_replacement_windows(env, session, primary_surface, lower_surface,
                                  &old_primary, &old_lower, error, sizeof(error))) {
        throw_state(env, error);
        return;
    }
    build_io(session, &io);
    const bool started = lucent_native_adapter_start(
            session->host, &io, error, sizeof(error));
    finish_window_binding(session, old_primary, old_lower, started);
    if (!started)
        throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeSurfaceRecreated(
        JNIEnv *env, jclass type, jlong handle, jobject primary_surface,
        jobject lower_surface) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    lucent_native_io io;
    ANativeWindow *old_primary = NULL;
    ANativeWindow *old_lower = NULL;
    if (!session) {
        throw_state(env, "adapter session is unavailable");
        return;
    }
    if (!bind_replacement_windows(env, session, primary_surface, lower_surface,
                                  &old_primary, &old_lower, error, sizeof(error))) {
        throw_state(env, error);
        return;
    }
    build_io(session, &io);
    const bool rebound = lucent_native_adapter_surface_recreated(
            session->host, &io, error, sizeof(error));
    finish_window_binding(session, old_primary, old_lower, rebound);
    if (!rebound)
        throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeRunFrame(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session || !lucent_native_adapter_run_frame(
            session->host, error, sizeof(error)))
        throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeSetControl(
        JNIEnv *env, jclass type, jlong handle, jint controllerIndex,
        jint control, jfloat value) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    if (control < 0 || controllerIndex < 0 || !session ||
            !lucent_native_adapter_set_control(
            session->host, (uint32_t)controllerIndex,
            (lucent_native_control)control, (float)value,
            error, sizeof(error)))
        throw_state(env, "invalid adapter control input");
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativePause(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session || !lucent_native_adapter_pause(
            session->host, error, sizeof(error)))
        throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeResume(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session || !lucent_native_adapter_resume(
            session->host, error, sizeof(error)))
        throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeFlushSave(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session || !lucent_native_adapter_flush_save(
            session->host, error, sizeof(error)))
        throw_state(env, error);
}

JNIEXPORT jshortArray JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeDrainAudio(
        JNIEnv *env, jclass type, jlong handle, jint max_frames) {
    (void)type;
    lucent_adapter_jni_session *session = from_handle(handle);
    size_t wanted;
    size_t available;
    size_t index;
    int16_t *samples;
    jshortArray result;
    if (!session || max_frames <= 0 || max_frames > INT32_MAX / 2) return NULL;
    wanted = (size_t)max_frames * 2u;
    pthread_mutex_lock(&session->audio_lock);
    available = session->audio_count < wanted ? session->audio_count : wanted;
    samples = available ? (int16_t *)malloc(available * sizeof(int16_t)) : NULL;
    if (available && !samples) {
        pthread_mutex_unlock(&session->audio_lock);
        throw_state(env, "out of memory draining adapter audio");
        return NULL;
    }
    for (index = 0; index < available; index++) {
        samples[index] = session->audio_ring[session->audio_read];
        session->audio_read =
                (session->audio_read + 1) % ADAPTER_AUDIO_RING_SAMPLES;
    }
    session->audio_count -= available;
    pthread_mutex_unlock(&session->audio_lock);
    result = (*env)->NewShortArray(env, (jsize)available);
    if (result && available)
        (*env)->SetShortArrayRegion(env, result, 0, (jsize)available,
                                    (const jshort *)samples);
    free(samples);
    return result;
}

JNIEXPORT jbyteArray JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeSerialize(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    size_t size = 0;
    void *bytes;
    jbyteArray result;
    if (!session) {
        throw_state(env, "adapter session is unavailable");
        return NULL;
    }
    /* An engine without Quick Resume is not an error; it simply has no state to
     * hand back. Lucent must treat this as "no snapshot", never a fake one. */
    if (!lucent_native_adapter_has_quick_resume(session->host)) return NULL;
    size = lucent_native_adapter_serialize_size(session->host);
    if (size == 0 || size > INT32_MAX) {
        throw_state(env, "adapter reported an unusable serialized state size");
        return NULL;
    }
    bytes = malloc(size);
    if (!bytes) {
        throw_state(env, "out of memory serializing adapter state");
        return NULL;
    }
    if (!lucent_native_adapter_serialize(session->host, bytes, size, &size,
                                         error, sizeof(error))) {
        free(bytes);
        throw_state(env, error);
        return NULL;
    }
    result = (*env)->NewByteArray(env, (jsize)size);
    if (result) (*env)->SetByteArrayRegion(env, result, 0, (jsize)size,
                                           (const jbyte *)bytes);
    free(bytes);
    return result;
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeUnserialize(
        JNIEnv *env, jclass type, jlong handle, jbyteArray state) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    jsize size;
    jbyte *bytes;
    bool success;
    if (!session || !state) return JNI_FALSE;
    if (!lucent_native_adapter_has_quick_resume(session->host)) return JNI_FALSE;
    size = (*env)->GetArrayLength(env, state);
    bytes = (*env)->GetByteArrayElements(env, state, NULL);
    success = bytes && lucent_native_adapter_unserialize(
            session->host, bytes, (size_t)size, error, sizeof(error));
    if (bytes) (*env)->ReleaseByteArrayElements(env, state, bytes, JNI_ABORT);
    if (!success && !(*env)->ExceptionCheck(env)) throw_state(env, error);
    return success ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeStop(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session || !lucent_native_adapter_stop(
            session->host, error, sizeof(error)))
        throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_NativeAdapterHost_nativeDestroy(
        JNIEnv *env, jclass type, jlong handle) {
    (void)env;
    (void)type;
    lucent_adapter_jni_session *session = from_handle(handle);
    if (!session) return;
    lucent_native_adapter_destroy(session->host);
    release_windows(session);
    pthread_mutex_destroy(&session->audio_lock);
    free(session);
}
