// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <cmath>
#include <cstdint>
#include <mutex>

namespace Lucent::Trial {
// One continuous guest-time map, shared by timers, CPU/GPU counters and audio.
// Rate changes preserve the current guest epoch; reset is load-only after stop.
class CoupledClock {
public:
    template<class RawClock> int64_t Now(RawClock raw_clock) const {
        for (;;) {
            const auto before = version.load();
            if (before & 1) continue;
            const auto h = host_anchor.load();
            const auto g = guest_anchor.load();
            const auto r = rate_ppb.load();
            const int64_t raw = raw_clock();
            if (before == version.load()) return Map(raw, h, g, r);
        }
    }
    template<class RawClock> bool SetRate(double ratio, RawClock raw_clock) {
        if (!std::isfinite(ratio) || ratio < 0.9925 || ratio > 1.0075) return false;
        const int64_t next = std::llround(ratio * 1000000000.0);
        std::scoped_lock lock{writer};
        if (next == rate_ppb.load()) return true;
        version.fetch_add(1);
        const int64_t raw = raw_clock();
        const auto guest = Map(raw, host_anchor.load(), guest_anchor.load(), rate_ppb.load());
        host_anchor.store(raw);
        guest_anchor.store(guest);
        rate_ppb.store(next);
        version.fetch_add(1);
        return true;
    }
    // Only when the previous guest and all readers have been retired.
    void Reset() {
        std::scoped_lock lock{writer};
        version.fetch_add(1);
        host_anchor.store(0); guest_anchor.store(0); rate_ppb.store(1000000000);
        version.fetch_add(1);
    }
    double Rate() const { return rate_ppb.load() / 1000000000.0; }
    int64_t HostWaitNs(int64_t guest_duration) const {
        if (guest_duration <= 0) return 0;
        const auto r = rate_ppb.load();
        return static_cast<int64_t>((static_cast<__int128>(guest_duration) * 1000000000 + r - 1) / r);
    }
private:
    static int64_t Map(int64_t raw, int64_t h, int64_t g, int64_t r) {
        return g + static_cast<int64_t>((static_cast<__int128>(raw) - h) * r / 1000000000);
    }
    // All fields are atomic (not a seqlock over data-racing ordinary storage).
    // Sequential consistency keeps the snapshot and raw-clock read in one epoch.
    mutable std::mutex writer;
    std::atomic<uint64_t> version{0};
    std::atomic<int64_t> host_anchor{0}, guest_anchor{0}, rate_ppb{1000000000};
};
inline CoupledClock g_coupled_clock;
} // namespace Lucent::Trial
