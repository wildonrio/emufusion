// SPDX-FileCopyrightText: 2026 EmuFusion contributors
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <atomic>
#include <cmath>
#include <cstdint>

namespace Lucent {
inline constexpr double kDeclaredVsyncHz = 60.0;
inline constexpr double kMaximumClockCorrection = 0.0075;
inline std::atomic<double> g_paced_vsync_hz{0.0};
// Only an attached FG consumer needs explicit timestamps for image matching.
// Direct presentation must retain the driver's normal timestamp policy.
inline std::atomic<bool> g_fg_presentation{false};
inline void SetFgPresentation(bool enabled) {
    g_fg_presentation.store(enabled, std::memory_order_relaxed);
}
inline bool UsesFgPresentation() {
    return g_fg_presentation.load(std::memory_order_relaxed);
}

inline double PacedVsyncHz() {
    return g_paced_vsync_hz.load(std::memory_order_relaxed);
}

inline bool PermitsVsyncCorrection(double hz) {
    return std::isfinite(hz) && hz > 0.0 &&
           std::abs(hz / kDeclaredVsyncHz - 1.0) <= kMaximumClockCorrection + 1.0e-12;
}

// Only zero resets. Invalid requests leave the current clock untouched.
inline bool SetPacedVsyncHz(double hz) {
    if (hz != 0.0 && !PermitsVsyncCorrection(hz)) {
        return false;
    }
    g_paced_vsync_hz.store(hz, std::memory_order_relaxed);
    return true;
}

inline double BaseVsyncHz() {
    const double hz = PacedVsyncHz();
    return hz > 0.0 ? hz : kDeclaredVsyncHz;
}

// The base VI clock and the game's composition swap interval are different.
// Preserve the game's swap interval and existing speed scale. This rounds one
// callback period to nanoseconds; it is not measured physical-panel phase lock.
inline std::int64_t CompositionPeriodNs(double baseHz, int swapInterval, double speedScale) {
    if (!(std::isfinite(baseHz) && baseHz > 0.0 &&
          std::isfinite(speedScale) && speedScale > 0.0) || swapInterval < 1) {
        return 0;
    }
    const long double period = 1000000000.0L * swapInterval * speedScale / baseHz;
    if (period < 1.0L || period > 1000000000.0L) {
        return 0;
    }
    return static_cast<std::int64_t>(std::llround(period));
}

// Diagnostics only: a VI callback need not produce a new image, and a Vulkan
// submission attempt need not complete or display. These sampled atomics are
// not an image-to-VI join and must never authorize a source-content timeline.
inline std::atomic<std::uint64_t> g_vi_callbacks{0};
inline std::atomic<std::uint64_t> g_submission_attempts{0};
inline std::atomic<int> g_last_swap_interval{1};
inline std::atomic<std::int64_t> g_last_composition_period_ns{0};

inline std::uint64_t RecordViCallback(int swapInterval, std::int64_t periodNs) {
    g_last_swap_interval.store(swapInterval, std::memory_order_relaxed);
    g_last_composition_period_ns.store(periodNs, std::memory_order_relaxed);
    return g_vi_callbacks.fetch_add(1, std::memory_order_relaxed) + 1;
}

inline std::uint64_t RecordSubmissionAttempt() {
    return g_submission_attempts.fetch_add(1, std::memory_order_relaxed) + 1;
}

inline void ResetTimingDiagnostics() {
    g_vi_callbacks.store(0, std::memory_order_relaxed);
    g_submission_attempts.store(0, std::memory_order_relaxed);
    g_last_swap_interval.store(1, std::memory_order_relaxed);
    g_last_composition_period_ns.store(0, std::memory_order_relaxed);
}
} // namespace Lucent
