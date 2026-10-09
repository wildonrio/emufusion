// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace Lucent::Trial {
// Native presentation experiment only. This schedules existing images; it does
// not generate images, change VI/guest/audio clocks, or prove new-frame cadence.
class DirectPresentPacer {
public:
    bool Configure(uint64_t refresh) {
        *this = {};
        if (refresh < 4000000 || refresh > 25000000) return false;
        nominal = measured = static_cast<double>(refresh);
        return true;
    }

    void Feedback(uint32_t id, uint64_t actual, uint64_t now) {
        if (!nominal || !id || id <= last_id || actual == 0 || actual > now ||
            now - actual > 1000000000 || (last_actual && actual <= last_actual)) return;
        if (last_actual) {
            const double delta = static_cast<double>(actual - last_actual);
            const auto holds = std::llround(delta / nominal);
            if (holds >= 1 && holds <= 8) {
                const double observation = delta / holds;
                if (std::abs(observation / nominal - 1.0) <= 0.0075) {
                    samples = std::min(samples + 1u, 256u);
                    measured += (observation - measured) / samples;
                }
            }
        }
        last_id = id;
        last_actual = actual;
    }

    uint64_t Schedule(uint32_t id, uint64_t now, int64_t composition_period) {
        if (!nominal || composition_period <= 0 || !id) return 0;
        const auto holds = std::llround(composition_period / nominal);
        if (holds < 1 || holds > 8 ||
            std::abs(composition_period / (holds * nominal) - 1.0) > 0.0075) {
            last_target = 0;
            return 0; // No 80-on-120 or large gameplay-rate conversion.
        }
        if (!HasRecentFeedback(id, now)) {
            last_target = 0;
            return 0; // No stale phase after pause, mode change, or missing feedback.
        }
        const double period = measured * holds;
        // The requested time is a NOT-BEFORE bound, not an exact display time.
        // A quarter-refresh margin avoids rounding a near-vsync request late.
        double target = last_actual + (id - last_id) * period - measured * 0.25;
        if (last_target && last_holds == holds) {
            if (id <= last_target_id || id - last_target_id > 16) {
                last_target = 0;
                ++resets;
                return 0;
            }
            // Feedback estimates refresh frequency; a late physical hold is
            // not a new source phase. Re-anchoring to that delayed actual time
            // would shift every subsequent target by a refresh and amplify a
            // single miss. Keep the established phase until bounded recovery
            // below or an explicit mode/staleness reset is necessary.
            target = last_target + (id - last_target_id) * period;
        }
        if (target + measured * 0.25 < now || target > now + 4 * period) {
            last_target = 0;
            ++resets;
            return 0; // Bounded direct fallback; never buffer seconds of input.
        }
        last_holds = holds;
        last_target = static_cast<uint64_t>(std::llround(target));
        last_target_id = id;
        return last_target;
    }

    double RefreshNs() const { return measured; }
    uint32_t Samples() const { return samples; }
    uint32_t Resets() const { return resets; }
    bool HasRecentFeedback(uint32_t id, uint64_t now) const {
        return samples >= 32 && id > last_id && id - last_id <= 16 &&
               now >= last_actual && now - last_actual <= 250000000;
    }
private:
    double nominal{}, measured{};
    uint32_t last_id{}, last_target_id{}, samples{}, resets{};
    uint64_t last_actual{}, last_target{};
    int64_t last_holds{};
};
} // namespace Lucent::Trial
