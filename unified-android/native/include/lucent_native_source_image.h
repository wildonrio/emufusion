#ifndef LUCENT_NATIVE_SOURCE_IMAGE_H
#define LUCENT_NATIVE_SOURCE_IMAGE_H
#include <stdint.h>

/* Value-only diagnostic ABI. Queue provenance is not pixel-change, retired
 * guest-time or physical-presentation proof; this grants no source authority. */
#define LUCENT_SOURCE_IMAGE_VERSION 1u
#define LUCENT_SOURCE_IMAGE_MAX_LAYERS 8u
#define LUCENT_SOURCE_IMAGE_RING_CAPACITY 128u
enum lucent_source_image_result {
    LUCENT_SOURCE_MATCH_ACCEPTED = 1,
    LUCENT_SOURCE_PENDING = 2,
    LUCENT_SOURCE_BUSY = 3,
    LUCENT_SOURCE_NOT_FOUND = 4,
    LUCENT_SOURCE_AMBIGUOUS = 5,
    LUCENT_SOURCE_REJECTED = 6,
    LUCENT_SOURCE_UNSUPPORTED = 7,
    LUCENT_SOURCE_CLOSED = 8,
    LUCENT_SOURCE_BAD_ARGUMENT = 9,
    LUCENT_SOURCE_STALE_EPOCH = 10
};
enum lucent_source_layer_flags {
    LUCENT_SOURCE_LAYER_ACQUIRED = 1u,
    LUCENT_SOURCE_LAYER_HELD = 2u,
    LUCENT_SOURCE_LAYER_OVERLAY = 4u,
    LUCENT_SOURCE_LAYER_AUTO_TIMESTAMP = 8u
};
enum lucent_source_composition_flags {
    LUCENT_SOURCE_COMPOSITION_COMPLETE = 1u,
    LUCENT_SOURCE_COMPOSITION_TOO_MANY_LAYERS = 2u,
    LUCENT_SOURCE_COMPOSITION_INCONSISTENT = 4u
};
typedef struct lucent_source_layer_v1 {
    uint64_t queue_epoch;
    uint64_t queue_frame_number;
    int64_t guest_requested_timestamp_ns; /* Domain unknown; never Android time. */
    int32_t consumer_id;
    int32_t buffer_slot; /* Reusable allocation slot, not source identity. */
    int32_t raw_swap_interval;
    int32_t normalized_swap_interval;
    uint32_t flags;
    uint32_t width;
    uint32_t height;
    uint32_t stride;
    uint32_t pixel_format;
    int32_t z_index;
    uint32_t transform;
    uint32_t blending;
    int32_t crop_left;
    int32_t crop_top;
    int32_t crop_right;
    int32_t crop_bottom;
} lucent_source_layer_v1;
typedef struct lucent_source_composition_header_v1 {
    uint64_t session_epoch;
    uint64_t surface_epoch;
    uint64_t swapchain_epoch;
    uint64_t display_id;
    uint64_t composition_ordinal;
    uint64_t observed_monotonic_ns; /* Composition observation, not guest time. */
    uint32_t layer_count; /* Full visible count, including any unsupported suffix. */
    uint32_t flags;
} lucent_source_composition_header_v1;
typedef struct lucent_source_composition_v1 {
    lucent_source_composition_header_v1 header;
    uint32_t retained_layer_count;
    uint32_t reserved;
    lucent_source_layer_v1 layers[LUCENT_SOURCE_IMAGE_MAX_LAYERS];
} lucent_source_composition_v1;
typedef struct lucent_source_image_v1 {
    uint32_t version;
    uint32_t struct_size;
    uint32_t state;
    int32_t vk_present_result;
    uint64_t submission_ordinal;
    uint64_t buffer_timestamp_ns; /* Exact Vulkan desiredPresentTime join key. */
    uint32_t vk_present_id;
    uint32_t swapchain_image_index;
    lucent_source_composition_v1 composition;
} lucent_source_image_v1;
typedef struct lucent_source_binding_v1 {
    uint32_t version;
    uint32_t struct_size;
    uint64_t session_epoch;
    uint64_t surface_epoch;
    uint64_t swapchain_epoch;
    uint64_t skipped_busy;
    uint64_t evicted;
    uint64_t ambiguous;
    uint64_t unsupported;
} lucent_source_binding_v1;
#endif
