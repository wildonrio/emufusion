// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstddef>
#include <cstdint>

namespace Lucent {

// Owned by one audio pump. Stream counters sum across streams; mixed/accepted
// counters describe the single host sink. Neither means hardware playback.
struct AudioObservation {
    uint64_t blocks{}, stream_frames{}, queued_frames{}, copied_samples{};
    uint64_t held_frames{}, paused_frames{}, no_stream_blocks{};
    uint64_t mixed_frames{}, accepted_frames{}, rejected_frames{}, invalid_returns{};
    uint64_t late_blocks{}, resyncs{}, max_lateness_ns{};

    void Pull(std::size_t requested, std::size_t queued, std::size_t copied,
              std::size_t held, std::size_t paused) {
        stream_frames += requested;
        queued_frames += queued;
        copied_samples += copied;
        held_frames += held;
        paused_frames += paused;
    }

    void Delivery(std::size_t frames, std::size_t accepted, bool any_stream) {
        ++blocks;
        if (!any_stream) ++no_stream_blocks;
        mixed_frames += frames;
        if (accepted > frames) {
            ++invalid_returns;
            // An invalid callback result is not evidence of accepted audio.
            rejected_frames += frames;
        } else {
            accepted_frames += accepted;
            rejected_frames += frames - accepted;
        }
    }

    void Late(uint64_t lateness_ns, bool resync) {
        if (lateness_ns > 0) ++late_blocks;
        if (lateness_ns > max_lateness_ns) max_lateness_ns = lateness_ns;
        if (resync) ++resyncs;
    }
};

} // namespace Lucent
