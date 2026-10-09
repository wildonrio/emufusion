// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "eden_coupled_clock.h"
#include "common/cpu_features.h"
namespace Lucent::Trial {
inline int64_t RawGuestClockNs() { return Common::g_wall_clock.GetTimeNS().count(); }
inline int64_t GuestClockNs() { return g_coupled_clock.Now(RawGuestClockNs); }
inline std::atomic<bool> g_coupled_clock_allowed{false};
inline void ResetDisplayClock() {
    // Preserve the guest epoch while returning to the uncorrected rate.
    g_coupled_clock.SetRate(1.0, RawGuestClockNs);
}
inline void ObserveDisplayClock(double refresh_ns) {
    if (!g_coupled_clock_allowed.load() || !std::isfinite(refresh_ns) ||
        refresh_ns < 4000000 || refresh_ns > 25000000) {
        ResetDisplayClock();
        return;
    }
    // Only the already verified near-60/120 physical modes, not performance tiers.
    const double refresh_hz = 1000000000.0 / refresh_ns;
    const auto divisor = std::llround(refresh_hz / 60.0);
    if ((divisor != 1 && divisor != 2) ||
        !g_coupled_clock.SetRate(refresh_hz / (60.0 * divisor), RawGuestClockNs))
        ResetDisplayClock();
}
} // namespace Lucent::Trial
