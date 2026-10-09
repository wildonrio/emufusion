#include "triplet_capture.hpp"
#include "midpoint_timestamp.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>

namespace emufusion::lsfg {
namespace {
void writeExclusive(const std::string& path, const uint8_t* bytes, size_t count) {
    const int fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) throw std::runtime_error("capture open failed: " + std::string(std::strerror(errno)));
    size_t offset = 0;
    while (offset < count) {
        const size_t chunk = std::min<size_t>(count - offset, 1024 * 1024);
        const ssize_t written = ::write(fd, bytes + offset, chunk);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) {
            const int error = errno;
            ::close(fd);
            throw std::runtime_error("capture write failed: " + std::string(std::strerror(error)));
        }
        offset += static_cast<size_t>(written);
    }
    if (::close(fd) != 0) throw std::runtime_error("capture close failed");
}

void writeText(const std::string& path, const std::string& text) {
    writeExclusive(path, reinterpret_cast<const uint8_t*>(text.data()), text.size());
}

bool validIdentity(const TripletCaptureWriter::Identity& id) {
    return id.sessionEpoch > 0 && id.presentationEpoch > 0 && id.leftSequence > 0 &&
           id.rightSequence > id.leftSequence && id.rightSequence - id.leftSequence == 1 &&
           isFloorMidpointTimestamp(id.leftTimestampNs, id.rightTimestampNs, id.contentTimestampNs) &&
           id.presentId > 0 && id.desiredPresentNs > 0 && id.actualPresentNs >= id.rightTimestampNs &&
           id.gpuCompletionNs > 0 && id.gpuCompletionNs <= id.actualPresentNs && id.refreshDurationNs > 0;
}
} // namespace

uint64_t TripletCaptureWriter::checkedBytes(uint32_t width, uint32_t height) {
    if (width == 0 || height == 0 || static_cast<uint64_t>(width) > kMaximumBytes / 12 / height)
        throw std::invalid_argument("triplet exceeds 64 MiB capture memory bound");
    return static_cast<uint64_t>(width) * height * 12;
}

TripletCaptureWriter::TripletCaptureWriter(const uint8_t* mapped, uint32_t width,
        uint32_t height, uint32_t limit, uint32_t skipPairs, uint32_t everyPairs, std::string directory,
        std::function<bool()> prepareRead, std::function<void(const std::string&)> diagnostic)
    : mapped_(mapped), width_(width), height_(height), limit_(limit), skipPairs_(skipPairs), everyPairs_(everyPairs),
      totalBytes_(checkedBytes(width, height)), directory_(std::move(directory)),
      prepareRead_(std::move(prepareRead)), diagnostic_(std::move(diagnostic)) {
    if (mapped == nullptr || limit == 0 || limit > kMaximumCaptures || skipPairs > 100000 ||
            everyPairs == 0 || everyPairs > 100000 ||
            directory_.empty() || !prepareRead_)
        throw std::invalid_argument("invalid bounded triplet capture configuration");
    // This constructor runs during setup, never at a presentation deadline.
    if (::mkdir(directory_.c_str(), 0700) != 0)
        throw std::runtime_error("capture directory must be fresh: " + std::string(std::strerror(errno)));
    worker_ = std::thread([this] { work(); });
}

TripletCaptureWriter::~TripletCaptureWriter() { close(); }

uint64_t TripletCaptureWriter::reserve() {
    if (stopping_.load(std::memory_order_acquire) || selected_.load() >= limit_) return 0;
    const uint64_t eligiblePair = ++eligiblePairs_;
    if (eligiblePair <= skipPairs_ || (eligiblePair - skipPairs_ - 1) % everyPairs_ != 0) return 0;
    if (state_.load(std::memory_order_acquire) != State::Idle) { ++skippedBusy_; return 0; }
    queuedId_ = ++selected_;
    queuedEligiblePair_ = eligiblePair;
    state_.store(State::Reserved, std::memory_order_release);
    return queuedId_;
}

bool TripletCaptureWriter::submit(uint64_t captureId, const Identity& identity) {
    if (state_.load(std::memory_order_acquire) != State::Reserved || captureId != queuedId_)
        return false;
    if (!validIdentity(identity)) { discard(captureId, "invalid-physical-or-source-identity"); return false; }
    queuedIdentity_ = identity;
    state_.store(State::Queued, std::memory_order_release);
    wake_.notify_one();
    return true;
}

void TripletCaptureWriter::discard(uint64_t captureId, const char* reason) {
    if (state_.load(std::memory_order_acquire) == State::Reserved && captureId == queuedId_) {
        ++discarded_;
        log("LSFG capture discarded id=" + std::to_string(captureId) + " reason=" + reason);
        state_.store(State::Idle, std::memory_order_release);
    }
}

TripletCaptureWriter::Stats TripletCaptureWriter::stats() const {
    return {selected_.load(), skippedBusy_.load(), completed_.load(), failed_.load(), discarded_.load()};
}

void TripletCaptureWriter::close() {
    if (!worker_.joinable()) return;
    if (state_.load(std::memory_order_acquire) == State::Reserved)
        discard(queuedId_, "teardown-before-physical-completion");
    stopping_.store(true, std::memory_order_release);
    wake_.notify_one();
    worker_.join();
}

void TripletCaptureWriter::log(const std::string& message) noexcept {
    try { if (diagnostic_) diagnostic_(message); } catch (...) {}
}

void TripletCaptureWriter::work() {
    for (;;) {
        if (state_.load(std::memory_order_acquire) == State::Queued) {
            const uint64_t id = queuedId_;
            const uint64_t eligiblePair = queuedEligiblePair_;
            const Identity identity = queuedIdentity_;
            try {
                if (!prepareRead_()) throw std::runtime_error("mapped-memory invalidate failed");
                writeCapture(id, eligiblePair, identity);
                ++completed_;
                log("LSFG capture written id=" + std::to_string(id) + " directory=" + directory_);
            } catch (const std::exception& error) {
                ++failed_;
                log("LSFG capture write failed id=" + std::to_string(id) + " reason=" + error.what());
                try { writeText(directory_ + "/capture-" + std::to_string(id) + "-FAILED.txt", error.what()); }
                catch (...) {}
            }
            state_.store(State::Idle, std::memory_order_release);
        }
        if (stopping_.load(std::memory_order_acquire)) return;
        std::unique_lock<std::mutex> lock(waitMutex_);
        // Producer notification is deliberately lock-free; timeout closes the
        // check/wait lost-notification race without blocking the renderer.
        wake_.wait_for(lock, std::chrono::milliseconds(20), [this] {
            return stopping_.load(std::memory_order_acquire) ||
                   state_.load(std::memory_order_acquire) == State::Queued;
        });
    }
}

void TripletCaptureWriter::writeCapture(uint64_t captureId, uint64_t eligiblePair, const Identity& id) {
    const std::string prefix = directory_ + "/capture-" + std::to_string(captureId);
    const size_t imageBytes = static_cast<size_t>(totalBytes_ / 3);
    writeExclusive(prefix + "-A.rgba", mapped_, imageBytes);
    writeExclusive(prefix + "-G.rgba", mapped_ + imageBytes, imageBytes);
    writeExclusive(prefix + "-B.rgba", mapped_ + imageBytes * 2, imageBytes);
    std::ostringstream json;
    json << "{\n\"schema_version\":1,\"capture_id\":" << captureId
         << ",\"backend\":\"LSFG\",\"role_source\":\"immutable_native_request\""
         << ",\"capture_stage\":\"exact_fixed_AHB_before_surface_release\""
         << ",\"instrumented\":true,\"quality_status\":\"UNVERIFIED\""
         << ",\"pixel_format\":\"RGBA8_UNORM\",\"row_origin\":\"image_coordinate_y0\""
         << ",\"width\":" << width_ << ",\"height\":" << height_
         << ",\"row_stride_bytes\":" << static_cast<uint64_t>(width_) * 4
         << ",\"image_bytes\":" << imageBytes
         << ",\"clock_domain\":\"android_monotonic\",\"session_epoch\":" << id.sessionEpoch
         << ",\"presentation_epoch\":" << id.presentationEpoch
         << ",\"left_sequence\":" << id.leftSequence << ",\"right_sequence\":" << id.rightSequence
         << ",\"left_timestamp_ns\":" << id.leftTimestampNs
         << ",\"right_timestamp_ns\":" << id.rightTimestampNs
         << ",\"content_timestamp_ns\":" << id.contentTimestampNs
         << ",\"phase_numerator\":1,\"phase_denominator\":2"
         << ",\"content_timestamp_rounding\":\"floor-nanosecond\",\"present_id\":" << id.presentId
         << ",\"desired_present_ns\":" << id.desiredPresentNs
         << ",\"actual_present_ns\":" << id.actualPresentNs
         << ",\"gpu_completion_ns\":" << id.gpuCompletionNs
         << ",\"refresh_duration_ns\":" << id.refreshDurationNs
         << ",\"endpoint_mad_ppm\":" << id.endpointMadPpm
         << ",\"sampling\":{\"skip_eligible_pairs\":" << skipPairs_
         << ",\"every_eligible_pairs\":" << everyPairs_
         << ",\"eligible_pair_ordinal\":" << eligiblePair
         << ",\"not_before_monotonic_ns\":" << id.captureNotBeforeNs
         << ",\"motion_selection\":\"none; verify moving content offline\"}"
         << ",\"images\":{\"left\":\"capture-" << captureId << "-A.rgba\",\"generated\":\"capture-"
         << captureId << "-G.rgba\",\"right\":\"capture-" << captureId << "-B.rgba\"}}\n";
    // JSON is the completion marker: partial images without it are invalid.
    writeText(prefix + ".json.tmp", json.str());
    if (::rename((prefix + ".json.tmp").c_str(), (prefix + ".json").c_str()) != 0)
        throw std::runtime_error("capture metadata commit failed");
}
} // namespace emufusion::lsfg
