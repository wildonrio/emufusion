#pragma once
#include <cstdint>

namespace emufusion::lsfg {
// Mathematical interpolation phase remains exactly 1/2. Integer content time
// stores floor(left + (right-left)/2), with no addition/overflow required.
inline bool isFloorMidpointTimestamp(uint64_t left, uint64_t right, uint64_t content) {
    return left > 0 && right > left && content > left && content < right &&
           content - left == (right - left) / 2;
}
} // namespace emufusion::lsfg
