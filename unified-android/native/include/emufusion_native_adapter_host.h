/*
 * EmuFusion Phase 3 native-adapter host.
 *
 * A thin, fail-closed C driver that loads a native-adapter shared library (see
 * lucent_native_adapter.h), verifies its exported entry symbol and vtable, and
 * exposes a linear lifecycle the JNI bridge and Java session drive on one
 * render-owner thread:
 *
 *   open -> describe -> create -> load -> start ->
 *     (run_frame / set_control / pause / resume / flush_save /
 *      serialize / unserialize / surface_recreated)* ->
 *   stop -> destroy
 *
 * The host owns NO engine logic. It refuses to load a library that fails any
 * validation gate, refuses serialize/unserialize when the adapter reports no
 * Quick Resume capability, and never fakes a success the adapter did not report.
 * This file contains no third-party code.
 */
#ifndef EMUFUSION_NATIVE_ADAPTER_HOST_H
#define EMUFUSION_NATIVE_ADAPTER_HOST_H

#include <stdbool.h>
#include <stddef.h>

#include "lucent_native_adapter.h"
#include "lucent_native_source_image.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct emufusion_native_adapter_host emufusion_native_adapter_host;

/*
 * Loads the adapter shared library at adapter_path, which must resolve to a real
 * file inside trusted_root (EmuFusion's app-private native library directory).
 * Resolves LUCENT_NATIVE_ADAPTER_ENTRY_SYMBOL, calls it, and validates the
 * returned vtable: non-NULL, abi_version == LUCENT_NATIVE_ADAPTER_ABI_VERSION,
 * and every function pointer present. It then calls describe() once and caches
 * the honest capability report. Returns NULL (fail closed) with a message in
 * error on any failure: dlopen failure, missing symbol, NULL vtable, ABI
 * mismatch, any NULL function pointer, or a describe() report whose
 * abi_version/engine_id is invalid.
 */
emufusion_native_adapter_host *emufusion_native_adapter_open(
        const char *adapter_path, const char *trusted_root,
        char *error, size_t error_size);

/* Optional adapter-specific JavaVM handoff. It exists for embedded adapters
 * whose upstream JNI_OnLoad also registers Activity-only Java classes that the
 * EmuFusion host deliberately does not package. The version is passed into the
 * setter, and a false return rejects the adapter before its vtable is entered. */
#define EMUFUSION_NATIVE_ADAPTER_JAVA_VM_SYMBOL \
    "lucent_native_adapter_set_java_vm"
#define EMUFUSION_NATIVE_ADAPTER_JAVA_VM_VERSION 1u

/* Caches the process JavaVM so open() can first try the versioned optional
 * setter above, then preserve the existing JNI_OnLoad behavior for adapters
 * without it (notably Eden). An adapter exporting neither hook is unaffected.
 * Call before open(); host tests may supply an opaque sentinel off Android. */
void emufusion_native_adapter_supply_java_vm(void *java_vm);

/* The engine's own averaged emulated-frame rate, or a negative value when this
 * adapter exposes no measurement hook.
 *
 * This is deliberately NOT the rate EmuFusion presents at. A surface that swaps at
 * the panel's refresh says nothing about whether the guest advanced, because a
 * repeated frame still counts as a present. Only the engine knows how many
 * emulated frames actually retired, so a 60fps claim has to come from here or
 * it is not a measurement at all. The symbol is optional and resolved by
 * dlsym; an adapter without it reports unsupported rather than zero, so
 * "unsupported" and "stalled at 0fps" stay distinguishable. */
#define EMUFUSION_NATIVE_ADAPTER_FPS_UNSUPPORTED (-1.0)
double emufusion_native_adapter_average_fps(emufusion_native_adapter_host *host);

/* Near-native clock correction. Both hooks are
 * optional adapter exports resolved by dlsym once the session is started:
 *   double lucent_native_adapter_declared_video_hz(void);
 *   bool   lucent_native_adapter_set_paced_video_hz(double hz);
 * declared_video_hz reports the guest's frame clock in Hz (0 when the adapter
 * publishes none); set_paced_video_hz asks the engine to run its frame clock at
 * a bounded correction of the original declared clock. Only explicit zero
 * restores normal timing. The host rejects non-finite, negative and greater
 * than 0.75-percent corrections before calling an adapter. */
double lucent_native_adapter_declared_video_hz(emufusion_native_adapter_host *host);
bool lucent_native_adapter_set_paced_video_hz(emufusion_native_adapter_host *host,
                                              double hz);

/* Optional version-1 timing capabilities. Missing exports mean unknown, not
 * an inferred 60-Hz source. Submission timestamps and VI callback counts are
 * diagnostics: neither establishes guest-image identity or content cadence.
 * AUTHORITATIVE_SOURCE_TIMELINE additionally requires a finite positive
 * lucent_native_adapter_producer_timeline_hz() export. An adapter may set that
 * bit only once image-linked source timing is implemented and available. */
uint32_t emufusion_native_adapter_timing_capabilities(emufusion_native_adapter_host *host);
double lucent_native_adapter_producer_timeline_hz(emufusion_native_adapter_host *host);

/* Exact consumed-image sideband, independent of source-timeline authority.
 * Calls copy bounded values without waiting. Caller must retain the host and
 * exclude stop/destroy for the duration of the call (Java uses a try-read lease).
 * Missing exports return UNSUPPORTED, never an assumed source image. */
uint32_t emufusion_native_adapter_source_image_binding(emufusion_native_adapter_host *host,
        lucent_source_binding_v1 *out, uint32_t out_size);
uint32_t emufusion_native_adapter_query_source_image(emufusion_native_adapter_host *host,
        uint64_t session_epoch, uint64_t surface_epoch, uint64_t buffer_timestamp_ns,
        lucent_source_image_v1 *out, uint32_t out_size);

/* Copies the cached, validated capability report. Callable any time after a
 * successful open(), including before create(). Returns false only when host or
 * out is NULL. */
bool emufusion_native_adapter_describe(const emufusion_native_adapter_host *host,
                                    lucent_native_capabilities *out,
                                    char *error, size_t error_size);

/* Allocates the adapter's per-session engine. Fails if already created or the
 * adapter returns NULL. */
bool emufusion_native_adapter_create(emufusion_native_adapter_host *host,
                                  char *error, size_t error_size);

/* Validates and loads content + firmware. Fails closed when the request or its
 * content_path is NULL, before the adapter is consulted. */
/* Optional presentation tagging, configured on the owner before start/rebind.
 * Missing hooks return false and leave existing adapter behavior unchanged. */
bool emufusion_native_adapter_set_fg_presentation(emufusion_native_adapter_host *host,
                                              bool enabled);

bool emufusion_native_adapter_load(emufusion_native_adapter_host *host,
                                const lucent_native_load_request *request,
                                char *error, size_t error_size);

/* Binds EmuFusion-owned render/audio IO. Fails closed when io or its primary
 * window is NULL. */
bool emufusion_native_adapter_start(emufusion_native_adapter_host *host,
                                 const lucent_native_io *io,
                                 char *error, size_t error_size);

/* Advances and presents one frame. Fails when not started or the adapter
 * reports a fatal error. */
bool emufusion_native_adapter_run_frame(emufusion_native_adapter_host *host,
                                     char *error, size_t error_size);

/* Delivers one canonical control value for the given controller_index (0 is
 * the primary/local player). Fails when not started. */
bool emufusion_native_adapter_set_control(emufusion_native_adapter_host *host,
                                       uint32_t controller_index,
                                       lucent_native_control control,
                                       float value,
                                       char *error, size_t error_size);

bool emufusion_native_adapter_pause(emufusion_native_adapter_host *host,
                                 char *error, size_t error_size);
bool emufusion_native_adapter_resume(emufusion_native_adapter_host *host,
                                  char *error, size_t error_size);

/* Flushes normal game saves durably. Propagates the adapter's fail-closed
 * result so EmuFusion never reports a clean exit over an uncommitted save. */
bool emufusion_native_adapter_flush_save(emufusion_native_adapter_host *host,
                                      char *error, size_t error_size);

/* Full-state serialization. These refuse (0 / false) whenever the adapter's
 * cached capability report has has_quick_resume == false, without calling the
 * adapter, so EmuFusion cannot advertise a Quick Resume the engine cannot honor.
 * serialize() writes at most capacity bytes and reports the count in *written;
 * a NULL out with capacity 0 queries the required size in *written. */
size_t emufusion_native_adapter_serialize_size(emufusion_native_adapter_host *host);
bool emufusion_native_adapter_serialize(emufusion_native_adapter_host *host,
                                     void *out, size_t capacity,
                                     size_t *written,
                                     char *error, size_t error_size);
bool emufusion_native_adapter_unserialize(emufusion_native_adapter_host *host,
                                       const void *data, size_t size,
                                       char *error, size_t error_size);

/* Re-binds rendering after an Android surface loss. */
bool emufusion_native_adapter_surface_recreated(emufusion_native_adapter_host *host,
                                             const lucent_native_io *io,
                                             char *error, size_t error_size);

/* Bounded synchronous stop; the render owner has already quiesced. Safe to call
 * more than once. */
bool emufusion_native_adapter_stop(emufusion_native_adapter_host *host,
                                char *error, size_t error_size);

/* Destroys the engine (if created) and unloads the library. host is invalid
 * afterward; NULL is tolerated. */
void emufusion_native_adapter_destroy(emufusion_native_adapter_host *host);

/* True once the cached report advertises the capability. Convenience for the
 * JNI bridge; false when host is NULL. */
bool emufusion_native_adapter_has_quick_resume(const emufusion_native_adapter_host *host);
bool emufusion_native_adapter_has_persistent_save(const emufusion_native_adapter_host *host);
bool emufusion_native_adapter_dual_screen(const emufusion_native_adapter_host *host);
/* How many controller_index values 0..N-1 set_control() actually honors.
 * Always >= 1 (open() rejects a describe() report claiming 0). Returns 1 for
 * a NULL host so an unopened/failed host reads as single-player. */
uint32_t emufusion_native_adapter_max_controllers(const emufusion_native_adapter_host *host);

#ifdef __cplusplus
}
#endif

#endif /* EMUFUSION_NATIVE_ADAPTER_HOST_H */
