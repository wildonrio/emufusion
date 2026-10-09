#pragma once

#include <cstdint>
#include <stdexcept>

namespace emufusion::lsfg {

// Android's desired-present timestamp is a not-before bound, not the physical
// scan we will verify. Keep the existing live 2 ms reserve for startup too:
// predicting exactly on a scan edge can miss that scan by timestamp jitter.
// This changes only the driver request, never the physical proof target or its
// tolerance. It is a reserve for the supported 60/120 Hz panel contract, not
// evidence that Android actually delivered the requested scan.
inline constexpr uint64_t kSurfaceDriverPresentLeadNs = 2'000'000ULL;

inline uint64_t startupDriverPresentTimeNs(uint64_t physicalTargetNs) {
    if (physicalTargetNs <= kSurfaceDriverPresentLeadNs)
        throw std::invalid_argument("physical target has no positive driver bound");
    return physicalTargetNs - kSurfaceDriverPresentLeadNs;
}

}  // namespace emufusion::lsfg
