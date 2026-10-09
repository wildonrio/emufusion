#include "include/lucent_android_vulkan_backend.h"
#include "include/lucent_libretro_host.h"

#include <jni.h>
#include <android/native_window_jni.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define ERROR_SIZE 512

typedef struct lucent_vulkan_jni_session {
    lucent_android_vulkan_backend *backend;
    lucent_retro_host *host;
    bool game_loaded;
} lucent_vulkan_jni_session;

static void throw_state(JNIEnv *env, const char *message) {
    jclass type = (*env)->FindClass(env, "java/lang/IllegalStateException");
    if (type) (*env)->ThrowNew(env, type,
            message && *message ? message : "native Vulkan core host failed");
}

static lucent_vulkan_jni_session *from_handle(jlong handle) {
    return (lucent_vulkan_jni_session *)(intptr_t)handle;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeSetFgTimestampVulkan(
        JNIEnv *env, jclass type, jlong handle, jboolean secondary, jboolean enabled) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    if ((!session || !session->backend ||
            !lucent_android_vulkan_set_fg_timestamp(session->backend,
                    secondary == JNI_TRUE, enabled == JNI_TRUE,
                    error, sizeof(error))) && !(*env)->ExceptionCheck(env))
        throw_state(env, error);
}

JNIEXPORT jlong JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeCreateVulkan(
        JNIEnv *env, jclass type, jstring core_path, jstring trusted_root,
        jstring system_directory, jstring save_directory,
        jboolean widescreen_enhancements_enabled) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    const char *core = NULL;
    const char *root = NULL;
    const char *system = NULL;
    const char *save = NULL;
    lucent_retro_hw_options options;
    lucent_vulkan_jni_session *session = NULL;
    if (!core_path || !trusted_root || !system_directory || !save_directory) {
        throw_state(env, "core, trusted root, system, and save paths are required");
        return 0;
    }
    core = (*env)->GetStringUTFChars(env, core_path, NULL);
    root = (*env)->GetStringUTFChars(env, trusted_root, NULL);
    system = (*env)->GetStringUTFChars(env, system_directory, NULL);
    save = (*env)->GetStringUTFChars(env, save_directory, NULL);
    if (!core || !root || !system || !save) goto done;
    session = (lucent_vulkan_jni_session *)calloc(1, sizeof(*session));
    if (!session) {
        snprintf(error, sizeof(error), "out of memory creating Vulkan JNI session");
        goto done;
    }
    session->backend = lucent_android_vulkan_create(error, sizeof(error));
    if (!session->backend || !lucent_android_vulkan_get_host_options(
            session->backend, &options, error, sizeof(error))) goto done;
    session->host = lucent_retro_create_with_preferences(
            core, root, system, save, &options,
            widescreen_enhancements_enabled == JNI_TRUE,
            error, sizeof(error));
done:
    if (core) (*env)->ReleaseStringUTFChars(env, core_path, core);
    if (root) (*env)->ReleaseStringUTFChars(env, trusted_root, root);
    if (system) (*env)->ReleaseStringUTFChars(env, system_directory, system);
    if (save) (*env)->ReleaseStringUTFChars(env, save_directory, save);
    if ((!session || !session->host) && !(*env)->ExceptionCheck(env)) {
        if (session) {
            lucent_android_vulkan_destroy(session->backend);
            free(session);
            session = NULL;
        }
        throw_state(env, error);
    }
    return (jlong)(intptr_t)session;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeLoadGameVulkan(
        JNIEnv *env, jclass type, jlong handle, jstring game_path) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    const char *path = game_path ?
            (*env)->GetStringUTFChars(env, game_path, NULL) : NULL;
    bool success = session && session->host && path &&
            lucent_retro_load_game(session->host, path, error, sizeof(error));
    if (success) session->game_loaded = true;
    if (path) (*env)->ReleaseStringUTFChars(env, game_path, path);
    if (!success && !(*env)->ExceptionCheck(env)) throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeSetPresentationAspectVulkan(
        JNIEnv *env, jclass type, jlong handle, jfloat aspect) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    if ((!session || !session->backend ||
            !lucent_android_vulkan_set_presentation_aspect(
                    session->backend, aspect, error, sizeof(error))) &&
            !(*env)->ExceptionCheck(env)) throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeSetSecondaryPresentationRotationVulkan(
        JNIEnv *env, jclass type, jlong handle, jint clockwise_degrees) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    if ((!session || !session->backend ||
            !lucent_android_vulkan_set_secondary_rotation(
                    session->backend, (unsigned)clockwise_degrees,
                    error, sizeof(error))) && !(*env)->ExceptionCheck(env))
        throw_state(env, error);
}

static bool attach_surface(JNIEnv *env, lucent_vulkan_jni_session *session,
                           jobject surface, bool recreate,
                           char *error, size_t error_size) {
    ANativeWindow *window;
    bool success;
    if (!session || !session->backend || !session->host || !surface) {
        snprintf(error, error_size,
                 "Vulkan session and Android Surface are required");
        return false;
    }
    if (recreate && !lucent_android_vulkan_detach(
            session->backend, error, error_size)) return false;
    window = ANativeWindow_fromSurface(env, surface);
    if (!window) {
        snprintf(error, error_size, "Android Surface has no valid ANativeWindow");
        return false;
    }
    success = lucent_android_vulkan_attach(session->backend, session->host,
                                            window, error, error_size);
    ANativeWindow_release(window);
    return success;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeAttachSurfaceVulkan(
        JNIEnv *env, jclass type, jlong handle, jobject surface) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    if (!attach_surface(env, from_handle(handle), surface, false,
                        error, sizeof(error)) && !(*env)->ExceptionCheck(env))
        throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeRecreateSurfaceVulkan(
        JNIEnv *env, jclass type, jlong handle, jobject surface) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    if (!attach_surface(env, from_handle(handle), surface, true,
                        error, sizeof(error)) && !(*env)->ExceptionCheck(env))
        throw_state(env, error);
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeRunAndPresentVulkan(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    bool presented = false;
    lucent_vulkan_jni_session *session = from_handle(handle);
    if (!session || !lucent_android_vulkan_run_and_present(
            session->backend, &presented, error, sizeof(error))) {
        if (!(*env)->ExceptionCheck(env)) throw_state(env, error);
        return JNI_FALSE;
    }
    return presented ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeDetachSurfaceVulkan(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    if ((!session || !lucent_android_vulkan_detach(
            session->backend, error, sizeof(error))) &&
            !(*env)->ExceptionCheck(env)) throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeAttachSecondarySurfaceVulkan(
        JNIEnv *env, jclass type, jlong handle, jobject surface) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    ANativeWindow *window;
    bool success;
    if (!session || !session->backend || !surface) {
        throw_state(env, "Vulkan session and secondary Surface are required");
        return;
    }
    window = ANativeWindow_fromSurface(env, surface);
    if (!window) {
        throw_state(env, "secondary Surface has no valid ANativeWindow");
        return;
    }
    success = lucent_android_vulkan_attach_secondary(
            session->backend, window, error, sizeof(error));
    ANativeWindow_release(window);
    if (!success && !(*env)->ExceptionCheck(env)) throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeDetachSecondarySurfaceVulkan(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    if ((!session || !lucent_android_vulkan_detach_secondary(
            session->backend, error, sizeof(error))) &&
            !(*env)->ExceptionCheck(env)) throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeSetPausedVulkan(
        JNIEnv *env, jclass type, jlong handle, jboolean paused) {
    (void)env; (void)type;
    lucent_vulkan_jni_session *session = from_handle(handle);
    if (session) lucent_retro_set_paused(session->host, paused == JNI_TRUE);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeSetJoypadButtonVulkan(
        JNIEnv *env, jclass type, jlong handle, jint port, jint button,
        jboolean pressed) {
    (void)type;
    lucent_vulkan_jni_session *session = from_handle(handle);
    if (!session || port < 0 || button < 0 ||
            !lucent_retro_set_joypad_button(session->host, (unsigned)port,
                    (unsigned)button, pressed == JNI_TRUE))
        throw_state(env, "invalid Vulkan joypad input");
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeSetAnalogAxisVulkan(
        JNIEnv *env, jclass type, jlong handle, jint port, jint index, jint id,
        jint value) {
    (void)type;
    lucent_vulkan_jni_session *session = from_handle(handle);
    if (!session || port < 0 || index < 0 || id < 0 ||
            value < INT16_MIN || value > INT16_MAX ||
            !lucent_retro_set_analog_axis(session->host, (unsigned)port,
                    (unsigned)index, (unsigned)id, (int16_t)value))
        throw_state(env, "invalid Vulkan analog input");
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeSetPointerVulkan(
        JNIEnv *env, jclass type, jlong handle, jint port, jint x, jint y,
        jboolean pressed) {
    (void)type;
    lucent_vulkan_jni_session *session = from_handle(handle);
    if (!session || port < 0 || x < INT16_MIN || x > INT16_MAX ||
            y < INT16_MIN || y > INT16_MAX ||
            !lucent_retro_set_pointer(session->host, (unsigned)port,
                    (int16_t)x, (int16_t)y, pressed == JNI_TRUE))
        throw_state(env, "invalid Vulkan pointer input");
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeSetControllerPortDeviceVulkan(
        JNIEnv *env, jclass type, jlong handle, jint port, jint device) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    if (!session || port < 0 || device < 0 ||
            !lucent_retro_set_controller_port_device(session->host,
                    (unsigned)port, (unsigned)device,
                    error, sizeof(error))) {
        if (!(*env)->ExceptionCheck(env)) throw_state(env, error);
    }
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeResetVulkan(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    bool success = session && session->host &&
            lucent_retro_reset(session->host, error, sizeof(error));
    if (!success && !(*env)->ExceptionCheck(env)) throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeCheatResetVulkan(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    bool success = session && session->host &&
            lucent_retro_cheat_reset(session->host, error, sizeof(error));
    if (!success && !(*env)->ExceptionCheck(env)) throw_state(env, error);
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeCheatSetVulkan(
        JNIEnv *env, jclass type, jlong handle, jint index, jboolean enabled,
        jstring code) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    if (!session || !session->host || index < 0 || code == NULL) {
        throw_state(env, "a loaded Vulkan session, nonnegative slot and cheat code are required");
        return;
    }
    const char *native_code = (*env)->GetStringUTFChars(env, code, NULL);
    if (native_code == NULL) return;
    bool success = lucent_retro_cheat_set(session->host, (unsigned)index,
            enabled == JNI_TRUE, native_code, error, sizeof(error));
    (*env)->ReleaseStringUTFChars(env, code, native_code);
    if (!success && !(*env)->ExceptionCheck(env)) throw_state(env, error);
}

JNIEXPORT jshortArray JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeDrainAudioVulkan(
        JNIEnv *env, jclass type, jlong handle, jint max_frames) {
    (void)type;
    lucent_vulkan_jni_session *session = from_handle(handle);
    size_t max_samples;
    int16_t *samples;
    size_t frames;
    jsize sample_count;
    jshortArray result;
    if (!session || max_frames <= 0 || max_frames > INT32_MAX / 2) return NULL;
    max_samples = (size_t)max_frames * 2;
    samples = (int16_t *)malloc(max_samples * sizeof(int16_t));
    if (!samples) {
        throw_state(env, "out of memory draining Vulkan audio");
        return NULL;
    }
    frames = lucent_retro_drain_audio(session->host, samples,
                                      (size_t)max_frames);
    sample_count = (jsize)(frames * 2);
    result = (*env)->NewShortArray(env, sample_count);
    if (result && sample_count)
        (*env)->SetShortArrayRegion(env, result, 0, sample_count,
                                    (const jshort *)samples);
    free(samples);
    return result;
}

JNIEXPORT jdoubleArray JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeAvInfoVulkan(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    lucent_vulkan_jni_session *session = from_handle(handle);
    lucent_retro_av_info info;
    jdouble values[5];
    jdoubleArray result;
    if (!session || !lucent_retro_get_av_info(session->host, &info)) return NULL;
    values[0] = info.frames_per_second;
    values[1] = info.sample_rate;
    values[2] = info.aspect_ratio;
    values[3] = info.base_width;
    values[4] = info.base_height;
    result = (*env)->NewDoubleArray(env, 5);
    if (result) (*env)->SetDoubleArrayRegion(env, result, 0, 5, values);
    return result;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeSetSynchronizedVideoRateVulkan(
        JNIEnv *env, jclass type, jlong handle, jdouble declared_hz,
        jdouble synchronized_hz) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    if (!session || !session->host ||
            !lucent_retro_set_synchronized_video_rate(
                    session->host, declared_hz, synchronized_hz,
                    error, sizeof(error))) throw_state(env, error);
}

JNIEXPORT jbyteArray JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeSerializeVulkan(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    size_t size;
    void *bytes;
    jbyteArray result;
    if (!session) return NULL;
    size = 0;
    bytes = NULL;
    if (!lucent_retro_serialize_alloc(session->host, &bytes, &size,
                                      error, sizeof(error))) {
        throw_state(env, error);
        return NULL;
    }
    if (size > INT32_MAX) {
        free(bytes);
        throw_state(env, "serialized Vulkan state exceeds the Java array limit");
        return NULL;
    }
    result = (*env)->NewByteArray(env, (jsize)size);
    if (result)
        (*env)->SetByteArrayRegion(env, result, 0, (jsize)size,
                                   (const jbyte *)bytes);
    free(bytes);
    return result;
}

JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeStateReadyVulkan(
        JNIEnv *env, jclass type, jlong handle) {
    (void)env;
    (void)type;
    lucent_vulkan_jni_session *session = from_handle(handle);
    return session && session->host && lucent_retro_serialize_size(session->host) > 0
            ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeUnserializeVulkan(
        JNIEnv *env, jclass type, jlong handle, jbyteArray state) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    jsize size;
    jbyte *bytes;
    bool success;
    if (!session || !state) {
        throw_state(env, "Vulkan serialized state is required");
        return;
    }
    size = (*env)->GetArrayLength(env, state);
    bytes = (*env)->GetByteArrayElements(env, state, NULL);
    success = bytes && lucent_retro_unserialize(
            session->host, bytes, (size_t)size, error, sizeof(error));
    if (bytes) (*env)->ReleaseByteArrayElements(env, state, bytes, JNI_ABORT);
    if (!success && !(*env)->ExceptionCheck(env)) throw_state(env, error);
}

JNIEXPORT jbyteArray JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeReadSaveRamVulkan(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    lucent_vulkan_jni_session *session = from_handle(handle);
    size_t size;
    void *bytes;
    jbyteArray result;
    if (!session) return NULL;
    size = lucent_retro_save_ram_size(session->host);
    if (!size || size > INT32_MAX) return NULL;
    bytes = malloc(size);
    if (!bytes) return NULL;
    if (!lucent_retro_read_save_ram(session->host, bytes, size)) {
        free(bytes);
        return NULL;
    }
    result = (*env)->NewByteArray(env, (jsize)size);
    if (result)
        (*env)->SetByteArrayRegion(env, result, 0, (jsize)size,
                                   (const jbyte *)bytes);
    free(bytes);
    return result;
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeWriteSaveRamVulkan(
        JNIEnv *env, jclass type, jlong handle, jbyteArray save_ram) {
    (void)type;
    lucent_vulkan_jni_session *session = from_handle(handle);
    jsize size;
    jbyte *bytes;
    bool success;
    if (!session || !save_ram) {
        throw_state(env, "Vulkan save RAM is required");
        return;
    }
    size = (*env)->GetArrayLength(env, save_ram);
    bytes = (*env)->GetByteArrayElements(env, save_ram, NULL);
    success = bytes && lucent_retro_write_save_ram(
            session->host, bytes, (size_t)size);
    if (bytes) (*env)->ReleaseByteArrayElements(env, save_ram, bytes, JNI_ABORT);
    if (!success && !(*env)->ExceptionCheck(env))
        throw_state(env, "Vulkan save RAM size mismatch");
}

JNIEXPORT void JNICALL
Java_com_thorium_preview_ExperimentalVulkanLibretroHost_nativeDestroyVulkan(
        JNIEnv *env, jclass type, jlong handle) {
    (void)type;
    char error[ERROR_SIZE] = {0};
    lucent_vulkan_jni_session *session = from_handle(handle);
    if (!session) return;
    if (session->game_loaded && !lucent_retro_unload_game(
            session->host, error, sizeof(error))) {
        throw_state(env, error);
        return;
    }
    session->game_loaded = false;
    lucent_android_vulkan_destroy(session->backend);
    lucent_retro_destroy(session->host);
    free(session);
}
