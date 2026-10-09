#pragma once

#include <array>
#include <cstdint>
#include <optional>

namespace emufusion::lsfg {

/** Diagnostic-only copies, never scheduling or physical-evidence authority. */
struct PresentationTimingRequest {
    uint64_t presentId = 0;
    uint64_t physicalTargetNs = 0;
    uint64_t driverDesiredNs = 0;
    uint64_t vsyncId = 0;
    uint64_t tokenExpectedNs = 0;
    uint64_t tokenDeadlineNs = 0;
};

/** Fixed slot identity join and host-lifetime log budget; deliberately no reset. */
class PresentationTimingDiagnostics final {
public:
    static constexpr uint32_t kSlots = 3;
    static constexpr uint32_t kLiveRowLimit = 32;

    void submitted(uint32_t slot, const PresentationTimingRequest& request) {
        if (slot < rows_.size() && request.presentId != 0)
            rows_[slot] = request;
    }

    std::optional<PresentationTimingRequest> request(uint64_t presentId) const {
        if (presentId == 0) return std::nullopt;
        std::optional<PresentationTimingRequest> result;
        for (const auto& row : rows_) {
            if (row.presentId != presentId) continue;
            if (result.has_value()) return std::nullopt; // Ambiguous is unknown.
            result = row;
        }
        return result;
    }

    bool takeLiveRow() {
        if (liveRows_ == kLiveRowLimit) return false;
        ++liveRows_;
        return true;
    }

    bool takeFailure() {
        if (failureLogged_) return false;
        failureLogged_ = true;
        return true;
    }

    uint32_t liveRows() const { return liveRows_; }

private:
    std::array<PresentationTimingRequest, kSlots> rows_{};
    uint32_t liveRows_ = 0;
    bool failureLogged_ = false;
};

} // namespace emufusion::lsfg
