#define _XOPEN_SOURCE 700

#include "include/lucent_native_adapter_host.h"

#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

static void *adapter_java_vm;

#define MAX_JNI_INITIALIZED_ADAPTERS 16
static pthread_mutex_t adapter_jni_onload_lock = PTHREAD_MUTEX_INITIALIZER;
static void *adapter_jni_initialized[MAX_JNI_INITIALIZED_ADAPTERS];
static size_t adapter_jni_initialized_count;

typedef int (*fn_lucent_set_java_vm)(uint32_t, void *);

static void set_error(char *buffer, size_t size, const char *format, ...);

void lucent_native_adapter_supply_java_vm(void *java_vm) {
    adapter_java_vm = java_vm;
}

#if defined(__ANDROID__)
#include <android/log.h>
#include <jni.h>

/* Android invokes JNI_OnLoad only for libraries opened through
 * System.loadLibrary. Lucent opens an adapter with dlopen, so an adapter that
 * embeds an Android frontend never gets its JNI state initialised: Eden caches
 * the process JavaVM there, and without it Common::Android::GetEnvForThread()
 * returns null and the first helper thread that reaches for a JNIEnv dies on a
 * null dereference. The bridge hands us the VM in JNI_OnLoad and we perform the
 * call Android would have made. The same problem is solved for libretro cores
 * by lucent_retro_supply_android_java_vm; an adapter differs only in exporting
 * the standard entry point rather than a Lucent-specific setter. */
/* Android's linker returns the same soinfo/handle when the same absolute
 * adapter path is opened again. JNI_OnLoad is a process-lifetime hook, not a
 * per-session hook, so invoking it on every NativeAdapterHost construction is
 * both incorrect and expensive for Eden's very large JNI library. Keep the
 * small set of successfully initialised adapter handles process-wide. This
 * also makes background preloading safe: the later gameplay session reuses the
 * already relocated library without re-running Eden's JNI bootstrap. */
typedef jint (*fn_jni_on_load)(JavaVM *, void *);
#endif

/* Prefer a Lucent-specific, ABI-versioned handoff. aPS3e uses this because its
 * JNI_OnLoad unconditionally registers upstream Activity classes; invoking it
 * in the unified app aborts ART before a Java error can be reported. Adapters
 * without the setter retain the old JNI_OnLoad path exactly. */
static bool supply_java_vm_to_adapter(void *library,
                                      char *error, size_t error_size) {
    fn_lucent_set_java_vm set_vm = NULL;
    void *setter_symbol;
#if defined(__ANDROID__)
    fn_jni_on_load on_load = NULL;
    void *on_load_symbol;
    jint version;
#endif
    if (!library || !adapter_java_vm) return true;
    pthread_mutex_lock(&adapter_jni_onload_lock);
    for (size_t index = 0; index < adapter_jni_initialized_count; ++index) {
        if (adapter_jni_initialized[index] == library) {
            pthread_mutex_unlock(&adapter_jni_onload_lock);
            return true;
        }
    }
    dlerror();
    setter_symbol = dlsym(library, LUCENT_NATIVE_ADAPTER_JAVA_VM_SYMBOL);
    if (setter_symbol) {
        int accepted;
        memcpy(&set_vm, &setter_symbol, sizeof(set_vm));
        accepted = set_vm(LUCENT_NATIVE_ADAPTER_JAVA_VM_VERSION,
                          adapter_java_vm);
        if (!accepted) {
            set_error(error, error_size,
                      "adapter rejected JavaVM handoff version %u",
                      LUCENT_NATIVE_ADAPTER_JAVA_VM_VERSION);
            pthread_mutex_unlock(&adapter_jni_onload_lock);
            return false;
        }
        if (adapter_jni_initialized_count < MAX_JNI_INITIALIZED_ADAPTERS)
            adapter_jni_initialized[adapter_jni_initialized_count++] = library;
        pthread_mutex_unlock(&adapter_jni_onload_lock);
#if defined(__ANDROID__)
        __android_log_print(ANDROID_LOG_INFO, "LucentNativeAdapter",
                "adapter accepted versioned JavaVM handoff version=%u",
                LUCENT_NATIVE_ADAPTER_JAVA_VM_VERSION);
#endif
        return true;
    }
#if defined(__ANDROID__)
    dlerror();
    on_load_symbol = dlsym(library, "JNI_OnLoad");
    if (!on_load_symbol) {
        pthread_mutex_unlock(&adapter_jni_onload_lock);
        return true;
    }
    memcpy(&on_load, &on_load_symbol, sizeof(on_load));
    version = on_load((JavaVM *)adapter_java_vm, NULL);
    if (version >= JNI_VERSION_1_6 &&
            adapter_jni_initialized_count < MAX_JNI_INITIALIZED_ADAPTERS) {
        adapter_jni_initialized[adapter_jni_initialized_count++] = library;
    }
    pthread_mutex_unlock(&adapter_jni_onload_lock);
    __android_log_print(version >= JNI_VERSION_1_6 ? ANDROID_LOG_INFO
                                                   : ANDROID_LOG_ERROR,
            "LucentNativeAdapter",
            "adapter JNI_OnLoad returned 0x%x for JavaVM %p", version,
            adapter_java_vm);
    if (version < JNI_VERSION_1_6) {
        set_error(error, error_size, "adapter JNI_OnLoad rejected the JavaVM");
        return false;
    }
    return true;
#else
    pthread_mutex_unlock(&adapter_jni_onload_lock);
    return true;
#endif
}

struct lucent_native_adapter_host {
    void *library;
    const lucent_native_adapter *vtable;
    lucent_native_engine *engine;
    lucent_native_capabilities capabilities;
    uint32_t (*source_binding)(lucent_source_binding_v1 *, uint32_t);
    uint32_t (*source_query)(uint64_t, uint64_t, uint64_t, lucent_source_image_v1 *, uint32_t);
    bool loaded;
    bool started;
    bool stopped;
};

static void set_error(char *buffer, size_t size, const char *format, ...) {
    va_list args;
    if (!buffer || !size) return;
    va_start(args, format);
    vsnprintf(buffer, size, format, args);
    va_end(args);
}

/* True when path is the trusted root itself or lies beneath it. Both arguments
 * must already be canonical (realpath) absolute paths. */
static bool path_is_inside(const char *path, const char *root) {
    size_t length = strlen(root);
    if (length == 0) return false;
    if (strcmp(path, root) == 0) return true;
    return strncmp(path, root, length) == 0 &&
           (root[length - 1] == '/' || path[length] == '/');
}

/* Every vtable function pointer is required. A no-op is expressed by a function
 * that returns the documented failure value, never by a NULL slot. */
static bool vtable_is_complete(const lucent_native_adapter *vtable) {
    return vtable->describe && vtable->create && vtable->load &&
           vtable->start && vtable->run_frame && vtable->set_control &&
           vtable->pause && vtable->resume && vtable->flush_save &&
           vtable->serialize_size && vtable->serialize && vtable->unserialize &&
           vtable->surface_recreated && vtable->stop && vtable->destroy;
}

lucent_native_adapter_host *lucent_native_adapter_open(
        const char *adapter_path, const char *trusted_root,
        char *error, size_t error_size) {
    char resolved_adapter[PATH_MAX];
    char resolved_root[PATH_MAX];
    lucent_native_adapter_entry_fn entry;
    const lucent_native_adapter *vtable;
    lucent_native_adapter_host *host;
    void *library;
    void *symbol;
    lucent_native_capabilities capabilities;

    if (!adapter_path || !trusted_root) {
        set_error(error, error_size, "adapter path and trusted root are required");
        return NULL;
    }
    if (!realpath(adapter_path, resolved_adapter) ||
            !realpath(trusted_root, resolved_root)) {
        set_error(error, error_size, "cannot resolve adapter path: %s",
                  strerror(errno));
        return NULL;
    }
    if (strcmp(resolved_root, "/") == 0 ||
            !path_is_inside(resolved_adapter, resolved_root)) {
        set_error(error, error_size,
                  "adapter must be inside Lucent's trusted directory");
        return NULL;
    }

    library = dlopen(resolved_adapter, RTLD_NOW | RTLD_LOCAL);
    if (!library) {
        set_error(error, error_size, "cannot load adapter: %s", dlerror());
        return NULL;
    }
    /* Before the entry point runs, so no adapter thread can reach for a JNIEnv
     * that has not been established yet. */
    if (!supply_java_vm_to_adapter(library, error, error_size)) {
        dlclose(library);
        return NULL;
    }
    dlerror();
    symbol = dlsym(library, LUCENT_NATIVE_ADAPTER_ENTRY_SYMBOL);
    if (!symbol || dlerror()) {
        set_error(error, error_size, "adapter is missing required symbol %s",
                  LUCENT_NATIVE_ADAPTER_ENTRY_SYMBOL);
        dlclose(library);
        return NULL;
    }
    memcpy(&entry, &symbol, sizeof(entry));
    vtable = entry();
    if (!vtable) {
        set_error(error, error_size, "adapter entry returned no vtable");
        dlclose(library);
        return NULL;
    }
    if (vtable->abi_version != LUCENT_NATIVE_ADAPTER_ABI_VERSION) {
        set_error(error, error_size,
                  "unsupported adapter ABI %u (expected %u)",
                  vtable->abi_version, LUCENT_NATIVE_ADAPTER_ABI_VERSION);
        dlclose(library);
        return NULL;
    }
    if (!vtable_is_complete(vtable)) {
        set_error(error, error_size, "adapter vtable has a null function pointer");
        dlclose(library);
        return NULL;
    }

    /* describe() is pure and callable before create(); validate its honest
     * report now and cache it so capability gating never re-enters the adapter. */
    memset(&capabilities, 0, sizeof(capabilities));
    vtable->describe(&capabilities);
    if (capabilities.abi_version != LUCENT_NATIVE_ADAPTER_ABI_VERSION ||
            !capabilities.engine_id || !capabilities.engine_id[0] ||
            capabilities.max_controllers == 0) {
        set_error(error, error_size,
                  "adapter describe() reported an invalid capability record");
        dlclose(library);
        return NULL;
    }

    host = (lucent_native_adapter_host *)calloc(1, sizeof(*host));
    if (!host) {
        set_error(error, error_size, "out of memory creating adapter host");
        dlclose(library);
        return NULL;
    }
    host->library = library;
    host->vtable = vtable;
    host->capabilities = capabilities;
    /* Resolve optional hot-path queries once during setup, not under a live
     * renderer deadline where dlsym may contend on the dynamic-linker lock. */
    void *binding_symbol = dlsym(library, "lucent_native_adapter_source_image_binding_v1");
    void *query_symbol = dlsym(library, "lucent_native_adapter_query_source_image_v1");
    if (binding_symbol) memcpy(&host->source_binding, &binding_symbol, sizeof(host->source_binding));
    if (query_symbol) memcpy(&host->source_query, &query_symbol, sizeof(host->source_query));
#if defined(__ANDROID__)
    __android_log_print(ANDROID_LOG_INFO, "LucentNativeAdapter",
            "adapter loaded engine=%s version=%s abi=%u quickResume=%d "
            "persistentSave=%d dualScreen=%d maxControllers=%u",
            capabilities.engine_id,
            capabilities.engine_version ? capabilities.engine_version : "",
            capabilities.abi_version, capabilities.has_quick_resume ? 1 : 0,
            capabilities.has_persistent_save ? 1 : 0,
            capabilities.dual_screen ? 1 : 0,
            capabilities.max_controllers);
#endif
    return host;
}

bool lucent_native_adapter_describe(const lucent_native_adapter_host *host,
                                    lucent_native_capabilities *out,
                                    char *error, size_t error_size) {
    if (!host || !out) {
        set_error(error, error_size, "host and output record are required");
        return false;
    }
    *out = host->capabilities;
    return true;
}

bool lucent_native_adapter_create(lucent_native_adapter_host *host,
                                  char *error, size_t error_size) {
    if (!host) {
        set_error(error, error_size, "host is required");
        return false;
    }
    if (host->engine) {
        set_error(error, error_size, "adapter session already created");
        return false;
    }
    host->engine = host->vtable->create();
    if (!host->engine) {
        set_error(error, error_size, "adapter could not allocate a session");
        return false;
    }
    host->loaded = false;
    host->started = false;
    host->stopped = false;
    return true;
}

bool lucent_native_adapter_load(lucent_native_adapter_host *host,
                                const lucent_native_load_request *request,
                                char *error, size_t error_size) {
    char adapter_error[256] = {0};
    if (!host || !host->engine) {
        set_error(error, error_size, "adapter session is not created");
        return false;
    }
    /* Fail closed before the adapter is consulted: content is mandatory. */
    if (!request || !request->content_path || !request->content_path[0]) {
        set_error(error, error_size, "adapter load requires a content path");
        return false;
    }
    if (!host->vtable->load(host->engine, request, adapter_error,
                            sizeof(adapter_error))) {
        set_error(error, error_size, "adapter rejected content: %s",
                  adapter_error[0] ? adapter_error : "unsupported or missing firmware");
        return false;
    }
    host->loaded = true;
    return true;
}

bool lucent_native_adapter_start(lucent_native_adapter_host *host,
                                 const lucent_native_io *io,
                                 char *error, size_t error_size) {
    char adapter_error[256] = {0};
    if (!host || !host->engine || !host->loaded) {
        set_error(error, error_size, "adapter content is not loaded");
        return false;
    }
    if (!io || !io->primary_window) {
        set_error(error, error_size, "adapter start requires a primary window");
        return false;
    }
    if (!host->vtable->start(host->engine, io, adapter_error,
                             sizeof(adapter_error))) {
        set_error(error, error_size, "adapter could not start: %s",
                  adapter_error[0] ? adapter_error : "render device init failed");
        return false;
    }
    host->started = true;
    host->stopped = false;
    return true;
}

bool lucent_native_adapter_run_frame(lucent_native_adapter_host *host,
                                     char *error, size_t error_size) {
    if (!host || !host->engine || !host->started || host->stopped) {
        set_error(error, error_size, "adapter is not running");
        return false;
    }
    if (!host->vtable->run_frame(host->engine)) {
        set_error(error, error_size, "adapter reported a fatal frame error");
        return false;
    }
    return true;
}

bool lucent_native_adapter_set_control(lucent_native_adapter_host *host,
                                       uint32_t controller_index,
                                       lucent_native_control control,
                                       float value,
                                       char *error, size_t error_size) {
    if (!host || !host->engine || !host->started) {
        set_error(error, error_size, "adapter is not running");
        return false;
    }
    host->vtable->set_control(host->engine, controller_index, control, value);
    return true;
}

bool lucent_native_adapter_pause(lucent_native_adapter_host *host,
                                 char *error, size_t error_size) {
    if (!host || !host->engine || !host->started) {
        set_error(error, error_size, "adapter is not running");
        return false;
    }
    host->vtable->pause(host->engine);
    return true;
}

bool lucent_native_adapter_resume(lucent_native_adapter_host *host,
                                  char *error, size_t error_size) {
    if (!host || !host->engine || !host->started) {
        set_error(error, error_size, "adapter is not running");
        return false;
    }
    host->vtable->resume(host->engine);
    return true;
}

bool lucent_native_adapter_flush_save(lucent_native_adapter_host *host,
                                      char *error, size_t error_size) {
    if (!host || !host->engine || !host->loaded) {
        set_error(error, error_size, "adapter content is not loaded");
        return false;
    }
    if (!host->vtable->flush_save(host->engine)) {
        set_error(error, error_size, "adapter could not commit a durable save");
        return false;
    }
    return true;
}

size_t lucent_native_adapter_serialize_size(lucent_native_adapter_host *host) {
    if (!host || !host->engine || !host->started) return 0;
    /* Never advertise a Quick Resume the engine cannot guarantee. */
    if (!host->capabilities.has_quick_resume) return 0;
    return host->vtable->serialize_size(host->engine);
}

bool lucent_native_adapter_serialize(lucent_native_adapter_host *host,
                                     void *out, size_t capacity,
                                     size_t *written,
                                     char *error, size_t error_size) {
    size_t count;
    if (written) *written = 0;
    if (!host || !host->engine || !host->started) {
        set_error(error, error_size, "adapter is not running");
        return false;
    }
    if (!host->capabilities.has_quick_resume) {
        set_error(error, error_size,
                  "adapter does not support Quick Resume serialization");
        return false;
    }
    /* A NULL out with zero capacity is the documented size query. */
    if (!out && capacity != 0) {
        set_error(error, error_size, "serialize buffer is required");
        return false;
    }
    count = host->vtable->serialize(host->engine, out, capacity);
    if (count == 0) {
        set_error(error, error_size, "adapter produced no serialized state");
        return false;
    }
    if (out && count > capacity) {
        set_error(error, error_size, "adapter overran the serialize buffer");
        return false;
    }
    if (written) *written = count;
    return true;
}

bool lucent_native_adapter_unserialize(lucent_native_adapter_host *host,
                                       const void *data, size_t size,
                                       char *error, size_t error_size) {
    if (!host || !host->engine || !host->started) {
        set_error(error, error_size, "adapter is not running");
        return false;
    }
    if (!host->capabilities.has_quick_resume) {
        set_error(error, error_size,
                  "adapter does not support Quick Resume restore");
        return false;
    }
    if (!data || size == 0) {
        set_error(error, error_size, "serialized state is required");
        return false;
    }
    if (!host->vtable->unserialize(host->engine, data, size)) {
        set_error(error, error_size, "adapter rejected the serialized state");
        return false;
    }
    return true;
}

bool lucent_native_adapter_surface_recreated(lucent_native_adapter_host *host,
                                             const lucent_native_io *io,
                                             char *error, size_t error_size) {
    if (!host || !host->engine || !host->started) {
        set_error(error, error_size, "adapter is not running");
        return false;
    }
    if (!io || !io->primary_window) {
        set_error(error, error_size, "surface_recreated requires a primary window");
        return false;
    }
    if (!host->vtable->surface_recreated(host->engine, io)) {
        set_error(error, error_size, "adapter could not rebind its render surface");
        return false;
    }
    return true;
}

bool lucent_native_adapter_stop(lucent_native_adapter_host *host,
                                char *error, size_t error_size) {
    if (!host) {
        set_error(error, error_size, "adapter session is not created");
        return false;
    }
    /* Preparation may reject missing user firmware after open/describe but
     * before create. There is no engine to stop in that state; let the owner
     * close its wrapper instead of permanently retaining a failed session. */
    if (!host->engine) return true;
    if (host->stopped) return true;
    host->vtable->stop(host->engine);
    host->started = false;
    host->stopped = true;
    return true;
}

void lucent_native_adapter_destroy(lucent_native_adapter_host *host) {
    if (!host) return;
    if (host->engine) {
        if (host->started && !host->stopped) host->vtable->stop(host->engine);
        host->vtable->destroy(host->engine);
        host->engine = NULL;
    }
    /*
     * The engine library is DELIBERATELY left mapped.
     *
     * dlclose() does not merely drop a mapping: the linker runs the library's
     * static destructors through __cxa_finalize first. For a 23 MB emulator
     * core that means destroying every file-scope object it owns, and neither
     * of the engines behind this ABI is built to survive that.
     *
     * Cemu is the measured case. It is a one-title-per-process emulator whose
     * own Android frontend calls exitProcess(0) when the user quits, so it has
     * no path that returns the library to a pristine state and never joins
     * several of its file-scope std::thread objects -- the title-list refresh
     * worker and the IOSU service threads among them. ~std::thread on a thread
     * that is still joinable calls std::terminate() by definition, so unloading
     * the library killed the whole app on the way out of a Wii U session:
     *
     *     #04 std::terminate()
     *     #05 std::__ndk1::thread::~thread()
     *     #06 __cxa_finalize
     *     #07 soinfo::call_destructors()
     *     #09 do_dlclose
     *     #12 lucent_native_adapter_destroy
     *     #18 NativeAdapterEngineSession.closeHost
     *
     * Even without that abort the unload would be unsound: both engines spawn
     * DETACHED threads (Cemu's PPC timer calibration, its ThreadPool
     * fire-and-forget work and its title thread; Eden's equivalents), and this
     * host has no way to know they have finished. Unmapping the code they are
     * executing is a dangling-code-pointer crash waiting for the next
     * scheduling slice.
     *
     * Keeping it mapped is also what the adapters already assume: the Cemu
     * adapter's process-wide one-shot initialisation exists precisely because
     * the library stays loaded and a second title launches into the same
     * process. Costing address space in a process that will dlopen the same
     * path again is the cheap side of this trade.
     *
     * The dlclose() calls on the LOAD-FAILURE paths above are unaffected and
     * still correct: nothing in the engine has run at that point.
     */
    free(host);
}

bool lucent_native_adapter_has_quick_resume(
        const lucent_native_adapter_host *host) {
    return host && host->capabilities.has_quick_resume;
}

bool lucent_native_adapter_has_persistent_save(
        const lucent_native_adapter_host *host) {
    return host && host->capabilities.has_persistent_save;
}

uint32_t lucent_native_adapter_max_controllers(
        const lucent_native_adapter_host *host) {
    return host ? host->capabilities.max_controllers : 1u;
}

bool lucent_native_adapter_dual_screen(
        const lucent_native_adapter_host *host) {
    return host && host->capabilities.dual_screen;
}

double lucent_native_adapter_average_fps(lucent_native_adapter_host *host) {
    /* Optional and resolved per call rather than cached at open(), because an
     * adapter is free to publish the hook only once a session is live. */
    static const char standard_symbol[] =
            "lucent_native_adapter_average_game_fps";
    static const char fps_symbol[] = "lucent_eden_average_game_fps";
    double (*reader)(void) = NULL;
    void *symbol;
    if (!host || !host->library || !host->started) {
        return LUCENT_NATIVE_ADAPTER_FPS_UNSUPPORTED;
    }
    dlerror();
    symbol = dlsym(host->library, standard_symbol);
    if (!symbol && host->capabilities.engine_id &&
            strcmp(host->capabilities.engine_id, "eden") == 0) {
        dlerror();
        symbol = dlsym(host->library, fps_symbol);
    }
    if (!symbol) return LUCENT_NATIVE_ADAPTER_FPS_UNSUPPORTED;
    memcpy(&reader, &symbol, sizeof(reader));
    return reader();
}

bool lucent_native_adapter_set_fg_presentation(lucent_native_adapter_host *host,
                                              bool enabled) {
    void (*setter)(bool) = NULL;
    void *symbol;
    if (!host || !host->library || !host->loaded) return false;
    dlerror();
    symbol = dlsym(host->library, "lucent_native_adapter_set_fg_presentation_v1");
    if (!symbol) return false;
    memcpy(&setter, &symbol, sizeof(setter));
    setter(enabled);
    return true;
}

double lucent_native_adapter_declared_video_hz(lucent_native_adapter_host *host) {
    double (*reader)(void) = NULL;
    void *symbol;
    if (!host || !host->library || !host->started) return 0.0;
    dlerror();
    symbol = dlsym(host->library, "lucent_native_adapter_declared_video_hz");
    if (!symbol) return 0.0;
    memcpy(&reader, &symbol, sizeof(reader));
    return reader();
}

bool lucent_native_adapter_set_paced_video_hz(lucent_native_adapter_host *host,
                                              double hz) {
    bool (*setter)(double) = NULL;
    void *symbol;
    if (!host || !host->library || !host->started) return false;
    if (hz != 0.0) {
        double declared = lucent_native_adapter_declared_video_hz(host);
        if (!isfinite(declared) || declared <= 1.0 || declared >= 1000.0 ||
            !isfinite(hz) || hz <= 1.0 || hz >= 1000.0 ||
            fabs(hz / declared - 1.0) > 0.0075 + 1.0e-12) return false;
    }
    dlerror();
    symbol = dlsym(host->library, "lucent_native_adapter_set_paced_video_hz");
    if (!symbol) return false;
    memcpy(&setter, &symbol, sizeof(setter));
    return setter(hz);
}

uint32_t lucent_native_adapter_timing_capabilities(lucent_native_adapter_host *host) {
    uint32_t (*reader)(void) = NULL;
    void *symbol;
    if (!host || !host->library || !host->started) return 0u;
    dlerror();
    symbol = dlsym(host->library, "lucent_native_adapter_timing_capabilities_v1");
    if (!symbol) return 0u;
    memcpy(&reader, &symbol, sizeof(reader));
    return reader() & (LUCENT_NATIVE_TIMING_BASE_CLOCK_CORRECTION |
                       LUCENT_NATIVE_TIMING_SUBMISSION_TIMESTAMPS |
                       LUCENT_NATIVE_TIMING_AUTHORITATIVE_SOURCE_TIMELINE);
}

double lucent_native_adapter_producer_timeline_hz(lucent_native_adapter_host *host) {
    double (*reader)(void) = NULL;
    void *symbol;
    if (!(lucent_native_adapter_timing_capabilities(host) &
            LUCENT_NATIVE_TIMING_AUTHORITATIVE_SOURCE_TIMELINE)) return 0.0;
    dlerror();
    symbol = dlsym(host->library, "lucent_native_adapter_producer_timeline_hz");
    if (!symbol) return 0.0;
    memcpy(&reader, &symbol, sizeof(reader));
    double hz = reader();
    return isfinite(hz) && hz > 1.0 && hz < 1000.0 ? hz : 0.0;
}

uint32_t lucent_native_adapter_source_image_binding(lucent_native_adapter_host *host,
        lucent_source_binding_v1 *out, uint32_t out_size) {
    if (!out || out_size < sizeof(*out)) return LUCENT_SOURCE_BAD_ARGUMENT;
    memset(out, 0, sizeof(*out));
    if (!host || !host->library || !host->started) return LUCENT_SOURCE_CLOSED;
    if (!host->source_binding) return LUCENT_SOURCE_UNSUPPORTED;
    uint32_t result = host->source_binding(out, out_size);
    if (result == LUCENT_SOURCE_MATCH_ACCEPTED &&
            (out->version != LUCENT_SOURCE_IMAGE_VERSION || out->struct_size != sizeof(*out) ||
             !out->session_epoch || !out->surface_epoch)) {
        memset(out, 0, sizeof(*out));
        return LUCENT_SOURCE_BAD_ARGUMENT;
    }
    return result;
}

uint32_t lucent_native_adapter_query_source_image(lucent_native_adapter_host *host,
        uint64_t session_epoch, uint64_t surface_epoch, uint64_t buffer_timestamp_ns,
        lucent_source_image_v1 *out, uint32_t out_size) {
    if (!out || out_size < sizeof(*out) || !session_epoch || !surface_epoch || !buffer_timestamp_ns)
        return LUCENT_SOURCE_BAD_ARGUMENT;
    memset(out, 0, sizeof(*out));
    if (!host || !host->library || !host->started) return LUCENT_SOURCE_CLOSED;
    if (!host->source_query) return LUCENT_SOURCE_UNSUPPORTED;
    uint32_t result = host->source_query(session_epoch, surface_epoch, buffer_timestamp_ns, out, out_size);
    if (result == LUCENT_SOURCE_MATCH_ACCEPTED || result == LUCENT_SOURCE_PENDING ||
            result == LUCENT_SOURCE_AMBIGUOUS || result == LUCENT_SOURCE_REJECTED) {
        if (out->version != LUCENT_SOURCE_IMAGE_VERSION || out->struct_size != sizeof(*out) ||
                out->state != result || out->buffer_timestamp_ns != buffer_timestamp_ns ||
                out->composition.header.session_epoch != session_epoch ||
                out->composition.header.surface_epoch != surface_epoch ||
                out->composition.retained_layer_count > LUCENT_SOURCE_IMAGE_MAX_LAYERS) {
            memset(out, 0, sizeof(*out));
            return LUCENT_SOURCE_BAD_ARGUMENT;
        }
    }
    return result;
}
