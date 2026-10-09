// Synthetic mapped-buffer fixtures; no emulator/device evidence is fabricated.
#include "triplet_capture.hpp"
#include "midpoint_timestamp.hpp"

#include <atomic>
#include <cassert>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <future>
#include <iostream>
#include <iterator>
#include <string>
#include <thread>
#include <vector>
#include <unistd.h>

using emufusion::lsfg::TripletCaptureWriter;
using namespace std::chrono_literals;

std::vector<uint8_t> read(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

TripletCaptureWriter::Identity identity() {
    return {1, 2, 10, 11, 100, 200, 150, 20, 280, 300, 250, 8};
}

int main() {
    char name[] = "/tmp/emufusion-triplet-fixture-XXXXXX";
    const char* created = ::mkdtemp(name);
    assert(created);
    const std::filesystem::path root(created);
    std::vector<uint8_t> bytes(2 * 2 * 4 * 3);
    for (size_t i = 0; i < bytes.size(); ++i) bytes[i] = static_cast<uint8_t>(i * 3 + 1);
    auto logger = [](const std::string&) {};
    using emufusion::lsfg::isFloorMidpointTimestamp;
    assert(isFloorMidpointTimestamp(100, 201, 150));
    assert(!isFloorMidpointTimestamp(100, 201, 151));
    assert(isFloorMidpointTimestamp(UINT64_MAX - 103, UINT64_MAX - 2, UINT64_MAX - 53));
    assert(!isFloorMidpointTimestamp(100, 101, 100));
    assert(!isFloorMidpointTimestamp(201, 100, 150));
    assert(TripletCaptureWriter::checkedBytes(1920, 1080) == 24883200);
    for (auto size : {std::pair<uint32_t, uint32_t>{0, 1}, {3840, 2160}, {UINT32_MAX, UINT32_MAX}}) {
        bool rejected = false;
        try { (void)TripletCaptureWriter::checkedBytes(size.first, size.second); }
        catch (const std::invalid_argument&) { rejected = true; }
        assert(rejected);
    }
    {
        std::promise<void> entered, allowRead;
        auto enteredFuture = entered.get_future();
        auto release = allowRead.get_future().share();
        std::atomic<bool> closed{false};
        TripletCaptureWriter writer(bytes.data(), 2, 2, 1, 1, 1, (root / "async").string(), [&] {
            entered.set_value();
            release.wait(); // Simulates a slow mapping invalidate/disk worker.
            return true;
        }, logger);
        assert(writer.reserve() == 0); // Explicit skipped pair, no readback.
        const auto id = writer.reserve();
        assert(id == 1);
        assert(enteredFuture.wait_for(10ms) == std::future_status::timeout);
        const auto before = std::chrono::steady_clock::now();
        assert(writer.submit(id, identity()));
        assert(std::chrono::steady_clock::now() - before < 100ms);
        assert(enteredFuture.wait_for(1s) == std::future_status::ready);
        assert(writer.reserve() == 0); // Cannot recycle mapping while worker reads.
        std::thread closer([&] { writer.close(); closed.store(true); });
        std::this_thread::sleep_for(10ms);
        assert(!closed.load()); // Owner cannot unmap/free until writer returns.
        allowRead.set_value();
        closer.join();
        const auto stats = writer.stats();
        assert(stats.selected == 1 && stats.completed == 1 && stats.failed == 0 && stats.discarded == 0);
        for (size_t i = 0; i < 3; ++i) {
            const char label[] = {'A', 'G', 'B'};
            const auto output = read(root / "async" / (std::string("capture-1-") + label[i] + ".rgba"));
            assert(output == std::vector<uint8_t>(bytes.begin() + i * 16, bytes.begin() + (i + 1) * 16));
        }
        const auto metadata = read(root / "async" / "capture-1.json");
        const std::string text(metadata.begin(), metadata.end());
        assert(text.find("\"present_id\":20") != std::string::npos);
        assert(text.find("\"presentation_epoch\":2") != std::string::npos);
        assert(text.find("\"phase_numerator\":1,\"phase_denominator\":2") != std::string::npos);
        assert(text.find("\"content_timestamp_rounding\":\"floor-nanosecond\"") != std::string::npos);
        assert(text.find("\"quality_status\":\"UNVERIFIED\"") != std::string::npos);
        assert(!std::filesystem::exists(root / "async" / "capture-1.json.tmp"));
    }
    {
        TripletCaptureWriter writer(bytes.data(), 2, 2, 3, 0, 1, (root / "cancel").string(), [] { return true; }, logger);
        const auto first = writer.reserve();
        assert(first == 1 && writer.reserve() == 0);
        assert(!writer.submit(100, identity())); // Wrong private buffer identity cannot publish.
        writer.discard(first, "synthetic-abandon-after-fence");
        const auto second = writer.reserve();
        auto invalid = identity();
        invalid.actualPresentNs = 120; // Before the right endpoint exists.
        assert(!writer.submit(second, invalid));
        assert(writer.reserve() == 3);
        writer.close(); // Unpresented private capture is reported as discarded.
        const auto stats = writer.stats();
        assert(stats.selected == 3 && stats.discarded == 3 && stats.completed == 0 && stats.skippedBusy == 1);
        assert(!std::filesystem::exists(root / "cancel" / "capture-1.json"));
    }
    {
        TripletCaptureWriter writer(bytes.data(), 2, 2, 1, 0, 1, (root / "failure").string(), [] { return false; }, logger);
        assert(writer.submit(writer.reserve(), identity()));
        writer.close();
        assert(writer.stats().failed == 1 && writer.stats().completed == 0);
        assert(std::filesystem::exists(root / "failure" / "capture-1-FAILED.txt"));
        assert(!std::filesystem::exists(root / "failure" / "capture-1.json"));
    }
    {
        TripletCaptureWriter writer(bytes.data(), 2, 2, 1, 0, 1, (root / "file-failure").string(), [] { return true; }, logger);
        { std::ofstream existing(root / "file-failure" / "capture-1-A.rgba"); existing << "preserve"; }
        assert(writer.submit(writer.reserve(), identity()));
        writer.close();
        assert(writer.stats().failed == 1);
        assert(!std::filesystem::exists(root / "file-failure" / "capture-1.json"));
        const auto preserved = read(root / "file-failure" / "capture-1-A.rgba");
        assert(std::string(preserved.begin(), preserved.end()) == "preserve");
    }
    {
        TripletCaptureWriter writer(bytes.data(), 2, 2, 2, 2, 3, (root / "sampling").string(), [] { return true; }, logger);
        assert(writer.reserve() == 0 && writer.reserve() == 0);
        const auto id = writer.reserve(); // Eligible pair 3, then 6, 9, ...
        assert(id == 1);
        writer.discard(id, "synthetic sampling test");
        assert(writer.reserve() == 0 && writer.reserve() == 0);
        assert(writer.submit(writer.reserve(), identity()));
        writer.close();
        const auto json = read(root / "sampling" / "capture-2.json");
        const std::string text(json.begin(), json.end());
        assert(text.find("\"eligible_pair_ordinal\":6") != std::string::npos);
        assert(text.find("\"every_eligible_pairs\":3") != std::string::npos);
    }
    {
        TripletCaptureWriter writer(bytes.data(), 2, 2, 2, 0, 1, (root / "odd-span").string(), [] { return true; }, logger);
        auto odd = identity();
        odd.rightTimestampNs = 201;
        odd.contentTimestampNs = 151;
        assert(!writer.submit(writer.reserve(), odd)); // Ceil is not the integer representation used.
        odd.contentTimestampNs = 150;
        assert(writer.submit(writer.reserve(), odd));
        writer.close();
        assert(writer.stats().completed == 1 && writer.stats().discarded == 1);
        assert(std::filesystem::exists(root / "odd-span" / "capture-2.json"));
    }
    std::filesystem::remove_all(root); // Exact mkdtemp test-fixture directory only.
    std::cout << "PASS: bounded native triplet byte/identity/lifetime/failure fixtures\n";
}
