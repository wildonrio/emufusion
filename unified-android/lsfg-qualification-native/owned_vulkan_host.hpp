#pragma once

#include <android/hardware_buffer.h>
#include <android/native_window.h>
#include <vulkan/vulkan_core.h>

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>

namespace emufusion::lsfg {

/**
 * EmuFusion-owned Vulkan/AHardwareBuffer/WSI boundary.
 *
 * The LSFG wrapper deliberately owns a separate Vulkan device. This class
 * owns the presentation device and keeps every extension entry point in a
 * per-device table so LSFG's internal volkLoadDevice() cannot overwrite it.
 */
class OwnedVulkanHost final {
public:
    // Three presentation slots plus one exclusive continuous-inference slot.
    // Display ownership may retain the current buffer and its successor while
    // the next image is prepared; scratch must not consume that third slot.
    static constexpr uint32_t kFixedSlotCount = 4;

    struct FixedBuffers {
        AHardwareBuffer* left = nullptr;
        AHardwareBuffer* right = nullptr;
        AHardwareBuffer* output = nullptr;
    };

    struct Capabilities {
        uint64_t deviceKey = 0;
        uint32_t apiVersion = 0;
        uint32_t queueFamily = UINT32_MAX;
        uint32_t swapchainWidth = 0;
        uint32_t swapchainHeight = 0;
        uint32_t swapchainImageCount = 0;
        VkFormat swapchainFormat = VK_FORMAT_UNDEFINED;
        VkPresentModeKHR presentMode = VK_PRESENT_MODE_MAX_ENUM_KHR;
        uint64_t refreshDurationNs = 0;
        bool sameGraphicsPresentQueue = false;
        bool displayTiming = false;
        bool externalSyncFd = false;
        bool fixedBuffersImported = false;
        bool setupOwnershipReleased = false;
        bool liveResourcesReady = false;
    };

    struct LiveRequest {
        AHardwareBuffer* left = nullptr;
        AHardwareBuffer* right = nullptr;
        uint64_t presentId = 0;
        uint64_t physicalPresentTimeNs = 0;
        uint64_t desiredPresentTimeNs = 0;
        uint64_t completionDeadlineNs = 0;
        uint64_t refreshDurationNs = 0;
        uint64_t compositorFrameTimelineVsyncId = 0;
        uint64_t compositorFrameTimelineExpectedNs = 0;
        uint64_t compositorFrameTimelineDeadlineNs = 0;
        bool generated = false;
        bool presentRight = false;
        // Immutable producer identity from the existing validated JNI request.
        // Startup self-test rows leave these zero and cannot become captures.
        uint64_t sessionEpoch = 0;
        uint64_t presentationEpoch = 0;
        uint64_t leftSequence = 0;
        uint64_t rightSequence = 0;
        uint64_t leftTimestampNs = 0;
        uint64_t rightTimestampNs = 0;
        uint64_t contentTimestampNs = 0;
    };

    struct PreparedPresentation {
        uint32_t slotIndex = UINT32_MAX;
        int inputReadySyncFd = -3;
    };

    /**
     * One fixed AHardwareBuffer released from Vulkan to SurfaceFlinger.
     * The caller owns proofReadySyncFd and must transfer it exactly once.
     * buffer remains borrowed until retireSurfacePresentation().
     */
    struct SurfaceSubmission {
        uint32_t slotIndex = UINT32_MAX;
        AHardwareBuffer* buffer = nullptr;
        int proofReadySyncFd = -3;
        uint64_t presentId = 0;
        uint64_t physicalPresentTimeNs = 0;
        uint64_t desiredPresentTimeNs = 0;
        uint64_t compositorFrameTimelineVsyncId = 0;
        uint64_t compositorFrameTimelineExpectedNs = 0;
        uint64_t compositorFrameTimelineDeadlineNs = 0;
        uint64_t refreshDurationNs = 0;
    };

    struct Completion {
        bool dropped = false;
        uint64_t presentId = 0;
        uint64_t desiredPresentTimeNs = 0;
        uint64_t actualPresentTimeNs = 0;
        uint64_t earliestPresentTimeNs = 0;
        int64_t presentMarginNs = 0;
        uint64_t refreshDurationNs = 0;
        uint64_t gpuWorkNs = 0;
        /** Diagnostic copy of the already-read kernel proof fence timestamp. */
        uint64_t gpuCompletionNs = 0;
        uint32_t pairStatus = 0;
        uint64_t leftChecksum = 0;
        uint64_t rightChecksum = 0;
        uint64_t outputChecksum = 0;
        uint64_t endpointMadPpm = 0;
        uint64_t outputLeftMadPpm = 0;
        uint64_t outputRightMadPpm = 0;
        uint64_t endpointHistogramDistancePpm = 0;
        uint32_t outputMin = 0;
        uint32_t outputMax = 0;
        bool sceneCutRisk = false;
        uint64_t analysisWallNs = 0;
    };

    OwnedVulkanHost();
    ~OwnedVulkanHost();
    OwnedVulkanHost(const OwnedVulkanHost&) = delete;
    OwnedVulkanHost& operator=(const OwnedVulkanHost&) = delete;

    /** Creates one FIFO/display-timing swapchain on the supplied owned window. */
    void open(ANativeWindow* window, uint32_t endpointWidth,
              uint32_t endpointHeight);

    /**
     * Imports all fixed LSFG buffers into the presentation device, performs a
     * bounded setup-only layout transition, and releases ownership to EXTERNAL.
     */
    void importAndPrepareFixedBuffers(
            const std::array<FixedBuffers, kFixedSlotCount>& buffers);

    /**
     * Pays the implementation-defined AHardwareBuffer Vulkan import cost away
     * from a visible presentation deadline. The cache retains its own buffer
     * reference and repeated calls for a recycled ImageReader carrier are
     * cheap, idempotent hits.
     */
    void prepareSourceImage(AHardwareBuffer* buffer);

    /**
     * Zero-wait stage one. Imports the exact producer AHB pair into the next
     * retired slot, queues a GPU-only copy, and exports its one-shot sync FD.
     * Returns nullopt without consuming a slot when no slot is retired or a
     * structurally valid request expires before admission. No deadline is moved.
     */
    std::optional<PreparedPresentation> tryPrepare(
            const LiveRequest& request);

    /**
     * Queues only the exact endpoint copy needed by a future generated image.
     * No visible timing identity exists yet and no presentation is admitted.
     */
    std::optional<PreparedPresentation> tryPreparePrivateGenerated(
            AHardwareBuffer* left, AHardwareBuffer* right);

    /** Reserve one idle fixed slot for continuous inference until host teardown.
     * General presentation allocation must never select its scratch buffers.
     * Call before submitting continuous inputs; repeated identical reservation
     * is allowed. Changing the reserved slot requires a new host.
     */
    void reserveInferenceSlot(uint32_t slotIndex);
    /** Startup may leave one display buffer leased; choose an actually idle slot. */
    uint32_t reserveIdleInferenceSlot();

    /** Copy a pair into the reserved context's alternating input buffers.
     * nextInput chooses the buffer that LSFG will encode on this call. The
     * caller owns history admission and GPU completion before another copy.
     * The returned slot must be abandoned only after inference has finished.
     */
    std::optional<PreparedPresentation> tryPrepareContinuousInputs(
            AHardwareBuffer* previous, AHardwareBuffer* next, unsigned nextInput);

    /** Copies a completed continuous-context output into a retired display slot.
     * completionFd is borrowed and zero-polled; -1 explicitly means successful
     * already-signaled SYNC_FD export, never missing work. Values below -1 fail.
     * Caller retains all three sources
     * until referencesSourceImage returns false. No inference is performed.
     */
    std::optional<PreparedPresentation> tryCopyCompletedGenerated(
            AHardwareBuffer* left, AHardwareBuffer* right,
            AHardwareBuffer* generated, int completionFd);

    /**
     * Copies and proves both exact REAL endpoints before choosing a display
     * slot. No interpolation or visible identity is admitted. Once ready,
     * activation may select either of these immutable fixed endpoint buffers.
     */
    std::optional<PreparedPresentation> tryPreparePrivateEndpointPair(
            AHardwareBuffer* left, AHardwareBuffer* right);

    /**
     * Zero-polls abandoned work, then reports whether a live slot still owns
     * this source image. A retained AHB alone is not an ImageReader lease;
     * callers must not return the producer image while this is true.
     */
    bool referencesSourceImage(AHardwareBuffer* buffer);

    /** Retains the private LSFG or endpoint-copy fence without making it visible. */
    void holdPrivatePrepared(const PreparedPresentation& prepared,
                             int outputReadySyncFd);

    /**
     * Zero-polls the private proof and retains its actual kernel signal time.
     * Generated pairs are classified for interpolation; REAL pairs only need
     * completed endpoint proof and are never rejected merely for scene cuts.
     */
    uint32_t privatePreparedPairStatus(
            const PreparedPresentation& prepared);

    /**
     * Atomically binds a READY private image to the complete immutable visible
     * request. The endpoint pointers and generated identity must still match;
     * a prepared REAL pair permits selection of either exact endpoint.
     * Returns false if a valid proposal expires before activation, retaining
     * the exact private work without assigning a visible ID or pending credit.
     */
    bool activatePrivatePrepared(const PreparedPresentation& prepared,
                                 const LiveRequest& request);

    /** Safely discards private work, retiring only after every fence signals. */
    void abandonPrivatePrepared(const PreparedPresentation& prepared);

    /**
     * Zero-wait stage two. `outputReadySyncFd` is the LSFG output fence for a
     * generated request, or the untouched input-ready FD for an endpoint.
     * Ownership transfers on success. Polling later submits the FIFO present
     * only if this FD is already signaled before the immutable cutoff.
     */
    void presentPrepared(const PreparedPresentation& prepared,
                         int outputReadySyncFd);

    /**
     * Zero-polls the LSFG-ready FD and, before the immutable cutoff, queues
     * only the GPU-resident content proof/release command. Returns the exact
     * fixed AHB and its proof-ready acquire FD for SurfaceControl.
     */
    std::optional<SurfaceSubmission> pollSurfaceSubmission();

    /**
     * Joins the zero-polled Vulkan proof fence with the exact SurfaceControl
     * physical row. The slot remains owned until SurfaceFlinger releases it.
     */
    std::optional<Completion> pollSurfaceCompletion(
            uint64_t presentId, uint64_t desiredPresentTimeNs,
            uint64_t latchTimeNs, uint64_t actualPresentTimeNs);

    /** Retires a compositor-rejected submission after its proof fence signals. */
    void dropSurfacePresentation(uint64_t presentId);

    /** Returns one safely retired pre-submit/compositor-rejected row without waiting. */
    std::optional<Completion> pollDroppedSurfacePresentation();

    /** Oldest visible request not yet delivered as a completion (zero if none). */
    uint64_t oldestPendingSurfacePresentId() const;

    /** Retires a physically delivered slot after SurfaceFlinger release. */
    void retireSurfacePresentation(uint64_t presentId);

    /** Retires a copy-only request after LSFG reports its own ring busy. */
    void abandonPrepared(const PreparedPresentation& prepared);

    /** Returns at most one fully joined GPU/content/physical row, never waits. */
    std::optional<Completion> pollCompletion();

    /** Invalidates future requests without destroying already queued rows. */
    void resetTimeline(uint64_t presentationEpoch);

    const Capabilities& capabilities() const;
    std::string capabilityJson() const;
    /** Zero-wait setup diagnostics used only to classify a bounded self-test failure. */
    std::string diagnosticJson() const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace emufusion::lsfg
