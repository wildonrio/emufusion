#pragma once

#include "lsfg_3_1.hpp"
#include "owned_vulkan_host.hpp"
#include "sync_poll_result.hpp"
#include "temporal_history.hpp"
#include <poll.h>
#include <unistd.h>
#include <stdexcept>

namespace emufusion::lsfg {

// Nonblocking lifetime of one continuous LSFG context. The owner creates a
// fresh backend before constructing this object, and destroys that backend
// before releasing its scratch AHBs. Neither submit nor poll waits for the GPU.
class ContinuousInference final {
public:
    enum class Submission { Submitted, Busy, RecreateRequired };
    enum class Completion { Idle, Pending, Ready };

    ContinuousInference(OwnedVulkanHost& transport, int32_t context,
                        AHardwareBuffer* output)
        : transport_(transport), context_(context), output_(output) {
        if (context < 0 || !output) throw std::invalid_argument("invalid continuous context");
    }
    ~ContinuousInference() {
        if (readyFd_ >= 0) ::close(readyFd_);
        if (inputs_ && inputs_->inputReadySyncFd >= 0) ::close(inputs_->inputReadySyncFd);
    }
    ContinuousInference(const ContinuousInference&) = delete;
    ContinuousInference& operator=(const ContinuousInference&) = delete;

    Submission submit(AHardwareBuffer* previous, AHardwareBuffer* next,
                      TemporalFrame identity) {
        if (failed_) return Submission::RecreateRequired;
        if (inputs_ || transport_.referencesSourceImage(output_)) return Submission::Busy;
        const auto admission = history_.inspect(identity);
        if (admission == TemporalHistory::Admission::Busy) return Submission::Busy;
        if (admission != TemporalHistory::Admission::Accepted)
            return Submission::RecreateRequired;
        auto prepared = transport_.tryPrepareContinuousInputs(previous, next, history_.nextInput());
        if (!prepared) return Submission::Busy; // No history consumed.
        if (readyFd_ >= 0) { ::close(readyFd_); readyFd_ = -1; }
        inputs_ = prepared;
        history_.begin(identity);
        completed_ = false;
        try {
            trySubmitBackend();
        } catch (...) {
            history_.complete(false);
            failed_ = true; // Teardown owns uncertain GPU work; never reuse it.
            throw;
        }
        return Submission::Submitted;
    }

    Completion poll() {
        if (failed_) throw std::runtime_error("continuous inference is quarantined");
        if (!inputs_) return completed_ ? Completion::Ready : Completion::Idle;
        if (readyFd_ == -2) {
            try {
                trySubmitBackend();
            } catch (...) {
                history_.complete(false);
                failed_ = true;
                throw;
            }
            if (readyFd_ == -2) return Completion::Pending;
        }
        const auto completion = pollSyncCompletion(readyFd_);
        if (completion == SyncCompletion::Pending) return Completion::Pending;
        if (completion == SyncCompletion::Failed) {
            history_.complete(false);
            failed_ = true;
            throw std::runtime_error("continuous inference completion failed");
        }
        transport_.abandonPrepared(*inputs_);
        inputs_.reset();
        if (!history_.complete(true)) throw std::logic_error("continuous history completion lost");
        completed_ = true;
        return Completion::Ready;
    }

    // Borrowed fence remains valid until the next accepted submission. Copy
    // output before submitting again; the transport's source lease then stops
    // scratch reuse until that copy completes.
    int completedFence() const { return completed_ && !failed_ ? readyFd_ : -3; }
    bool historyReady() const { return history_.historyReady(); }
    std::optional<TemporalFrame> lastCompleted() const { return history_.lastCompleted(); }

private:
    void trySubmitBackend() {
        // Busy does not consume the input FD; retain the exact copy and retry
        // without advancing the temporal history or submitting another copy.
        const int inputFd = inputs_->inputReadySyncFd;
        inputs_->inputReadySyncFd = -1;
        readyFd_ = LSFG_3_1::tryPresentContextSyncFd(context_, inputFd);
        if (readyFd_ == -2) inputs_->inputReadySyncFd = inputFd;
        else if (readyFd_ < -1) throw std::runtime_error("invalid LSFG completion result");
    }
    OwnedVulkanHost& transport_;
    int32_t context_;
    AHardwareBuffer* output_;
    TemporalHistory history_;
    std::optional<OwnedVulkanHost::PreparedPresentation> inputs_;
    int readyFd_ = -1;
    bool completed_ = false, failed_ = false;
};
}
