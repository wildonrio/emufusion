// Synthetic scheduling arithmetic only, not a device/compositor qualification.
#include "surface_present_timing.hpp"

#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>

using emufusion::lsfg::kSurfaceDriverPresentLeadNs;
using emufusion::lsfg::startupDriverPresentTimeNs;

// Models only Android's documented at-or-after constraint. Real SurfaceFlinger
// may still present later due to load/fences; device feedback must detect that.
template <std::size_t N>
uint64_t earliestAllowedScan(const std::array<uint64_t, N>& scans,
                             uint64_t driverDesired) {
    for (uint64_t scan : scans) if (scan >= driverDesired) return scan;
    assert(false);
    return 0;
}

int main() {
    for (uint64_t invalid : {0ULL, 1ULL, kSurfaceDriverPresentLeadNs}) {
        bool rejected = false;
        try { (void)startupDriverPresentTimeNs(invalid); }
        catch (const std::invalid_argument&) { rejected = true; }
        assert(rejected);
    }
    assert(startupDriverPresentTimeNs(kSurfaceDriverPresentLeadNs + 1) == 1);
    assert(startupDriverPresentTimeNs(UINT64_MAX) ==
            UINT64_MAX - kSurfaceDriverPresentLeadNs);

    // Recorded Sept 4 startup failure: the first raw fence is one scan late;
    // the next is on time. Infer a counterfactual earlier scan from the measured
    // interval solely to reproduce the boundary defect, not to fabricate a row.
    constexpr uint64_t firstPhysical = 293383454097394ULL;
    constexpr uint64_t secondPhysical = 293383470764060ULL;
    constexpr uint64_t firstRaw = 293383462431100ULL;
    constexpr uint64_t secondRaw = 293383470764955ULL;
    constexpr uint64_t observedScan = secondRaw - firstRaw;
    const std::array<uint64_t, 3> scans{
        firstRaw - observedScan, firstRaw, secondRaw,
    };
    assert(secondPhysical - firstPhysical == 16'666'666ULL);
    assert(observedScan == 8'333'855ULL);
    assert(earliestAllowedScan(scans, firstPhysical) == firstRaw);
    assert(earliestAllowedScan(scans, secondPhysical) == secondRaw);
    assert(earliestAllowedScan(scans, startupDriverPresentTimeNs(firstPhysical)) ==
            scans[0]);
    assert(earliestAllowedScan(scans, startupDriverPresentTimeNs(secondPhysical)) ==
            secondRaw);
    assert(secondRaw - scans[0] == observedScan * 2);

    // Under bounded sub-ms phase prediction noise at supported panel periods,
    // the existing 2 ms reserve allows the intended scan, never its predecessor.
    // A one-scan late measured result remains late: this helper doesn't change
    // or normalize physical timestamps, targets, or proof tolerances.
    for (uint64_t panelPeriod : {8'333'333ULL, 16'666'667ULL}) {
        for (uint64_t heldScans : {1ULL, 2ULL, 3ULL, 4ULL, 6ULL}) {
            constexpr uint64_t anchor = 1'000'000'000ULL;
            for (int64_t jitter = -150'000; jitter <= 150'000; jitter += 137) {
                const uint64_t actual = anchor + heldScans * panelPeriod;
                const uint64_t predicted = static_cast<uint64_t>(
                        static_cast<int64_t>(actual) + jitter);
                const std::array<uint64_t, 3> panelScans{
                    actual - panelPeriod, actual, actual + panelPeriod,
                };
                assert(earliestAllowedScan(panelScans,
                        startupDriverPresentTimeNs(predicted)) == actual);
                assert(predicted - startupDriverPresentTimeNs(predicted) ==
                        kSurfaceDriverPresentLeadNs);
            }
        }
    }
    std::cout << "surface_present_timing_test PASS (synthetic only)\n";
}
