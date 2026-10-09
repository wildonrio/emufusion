#include "owned_vulkan_host.hpp"
#include "triplet_capture.hpp"
#include "sync_poll_result.hpp"

#include <android/log.h>
#include <android/sync.h>
#include <volk.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <deque>
#include <limits>
#include <optional>
#include <poll.h>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>
#include <sys/stat.h>
#include <unistd.h>

#define LOG_TAG "EmuFusion-LSFG-WSI"
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

namespace emufusion::lsfg {
namespace {

constexpr uint64_t kSetupFenceTimeoutNs = 1'000'000'000ULL;
// A missed visible deadline is never extended. This separate bound only
// limits zero-polled retirement of work that will NEVER be presented.
constexpr uint64_t kDroppedDrainTimeoutNs = 1'000'000'000ULL;
constexpr uint64_t kCutoffDiagnosticRequestLimit = 8;
constexpr uint32_t kProofWidth = 48;
constexpr uint32_t kProofHeight = 27;
constexpr uint32_t kProofTileCount = 3;
constexpr uint32_t kProofAtlasHeight = kProofHeight * kProofTileCount;
constexpr VkDeviceSize kProofRgbaBytes =
        static_cast<VkDeviceSize>(kProofWidth) * kProofAtlasHeight * 4U;
constexpr uint64_t kLogicalProofBytes =
        static_cast<uint64_t>(kProofWidth) * kProofHeight * 3U * 3U;
constexpr uint32_t kPairReady = 1;
constexpr uint32_t kPairUnsafe = 2;

uint64_t monotonicNs() {
    return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
}

[[noreturn]] void fail(const char* operation, VkResult result) {
    std::ostringstream message;
    message << operation << " failed (VkResult=" << static_cast<int>(result) << ')';
    throw std::runtime_error(message.str());
}

void requireSuccess(VkResult result, const char* operation) {
    if (result != VK_SUCCESS) fail(operation, result);
}

struct ReadyFenceObservation {
    bool ready = false;
    uint64_t kernelSignalNs = 0; // Zero means unavailable, never a guessed time.
    bool stateKnown = false;
};

ReadyFenceObservation observeReadyFence(int fd) {
    if (fd == -1) return {true, 0, true}; // Explicit no-wait/already-ready sentinel.
    if (fd < -1) throw std::runtime_error("dropped output fence identity invalid");
    pollfd descriptor{fd, POLLIN, 0};
    const int status = ::poll(&descriptor, 1, 0);
    if (status == 0) return {false, 0, true};
    // Match libsync's transient-error contract without its retry loop: the
    // next owner poll retries, and the separate drain watchdog still applies.
    if (status == -1 && (errno == EINTR || errno == EAGAIN)) return {};
    if (status != 1 || (descriptor.revents & (POLLERR | POLLNVAL)) != 0 ||
            (descriptor.revents & (POLLIN | POLLERR | POLLHUP)) == 0)
        throw std::runtime_error("dropped output fence poll failed");
    std::unique_ptr<struct sync_file_info, decltype(&sync_file_info_free)> info(
            sync_file_info(fd), &sync_file_info_free);
    if (!info && (errno == EINTR || errno == EAGAIN)) return {};
    if (!info || info->status != 1)
        throw std::runtime_error("dropped output fence status unknown or failed");
    uint64_t signalNs = 0;
    bool allTimestampsKnown = info->num_fences != 0;
    const sync_fence_info* fences = sync_get_fence_info(info.get());
    for (uint32_t index = 0; index < info->num_fences; ++index) {
        if (fences[index].status != 1)
            throw std::runtime_error("dropped output child fence invalid");
        if (fences[index].timestamp_ns == 0) allTimestampsKnown = false;
        signalNs = std::max<uint64_t>(signalNs, fences[index].timestamp_ns);
    }
    // Valid signaled status proves completion, not availability of its time.
    // Like Android Fence::getSignalTime, empty information starts at zero.
    // Missing child times must never become an inferred completion timestamp.
    return {true, allTimestampsKnown ? signalNs : 0, true};
}

bool hasExtension(const std::vector<VkExtensionProperties>& extensions,
                  const char* name) {
    return std::any_of(extensions.begin(), extensions.end(),
            [name](const VkExtensionProperties& extension) {
                return std::strcmp(extension.extensionName, name) == 0;
            });
}

std::vector<VkExtensionProperties> instanceExtensions() {
    uint32_t count = 0;
    requireSuccess(vkEnumerateInstanceExtensionProperties(
            nullptr, &count, nullptr), "enumerate instance extensions");
    std::vector<VkExtensionProperties> result(count);
    requireSuccess(vkEnumerateInstanceExtensionProperties(
            nullptr, &count, result.data()), "read instance extensions");
    result.resize(count);
    return result;
}

std::vector<VkExtensionProperties> deviceExtensions(VkPhysicalDevice device) {
    uint32_t count = 0;
    requireSuccess(vkEnumerateDeviceExtensionProperties(
            device, nullptr, &count, nullptr), "enumerate device extensions");
    std::vector<VkExtensionProperties> result(count);
    requireSuccess(vkEnumerateDeviceExtensionProperties(
            device, nullptr, &count, result.data()), "read device extensions");
    result.resize(count);
    return result;
}

uint32_t compatibleMemoryType(VkPhysicalDevice physicalDevice,
                              uint32_t allowedBits) {
    VkPhysicalDeviceMemoryProperties properties{};
    vkGetPhysicalDeviceMemoryProperties(physicalDevice, &properties);
    for (uint32_t index = 0; index < properties.memoryTypeCount; ++index) {
        if ((allowedBits & (1U << index)) != 0U &&
                (properties.memoryTypes[index].propertyFlags &
                 VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT) != 0U) {
            return index;
        }
    }
    for (uint32_t index = 0; index < properties.memoryTypeCount; ++index) {
        if ((allowedBits & (1U << index)) != 0U) return index;
    }
    throw std::runtime_error("AHardwareBuffer has no compatible Vulkan memory type");
}

}  // namespace

class OwnedVulkanHost::Impl final {
public:
    struct ImportedImage {
        AHardwareBuffer* buffer = nullptr;
        VkImage image = VK_NULL_HANDLE;
        VkDeviceMemory memory = VK_NULL_HANDLE;
        VkExtent2D extent{};
    };

    struct ImportedSlot {
        ImportedImage left;
        ImportedImage right;
        ImportedImage output;
    };

    enum class LiveSlotState {
        Idle,
        CopyQueued,
        PrivateAwaitingReady,
        PrivateProofQueued,
        PrivateReady,
        Abandoned,
        AwaitingReady,
        Presented,
        SurfaceProofQueued,
        SurfaceDroppedAwaitingReady,
        SurfaceDroppedAwaitingProof,
        SurfaceDeliveredAwaitingRelease,
    };

    struct LiveSlot {
        VkCommandBuffer copyCommand = VK_NULL_HANDLE;
        VkCommandBuffer presentCommand = VK_NULL_HANDLE;
        VkFence copyFence = VK_NULL_HANDLE;
        VkFence presentFence = VK_NULL_HANDLE;
        VkSemaphore inputReady = VK_NULL_HANDLE;
        VkSemaphore acquire = VK_NULL_HANDLE;
        VkSemaphore render = VK_NULL_HANDLE;
        VkImage proofImage = VK_NULL_HANDLE;
        VkDeviceMemory proofImageMemory = VK_NULL_HANDLE;
        VkBuffer proofBuffer = VK_NULL_HANDLE;
        VkDeviceMemory proofBufferMemory = VK_NULL_HANDLE;
        void* proofMapped = nullptr;
        bool proofCoherent = false;
        bool proofInitialized = false;
        ImportedImage* sourceLeft = nullptr;
        ImportedImage* sourceRight = nullptr;
        ImportedImage* sourceGenerated = nullptr;
        LiveSlotState state = LiveSlotState::Idle;
        LiveRequest request{};
        uint64_t gpuStartNs = 0;
        uint64_t gpuCompletionObservedNs = 0;
        uint32_t swapchainImage = UINT32_MAX;
        uint32_t wsiPresentId = 0;
        int readySyncFd = -1;
        int proofTimestampSyncFd = -1;
        uint32_t privatePairStatus = 0;
        bool privateProofPrepared = false;
        uint64_t fullCaptureId = 0;
        uint64_t cutoffObservedNs = 0;
        uint64_t cutoffDropOrdinal = 0;
        uint32_t cutoffBranch = 0;
    };

    struct DropDrainObservation {
        bool copyKnown = false;
        bool copyReady = false;
        bool proofKnown = false;
        bool proofReady = false;
        bool outputKnown = false;
        ReadyFenceObservation output{};
        bool ready() const {
            return copyKnown && copyReady && proofKnown && proofReady &&
                    outputKnown && output.ready;
        }
    };

    ~Impl() { close(); }

    void open(ANativeWindow* outputWindow, uint32_t endpointWidth,
              uint32_t endpointHeight) {
        if (instance_ != VK_NULL_HANDLE || outputWindow == nullptr ||
                endpointWidth == 0 || endpointHeight == 0) {
            throw std::invalid_argument("invalid or repeated owned Vulkan open");
        }
        endpointExtent_ = {endpointWidth, endpointHeight};
        requireSuccess(volkInitialize(), "volkInitialize");

        const auto availableInstance = instanceExtensions();
        const std::array<const char*, 2> requiredInstance = {
            VK_KHR_SURFACE_EXTENSION_NAME,
            VK_KHR_ANDROID_SURFACE_EXTENSION_NAME,
        };
        for (const char* name : requiredInstance) {
            if (!hasExtension(availableInstance, name))
                throw std::runtime_error(std::string("missing instance extension: ") + name);
        }
        const VkApplicationInfo application{
            .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
            .pApplicationName = "EmuFusion LSFG qualification",
            .applicationVersion = VK_MAKE_API_VERSION(0, 1, 0, 0),
            .pEngineName = "EmuFusion",
            .engineVersion = VK_MAKE_API_VERSION(0, 1, 0, 0),
            .apiVersion = VK_API_VERSION_1_2,
        };
        const VkInstanceCreateInfo create{
            .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
            .pApplicationInfo = &application,
            .enabledExtensionCount = static_cast<uint32_t>(requiredInstance.size()),
            .ppEnabledExtensionNames = requiredInstance.data(),
        };
        requireSuccess(vkCreateInstance(&create, nullptr, &instance_),
                       "create owned Vulkan instance");
        volkLoadInstance(instance_);
        loadInstanceFunctions();

        const VkAndroidSurfaceCreateInfoKHR surfaceCreate{
            .sType = VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR,
            .window = outputWindow,
        };
        requireSuccess(createAndroidSurface_(instance_, &surfaceCreate, nullptr,
                                             &surface_),
                       "create owned Android surface");
        choosePhysicalDeviceAndQueue();
        createDevice();
        createSwapchain();
        createSetupCommandPool();
    }

    void importAndPrepareFixedBuffers(
            const std::array<FixedBuffers, kFixedSlotCount>& buffers) {
        if (device_ == VK_NULL_HANDLE || capabilities_.fixedBuffersImported)
            throw std::logic_error("owned Vulkan fixed-buffer import ordering invalid");
        try {
            for (uint32_t index = 0; index < kFixedSlotCount; ++index) {
                imported_[index].left = importImage(buffers[index].left);
                imported_[index].right = importImage(buffers[index].right);
                imported_[index].output = importImage(buffers[index].output);
            }
            capabilities_.fixedBuffersImported = true;
            transitionFixedBuffersToExternal();
            capabilities_.setupOwnershipReleased = true;
            createLiveResources();
            capabilities_.liveResourcesReady = true;
            initializeTripletCapture();
        } catch (...) {
            destroyLiveResources();
            destroyImportedImages();
            capabilities_.fixedBuffersImported = false;
            capabilities_.setupOwnershipReleased = false;
            capabilities_.liveResourcesReady = false;
            throw;
        }
    }

    std::optional<PreparedPresentation> tryPrepare(const LiveRequest& request) {
        validateLiveRequest(request);
        // Structurally invalid requests are errors. A valid request can simply
        // expire between the Java check and this native admission point. It
        // has not acquired a slot or submitted GPU work: decline it unchanged.
        if (monotonicNs() >= request.completionDeadlineNs) return std::nullopt;
        retireAbandonedCopies();
        uint32_t slotIndex = UINT32_MAX;
        for (uint32_t offset = 0; offset < kFixedSlotCount; ++offset) {
            const uint32_t candidate =
                    (nextLiveSlot_ + offset) % kFixedSlotCount;
            if (candidate == inferenceSlot_) continue;
            if (live_[candidate].state == LiveSlotState::Idle) {
                slotIndex = candidate;
                break;
            }
        }
        if (slotIndex == UINT32_MAX) return std::nullopt;
        if (monotonicNs() >= request.completionDeadlineNs) return std::nullopt;
        LiveSlot& slot = live_[slotIndex];
        nextLiveSlot_ = (slotIndex + 1U) % kFixedSlotCount;
        resetLiveSlotForRequest(slot, request);
        try {
            slot.sourceLeft = &cachedSourceImage(request.left);
            slot.sourceRight = &cachedSourceImage(request.right);
            recordEndpointCopy(slotIndex, slot);
            slot.gpuStartNs = monotonicNs();
            const VkSubmitInfo submit{
                .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                .commandBufferCount = 1,
                .pCommandBuffers = &slot.copyCommand,
                .signalSemaphoreCount = 1,
                .pSignalSemaphores = &slot.inputReady,
            };
            requireSuccess(deviceFunctions_.vkQueueSubmit(
                    queue_, 1, &submit, slot.copyFence),
                    "submit exact endpoint copy");
            slot.state = LiveSlotState::CopyQueued;
            const VkSemaphoreGetFdInfoKHR fdInfo{
                .sType = VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR,
                .semaphore = slot.inputReady,
                .handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT,
            };
            int syncFd = -1;
            requireSuccess(deviceFunctions_.vkGetSemaphoreFdKHR(
                    device_, &fdInfo, &syncFd), "export endpoint-copy sync FD");
            return PreparedPresentation{slotIndex, syncFd};
        } catch (...) {
            // If queue submission happened, only teardown can prove safety.
            if (slot.state == LiveSlotState::CopyQueued) fatal_ = true;
            else resetLiveSlotStorage(slot);
            throw;
        }
    }

    std::optional<PreparedPresentation> tryPreparePrivateGenerated(
            AHardwareBuffer* left, AHardwareBuffer* right) {
        return tryPreparePrivateOutput(left, right, true);
    }

    void reserveInferenceSlot(uint32_t slotIndex) {
        if (fatal_ || !capabilities_.liveResourcesReady || slotIndex >= kFixedSlotCount)
            throw std::invalid_argument("invalid inference slot reservation");
        if (inferenceSlot_ == slotIndex) return;
        if (inferenceSlot_ != UINT32_MAX || live_[slotIndex].state != LiveSlotState::Idle)
            throw std::logic_error("inference reservation requires an idle unreserved slot");
        inferenceSlot_ = slotIndex;
    }

    uint32_t reserveIdleInferenceSlot() {
        if (inferenceSlot_ != UINT32_MAX) return inferenceSlot_;
        retireAbandonedCopies();
        for (uint32_t candidate = 0; candidate < kFixedSlotCount; ++candidate) {
            if (live_[candidate].state != LiveSlotState::Idle) continue;
            reserveInferenceSlot(candidate);
            return candidate;
        }
        throw std::runtime_error("no idle slot available for continuous inference");
    }

    std::optional<PreparedPresentation> tryPrepareContinuousInputs(
            AHardwareBuffer* previous, AHardwareBuffer* next, unsigned nextInput) {
        if (inferenceSlot_ == UINT32_MAX || nextInput > 1)
            throw std::invalid_argument("continuous input slot/parity is invalid");
        const auto& scratch = imported_[inferenceSlot_];
        for (auto* source : {previous, next})
            if (source == scratch.left.buffer || source == scratch.right.buffer ||
                    source == scratch.output.buffer)
                throw std::invalid_argument("continuous input aliases inference scratch");
        return tryPreparePrivateOutput(nextInput == 0 ? next : previous,
                nextInput == 0 ? previous : next, true, nullptr, inferenceSlot_);
    }

    std::optional<PreparedPresentation> tryPreparePrivateEndpointPair(
            AHardwareBuffer* left, AHardwareBuffer* right) {
        return tryPreparePrivateOutput(left, right, false);
    }

    std::optional<PreparedPresentation> tryCopyCompletedGenerated(
            AHardwareBuffer* left, AHardwareBuffer* right,
            AHardwareBuffer* generated, int completionFd) {
        if (!generated || generated == left || generated == right || completionFd < -1)
            throw std::invalid_argument("invalid completed generated source");
        const auto completion = pollSyncCompletion(completionFd);
        if (completion == SyncCompletion::Pending) return std::nullopt;
        if (completion == SyncCompletion::Failed)
            throw std::runtime_error("generated source completion failed");
        return tryPreparePrivateOutput(left, right, true, generated);
    }

    std::optional<PreparedPresentation> tryPreparePrivateOutput(
            AHardwareBuffer* left, AHardwareBuffer* right, bool generated,
            AHardwareBuffer* generatedSource = nullptr, uint32_t requiredSlot = UINT32_MAX) {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        if (!capabilities_.liveResourcesReady || presentationEpoch_ == 0 ||
                left == nullptr || right == nullptr)
            throw std::invalid_argument(
                    "owned Vulkan private preparation is invalid");
        retireAbandonedCopies();
        uint32_t slotIndex = UINT32_MAX;
        for (uint32_t offset = 0; offset < kFixedSlotCount; ++offset) {
            const uint32_t candidate =
                    (nextLiveSlot_ + offset) % kFixedSlotCount;
            if (requiredSlot != UINT32_MAX ? candidate != requiredSlot :
                    candidate == inferenceSlot_) continue;
            if (generatedSource) {
                const auto& destination = imported_[candidate];
                bool aliases = false;
                for (auto* source : {left, right, generatedSource})
                    aliases = aliases || source == destination.left.buffer ||
                            source == destination.right.buffer || source == destination.output.buffer;
                if (aliases) continue;
            }
            if (live_[candidate].state == LiveSlotState::Idle) {
                slotIndex = candidate;
                break;
            }
        }
        if (slotIndex == UINT32_MAX) return std::nullopt;
        LiveSlot& slot = live_[slotIndex];
        nextLiveSlot_ = (slotIndex + 1U) % kFixedSlotCount;
        LiveRequest pixelRequest{
            .left = left,
            .right = right,
            .generated = generated,
        };
        resetLiveSlotForRequest(slot, pixelRequest);
        try {
            slot.sourceLeft = &cachedSourceImage(left);
            slot.sourceRight = &cachedSourceImage(right);
            slot.sourceGenerated = generatedSource ? &cachedSourceImage(generatedSource) : nullptr;
            recordEndpointCopy(slotIndex, slot);
            slot.gpuStartNs = monotonicNs();
            const VkSubmitInfo submit{
                .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                .commandBufferCount = 1,
                .pCommandBuffers = &slot.copyCommand,
                .signalSemaphoreCount = 1,
                .pSignalSemaphores = &slot.inputReady,
            };
            requireSuccess(deviceFunctions_.vkQueueSubmit(
                    queue_, 1, &submit, slot.copyFence),
                    "submit private endpoint copy");
            slot.state = LiveSlotState::CopyQueued;
            const VkSemaphoreGetFdInfoKHR fdInfo{
                .sType = VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR,
                .semaphore = slot.inputReady,
                .handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT,
            };
            int syncFd = -1;
            requireSuccess(deviceFunctions_.vkGetSemaphoreFdKHR(
                    device_, &fdInfo, &syncFd),
                    "export private endpoint-copy sync FD");
            return PreparedPresentation{slotIndex, syncFd};
        } catch (...) {
            if (slot.state == LiveSlotState::CopyQueued) fatal_ = true;
            else resetLiveSlotStorage(slot);
            throw;
        }
    }

    void prepareSourceImage(AHardwareBuffer* buffer) {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        if (!capabilities_.liveResourcesReady)
            throw std::logic_error("owned Vulkan live resources are unavailable");
        (void) cachedSourceImage(buffer);
    }

    bool referencesSourceImage(AHardwareBuffer* buffer) {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        if (buffer == nullptr)
            throw std::invalid_argument("source image reference query is null");
        try {
            retireAbandonedCopies();
            bool copyPending = false;
            for (const LiveSlot& slot : live_) {
                if (slot.state == LiveSlotState::Idle ||
                        !((slot.sourceLeft != nullptr && slot.sourceLeft->buffer == buffer) ||
                          (slot.sourceRight != nullptr && slot.sourceRight->buffer == buffer) ||
                          (slot.sourceGenerated != nullptr && slot.sourceGenerated->buffer == buffer)))
                    continue;
                // recordEndpointCopy is the only GPU reader of these original
                // carriers and releases both to EXTERNAL before copyFence.
                // Proof, LSFG and the compositor own fixed slot copies instead.
                // Do not retire/reset that later work when releasing a carrier.
                if (slot.copyFence == VK_NULL_HANDLE)
                    throw std::logic_error("source image lease lost its copy fence");
                const VkResult status = deviceFunctions_.vkGetFenceStatus(
                        device_, slot.copyFence);
                if (status == VK_NOT_READY) copyPending = true;
                else requireSuccess(status, "poll original source-copy lease fence");
                // The same AHB may participate in more than one fixed slot.
                // A completed older copy cannot release a newer pending copy.
            }
            return copyPending;
        } catch (...) {
            fatal_ = true;
            throw;
        }
    }

    void presentPrepared(const PreparedPresentation& prepared,
                         int outputReadySyncFd) {
        LiveSlot& slot = requirePrepared(prepared);
        if (slot.request.generated && outputReadySyncFd < -1)
            throw std::invalid_argument("generated output-ready FD is invalid");
        slot.readySyncFd = outputReadySyncFd;
        slot.state = LiveSlotState::AwaitingReady;
        ++pendingPresentations_;
    }

    void holdPrivatePrepared(const PreparedPresentation& prepared,
                             int outputReadySyncFd) {
        LiveSlot& slot = requirePrepared(prepared);
        if (outputReadySyncFd < -1)
            throw std::invalid_argument(
                    "private output-ready FD is invalid");
        slot.readySyncFd = outputReadySyncFd;
        slot.state = LiveSlotState::PrivateAwaitingReady;
    }

    uint32_t privatePreparedPairStatus(
            const PreparedPresentation& prepared) {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        if (prepared.slotIndex >= kFixedSlotCount)
            throw std::invalid_argument("owned private slot index is invalid");
        LiveSlot& slot = live_[prepared.slotIndex];
        if (slot.state == LiveSlotState::PrivateReady)
            return slot.privatePairStatus;
        try {
            if (slot.state == LiveSlotState::PrivateProofQueued) {
                const VkResult status = deviceFunctions_.vkGetFenceStatus(
                        device_, slot.presentFence);
                if (status == VK_NOT_READY) return 0;
                requireSuccess(status, "poll private content proof fence");
                if (!readyFdSignaled(slot)) return 0;
                // Kernel completion belongs to this exact copied/proved image,
                // not the later owner callback that noticed readiness. Keep it
                // after consuming the duplicate FD for the physical join.
                slot.gpuCompletionObservedNs = proofFenceTimestamp(slot);
                slot.privatePairStatus = slot.request.generated ?
                        analyzePrivatePairStatus(slot) : kPairReady;
                slot.state = LiveSlotState::PrivateReady;
                return slot.privatePairStatus;
            }
            if (slot.state != LiveSlotState::PrivateAwaitingReady)
                throw std::logic_error("owned private slot is not awaiting output");
            if (slot.readySyncFd < -1)
                throw std::logic_error("owned private output-ready FD is invalid");
            // A real pair's copy signal is already queued by this host. Import
            // that pending sync payload and let the GPU order proof after copy,
            // rather than adding a Choreographer interval while the CPU polls
            // before submitting the dependent command. Keep generated output's
            // external readiness gate unchanged. Neither path reports READY
            // until the proof fence and exact kernel signal pass below/above.
            if (slot.request.generated && !readyFdSignaled(slot)) return 0;
            recordSurfaceProof(slot);
            const bool waitForExternalReady = slot.readySyncFd >= 0;
            if (waitForExternalReady) {
                const VkImportSemaphoreFdInfoKHR import{
                    .sType = VK_STRUCTURE_TYPE_IMPORT_SEMAPHORE_FD_INFO_KHR,
                    .semaphore = slot.acquire,
                    .flags = VK_SEMAPHORE_IMPORT_TEMPORARY_BIT,
                    .handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT,
                    .fd = slot.readySyncFd,
                };
                requireSuccess(deviceFunctions_.vkImportSemaphoreFdKHR(
                        device_, &import),
                        "import private LSFG-ready sync FD for proof");
                slot.readySyncFd = -1;
            }
            const VkPipelineStageFlags waitStage = VK_PIPELINE_STAGE_TRANSFER_BIT;
            const VkSubmitInfo submit{
                .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                .waitSemaphoreCount = waitForExternalReady ? 1U : 0U,
                .pWaitSemaphores = waitForExternalReady ? &slot.acquire : nullptr,
                .pWaitDstStageMask = waitForExternalReady ? &waitStage : nullptr,
                .commandBufferCount = 1,
                .pCommandBuffers = &slot.presentCommand,
                .signalSemaphoreCount = 1,
                .pSignalSemaphores = &slot.render,
            };
            requireSuccess(deviceFunctions_.vkQueueSubmit(
                    queue_, 1, &submit, slot.presentFence),
                    "submit private content proof");
            // Submission owns proof resources before FD export/dup can fail.
            // Abandonment must not treat such an error as copy-only work.
            slot.privateProofPrepared = true;
            slot.state = LiveSlotState::PrivateProofQueued;
            const VkSemaphoreGetFdInfoKHR fdInfo{
                .sType = VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR,
                .semaphore = slot.render,
                .handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT,
            };
            int proofReadyFd = -1;
            requireSuccess(deviceFunctions_.vkGetSemaphoreFdKHR(
                    device_, &fdInfo, &proofReadyFd),
                    "export private proof-ready sync FD");
            slot.proofTimestampSyncFd = ::dup(proofReadyFd);
            if (slot.proofTimestampSyncFd < 0) {
                ::close(proofReadyFd);
                throw std::runtime_error("duplicate private proof fence failed");
            }
            slot.readySyncFd = proofReadyFd;
            return 0;
        } catch (...) {
            fatal_ = true;
            throw;
        }
    }

    bool activatePrivatePrepared(const PreparedPresentation& prepared,
                                 const LiveRequest& request) {
        validateLiveRequest(request);
        if (prepared.slotIndex >= kFixedSlotCount)
            throw std::invalid_argument("owned private slot index is invalid");
        LiveSlot& slot = live_[prepared.slotIndex];
        if (slot.state != LiveSlotState::PrivateReady || !slot.privateProofPrepared ||
                request.generated != slot.request.generated ||
                slot.request.left != request.left ||
                slot.request.right != request.right)
            throw std::logic_error(
                    "owned private output does not match visible request");
        // Until activation this is private GPU work, not a visible request.
        // Keep its exact pair, readiness and fences if this proposal expired.
        if (slot.gpuCompletionObservedNs == 0)
            throw std::logic_error("ready private image has no kernel proof signal");
        const uint64_t activationNs = monotonicNs();
        if (slot.gpuCompletionObservedNs > request.completionDeadlineNs ||
                activationNs >= request.completionDeadlineNs) return false;
        slot.request = request;
        slot.state = LiveSlotState::AwaitingReady;
        ++pendingPresentations_;
        // Keep startup detail, then sample into gameplay. The first observed
        // runtime underrun can occur after present32; startup-only timestamps
        // cannot explain that failure. Bound the additional log cost to16 rows.
        if (request.sessionEpoch > 0 && (request.presentId <= 32 ||
                (request.presentId <= 1920 && request.presentId % 120 == 0))) {
            LOGE("Private output activated presentId=%llu generated=%d "
                 "leftSequence=%llu rightSequence=%llu presentRight=%d "
                 "gpuStartNs=%llu gpuCompletionNs=%llu activationNs=%llu "
                 "completionDeadlineNs=%llu physicalTargetNs=%llu",
                 static_cast<unsigned long long>(request.presentId), request.generated ? 1 : 0,
                 static_cast<unsigned long long>(request.leftSequence),
                 static_cast<unsigned long long>(request.rightSequence), request.presentRight ? 1 : 0,
                 static_cast<unsigned long long>(slot.gpuStartNs),
                 static_cast<unsigned long long>(slot.gpuCompletionObservedNs),
                 static_cast<unsigned long long>(activationNs),
                 static_cast<unsigned long long>(request.completionDeadlineNs),
                 static_cast<unsigned long long>(request.physicalPresentTimeNs));
        }
        return true;
    }

    void abandonPrivatePrepared(const PreparedPresentation& prepared) {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        if (prepared.slotIndex >= kFixedSlotCount)
            throw std::invalid_argument("owned private slot index is invalid");
        LiveSlot& slot = live_[prepared.slotIndex];
        if (slot.state != LiveSlotState::PrivateAwaitingReady &&
                slot.state != LiveSlotState::PrivateProofQueued &&
                slot.state != LiveSlotState::PrivateReady)
            throw std::logic_error("owned private slot cannot be abandoned");
        slot.state = LiveSlotState::Abandoned;
        retireAbandonedCopies();
    }

    std::optional<SurfaceSubmission> pollSurfaceSubmission() {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        retireAbandonedCopies();
        // No later request can pass an expired output whose GPU ownership is
        // still being retired. This is a bounded ring barrier, not a timing
        // reanchor, retry, or additional queue of future presentation slots.
        for (const LiveSlot& candidate : live_) {
            if (candidate.state == LiveSlotState::SurfaceDroppedAwaitingReady)
                return std::nullopt;
        }
        LiveSlot* oldest = nullptr;
        for (LiveSlot& candidate : live_) {
            if (candidate.state != LiveSlotState::AwaitingReady) continue;
            if (oldest == nullptr ||
                    candidate.request.presentId < oldest->request.presentId)
                oldest = &candidate;
        }
        if (oldest == nullptr) return std::nullopt;
        LiveSlot& slot = *oldest;
        const uint64_t now = monotonicNs();
        if (now >= slot.request.completionDeadlineNs) {
            markSurfaceCutoffDrop(slot, now, 1);
            return std::nullopt;
        }
        if (!readyFdSignaled(slot)) return std::nullopt;
        const uint64_t readyPollNow = monotonicNs();
        if (readyPollNow >= slot.request.completionDeadlineNs) {
            markSurfaceCutoffDrop(slot, readyPollNow, 2);
            return std::nullopt;
        }
        try {
            if (slot.privateProofPrepared) {
                if (!readyFdSignaled(slot)) return std::nullopt;
                const int proofReadyFd = slot.readySyncFd;
                slot.readySyncFd = -1;
                slot.wsiPresentId = static_cast<uint32_t>(
                        slot.request.presentId);
                slot.state = LiveSlotState::SurfaceProofQueued;
                return SurfaceSubmission{
                    .slotIndex = static_cast<uint32_t>(&slot - live_.data()),
                    .buffer = selectedBuffer(slot),
                    .proofReadySyncFd = proofReadyFd,
                    .presentId = slot.request.presentId,
                    .physicalPresentTimeNs = slot.request.physicalPresentTimeNs,
                    .desiredPresentTimeNs = slot.request.desiredPresentTimeNs,
                    .compositorFrameTimelineVsyncId =
                            slot.request.compositorFrameTimelineVsyncId,
                    .compositorFrameTimelineExpectedNs =
                            slot.request.compositorFrameTimelineExpectedNs,
                    .compositorFrameTimelineDeadlineNs =
                            slot.request.compositorFrameTimelineDeadlineNs,
                    .refreshDurationNs = slot.request.refreshDurationNs,
                };
            }
            recordSurfaceProof(slot);
            const bool waitForExternalReady = slot.readySyncFd >= 0;
            if (waitForExternalReady) {
                const VkImportSemaphoreFdInfoKHR import{
                    .sType = VK_STRUCTURE_TYPE_IMPORT_SEMAPHORE_FD_INFO_KHR,
                    .semaphore = slot.acquire,
                    .flags = VK_SEMAPHORE_IMPORT_TEMPORARY_BIT,
                    .handleType =
                            VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT,
                    .fd = slot.readySyncFd,
                };
                requireSuccess(deviceFunctions_.vkImportSemaphoreFdKHR(
                        device_, &import),
                        "import LSFG-ready sync FD for proof");
                // A successful sync-FD import transfers ownership to Vulkan.
                slot.readySyncFd = -1;
            }
            const VkPipelineStageFlags waitStage =
                    VK_PIPELINE_STAGE_TRANSFER_BIT;
            const VkSubmitInfo submit{
                .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                .waitSemaphoreCount = waitForExternalReady ? 1U : 0U,
                .pWaitSemaphores = waitForExternalReady ?
                        &slot.acquire : nullptr,
                .pWaitDstStageMask = waitForExternalReady ?
                        &waitStage : nullptr,
                .commandBufferCount = 1,
                .pCommandBuffers = &slot.presentCommand,
                .signalSemaphoreCount = 1,
                .pSignalSemaphores = &slot.render,
            };
            requireSuccess(deviceFunctions_.vkQueueSubmit(
                    queue_, 1, &submit, slot.presentFence),
                    "submit owned SurfaceControl proof");
            const VkSemaphoreGetFdInfoKHR fdInfo{
                .sType = VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR,
                .semaphore = slot.render,
                .handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT,
            };
            int proofReadyFd = -1;
            requireSuccess(deviceFunctions_.vkGetSemaphoreFdKHR(
                    device_, &fdInfo, &proofReadyFd),
                    "export SurfaceControl proof-ready sync FD");
            slot.proofTimestampSyncFd = ::dup(proofReadyFd);
            if (slot.proofTimestampSyncFd < 0) {
                ::close(proofReadyFd);
                throw std::runtime_error(
                        "duplicate SurfaceControl proof fence failed");
            }
            slot.wsiPresentId = static_cast<uint32_t>(slot.request.presentId);
            slot.state = LiveSlotState::SurfaceProofQueued;
            return SurfaceSubmission{
                .slotIndex = static_cast<uint32_t>(&slot - live_.data()),
                .buffer = selectedBuffer(slot),
                .proofReadySyncFd = proofReadyFd,
                .presentId = slot.request.presentId,
                .physicalPresentTimeNs = slot.request.physicalPresentTimeNs,
                .desiredPresentTimeNs = slot.request.desiredPresentTimeNs,
                .compositorFrameTimelineVsyncId =
                        slot.request.compositorFrameTimelineVsyncId,
                .compositorFrameTimelineExpectedNs =
                        slot.request.compositorFrameTimelineExpectedNs,
                .compositorFrameTimelineDeadlineNs =
                        slot.request.compositorFrameTimelineDeadlineNs,
                .refreshDurationNs = slot.request.refreshDurationNs,
            };
        } catch (...) {
            fatal_ = true;
            throw;
        }
    }

    std::optional<Completion> pollSurfaceCompletion(
            uint64_t presentId, uint64_t desiredPresentTimeNs,
            uint64_t latchTimeNs, uint64_t actualPresentTimeNs) {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        LiveSlot* slot = findSurfaceSlot(
                presentId, LiveSlotState::SurfaceProofQueued);
        if (slot == nullptr)
            throw std::runtime_error("unknown SurfaceControl completion identity");
        // The driver's not-before bound remains the same with or without an
        // AVsyncId. The separate physical target is never relabelled as it.
        const uint64_t expectedSurfaceDesiredNs =
                slot->request.desiredPresentTimeNs;
        if (desiredPresentTimeNs != expectedSurfaceDesiredNs ||
                latchTimeNs == 0 || actualPresentTimeNs < latchTimeNs)
            throw std::runtime_error("SurfaceControl physical row is invalid");
        const VkResult fenceStatus = deviceFunctions_.vkGetFenceStatus(
                device_, slot->presentFence);
        if (fenceStatus == VK_NOT_READY) return std::nullopt;
        requireSuccess(fenceStatus, "poll owned SurfaceControl proof fence");
        if (!slot->privateProofPrepared)
            slot->gpuCompletionObservedNs = proofFenceTimestamp(*slot);
        if (slot->gpuCompletionObservedNs == 0 ||
                slot->gpuCompletionObservedNs >
                        slot->request.completionDeadlineNs) {
            fatal_ = true;
            throw std::runtime_error(
                    "SurfaceControl proof missed its immutable completion deadline"
                    " presentId=" + std::to_string(slot->request.presentId) +
                    " gpuCompletionNs=" + std::to_string(slot->gpuCompletionObservedNs) +
                    " completionDeadlineNs=" +
                            std::to_string(slot->request.completionDeadlineNs) +
                    " gpuStartNs=" + std::to_string(slot->gpuStartNs) +
                    " generated=" + std::to_string(slot->request.generated ? 1 : 0));
        }
        const VkPastPresentationTimingGOOGLE physical{
            .presentID = slot->wsiPresentId,
            .desiredPresentTime = slot->request.desiredPresentTimeNs,
            .actualPresentTime = actualPresentTimeNs,
            .earliestPresentTime = latchTimeNs,
            .presentMargin = actualPresentTimeNs >= desiredPresentTimeNs ?
                    actualPresentTimeNs - desiredPresentTimeNs : 0,
        };
        Completion completion = analyzeCompletion(*slot, physical);
        completeTripletCapture(*slot, completion);
        slot->state = LiveSlotState::SurfaceDeliveredAwaitingRelease;
        return completion;
    }

    void dropSurfacePresentation(uint64_t presentId) {
        LiveSlot* slot = findSurfaceSlot(
                presentId, LiveSlotState::SurfaceProofQueued);
        if (slot == nullptr)
            throw std::runtime_error(
                    "unknown rejected SurfaceControl presentation identity");
        slot->state = LiveSlotState::SurfaceDroppedAwaitingProof;
    }

    std::optional<Completion> pollDroppedSurfacePresentation() {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        LiveSlot* oldest = nullptr;
        for (LiveSlot& candidate : live_) {
            if (candidate.state !=
                    LiveSlotState::SurfaceDroppedAwaitingProof &&
                    candidate.state !=
                            LiveSlotState::SurfaceDroppedAwaitingReady) continue;
            if (oldest == nullptr ||
                    candidate.request.presentId < oldest->request.presentId)
                oldest = &candidate;
        }
        if (oldest == nullptr) return std::nullopt;
        try {
            if (oldest->state == LiveSlotState::SurfaceDroppedAwaitingReady) {
                const DropDrainObservation observed = observeDropDrain(*oldest);
                const uint64_t now = monotonicNs();
                if (!observed.ready()) {
                    if (now < oldest->cutoffObservedNs ||
                            now - oldest->cutoffObservedNs >= kDroppedDrainTimeoutNs) {
                        logSurfaceCutoffDrop(*oldest, "quarantine", now, observed);
                        throw std::runtime_error(
                                "dropped LSFG request did not retire within drain bound");
                    }
                    return std::nullopt;
                }
                logSurfaceCutoffDrop(*oldest, "retired", now, observed);
            } else {
                const VkResult fenceStatus = deviceFunctions_.vkGetFenceStatus(
                        device_, oldest->presentFence);
                if (fenceStatus == VK_NOT_READY) return std::nullopt;
                requireSuccess(fenceStatus,
                        "poll rejected SurfaceControl proof fence");
            }
        } catch (...) {
            // Unknown completion/device loss is an ownership failure, unlike
            // the already-recorded missed visible deadline. Never recycle it.
            if (oldest->cutoffDropOrdinal != 0)
                logSurfaceCutoffDrop(*oldest, "quarantine", monotonicNs(), {});
            fatal_ = true;
            throw;
        }
        if (pendingPresentations_ == 0) {
            fatal_ = true;
            throw std::logic_error("owned pending presentation underflow");
        }
        Completion result{
            .dropped = true,
            .presentId = oldest->request.presentId,
            .desiredPresentTimeNs = oldest->request.desiredPresentTimeNs,
            .refreshDurationNs = oldest->request.refreshDurationNs,
        };
        if (oldest->cutoffDropOrdinal != 0) ++surfaceCutoffRetired_;
        resetLiveSlotStorage(*oldest);
        --pendingPresentations_;
        return result;
    }

    uint64_t oldestPendingSurfacePresentId() const {
        uint64_t oldest = 0;
        for (const LiveSlot& slot : live_) {
            if (slot.state != LiveSlotState::AwaitingReady &&
                    slot.state != LiveSlotState::SurfaceProofQueued &&
                    slot.state != LiveSlotState::SurfaceDroppedAwaitingReady &&
                    slot.state != LiveSlotState::SurfaceDroppedAwaitingProof)
                continue;
            if (slot.request.presentId == 0)
                throw std::logic_error("visible slot lost its presentation identity");
            if (oldest == 0 || slot.request.presentId < oldest)
                oldest = slot.request.presentId;
        }
        return oldest;
    }

    void retireSurfacePresentation(uint64_t presentId) {
        LiveSlot* slot = findSurfaceSlot(
                presentId, LiveSlotState::SurfaceDeliveredAwaitingRelease);
        if (slot == nullptr)
            throw std::runtime_error("SurfaceControl slot retired out of order");
        resetLiveSlotStorage(*slot);
        if (pendingPresentations_ == 0)
            throw std::logic_error("owned pending presentation underflow");
        --pendingPresentations_;
    }

    void abandonPrepared(const PreparedPresentation& prepared) {
        LiveSlot& slot = requirePrepared(prepared);
        if (prepared.inputReadySyncFd >= 0) ::close(prepared.inputReadySyncFd);
        slot.state = LiveSlotState::Abandoned;
    }

    std::optional<Completion> pollCompletion() {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        retireAbandonedCopies();
        progressReadyPresentations();
        collectPastPresentationTimings();
        LiveSlot* oldest = nullptr;
        for (LiveSlot& candidate : live_) {
            if (candidate.state != LiveSlotState::AwaitingReady &&
                    candidate.state != LiveSlotState::Presented) continue;
            if (oldest == nullptr ||
                    candidate.request.presentId < oldest->request.presentId)
                oldest = &candidate;
        }
        if (oldest == nullptr || oldest->state != LiveSlotState::Presented)
            return std::nullopt;
        const VkResult fenceStatus = deviceFunctions_.vkGetFenceStatus(
                device_, oldest->presentFence);
        if (fenceStatus == VK_NOT_READY) return std::nullopt;
        requireSuccess(fenceStatus, "poll owned presentation fence");
        if (oldest->gpuCompletionObservedNs == 0)
            oldest->gpuCompletionObservedNs = monotonicNs();
        const auto timing = completedTimings_.find(oldest->wsiPresentId);
        if (timing == completedTimings_.end()) return std::nullopt;
        Completion completion = analyzeCompletion(*oldest, timing->second);
        completeTripletCapture(*oldest, completion);
        completedTimings_.erase(timing);
        resetLiveSlotStorage(*oldest);
        if (pendingPresentations_ == 0)
            throw std::logic_error("owned pending presentation underflow");
        --pendingPresentations_;
        return completion;
    }

    void resetTimeline(uint64_t presentationEpoch) {
        if (presentationEpoch == 0)
            throw std::invalid_argument("owned presentation epoch is zero");
        presentationEpoch_ = presentationEpoch;
    }

    const Capabilities& capabilities() const { return capabilities_; }

    std::string capabilityJson() const {
        std::ostringstream record;
        record << "{\"deviceKey\":" << capabilities_.deviceKey
               << ",\"apiVersion\":" << capabilities_.apiVersion
               << ",\"queueFamily\":" << capabilities_.queueFamily
               << ",\"swapchainWidth\":" << capabilities_.swapchainWidth
               << ",\"swapchainHeight\":" << capabilities_.swapchainHeight
               << ",\"swapchainImageCount\":" << capabilities_.swapchainImageCount
               << ",\"swapchainFormat\":" << static_cast<int>(capabilities_.swapchainFormat)
               << ",\"presentMode\":" << static_cast<int>(capabilities_.presentMode)
               << ",\"refreshDurationNs\":" << capabilities_.refreshDurationNs
               << ",\"sameGraphicsPresentQueue\":"
               << (capabilities_.sameGraphicsPresentQueue ? "true" : "false")
               << ",\"displayTiming\":"
               << (capabilities_.displayTiming ? "true" : "false")
               << ",\"externalSyncFd\":"
               << (capabilities_.externalSyncFd ? "true" : "false")
               << ",\"fixedBuffersImported\":"
               << (capabilities_.fixedBuffersImported ? "true" : "false")
               << ",\"setupOwnershipReleased\":"
               << (capabilities_.setupOwnershipReleased ? "true" : "false")
               << ",\"liveResourcesReady\":"
               << (capabilities_.liveResourcesReady ? "true" : "false")
               << '}';
        return record.str();
    }

    std::string diagnosticJson() const {
        uint32_t idle = 0;
        uint32_t copyQueued = 0;
        uint32_t privateAwaitingReady = 0;
        uint32_t privateProofQueued = 0;
        uint32_t privateReady = 0;
        uint32_t abandoned = 0;
        uint32_t awaitingReady = 0;
        uint32_t presented = 0;
        uint32_t surfaceProofQueued = 0;
        uint32_t surfaceDroppedAwaitingReady = 0;
        uint32_t surfaceAwaitingRelease = 0;
        uint32_t presentFenceReady = 0;
        uint32_t presentFenceNotReady = 0;
        uint32_t presentFenceError = 0;
        for (const LiveSlot& slot : live_) {
            switch (slot.state) {
                case LiveSlotState::Idle: ++idle; break;
                case LiveSlotState::CopyQueued: ++copyQueued; break;
                case LiveSlotState::PrivateAwaitingReady:
                    ++privateAwaitingReady; break;
                case LiveSlotState::PrivateProofQueued:
                    ++privateProofQueued; break;
                case LiveSlotState::PrivateReady: ++privateReady; break;
                case LiveSlotState::Abandoned: ++abandoned; break;
                case LiveSlotState::AwaitingReady: ++awaitingReady; break;
                case LiveSlotState::Presented:
                    ++presented;
                    if (slot.presentFence == VK_NULL_HANDLE ||
                            device_ == VK_NULL_HANDLE) {
                        ++presentFenceError;
                    } else {
                        const VkResult status = deviceFunctions_.vkGetFenceStatus(
                                device_, slot.presentFence);
                        if (status == VK_SUCCESS) ++presentFenceReady;
                        else if (status == VK_NOT_READY) ++presentFenceNotReady;
                        else ++presentFenceError;
                    }
                    break;
                case LiveSlotState::SurfaceProofQueued:
                    ++surfaceProofQueued;
                    break;
                case LiveSlotState::SurfaceDroppedAwaitingProof:
                    ++surfaceProofQueued;
                    break;
                case LiveSlotState::SurfaceDroppedAwaitingReady:
                    ++surfaceDroppedAwaitingReady;
                    break;
                case LiveSlotState::SurfaceDeliveredAwaitingRelease:
                    ++surfaceAwaitingRelease;
                    break;
            }
        }
        const auto capture = tripletWriter_ ? tripletWriter_->stats() : TripletCaptureWriter::Stats{};
        std::ostringstream record;
        record << "{\"pending\":" << pendingPresentations_
               << ",\"idle\":" << idle
               << ",\"copyQueued\":" << copyQueued
               << ",\"privateAwaitingReady\":" << privateAwaitingReady
               << ",\"privateProofQueued\":" << privateProofQueued
               << ",\"privateReady\":" << privateReady
               << ",\"abandoned\":" << abandoned
               << ",\"awaitingReady\":" << awaitingReady
               << ",\"presented\":" << presented
               << ",\"surfaceProofQueued\":" << surfaceProofQueued
               << ",\"surfaceDroppedAwaitingReady\":" << surfaceDroppedAwaitingReady
               << ",\"surfaceCutoffDrops\":" << surfaceCutoffDrops_
               << ",\"surfaceCutoffRetired\":" << surfaceCutoffRetired_
               << ",\"surfaceAwaitingRelease\":"
               << surfaceAwaitingRelease
               << ",\"presentFenceReady\":" << presentFenceReady
               << ",\"presentFenceNotReady\":" << presentFenceNotReady
               << ",\"presentFenceError\":" << presentFenceError
               << ",\"pastTimingQueries\":" << pastTimingQueries_
               << ",\"pastTimingNonzeroQueries\":"
               << pastTimingNonzeroQueries_
               << ",\"pastTimingRecords\":" << pastTimingRecords_
               << ",\"joinedTimingRecords\":" << completedTimings_.size()
               << ",\"captureEnabled\":" << (tripletWriter_ ? "true" : "false")
               << ",\"captureSelected\":" << capture.selected
               << ",\"captureSkippedBusy\":" << capture.skippedBusy
               << ",\"captureWritten\":" << capture.completed
               << ",\"captureWriteFailures\":" << capture.failed
               << ",\"captureDiscarded\":" << capture.discarded
               << ",\"fatal\":" << (fatal_ ? "true" : "false")
               << '}';
        return record.str();
    }

private:
    void initializeTripletCapture() noexcept {
        // One setup-only probe, no frame-loop marker polling. Missing marker
        // means no allocation, writer thread, copy command, or CPU readback.
        constexpr const char* marker = "/data/user/0/com.thorium.preview/files/lsfg-triplet-capture.arm";
        const int fd = ::open(marker, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
        if (fd < 0) return;
        struct stat markerStatus{};
        if (::fstat(fd, &markerStatus) != 0 || !S_ISREG(markerStatus.st_mode) || markerStatus.st_size > 63) {
            ::close(fd);
            LOGE("LSFG capture setup failed: arm must be a small regular file");
            return;
        }
        char config[64]{};
        const ssize_t length = ::read(fd, config, sizeof(config) - 1);
        ::close(fd);
        unsigned count = 0, skip = 0, every = 1, delay = 0;
        std::istringstream values(config);
        std::array<unsigned, 4> parsed{0, 0, 1, 0};
        size_t parsedCount = 0;
        unsigned value = 0;
        while (parsedCount < parsed.size() && values >> value) parsed[parsedCount++] = value;
        values.clear();
        values >> std::ws;
        const bool consumed = values.eof();
        count = parsed[0]; skip = parsed[1]; every = parsed[2]; delay = parsed[3];
        if (length <= 0 || parsedCount == 0 || !consumed ||
                count == 0 || count > TripletCaptureWriter::kMaximumCaptures || skip > 100000 ||
                every == 0 || every > 100000 || delay > 3600) {
            LOGE("LSFG capture setup failed: count(1..8) skipPairs(0..100000) everyPairs(1..100000) delaySeconds(0..3600)");
            return;
        }
        try {
            captureBytes_ = TripletCaptureWriter::checkedBytes(endpointExtent_.width, endpointExtent_.height);
            const VkBufferCreateInfo create{
                .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                .size = captureBytes_,
                .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
            };
            requireSuccess(deviceFunctions_.vkCreateBuffer(device_, &create, nullptr, &captureBuffer_),
                           "create opt-in triplet buffer");
            VkMemoryRequirements requirements{};
            deviceFunctions_.vkGetBufferMemoryRequirements(device_, captureBuffer_, &requirements);
            if (requirements.size > TripletCaptureWriter::kMaximumBytes)
                throw std::runtime_error("triplet memory alignment exceeds 64 MiB bound");
            const uint32_t type = memoryType(requirements.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,
                                             VK_MEMORY_PROPERTY_HOST_CACHED_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
            captureCoherent_ = (memoryProperties_.memoryTypes[type].propertyFlags &
                                VK_MEMORY_PROPERTY_HOST_COHERENT_BIT) != 0;
            const VkMemoryAllocateInfo allocate{
                .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                .allocationSize = requirements.size,
                .memoryTypeIndex = type,
            };
            requireSuccess(deviceFunctions_.vkAllocateMemory(device_, &allocate, nullptr, &captureMemory_),
                           "allocate opt-in triplet memory");
            requireSuccess(deviceFunctions_.vkBindBufferMemory(device_, captureBuffer_, captureMemory_, 0),
                           "bind opt-in triplet memory");
            requireSuccess(deviceFunctions_.vkMapMemory(device_, captureMemory_, 0, VK_WHOLE_SIZE, 0, &captureMapped_),
                           "map opt-in triplet memory");
            const char* root = "/data/user/0/com.thorium.preview/files/lsfg-captures";
            struct stat status{};
            if (::mkdir(root, 0700) != 0 && errno != EEXIST)
                throw std::runtime_error("cannot create private LSFG capture root");
            if (::lstat(root, &status) != 0 || !S_ISDIR(status.st_mode))
                throw std::runtime_error("private LSFG capture root is not a directory");
            const std::string directory = std::string(root) + "/session-" +
                    std::to_string(::getpid()) + "-" + std::to_string(monotonicNs());
            captureNotBeforeNs_ = monotonicNs() + static_cast<uint64_t>(delay) * 1000000000ULL;
            tripletWriter_ = std::make_unique<TripletCaptureWriter>(
                    static_cast<const uint8_t*>(captureMapped_), endpointExtent_.width, endpointExtent_.height,
                    count, skip, every, directory, [this] {
                        // Worker-only, after a signaled fence and physical join.
                        // This mapping cannot be reused or freed until the writer
                        // returns to Idle (or teardown joins it).
                        if (captureCoherent_) return true;
                        const VkMappedMemoryRange range{
                            .sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,
                            .memory = captureMemory_, .offset = 0, .size = VK_WHOLE_SIZE,
                        };
                        return deviceFunctions_.vkInvalidateMappedMemoryRanges(device_, 1, &range) == VK_SUCCESS;
                    }, [](const std::string& text) { LOGE("%s", text.c_str()); });
            // The first successfully initialized owner consumes this opt-in.
            if (::unlink(marker) != 0) LOGE("LSFG capture arm consumption failed errno=%d", errno);
            LOGE("LSFG capture armed count=%u skipPairs=%u everyPairs=%u delaySeconds=%u bytes=%llu directory=%s instrumentation=1",
                 count, skip, every, delay, static_cast<unsigned long long>(captureBytes_), directory.c_str());
        } catch (const std::exception& error) {
            LOGE("LSFG capture setup failed (generation unchanged): %s", error.what());
            destroyTripletCapture();
        }
    }

    void recordTripletCapture(LiveSlot& slot, const ImportedSlot& fixed) {
        if (!tripletWriter_ || !slot.request.generated ||
                (slot.state != LiveSlotState::PrivateAwaitingReady && slot.request.sessionEpoch == 0)) return;
        if (monotonicNs() < captureNotBeforeNs_) return;
        slot.fullCaptureId = tripletWriter_->reserve();
        if (slot.fullCaptureId == 0) return;
        const VkBufferMemoryBarrier begin{
            .sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_HOST_READ_BIT,
            .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .buffer = captureBuffer_, .offset = 0, .size = captureBytes_,
        };
        deviceFunctions_.vkCmdPipelineBarrier(slot.presentCommand, VK_PIPELINE_STAGE_HOST_BIT,
                VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 1, &begin, 0, nullptr);
        const std::array<VkImage, 3> images{fixed.left.image, fixed.output.image, fixed.right.image};
        for (uint32_t index = 0; index < images.size(); ++index) {
            const VkBufferImageCopy copy{
                .bufferOffset = (captureBytes_ / 3) * index,
                .bufferRowLength = 0, .bufferImageHeight = 0,
                .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                .imageOffset = {0, 0, 0},
                .imageExtent = {endpointExtent_.width, endpointExtent_.height, 1},
            };
            // Exact bytes: no blit, resize, shader, colorspace, or pixel edit.
            deviceFunctions_.vkCmdCopyImageToBuffer(slot.presentCommand, images[index],
                    VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, captureBuffer_, 1, &copy);
        }
        const VkBufferMemoryBarrier end{
            .sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .buffer = captureBuffer_, .offset = 0, .size = captureBytes_,
        };
        deviceFunctions_.vkCmdPipelineBarrier(slot.presentCommand, VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_HOST_BIT, 0, 0, nullptr, 1, &end, 0, nullptr);
    }

    void completeTripletCapture(LiveSlot& slot, const Completion& completion) {
        if (!tripletWriter_ || slot.fullCaptureId == 0) return;
        const LiveRequest& request = slot.request;
        const TripletCaptureWriter::Identity identity{
            .sessionEpoch = request.sessionEpoch, .presentationEpoch = request.presentationEpoch,
            .leftSequence = request.leftSequence, .rightSequence = request.rightSequence,
            .leftTimestampNs = request.leftTimestampNs, .rightTimestampNs = request.rightTimestampNs,
            .contentTimestampNs = request.contentTimestampNs, .presentId = request.presentId,
            .desiredPresentNs = request.physicalPresentTimeNs,
            .actualPresentNs = completion.actualPresentTimeNs,
            .gpuCompletionNs = slot.gpuCompletionObservedNs,
            .refreshDurationNs = request.refreshDurationNs,
            .captureNotBeforeNs = captureNotBeforeNs_,
            .endpointMadPpm = completion.endpointMadPpm,
        };
        if (!tripletWriter_->submit(slot.fullCaptureId, identity))
            LOGE("LSFG capture submission rejected id=%llu", static_cast<unsigned long long>(slot.fullCaptureId));
        slot.fullCaptureId = 0; // Independent staging memory now belongs to writer.
    }

    void destroyTripletCapture() noexcept {
        if (tripletWriter_) {
            tripletWriter_->close(); // Teardown only, before mapped memory release.
            const auto count = tripletWriter_->stats();
            LOGE("LSFG capture totals selected=%llu busy=%llu written=%llu failed=%llu discarded=%llu",
                 static_cast<unsigned long long>(count.selected), static_cast<unsigned long long>(count.skippedBusy),
                 static_cast<unsigned long long>(count.completed), static_cast<unsigned long long>(count.failed),
                 static_cast<unsigned long long>(count.discarded));
            tripletWriter_.reset();
        }
        if (captureMapped_) deviceFunctions_.vkUnmapMemory(device_, captureMemory_);
        if (captureBuffer_) deviceFunctions_.vkDestroyBuffer(device_, captureBuffer_, nullptr);
        if (captureMemory_) deviceFunctions_.vkFreeMemory(device_, captureMemory_, nullptr);
        captureMapped_ = nullptr;
        captureBuffer_ = VK_NULL_HANDLE;
        captureMemory_ = VK_NULL_HANDLE;
        captureBytes_ = 0;
    }

    void loadInstanceFunctions() {
        createAndroidSurface_ = reinterpret_cast<PFN_vkCreateAndroidSurfaceKHR>(
                vkGetInstanceProcAddr(instance_, "vkCreateAndroidSurfaceKHR"));
        destroyInstance_ = reinterpret_cast<PFN_vkDestroyInstance>(
                vkGetInstanceProcAddr(instance_, "vkDestroyInstance"));
        destroySurface_ = reinterpret_cast<PFN_vkDestroySurfaceKHR>(
                vkGetInstanceProcAddr(instance_, "vkDestroySurfaceKHR"));
        surfaceSupport_ = reinterpret_cast<PFN_vkGetPhysicalDeviceSurfaceSupportKHR>(
                vkGetInstanceProcAddr(instance_, "vkGetPhysicalDeviceSurfaceSupportKHR"));
        surfaceCapabilities_ =
                reinterpret_cast<PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR>(
                vkGetInstanceProcAddr(instance_,
                                      "vkGetPhysicalDeviceSurfaceCapabilitiesKHR"));
        surfaceFormats_ = reinterpret_cast<PFN_vkGetPhysicalDeviceSurfaceFormatsKHR>(
                vkGetInstanceProcAddr(instance_, "vkGetPhysicalDeviceSurfaceFormatsKHR"));
        surfacePresentModes_ =
                reinterpret_cast<PFN_vkGetPhysicalDeviceSurfacePresentModesKHR>(
                vkGetInstanceProcAddr(instance_,
                                      "vkGetPhysicalDeviceSurfacePresentModesKHR"));
        if (createAndroidSurface_ == nullptr || destroyInstance_ == nullptr ||
                destroySurface_ == nullptr ||
                surfaceSupport_ == nullptr || surfaceCapabilities_ == nullptr ||
                surfaceFormats_ == nullptr || surfacePresentModes_ == nullptr) {
            throw std::runtime_error("owned Vulkan WSI instance functions unavailable");
        }
    }

    void choosePhysicalDeviceAndQueue() {
        uint32_t deviceCount = 0;
        requireSuccess(vkEnumeratePhysicalDevices(instance_, &deviceCount, nullptr),
                       "enumerate owned Vulkan devices");
        if (deviceCount == 0) throw std::runtime_error("no Vulkan physical device");
        std::vector<VkPhysicalDevice> devices(deviceCount);
        requireSuccess(vkEnumeratePhysicalDevices(instance_, &deviceCount,
                                                   devices.data()),
                       "read owned Vulkan devices");

        const std::array<const char*, 12> requiredDevice = {
            VK_KHR_EXTERNAL_MEMORY_EXTENSION_NAME,
            VK_KHR_EXTERNAL_SEMAPHORE_EXTENSION_NAME,
            VK_KHR_EXTERNAL_SEMAPHORE_FD_EXTENSION_NAME,
            VK_ANDROID_EXTERNAL_MEMORY_ANDROID_HARDWARE_BUFFER_EXTENSION_NAME,
            VK_KHR_SAMPLER_YCBCR_CONVERSION_EXTENSION_NAME,
            VK_KHR_DEDICATED_ALLOCATION_EXTENSION_NAME,
            VK_KHR_GET_MEMORY_REQUIREMENTS_2_EXTENSION_NAME,
            VK_KHR_BIND_MEMORY_2_EXTENSION_NAME,
            VK_KHR_MAINTENANCE1_EXTENSION_NAME,
            VK_KHR_SWAPCHAIN_EXTENSION_NAME,
            VK_GOOGLE_DISPLAY_TIMING_EXTENSION_NAME,
            VK_EXT_QUEUE_FAMILY_FOREIGN_EXTENSION_NAME,
        };
        for (VkPhysicalDevice candidate : devices) {
            const auto extensions = deviceExtensions(candidate);
            bool allExtensions = true;
            for (const char* name : requiredDevice) {
                if (!hasExtension(extensions, name)) {
                    allExtensions = false;
                    break;
                }
            }
            if (!allExtensions) continue;

            uint32_t queueCount = 0;
            vkGetPhysicalDeviceQueueFamilyProperties(candidate, &queueCount, nullptr);
            std::vector<VkQueueFamilyProperties> queues(queueCount);
            vkGetPhysicalDeviceQueueFamilyProperties(candidate, &queueCount,
                                                      queues.data());
            for (uint32_t index = 0; index < queueCount; ++index) {
                VkBool32 present = VK_FALSE;
                if (surfaceSupport_(candidate, index, surface_, &present) != VK_SUCCESS ||
                        present != VK_TRUE) continue;
                // Vulkan guarantees transfer commands on graphics queues;
                // advertising VK_QUEUE_TRANSFER_BIT separately is optional.
                // Adreno 740 correctly omits that redundant flag on its
                // graphics/present family (0x9b), so requiring the bit would
                // reject a queue that supports every command used here.
                const VkQueueFlags required = VK_QUEUE_GRAPHICS_BIT;
                if ((queues[index].queueFlags & required) != required) continue;
                physicalDevice_ = candidate;
                queueFamily_ = index;
                requiredDeviceExtensions_.assign(requiredDevice.begin(),
                                                  requiredDevice.end());
                break;
            }
            if (physicalDevice_ != VK_NULL_HANDLE) break;
        }
        if (physicalDevice_ == VK_NULL_HANDLE)
            throw std::runtime_error(
                    "no Vulkan device has AHB, sync-FD, FIFO timing, and present support");

        VkPhysicalDeviceProperties properties{};
        vkGetPhysicalDeviceProperties(physicalDevice_, &properties);
        vkGetPhysicalDeviceMemoryProperties(physicalDevice_, &memoryProperties_);
        capabilities_.deviceKey =
                (static_cast<uint64_t>(properties.vendorID) << 32U) |
                static_cast<uint64_t>(properties.deviceID);
        capabilities_.apiVersion = properties.apiVersion;
        capabilities_.queueFamily = queueFamily_;
        capabilities_.sameGraphicsPresentQueue = true;
        capabilities_.displayTiming = true;
        capabilities_.externalSyncFd = true;
    }

    void createDevice() {
        VkPhysicalDeviceSamplerYcbcrConversionFeatures ycbcrQuery{
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SAMPLER_YCBCR_CONVERSION_FEATURES,
        };
        VkPhysicalDeviceFeatures2 featuresQuery{
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2,
            .pNext = &ycbcrQuery,
        };
        vkGetPhysicalDeviceFeatures2(physicalDevice_, &featuresQuery);
        if (ycbcrQuery.samplerYcbcrConversion != VK_TRUE)
            throw std::runtime_error("sampler YCbCr conversion feature unavailable");

        const float priority = 1.0F;
        const VkDeviceQueueCreateInfo queueCreate{
            .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
            .queueFamilyIndex = queueFamily_,
            .queueCount = 1,
            .pQueuePriorities = &priority,
        };
        VkPhysicalDeviceSamplerYcbcrConversionFeatures ycbcrEnable{
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SAMPLER_YCBCR_CONVERSION_FEATURES,
            .samplerYcbcrConversion = VK_TRUE,
        };
        const VkDeviceCreateInfo deviceCreate{
            .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
            .pNext = &ycbcrEnable,
            .queueCreateInfoCount = 1,
            .pQueueCreateInfos = &queueCreate,
            .enabledExtensionCount =
                    static_cast<uint32_t>(requiredDeviceExtensions_.size()),
            .ppEnabledExtensionNames = requiredDeviceExtensions_.data(),
        };
        requireSuccess(vkCreateDevice(physicalDevice_, &deviceCreate, nullptr,
                                      &device_),
                       "create owned Vulkan device");
        volkLoadDeviceTable(&deviceFunctions_, device_);
        deviceFunctions_.vkGetDeviceQueue(device_, queueFamily_, 0, &queue_);
        std::ostringstream missing;
        if (queue_ == VK_NULL_HANDLE) missing << " queue";
        if (deviceFunctions_.vkGetAndroidHardwareBufferPropertiesANDROID == nullptr)
            missing << " vkGetAndroidHardwareBufferPropertiesANDROID";
        if (deviceFunctions_.vkImportSemaphoreFdKHR == nullptr)
            missing << " vkImportSemaphoreFdKHR";
        if (deviceFunctions_.vkGetSemaphoreFdKHR == nullptr)
            missing << " vkGetSemaphoreFdKHR";
        if (deviceFunctions_.vkCreateSwapchainKHR == nullptr)
            missing << " vkCreateSwapchainKHR";
        if (deviceFunctions_.vkGetRefreshCycleDurationGOOGLE == nullptr)
            missing << " vkGetRefreshCycleDurationGOOGLE";
        if (deviceFunctions_.vkGetPastPresentationTimingGOOGLE == nullptr)
            missing << " vkGetPastPresentationTimingGOOGLE";
        if (!missing.str().empty())
            throw std::runtime_error(
                    "owned Vulkan device entry points unavailable:" + missing.str());
    }

    void createSwapchain() {
        VkSurfaceCapabilitiesKHR surfaceCapabilities{};
        requireSuccess(surfaceCapabilities_(physicalDevice_, surface_,
                                            &surfaceCapabilities),
                       "query owned surface capabilities");
        if ((surfaceCapabilities.supportedUsageFlags &
             VK_IMAGE_USAGE_TRANSFER_DST_BIT) == 0U) {
            throw std::runtime_error("owned surface lacks transfer-destination usage");
        }

        uint32_t formatCount = 0;
        requireSuccess(surfaceFormats_(physicalDevice_, surface_, &formatCount, nullptr),
                       "count owned surface formats");
        if (formatCount == 0) throw std::runtime_error("owned surface has no formats");
        std::vector<VkSurfaceFormatKHR> formats(formatCount);
        requireSuccess(surfaceFormats_(physicalDevice_, surface_, &formatCount,
                                       formats.data()),
                       "read owned surface formats");
        VkSurfaceFormatKHR chosen = formats.front();
        for (const VkSurfaceFormatKHR& format : formats) {
            if (format.format == VK_FORMAT_R8G8B8A8_UNORM ||
                    format.format == VK_FORMAT_B8G8R8A8_UNORM) {
                chosen = format;
                break;
            }
        }
        if (chosen.format != VK_FORMAT_R8G8B8A8_UNORM &&
                chosen.format != VK_FORMAT_B8G8R8A8_UNORM) {
            throw std::runtime_error("owned surface has no RGBA8/BGRA8 format");
        }

        uint32_t modeCount = 0;
        requireSuccess(surfacePresentModes_(physicalDevice_, surface_, &modeCount,
                                            nullptr),
                       "count owned present modes");
        std::vector<VkPresentModeKHR> modes(modeCount);
        requireSuccess(surfacePresentModes_(physicalDevice_, surface_, &modeCount,
                                            modes.data()),
                       "read owned present modes");
        if (std::find(modes.begin(), modes.end(), VK_PRESENT_MODE_FIFO_KHR) ==
                modes.end()) {
            throw std::runtime_error("owned surface does not expose FIFO present mode");
        }

        VkExtent2D extent = surfaceCapabilities.currentExtent;
        if (extent.width == std::numeric_limits<uint32_t>::max()) {
            extent.width = std::clamp(endpointExtent_.width,
                                      surfaceCapabilities.minImageExtent.width,
                                      surfaceCapabilities.maxImageExtent.width);
            extent.height = std::clamp(endpointExtent_.height,
                                       surfaceCapabilities.minImageExtent.height,
                                       surfaceCapabilities.maxImageExtent.height);
        }
        uint32_t imageCount = surfaceCapabilities.minImageCount + 1U;
        if (surfaceCapabilities.maxImageCount > 0)
            imageCount = std::min(imageCount, surfaceCapabilities.maxImageCount);
        const VkSwapchainCreateInfoKHR swapchainCreate{
            .sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,
            .surface = surface_,
            .minImageCount = imageCount,
            .imageFormat = chosen.format,
            .imageColorSpace = chosen.colorSpace,
            .imageExtent = extent,
            .imageArrayLayers = 1,
            .imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT,
            .imageSharingMode = VK_SHARING_MODE_EXCLUSIVE,
            .preTransform = surfaceCapabilities.currentTransform,
            .compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR,
            .presentMode = VK_PRESENT_MODE_FIFO_KHR,
            .clipped = VK_TRUE,
        };
        requireSuccess(deviceFunctions_.vkCreateSwapchainKHR(
                device_, &swapchainCreate, nullptr, &swapchain_),
                       "create owned FIFO swapchain");
        uint32_t actualImageCount = 0;
        requireSuccess(deviceFunctions_.vkGetSwapchainImagesKHR(
                device_, swapchain_, &actualImageCount, nullptr),
                       "count owned swapchain images");
        swapchainImages_.resize(actualImageCount);
        requireSuccess(deviceFunctions_.vkGetSwapchainImagesKHR(
                device_, swapchain_, &actualImageCount, swapchainImages_.data()),
                       "read owned swapchain images");
        swapchainImages_.resize(actualImageCount);

        VkRefreshCycleDurationGOOGLE refresh{};
        requireSuccess(deviceFunctions_.vkGetRefreshCycleDurationGOOGLE(
                device_, swapchain_, &refresh), "query owned refresh duration");
        if (refresh.refreshDuration == 0)
            throw std::runtime_error("owned refresh duration is zero");
        capabilities_.swapchainWidth = extent.width;
        capabilities_.swapchainHeight = extent.height;
        capabilities_.swapchainImageCount = actualImageCount;
        capabilities_.swapchainFormat = chosen.format;
        capabilities_.presentMode = VK_PRESENT_MODE_FIFO_KHR;
        capabilities_.refreshDurationNs = refresh.refreshDuration;
    }

    void createSetupCommandPool() {
        const VkCommandPoolCreateInfo poolCreate{
            .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
            .flags = VK_COMMAND_POOL_CREATE_TRANSIENT_BIT |
                     VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
            .queueFamilyIndex = queueFamily_,
        };
        requireSuccess(deviceFunctions_.vkCreateCommandPool(
                device_, &poolCreate, nullptr, &setupCommandPool_),
                       "create owned setup command pool");
    }

    uint32_t memoryType(uint32_t allowedBits, VkMemoryPropertyFlags required,
                        VkMemoryPropertyFlags preferred = 0) const {
        for (uint32_t index = 0; index < memoryProperties_.memoryTypeCount; ++index) {
            const VkMemoryPropertyFlags flags =
                    memoryProperties_.memoryTypes[index].propertyFlags;
            if ((allowedBits & (1U << index)) != 0U &&
                    (flags & required) == required &&
                    (flags & preferred) == preferred) return index;
        }
        for (uint32_t index = 0; index < memoryProperties_.memoryTypeCount; ++index) {
            const VkMemoryPropertyFlags flags =
                    memoryProperties_.memoryTypes[index].propertyFlags;
            if ((allowedBits & (1U << index)) != 0U &&
                    (flags & required) == required) return index;
        }
        throw std::runtime_error("owned Vulkan memory type unavailable");
    }

    void createLiveResources() {
        VkFormatProperties formatProperties{};
        vkGetPhysicalDeviceFormatProperties(
                physicalDevice_, VK_FORMAT_R8G8B8A8_UNORM, &formatProperties);
        const VkFormatFeatureFlags requiredBlit =
                VK_FORMAT_FEATURE_BLIT_SRC_BIT |
                VK_FORMAT_FEATURE_BLIT_DST_BIT |
                VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;
        if ((formatProperties.optimalTilingFeatures & requiredBlit) != requiredBlit)
            throw std::runtime_error("RGBA8 linear proof/present blit unavailable");

        std::array<VkCommandBuffer, kFixedSlotCount * 2U> commands{};
        const VkCommandBufferAllocateInfo commandAllocate{
            .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            .commandPool = setupCommandPool_,
            .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
            .commandBufferCount = static_cast<uint32_t>(commands.size()),
        };
        requireSuccess(deviceFunctions_.vkAllocateCommandBuffers(
                device_, &commandAllocate, commands.data()),
                "allocate owned live command buffers");

        for (uint32_t index = 0; index < kFixedSlotCount; ++index) {
            LiveSlot& slot = live_[index];
            slot.copyCommand = commands[index * 2U];
            slot.presentCommand = commands[index * 2U + 1U];
            const VkFenceCreateInfo fenceCreate{
                .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO,
            };
            requireSuccess(deviceFunctions_.vkCreateFence(
                    device_, &fenceCreate, nullptr, &slot.copyFence),
                    "create owned copy fence");
            requireSuccess(deviceFunctions_.vkCreateFence(
                    device_, &fenceCreate, nullptr, &slot.presentFence),
                    "create owned presentation fence");

            const VkExportSemaphoreCreateInfo exportInfo{
                .sType = VK_STRUCTURE_TYPE_EXPORT_SEMAPHORE_CREATE_INFO,
                .handleTypes = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_SYNC_FD_BIT,
            };
            const VkSemaphoreCreateInfo exportSemaphoreCreate{
                .sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO,
                .pNext = &exportInfo,
            };
            requireSuccess(deviceFunctions_.vkCreateSemaphore(
                    device_, &exportSemaphoreCreate, nullptr, &slot.inputReady),
                    "create owned input-ready semaphore");
            const VkSemaphoreCreateInfo semaphoreCreate{
                .sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO,
            };
            requireSuccess(deviceFunctions_.vkCreateSemaphore(
                    device_, &semaphoreCreate, nullptr, &slot.acquire),
                    "create owned acquire semaphore");
            requireSuccess(deviceFunctions_.vkCreateSemaphore(
                    device_, &exportSemaphoreCreate, nullptr, &slot.render),
                    "create owned render semaphore");
            createProofResources(slot);
        }
        swapchainInitialized_.assign(swapchainImages_.size(), false);
    }

    void createProofResources(LiveSlot& slot) {
        const VkImageCreateInfo imageCreate{
            .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
            .imageType = VK_IMAGE_TYPE_2D,
            .format = VK_FORMAT_R8G8B8A8_UNORM,
            .extent = {kProofWidth, kProofAtlasHeight, 1},
            .mipLevels = 1,
            .arrayLayers = 1,
            .samples = VK_SAMPLE_COUNT_1_BIT,
            .tiling = VK_IMAGE_TILING_OPTIMAL,
            .usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
                     VK_IMAGE_USAGE_TRANSFER_DST_BIT,
            .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
            .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
        };
        requireSuccess(deviceFunctions_.vkCreateImage(
                device_, &imageCreate, nullptr, &slot.proofImage),
                "create owned proof image");
        VkMemoryRequirements imageRequirements{};
        deviceFunctions_.vkGetImageMemoryRequirements(
                device_, slot.proofImage, &imageRequirements);
        const VkMemoryAllocateInfo imageAllocation{
            .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            .allocationSize = imageRequirements.size,
            .memoryTypeIndex = memoryType(imageRequirements.memoryTypeBits,
                                          VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT),
        };
        requireSuccess(deviceFunctions_.vkAllocateMemory(
                device_, &imageAllocation, nullptr, &slot.proofImageMemory),
                "allocate owned proof image memory");
        requireSuccess(deviceFunctions_.vkBindImageMemory(
                device_, slot.proofImage, slot.proofImageMemory, 0),
                "bind owned proof image memory");

        const VkBufferCreateInfo bufferCreate{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = kProofRgbaBytes,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
            .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
        };
        requireSuccess(deviceFunctions_.vkCreateBuffer(
                device_, &bufferCreate, nullptr, &slot.proofBuffer),
                "create owned proof buffer");
        VkMemoryRequirements bufferRequirements{};
        deviceFunctions_.vkGetBufferMemoryRequirements(
                device_, slot.proofBuffer, &bufferRequirements);
        const uint32_t type = memoryType(bufferRequirements.memoryTypeBits,
                VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,
                VK_MEMORY_PROPERTY_HOST_CACHED_BIT |
                VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        const VkMemoryPropertyFlags flags =
                memoryProperties_.memoryTypes[type].propertyFlags;
        slot.proofCoherent =
                (flags & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT) != 0U;
        const VkMemoryAllocateInfo bufferAllocation{
            .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
            .allocationSize = bufferRequirements.size,
            .memoryTypeIndex = type,
        };
        requireSuccess(deviceFunctions_.vkAllocateMemory(
                device_, &bufferAllocation, nullptr, &slot.proofBufferMemory),
                "allocate owned proof buffer memory");
        requireSuccess(deviceFunctions_.vkBindBufferMemory(
                device_, slot.proofBuffer, slot.proofBufferMemory, 0),
                "bind owned proof buffer memory");
        requireSuccess(deviceFunctions_.vkMapMemory(device_, slot.proofBufferMemory,
                0, VK_WHOLE_SIZE, 0, &slot.proofMapped),
                "map owned asynchronous proof buffer");
    }

    ImportedImage importSourceImage(AHardwareBuffer* buffer) {
        if (buffer == nullptr) throw std::invalid_argument("source AHB is null");
        AHardwareBuffer_Desc descriptor{};
        AHardwareBuffer_describe(buffer, &descriptor);
        if (descriptor.width != endpointExtent_.width ||
                descriptor.height != endpointExtent_.height ||
                descriptor.layers != 1 ||
                descriptor.format != AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM ||
                (descriptor.usage & AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE) == 0U)
            throw std::runtime_error("source AHB geometry/format/usage mismatch");

        VkAndroidHardwareBufferFormatPropertiesANDROID formatProperties{
            .sType = VK_STRUCTURE_TYPE_ANDROID_HARDWARE_BUFFER_FORMAT_PROPERTIES_ANDROID,
        };
        VkAndroidHardwareBufferPropertiesANDROID properties{
            .sType = VK_STRUCTURE_TYPE_ANDROID_HARDWARE_BUFFER_PROPERTIES_ANDROID,
            .pNext = &formatProperties,
        };
        requireSuccess(deviceFunctions_.vkGetAndroidHardwareBufferPropertiesANDROID(
                device_, buffer, &properties), "query source AHB properties");
        // externalFormat is an additional implementation-defined identifier
        // and Vulkan requires it to be non-zero; it does not invalidate the
        // simultaneously reported equivalent VkFormat. This path imports the
        // format-defined RGBA8 image and intentionally does not chain
        // VkExternalFormatANDROID into VkImageCreateInfo.
        if (formatProperties.format != VK_FORMAT_R8G8B8A8_UNORM ||
                properties.allocationSize == 0 || properties.memoryTypeBits == 0)
            throw std::runtime_error("source AHB Vulkan properties mismatch");

        const VkExternalMemoryImageCreateInfo externalImage{
            .sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO,
            .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_ANDROID_HARDWARE_BUFFER_BIT_ANDROID,
        };
        const VkImageCreateInfo imageCreate{
            .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
            .pNext = &externalImage,
            .imageType = VK_IMAGE_TYPE_2D,
            .format = VK_FORMAT_R8G8B8A8_UNORM,
            .extent = {endpointExtent_.width, endpointExtent_.height, 1},
            .mipLevels = 1,
            .arrayLayers = 1,
            .samples = VK_SAMPLE_COUNT_1_BIT,
            .tiling = VK_IMAGE_TILING_OPTIMAL,
            .usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
                     VK_IMAGE_USAGE_SAMPLED_BIT,
            .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
            .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
        };
        ImportedImage result;
        result.extent = endpointExtent_;
        requireSuccess(deviceFunctions_.vkCreateImage(
                device_, &imageCreate, nullptr, &result.image),
                "create source AHB Vulkan image");
        try {
            const VkMemoryDedicatedAllocateInfo dedicated{
                .sType = VK_STRUCTURE_TYPE_MEMORY_DEDICATED_ALLOCATE_INFO,
                .image = result.image,
            };
            const VkImportAndroidHardwareBufferInfoANDROID import{
                .sType = VK_STRUCTURE_TYPE_IMPORT_ANDROID_HARDWARE_BUFFER_INFO_ANDROID,
                .pNext = &dedicated,
                .buffer = buffer,
            };
            const VkMemoryAllocateInfo allocation{
                .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                .pNext = &import,
                .allocationSize = properties.allocationSize,
                .memoryTypeIndex = memoryType(properties.memoryTypeBits, 0),
            };
            requireSuccess(deviceFunctions_.vkAllocateMemory(
                    device_, &allocation, nullptr, &result.memory),
                    "import source AHB Vulkan memory");
            requireSuccess(deviceFunctions_.vkBindImageMemory(
                    device_, result.image, result.memory, 0),
                    "bind source AHB Vulkan memory");
            AHardwareBuffer_acquire(buffer);
            result.buffer = buffer;
            return result;
        } catch (...) {
            if (result.image != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroyImage(device_, result.image, nullptr);
            if (result.memory != VK_NULL_HANDLE)
                deviceFunctions_.vkFreeMemory(device_, result.memory, nullptr);
            throw;
        }
    }

    void validateLiveRequest(const LiveRequest& request) const {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        if (!capabilities_.liveResourcesReady || presentationEpoch_ == 0)
            throw std::logic_error("owned Vulkan live timeline is not armed");
        const bool hasNoFrameTimeline =
                request.compositorFrameTimelineVsyncId == 0 &&
                request.compositorFrameTimelineExpectedNs == 0 &&
                request.compositorFrameTimelineDeadlineNs == 0;
        const bool hasCompleteFrameTimeline =
                request.compositorFrameTimelineVsyncId != 0 &&
                request.compositorFrameTimelineExpectedNs != 0 &&
                request.compositorFrameTimelineDeadlineNs != 0;
        if ((!hasNoFrameTimeline && !hasCompleteFrameTimeline) ||
                request.left == nullptr || request.right == nullptr ||
                request.presentId == 0 || request.presentId > UINT32_MAX ||
                request.physicalPresentTimeNs == 0 ||
                request.desiredPresentTimeNs == 0 ||
                request.completionDeadlineNs == 0 ||
                request.refreshDurationNs == 0 ||
                request.completionDeadlineNs > request.desiredPresentTimeNs ||
                request.desiredPresentTimeNs > request.physicalPresentTimeNs)
            throw std::invalid_argument("owned Vulkan live request is invalid");
    }

    void resetLiveSlotForRequest(LiveSlot& slot, const LiveRequest& request) {
        requireSuccess(deviceFunctions_.vkResetFences(
                device_, 1, &slot.copyFence), "reset owned copy fence");
        requireSuccess(deviceFunctions_.vkResetFences(
                device_, 1, &slot.presentFence), "reset owned present fence");
        requireSuccess(deviceFunctions_.vkResetCommandBuffer(
                slot.copyCommand, 0), "reset owned copy command");
        requireSuccess(deviceFunctions_.vkResetCommandBuffer(
                slot.presentCommand, 0), "reset owned present command");
        slot.request = request;
        slot.gpuStartNs = 0;
        slot.gpuCompletionObservedNs = 0;
        slot.swapchainImage = UINT32_MAX;
    }

    LiveSlot& requirePrepared(const PreparedPresentation& prepared) {
        if (fatal_) throw std::runtime_error("owned Vulkan live host is quarantined");
        if (prepared.slotIndex >= kFixedSlotCount)
            throw std::invalid_argument("owned prepared slot index is invalid");
        LiveSlot& slot = live_[prepared.slotIndex];
        if (slot.state != LiveSlotState::CopyQueued)
            throw std::logic_error("owned prepared slot is not copy-queued");
        return slot;
    }

    void recordEndpointCopy(uint32_t slotIndex, LiveSlot& slot) {
        const VkCommandBufferBeginInfo begin{
            .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
            .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
        };
        requireSuccess(deviceFunctions_.vkBeginCommandBuffer(slot.copyCommand, &begin),
                       "begin exact endpoint copy");
        ImportedSlot& fixed = imported_[slotIndex];
        const uint32_t count = slot.sourceGenerated ? 3U : 2U;
        std::array<VkImageMemoryBarrier, 6> acquire{};
        const std::array<ImportedImage*, 3> sources{
            slot.sourceLeft, slot.sourceRight, slot.sourceGenerated,
        };
        const std::array<ImportedImage*, 3> destinations{
            &fixed.left, &fixed.right, &fixed.output,
        };
        for (uint32_t index = 0; index < count; ++index) {
            acquire[index] = VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = 0,
                .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                // Android producer AHBs enter this imported VkImage with no
                // EmuFusion-owned prior layout. The proven Android import path
                // acquires them from generic EXTERNAL with oldLayout UNDEFINED;
                // the already-signaled Image SyncFence supplies availability.
                .oldLayout = index == 2 ? VK_IMAGE_LAYOUT_GENERAL : VK_IMAGE_LAYOUT_UNDEFINED,
                .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .dstQueueFamilyIndex = queueFamily_,
                .image = sources[index]->image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            };
            acquire[index + count] = VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = 0,
                .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
                .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
                .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .dstQueueFamilyIndex = queueFamily_,
                .image = destinations[index]->image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            };
        }
        deviceFunctions_.vkCmdPipelineBarrier(slot.copyCommand,
                VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                VK_PIPELINE_STAGE_TRANSFER_BIT, 0,
                0, nullptr, 0, nullptr,
                count * 2, acquire.data());
        const VkImageCopy copy{
            .srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
            .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
            .extent = {endpointExtent_.width, endpointExtent_.height, 1},
        };
        for (uint32_t index = 0; index < count; ++index) {
            deviceFunctions_.vkCmdCopyImage(slot.copyCommand,
                    sources[index]->image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                    destinations[index]->image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                    1, &copy);
        }
        std::array<VkImageMemoryBarrier, 6> release{};
        for (uint32_t index = 0; index < count; ++index) {
            release[index] = VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                .dstAccessMask = 0,
                .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .newLayout = VK_IMAGE_LAYOUT_GENERAL,
                .srcQueueFamilyIndex = queueFamily_,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .image = sources[index]->image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            };
            release[index + count] = VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
                .dstAccessMask = 0,
                .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                .newLayout = VK_IMAGE_LAYOUT_GENERAL,
                .srcQueueFamilyIndex = queueFamily_,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .image = destinations[index]->image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            };
        }
        deviceFunctions_.vkCmdPipelineBarrier(slot.copyCommand,
                VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, 0,
                0, nullptr, 0, nullptr,
                count * 2, release.data());
        requireSuccess(deviceFunctions_.vkEndCommandBuffer(slot.copyCommand),
                       "end exact endpoint copy");
    }

    void progressReadyPresentations() {
        for (LiveSlot& slot : live_) {
            if (slot.state != LiveSlotState::AwaitingReady) continue;
            const uint64_t now = monotonicNs();
            if (now >= slot.request.completionDeadlineNs) {
                if (slot.readySyncFd >= 0) ::close(slot.readySyncFd);
                slot.readySyncFd = -1;
                fatal_ = true;
                throw std::runtime_error(
                        "LSFG output missed its immutable completion deadline");
            }
            if (slot.readySyncFd >= 0) {
                pollfd descriptor{
                    .fd = slot.readySyncFd,
                    .events = POLLIN,
                    .revents = 0,
                };
                const int result = ::poll(&descriptor, 1, 0);
                if (result == 0) continue;
                if (result != 1 ||
                        (descriptor.revents & (POLLIN | POLLERR | POLLHUP)) == 0) {
                    ::close(slot.readySyncFd);
                    slot.readySyncFd = -1;
                    fatal_ = true;
                    throw std::runtime_error("LSFG output sync FD poll failed");
                }
                ::close(slot.readySyncFd);
                slot.readySyncFd = -1;
            }
            if (monotonicNs() >= slot.request.completionDeadlineNs) {
                fatal_ = true;
                throw std::runtime_error(
                        "LSFG output became ready after its completion deadline");
            }
            if (!tryQueuePresentation(slot)) continue;
        }
    }

    void closeReadyFd(LiveSlot& slot) {
        if (slot.readySyncFd >= 0) ::close(slot.readySyncFd);
        slot.readySyncFd = -1;
    }

    DropDrainObservation observeDropDrain(const LiveSlot& slot) {
        DropDrainObservation result;
        const VkResult copyStatus = deviceFunctions_.vkGetFenceStatus(
                device_, slot.copyFence);
        if (copyStatus != VK_NOT_READY)
            requireSuccess(copyStatus, "poll cutoff endpoint-copy fence");
        result.copyKnown = true;
        result.copyReady = copyStatus == VK_SUCCESS;
        if (slot.privateProofPrepared) {
            const VkResult proofStatus = deviceFunctions_.vkGetFenceStatus(
                    device_, slot.presentFence);
            if (proofStatus != VK_NOT_READY)
                requireSuccess(proofStatus, "poll cutoff private-proof fence");
            result.proofKnown = true;
            result.proofReady = proofStatus == VK_SUCCESS;
        } else {
            // No proof command was submitted for this pre-SurfaceControl
            // endpoint. Its reset, unsignaled presentFence is NOT a dependency.
            result.proofKnown = true;
            result.proofReady = true;
        }
        result.output = observeReadyFence(slot.readySyncFd);
        result.outputKnown = result.output.stateKnown;
        return result;
    }

    void logSurfaceCutoffDrop(const LiveSlot& slot, const char* stage,
                              uint64_t pollNowNs,
                              const DropDrainObservation& observed) {
        const bool quarantine = std::strcmp(stage, "quarantine") == 0;
        if (quarantine) {
            if (surfaceCutoffQuarantineLogged_) return;
            surfaceCutoffQuarantineLogged_ = true;
        } else if (slot.cutoffDropOrdinal > kCutoffDiagnosticRequestLimit) {
            return;
        }
        // Eight exact cutoff/retirement pairs plus one quarantine diagnostic
        // per host. Lifetime counts below survive resetTimeline, even after
        // this fixed logging budget is exhausted. Signal time is kernel-only.
        LOGE("Surface cutoff drop stage=%s ordinal=%llu presentId=%llu "
             "sessionEpoch=%llu presentationEpoch=%llu generated=%d "
             "leftSequence=%llu rightSequence=%llu contentTimestampNs=%llu "
             "physicalTargetNs=%llu driverDesiredNs=%llu vsyncId=%llu "
             "tokenExpectedNs=%llu tokenDeadlineNs=%llu cutoffNs=%llu "
             "pollNowNs=%llu firstObservedNs=%llu branch=%u "
             "copyReady=%d privateProofRequired=%d proofReady=%d outputReady=%d "
             "kernelSignalKnown=%d kernelSignalNs=%llu physicalSubmitted=0",
             stage, static_cast<unsigned long long>(slot.cutoffDropOrdinal),
             static_cast<unsigned long long>(slot.request.presentId),
             static_cast<unsigned long long>(slot.request.sessionEpoch),
             static_cast<unsigned long long>(slot.request.presentationEpoch),
             slot.request.generated ? 1 : 0,
             static_cast<unsigned long long>(slot.request.leftSequence),
             static_cast<unsigned long long>(slot.request.rightSequence),
             static_cast<unsigned long long>(slot.request.contentTimestampNs),
             static_cast<unsigned long long>(slot.request.physicalPresentTimeNs),
             static_cast<unsigned long long>(slot.request.desiredPresentTimeNs),
             static_cast<unsigned long long>(slot.request.compositorFrameTimelineVsyncId),
             static_cast<unsigned long long>(slot.request.compositorFrameTimelineExpectedNs),
             static_cast<unsigned long long>(slot.request.compositorFrameTimelineDeadlineNs),
             static_cast<unsigned long long>(slot.request.completionDeadlineNs),
             static_cast<unsigned long long>(pollNowNs),
             static_cast<unsigned long long>(slot.cutoffObservedNs), slot.cutoffBranch,
             observed.copyKnown ? (observed.copyReady ? 1 : 0) : -1,
             slot.privateProofPrepared ? 1 : 0,
             observed.proofKnown ? (observed.proofReady ? 1 : 0) : -1,
             observed.outputKnown ? (observed.output.ready ? 1 : 0) : -1,
             observed.output.kernelSignalNs != 0 ? 1 : 0,
             static_cast<unsigned long long>(observed.output.kernelSignalNs));
    }

    void markSurfaceCutoffDrop(LiveSlot& slot, uint64_t now, uint32_t branch) {
        if (slot.state != LiveSlotState::AwaitingReady)
            throw std::logic_error("cutoff drop does not own a pre-submit slot");
        // Do not close or import the ready FD here. Its LSFG/copy/proof work
        // can still be running even though the visible request has expired.
        slot.state = LiveSlotState::SurfaceDroppedAwaitingReady;
        slot.cutoffObservedNs = now;
        slot.cutoffDropOrdinal = ++surfaceCutoffDrops_;
        slot.cutoffBranch = branch;
        try {
            logSurfaceCutoffDrop(slot, "cutoff", now, observeDropDrain(slot));
        } catch (...) {
            logSurfaceCutoffDrop(slot, "quarantine", now, {});
            fatal_ = true;
            throw;
        }
    }

    bool readyFdSignaled(LiveSlot& slot) {
        if (slot.readySyncFd < 0) return true;
        pollfd descriptor{
            .fd = slot.readySyncFd,
            .events = POLLIN,
            .revents = 0,
        };
        const int result = ::poll(&descriptor, 1, 0);
        if (result == 0) return false;
        if (result != 1 ||
                (descriptor.revents & (POLLIN | POLLERR | POLLHUP)) == 0) {
            closeReadyFd(slot);
            fatal_ = true;
            throw std::runtime_error("LSFG output sync FD poll failed");
        }
        return true;
    }

    ImportedImage& selectedImage(LiveSlot& slot) {
        const uint32_t slotIndex = static_cast<uint32_t>(&slot - live_.data());
        ImportedSlot& fixed = imported_[slotIndex];
        return slot.request.generated ? fixed.output :
                (slot.request.presentRight ? fixed.right : fixed.left);
    }

    AHardwareBuffer* selectedBuffer(LiveSlot& slot) {
        return selectedImage(slot).buffer;
    }

    LiveSlot* findSurfaceSlot(uint64_t presentId, LiveSlotState state) {
        for (LiveSlot& slot : live_) {
            if (slot.state == state && slot.request.presentId == presentId)
                return &slot;
        }
        return nullptr;
    }

    uint64_t proofFenceTimestamp(LiveSlot& slot) {
        if (slot.proofTimestampSyncFd < 0)
            throw std::runtime_error("SurfaceControl proof timestamp fence missing");
        pollfd descriptor{
            .fd = slot.proofTimestampSyncFd,
            .events = POLLIN,
            .revents = 0,
        };
        const int result = ::poll(&descriptor, 1, 0);
        if (result != 1 ||
                (descriptor.revents & (POLLIN | POLLERR | POLLHUP)) == 0)
            throw std::runtime_error(
                    "SurfaceControl presented before proof fence completion");
        std::unique_ptr<struct sync_file_info,
                decltype(&sync_file_info_free)> info(
                sync_file_info(slot.proofTimestampSyncFd),
                &sync_file_info_free);
        if (!info || info->status != 1 || info->num_fences == 0)
            throw std::runtime_error(
                    "SurfaceControl proof fence status invalid");
        uint64_t timestampNs = 0;
        const sync_fence_info* fences = sync_get_fence_info(info.get());
        for (uint32_t index = 0; index < info->num_fences; ++index) {
            if (fences[index].status != 1 || fences[index].timestamp_ns == 0)
                throw std::runtime_error(
                        "SurfaceControl child proof fence invalid");
            timestampNs = std::max<uint64_t>(
                    timestampNs, fences[index].timestamp_ns);
        }
        ::close(slot.proofTimestampSyncFd);
        slot.proofTimestampSyncFd = -1;
        return timestampNs;
    }

    bool tryQueuePresentation(LiveSlot& slot) {
        try {
            uint32_t imageIndex = 0;
            const VkResult acquired = deviceFunctions_.vkAcquireNextImageKHR(
                    device_, swapchain_, 0, slot.acquire, VK_NULL_HANDLE,
                    &imageIndex);
            if (acquired == VK_NOT_READY || acquired == VK_TIMEOUT) return false;
            if (acquired != VK_SUCCESS && acquired != VK_SUBOPTIMAL_KHR)
                fail("acquire owned FIFO image", acquired);
            if (imageIndex >= swapchainImages_.size())
                throw std::runtime_error("owned FIFO image index is out of range");
            if (monotonicNs() >= slot.request.completionDeadlineNs)
                throw std::runtime_error(
                        "owned FIFO acquisition crossed the completion deadline");
            slot.swapchainImage = imageIndex;
            recordPresentation(slot);
            const VkPipelineStageFlags waitStage = VK_PIPELINE_STAGE_TRANSFER_BIT;
            const VkSubmitInfo submit{
                .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                .waitSemaphoreCount = 1,
                .pWaitSemaphores = &slot.acquire,
                .pWaitDstStageMask = &waitStage,
                .commandBufferCount = 1,
                .pCommandBuffers = &slot.presentCommand,
                .signalSemaphoreCount = 1,
                .pSignalSemaphores = &slot.render,
            };
            requireSuccess(deviceFunctions_.vkQueueSubmit(
                    queue_, 1, &submit, slot.presentFence),
                    "submit owned LSFG presentation");
            if (nextWsiPresentId_ == 0)
                throw std::overflow_error("owned WSI present ID exhausted");
            slot.wsiPresentId = nextWsiPresentId_++;
            const VkPresentTimeGOOGLE presentTime{
                .presentID = slot.wsiPresentId,
                .desiredPresentTime = slot.request.desiredPresentTimeNs,
            };
            const VkPresentTimesInfoGOOGLE presentTimes{
                .sType = VK_STRUCTURE_TYPE_PRESENT_TIMES_INFO_GOOGLE,
                .swapchainCount = 1,
                .pTimes = &presentTime,
            };
            const VkPresentInfoKHR present{
                .sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
                .pNext = &presentTimes,
                .waitSemaphoreCount = 1,
                .pWaitSemaphores = &slot.render,
                .swapchainCount = 1,
                .pSwapchains = &swapchain_,
                .pImageIndices = &slot.swapchainImage,
            };
            requireSuccess(deviceFunctions_.vkQueuePresentKHR(queue_, &present),
                           "queue owned timed FIFO present");
            swapchainInitialized_[slot.swapchainImage] = true;
            slot.state = LiveSlotState::Presented;
            return true;
        } catch (...) {
            // A successful acquire or queue submission cannot be rolled back.
            // Quarantine; teardown drains while no stale output is retried.
            fatal_ = true;
            throw;
        }
    }

    static VkImageBlit fullBlit(VkExtent2D source, VkExtent2D destination,
                                int32_t destinationYOffset = 0) {
        return VkImageBlit{
            .srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
            .srcOffsets = {{0, 0, 0},
                           {static_cast<int32_t>(source.width),
                            static_cast<int32_t>(source.height), 1}},
            .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
            .dstOffsets = {{0, destinationYOffset, 0},
                           {static_cast<int32_t>(destination.width),
                            destinationYOffset + static_cast<int32_t>(destination.height), 1}},
        };
    }

    void recordSurfaceProof(LiveSlot& slot) {
        const uint32_t slotIndex = static_cast<uint32_t>(&slot - live_.data());
        ImportedSlot& fixed = imported_[slotIndex];
        ImportedImage* selected = &selectedImage(slot);
        const bool includeOutput = slot.request.generated;
        const VkCommandBufferBeginInfo begin{
            .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
            .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
        };
        requireSuccess(deviceFunctions_.vkBeginCommandBuffer(
                slot.presentCommand, &begin),
                "begin owned SurfaceControl proof command");

        std::vector<VkImageMemoryBarrier> acquire;
        acquire.reserve(includeOutput ? 4U : 3U);
        for (ImportedImage* image : std::array<ImportedImage*, 2>{
                     &fixed.left, &fixed.right}) {
            acquire.push_back(VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = 0,
                .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
                .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .dstQueueFamilyIndex = queueFamily_,
                .image = image->image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            });
        }
        if (includeOutput) {
            acquire.push_back(VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = 0,
                .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
                .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .dstQueueFamilyIndex = queueFamily_,
                .image = fixed.output.image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            });
        }
        acquire.push_back(VkImageMemoryBarrier{
            .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            .srcAccessMask = slot.proofInitialized ? VK_ACCESS_TRANSFER_READ_BIT : 0U,
            .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
            .oldLayout = slot.proofInitialized ?
                    VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL :
                    VK_IMAGE_LAYOUT_UNDEFINED,
            .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = slot.proofImage,
            .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
        });
        deviceFunctions_.vkCmdPipelineBarrier(slot.presentCommand,
                VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT |
                        VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_TRANSFER_BIT, 0,
                0, nullptr, 0, nullptr,
                static_cast<uint32_t>(acquire.size()), acquire.data());

        recordTripletCapture(slot, fixed);

        const std::array<ImportedImage*, 3> proofSources{
            &fixed.left, &fixed.right, selected,
        };
        const VkExtent2D proofExtent{kProofWidth, kProofHeight};
        for (uint32_t tile = 0; tile < proofSources.size(); ++tile) {
            const VkImageBlit proofBlit = fullBlit(endpointExtent_, proofExtent,
                    static_cast<int32_t>(tile * kProofHeight));
            deviceFunctions_.vkCmdBlitImage(slot.presentCommand,
                    proofSources[tile]->image,
                    VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                    slot.proofImage, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                    1, &proofBlit, VK_FILTER_LINEAR);
        }
        const VkImageMemoryBarrier proofReady{
            .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
            .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
            .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
            .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = slot.proofImage,
            .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
        };
        deviceFunctions_.vkCmdPipelineBarrier(slot.presentCommand,
                VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_TRANSFER_BIT, 0,
                0, nullptr, 0, nullptr, 1, &proofReady);
        const VkBufferImageCopy proofCopy{
            .bufferOffset = 0,
            .bufferRowLength = 0,
            .bufferImageHeight = 0,
            .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
            .imageOffset = {0, 0, 0},
            .imageExtent = {kProofWidth, kProofAtlasHeight, 1},
        };
        deviceFunctions_.vkCmdCopyImageToBuffer(slot.presentCommand,
                slot.proofImage, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                slot.proofBuffer, 1, &proofCopy);
        const VkBufferMemoryBarrier proofHost{
            .sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
            .dstAccessMask = VK_ACCESS_HOST_READ_BIT,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .buffer = slot.proofBuffer,
            .offset = 0,
            .size = kProofRgbaBytes,
        };

        std::vector<VkImageMemoryBarrier> release;
        release.reserve(includeOutput ? 3U : 2U);
        for (ImportedImage* image : std::array<ImportedImage*, 2>{
                     &fixed.left, &fixed.right}) {
            release.push_back(VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                .dstAccessMask = 0,
                .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .newLayout = VK_IMAGE_LAYOUT_GENERAL,
                .srcQueueFamilyIndex = queueFamily_,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .image = image->image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            });
        }
        if (includeOutput) {
            release.push_back(VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                .dstAccessMask = 0,
                .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .newLayout = VK_IMAGE_LAYOUT_GENERAL,
                .srcQueueFamilyIndex = queueFamily_,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .image = fixed.output.image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            });
        }
        deviceFunctions_.vkCmdPipelineBarrier(slot.presentCommand,
                VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT |
                        VK_PIPELINE_STAGE_HOST_BIT,
                0, 0, nullptr, 1, &proofHost,
                static_cast<uint32_t>(release.size()), release.data());
        requireSuccess(deviceFunctions_.vkEndCommandBuffer(slot.presentCommand),
                "end owned SurfaceControl proof command");
        slot.proofInitialized = true;
    }

    void recordPresentation(LiveSlot& slot) {
        const uint32_t slotIndex = static_cast<uint32_t>(&slot - live_.data());
        ImportedSlot& fixed = imported_[slotIndex];
        ImportedImage* selected = slot.request.generated ? &fixed.output :
                (slot.request.presentRight ? &fixed.right : &fixed.left);
        const bool includeOutput = slot.request.generated;
        const VkCommandBufferBeginInfo begin{
            .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
            .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
        };
        requireSuccess(deviceFunctions_.vkBeginCommandBuffer(
                slot.presentCommand, &begin), "begin owned presentation command");

        std::vector<VkImageMemoryBarrier> acquire;
        acquire.reserve(includeOutput ? 4U : 3U);
        for (ImportedImage* image : std::array<ImportedImage*, 2>{
                     &fixed.left, &fixed.right}) {
            acquire.push_back(VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = 0,
                .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
                .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .dstQueueFamilyIndex = queueFamily_,
                .image = image->image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            });
        }
        if (includeOutput) {
            acquire.push_back(VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = 0,
                .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
                .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .dstQueueFamilyIndex = queueFamily_,
                .image = fixed.output.image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            });
        }
        acquire.push_back(VkImageMemoryBarrier{
            .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            .srcAccessMask = 0,
            .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
            .oldLayout = swapchainInitialized_[slot.swapchainImage] ?
                    VK_IMAGE_LAYOUT_PRESENT_SRC_KHR : VK_IMAGE_LAYOUT_UNDEFINED,
            .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = swapchainImages_[slot.swapchainImage],
            .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
        });
        acquire.push_back(VkImageMemoryBarrier{
            .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            .srcAccessMask = slot.proofInitialized ? VK_ACCESS_TRANSFER_READ_BIT : 0U,
            .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
            .oldLayout = slot.proofInitialized ? VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL :
                    VK_IMAGE_LAYOUT_UNDEFINED,
            .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = slot.proofImage,
            .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
        });
        deviceFunctions_.vkCmdPipelineBarrier(slot.presentCommand,
                VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT |
                        VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_TRANSFER_BIT, 0,
                0, nullptr, 0, nullptr,
                static_cast<uint32_t>(acquire.size()), acquire.data());

        const VkExtent2D swapExtent{
            capabilities_.swapchainWidth, capabilities_.swapchainHeight,
        };
        const VkImageBlit presentBlit = fullBlit(endpointExtent_, swapExtent);
        deviceFunctions_.vkCmdBlitImage(slot.presentCommand,
                selected->image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                swapchainImages_[slot.swapchainImage],
                VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                1, &presentBlit, VK_FILTER_LINEAR);

        const std::array<ImportedImage*, 3> proofSources{
            &fixed.left, &fixed.right, selected,
        };
        const VkExtent2D proofExtent{kProofWidth, kProofHeight};
        for (uint32_t tile = 0; tile < proofSources.size(); ++tile) {
            const VkImageBlit proofBlit = fullBlit(endpointExtent_, proofExtent,
                    static_cast<int32_t>(tile * kProofHeight));
            deviceFunctions_.vkCmdBlitImage(slot.presentCommand,
                    proofSources[tile]->image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                    slot.proofImage, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                    1, &proofBlit, VK_FILTER_LINEAR);
        }
        const VkImageMemoryBarrier proofReady{
            .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
            .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
            .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
            .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = slot.proofImage,
            .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
        };
        deviceFunctions_.vkCmdPipelineBarrier(slot.presentCommand,
                VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_TRANSFER_BIT, 0,
                0, nullptr, 0, nullptr, 1, &proofReady);
        const VkBufferImageCopy proofCopy{
            .bufferOffset = 0,
            .bufferRowLength = 0,
            .bufferImageHeight = 0,
            .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
            .imageOffset = {0, 0, 0},
            .imageExtent = {kProofWidth, kProofAtlasHeight, 1},
        };
        deviceFunctions_.vkCmdCopyImageToBuffer(slot.presentCommand,
                slot.proofImage, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                slot.proofBuffer, 1, &proofCopy);
        const VkBufferMemoryBarrier proofHost{
            .sType = VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
            .dstAccessMask = VK_ACCESS_HOST_READ_BIT,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .buffer = slot.proofBuffer,
            .offset = 0,
            .size = kProofRgbaBytes,
        };

        std::vector<VkImageMemoryBarrier> release;
        release.reserve(includeOutput ? 4U : 3U);
        for (ImportedImage* image : std::array<ImportedImage*, 2>{
                     &fixed.left, &fixed.right}) {
            release.push_back(VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                .dstAccessMask = 0,
                .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .newLayout = VK_IMAGE_LAYOUT_GENERAL,
                .srcQueueFamilyIndex = queueFamily_,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .image = image->image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            });
        }
        if (includeOutput) {
            release.push_back(VkImageMemoryBarrier{
                .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                .srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT,
                .dstAccessMask = 0,
                .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                .newLayout = VK_IMAGE_LAYOUT_GENERAL,
                .srcQueueFamilyIndex = queueFamily_,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                .image = fixed.output.image,
                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
            });
        }
        release.push_back(VkImageMemoryBarrier{
            .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
            .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
            .dstAccessMask = 0,
            .oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
            .newLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = swapchainImages_[slot.swapchainImage],
            .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1},
        });
        deviceFunctions_.vkCmdPipelineBarrier(slot.presentCommand,
                VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT | VK_PIPELINE_STAGE_HOST_BIT,
                0, 0, nullptr, 1, &proofHost,
                static_cast<uint32_t>(release.size()), release.data());
        requireSuccess(deviceFunctions_.vkEndCommandBuffer(slot.presentCommand),
                       "end owned presentation command");
        slot.proofInitialized = true;
    }

    void retireAbandonedCopies() {
        for (LiveSlot& slot : live_) {
            if (slot.state != LiveSlotState::Abandoned) continue;
            // Private work may have advanced beyond its source copy to a
            // proof command. Returning the ImageReader image or recycling the
            // fixed slot requires every submitted dependency, not just copy.
            if (!observeDropDrain(slot).ready()) continue;
            closeReadyFd(slot);
            resetLiveSlotStorage(slot);
        }
    }

    void collectPastPresentationTimings() {
        ++pastTimingQueries_;
        uint32_t count = 0;
        requireSuccess(deviceFunctions_.vkGetPastPresentationTimingGOOGLE(
                device_, swapchain_, &count, nullptr),
                "count owned past presentation timings");
        if (count == 0) return;
        ++pastTimingNonzeroQueries_;
        std::vector<VkPastPresentationTimingGOOGLE> timings(count);
        const VkResult result =
                deviceFunctions_.vkGetPastPresentationTimingGOOGLE(
                        device_, swapchain_, &count, timings.data());
        if (result != VK_SUCCESS && result != VK_INCOMPLETE)
            fail("read owned past presentation timings", result);
        pastTimingRecords_ += count;
        for (uint32_t index = 0; index < count; ++index) {
            if (timings[index].presentID != 0)
                completedTimings_[timings[index].presentID] = timings[index];
        }
    }

    static uint64_t ppm(uint64_t numerator, uint64_t denominator) {
        if (denominator == 0) return 0;
        return (numerator * 1'000'000ULL + denominator / 2ULL) / denominator;
    }

    uint32_t analyzePrivatePairStatus(LiveSlot& slot) {
        if (!slot.proofCoherent) {
            const VkMappedMemoryRange range{
                .sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,
                .memory = slot.proofBufferMemory,
                .offset = 0,
                .size = VK_WHOLE_SIZE,
            };
            requireSuccess(deviceFunctions_.vkInvalidateMappedMemoryRanges(
                    device_, 1, &range),
                    "invalidate private proof buffer");
        }
        const auto* bytes = static_cast<const uint8_t*>(slot.proofMapped);
        if (bytes == nullptr)
            throw std::runtime_error("private proof map is null");
        std::array<uint32_t, 32> leftHistogram{};
        std::array<uint32_t, 32> rightHistogram{};
        uint64_t endpointDifference = 0;
        for (uint32_t y = 0; y < kProofHeight; ++y) {
            for (uint32_t x = 0; x < kProofWidth; ++x) {
                uint32_t leftLuma = 0;
                uint32_t rightLuma = 0;
                for (uint32_t channel = 0; channel < 3; ++channel) {
                    const uint64_t leftIndex =
                            (static_cast<uint64_t>(y) * kProofWidth + x) *
                                    4ULL + channel;
                    const uint64_t rightIndex =
                            ((static_cast<uint64_t>(kProofHeight) + y) *
                                    kProofWidth + x) * 4ULL + channel;
                    const uint8_t left = bytes[leftIndex];
                    const uint8_t right = bytes[rightIndex];
                    endpointDifference += static_cast<uint64_t>(std::abs(
                            static_cast<int>(left) -
                            static_cast<int>(right)));
                    const uint32_t weight = channel == 0 ? 77U :
                            channel == 1 ? 150U : 29U;
                    leftLuma += weight * left;
                    rightLuma += weight * right;
                }
                ++leftHistogram[std::min(31U, (leftLuma >> 8U) >> 3U)];
                ++rightHistogram[std::min(31U, (rightLuma >> 8U) >> 3U)];
            }
        }
        uint64_t histogramDifference = 0;
        for (uint32_t bin = 0; bin < leftHistogram.size(); ++bin) {
            histogramDifference += static_cast<uint64_t>(std::abs(
                    static_cast<int64_t>(leftHistogram[bin]) -
                    static_cast<int64_t>(rightHistogram[bin])));
        }
        constexpr uint64_t sampleCount =
                static_cast<uint64_t>(kProofWidth) * kProofHeight;
        const uint64_t endpointMad = ppm(endpointDifference,
                sampleCount * 3ULL * 255ULL);
        const uint64_t histogramPpm = ppm(
                histogramDifference, sampleCount * 2ULL);
        const bool sceneCut = endpointMad >= 350'000ULL ||
                (endpointMad >= 220'000ULL &&
                        histogramPpm >= 250'000ULL);
        return sceneCut ? kPairUnsafe : kPairReady;
    }

    Completion analyzeCompletion(
            LiveSlot& slot, const VkPastPresentationTimingGOOGLE& timing) {
        if (!slot.proofCoherent) {
            const VkMappedMemoryRange range{
                .sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE,
                .memory = slot.proofBufferMemory,
                .offset = 0,
                .size = VK_WHOLE_SIZE,
            };
            requireSuccess(deviceFunctions_.vkInvalidateMappedMemoryRanges(
                    device_, 1, &range), "invalidate owned proof buffer");
        }
        const uint64_t analysisStartNs = monotonicNs();
        const auto* bytes = static_cast<const uint8_t*>(slot.proofMapped);
        if (bytes == nullptr) throw std::runtime_error("owned proof map is null");
        constexpr uint64_t fnvOffset = 1469598103934665603ULL;
        constexpr uint64_t fnvPrime = 1099511628211ULL;
        std::array<uint64_t, 3> checksums{fnvOffset, fnvOffset, fnvOffset};
        std::array<uint32_t, 32> leftHistogram{};
        std::array<uint32_t, 32> rightHistogram{};
        uint64_t endpointDifference = 0;
        uint64_t outputLeftDifference = 0;
        uint64_t outputRightDifference = 0;
        uint32_t outputMin = 255;
        uint32_t outputMax = 0;
        const auto valueAt = [bytes](uint32_t tile, uint32_t x,
                                     uint32_t y, uint32_t channel) {
            const uint64_t atlasY = static_cast<uint64_t>(tile) *
                    kProofHeight + y;
            const uint64_t index =
                    (atlasY * kProofWidth + x) * 4ULL + channel;
            return bytes[index];
        };
        // A privately prepared REAL pair proves both fixed endpoint buffers
        // before the scheduler selects either one. SurfaceSubmission hands out
        // exactly selectedImage(slot), so sample that same endpoint tile here.
        // This is endpoint provenance, NOT an independently generated image.
        // Generated output and the setup-only visible path retain tile 2.
        const uint32_t outputProofTile = slot.privateProofPrepared &&
                !slot.request.generated ? (slot.request.presentRight ? 1U : 0U) : 2U;
        for (uint32_t y = 0; y < kProofHeight; ++y) {
            for (uint32_t x = 0; x < kProofWidth; ++x) {
                uint32_t leftLuma = 0;
                uint32_t rightLuma = 0;
                for (uint32_t channel = 0; channel < 3; ++channel) {
                    const uint8_t left = valueAt(0, x, y, channel);
                    const uint8_t right = valueAt(1, x, y, channel);
                    const uint8_t output = valueAt(outputProofTile, x, y, channel);
                    checksums[0] = (checksums[0] ^ left) * fnvPrime;
                    checksums[1] = (checksums[1] ^ right) * fnvPrime;
                    checksums[2] = (checksums[2] ^ output) * fnvPrime;
                    endpointDifference += static_cast<uint64_t>(std::abs(
                            static_cast<int>(left) - static_cast<int>(right)));
                    outputLeftDifference += static_cast<uint64_t>(std::abs(
                            static_cast<int>(output) - static_cast<int>(left)));
                    outputRightDifference += static_cast<uint64_t>(std::abs(
                            static_cast<int>(output) - static_cast<int>(right)));
                    outputMin = std::min(outputMin, static_cast<uint32_t>(output));
                    outputMax = std::max(outputMax, static_cast<uint32_t>(output));
                    const uint32_t weight = channel == 0 ? 77U :
                            channel == 1 ? 150U : 29U;
                    leftLuma += weight * left;
                    rightLuma += weight * right;
                }
                ++leftHistogram[std::min(31U, (leftLuma >> 8U) >> 3U)];
                ++rightHistogram[std::min(31U, (rightLuma >> 8U) >> 3U)];
            }
        }
        uint64_t histogramDifference = 0;
        for (uint32_t bin = 0; bin < leftHistogram.size(); ++bin) {
            histogramDifference += static_cast<uint64_t>(std::abs(
                    static_cast<int64_t>(leftHistogram[bin]) -
                    static_cast<int64_t>(rightHistogram[bin])));
        }
        constexpr uint64_t sampleCount =
                static_cast<uint64_t>(kProofWidth) * kProofHeight;
        constexpr uint64_t rgbDenominator = sampleCount * 3ULL * 255ULL;
        const uint64_t endpointMad = ppm(endpointDifference, rgbDenominator);
        const uint64_t histogramPpm = ppm(
                histogramDifference, sampleCount * 2ULL);
        const bool sceneCut = endpointMad >= 350'000ULL ||
                (endpointMad >= 220'000ULL && histogramPpm >= 250'000ULL);
        const uint64_t analysisWallNs =
                std::max<uint64_t>(1, monotonicNs() - analysisStartNs);
        if (timing.presentID != slot.wsiPresentId ||
                timing.desiredPresentTime != slot.request.desiredPresentTimeNs ||
                timing.actualPresentTime == 0 ||
                slot.gpuCompletionObservedNs <= slot.gpuStartNs ||
                kLogicalProofBytes != 11'664ULL)
            throw std::runtime_error("owned completion identity is invalid");
        return Completion{
            .presentId = slot.request.presentId,
            .desiredPresentTimeNs = timing.desiredPresentTime,
            .actualPresentTimeNs = timing.actualPresentTime,
            .earliestPresentTimeNs = timing.earliestPresentTime,
            .presentMarginNs = static_cast<int64_t>(timing.presentMargin),
            .refreshDurationNs = slot.request.refreshDurationNs,
            .gpuWorkNs = slot.gpuCompletionObservedNs - slot.gpuStartNs,
            .gpuCompletionNs = slot.gpuCompletionObservedNs,
            .pairStatus = sceneCut ? kPairUnsafe : kPairReady,
            .leftChecksum = checksums[0],
            .rightChecksum = checksums[1],
            .outputChecksum = checksums[2],
            .endpointMadPpm = endpointMad,
            .outputLeftMadPpm = ppm(outputLeftDifference, rgbDenominator),
            .outputRightMadPpm = ppm(outputRightDifference, rgbDenominator),
            .endpointHistogramDistancePpm = histogramPpm,
            .outputMin = outputMin,
            .outputMax = outputMax,
            .sceneCutRisk = sceneCut,
            .analysisWallNs = analysisWallNs,
        };
    }

    void resetLiveSlotStorage(LiveSlot& slot) {
        if (tripletWriter_ && slot.fullCaptureId != 0)
            tripletWriter_->discard(slot.fullCaptureId, "slot-retired-without-physical-capture-completion");
        slot.fullCaptureId = 0;
        if (slot.readySyncFd >= 0) ::close(slot.readySyncFd);
        if (slot.proofTimestampSyncFd >= 0)
            ::close(slot.proofTimestampSyncFd);
        slot.sourceRight = nullptr;
        slot.sourceGenerated = nullptr;
        slot.sourceLeft = nullptr;
        slot.state = LiveSlotState::Idle;
        slot.request = {};
        slot.gpuStartNs = 0;
        slot.gpuCompletionObservedNs = 0;
        slot.swapchainImage = UINT32_MAX;
        slot.wsiPresentId = 0;
        slot.readySyncFd = -1;
        slot.proofTimestampSyncFd = -1;
        slot.privatePairStatus = 0;
        slot.privateProofPrepared = false;
        slot.cutoffObservedNs = 0;
        slot.cutoffDropOrdinal = 0;
        slot.cutoffBranch = 0;
    }

    void destroyLiveResources() noexcept {
        if (device_ == VK_NULL_HANDLE) return;
        for (LiveSlot& slot : live_) {
            if (slot.readySyncFd >= 0) ::close(slot.readySyncFd);
            if (slot.proofTimestampSyncFd >= 0)
                ::close(slot.proofTimestampSyncFd);
            slot.sourceRight = nullptr;
            slot.sourceGenerated = nullptr;
            slot.sourceLeft = nullptr;
            if (slot.proofMapped != nullptr)
                deviceFunctions_.vkUnmapMemory(device_, slot.proofBufferMemory);
            if (slot.proofBuffer != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroyBuffer(device_, slot.proofBuffer, nullptr);
            if (slot.proofBufferMemory != VK_NULL_HANDLE)
                deviceFunctions_.vkFreeMemory(device_, slot.proofBufferMemory, nullptr);
            if (slot.proofImage != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroyImage(device_, slot.proofImage, nullptr);
            if (slot.proofImageMemory != VK_NULL_HANDLE)
                deviceFunctions_.vkFreeMemory(device_, slot.proofImageMemory, nullptr);
            if (slot.render != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroySemaphore(device_, slot.render, nullptr);
            if (slot.acquire != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroySemaphore(device_, slot.acquire, nullptr);
            if (slot.inputReady != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroySemaphore(device_, slot.inputReady, nullptr);
            if (slot.presentFence != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroyFence(device_, slot.presentFence, nullptr);
            if (slot.copyFence != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroyFence(device_, slot.copyFence, nullptr);
            slot = {};
        }
        completedTimings_.clear();
        swapchainInitialized_.clear();
        capabilities_.liveResourcesReady = false;
        pendingPresentations_ = 0;
    }

    ImportedImage importImage(AHardwareBuffer* buffer) {
        if (buffer == nullptr) throw std::invalid_argument("fixed AHB is null");
        AHardwareBuffer_Desc descriptor{};
        AHardwareBuffer_describe(buffer, &descriptor);
        if (descriptor.width != endpointExtent_.width ||
                descriptor.height != endpointExtent_.height ||
                descriptor.layers != 1 ||
                descriptor.format != AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM ||
                (descriptor.usage & AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE) == 0U ||
                (descriptor.usage & AHARDWAREBUFFER_USAGE_GPU_COLOR_OUTPUT) == 0U) {
            throw std::runtime_error("fixed AHB geometry/format/usage mismatch");
        }

        VkAndroidHardwareBufferFormatPropertiesANDROID formatProperties{
            .sType =
                    VK_STRUCTURE_TYPE_ANDROID_HARDWARE_BUFFER_FORMAT_PROPERTIES_ANDROID,
        };
        VkAndroidHardwareBufferPropertiesANDROID properties{
            .sType = VK_STRUCTURE_TYPE_ANDROID_HARDWARE_BUFFER_PROPERTIES_ANDROID,
            .pNext = &formatProperties,
        };
        requireSuccess(deviceFunctions_.vkGetAndroidHardwareBufferPropertiesANDROID(
                device_, buffer, &properties), "query fixed AHB properties");
        if (formatProperties.format != VK_FORMAT_R8G8B8A8_UNORM ||
                properties.allocationSize == 0 || properties.memoryTypeBits == 0) {
            throw std::runtime_error("fixed AHB Vulkan format/properties mismatch");
        }

        const VkExternalMemoryImageCreateInfo externalImage{
            .sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO,
            .handleTypes =
                    VK_EXTERNAL_MEMORY_HANDLE_TYPE_ANDROID_HARDWARE_BUFFER_BIT_ANDROID,
        };
        const VkImageCreateInfo imageCreate{
            .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
            .pNext = &externalImage,
            .imageType = VK_IMAGE_TYPE_2D,
            .format = VK_FORMAT_R8G8B8A8_UNORM,
            .extent = {endpointExtent_.width, endpointExtent_.height, 1},
            .mipLevels = 1,
            .arrayLayers = 1,
            .samples = VK_SAMPLE_COUNT_1_BIT,
            .tiling = VK_IMAGE_TILING_OPTIMAL,
            .usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
                     VK_IMAGE_USAGE_TRANSFER_DST_BIT |
                     VK_IMAGE_USAGE_SAMPLED_BIT |
                     VK_IMAGE_USAGE_STORAGE_BIT,
            .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
            .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
        };
        ImportedImage result;
        result.extent = endpointExtent_;
        requireSuccess(deviceFunctions_.vkCreateImage(
                device_, &imageCreate, nullptr, &result.image),
                       "create fixed AHB Vulkan image");
        try {
            const VkMemoryDedicatedAllocateInfo dedicated{
                .sType = VK_STRUCTURE_TYPE_MEMORY_DEDICATED_ALLOCATE_INFO,
                .image = result.image,
            };
            const VkImportAndroidHardwareBufferInfoANDROID import{
                .sType =
                        VK_STRUCTURE_TYPE_IMPORT_ANDROID_HARDWARE_BUFFER_INFO_ANDROID,
                .pNext = &dedicated,
                .buffer = buffer,
            };
            const VkMemoryAllocateInfo allocation{
                .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
                .pNext = &import,
                .allocationSize = properties.allocationSize,
                .memoryTypeIndex = compatibleMemoryType(
                        physicalDevice_, properties.memoryTypeBits),
            };
            requireSuccess(deviceFunctions_.vkAllocateMemory(
                    device_, &allocation, nullptr, &result.memory),
                           "import fixed AHB Vulkan memory");
            requireSuccess(deviceFunctions_.vkBindImageMemory(
                    device_, result.image, result.memory, 0),
                           "bind fixed AHB Vulkan memory");
            AHardwareBuffer_acquire(buffer);
            result.buffer = buffer;
            return result;
        } catch (...) {
            if (result.image != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroyImage(device_, result.image, nullptr);
            if (result.memory != VK_NULL_HANDLE)
                deviceFunctions_.vkFreeMemory(device_, result.memory, nullptr);
            throw;
        }
    }

    std::vector<ImportedImage*> allImportedImages() {
        std::vector<ImportedImage*> result;
        result.reserve(kFixedSlotCount * 3U);
        for (ImportedSlot& slot : imported_) {
            result.push_back(&slot.left);
            result.push_back(&slot.right);
            result.push_back(&slot.output);
        }
        return result;
    }

    void transitionFixedBuffersToExternal() {
        const auto images = allImportedImages();
        VkCommandBuffer command = VK_NULL_HANDLE;
        const VkCommandBufferAllocateInfo commandAllocate{
            .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            .commandPool = setupCommandPool_,
            .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
            .commandBufferCount = 1,
        };
        requireSuccess(deviceFunctions_.vkAllocateCommandBuffers(
                device_, &commandAllocate, &command),
                       "allocate owned setup command buffer");
        VkFence fence = VK_NULL_HANDLE;
        const VkFenceCreateInfo fenceCreate{
            .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO,
        };
        requireSuccess(deviceFunctions_.vkCreateFence(
                device_, &fenceCreate, nullptr, &fence),
                       "create owned setup fence");
        try {
            const VkCommandBufferBeginInfo begin{
                .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
                .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
            };
            requireSuccess(deviceFunctions_.vkBeginCommandBuffer(command, &begin),
                           "begin owned setup command");
            std::vector<VkImageMemoryBarrier> initialize;
            initialize.reserve(images.size());
            for (const ImportedImage* image : images) {
                initialize.push_back(VkImageMemoryBarrier{
                    .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                    .srcAccessMask = 0,
                    .dstAccessMask = 0,
                    .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED,
                    .newLayout = VK_IMAGE_LAYOUT_GENERAL,
                    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .image = image->image,
                    .subresourceRange = {
                        VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1,
                    },
                });
            }
            deviceFunctions_.vkCmdPipelineBarrier(command,
                    VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                    VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, 0,
                    0, nullptr, 0, nullptr,
                    static_cast<uint32_t>(initialize.size()), initialize.data());
            std::vector<VkImageMemoryBarrier> release;
            release.reserve(images.size());
            for (const ImportedImage* image : images) {
                release.push_back(VkImageMemoryBarrier{
                    .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
                    .srcAccessMask = 0,
                    .dstAccessMask = 0,
                    .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
                    .newLayout = VK_IMAGE_LAYOUT_GENERAL,
                    .srcQueueFamilyIndex = queueFamily_,
                    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_EXTERNAL,
                    .image = image->image,
                    .subresourceRange = {
                        VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1,
                    },
                });
            }
            deviceFunctions_.vkCmdPipelineBarrier(command,
                    VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                    VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, 0,
                    0, nullptr, 0, nullptr,
                    static_cast<uint32_t>(release.size()), release.data());
            requireSuccess(deviceFunctions_.vkEndCommandBuffer(command),
                           "end owned setup command");
            const VkSubmitInfo submit{
                .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                .commandBufferCount = 1,
                .pCommandBuffers = &command,
            };
            requireSuccess(deviceFunctions_.vkQueueSubmit(queue_, 1, &submit, fence),
                           "submit owned setup command");
            requireSuccess(deviceFunctions_.vkWaitForFences(
                    device_, 1, &fence, VK_TRUE, kSetupFenceTimeoutNs),
                           "wait owned setup fence");
        } catch (...) {
            deviceFunctions_.vkDestroyFence(device_, fence, nullptr);
            deviceFunctions_.vkFreeCommandBuffers(
                    device_, setupCommandPool_, 1, &command);
            throw;
        }
        deviceFunctions_.vkDestroyFence(device_, fence, nullptr);
        deviceFunctions_.vkFreeCommandBuffers(device_, setupCommandPool_, 1, &command);
    }

    void destroyImportedImage(ImportedImage& image) {
        if (image.image != VK_NULL_HANDLE)
            deviceFunctions_.vkDestroyImage(device_, image.image, nullptr);
        if (image.memory != VK_NULL_HANDLE)
            deviceFunctions_.vkFreeMemory(device_, image.memory, nullptr);
        if (image.buffer != nullptr) AHardwareBuffer_release(image.buffer);
        image = {};
    }

    ImportedImage& cachedSourceImage(AHardwareBuffer* buffer) {
        const auto found = sourceCache_.find(buffer);
        if (found != sourceCache_.end()) return found->second;
        ImportedImage imported = importSourceImage(buffer);
        const auto inserted = sourceCache_.emplace(buffer, std::move(imported));
        if (!inserted.second)
            throw std::runtime_error("source AHB cache insertion failed");
        return inserted.first->second;
    }

    void destroySourceCache() noexcept {
        for (auto& entry : sourceCache_) destroyImportedImage(entry.second);
        sourceCache_.clear();
    }

    void destroyImportedImages() {
        if (device_ == VK_NULL_HANDLE) return;
        for (ImportedSlot& slot : imported_) {
            destroyImportedImage(slot.output);
            destroyImportedImage(slot.right);
            destroyImportedImage(slot.left);
        }
    }

    void close() noexcept {
        if (device_ != VK_NULL_HANDLE) {
            // Teardown only. Live enqueue/poll never calls a device-idle wait.
            deviceFunctions_.vkDeviceWaitIdle(device_);
            destroyTripletCapture();
            destroyLiveResources();
            destroySourceCache();
            destroyImportedImages();
            if (setupCommandPool_ != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroyCommandPool(
                        device_, setupCommandPool_, nullptr);
            if (swapchain_ != VK_NULL_HANDLE)
                deviceFunctions_.vkDestroySwapchainKHR(device_, swapchain_, nullptr);
            deviceFunctions_.vkDestroyDevice(device_, nullptr);
        }
        if (surface_ != VK_NULL_HANDLE && destroySurface_ != nullptr)
            destroySurface_(instance_, surface_, nullptr);
        if (instance_ != VK_NULL_HANDLE && destroyInstance_ != nullptr)
            destroyInstance_(instance_, nullptr);
        setupCommandPool_ = VK_NULL_HANDLE;
        swapchain_ = VK_NULL_HANDLE;
        swapchainImages_.clear();
        device_ = VK_NULL_HANDLE;
        queue_ = VK_NULL_HANDLE;
        physicalDevice_ = VK_NULL_HANDLE;
        surface_ = VK_NULL_HANDLE;
        instance_ = VK_NULL_HANDLE;
    }

    VkInstance instance_ = VK_NULL_HANDLE;
    VkPhysicalDevice physicalDevice_ = VK_NULL_HANDLE;
    VkDevice device_ = VK_NULL_HANDLE;
    VkQueue queue_ = VK_NULL_HANDLE;
    VkSurfaceKHR surface_ = VK_NULL_HANDLE;
    VkSwapchainKHR swapchain_ = VK_NULL_HANDLE;
    VkCommandPool setupCommandPool_ = VK_NULL_HANDLE;
    VkExtent2D endpointExtent_{};
    VkPhysicalDeviceMemoryProperties memoryProperties_{};
    uint32_t queueFamily_ = UINT32_MAX;
    std::vector<const char*> requiredDeviceExtensions_;
    std::vector<VkImage> swapchainImages_;
    std::vector<bool> swapchainInitialized_;
    std::array<ImportedSlot, kFixedSlotCount> imported_{};
    std::array<LiveSlot, kFixedSlotCount> live_{};
    std::unordered_map<AHardwareBuffer*, ImportedImage> sourceCache_;
    std::unordered_map<uint32_t, VkPastPresentationTimingGOOGLE>
            completedTimings_;
    uint32_t nextLiveSlot_ = 0;
    uint32_t inferenceSlot_ = UINT32_MAX;
    uint32_t pendingPresentations_ = 0;
    uint64_t surfaceCutoffDrops_ = 0;
    uint64_t surfaceCutoffRetired_ = 0;
    bool surfaceCutoffQuarantineLogged_ = false;
    uint32_t nextWsiPresentId_ = 1;
    uint64_t presentationEpoch_ = 0;
    uint64_t pastTimingQueries_ = 0;
    uint64_t pastTimingNonzeroQueries_ = 0;
    uint64_t pastTimingRecords_ = 0;
    bool fatal_ = false;
    std::unique_ptr<TripletCaptureWriter> tripletWriter_;
    VkBuffer captureBuffer_ = VK_NULL_HANDLE;
    VkDeviceMemory captureMemory_ = VK_NULL_HANDLE;
    void* captureMapped_ = nullptr;
    VkDeviceSize captureBytes_ = 0;
    bool captureCoherent_ = false;
    uint64_t captureNotBeforeNs_ = 0;
    VolkDeviceTable deviceFunctions_{};
    Capabilities capabilities_{};

    PFN_vkCreateAndroidSurfaceKHR createAndroidSurface_ = nullptr;
    PFN_vkDestroyInstance destroyInstance_ = nullptr;
    PFN_vkDestroySurfaceKHR destroySurface_ = nullptr;
    PFN_vkGetPhysicalDeviceSurfaceSupportKHR surfaceSupport_ = nullptr;
    PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR surfaceCapabilities_ = nullptr;
    PFN_vkGetPhysicalDeviceSurfaceFormatsKHR surfaceFormats_ = nullptr;
    PFN_vkGetPhysicalDeviceSurfacePresentModesKHR surfacePresentModes_ = nullptr;
};

OwnedVulkanHost::OwnedVulkanHost() : impl_(std::make_unique<Impl>()) {}
OwnedVulkanHost::~OwnedVulkanHost() = default;

void OwnedVulkanHost::open(ANativeWindow* window, uint32_t endpointWidth,
                           uint32_t endpointHeight) {
    impl_->open(window, endpointWidth, endpointHeight);
}

void OwnedVulkanHost::importAndPrepareFixedBuffers(
        const std::array<FixedBuffers, kFixedSlotCount>& buffers) {
    impl_->importAndPrepareFixedBuffers(buffers);
}

void OwnedVulkanHost::prepareSourceImage(AHardwareBuffer* buffer) {
    impl_->prepareSourceImage(buffer);
}

bool OwnedVulkanHost::referencesSourceImage(AHardwareBuffer* buffer) {
    return impl_->referencesSourceImage(buffer);
}

std::optional<OwnedVulkanHost::PreparedPresentation>
OwnedVulkanHost::tryPrepare(const LiveRequest& request) {
    return impl_->tryPrepare(request);
}

std::optional<OwnedVulkanHost::PreparedPresentation>
OwnedVulkanHost::tryPreparePrivateGenerated(
        AHardwareBuffer* left, AHardwareBuffer* right) {
    return impl_->tryPreparePrivateGenerated(left, right);
}

void OwnedVulkanHost::reserveInferenceSlot(uint32_t slotIndex) {
    impl_->reserveInferenceSlot(slotIndex);
}

uint32_t OwnedVulkanHost::reserveIdleInferenceSlot() {
    return impl_->reserveIdleInferenceSlot();
}

std::optional<OwnedVulkanHost::PreparedPresentation>
OwnedVulkanHost::tryPrepareContinuousInputs(AHardwareBuffer* previous,
        AHardwareBuffer* next, unsigned nextInput) {
    return impl_->tryPrepareContinuousInputs(previous, next, nextInput);
}

std::optional<OwnedVulkanHost::PreparedPresentation>
OwnedVulkanHost::tryPreparePrivateEndpointPair(
        AHardwareBuffer* left, AHardwareBuffer* right) {
    return impl_->tryPreparePrivateEndpointPair(left, right);
}

std::optional<OwnedVulkanHost::PreparedPresentation>
OwnedVulkanHost::tryCopyCompletedGenerated(AHardwareBuffer* left,
        AHardwareBuffer* right, AHardwareBuffer* generated, int completionFd) {
    return impl_->tryCopyCompletedGenerated(left, right, generated, completionFd);
}

void OwnedVulkanHost::holdPrivatePrepared(
        const PreparedPresentation& prepared, int outputReadySyncFd) {
    impl_->holdPrivatePrepared(prepared, outputReadySyncFd);
}

uint32_t OwnedVulkanHost::privatePreparedPairStatus(
        const PreparedPresentation& prepared) {
    return impl_->privatePreparedPairStatus(prepared);
}

bool OwnedVulkanHost::activatePrivatePrepared(
        const PreparedPresentation& prepared, const LiveRequest& request) {
    return impl_->activatePrivatePrepared(prepared, request);
}

void OwnedVulkanHost::abandonPrivatePrepared(
        const PreparedPresentation& prepared) {
    impl_->abandonPrivatePrepared(prepared);
}

void OwnedVulkanHost::presentPrepared(
        const PreparedPresentation& prepared, int outputReadySyncFd) {
    impl_->presentPrepared(prepared, outputReadySyncFd);
}

std::optional<OwnedVulkanHost::SurfaceSubmission>
OwnedVulkanHost::pollSurfaceSubmission() {
    return impl_->pollSurfaceSubmission();
}

std::optional<OwnedVulkanHost::Completion>
OwnedVulkanHost::pollSurfaceCompletion(
        uint64_t presentId, uint64_t desiredPresentTimeNs,
        uint64_t latchTimeNs, uint64_t actualPresentTimeNs) {
    return impl_->pollSurfaceCompletion(
            presentId, desiredPresentTimeNs, latchTimeNs,
            actualPresentTimeNs);
}

void OwnedVulkanHost::dropSurfacePresentation(uint64_t presentId) {
    impl_->dropSurfacePresentation(presentId);
}

std::optional<OwnedVulkanHost::Completion>
OwnedVulkanHost::pollDroppedSurfacePresentation() {
    return impl_->pollDroppedSurfacePresentation();
}

uint64_t OwnedVulkanHost::oldestPendingSurfacePresentId() const {
    return impl_->oldestPendingSurfacePresentId();
}

void OwnedVulkanHost::retireSurfacePresentation(uint64_t presentId) {
    impl_->retireSurfacePresentation(presentId);
}

void OwnedVulkanHost::abandonPrepared(
        const PreparedPresentation& prepared) {
    impl_->abandonPrepared(prepared);
}

std::optional<OwnedVulkanHost::Completion>
OwnedVulkanHost::pollCompletion() {
    return impl_->pollCompletion();
}

void OwnedVulkanHost::resetTimeline(uint64_t presentationEpoch) {
    impl_->resetTimeline(presentationEpoch);
}

const OwnedVulkanHost::Capabilities& OwnedVulkanHost::capabilities() const {
    return impl_->capabilities();
}

std::string OwnedVulkanHost::capabilityJson() const {
    return impl_->capabilityJson();
}

std::string OwnedVulkanHost::diagnosticJson() const {
    return impl_->diagnosticJson();
}

}  // namespace emufusion::lsfg
