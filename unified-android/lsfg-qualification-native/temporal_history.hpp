#pragma once
#include <cstdint>
#include <limits>
#include <optional>

namespace emufusion::lsfg {
struct TemporalFrame {
    uint64_t session = 0, timeline = 0, sequence = 0, timestampNs = 0;
};

// Tracks inference history, not presentation-buffer availability. The caller
// must recreate/reset the actual backend before resetAfterBackendRecreation().
class TemporalHistory {
public:
    enum class Admission { Accepted, Busy, Invalid, RecreateRequired };
    Admission inspect(TemporalFrame next) const {
        if (pending_) return Admission::Busy;
        if (!next.session || !next.timeline || !next.sequence || !next.timestampNs)
            return Admission::Invalid;
        if (failed_) return Admission::RecreateRequired;
        if (last_ && (next.session != last_->session || next.timeline != last_->timeline ||
                last_->sequence == std::numeric_limits<uint64_t>::max() ||
                next.sequence != last_->sequence + 1 || next.timestampNs <= last_->timestampNs))
            return Admission::RecreateRequired;
        return Admission::Accepted;
    }
    Admission begin(TemporalFrame next) {
        const auto admission = inspect(next);
        if (admission == Admission::Accepted) pending_ = next;
        return admission;
    }
    bool complete(bool gpuSucceeded) {
        if (!pending_) return false;
        if (gpuSucceeded) {
            last_ = pending_;
            if (historyDepth_ < 3) ++historyDepth_;
            nextInput_ ^= 1;
        } else {
            failed_ = true;
            historyDepth_ = 0;
        }
        pending_.reset();
        return gpuSucceeded;
    }
    bool resetAfterBackendRecreation() {
        if (pending_) return false;
        last_.reset(); historyDepth_ = 0; nextInput_ = 0; failed_ = false;
        return true;
    }
    bool historyReady() const { return historyDepth_ == 3 && !pending_ && !failed_; }
    unsigned nextInput() const { return nextInput_; }
    std::optional<TemporalFrame> lastCompleted() const { return last_; }
private:
    std::optional<TemporalFrame> last_, pending_;
    unsigned historyDepth_ = 0, nextInput_ = 0;
    bool failed_ = false;
};
}
