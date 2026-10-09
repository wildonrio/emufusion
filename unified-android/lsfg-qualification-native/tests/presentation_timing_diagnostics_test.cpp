#include "presentation_timing_diagnostics.hpp"

#include <cassert>
#include <cstdint>

using emufusion::lsfg::PresentationTimingDiagnostics;
using emufusion::lsfg::PresentationTimingRequest;

int main() {
    PresentationTimingDiagnostics diagnostics;
    assert(!diagnostics.request(0).has_value());
    assert(!diagnostics.request(1).has_value());
    const PresentationTimingRequest first{1, 100, 98, 51, 101, 90};
    diagnostics.submitted(0, first);
    auto copied = diagnostics.request(1);
    assert(copied.has_value());
    assert(copied->physicalTargetNs == 100 && copied->driverDesiredNs == 98);
    assert(copied->vsyncId == 51 && copied->tokenExpectedNs == 101);
    assert(copied->tokenDeadlineNs == 90);
    copied->physicalTargetNs = 999; // Copy cannot alter the saved request.
    assert(diagnostics.request(1)->physicalTargetNs == 100);
    diagnostics.submitted(1, {2, 200, 198, 52, 201, 190});
    assert(diagnostics.request(1)->physicalTargetNs == 100);
    assert(diagnostics.request(2)->physicalTargetNs == 200);
    diagnostics.submitted(0, {3, 300, 298, 53, 301, 290});
    assert(!diagnostics.request(1).has_value()); // Recycled slot is not old ID.
    assert(diagnostics.request(3)->physicalTargetNs == 300);
    diagnostics.submitted(3, {4, 400, 398, 54, 401, 390});
    assert(!diagnostics.request(4).has_value()); // Out-of-range slot ignored.
    diagnostics.submitted(2, {3, 301, 299, 53, 302, 291});
    assert(!diagnostics.request(3).has_value()); // Ambiguous identity fails closed.
    for (uint32_t row = 0; row < 32; ++row) assert(diagnostics.takeLiveRow());
    for (uint32_t row = 0; row < 1000; ++row) {
        diagnostics.submitted(0, {100 + row, row, row, row, row, row});
        assert(!diagnostics.takeLiveRow()); // New requests/epochs cannot reset budget.
    }
    assert(diagnostics.liveRows() == 32);
    assert(diagnostics.takeFailure()); // One explicit failure survives the row cap.
    assert(!diagnostics.takeFailure());
}
