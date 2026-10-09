#pragma once

#include <android/hardware_buffer.h>
#include <android/native_window.h>

#include <cstdint>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace emufusion::lsfg {

/** The completed transaction supplied no physical-present fence evidence. */
class PresentFenceUnavailable final : public std::runtime_error {
public:
    explicit PresentFenceUnavailable(const std::string& message)
            : std::runtime_error(message) {}
};

/**
 * EmuFusion-owned, callback-driven Android compositor presentation boundary.
 *
 * A completed LSFG AHardwareBuffer is attached directly to a child
 * ASurfaceControl. The framework owns the acquire FD and returns physical
 * completion through an OnComplete present fence. An owned native
 * frame-timeline row proves that the requested scan and its composition
 * deadline were live at submission admission. A persistent FIFO worker submits
 * the prepared output promptly, binding the admission-validated token with
 * EmuFusion's
 * independent CLOCK_MONOTONIC desired-present bound. The rolling contents of
 * later Choreographer callbacks do not define token lifetime. The caller never
 * waits.
 * OnCommit is observed only for exact-request diagnostics. It is not a pacing
 * gate, physical-present proof, or permission to reuse a buffer.
 */
class OwnedSurfaceControlPresenter final {
public:
    struct FrameTimeline {
        uint64_t vsyncId = 0;
        uint64_t expectedPresentationTimeNs = 0;
        uint64_t deadlineNs = 0;
    };

    struct Completion {
        uint64_t presentId = 0;
        uint64_t desiredPresentTimeNs = 0;
        uint64_t latchTimeNs = 0;
        uint64_t actualPresentTimeNs = 0;
        // Immutable kernel fence value, retained even if a caller separately
        // applies a diagnostic/legacy normalization to actualPresentTimeNs.
        uint64_t rawPresentFenceTimeNs = 0;
        uint64_t frameTimelineDeadlineNs = 0;
        uint64_t transactionApplyStartNs = 0;
        uint64_t transactionApplyEndNs = 0;
    };

    OwnedSurfaceControlPresenter(ANativeWindow* parent, uint32_t bufferWidth,
                                 uint32_t bufferHeight);
    ~OwnedSurfaceControlPresenter();
    OwnedSurfaceControlPresenter(const OwnedSurfaceControlPresenter&) = delete;
    OwnedSurfaceControlPresenter& operator=(
            const OwnedSurfaceControlPresenter&) = delete;

    /**
     * Consumes acquireFenceFd on true OR exception. Only an explicit false
     * leaves the FD caller-owned. Schedules one ordered transaction on success.
     * Returns false, without consuming the fence or buffer, when the exact
     * target frame-timeline row is already invalid. A contradictory row
     * still visible before apply, or a deadline missed before buffer handoff,
     * is reported asynchronously as rejected. Once handed off, callback and
     * fence evidence retain ownership even if apply returns after its deadline.
     * An exception after apply is attempted retains the dispatched row and
     * surfaces a persistent error; it never turns that row into a rejection.
     * Release-fence polling remains available after such a presentation error.
     */
    bool present(AHardwareBuffer* buffer, int acquireFenceFd,
                 uint64_t presentId, uint64_t desiredPresentTimeNs,
                 uint64_t compositorFrameTimelineVsyncId = 0,
                 uint64_t compositorFrameTimelineExpectedNs = 0,
                 uint64_t compositorFrameTimelineDeadlineNs = 0,
                 uint64_t compositorRefreshDurationNs = 0);

    /** Returns the oldest physically completed row, or nullopt without waiting. */
    std::optional<Completion> pollCompletion();

    /**
     * Returns contiguous oldest callback rows whose framework completion
     * explicitly omitted physical-present fence evidence. Each ID is reported
     * once and remains owned until {@link markDropped} plus release retirement.
     */
    std::vector<uint64_t> takeUnavailablePresentFences();

    /** Marks one previously reported fence-less callback as an observed drop. */
    void markDropped(uint64_t presentId);

    /** Zero-polls SurfaceFlinger's previous-buffer release fence. */
    bool isReleased(uint64_t presentId);

    /** Drops presenter bookkeeping only after physical delivery and release. */
    void retire(uint64_t presentId);

    std::string diagnosticJson() const;

    /**
     * Starts an API-33 NDK Choreographer source on the calling Looper thread.
     * ASurfaceTransaction_setFrameTimeline accepts only IDs registered by
     * AChoreographer; Java Choreographer IDs are a different ownership domain.
     */
    void enableNativeFrameTimelineSource();

    /** Copies the newest native callback's timelines without waiting. */
    std::vector<FrameTimeline> nativeFrameTimelines(
            uint64_t* callbackSequence, uint64_t* frameTimeNs) const;

    /** Zero-wait exact-row check used before a RIFE submission consumes work. */
    bool canSubmitFrameTimeline(uint64_t vsyncId, uint64_t expectedNs,
                                uint64_t deadlineNs,
                                uint64_t refreshDurationNs) const;

    /** True only when binding and the native timeline source are both live. */
    bool supportsFrameTimeline() const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace emufusion::lsfg
