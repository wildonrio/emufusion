#pragma once

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

namespace emufusion::lsfg {

// Opt-in diagnostic transport only. No pixel analysis or successful quality
// verdict is inferred from a dump. The Vulkan owner supplies immutable bytes
// AFTER its existing fence signals and retains mapping until close() returns.
class TripletCaptureWriter final {
public:
    static constexpr uint64_t kMaximumBytes = 64ULL * 1024ULL * 1024ULL;
    static constexpr uint32_t kMaximumCaptures = 8;

    struct Identity {
        uint64_t sessionEpoch = 0;
        uint64_t presentationEpoch = 0;
        uint64_t leftSequence = 0;
        uint64_t rightSequence = 0;
        uint64_t leftTimestampNs = 0;
        uint64_t rightTimestampNs = 0;
        uint64_t contentTimestampNs = 0;
        uint64_t presentId = 0;
        uint64_t desiredPresentNs = 0;
        uint64_t actualPresentNs = 0;
        uint64_t gpuCompletionNs = 0;
        uint64_t refreshDurationNs = 0;
        uint64_t captureNotBeforeNs = 0;
        uint64_t endpointMadPpm = 0;
    };
    struct Stats {
        uint64_t selected = 0;
        uint64_t skippedBusy = 0;
        uint64_t completed = 0;
        uint64_t failed = 0;
        uint64_t discarded = 0;
    };

    static uint64_t checkedBytes(uint32_t width, uint32_t height);
    TripletCaptureWriter(const uint8_t* mapped, uint32_t width, uint32_t height,
                         uint32_t limit, uint32_t skipPairs, uint32_t everyPairs,
                         std::string directory,
                         std::function<bool()> prepareRead,
                         std::function<void(const std::string&)> diagnostic);
    ~TripletCaptureWriter();
    TripletCaptureWriter(const TripletCaptureWriter&) = delete;
    TripletCaptureWriter& operator=(const TripletCaptureWriter&) = delete;

    // Called only by the Vulkan owner's serialized thread. These operations
    // never wait for the writer, GPU, or filesystem. Zero means skip this pair.
    uint64_t reserve();
    bool submit(uint64_t captureId, const Identity& identity);
    void discard(uint64_t captureId, const char* reason);
    Stats stats() const;
    // Teardown only; joins a bounded-size pending write before mapping release.
    void close();

private:
    enum class State { Idle, Reserved, Queued };
    void work();
    void writeCapture(uint64_t captureId, uint64_t eligiblePair, const Identity& identity);
    void log(const std::string& message) noexcept;

    const uint8_t* mapped_;
    uint32_t width_, height_, limit_, skipPairs_, everyPairs_;
    uint64_t totalBytes_;
    std::string directory_;
    std::function<bool()> prepareRead_;
    std::function<void(const std::string&)> diagnostic_;
    std::atomic<State> state_{State::Idle};
    std::atomic<bool> stopping_{false};
    std::atomic<uint64_t> selected_{0}, skippedBusy_{0}, completed_{0}, failed_{0}, discarded_{0};
    uint64_t queuedId_ = 0;
    uint64_t eligiblePairs_ = 0, queuedEligiblePair_ = 0;
    Identity queuedIdentity_{};
    std::mutex waitMutex_;
    std::condition_variable wake_;
    std::thread worker_;
};

} // namespace emufusion::lsfg
