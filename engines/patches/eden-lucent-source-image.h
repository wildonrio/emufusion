// SPDX-FileCopyrightText: 2026 EmuFusion contributors
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "lucent_source_image_types.h"
#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <limits>
#include <mutex>
#include <time.h>
#include <type_traits>

namespace Lucent {
inline std::atomic<uint64_t> g_source_epoch_counter{1};
inline uint64_t NextSourceEpoch() {
    return g_source_epoch_counter.fetch_add(1, std::memory_order_relaxed);
}
inline uint64_t SourceMonotonicNs() {
    timespec now{};
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0 || now.tv_sec < 0) return 0;
    return static_cast<uint64_t>(now.tv_sec) * 1000000000ULL + now.tv_nsec;
}
inline bool SameCompositionHeader(const lucent_source_composition_header_v1& a,
                                  const lucent_source_composition_header_v1& b) {
    return a.session_epoch == b.session_epoch && a.surface_epoch == b.surface_epoch &&
           a.swapchain_epoch == b.swapchain_epoch && a.display_id == b.display_id &&
           a.composition_ordinal == b.composition_ordinal &&
           a.observed_monotonic_ns == b.observed_monotonic_ns &&
           a.layer_count == b.layer_count && a.flags == b.flags;
}
inline void AppendSourceLayer(lucent_source_composition_v1& result,
                              const lucent_source_composition_header_v1& header,
                              const lucent_source_layer_v1& layer) {
    if (result.retained_layer_count == 0) result.header = header;
    else if (!SameCompositionHeader(result.header, header)) {
        result.header.flags &= ~LUCENT_SOURCE_COMPOSITION_COMPLETE;
        result.header.flags |= LUCENT_SOURCE_COMPOSITION_INCONSISTENT;
    }
    if (result.retained_layer_count >= LUCENT_SOURCE_IMAGE_MAX_LAYERS) {
        result.header.flags &= ~LUCENT_SOURCE_COMPOSITION_COMPLETE;
        result.header.flags |= LUCENT_SOURCE_COMPOSITION_TOO_MANY_LAYERS;
        return;
    }
    result.layers[result.retained_layer_count++] = layer;
}

// Fixed value-only ledger. Epoch transitions are atomic invalidations. Every
// composition, publish, finalize and query uses try_lock: contention loses
// diagnostic coverage, never blocks a rendering deadline. No lock is held over
// Vulkan or a callback into the host.
class SourceImageLedger final {
public:
    void BeginSession() {
        session_.store(0, std::memory_order_release);
        surface_.store(0, std::memory_order_release);
        swapchain_.store(0, std::memory_order_release);
        session_.store(NextSourceEpoch(), std::memory_order_release);
    }
    void BindSurface() {
        // New producer binding is unqualified until its swapchain exists.
        swapchain_.store(0, std::memory_order_release);
        surface_.store(NextSourceEpoch(), std::memory_order_release);
    }
    void NewSwapchain() {
        swapchain_.store(NextSourceEpoch(), std::memory_order_release);
    }
    void Close() {
        session_.store(0, std::memory_order_release);
    }
    lucent_source_composition_header_v1 Composition(uint64_t display, uint32_t layers,
                                                   uint64_t now) {
        std::unique_lock lock(mutex_, std::try_to_lock);
        if (!lock.owns_lock()) { ++busy_; return {}; }
        if (!session_ || !surface_ || !swapchain_) return {};
        const uint32_t flags = layers <= LUCENT_SOURCE_IMAGE_MAX_LAYERS ?
            LUCENT_SOURCE_COMPOSITION_COMPLETE : LUCENT_SOURCE_COMPOSITION_TOO_MANY_LAYERS;
        return {session_, surface_, swapchain_, display, ++composition_, now, layers, flags};
    }
    uint64_t BeginPresent(const lucent_source_composition_v1& source, uint64_t timestamp,
                          uint32_t presentId, uint32_t imageIndex, bool timestampSupported) {
        if (!timestampSupported) { ++unsupported_; return 0; }
        std::unique_lock lock(mutex_, std::try_to_lock);
        if (!lock.owns_lock()) { ++busy_; return 0; }
        if (!Current(source.header) || !timestamp || !source.header.composition_ordinal) return 0;
        if (timestamp_session_ != source.header.session_epoch ||
                timestamp_surface_ != source.header.surface_epoch) {
            last_timestamp_ = 0;
            timestamp_session_ = source.header.session_epoch;
            timestamp_surface_ = source.header.surface_epoch;
        }
        bool collision = timestamp <= last_timestamp_;
        if (timestamp > last_timestamp_) last_timestamp_ = timestamp;
        for (auto& row : rows_) {
            if (row.state && row.buffer_timestamp_ns == timestamp &&
                    row.composition.header.session_epoch == session_ &&
                    row.composition.header.surface_epoch == surface_) {
                row.state = LUCENT_SOURCE_AMBIGUOUS;
                collision = true;
            }
        }
        if (cursor_ == std::numeric_limits<uint64_t>::max()) return 0;
        const uint64_t token = ++cursor_;
        auto& row = rows_[(token - 1) % rows_.size()];
        if (row.state) ++evicted_;
        row = {};
        row.version = LUCENT_SOURCE_IMAGE_VERSION;
        row.struct_size = sizeof(row);
        row.state = collision ? LUCENT_SOURCE_AMBIGUOUS : LUCENT_SOURCE_PENDING;
        row.submission_ordinal = token;
        row.buffer_timestamp_ns = timestamp;
        row.vk_present_id = presentId;
        row.swapchain_image_index = imageIndex;
        row.composition = source;
        if (source.retained_layer_count != source.header.layer_count)
            row.composition.header.flags &= ~LUCENT_SOURCE_COMPOSITION_COMPLETE;
        if (collision) ++ambiguous_;
        return token;
    }
    void FinishPresent(uint64_t token, int32_t result, bool accepted) {
        if (!token) return;
        std::unique_lock lock(mutex_, std::try_to_lock);
        if (!lock.owns_lock()) { ++busy_; return; }
        auto& row = rows_[(token - 1) % rows_.size()];
        if (row.submission_ordinal != token || !Current(row.composition.header)) return;
        row.vk_present_result = result;
        if (row.state == LUCENT_SOURCE_PENDING)
            row.state = accepted ? LUCENT_SOURCE_MATCH_ACCEPTED : LUCENT_SOURCE_REJECTED;
    }
    uint32_t Binding(lucent_source_binding_v1* out, uint32_t size) {
        if (!out || size < sizeof(*out)) return LUCENT_SOURCE_BAD_ARGUMENT;
        *out = {};
        std::unique_lock lock(mutex_, std::try_to_lock);
        if (!lock.owns_lock()) { ++busy_; return LUCENT_SOURCE_BUSY; }
        if (!session_ || !surface_) return LUCENT_SOURCE_CLOSED;
        *out = {LUCENT_SOURCE_IMAGE_VERSION, sizeof(*out), session_, surface_, swapchain_,
                busy_.load(), evicted_.load(), ambiguous_.load(), unsupported_.load()};
        return LUCENT_SOURCE_MATCH_ACCEPTED;
    }
    uint32_t Query(uint64_t session, uint64_t surface, uint64_t timestamp,
                   lucent_source_image_v1* out, uint32_t size) {
        if (!out || size < sizeof(*out) || !session || !surface || !timestamp)
            return LUCENT_SOURCE_BAD_ARGUMENT;
        *out = {};
        std::unique_lock lock(mutex_, std::try_to_lock);
        if (!lock.owns_lock()) { ++busy_; return LUCENT_SOURCE_BUSY; }
        if (!session_) return LUCENT_SOURCE_CLOSED;
        if (session != session_ || surface != surface_) return LUCENT_SOURCE_STALE_EPOCH;
        for (const auto& row : rows_) {
            if (row.state && row.buffer_timestamp_ns == timestamp && Current(row.composition.header)) {
                *out = row;
                return row.state;
            }
        }
        return LUCENT_SOURCE_NOT_FOUND;
    }
private:
    bool Current(const lucent_source_composition_header_v1& header) const {
        return session_ && surface_ && swapchain_ && header.session_epoch == session_ &&
               header.surface_epoch == surface_ && header.swapchain_epoch == swapchain_;
    }
    std::mutex mutex_;
    std::array<lucent_source_image_v1, LUCENT_SOURCE_IMAGE_RING_CAPACITY> rows_{};
    std::atomic<uint64_t> session_{0}, surface_{0}, swapchain_{0};
    uint64_t cursor_ = 0, composition_ = 0, last_timestamp_ = 0;
    uint64_t timestamp_session_ = 0, timestamp_surface_ = 0;
    std::atomic<uint64_t> busy_{0}, evicted_{0}, ambiguous_{0}, unsupported_{0};
};
static_assert(std::is_trivially_copyable_v<lucent_source_image_v1>);
static_assert(sizeof(SourceImageLedger) < 256 * 1024);
inline SourceImageLedger g_source_images;
} // namespace Lucent
