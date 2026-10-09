#include <jni.h>

#include <android/hardware_buffer.h>
#include <android/hardware_buffer_jni.h>
#include <android/log.h>
#include <android/native_window.h>
#include <android/native_window_jni.h>
#include <android/sync.h>
#include <poll.h>
#include <unistd.h>
#include <vulkan/vulkan_core.h>

#include <array>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "lsfg_3_1.hpp"
#include "continuous_inference.hpp"
#include "midpoint_timestamp.hpp"
#include "owned_surface_control_presenter.hpp"
#include "owned_vulkan_host.hpp"
#include "presentation_timing_diagnostics.hpp"
#include "surface_present_timing.hpp"
#include "sync_poll_result.hpp"

#if EMUFUSION_LSFG_PIXEL_PROBE
#include <fcntl.h>
#include "temporal_history.hpp"
#endif

#define LOG_TAG "EmuFusion-LSFG"
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

namespace {

constexpr uint32_t kSlotCount = emufusion::lsfg::OwnedVulkanHost::kFixedSlotCount;
constexpr uint32_t kGenerationCount = 1;
constexpr uint32_t kSpirvOffset = 98;
constexpr int kSetupFenceTimeoutMs = 1000;

const std::unordered_map<std::string, uint32_t> kShaderResourceIds = {
    {"mipmaps", 255}, {"alpha[0]", 267}, {"alpha[1]", 268},
    {"alpha[2]", 269}, {"alpha[3]", 270}, {"beta[0]", 275},
    {"beta[1]", 276}, {"beta[2]", 277}, {"beta[3]", 278},
    {"beta[4]", 279}, {"gamma[0]", 257}, {"gamma[1]", 259},
    {"gamma[2]", 260}, {"gamma[3]", 261}, {"gamma[4]", 262},
    {"delta[0]", 257}, {"delta[1]", 263}, {"delta[2]", 264},
    {"delta[3]", 265}, {"delta[4]", 266}, {"delta[5]", 258},
    {"delta[6]", 271}, {"delta[7]", 272}, {"delta[8]", 273},
    {"delta[9]", 274}, {"generate", 256},
};

struct Slot {
    AHardwareBuffer* left = nullptr;
    AHardwareBuffer* right = nullptr;
    AHardwareBuffer* output = nullptr;
    int32_t context = -1;
};

struct PreparedGenerated {
    AHardwareBuffer* left = nullptr;
    AHardwareBuffer* right = nullptr;
    uint64_t sessionEpoch = 0;
    uint64_t presentationEpoch = 0;
    uint64_t leftSequence = 0;
    uint64_t leftTimestampNs = 0;
    uint64_t rightSequence = 0;
    uint64_t rightTimestampNs = 0;
    uint64_t presentationTimestampNs = 0;
    emufusion::lsfg::OwnedVulkanHost::PreparedPresentation prepared{};

    bool matches(AHardwareBuffer* candidateLeft,
                 AHardwareBuffer* candidateRight,
                 uint64_t candidateSessionEpoch,
                 uint64_t candidatePresentationEpoch,
                 uint64_t candidateLeftSequence,
                 uint64_t candidateLeftTimestampNs,
                 uint64_t candidateRightSequence,
                 uint64_t candidateRightTimestampNs,
                 uint64_t candidatePresentationTimestampNs) const {
        return left == candidateLeft && right == candidateRight &&
                sessionEpoch == candidateSessionEpoch &&
                presentationEpoch == candidatePresentationEpoch &&
                leftSequence == candidateLeftSequence &&
                leftTimestampNs == candidateLeftTimestampNs &&
                rightSequence == candidateRightSequence &&
                rightTimestampNs == candidateRightTimestampNs &&
                presentationTimestampNs == candidatePresentationTimestampNs;
    }
};

// Canonical phase zero announces both endpoints, not the eventual selection.
// The visible request may choose either exact timestamp from this same pair.
struct PreparedRealPair {
    PreparedGenerated identity{};

    bool matches(AHardwareBuffer* left, AHardwareBuffer* right,
                 uint64_t sessionEpoch, uint64_t presentationEpoch,
                 uint64_t leftSequence, uint64_t leftTimestampNs,
                 uint64_t rightSequence, uint64_t rightTimestampNs) const {
        return identity.matches(left, right, sessionEpoch, presentationEpoch,
                leftSequence, leftTimestampNs, rightSequence, rightTimestampNs,
                leftTimestampNs);
    }
};

struct ContinuousPair {
    PreparedGenerated identity;
    bool needsLeft = false;
    bool inFlight = false;
    bool outputComplete = false;
    bool unsafe = false;
    bool discarded = false;
};

struct Host {
    std::mutex mutex;
    ANativeWindow* window = nullptr;
    std::array<Slot, kSlotCount> slots{};
    bool initialized = false;
    bool contextsPrewarmed = false;
    bool selfTestPassed = false;
    bool selfTestEndpoint = false;
    bool selfTestGenerated = false;
    bool selfTestDeadline = false;
    bool selfTestPhysicalTiming = false;
    bool selfTestContent = false;
    bool selfTestLiveSurfaceControl = false;
    bool selfTestLiveCadence = false;
    uint64_t selfTestLiveCadencePresents = 0;
    uint64_t selfTestLiveCadenceGenerated = 0;
    uint64_t selfTestLiveCadenceMinIntervalNs = 0;
    uint64_t selfTestLiveCadenceMaxIntervalNs = 0;
    uint64_t selfTestLiveCadenceMaxErrorNs = 0;
    uint64_t selfTestGenerationCompleteNs = 0;
    uint64_t selfTestGenerationDeadlineNs = 0;
    uint64_t selfTestFirstDesiredNs = 0;
    uint64_t selfTestFirstLatchNs = 0;
    uint64_t selfTestFirstActualNs = 0;
    uint64_t selfTestSecondDesiredNs = 0;
    uint64_t selfTestSecondLatchNs = 0;
    uint64_t selfTestSecondActualNs = 0;
    uint64_t selfTestPhysicalIntervalNs = 0;
    uint64_t selfTestPhysicalAnchorNs = 0;
    uint64_t selfTestPresentFenceOffsetNs = 0;
    bool closed = false;
    uint32_t width = 0;
    uint32_t height = 0;
    std::unique_ptr<emufusion::lsfg::OwnedVulkanHost> ownedVulkan;
    std::unique_ptr<emufusion::lsfg::OwnedSurfaceControlPresenter>
            surfacePresenter;
    std::map<uint64_t,
            emufusion::lsfg::OwnedSurfaceControlPresenter::Completion>
            physicalCompletions;
    std::map<uint64_t, emufusion::lsfg::OwnedVulkanHost::Completion>
            droppedCompletions;
    std::set<uint64_t> deliveredAwaitingRelease;
    std::optional<PreparedGenerated> preparedGenerated;
    std::unique_ptr<emufusion::lsfg::ContinuousInference> continuous;
    uint32_t inferenceSlotIndex = 0;
    std::optional<ContinuousPair> continuousPair;
    std::optional<PreparedRealPair> preparedRealPair;
    // Diagnostic budget and exact request copies survive every live epoch.
    emufusion::lsfg::PresentationTimingDiagnostics timingDiagnostics;
};

std::mutex g_libraryMutex;
Host* g_libraryOwner = nullptr;

uint64_t monotonicNowNs() {
    return static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                    std::chrono::steady_clock::now().time_since_epoch()).count());
}

uint64_t alignedFuturePresentTime(uint64_t physicalAnchorNs,
                                  uint64_t refreshDurationNs,
                                  uint64_t nowNs,
                                  uint64_t minimumPeriodsAhead) {
    if (physicalAnchorNs == 0 || refreshDurationNs == 0 ||
            minimumPeriodsAhead == 0)
        throw std::invalid_argument("invalid physical presentation anchor");
    if (minimumPeriodsAhead >
            (UINT64_MAX - nowNs) / refreshDurationNs)
        throw std::overflow_error("physical presentation lead overflow");
    const uint64_t minimumTarget =
            nowNs + minimumPeriodsAhead * refreshDurationNs;
    if (physicalAnchorNs >= minimumTarget) return physicalAnchorNs;
    const uint64_t delta = minimumTarget - physicalAnchorNs;
    const uint64_t periods = delta / refreshDurationNs +
            (delta % refreshDurationNs == 0 ? 0ULL : 1ULL);
    if (periods > (UINT64_MAX - physicalAnchorNs) / refreshDurationNs)
        throw std::overflow_error("aligned physical presentation overflow");
    return physicalAnchorNs + periods * refreshDurationNs;
}

uint64_t normalizedPhysicalPresentTime(uint64_t rawPresentFenceTimeNs,
                                       uint64_t presentFenceOffsetNs) {
    if (rawPresentFenceTimeNs == 0 ||
            rawPresentFenceTimeNs > UINT64_MAX - presentFenceOffsetNs)
        throw std::overflow_error("normalized physical timestamp overflow");
    return rawPresentFenceTimeNs + presentFenceOffsetNs;
}

bool physicalTargetWithinTolerance(uint64_t actualPresentTimeNs,
                                   uint64_t desiredPresentTimeNs,
                                   uint64_t earlyToleranceNs,
                                   uint64_t maximumLateNs) {
    if (actualPresentTimeNs >= desiredPresentTimeNs)
        return actualPresentTimeNs - desiredPresentTimeNs <= maximumLateNs;
    return desiredPresentTimeNs - actualPresentTimeNs <= earlyToleranceNs;
}

std::string jstringValue(JNIEnv* env, jstring value) {
    if (value == nullptr) throw std::invalid_argument("string is null");
    const char* chars = env->GetStringUTFChars(value, nullptr);
    if (chars == nullptr) throw std::runtime_error("GetStringUTFChars failed");
    std::string result(chars);
    env->ReleaseStringUTFChars(value, chars);
    return result;
}

std::vector<uint8_t> readShader(const std::string& directory,
                                const std::string& symbolicName) {
    const auto found = kShaderResourceIds.find(symbolicName);
    if (found == kShaderResourceIds.end())
        throw std::runtime_error("unknown LSFG shader name: " + symbolicName);
    const uint32_t resource = found->second + kSpirvOffset;
    const std::string path = directory + "/" + std::to_string(resource) + ".spv";
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) throw std::runtime_error("missing LSFG shader: " + path);
    const std::streamsize size = stream.tellg();
    if (size < 20 || (size % 4) != 0)
        throw std::runtime_error("invalid LSFG SPIR-V size: " + path);
    stream.seekg(0);
    std::vector<uint8_t> bytes(static_cast<size_t>(size));
    if (!stream.read(reinterpret_cast<char*>(bytes.data()), size))
        throw std::runtime_error("unable to read LSFG shader: " + path);
    const uint32_t magic = static_cast<uint32_t>(bytes[0]) |
        (static_cast<uint32_t>(bytes[1]) << 8U) |
        (static_cast<uint32_t>(bytes[2]) << 16U) |
        (static_cast<uint32_t>(bytes[3]) << 24U);
    if (magic != 0x07230203U)
        throw std::runtime_error("invalid LSFG SPIR-V magic: " + path);
    return bytes;
}

AHardwareBuffer* allocateBuffer(uint32_t width, uint32_t height) {
    AHardwareBuffer_Desc descriptor{};
    descriptor.width = width;
    descriptor.height = height;
    descriptor.layers = 1;
    descriptor.format = AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM;
    descriptor.usage = AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE |
        AHARDWAREBUFFER_USAGE_GPU_COLOR_OUTPUT |
        AHARDWAREBUFFER_USAGE_COMPOSER_OVERLAY |
        AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN |
        AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN;
    AHardwareBuffer* buffer = nullptr;
    if (AHardwareBuffer_allocate(&descriptor, &buffer) != 0 || buffer == nullptr)
        throw std::runtime_error("AHardwareBuffer allocation failed");
    return buffer;
}

void fillSetupPattern(AHardwareBuffer* buffer, uint8_t bias) {
    AHardwareBuffer_Desc descriptor{};
    AHardwareBuffer_describe(buffer, &descriptor);
    void* mapped = nullptr;
    if (AHardwareBuffer_lock(buffer, AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN,
            -1, nullptr, &mapped) != 0 || mapped == nullptr)
        throw std::runtime_error("setup AHardwareBuffer lock failed");
    auto* pixels = static_cast<uint8_t*>(mapped);
    for (uint32_t y = 0; y < descriptor.height; ++y) {
        for (uint32_t x = 0; x < descriptor.width; ++x) {
            const size_t offset = (static_cast<size_t>(y) * descriptor.stride + x) * 4U;
            pixels[offset + 0] = static_cast<uint8_t>(bias + (x & 31U));
            pixels[offset + 1] = static_cast<uint8_t>(bias + (y & 31U));
            pixels[offset + 2] = bias;
            pixels[offset + 3] = 255;
        }
    }
    int fenceFd = -1;
    if (AHardwareBuffer_unlock(buffer, &fenceFd) != 0)
        throw std::runtime_error("setup AHardwareBuffer unlock failed");
    if (fenceFd >= 0) {
        pollfd descriptorFd{fenceFd, POLLIN, 0};
        const int result = ::poll(&descriptorFd, 1, kSetupFenceTimeoutMs);
        ::close(fenceFd);
        if (result != 1 ||
                !emufusion::lsfg::successfulSyncPoll(result, descriptorFd.revents))
            throw std::runtime_error("setup AHardwareBuffer fence timeout");
    }
}

void fillSoakPattern(AHardwareBuffer* buffer, uint32_t frameIndex) {
    AHardwareBuffer_Desc descriptor{};
    AHardwareBuffer_describe(buffer, &descriptor);
    void* mapped = nullptr;
    if (AHardwareBuffer_lock(buffer, AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN,
            -1, nullptr, &mapped) != 0 || mapped == nullptr)
        throw std::runtime_error("soak AHardwareBuffer lock failed");
    auto* pixels = static_cast<uint8_t*>(mapped);
    const uint32_t barLeft = (frameIndex * 3U) % descriptor.width;
    for (uint32_t y = 0; y < descriptor.height; ++y) {
        for (uint32_t x = 0; x < descriptor.width; ++x) {
            const size_t offset =
                    (static_cast<size_t>(y) * descriptor.stride + x) * 4U;
            const bool bar = x >= barLeft && x < std::min(
                    descriptor.width, barLeft + 24U);
            pixels[offset + 0] = static_cast<uint8_t>(
                    24U + ((x + frameIndex) & 63U));
            pixels[offset + 1] = static_cast<uint8_t>(
                    32U + ((y * 2U + frameIndex) & 63U));
            pixels[offset + 2] = bar ? 208U : static_cast<uint8_t>(
                    40U + ((x + y + frameIndex) & 31U));
            pixels[offset + 3] = 255U;
        }
    }
    int fenceFd = -1;
    if (AHardwareBuffer_unlock(buffer, &fenceFd) != 0)
        throw std::runtime_error("soak AHardwareBuffer unlock failed");
    if (fenceFd >= 0) {
        pollfd descriptorFd{fenceFd, POLLIN, 0};
        const int result = ::poll(&descriptorFd, 1, kSetupFenceTimeoutMs);
        ::close(fenceFd);
        if (result != 1 ||
                !emufusion::lsfg::successfulSyncPoll(result, descriptorFd.revents))
            throw std::runtime_error("soak AHardwareBuffer fence timeout");
    }
}

void destroyHost(Host* host) {
    if (host == nullptr) return;
    host->continuousPair.reset();
    host->continuous.reset();
    for (Slot& slot : host->slots) {
        if (slot.context >= 0) {
            try { LSFG_3_1::deleteContext(slot.context); }
            catch (const std::exception& error) {
                LOGE("deleteContext failed: %s", error.what());
            }
            slot.context = -1;
        }
    }
    if (host->initialized) {
        try { LSFG_3_1::finalize(); }
        catch (const std::exception& error) { LOGE("finalize failed: %s", error.what()); }
        host->initialized = false;
    }
    // Hide/release the compositor child before destroying imported AHBs.
    host->surfacePresenter.reset();
    host->physicalCompletions.clear();
    host->droppedCompletions.clear();
    host->deliveredAwaitingRelease.clear();
    // The owned Vulkan device must be destroyed while its native window and
    // fixed AHB allocations are still alive.
    host->ownedVulkan.reset();
    for (Slot& slot : host->slots) {
        if (slot.output != nullptr) AHardwareBuffer_release(slot.output);
        if (slot.right != nullptr) AHardwareBuffer_release(slot.right);
        if (slot.left != nullptr) AHardwareBuffer_release(slot.left);
        slot = {};
    }
    if (host->window != nullptr) ANativeWindow_release(host->window);
    host->window = nullptr;
}

Host* fromHandle(jlong handle) {
    if (handle == 0) throw std::invalid_argument("LSFG host handle is zero");
    return reinterpret_cast<Host*>(static_cast<uintptr_t>(handle));
}

// Returns the existing JNI preparation codes: absent/pending/ready/unsafe.
// At most one inference or output-copy submission per call; never waits.
int progressContinuousPair(Host* host) {
    using CI = emufusion::lsfg::ContinuousInference;
    if (!host->continuousPair) return 0;
    auto& pair = *host->continuousPair;
    auto& identity = pair.identity;
    if (pair.inFlight) {
        if (host->continuous->poll() != CI::Completion::Ready) return 1;
        pair.inFlight = false;
        if (pair.needsLeft) pair.needsLeft = false;
        else pair.outputComplete = true;
    }
    if (pair.discarded) {
        host->continuousPair.reset();
        return 0;
    }
    if (pair.unsafe) return 3;
    if (pair.outputComplete) {
        if (!host->continuous->historyReady()) {
            // Initial real frames build history; uninitialized output is never
            // eligible for presentation. No duplicated synthetic warm-up input.
            pair.unsafe = true;
            return 3;
        }
        auto copied = host->ownedVulkan->tryCopyCompletedGenerated(
                identity.left, identity.right, host->slots[host->inferenceSlotIndex].output,
                host->continuous->completedFence());
        if (!copied) return 1;
        host->ownedVulkan->holdPrivatePrepared(*copied, copied->inputReadySyncFd);
        host->preparedGenerated = identity;
        host->preparedGenerated->prepared = {copied->slotIndex, -1};
        host->continuousPair.reset();
        return 1;
    }
    const bool left = pair.needsLeft;
    const auto submission = host->continuous->submit(identity.left,
            left ? identity.left : identity.right,
            {identity.sessionEpoch, identity.presentationEpoch,
             left ? identity.leftSequence : identity.rightSequence,
             left ? identity.leftTimestampNs : identity.rightTimestampNs});
    if (submission == CI::Submission::RecreateRequired)
        throw std::runtime_error("LSFG source continuity changed; recreate transport");
    pair.inFlight = submission == CI::Submission::Submitted;
    return 1;
}

void discardContinuousPair(Host* host) {
    if (!host->continuousPair) return;
    host->continuousPair->discarded = true;
    (void) progressContinuousPair(host);
}

struct AhbRelease {
    void operator()(AHardwareBuffer* buffer) const {
        if (buffer != nullptr) AHardwareBuffer_release(buffer);
    }
};

void runBoundedOwnedSelfTest(Host* host) {
    if (host == nullptr || host->ownedVulkan == nullptr ||
            !host->contextsPrewarmed)
        throw std::logic_error("LSFG self-test setup is incomplete");
    std::unique_ptr<AHardwareBuffer, AhbRelease> left(
            allocateBuffer(host->width, host->height));
    std::unique_ptr<AHardwareBuffer, AhbRelease> right(
            allocateBuffer(host->width, host->height));
    fillSetupPattern(left.get(), 24U);
    fillSetupPattern(right.get(), 36U);
    host->ownedVulkan->resetTimeline(1);
    const uint64_t refresh =
            host->ownedVulkan->capabilities().refreshDurationNs;
    if (refresh == 0) throw std::runtime_error("self-test refresh is zero");
    const uint64_t now = static_cast<uint64_t>(std::chrono::duration_cast<
            std::chrono::nanoseconds>(std::chrono::steady_clock::now()
                    .time_since_epoch()).count());
    constexpr uint64_t driverLeadNs = 2'000'000ULL;
    const uint64_t firstPhysical = now + refresh * 12ULL;
    if (firstPhysical <= driverLeadNs)
        throw std::overflow_error("self-test timestamp overflow");
    const uint64_t firstDriver = firstPhysical - driverLeadNs;
    const uint64_t secondPhysical = firstPhysical + refresh;
    const uint64_t secondDriver = secondPhysical - driverLeadNs;
    const emufusion::lsfg::OwnedVulkanHost::LiveRequest endpointRequest{
        .left = left.get(),
        .right = right.get(),
        .presentId = 1,
        .physicalPresentTimeNs = firstPhysical,
        .desiredPresentTimeNs = firstDriver,
        .completionDeadlineNs = firstDriver,
        .refreshDurationNs = refresh,
        .generated = false,
        .presentRight = false,
    };
    auto endpoint = host->ownedVulkan->tryPrepare(endpointRequest);
    if (!endpoint.has_value())
        throw std::runtime_error("self-test endpoint slot unavailable");
    host->ownedVulkan->presentPrepared(
            *endpoint, endpoint->inputReadySyncFd);

    const emufusion::lsfg::OwnedVulkanHost::LiveRequest generatedRequest{
        .left = left.get(),
        .right = right.get(),
        .presentId = 2,
        .physicalPresentTimeNs = secondPhysical,
        .desiredPresentTimeNs = secondDriver,
        .completionDeadlineNs = secondDriver,
        .refreshDurationNs = refresh,
        .generated = true,
        .presentRight = false,
    };
    auto generated = host->ownedVulkan->tryPrepare(generatedRequest);
    if (!generated.has_value())
        throw std::runtime_error("self-test generated slot unavailable");
    int outputReadyFd = LSFG_3_1::tryPresentContextSyncFd(
            host->slots[generated->slotIndex].context,
            generated->inputReadySyncFd);
    if (outputReadyFd == -2) {
        host->ownedVulkan->abandonPrepared(*generated);
        throw std::runtime_error("self-test LSFG context is busy");
    }
    if (outputReadyFd < -1)
        throw std::runtime_error("self-test LSFG output fence failed");
    host->ownedVulkan->presentPrepared(*generated, outputReadyFd);

    std::array<emufusion::lsfg::OwnedVulkanHost::Completion, 2> rows{};
    uint32_t completed = 0;
    // GOOGLE_display_timing feedback is explicitly asynchronous and may lag
    // physical presentation by many refreshes. Keep the live deadlines above
    // exact, but give this setup-only collector a fixed finite horizon rather
    // than incorrectly treating twelve refreshes as a driver guarantee.
    constexpr uint64_t timingFeedbackTimeoutNs = 3'000'000'000ULL;
    if (secondPhysical > UINT64_MAX - timingFeedbackTimeoutNs)
        throw std::overflow_error("self-test timing deadline overflow");
    const uint64_t pollDeadline = secondPhysical + timingFeedbackTimeoutNs;
    while (completed < rows.size()) {
        auto row = host->ownedVulkan->pollCompletion();
        if (row.has_value()) rows[completed++] = *row;
        if (completed == rows.size()) break;
        const uint64_t pollNow = static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now().time_since_epoch()).count());
        if (pollNow >= pollDeadline) {
            throw std::runtime_error(
                    "self-test physical timing timeout diagnostics=" +
                    host->ownedVulkan->diagnosticJson());
        }
        ::usleep(250);
    }
    host->selfTestEndpoint = rows[0].presentId == 1 &&
            rows[0].outputChecksum == rows[0].leftChecksum;
    host->selfTestGenerated = rows[1].presentId == 2 &&
            rows[1].outputChecksum != rows[1].leftChecksum &&
            rows[1].outputChecksum != rows[1].rightChecksum;
    host->selfTestDeadline = rows[0].gpuWorkNs > 0 && rows[1].gpuWorkNs > 0 &&
            rows[0].gpuWorkNs < firstDriver - now &&
            rows[1].gpuWorkNs < secondDriver - now;
    const uint64_t tolerance = std::max<uint64_t>(
            150'000ULL, (refresh + 49ULL) / 50ULL);
    const auto absoluteDifference = [](uint64_t a, uint64_t b) {
        return a >= b ? a - b : b - a;
    };
    host->selfTestPhysicalTiming =
            rows[0].actualPresentTimeNs < rows[1].actualPresentTimeNs &&
            absoluteDifference(rows[0].actualPresentTimeNs, firstPhysical) <= tolerance &&
            absoluteDifference(rows[1].actualPresentTimeNs, secondPhysical) <= tolerance;
    host->selfTestContent = rows[0].pairStatus == 1 &&
            rows[1].pairStatus == 1 && !rows[0].sceneCutRisk &&
            !rows[1].sceneCutRisk && rows[0].analysisWallNs > 0 &&
            rows[1].analysisWallNs > 0;
    host->selfTestPassed = host->selfTestEndpoint && host->selfTestGenerated &&
            host->selfTestDeadline && host->selfTestPhysicalTiming &&
            host->selfTestContent;
    if (!host->selfTestPassed)
        throw std::runtime_error("owned LSFG self-test evidence rejected");
}

struct SetupContentRecord {
    uint64_t checksum = 1469598103934665603ULL;
    uint8_t minimum = 255;
    uint8_t maximum = 0;
};

SetupContentRecord readSetupContent(AHardwareBuffer* buffer) {
    if (buffer == nullptr) throw std::invalid_argument("setup content buffer is null");
    AHardwareBuffer_Desc descriptor{};
    AHardwareBuffer_describe(buffer, &descriptor);
    void* mapped = nullptr;
    if (AHardwareBuffer_lock(buffer, AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN,
            -1, nullptr, &mapped) != 0 || mapped == nullptr)
        throw std::runtime_error("setup content AHardwareBuffer lock failed");
    SetupContentRecord result;
    try {
        const auto* pixels = static_cast<const uint8_t*>(mapped);
        constexpr uint64_t fnvPrime = 1099511628211ULL;
        for (uint32_t y = 0; y < descriptor.height; ++y) {
            for (uint32_t x = 0; x < descriptor.width; ++x) {
                const size_t offset =
                        (static_cast<size_t>(y) * descriptor.stride + x) * 4U;
                for (uint32_t channel = 0; channel < 3; ++channel) {
                    const uint8_t value = pixels[offset + channel];
                    result.checksum = (result.checksum ^ value) * fnvPrime;
                    result.minimum = std::min(result.minimum, value);
                    result.maximum = std::max(result.maximum, value);
                }
            }
        }
    } catch (...) {
        AHardwareBuffer_unlock(buffer, nullptr);
        throw;
    }
    if (AHardwareBuffer_unlock(buffer, nullptr) != 0)
        throw std::runtime_error("setup content AHardwareBuffer unlock failed");
    return result;
}

uint64_t signaledSyncFenceTimestamp(int fenceFd) {
    if (fenceFd < 0) return 0;
    pollfd descriptor{fenceFd, POLLIN, 0};
    const int pollResult = ::poll(&descriptor, 1, 0);
    if (pollResult != 1 ||
            !emufusion::lsfg::successfulSyncPoll(pollResult, descriptor.revents))
        return 0;
    std::unique_ptr<struct sync_file_info,
            decltype(&sync_file_info_free)> info(
            sync_file_info(fenceFd), &sync_file_info_free);
    if (!info || info->status != 1 || info->num_fences == 0)
        throw std::runtime_error("setup LSFG sync fence status invalid");
    uint64_t timestampNs = 0;
    const sync_fence_info* fences = sync_get_fence_info(info.get());
    for (uint32_t index = 0; index < info->num_fences; ++index) {
        if (fences[index].status != 1 || fences[index].timestamp_ns == 0)
            throw std::runtime_error("setup LSFG child fence invalid");
        timestampNs = std::max<uint64_t>(
                timestampNs, fences[index].timestamp_ns);
    }
    return timestampNs;
}

// Submit at most the oldest eligible output. Does not consume completions:
// Java has not committed its presentation ledger when enqueue calls this.
// pollSurfaceSubmission retains the immutable cutoff and GPU readiness gates;
// the presenter's existing worker applies the exact token-bearing transaction.
void dispatchReadySurfaceSubmission(Host* host) {
    auto submission = host->ownedVulkan->pollSurfaceSubmission();
    if (!submission.has_value()) return;
    const bool accepted = host->surfacePresenter->present(
            submission->buffer, submission->proofReadySyncFd,
            submission->presentId,
            // Token-less startup retains its driver not-before bound.
            submission->desiredPresentTimeNs,
            submission->compositorFrameTimelineVsyncId,
            submission->compositorFrameTimelineExpectedNs,
            submission->compositorFrameTimelineDeadlineNs,
            submission->compositorFrameTimelineVsyncId == 0 ? 0 :
                    submission->refreshDurationNs);
    if (!accepted) {
        if (submission->proofReadySyncFd >= 0)
            ::close(submission->proofReadySyncFd);
        host->ownedVulkan->dropSurfacePresentation(submission->presentId);
    } else {
        host->timingDiagnostics.submitted(submission->slotIndex, {
            .presentId = submission->presentId,
            .physicalTargetNs = submission->physicalPresentTimeNs,
            .driverDesiredNs = submission->desiredPresentTimeNs,
            .vsyncId = submission->compositorFrameTimelineVsyncId,
            .tokenExpectedNs = submission->compositorFrameTimelineExpectedNs,
            .tokenDeadlineNs = submission->compositorFrameTimelineDeadlineNs,
        });
    }
}

void logSurfaceTimingDiagnostic(
        Host* host, const char* stage,
        const emufusion::lsfg::OwnedSurfaceControlPresenter::Completion& row,
        bool normalizedAvailable,
        const emufusion::lsfg::OwnedVulkanHost::Completion* gpu,
        bool failed) {
    if (failed) {
        if (!host->timingDiagnostics.takeFailure()) return;
    } else {
        // The 240-row startup soak uses this same Host. It must not consume
        // any of the 32 real-game rows; there is no later counter reset.
        if (!host->selfTestLiveCadence || std::strcmp(stage, "live") != 0 ||
                !host->timingDiagnostics.takeLiveRow()) return;
    }
    const auto exact = host->timingDiagnostics.request(row.presentId);
    const auto request = exact.value_or(
            emufusion::lsfg::PresentationTimingRequest{});
    __android_log_print(failed ? ANDROID_LOG_ERROR : ANDROID_LOG_INFO,
            LOG_TAG,
            "Surface timing diagnostic stage=%s failed=%d liveRow=%u "
            "presentId=%llu requestKnown=%d rawPresentFenceNs=%llu "
            "addedOffsetNs=%llu normalizedKnown=%d normalizedPresentNs=%llu "
            "physicalTargetNs=%llu driverDesiredNs=%llu vsyncId=%llu "
            "tokenExpectedNs=%llu tokenDeadlineNs=%llu "
            "applyStartNs=%llu applyEndNs=%llu latchNs=%llu "
            "gpuSignalKnown=%d gpuSignalNs=%llu gpuWorkNs=%llu",
            stage, failed ? 1 : 0, host->timingDiagnostics.liveRows(),
            static_cast<unsigned long long>(row.presentId), exact.has_value() ? 1 : 0,
            static_cast<unsigned long long>(row.rawPresentFenceTimeNs),
            static_cast<unsigned long long>(host->selfTestPresentFenceOffsetNs),
            normalizedAvailable ? 1 : 0,
            static_cast<unsigned long long>(normalizedAvailable ? row.actualPresentTimeNs : 0),
            static_cast<unsigned long long>(request.physicalTargetNs),
            static_cast<unsigned long long>(request.driverDesiredNs),
            static_cast<unsigned long long>(request.vsyncId),
            static_cast<unsigned long long>(request.tokenExpectedNs),
            static_cast<unsigned long long>(request.tokenDeadlineNs),
            static_cast<unsigned long long>(row.transactionApplyStartNs),
            static_cast<unsigned long long>(row.transactionApplyEndNs),
            static_cast<unsigned long long>(row.latchTimeNs),
            gpu != nullptr && gpu->gpuCompletionNs != 0 ? 1 : 0,
            static_cast<unsigned long long>(gpu != nullptr ? gpu->gpuCompletionNs : 0),
            static_cast<unsigned long long>(gpu != nullptr ? gpu->gpuWorkNs : 0));
}

std::optional<emufusion::lsfg::OwnedVulkanHost::Completion>
progressLiveSurfacePipeline(Host* host, const char* diagnosticStage = "live") {
    if (host == nullptr || host->ownedVulkan == nullptr ||
            host->surfacePresenter == nullptr)
        throw std::logic_error("live SurfaceControl pipeline is unavailable");
    for (auto it = host->deliveredAwaitingRelease.begin();
            it != host->deliveredAwaitingRelease.end();) {
        if (!host->surfacePresenter->isReleased(*it)) {
            ++it;
            continue;
        }
        const uint64_t presentId = *it;
        host->surfacePresenter->retire(presentId);
        host->ownedVulkan->retireSurfacePresentation(presentId);
        it = host->deliveredAwaitingRelease.erase(it);
    }

    dispatchReadySurfaceSubmission(host);

    auto dropped = host->ownedVulkan->pollDroppedSurfacePresentation();
    if (dropped.has_value())
        host->droppedCompletions.emplace(dropped->presentId, *dropped);

    const auto unavailable =
            host->surfacePresenter->takeUnavailablePresentFences();
    if (!unavailable.empty()) {
        emufusion::lsfg::OwnedSurfaceControlPresenter::Completion unknown{};
        unknown.presentId = unavailable.front();
        logSurfaceTimingDiagnostic(host, diagnosticStage, unknown, false,
                nullptr, true);
        throw emufusion::lsfg::PresentFenceUnavailable(
                "live SurfaceControl completion omitted its present fence"
                " stage=" + std::string(diagnosticStage) +
                " presentId=" + std::to_string(unavailable.front()) +
                " count=" + std::to_string(unavailable.size()) +
                " diagnostics=" + host->surfacePresenter->diagnosticJson());
    }
    auto physical = host->surfacePresenter->pollCompletion();
    if (physical.has_value()) {
        physical->actualPresentTimeNs = normalizedPhysicalPresentTime(
                physical->actualPresentTimeNs,
                host->selfTestPresentFenceOffsetNs);
        const auto inserted = host->physicalCompletions.emplace(
                physical->presentId, *physical);
        if (!inserted.second)
            throw std::runtime_error(
                    "duplicate SurfaceControl physical completion");
    }

    // A ready dropped row does not prove that an earlier applied transaction
    // was dropped. Likewise a newer physical row cannot retire an older GPU
    // request still draining. Keep the exact native ownership order even when
    // the older callback has not populated either completion map yet.
    uint64_t candidateId = 0;
    if (!host->droppedCompletions.empty())
        candidateId = host->droppedCompletions.begin()->first;
    if (!host->physicalCompletions.empty() &&
            (candidateId == 0 || host->physicalCompletions.begin()->first < candidateId))
        candidateId = host->physicalCompletions.begin()->first;
    const uint64_t oldestPendingId =
            host->ownedVulkan->oldestPendingSurfacePresentId();
    if (candidateId != 0 && oldestPendingId != 0 && oldestPendingId < candidateId)
        return std::nullopt;

    if (!host->droppedCompletions.empty() &&
            (host->physicalCompletions.empty() ||
                    host->droppedCompletions.begin()->first <
                            host->physicalCompletions.begin()->first)) {
        auto row = host->droppedCompletions.begin();
        auto result = row->second;
        host->droppedCompletions.erase(row);
        return result;
    }
    if (host->physicalCompletions.empty()) return std::nullopt;
    const auto physicalRow = host->physicalCompletions.begin();
    std::optional<emufusion::lsfg::OwnedVulkanHost::Completion> completion;
    try {
        completion = host->ownedVulkan->pollSurfaceCompletion(
                physicalRow->second.presentId,
                physicalRow->second.desiredPresentTimeNs,
                physicalRow->second.latchTimeNs,
                physicalRow->second.actualPresentTimeNs);
    } catch (...) {
        logSurfaceTimingDiagnostic(host, diagnosticStage, physicalRow->second,
                true, nullptr, true);
        throw;
    }
    if (!completion.has_value()) return std::nullopt;
    logSurfaceTimingDiagnostic(host, diagnosticStage, physicalRow->second,
            true, &*completion, false);
    host->deliveredAwaitingRelease.insert(physicalRow->second.presentId);
    host->physicalCompletions.erase(physicalRow);
    return completion;
}

void runBoundedSurfaceControlSelfTest(Host* host) {
    if (host == nullptr || host->ownedVulkan == nullptr ||
            !host->contextsPrewarmed || host->slots[0].context < 0)
        throw std::logic_error("SurfaceControl self-test setup is incomplete");
    const uint64_t refresh = host->ownedVulkan->capabilities().refreshDurationNs;
    if (refresh == 0) throw std::runtime_error("self-test refresh is zero");

    const int outputReadyFd = LSFG_3_1::tryPresentContextSyncFd(
            host->slots[0].context, -1);
    if (outputReadyFd == -2)
        throw std::runtime_error("SurfaceControl self-test LSFG context is busy");
    if (outputReadyFd < -1)
        throw std::runtime_error("SurfaceControl self-test LSFG submission failed");
    int ownedOutputReadyFd = outputReadyFd;
    uint64_t generationCompleteNs = 0;
    const uint64_t generationPollStart = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                    std::chrono::steady_clock::now().time_since_epoch()).count());
    constexpr uint64_t generationTimeoutNs = 1'000'000'000ULL;
    while (ownedOutputReadyFd >= 0 && generationCompleteNs == 0) {
        generationCompleteNs = signaledSyncFenceTimestamp(ownedOutputReadyFd);
        const uint64_t now = static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now().time_since_epoch()).count());
        if (generationCompleteNs == 0 &&
                now - generationPollStart >= generationTimeoutNs) {
            ::close(ownedOutputReadyFd);
            throw std::runtime_error("SurfaceControl self-test LSFG fence timeout");
        }
        if (generationCompleteNs == 0) ::usleep(250);
    }
    if (ownedOutputReadyFd >= 0) ::close(ownedOutputReadyFd);
    if (generationCompleteNs == 0) {
        generationCompleteNs = static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now().time_since_epoch()).count());
    }

    // Setup-only content validation. The live SurfaceControl path never maps
    // a frame; it consumes the LSFG AHB and its acquire fence directly.
    const SetupContentRecord left = readSetupContent(host->slots[0].left);
    const SetupContentRecord right = readSetupContent(host->slots[0].right);
    const SetupContentRecord output = readSetupContent(host->slots[0].output);
    host->selfTestEndpoint = left.checksum != right.checksum;
    host->selfTestGenerated = output.checksum != left.checksum &&
            output.checksum != right.checksum;
    host->selfTestContent = host->selfTestEndpoint && host->selfTestGenerated &&
            output.minimum < output.maximum;

    emufusion::lsfg::OwnedSurfaceControlPresenter presenter(
            host->window, host->width, host->height);
    // A raw CLOCK_MONOTONIC instant is not necessarily on the panel's physical
    // retire-fence phase. SurfaceFlinger may therefore choose the neighboring
    // scan even when two arbitrary desired times are perfectly one refresh
    // apart. Establish one bounded physical fence anchor first, then retain the
    // strict bounded target checks on targets derived from that phase.
    const uint64_t calibrationNow = monotonicNowNs();
    const uint64_t calibrationDesired = alignedFuturePresentTime(
            calibrationNow, refresh, calibrationNow, 4ULL);
    constexpr uint64_t calibrationId = UINT64_MAX;
    presenter.present(host->slots[0].left, -1, calibrationId,
                      calibrationDesired);
    constexpr uint64_t physicalFeedbackTimeoutNs = 3'000'000'000ULL;
    if (calibrationDesired > UINT64_MAX - physicalFeedbackTimeoutNs)
        throw std::overflow_error("SurfaceControl calibration deadline overflow");
    const uint64_t calibrationDeadline =
            calibrationDesired + physicalFeedbackTimeoutNs;
    std::optional<emufusion::lsfg::OwnedSurfaceControlPresenter::Completion>
            calibration;
    while (!calibration.has_value()) {
        calibration = presenter.pollCompletion();
        if (calibration.has_value()) break;
        if (!presenter.takeUnavailablePresentFences().empty())
            throw emufusion::lsfg::PresentFenceUnavailable(
                    "SurfaceControl calibration omitted its present fence");
        if (monotonicNowNs() >= calibrationDeadline)
            throw std::runtime_error(
                    "SurfaceControl physical phase calibration timeout diagnostics=" +
                    presenter.diagnosticJson());
        ::usleep(250);
    }
    const uint64_t calibrationOffset =
            calibration->actualPresentTimeNs >= calibrationDesired ?
            calibration->actualPresentTimeNs - calibrationDesired :
            calibrationDesired - calibration->actualPresentTimeNs;
    if (calibration->presentId != calibrationId ||
            calibrationOffset > refresh * 2ULL)
        throw std::runtime_error(
                "SurfaceControl physical phase calibration rejected");

    const uint64_t phaseProbePhysical = alignedFuturePresentTime(
            calibration->actualPresentTimeNs, refresh, monotonicNowNs(), 12ULL);
    constexpr uint64_t phaseProbeId = UINT64_MAX - 1ULL;
    presenter.present(host->slots[0].left, -1, phaseProbeId,
                      emufusion::lsfg::startupDriverPresentTimeNs(
                              phaseProbePhysical));
    if (phaseProbePhysical > UINT64_MAX - physicalFeedbackTimeoutNs)
        throw std::overflow_error("SurfaceControl phase-probe deadline overflow");
    const uint64_t phaseProbeDeadline =
            phaseProbePhysical + physicalFeedbackTimeoutNs;
    std::optional<emufusion::lsfg::OwnedSurfaceControlPresenter::Completion>
            phaseProbe;
    while (!phaseProbe.has_value()) {
        phaseProbe = presenter.pollCompletion();
        if (phaseProbe.has_value()) break;
        if (!presenter.takeUnavailablePresentFences().empty())
            throw emufusion::lsfg::PresentFenceUnavailable(
                    "SurfaceControl phase probe omitted its present fence");
        if (monotonicNowNs() >= phaseProbeDeadline)
            throw std::runtime_error(
                    "SurfaceControl physical phase probe timeout diagnostics=" +
                    presenter.diagnosticJson());
        ::usleep(250);
    }
    const uint64_t phaseProbeOffset =
            phaseProbe->actualPresentTimeNs >= phaseProbePhysical ?
            phaseProbe->actualPresentTimeNs - phaseProbePhysical :
            phaseProbePhysical - phaseProbe->actualPresentTimeNs;
    if (phaseProbe->presentId != phaseProbeId ||
            phaseProbeOffset > refresh * 2ULL)
        throw std::runtime_error("SurfaceControl physical phase probe rejected");
    host->selfTestPresentFenceOffsetNs =
            phaseProbe->actualPresentTimeNs < phaseProbePhysical ?
            phaseProbePhysical - phaseProbe->actualPresentTimeNs : 0ULL;
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
            "Surface timing setup phaseProbeId=%llu physicalTargetNs=%llu "
            "driverDesiredNs=%llu rawPresentFenceNs=%llu addedOffsetNs=%llu "
            "applyStartNs=%llu applyEndNs=%llu latchNs=%llu refreshNs=%llu",
            static_cast<unsigned long long>(phaseProbe->presentId),
            static_cast<unsigned long long>(phaseProbePhysical),
            static_cast<unsigned long long>(phaseProbe->desiredPresentTimeNs),
            static_cast<unsigned long long>(phaseProbe->rawPresentFenceTimeNs),
            static_cast<unsigned long long>(host->selfTestPresentFenceOffsetNs),
            static_cast<unsigned long long>(phaseProbe->transactionApplyStartNs),
            static_cast<unsigned long long>(phaseProbe->transactionApplyEndNs),
            static_cast<unsigned long long>(phaseProbe->latchTimeNs),
            static_cast<unsigned long long>(refresh));

    const uint64_t firstPhysical = alignedFuturePresentTime(
            phaseProbe->actualPresentTimeNs, refresh, monotonicNowNs(), 12ULL);
    if (firstPhysical > UINT64_MAX - refresh)
        throw std::overflow_error("SurfaceControl self-test timestamp overflow");
    const uint64_t secondPhysical = firstPhysical + refresh;
    const uint64_t firstDriverDesired =
            emufusion::lsfg::startupDriverPresentTimeNs(firstPhysical);
    const uint64_t secondDriverDesired =
            emufusion::lsfg::startupDriverPresentTimeNs(secondPhysical);
    const uint64_t generationDeadline = secondDriverDesired;
    host->selfTestDeadline = generationCompleteNs < generationDeadline;

    presenter.present(host->slots[0].left, -1, 1, firstDriverDesired);
    presenter.present(host->slots[0].output, -1, 2, secondDriverDesired);
    std::array<emufusion::lsfg::OwnedSurfaceControlPresenter::Completion, 2>
            rows{};
    uint32_t completed = 0;
    if (secondPhysical > UINT64_MAX - physicalFeedbackTimeoutNs)
        throw std::overflow_error("SurfaceControl physical timing deadline overflow");
    const uint64_t pollDeadline = secondPhysical + physicalFeedbackTimeoutNs;
    while (completed < rows.size()) {
        auto row = presenter.pollCompletion();
        if (row.has_value()) rows[completed++] = *row;
        if (completed == rows.size()) break;
        if (!presenter.takeUnavailablePresentFences().empty())
            throw emufusion::lsfg::PresentFenceUnavailable(
                    "SurfaceControl self-test omitted its present fence");
        const uint64_t now = static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now().time_since_epoch()).count());
        if (now >= pollDeadline) {
            throw std::runtime_error(
                    "SurfaceControl physical timing timeout diagnostics=" +
                    presenter.diagnosticJson());
        }
        ::usleep(250);
    }
    const uint64_t firstNormalizedActual = normalizedPhysicalPresentTime(
            rows[0].actualPresentTimeNs, host->selfTestPresentFenceOffsetNs);
    const uint64_t secondNormalizedActual = normalizedPhysicalPresentTime(
            rows[1].actualPresentTimeNs, host->selfTestPresentFenceOffsetNs);
    if (secondNormalizedActual <= firstNormalizedActual)
        throw std::runtime_error("SurfaceControl physical timestamp regressed");
    const uint64_t actualInterval =
            secondNormalizedActual - firstNormalizedActual;
    const uint64_t intervalTolerance = std::max<uint64_t>(
            150'000ULL, (refresh + 49ULL) / 50ULL);
    const uint64_t intervalError = actualInterval >= refresh ?
            actualInterval - refresh : refresh - actualInterval;
    const bool firstPhysicalTargetMatched = physicalTargetWithinTolerance(
            firstNormalizedActual, firstPhysical, intervalTolerance,
            refresh * 2ULL);
    const bool secondPhysicalTargetMatched = physicalTargetWithinTolerance(
            secondNormalizedActual, secondPhysical, intervalTolerance,
            refresh * 2ULL);
    host->selfTestPhysicalTiming = rows[0].presentId == 1 &&
            rows[1].presentId == 2 &&
            firstNormalizedActual >= rows[0].latchTimeNs &&
            secondNormalizedActual >= rows[1].latchTimeNs &&
            intervalError <= intervalTolerance &&
            firstPhysicalTargetMatched && secondPhysicalTargetMatched;
    host->selfTestGenerationCompleteNs = generationCompleteNs;
    host->selfTestGenerationDeadlineNs = generationDeadline;
    host->selfTestFirstDesiredNs = firstPhysical;
    host->selfTestFirstLatchNs = rows[0].latchTimeNs;
    host->selfTestFirstActualNs = firstNormalizedActual;
    host->selfTestSecondDesiredNs = secondPhysical;
    host->selfTestSecondLatchNs = rows[1].latchTimeNs;
    host->selfTestSecondActualNs = secondNormalizedActual;
    host->selfTestPhysicalIntervalNs = actualInterval;
    host->selfTestPhysicalAnchorNs = rows[1].actualPresentTimeNs;
    host->selfTestPassed = host->selfTestEndpoint && host->selfTestGenerated &&
            host->selfTestDeadline && host->selfTestPhysicalTiming &&
            host->selfTestContent;
    if (!host->selfTestPassed) {
        throw std::runtime_error(
                "SurfaceControl LSFG self-test evidence rejected"
                " endpoint=" + std::to_string(host->selfTestEndpoint) +
                " generated=" + std::to_string(host->selfTestGenerated) +
                " deadline=" + std::to_string(host->selfTestDeadline) +
                " physical=" + std::to_string(host->selfTestPhysicalTiming) +
                " content=" + std::to_string(host->selfTestContent) +
                " leftChecksum=" + std::to_string(left.checksum) +
                " rightChecksum=" + std::to_string(right.checksum) +
                " outputChecksum=" + std::to_string(output.checksum) +
                " outputMin=" + std::to_string(output.minimum) +
                " outputMax=" + std::to_string(output.maximum) +
                " generationCompleteNs=" + std::to_string(generationCompleteNs) +
                " generationDeadlineNs=" + std::to_string(generationDeadline) +
                " firstDesiredNs=" + std::to_string(firstPhysical) +
                " firstDriverDesiredNs=" + std::to_string(firstDriverDesired) +
                " firstApplyStartNs=" + std::to_string(rows[0].transactionApplyStartNs) +
                " firstApplyEndNs=" + std::to_string(rows[0].transactionApplyEndNs) +
                " firstLatchNs=" + std::to_string(rows[0].latchTimeNs) +
                " firstRawFenceNs=" + std::to_string(rows[0].actualPresentTimeNs) +
                " firstActualNs=" + std::to_string(firstNormalizedActual) +
                " secondDesiredNs=" + std::to_string(secondPhysical) +
                " secondDriverDesiredNs=" + std::to_string(secondDriverDesired) +
                " secondApplyStartNs=" + std::to_string(rows[1].transactionApplyStartNs) +
                " secondApplyEndNs=" + std::to_string(rows[1].transactionApplyEndNs) +
                " secondLatchNs=" + std::to_string(rows[1].latchTimeNs) +
                " secondRawFenceNs=" + std::to_string(rows[1].actualPresentTimeNs) +
                " secondActualNs=" + std::to_string(secondNormalizedActual) +
                " presentFenceOffsetNs=" +
                        std::to_string(host->selfTestPresentFenceOffsetNs) +
                " intervalNs=" + std::to_string(actualInterval) +
                " intervalErrorNs=" + std::to_string(intervalError) +
                " intervalToleranceNs=" + std::to_string(intervalTolerance));
    }
}

void runBoundedLiveSurfaceControlSelfTest(Host* host) {
    if (host == nullptr || host->ownedVulkan == nullptr ||
            host->surfacePresenter == nullptr ||
            !host->contextsPrewarmed)
        throw std::logic_error("live SurfaceControl self-test is unavailable");
    std::unique_ptr<AHardwareBuffer, AhbRelease> left(
            allocateBuffer(host->width, host->height));
    std::unique_ptr<AHardwareBuffer, AhbRelease> right(
            allocateBuffer(host->width, host->height));
    fillSetupPattern(left.get(), 32U);
    fillSetupPattern(right.get(), 44U);
    constexpr uint64_t epoch = 2;
    constexpr uint64_t endpointId = UINT32_MAX - 1ULL;
    constexpr uint64_t generatedId = UINT32_MAX;
    host->ownedVulkan->resetTimeline(epoch);
    const uint64_t refresh =
            host->ownedVulkan->capabilities().refreshDurationNs;
    if (host->selfTestPhysicalAnchorNs == 0)
        throw std::logic_error("live self-test physical phase is unavailable");
    const uint64_t now = monotonicNowNs();
    constexpr uint64_t driverLeadNs = 2'000'000ULL;
    const uint64_t firstPhysical = alignedFuturePresentTime(
            host->selfTestPhysicalAnchorNs, refresh, now, 12ULL);
    if (firstPhysical > UINT64_MAX - refresh)
        throw std::overflow_error("live self-test timestamp overflow");
    const uint64_t secondPhysical = firstPhysical + refresh;
    if (firstPhysical <= driverLeadNs)
        throw std::overflow_error("live self-test timestamp overflow");
    const emufusion::lsfg::OwnedVulkanHost::LiveRequest endpointRequest{
        .left = left.get(),
        .right = right.get(),
        .presentId = endpointId,
        .physicalPresentTimeNs = firstPhysical,
        .desiredPresentTimeNs = firstPhysical - driverLeadNs,
        .completionDeadlineNs = firstPhysical - driverLeadNs,
        .refreshDurationNs = refresh,
        .generated = false,
        .presentRight = false,
    };
    auto endpoint = host->ownedVulkan->tryPrepare(endpointRequest);
    if (!endpoint.has_value())
        throw std::runtime_error("live self-test endpoint slot unavailable");
    host->ownedVulkan->presentPrepared(
            *endpoint, endpoint->inputReadySyncFd);

    const emufusion::lsfg::OwnedVulkanHost::LiveRequest generatedRequest{
        .left = left.get(),
        .right = right.get(),
        .presentId = generatedId,
        .physicalPresentTimeNs = secondPhysical,
        .desiredPresentTimeNs = secondPhysical - driverLeadNs,
        .completionDeadlineNs = secondPhysical - driverLeadNs,
        .refreshDurationNs = refresh,
        .generated = true,
        .presentRight = false,
    };
    auto generated = host->ownedVulkan->tryPrepare(generatedRequest);
    if (!generated.has_value())
        throw std::runtime_error("live self-test generated slot unavailable");
    int outputReadyFd = LSFG_3_1::tryPresentContextSyncFd(
            host->slots[generated->slotIndex].context,
            generated->inputReadySyncFd);
    if (outputReadyFd == -2) {
        host->ownedVulkan->abandonPrepared(*generated);
        throw std::runtime_error("live self-test LSFG context is busy");
    }
    if (outputReadyFd < -1)
        throw std::runtime_error("live self-test LSFG output fence failed");
    host->ownedVulkan->presentPrepared(*generated, outputReadyFd);

    std::array<emufusion::lsfg::OwnedVulkanHost::Completion, 2> rows{};
    uint32_t completed = 0;
    constexpr uint64_t feedbackTimeoutNs = 3'000'000'000ULL;
    const uint64_t deadline = secondPhysical + feedbackTimeoutNs;
    while (completed < rows.size()) {
        auto row = progressLiveSurfacePipeline(host, "startup-live-pair");
        if (row.has_value()) rows[completed++] = *row;
        if (completed == rows.size()) break;
        const uint64_t pollNow = static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now().time_since_epoch()).count());
        if (pollNow >= deadline)
            throw std::runtime_error(
                    "live SurfaceControl self-test timeout diagnostics=" +
                    host->ownedVulkan->diagnosticJson() + "/" +
                    host->surfacePresenter->diagnosticJson());
        ::usleep(250);
    }
    // The second compositor callback owns the first buffer's release fence.
    // Drain that release nonblockingly within the same setup-only bound. The
    // newest buffer intentionally remains owned until the first live replace.
    while (host->deliveredAwaitingRelease.count(endpointId) != 0) {
        (void) progressLiveSurfacePipeline(host, "startup-live-pair-release");
        const uint64_t pollNow = static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now().time_since_epoch()).count());
        if (pollNow >= deadline)
            throw std::runtime_error(
                    "live SurfaceControl release self-test timeout");
        ::usleep(250);
    }
    const uint64_t liveTargetToleranceNs = std::max<uint64_t>(
            150'000ULL, (refresh + 49ULL) / 50ULL);
    const bool endpointPhysicalTargetMatched = physicalTargetWithinTolerance(
            rows[0].actualPresentTimeNs, firstPhysical,
            liveTargetToleranceNs, refresh * 2ULL);
    const bool generatedPhysicalTargetMatched = physicalTargetWithinTolerance(
            rows[1].actualPresentTimeNs, secondPhysical,
            liveTargetToleranceNs, refresh * 2ULL);
    host->selfTestLiveSurfaceControl =
            rows[0].presentId == endpointId &&
            rows[1].presentId == generatedId &&
            rows[0].outputChecksum == rows[0].leftChecksum &&
            rows[1].outputChecksum != rows[1].leftChecksum &&
            rows[1].outputChecksum != rows[1].rightChecksum &&
            endpointPhysicalTargetMatched &&
            generatedPhysicalTargetMatched &&
            rows[0].gpuWorkNs > 0 && rows[1].gpuWorkNs > 0 &&
            rows[0].pairStatus == 1 && rows[1].pairStatus == 1;
    if (host->selfTestLiveSurfaceControl) {
        if (rows[1].actualPresentTimeNs < host->selfTestPresentFenceOffsetNs)
            throw std::runtime_error("live physical anchor underflow");
        host->selfTestPhysicalAnchorNs =
                rows[1].actualPresentTimeNs -
                host->selfTestPresentFenceOffsetNs;
    }
    if (!host->selfTestLiveSurfaceControl)
        throw std::runtime_error(
                "integrated live SurfaceControl self-test rejected"
                " firstId=" + std::to_string(rows[0].presentId) +
                " expectedFirstId=" + std::to_string(endpointId) +
                " secondId=" + std::to_string(rows[1].presentId) +
                " expectedSecondId=" + std::to_string(generatedId) +
                " firstOutput=" + std::to_string(rows[0].outputChecksum) +
                " firstLeft=" + std::to_string(rows[0].leftChecksum) +
                " secondOutput=" + std::to_string(rows[1].outputChecksum) +
                " secondLeft=" + std::to_string(rows[1].leftChecksum) +
                " secondRight=" + std::to_string(rows[1].rightChecksum) +
                " firstActual=" + std::to_string(rows[0].actualPresentTimeNs) +
                " firstDesired=" + std::to_string(firstPhysical) +
                " secondActual=" + std::to_string(rows[1].actualPresentTimeNs) +
                " secondDesired=" + std::to_string(secondPhysical) +
                " firstGpu=" + std::to_string(rows[0].gpuWorkNs) +
                " secondGpu=" + std::to_string(rows[1].gpuWorkNs) +
                " firstPair=" + std::to_string(rows[0].pairStatus) +
                " secondPair=" + std::to_string(rows[1].pairStatus));
}

void runBoundedLiveCadenceSoak(Host* host) {
    if (host == nullptr || host->ownedVulkan == nullptr ||
            host->surfacePresenter == nullptr ||
            !host->selfTestLiveSurfaceControl)
        throw std::logic_error("live cadence soak setup is incomplete");
    constexpr uint32_t presentationCount = 240;
    constexpr uint32_t endpointCount = presentationCount / 2U + 1U;
    constexpr uint64_t firstPresentId = 1'000'000ULL;
    constexpr uint64_t epoch = 3ULL;
    constexpr uint64_t driverLeadNs = 2'000'000ULL;
    std::vector<std::unique_ptr<AHardwareBuffer, AhbRelease>> endpoints;
    endpoints.reserve(endpointCount);
    for (uint32_t index = 0; index < endpointCount; ++index) {
        endpoints.emplace_back(allocateBuffer(host->width, host->height));
        fillSoakPattern(endpoints.back().get(), index);
    }
    host->ownedVulkan->resetTimeline(epoch);
    const uint64_t refresh =
            host->ownedVulkan->capabilities().refreshDurationNs;
    if (host->selfTestPhysicalAnchorNs == 0)
        throw std::logic_error("live cadence physical phase is unavailable");
    const uint64_t startNs = monotonicNowNs();
    const uint64_t firstPhysical = alignedFuturePresentTime(
            host->selfTestPhysicalAnchorNs, refresh, startNs, 12ULL);
    const uint64_t lastPhysical = firstPhysical +
            refresh * static_cast<uint64_t>(presentationCount - 1U);
    constexpr uint64_t feedbackTimeoutNs = 3'000'000'000ULL;
    if (lastPhysical > UINT64_MAX - feedbackTimeoutNs)
        throw std::overflow_error("live cadence soak deadline overflow");
    const uint64_t soakDeadline = lastPhysical + feedbackTimeoutNs;
    uint32_t nextSubmit = 0;
    uint32_t completed = 0;
    uint64_t priorActualNs = 0;
    uint64_t minIntervalNs = UINT64_MAX;
    uint64_t maxIntervalNs = 0;
    uint64_t maxErrorNs = 0;
    while (completed < presentationCount) {
        if (nextSubmit < presentationCount) {
            const uint32_t pairIndex = nextSubmit / 2U;
            const bool generated = (nextSubmit & 1U) != 0U;
            const uint64_t physical = firstPhysical +
                    refresh * static_cast<uint64_t>(nextSubmit);
            const uint64_t presentId = firstPresentId + nextSubmit;
            const emufusion::lsfg::OwnedVulkanHost::LiveRequest request{
                .left = endpoints[pairIndex].get(),
                .right = endpoints[pairIndex + 1U].get(),
                .presentId = presentId,
                .physicalPresentTimeNs = physical,
                .desiredPresentTimeNs = physical - driverLeadNs,
                .completionDeadlineNs = physical - driverLeadNs,
                .refreshDurationNs = refresh,
                .generated = generated,
                .presentRight = false,
            };
            auto prepared = host->ownedVulkan->tryPrepare(request);
            if (prepared.has_value()) {
                int readyFd = prepared->inputReadySyncFd;
                if (generated) {
                    readyFd = LSFG_3_1::tryPresentContextSyncFd(
                            host->slots[prepared->slotIndex].context, readyFd);
                    if (readyFd == -2) {
                        host->ownedVulkan->abandonPrepared(*prepared);
                    } else {
                        if (readyFd < -1)
                            throw std::runtime_error(
                                    "live cadence LSFG output fence failed");
                        host->ownedVulkan->presentPrepared(*prepared, readyFd);
                        ++nextSubmit;
                    }
                } else {
                    host->ownedVulkan->presentPrepared(*prepared, readyFd);
                    ++nextSubmit;
                }
            }
        }
        auto row = progressLiveSurfacePipeline(host, "startup-live-cadence");
        if (row.has_value()) {
            const uint64_t expectedId = firstPresentId + completed;
            const bool generated = (completed & 1U) != 0U;
            if (row->presentId != expectedId || row->pairStatus != 1U ||
                    row->gpuWorkNs == 0 ||
                    (generated &&
                            (row->outputChecksum == row->leftChecksum ||
                             row->outputChecksum == row->rightChecksum)) ||
                    (!generated &&
                            row->outputChecksum != row->leftChecksum))
                throw std::runtime_error(
                        "live cadence content/identity row rejected");
            if (priorActualNs != 0) {
                if (row->actualPresentTimeNs <= priorActualNs)
                    throw std::runtime_error(
                            "live cadence physical timestamp regressed");
                const uint64_t interval =
                        row->actualPresentTimeNs - priorActualNs;
                const uint64_t error = interval >= refresh ?
                        interval - refresh : refresh - interval;
                minIntervalNs = std::min(minIntervalNs, interval);
                maxIntervalNs = std::max(maxIntervalNs, interval);
                maxErrorNs = std::max(maxErrorNs, error);
            }
            priorActualNs = row->actualPresentTimeNs;
            ++completed;
        }
        const uint64_t pollNow = static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now().time_since_epoch()).count());
        if (pollNow >= soakDeadline)
            throw std::runtime_error(
                    "live cadence soak timeout completed=" +
                    std::to_string(completed) + " submitted=" +
                    std::to_string(nextSubmit) + " diagnostics=" +
                    host->ownedVulkan->diagnosticJson() + "/" +
                    host->surfacePresenter->diagnosticJson());
        if (!row.has_value()) ::usleep(100);
    }
    const uint64_t latestId = firstPresentId + presentationCount - 1ULL;
    while (host->deliveredAwaitingRelease.size() > 1U ||
            host->deliveredAwaitingRelease.count(latestId) == 0U) {
        (void) progressLiveSurfacePipeline(host, "startup-live-cadence-release");
        const uint64_t pollNow = static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now().time_since_epoch()).count());
        if (pollNow >= soakDeadline)
            throw std::runtime_error("live cadence release drain timeout");
        ::usleep(100);
    }
    const uint64_t tolerance = std::max<uint64_t>(
            150'000ULL, (refresh + 49ULL) / 50ULL);
    host->selfTestLiveCadencePresents = completed;
    host->selfTestLiveCadenceGenerated = presentationCount / 2U;
    host->selfTestLiveCadenceMinIntervalNs = minIntervalNs;
    host->selfTestLiveCadenceMaxIntervalNs = maxIntervalNs;
    host->selfTestLiveCadenceMaxErrorNs = maxErrorNs;
    host->selfTestLiveCadence = completed == presentationCount &&
            minIntervalNs > 0 && maxIntervalNs >= minIntervalNs &&
            maxErrorNs <= tolerance;
    if (!host->selfTestLiveCadence)
        throw std::runtime_error("live cadence interval histogram rejected");
}

}  // namespace

#if EMUFUSION_LSFG_PIXEL_PROBE
// Separate-process diagnostic only. A caller-owned ImageReader supplies WSI,
// never a visible display. CPU transfers are outside the generation measurement.
extern "C" JNIEXPORT jlong JNICALL
Java_com_thorium_preview_game_LsfgPixelProbe_generate(
        JNIEnv* env, jclass, jobject surface, jstring shaderPath,
        jstring leftPath, jstring rightPath, jstring outputPath,
        jint width, jint height, jstring previousPath) {
    Host host;
    int copyProofFd = -1;
    try {
        if (!surface || width < 1 || height < 1 || width > 1920 || height > 1080)
            throw std::invalid_argument("invalid pixel probe geometry");
        const auto directory = jstringValue(env, shaderPath);
        const auto output = jstringValue(env, outputPath);
        const size_t rowBytes = static_cast<size_t>(width) * 4;
        const size_t bytes = rowBytes * height;
        auto load = [&](jstring path) {
            std::ifstream file(jstringValue(env, path), std::ios::binary | std::ios::ate);
            if (!file || file.tellg() != static_cast<std::streamoff>(bytes))
                throw std::runtime_error("endpoint byte count mismatch");
            std::vector<char> data(bytes);
            file.seekg(0);
            if (!file.read(data.data(), bytes)) throw std::runtime_error("endpoint read failed");
            return data;
        };
        const auto left = load(leftPath), right = load(rightPath);
        const auto previous = previousPath ? load(previousPath) : left;
        host.window = ANativeWindow_fromSurface(env, surface);
        host.width = width; host.height = height;
        host.ownedVulkan = std::make_unique<emufusion::lsfg::OwnedVulkanHost>();
        host.ownedVulkan->open(host.window, width, height);
        std::array<emufusion::lsfg::OwnedVulkanHost::FixedBuffers, kSlotCount> fixed{};
        for (size_t i = 0; i < kSlotCount; ++i) {
            auto& slot = host.slots[i];
            slot.left = allocateBuffer(width, height);
            slot.right = allocateBuffer(width, height);
            slot.output = allocateBuffer(width, height);
            fixed[i] = {slot.left, slot.right, slot.output};
        }
        host.ownedVulkan->importAndPrepareFixedBuffers(fixed);
        auto wait = [](int fd) {
            if (fd == -1) return; // Successful already-signaled SYNC_FD export.
            if (fd < 0) throw std::runtime_error("missing completion fence");
            pollfd descriptor{fd, POLLIN, 0};
            const int result = ::poll(&descriptor, 1, 1000);
            ::close(fd);
            if (!emufusion::lsfg::successfulSyncPoll(result, descriptor.revents))
                throw std::runtime_error("pixel probe completion failed");
        };
        auto upload = [&](AHardwareBuffer* buffer, const std::vector<char>& data) {
            AHardwareBuffer_Desc desc{}; AHardwareBuffer_describe(buffer, &desc);
            void* mapped = nullptr;
            if (AHardwareBuffer_lock(buffer, AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN,
                    -1, nullptr, &mapped) != 0 || !mapped)
                throw std::runtime_error("endpoint lock failed");
            for (int y = 0; y < height; ++y)
                std::memcpy(static_cast<char*>(mapped) + size_t(y) * desc.stride * 4,
                            data.data() + size_t(y) * rowBytes, rowBytes);
            int fd = -1;
            if (AHardwareBuffer_unlock(buffer, &fd) != 0)
                throw std::runtime_error("endpoint unlock failed");
            if (fd >= 0) wait(fd);
        };
        host.ownedVulkan->resetTimeline(1);
        if (std::getenv("EMUFUSION_LSFG_LIVE_PAIR_PROBE")) {
            upload(host.slots[2].left, previous);
            upload(host.slots[2].right, left);
            auto occupied = host.ownedVulkan->tryPreparePrivateEndpointPair(
                    host.slots[2].left, host.slots[2].right);
            if (!occupied || occupied->slotIndex != 0)
                throw std::runtime_error("occupied-slot probe setup failed");
            host.ownedVulkan->holdPrivatePrepared(*occupied, occupied->inputReadySyncFd);
            host.inferenceSlotIndex = host.ownedVulkan->reserveIdleInferenceSlot();
            if (host.inferenceSlotIndex == 0)
                throw std::runtime_error("inference selected occupied startup buffer");
            __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                    "LSFG_IDLE_SLOT_PROBE occupied=0 inference=%u", host.inferenceSlotIndex);
        } else {
            host.inferenceSlotIndex = host.ownedVulkan->reserveIdleInferenceSlot();
        }
        auto& slot = host.slots[host.inferenceSlotIndex];
        // The backend is temporal: one alternating input is encoded per call,
        // and Beta consumes a three-feature ring. Seed all history explicitly
        // with the left endpoint; never judge the uninitialized first output.
        upload(slot.left, previous); upload(slot.right, previous);
        LSFG_3_1::initialize(host.ownedVulkan->capabilities().deviceKey,
                false, 1.0F, 1, [directory](const std::string& name) {
                    return readShader(directory, name);
                });
        host.initialized = true;
        slot.context = LSFG_3_1::createContextFromAHB(slot.left, slot.right,
                std::vector<AHardwareBuffer*>{slot.output},
                VkExtent2D{uint32_t(width), uint32_t(height)}, VK_FORMAT_R8G8B8A8_UNORM);
        emufusion::lsfg::ContinuousInference inference(*host.ownedVulkan,
                slot.context, slot.output);
        // Exercise the same GPU-only input transport required by gameplay,
        // not direct CPU writes into LSFG's alternating scratch buffers.
        using ProbeBuffer = std::unique_ptr<AHardwareBuffer, decltype(&AHardwareBuffer_release)>;
        ProbeBuffer sourcePrevious(allocateBuffer(width, height), &AHardwareBuffer_release);
        ProbeBuffer sourceNext(allocateBuffer(width, height), &AHardwareBuffer_release);
        host.ownedVulkan->prepareSourceImage(sourcePrevious.get());
        host.ownedVulkan->prepareSourceImage(sourceNext.get());
        std::vector<char> precedingPixels = previous;
        uint64_t diagnosticSequence = 0;
        auto encode = [&](const std::vector<char>& pixels) {
            const uint64_t sequence = ++diagnosticSequence;
                upload(sourcePrevious.get(), precedingPixels);
                upload(sourceNext.get(), pixels);
                const auto start = std::chrono::steady_clock::now();
                using CI = emufusion::lsfg::ContinuousInference;
                // Probe ordinals are synthetic, never guest timing evidence.
                if (inference.submit(sourcePrevious.get(), sourceNext.get(),
                        {1, 1, sequence, sequence * 33333333ULL}) != CI::Submission::Submitted)
                    throw std::runtime_error("continuous diagnostic submission failed");
                while (inference.poll() != CI::Completion::Ready) {
                    if (std::chrono::steady_clock::now() - start > std::chrono::seconds(1))
                        throw std::runtime_error("continuous diagnostic completion timeout");
                    // Test harness only: gameplay calls poll once and returns.
                    ::usleep(1000);
                }
                const int readyFd = inference.completedFence();
                if (copyProofFd >= 0) ::close(copyProofFd);
                copyProofFd = readyFd >= 0 ? ::dup(readyFd) : -1;
                if (readyFd < -1 || (readyFd >= 0 && copyProofFd < 0))
                    throw std::runtime_error("completion fence duplication failed");
                const auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now() - start).count();
                precedingPixels = pixels;
                return duration;
        };
        for (int seed = 0; seed < 3; ++seed) encode(previous);
        if (previousPath) encode(left);
        const auto elapsed = encode(right);
        if (!inference.historyReady())
            throw std::runtime_error("output lacks completed temporal history");
        auto copied = host.ownedVulkan->tryCopyCompletedGenerated(
                slot.left, slot.right, slot.output, copyProofFd);
        if (!copied) throw std::runtime_error("generated copy was not accepted");
        if (copied->slotIndex == host.inferenceSlotIndex)
            throw std::runtime_error("generated copy aliases inference storage");
        wait(copied->inputReadySyncFd);
        if (host.ownedVulkan->referencesSourceImage(slot.output))
            throw std::runtime_error("generated source lease remains after copy completion");
        AHardwareBuffer* copiedOutput = host.slots[copied->slotIndex].output;
        if (previous != right) {
            const uint64_t retainedChecksum = readSetupContent(copiedOutput).checksum;
            // Continue inference after the copy's source lease retires. Its
            // scratch output must change without touching the retained frame.
            encode(previous);
            if (readSetupContent(slot.output).checksum == retainedChecksum)
                throw std::runtime_error("overwrite control did not change inference output");
            if (readSetupContent(copiedOutput).checksum != retainedChecksum)
                throw std::runtime_error("inference reuse corrupted retained output");
            __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                "LSFG_PIXEL_PROBE_RETAINED_OUTPUT_UNCHANGED_AFTER_INFERENCE_REUSE");
        }
        if (std::getenv("EMUFUSION_LSFG_LIVE_PAIR_PROBE")) {
            // Exercise the actual live pair state machine with a fresh context
            // and three genuine chronological inputs, not seeded duplicates.
            host.ownedVulkan->abandonPrepared({copied->slotIndex, -1});
            LSFG_3_1::deleteContext(slot.context);
            slot.context = LSFG_3_1::createContextFromAHB(slot.left, slot.right,
                    std::vector<AHardwareBuffer*>{slot.output},
                    VkExtent2D{uint32_t(width), uint32_t(height)}, VK_FORMAT_R8G8B8A8_UNORM);
            host.continuous = std::make_unique<emufusion::lsfg::ContinuousInference>(
                    *host.ownedVulkan, slot.context, slot.output);
            auto startPair = [&](uint64_t sequence, bool first) {
                PreparedGenerated identity{
                    .left = sourcePrevious.get(), .right = sourceNext.get(),
                    .sessionEpoch = 1, .presentationEpoch = 1,
                    .leftSequence = sequence, .leftTimestampNs = sequence * 100,
                    .rightSequence = sequence + 1, .rightTimestampNs = (sequence + 1) * 100,
                    .presentationTimestampNs = sequence * 100 + 50,
                };
                host.continuousPair = ContinuousPair{.identity = identity, .needsLeft = first};
            };
            auto advance = [&]() {
                const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(1);
                int status = 1;
                while (host.continuousPair && status == 1) {
                    status = progressContinuousPair(&host);
                    if (std::chrono::steady_clock::now() > deadline)
                        throw std::runtime_error("live pair progression timed out");
                    if (host.continuousPair && status == 1) ::usleep(1000);
                }
                return status;
            };
            upload(sourcePrevious.get(), previous);
            upload(sourceNext.get(), left);
            startPair(1, true);
            if (advance() != 3 || host.preparedGenerated || host.continuous->historyReady())
                throw std::runtime_error("live startup output was not withheld");
            discardContinuousPair(&host);
            if (host.continuousPair) throw std::runtime_error("completed warmup did not retire");
            upload(sourcePrevious.get(), left);
            upload(sourceNext.get(), right);
            startPair(2, false);
            advance();
            if (!host.preparedGenerated || !host.continuous->historyReady())
                throw std::runtime_error("third real input did not produce private output");
            const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(1);
            uint32_t status;
            while ((status = host.ownedVulkan->privatePreparedPairStatus(
                    host.preparedGenerated->prepared)) == 0) {
                if (std::chrono::steady_clock::now() > deadline)
                    throw std::runtime_error("live copied output proof timed out");
                ::usleep(1000);
            }
            copiedOutput = host.slots[host.preparedGenerated->prepared.slotIndex].output;
            __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                    "LSFG_LIVE_PAIR_PROBE startupWithheld=true realInputs=3 pairStatus=%u", status);
            // Keep the completed display copy, cancel the next inference before
            // its readiness poll, then verify history and output ownership.
            const auto retainedChecksum = readSetupContent(copiedOutput).checksum;
            upload(sourcePrevious.get(), right);
            upload(sourceNext.get(), previous);
            startPair(3, false);
            if (progressContinuousPair(&host) != 1 || !host.continuousPair->inFlight)
                throw std::runtime_error("cancellation probe did not submit inference");
            discardContinuousPair(&host);
            advance();
            if (host.continuousPair || !host.continuous->lastCompleted() ||
                    host.continuous->lastCompleted()->sequence != 4)
                throw std::runtime_error("canceled inference failed to retire history");
            if (readSetupContent(copiedOutput).checksum != retainedChecksum ||
                    !host.preparedGenerated || host.preparedGenerated->rightSequence != 3)
                throw std::runtime_error("canceled inference changed retained output");
            if (host.ownedVulkan->referencesSourceImage(sourcePrevious.get()) ||
                    host.ownedVulkan->referencesSourceImage(sourceNext.get()))
                throw std::runtime_error("canceled inference retained source carriers");
            __android_log_print(ANDROID_LOG_INFO, LOG_TAG,
                    "LSFG_LIVE_PAIR_CANCEL_PROBE retired=true retainedOutputUnchanged=true");
        }
        AHardwareBuffer_Desc desc{}; AHardwareBuffer_describe(copiedOutput, &desc);
        void* mapped = nullptr;
        if (AHardwareBuffer_lock(copiedOutput, AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN,
                -1, nullptr, &mapped) != 0 || !mapped)
            throw std::runtime_error("output lock failed");
        std::vector<char> pixels(bytes);
        for (int y = 0; y < height; ++y)
            std::memcpy(pixels.data() + size_t(y) * rowBytes,
                        static_cast<char*>(mapped) + size_t(y) * desc.stride * 4, rowBytes);
        if (AHardwareBuffer_unlock(copiedOutput, nullptr) != 0)
            throw std::runtime_error("output unlock failed");
        const int fd = ::open(output.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
        if (fd < 0) throw std::runtime_error("output already exists or cannot be created");
        const auto written = ::write(fd, pixels.data(), pixels.size());
        ::close(fd);
        if (written != static_cast<ssize_t>(pixels.size()))
            throw std::runtime_error("short pixel output write");
        ::close(copyProofFd); copyProofFd = -1;
        destroyHost(&host);
        return elapsed;
    } catch (const std::exception& error) {
        if (copyProofFd >= 0) ::close(copyProofFd);
        destroyHost(&host);
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"), error.what());
        return -1;
    }
}
#endif

extern "C" JNIEXPORT jstring JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_libraryBuildId(
        JNIEnv* env, jclass) {
    return env->NewStringUTF("emufusion-lsfg-live-surface-control-v8-" LUCENT_LSFG_WRAPPER_COMMIT);
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_open(
        JNIEnv* env, jclass, jobject surface, jstring shaderDirectory,
        jint width, jint height) {
    try {
        if (surface == nullptr || width < 1 || height < 1)
            throw std::invalid_argument("invalid LSFG output surface/geometry");
        std::lock_guard<std::mutex> libraryLock(g_libraryMutex);
        if (g_libraryOwner != nullptr)
            throw std::runtime_error("only one LSFG qualification host is allowed");
        std::unique_ptr<Host, void(*)(Host*)> host(new Host(), [](Host* value) {
            destroyHost(value);
            delete value;
        });
        host->window = ANativeWindow_fromSurface(env, surface);
        if (host->window == nullptr) throw std::runtime_error("ANativeWindow unavailable");
        host->width = static_cast<uint32_t>(width);
        host->height = static_cast<uint32_t>(height);
        const std::string directory = jstringValue(env, shaderDirectory);
        for (uint32_t index = 0; index < kSlotCount; ++index) {
            Slot& slot = host->slots[index];
            slot.left = allocateBuffer(host->width, host->height);
            slot.right = allocateBuffer(host->width, host->height);
            slot.output = allocateBuffer(host->width, host->height);
        }
        host->ownedVulkan =
                std::make_unique<emufusion::lsfg::OwnedVulkanHost>();
        host->ownedVulkan->open(host->window, host->width, host->height);
        std::array<emufusion::lsfg::OwnedVulkanHost::FixedBuffers,
                   kSlotCount> fixedBuffers{};
        for (uint32_t index = 0; index < kSlotCount; ++index) {
            fixedBuffers[index] = {
                host->slots[index].left,
                host->slots[index].right,
                host->slots[index].output,
            };
        }
        host->ownedVulkan->importAndPrepareFixedBuffers(fixedBuffers);
        // Populate setup endpoints only after the owned Vulkan device has
        // established GENERAL/external ownership. An UNDEFINED transition
        // after CPU writes would legally discard the prewarm pattern.
        for (uint32_t index = 0; index < kSlotCount; ++index) {
            fillSetupPattern(host->slots[index].left,
                             static_cast<uint8_t>(16U + index));
            fillSetupPattern(host->slots[index].right,
                             static_cast<uint8_t>(80U + index));
        }
        const uint64_t deviceKey =
                host->ownedVulkan->capabilities().deviceKey;
        LSFG_3_1::initialize(deviceKey, false, 1.0F, kGenerationCount,
                [directory](const std::string& name) {
                    return readShader(directory, name);
                });
        host->initialized = true;
        const VkExtent2D extent{host->width, host->height};
        for (uint32_t index = 0; index < kSlotCount; ++index) {
            Slot& slot = host->slots[index];
            std::vector<AHardwareBuffer*> outputs{slot.output};
            slot.context = LSFG_3_1::createContextFromAHB(
                    slot.left, slot.right, outputs, extent,
                    VK_FORMAT_R8G8B8A8_UNORM);
            const int readyFd = LSFG_3_1::tryPresentContextSyncFd(slot.context, -1);
            if (readyFd == -2) throw std::runtime_error("cold LSFG context reported busy");
            if (readyFd < -1) throw std::runtime_error("LSFG prewarm submission failed");
            if (readyFd >= 0) {
                pollfd descriptor{readyFd, POLLIN, 0};
                const int result = ::poll(&descriptor, 1, kSetupFenceTimeoutMs);
                ::close(readyFd);
                if (result != 1 ||
                        !emufusion::lsfg::successfulSyncPoll(result, descriptor.revents))
                    throw std::runtime_error("LSFG prewarm timeout");
            }
        }
        host->contextsPrewarmed = true;
        // A completed SurfaceControl transaction may legally omit its present
        // fence. That row cannot prove physical delivery, so never accept it.
        // Thor normally supplies the fence; allow one fresh child-surface retry
        // to distinguish a transient startup callback from unsupported timing.
        constexpr uint32_t kSurfaceControlSelfTestAttempts = 2U;
        for (uint32_t attempt = 0; attempt < kSurfaceControlSelfTestAttempts;
                ++attempt) {
            try {
                runBoundedSurfaceControlSelfTest(host.get());
                break;
            } catch (const emufusion::lsfg::PresentFenceUnavailable&) {
                if (attempt + 1U == kSurfaceControlSelfTestAttempts) throw;
            }
        }
        host->surfacePresenter = std::make_unique<
                emufusion::lsfg::OwnedSurfaceControlPresenter>(
                host->window, host->width, host->height);
        runBoundedLiveSurfaceControlSelfTest(host.get());
        runBoundedLiveCadenceSoak(host.get());
        // Startup probes deliberately use synthetic inputs. Never carry that
        // history into gameplay or rotate it with presentation storage.
        host->inferenceSlotIndex = host->ownedVulkan->reserveIdleInferenceSlot();
        for (auto& slot : host->slots) {
            LSFG_3_1::deleteContext(slot.context);
            slot.context = -1;
        }
        auto& inferenceSlot = host->slots[host->inferenceSlotIndex];
        inferenceSlot.context = LSFG_3_1::createContextFromAHB(
                inferenceSlot.left, inferenceSlot.right,
                std::vector<AHardwareBuffer*>{inferenceSlot.output},
                extent, VK_FORMAT_R8G8B8A8_UNORM);
        host->continuous = std::make_unique<emufusion::lsfg::ContinuousInference>(
                *host->ownedVulkan, inferenceSlot.context, inferenceSlot.output);
        // The bounded startup proofs intentionally exercise the presenter's
        // legacy untimed contract. Arm strict AChoreographer token ownership
        // only after those proofs and before any live transport request.
        host->surfacePresenter->enableNativeFrameTimelineSource();
        g_libraryOwner = host.get();
        return static_cast<jlong>(reinterpret_cast<uintptr_t>(host.release()));
    } catch (const std::exception& error) {
        LOGE("open failed: %s", error.what());
        return 0;
    }
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_capabilities(
        JNIEnv* env, jclass, jlong handle) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (!host->contextsPrewarmed || host->ownedVulkan == nullptr)
            return env->NewStringUTF(
                    "{\"selfTestPassed\":false,\"contextsPrewarmed\":false}");
        const auto& owned = host->ownedVulkan->capabilities();
        std::string record =
            "{\"selfTestPassed\":" +
                    std::string(host->selfTestPassed ? "true" : "false") +
            ",\"selfTestEndpoint\":" +
                    (host->selfTestEndpoint ? "true" : "false") +
            ",\"selfTestGenerated\":" +
                    (host->selfTestGenerated ? "true" : "false") +
            ",\"selfTestDeadline\":" +
                    (host->selfTestDeadline ? "true" : "false") +
            ",\"selfTestPhysicalTiming\":" +
                    (host->selfTestPhysicalTiming ? "true" : "false") +
            ",\"selfTestContent\":" +
                    (host->selfTestContent ? "true" : "false") +
            ",\"selfTestLiveSurfaceControl\":" +
                    (host->selfTestLiveSurfaceControl ? "true" : "false") +
            ",\"selfTestLiveCadence\":" +
                    (host->selfTestLiveCadence ? "true" : "false") +
            ",\"selfTestLiveCadencePresents\":" +
                    std::to_string(host->selfTestLiveCadencePresents) +
            ",\"selfTestLiveCadenceGenerated\":" +
                    std::to_string(host->selfTestLiveCadenceGenerated) +
            ",\"selfTestLiveCadenceMinIntervalNs\":" +
                    std::to_string(host->selfTestLiveCadenceMinIntervalNs) +
            ",\"selfTestLiveCadenceMaxIntervalNs\":" +
                    std::to_string(host->selfTestLiveCadenceMaxIntervalNs) +
            ",\"selfTestLiveCadenceMaxErrorNs\":" +
                    std::to_string(host->selfTestLiveCadenceMaxErrorNs) +
            ",\"selfTestGenerationCompleteNs\":" +
                    std::to_string(host->selfTestGenerationCompleteNs) +
            ",\"selfTestGenerationDeadlineNs\":" +
                    std::to_string(host->selfTestGenerationDeadlineNs) +
            ",\"selfTestFirstDesiredNs\":" +
                    std::to_string(host->selfTestFirstDesiredNs) +
            ",\"selfTestFirstLatchNs\":" +
                    std::to_string(host->selfTestFirstLatchNs) +
            ",\"selfTestFirstActualNs\":" +
                    std::to_string(host->selfTestFirstActualNs) +
            ",\"selfTestSecondDesiredNs\":" +
                    std::to_string(host->selfTestSecondDesiredNs) +
            ",\"selfTestSecondLatchNs\":" +
                    std::to_string(host->selfTestSecondLatchNs) +
            ",\"selfTestSecondActualNs\":" +
                    std::to_string(host->selfTestSecondActualNs) +
            ",\"selfTestPhysicalIntervalNs\":" +
                    std::to_string(host->selfTestPhysicalIntervalNs) +
            ",\"selfTestPresentFenceOffsetNs\":" +
                    std::to_string(host->selfTestPresentFenceOffsetNs) +
            ",\"androidArm64\":true,"
            "\"fixedMidpoint\":true,\"generationCount\":1,\"slotCount\":3,"
            "\"presentMode\":" + std::to_string(static_cast<int>(owned.presentMode)) +
            ",\"displayTiming\":" + (owned.displayTiming ? "true" : "false") +
            ",\"refreshDurationNs\":" + std::to_string(owned.refreshDurationNs) +
            ",\"sameGraphicsPresentQueue\":" +
                    (owned.sameGraphicsPresentQueue ? "true" : "false") +
            ",\"externalSyncFd\":" + (owned.externalSyncFd ? "true" : "false") +
            ",\"fixedBuffersImported\":" +
                    (owned.fixedBuffersImported ? "true" : "false") +
            ",\"setupOwnershipReleased\":" +
                    (owned.setupOwnershipReleased ? "true" : "false") +
            ",\"liveResourcesReady\":" +
                    (owned.liveResourcesReady ? "true" : "false") +
            ",\"zeroWaitLivePath\":true,\"liveDeviceWaitIdle\":false,"
            "\"liveBlockingFenceWait\":false,\"contextsPrewarmed\":true,"
            "\"ownedWsiSetupPassed\":true,\"ownedWsiImplemented\":false,"
            "\"ownedWsiFrozenReference\":true,"
            "\"surfaceControlPresentation\":true,"
            "\"surfaceControlDesiredPresentTime\":true,"
            "\"surfaceControlPhysicalFence\":true,"
            "\"surfaceControlLiveImplemented\":true,"
            "\"surfaceControlReleaseFenceReuse\":true,"
            "\"setupOnlyCpuContentCheck\":true}";
        return env->NewStringUTF(record.c_str());
    } catch (const std::exception& error) {
        LOGE("capabilities failed: %s", error.what());
        return nullptr;
    }
}

extern "C" JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_copyCompositorFrameTimelines(
        JNIEnv* env, jclass, jlong handle, jlongArray vsyncIds,
        jlongArray expectedTimesNs, jlongArray deadlinesNs,
        jlongArray metadata) {
    try {
        if (vsyncIds == nullptr || expectedTimesNs == nullptr ||
                deadlinesNs == nullptr || metadata == nullptr ||
                env->GetArrayLength(vsyncIds) < 8 ||
                env->GetArrayLength(expectedTimesNs) < 8 ||
                env->GetArrayLength(deadlinesNs) < 8 ||
                env->GetArrayLength(metadata) < 2)
            throw std::invalid_argument(
                    "LSFG frame-timeline output arrays are invalid");
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->surfacePresenter == nullptr ||
                !host->surfacePresenter->supportsFrameTimeline())
            throw std::runtime_error(
                    "LSFG native frame-timeline source is unavailable");
        uint64_t callbackSequence = 0;
        uint64_t frameTimeNs = 0;
        const auto rows = host->surfacePresenter->nativeFrameTimelines(
                &callbackSequence, &frameTimeNs);
        if (rows.size() > 8)
            throw std::runtime_error("LSFG frame-timeline count overflowed");
        std::array<jlong, 8> ids{};
        std::array<jlong, 8> expected{};
        std::array<jlong, 8> deadlines{};
        for (std::size_t index = 0; index < rows.size(); ++index) {
            ids[index] = static_cast<jlong>(rows[index].vsyncId);
            expected[index] = static_cast<jlong>(
                    rows[index].expectedPresentationTimeNs);
            deadlines[index] = static_cast<jlong>(rows[index].deadlineNs);
        }
        const jlong source[2] = {
            static_cast<jlong>(callbackSequence),
            static_cast<jlong>(frameTimeNs),
        };
        env->SetLongArrayRegion(vsyncIds, 0, 8, ids.data());
        env->SetLongArrayRegion(expectedTimesNs, 0, 8, expected.data());
        env->SetLongArrayRegion(deadlinesNs, 0, 8, deadlines.data());
        env->SetLongArrayRegion(metadata, 0, 2, source);
        if (env->ExceptionCheck())
            throw std::runtime_error("LSFG frame-timeline copy failed");
        return static_cast<jint>(rows.size());
    } catch (const std::exception& error) {
        LOGE("copyCompositorFrameTimelines failed: %s", error.what());
        jclass failureClass = env->FindClass("java/lang/IllegalStateException");
        if (failureClass != nullptr) env->ThrowNew(failureClass, error.what());
        return -1;
    }
}

extern "C" JNIEXPORT void JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_prepareEndpoint(
        JNIEnv* env, jclass, jlong handle, jobject endpointBuffer) {
    try {
        if (endpointBuffer == nullptr)
            throw std::invalid_argument("LSFG endpoint buffer is null");
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->ownedVulkan == nullptr ||
                !host->contextsPrewarmed)
            throw std::runtime_error("LSFG host is not live");
        AHardwareBuffer* endpoint =
                AHardwareBuffer_fromHardwareBuffer(env, endpointBuffer);
        if (endpoint == nullptr)
            throw std::runtime_error("Java endpoint HardwareBuffer conversion failed");
        host->ownedVulkan->prepareSourceImage(endpoint);
    } catch (const std::exception& error) {
        LOGE("prepareEndpoint failed: %s", error.what());
        jclass failureClass = env->FindClass("java/lang/IllegalStateException");
        if (failureClass != nullptr) env->ThrowNew(failureClass, error.what());
    }
}

extern "C" JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_prepareRealPair(
        JNIEnv* env, jclass, jlong handle, jobject leftBuffer,
        jobject rightBuffer, jlong sessionEpoch, jlong presentationEpoch,
        jlong leftSequence, jlong leftTimestampNs, jlong rightSequence,
        jlong rightTimestampNs, jint width, jint height, jint format) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->ownedVulkan == nullptr || !host->contextsPrewarmed)
            throw std::runtime_error("LSFG host is not live");
        if (leftBuffer == nullptr || rightBuffer == nullptr ||
                sessionEpoch <= 0 || presentationEpoch <= 0 ||
                leftSequence <= 0 || leftSequence == INT64_MAX ||
                rightSequence != leftSequence + 1 || leftTimestampNs <= 0 ||
                rightTimestampNs <= leftTimestampNs ||
                width != static_cast<jint>(host->width) ||
                height != static_cast<jint>(host->height) || format != 1)
            throw std::invalid_argument("LSFG private real pair contract is invalid");
        AHardwareBuffer* left = AHardwareBuffer_fromHardwareBuffer(env, leftBuffer);
        AHardwareBuffer* right = AHardwareBuffer_fromHardwareBuffer(env, rightBuffer);
        if (left == nullptr || right == nullptr || left == right)
            throw std::runtime_error("Java endpoint HardwareBuffer conversion failed");
        if (host->preparedRealPair.has_value()) {
            if (host->preparedRealPair->matches(left, right,
                    static_cast<uint64_t>(sessionEpoch),
                    static_cast<uint64_t>(presentationEpoch),
                    static_cast<uint64_t>(leftSequence),
                    static_cast<uint64_t>(leftTimestampNs),
                    static_cast<uint64_t>(rightSequence),
                    static_cast<uint64_t>(rightTimestampNs))) {
                const uint32_t status = host->ownedVulkan->privatePreparedPairStatus(
                        host->preparedRealPair->identity.prepared);
                if (status > 1) throw std::runtime_error("real pair proof returned generation status");
                return status == 1 ? 2 : 1;
            }
            host->ownedVulkan->abandonPrivatePrepared(
                    host->preparedRealPair->identity.prepared);
            host->preparedRealPair.reset();
        }
        auto prepared = host->ownedVulkan->tryPreparePrivateEndpointPair(left, right);
        if (!prepared.has_value()) return 0;
        host->ownedVulkan->holdPrivatePrepared(*prepared, prepared->inputReadySyncFd);
        host->preparedRealPair = PreparedRealPair{PreparedGenerated{
            .left = left,
            .right = right,
            .sessionEpoch = static_cast<uint64_t>(sessionEpoch),
            .presentationEpoch = static_cast<uint64_t>(presentationEpoch),
            .leftSequence = static_cast<uint64_t>(leftSequence),
            .leftTimestampNs = static_cast<uint64_t>(leftTimestampNs),
            .rightSequence = static_cast<uint64_t>(rightSequence),
            .rightTimestampNs = static_cast<uint64_t>(rightTimestampNs),
            .presentationTimestampNs = static_cast<uint64_t>(leftTimestampNs),
            .prepared = {prepared->slotIndex, -1},
        }};
        // Queue the dependent proof in this same preparation call, while its
        // GPU wait owns the copy dependency. Do not wait for a visible request
        // or a later Java callback to initiate the next private stage.
        const uint32_t status = host->ownedVulkan->privatePreparedPairStatus(
                host->preparedRealPair->identity.prepared);
        if (status > 1) throw std::runtime_error("real pair proof returned generation status");
        return status == 1 ? 2 : 1;
    } catch (const std::exception& error) {
        LOGE("prepareRealPair failed: %s", error.what());
        return -1;
    }
}

extern "C" JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_preparedRealPairReadiness(
        JNIEnv* env, jclass, jlong handle, jobject leftBuffer,
        jobject rightBuffer, jlong sessionEpoch, jlong presentationEpoch,
        jlong leftSequence, jlong leftTimestampNs, jlong rightSequence,
        jlong rightTimestampNs) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->ownedVulkan == nullptr)
            throw std::runtime_error("LSFG host is not live");
        if (leftBuffer == nullptr || rightBuffer == nullptr ||
                sessionEpoch <= 0 || presentationEpoch <= 0 ||
                leftSequence <= 0 || leftSequence == INT64_MAX ||
                rightSequence != leftSequence + 1 || leftTimestampNs <= 0 ||
                rightTimestampNs <= leftTimestampNs)
            throw std::invalid_argument("LSFG private real readiness identity is invalid");
        if (!host->preparedRealPair.has_value()) return 0;
        AHardwareBuffer* left = AHardwareBuffer_fromHardwareBuffer(env, leftBuffer);
        AHardwareBuffer* right = AHardwareBuffer_fromHardwareBuffer(env, rightBuffer);
        if (left == nullptr || right == nullptr || left == right)
            throw std::runtime_error("Java endpoint HardwareBuffer conversion failed");
        if (!host->preparedRealPair->matches(left, right,
                static_cast<uint64_t>(sessionEpoch),
                static_cast<uint64_t>(presentationEpoch),
                static_cast<uint64_t>(leftSequence),
                static_cast<uint64_t>(leftTimestampNs),
                static_cast<uint64_t>(rightSequence),
                static_cast<uint64_t>(rightTimestampNs))) return 3;
        const uint32_t status = host->ownedVulkan->privatePreparedPairStatus(
                host->preparedRealPair->identity.prepared);
        if (status > 1) throw std::runtime_error("real pair proof returned generation status");
        return status == 1 ? 2 : 1;
    } catch (const std::exception& error) {
        LOGE("preparedRealPairReadiness failed: %s", error.what());
        return -1;
    }
}

extern "C" JNIEXPORT void JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_discardPreparedRealPair(
        JNIEnv* env, jclass, jlong handle) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->ownedVulkan == nullptr)
            throw std::runtime_error("LSFG host is not live");
        if (!host->preparedRealPair.has_value()) return;
        host->ownedVulkan->abandonPrivatePrepared(host->preparedRealPair->identity.prepared);
        host->preparedRealPair.reset();
    } catch (const std::exception& error) {
        LOGE("discardPreparedRealPair failed: %s", error.what());
        jclass failure = env->FindClass("java/lang/IllegalStateException");
        if (failure != nullptr) env->ThrowNew(failure, error.what());
    }
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_referencesSourceImage(
        JNIEnv* env, jclass, jlong handle, jobject endpointBuffer) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->ownedVulkan == nullptr || endpointBuffer == nullptr)
            throw std::runtime_error("LSFG source lease query is invalid");
        AHardwareBuffer* endpoint = AHardwareBuffer_fromHardwareBuffer(env, endpointBuffer);
        if (endpoint == nullptr)
            throw std::runtime_error("Java source HardwareBuffer conversion failed");
        if (host->continuousPair && host->continuousPair->discarded)
            (void) progressContinuousPair(host);
        if (host->continuousPair &&
                (host->continuousPair->identity.left == endpoint ||
                 host->continuousPair->identity.right == endpoint)) return JNI_TRUE;
        return host->ownedVulkan->referencesSourceImage(endpoint) ? JNI_TRUE : JNI_FALSE;
    } catch (const std::exception& error) {
        LOGE("referencesSourceImage failed: %s", error.what());
        jclass failure = env->FindClass("java/lang/IllegalStateException");
        if (failure != nullptr) env->ThrowNew(failure, error.what());
        return JNI_TRUE; // Unknown never releases the ImageReader carrier.
    }
}

extern "C" JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_prepareGenerated(
        JNIEnv* env, jclass, jlong handle, jobject leftBuffer,
        jobject rightBuffer, jlong sessionEpoch, jlong presentationEpoch,
        jlong leftSequence, jlong leftTimestampNs, jlong rightSequence,
        jlong rightTimestampNs, jlong presentationTimestampNs,
        jint width, jint height, jint format) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->ownedVulkan == nullptr ||
                !host->contextsPrewarmed)
            throw std::runtime_error("LSFG host is not live");
        if (leftBuffer == nullptr || rightBuffer == nullptr ||
                sessionEpoch <= 0 || presentationEpoch <= 0 ||
                leftSequence <= 0 || leftSequence == INT64_MAX ||
                rightSequence != leftSequence + 1 ||
                leftTimestampNs <= 0 || rightTimestampNs <= leftTimestampNs ||
                presentationTimestampNs <= leftTimestampNs ||
                presentationTimestampNs >= rightTimestampNs ||
                !emufusion::lsfg::isFloorMidpointTimestamp(
                        static_cast<uint64_t>(leftTimestampNs),
                        static_cast<uint64_t>(rightTimestampNs),
                        static_cast<uint64_t>(presentationTimestampNs)) ||
                width != static_cast<jint>(host->width) ||
                height != static_cast<jint>(host->height) || format != 1)
            throw std::invalid_argument(
                    "LSFG private preparation contract is invalid");
        AHardwareBuffer* left =
                AHardwareBuffer_fromHardwareBuffer(env, leftBuffer);
        AHardwareBuffer* right =
                AHardwareBuffer_fromHardwareBuffer(env, rightBuffer);
        if (left == nullptr || right == nullptr)
            throw std::runtime_error("Java HardwareBuffer conversion failed");
        const auto matches = [&](const PreparedGenerated& current) {
            return current.matches(left, right,
                    static_cast<uint64_t>(sessionEpoch),
                    static_cast<uint64_t>(presentationEpoch),
                    static_cast<uint64_t>(leftSequence),
                    static_cast<uint64_t>(leftTimestampNs),
                    static_cast<uint64_t>(rightSequence),
                    static_cast<uint64_t>(rightTimestampNs),
                    static_cast<uint64_t>(presentationTimestampNs));
        };
        if (host->continuousPair) {
            if (!matches(host->continuousPair->identity)) discardContinuousPair(host);
            if (host->continuousPair) {
                if (host->continuousPair->discarded) return 0;
                return progressContinuousPair(host);
            }
        }
        if (host->preparedGenerated.has_value()) {
            if (matches(*host->preparedGenerated)) {
                const uint32_t pairStatus =
                        host->ownedVulkan->privatePreparedPairStatus(
                                host->preparedGenerated->prepared);
                return pairStatus == 0 ? 1 : pairStatus == 1 ? 2 : 3;
            }
            host->ownedVulkan->abandonPrivatePrepared(
                    host->preparedGenerated->prepared);
            host->preparedGenerated.reset();
        }
        if (!host->continuous) throw std::runtime_error("continuous context is unavailable");
        const auto last = host->continuous->lastCompleted();
        if (last && (last->session != static_cast<uint64_t>(sessionEpoch) ||
                last->timeline != static_cast<uint64_t>(presentationEpoch) ||
                last->sequence != static_cast<uint64_t>(leftSequence) ||
                last->timestampNs != static_cast<uint64_t>(leftTimestampNs)))
            throw std::runtime_error("LSFG pair skips temporal history; recreate transport");
        PreparedGenerated identity{
            .left = left,
            .right = right,
            .sessionEpoch = static_cast<uint64_t>(sessionEpoch),
            .presentationEpoch = static_cast<uint64_t>(presentationEpoch),
            .leftSequence = static_cast<uint64_t>(leftSequence),
            .leftTimestampNs = static_cast<uint64_t>(leftTimestampNs),
            .rightSequence = static_cast<uint64_t>(rightSequence),
            .rightTimestampNs = static_cast<uint64_t>(rightTimestampNs),
            .presentationTimestampNs =
                    static_cast<uint64_t>(presentationTimestampNs),
        };
        host->continuousPair = ContinuousPair{.identity = identity, .needsLeft = !last};
        return progressContinuousPair(host);
    } catch (const std::exception& error) {
        LOGE("prepareGenerated failed: %s", error.what());
        return -1;
    }
}

extern "C" JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_preparedGeneratedReadiness(
        JNIEnv* env, jclass, jlong handle, jobject leftBuffer,
        jobject rightBuffer, jlong sessionEpoch, jlong presentationEpoch,
        jlong leftSequence, jlong leftTimestampNs, jlong rightSequence,
        jlong rightTimestampNs, jlong presentationTimestampNs) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->ownedVulkan == nullptr)
            throw std::runtime_error("LSFG host is not live");
        AHardwareBuffer* left =
                AHardwareBuffer_fromHardwareBuffer(env, leftBuffer);
        AHardwareBuffer* right =
                AHardwareBuffer_fromHardwareBuffer(env, rightBuffer);
        if (left == nullptr || right == nullptr)
            throw std::runtime_error("Java HardwareBuffer conversion failed");
        if (host->continuousPair) {
            if (!host->continuousPair->identity.matches(left, right,
                    static_cast<uint64_t>(sessionEpoch),
                    static_cast<uint64_t>(presentationEpoch),
                    static_cast<uint64_t>(leftSequence),
                    static_cast<uint64_t>(leftTimestampNs),
                    static_cast<uint64_t>(rightSequence),
                    static_cast<uint64_t>(rightTimestampNs),
                    static_cast<uint64_t>(presentationTimestampNs))) return 3;
            const int progress = progressContinuousPair(host);
            if (!host->preparedGenerated) return progress;
        }
        if (!host->preparedGenerated.has_value()) return 0;
        if (!host->preparedGenerated->matches(left, right,
                static_cast<uint64_t>(sessionEpoch),
                static_cast<uint64_t>(presentationEpoch),
                static_cast<uint64_t>(leftSequence),
                static_cast<uint64_t>(leftTimestampNs),
                static_cast<uint64_t>(rightSequence),
                static_cast<uint64_t>(rightTimestampNs),
                static_cast<uint64_t>(presentationTimestampNs)))
            return 3;
        const uint32_t pairStatus =
                host->ownedVulkan->privatePreparedPairStatus(
                        host->preparedGenerated->prepared);
        return pairStatus == 0 ? 1 : pairStatus == 1 ? 2 : 3;
    } catch (const std::exception& error) {
        LOGE("preparedGeneratedReadiness failed: %s", error.what());
        return -1;
    }
}

extern "C" JNIEXPORT void JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_discardPreparedGenerated(
        JNIEnv*, jclass, jlong handle) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->ownedVulkan == nullptr) return;
        discardContinuousPair(host);
        if (!host->preparedGenerated.has_value()) return;
        host->ownedVulkan->abandonPrivatePrepared(
                host->preparedGenerated->prepared);
        host->preparedGenerated.reset();
    } catch (const std::exception& error) {
        LOGE("discardPreparedGenerated failed: %s", error.what());
    }
}

extern "C" JNIEXPORT jint JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_enqueue(
        JNIEnv* env, jclass, jlong handle, jobject leftBuffer,
        jobject rightBuffer, jlong sessionEpoch, jlong presentationEpoch,
        jlong leftSequence, jlong leftTimestampNs, jlong rightSequence,
        jlong rightTimestampNs, jlong presentationTimestampNs,
        jlong desiredPhysicalPresentTimeNs, jlong driverDesiredPresentTimeNs,
        jlong hardCompletionDeadlineNs,
        jlong compositorFrameTimelineVsyncId,
        jlong compositorFrameTimelineExpectedNs,
        jlong compositorFrameTimelineDeadlineNs,
        jint width, jint height, jint format,
        jlong presentId) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->ownedVulkan == nullptr ||
                !host->contextsPrewarmed)
            throw std::runtime_error("LSFG host is not live");
        if (leftBuffer == nullptr || rightBuffer == nullptr ||
                sessionEpoch <= 0 || presentationEpoch <= 0 ||
                leftSequence <= 0 || leftSequence == INT64_MAX ||
                rightSequence != leftSequence + 1 ||
                leftTimestampNs <= 0 || rightTimestampNs <= leftTimestampNs ||
                presentationTimestampNs < leftTimestampNs ||
                presentationTimestampNs > rightTimestampNs ||
                desiredPhysicalPresentTimeNs <= 0 ||
                driverDesiredPresentTimeNs <= 0 || hardCompletionDeadlineNs <= 0 ||
                compositorFrameTimelineVsyncId <= 0 ||
                compositorFrameTimelineExpectedNs <= 0 ||
                compositorFrameTimelineDeadlineNs <= 0 ||
                hardCompletionDeadlineNs > driverDesiredPresentTimeNs ||
                driverDesiredPresentTimeNs > desiredPhysicalPresentTimeNs ||
                width != static_cast<jint>(host->width) ||
                height != static_cast<jint>(host->height) || format != 1 ||
                presentId <= 0 || presentId > UINT32_MAX)
            throw std::invalid_argument("LSFG native request contract is invalid");
        const bool generated = presentationTimestampNs > leftTimestampNs &&
                presentationTimestampNs < rightTimestampNs;
        if (generated && !emufusion::lsfg::isFloorMidpointTimestamp(
                static_cast<uint64_t>(leftTimestampNs),
                static_cast<uint64_t>(rightTimestampNs),
                static_cast<uint64_t>(presentationTimestampNs)))
            throw std::invalid_argument("LSFG request is not an exact midpoint");
        AHardwareBuffer* left =
                AHardwareBuffer_fromHardwareBuffer(env, leftBuffer);
        AHardwareBuffer* right =
                AHardwareBuffer_fromHardwareBuffer(env, rightBuffer);
        if (left == nullptr || right == nullptr)
            throw std::runtime_error("Java HardwareBuffer conversion failed");
        // The selected AChoreographer deadline already contains the fixed
        // 2-ms app-work reserve used by this presenter's immutable contract.
        // The setup WSI refresh belongs to the temporary startup mode and must
        // never be reported as the live Thor panel period.
        constexpr uint64_t kCompositorAppWorkReserveNs = 2'000'000ULL;
        const uint64_t expectedNs =
                static_cast<uint64_t>(compositorFrameTimelineExpectedNs);
        const uint64_t deadlineNs =
                static_cast<uint64_t>(compositorFrameTimelineDeadlineNs);
        if (expectedNs <= deadlineNs + kCompositorAppWorkReserveNs)
            throw std::invalid_argument(
                    "LSFG compositor refresh interval is invalid");
        const uint64_t liveRefreshDurationNs =
                expectedNs - deadlineNs - kCompositorAppWorkReserveNs;
        if (liveRefreshDurationNs < 4'000'000ULL ||
                liveRefreshDurationNs > 25'000'000ULL)
            throw std::invalid_argument(
                    "LSFG compositor refresh interval is unsupported");
        emufusion::lsfg::OwnedVulkanHost::LiveRequest request{
            .left = left,
            .right = right,
            .presentId = static_cast<uint64_t>(presentId),
            .physicalPresentTimeNs =
                    static_cast<uint64_t>(desiredPhysicalPresentTimeNs),
            .desiredPresentTimeNs =
                    static_cast<uint64_t>(driverDesiredPresentTimeNs),
            .completionDeadlineNs =
                    static_cast<uint64_t>(hardCompletionDeadlineNs),
            .refreshDurationNs = liveRefreshDurationNs,
            .compositorFrameTimelineVsyncId =
                    static_cast<uint64_t>(compositorFrameTimelineVsyncId),
            .compositorFrameTimelineExpectedNs =
                    static_cast<uint64_t>(compositorFrameTimelineExpectedNs),
            .compositorFrameTimelineDeadlineNs =
                    static_cast<uint64_t>(compositorFrameTimelineDeadlineNs),
            .generated = generated,
            .presentRight = presentationTimestampNs == rightTimestampNs,
            .sessionEpoch = static_cast<uint64_t>(sessionEpoch),
            .presentationEpoch = static_cast<uint64_t>(presentationEpoch),
            .leftSequence = static_cast<uint64_t>(leftSequence),
            .rightSequence = static_cast<uint64_t>(rightSequence),
            .leftTimestampNs = static_cast<uint64_t>(leftTimestampNs),
            .rightTimestampNs = static_cast<uint64_t>(rightTimestampNs),
            .contentTimestampNs = static_cast<uint64_t>(presentationTimestampNs),
        };
        // Retired-drop metadata can wait behind an older physical callback.
        // Bound that queue separately from the three GPU-owned live slots;
        // do not allocate an unbounded completion FIFO during a stalled scan.
        if (host->droppedCompletions.size() >= kSlotCount) return 0;
        if (generated) {
            if (!host->preparedGenerated.has_value() ||
                    !host->preparedGenerated->matches(left, right,
                            static_cast<uint64_t>(sessionEpoch),
                            static_cast<uint64_t>(presentationEpoch),
                            static_cast<uint64_t>(leftSequence),
                            static_cast<uint64_t>(leftTimestampNs),
                            static_cast<uint64_t>(rightSequence),
                            static_cast<uint64_t>(rightTimestampNs),
                            static_cast<uint64_t>(presentationTimestampNs)))
                return 0;
            if (host->ownedVulkan->privatePreparedPairStatus(
                    host->preparedGenerated->prepared) != 1U) return 0;
            if (!host->ownedVulkan->activatePrivatePrepared(
                    host->preparedGenerated->prepared, request)) return 0;
            host->preparedGenerated.reset();
            dispatchReadySurfaceSubmission(host);
            return 1;
        }
        if (!host->preparedRealPair.has_value() ||
                (presentationTimestampNs != leftTimestampNs &&
                        presentationTimestampNs != rightTimestampNs) ||
                !host->preparedRealPair->matches(left, right,
                        static_cast<uint64_t>(sessionEpoch),
                        static_cast<uint64_t>(presentationEpoch),
                        static_cast<uint64_t>(leftSequence),
                        static_cast<uint64_t>(leftTimestampNs),
                        static_cast<uint64_t>(rightSequence),
                        static_cast<uint64_t>(rightTimestampNs))) return 0;
        if (host->ownedVulkan->privatePreparedPairStatus(
                host->preparedRealPair->identity.prepared) != 1U) return 0;
        if (!host->ownedVulkan->activatePrivatePrepared(
                host->preparedRealPair->identity.prepared, request)) return 0;
        host->preparedRealPair.reset();
        // A ready image must reach the compositor worker now, not after an
        // unrelated next owner callback that can arrive beyond this cutoff.
        // Success is still admission only; physical/drop completion is polled.
        dispatchReadySurfaceSubmission(host);
        return 1;
    } catch (const std::exception& error) {
        LOGE("enqueue failed: %s", error.what());
        return -1;
    }
}

extern "C" JNIEXPORT jlongArray JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_poll(
        JNIEnv* env, jclass, jlong handle) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed || host->ownedVulkan == nullptr ||
                host->surfacePresenter == nullptr)
            throw std::runtime_error("LSFG host is closed");

        auto completion = progressLiveSurfacePipeline(host);
        if (!completion.has_value()) return nullptr;
        const jlong values[24] = {
            static_cast<jlong>(completion->presentId),
            static_cast<jlong>(completion->desiredPresentTimeNs),
            completion->dropped ? 0 :
                    static_cast<jlong>(completion->actualPresentTimeNs),
            static_cast<jlong>(completion->earliestPresentTimeNs),
            static_cast<jlong>(completion->presentMarginNs),
            static_cast<jlong>(completion->refreshDurationNs),
            static_cast<jlong>(completion->gpuWorkNs),
            static_cast<jlong>(completion->pairStatus),
            static_cast<jlong>(completion->leftChecksum),
            static_cast<jlong>(completion->rightChecksum),
            static_cast<jlong>(completion->outputChecksum),
            static_cast<jlong>(completion->endpointMadPpm),
            static_cast<jlong>(completion->outputLeftMadPpm),
            static_cast<jlong>(completion->outputRightMadPpm),
            static_cast<jlong>(completion->endpointHistogramDistancePpm),
            static_cast<jlong>(completion->outputMin),
            static_cast<jlong>(completion->outputMax),
            completion->sceneCutRisk ? 1 : 0,
            static_cast<jlong>(completion->analysisWallNs),
            48, 27, 1296,
            static_cast<jlong>(completion->presentId),
            11664,
        };
        jlongArray result = env->NewLongArray(24);
        if (result == nullptr) throw std::runtime_error("completion array allocation failed");
        env->SetLongArrayRegion(result, 0, 24, values);
        return result;
    } catch (const std::exception& error) {
        LOGE("poll failed: %s", error.what());
        jclass failureClass = env->FindClass("java/lang/IllegalStateException");
        if (failureClass != nullptr) env->ThrowNew(failureClass, error.what());
        return nullptr;
    }
}

extern "C" JNIEXPORT void JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_resetTimeline(
        JNIEnv* env, jclass, jlong handle, jlong presentationEpoch) {
    try {
        Host* host = fromHandle(handle);
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed) throw std::runtime_error("LSFG host is closed");
        if (presentationEpoch <= 0)
            throw std::invalid_argument("LSFG presentation epoch is invalid");
        if (host->ownedVulkan == nullptr)
            throw std::runtime_error("LSFG owned Vulkan host is unavailable");
        const auto last = host->continuous ? host->continuous->lastCompleted() : std::nullopt;
        if (host->continuousPair || (last && last->timeline != static_cast<uint64_t>(presentationEpoch)))
            throw std::runtime_error("LSFG active history requires fresh transport for timeline reset");
        if (host->preparedGenerated.has_value()) {
            host->ownedVulkan->abandonPrivatePrepared(
                    host->preparedGenerated->prepared);
            host->preparedGenerated.reset();
        }
        if (host->preparedRealPair.has_value()) {
            host->ownedVulkan->abandonPrivatePrepared(
                    host->preparedRealPair->identity.prepared);
            host->preparedRealPair.reset();
        }
        host->ownedVulkan->resetTimeline(
                static_cast<uint64_t>(presentationEpoch));
    } catch (const std::exception& error) {
        LOGE("resetTimeline failed: %s", error.what());
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"), error.what());
    }
}

extern "C" JNIEXPORT void JNICALL
Java_com_thorium_preview_game_NativeLsfgBridge_close(
        JNIEnv*, jclass, jlong handle) {
    if (handle == 0) return;
    std::unique_ptr<Host> host(fromHandle(handle));
    {
        std::lock_guard<std::mutex> libraryLock(g_libraryMutex);
        if (g_libraryOwner == host.get()) g_libraryOwner = nullptr;
    }
    {
        std::lock_guard<std::mutex> lock(host->mutex);
        if (host->closed) return;
        host->closed = true;
        destroyHost(host.get());
    }
}
