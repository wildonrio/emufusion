#include "../lucent_spurs_taskset_trace.h"
#include <cassert>
#include <string>
#include <vector>
#include <thread>
#include <stdexcept>

using namespace lucent_spurs_trace;
static std::vector<std::string> lines;
static std::vector<std::string> milestones;
static std::mutex capture_mutex;
static void capture(const char* line)
{
    std::lock_guard<std::mutex> lock(capture_mutex);
    std::string value(line);
    if (value.find("SPURS_TRACE READY ") == 0 || value.find("SPURS_TRACE TARGET ") == 0)
        milestones.push_back(value);
    else lines.push_back(value);
}

int main()
{
    std::array<unsigned char, 256> data{};
    data[0] = 0x20; data[0x50] = 0x20;
    auto bad = snapshot("GETLLAR", 7, 0xf00, target, 0x2700, 128, data.data(), 128);
    assert(invalid(bad));
    auto partial = snapshot("DMA-PUT", 7, 0, target + 0x50, 0, 4, data.data(), 0);
    assert(partial.offset == 0x50 && partial.length == 4 && !invalid(partial));
    auto crossing = snapshot("DMA-PUT", 7, 0, target - 64, 0, 256, data.data(), 0);
    assert(crossing.offset == 0 && crossing.length == 128);
    assert(crossing.bytes[16] == 0x20); // source[64 + 16]
    assert(!overlap(target - 128, 128));
    assert(!overlap(target + 128, 4));
    assert(!overlap(0xfffffff0, 0x100)); // widened, no 32-bit wrap alias
    assert(!overlap(target, 0));
    assert(snapshot("absent", 0, 0, 0, 0, 128, nullptr, 0).length == 0);

    journal bounded;
    bounded.observe_read_hook(target + 128, nullptr); // Missing sink consumes nothing.
    bounded.observe_read_hook(target + 128, capture);
    bounded.observe_read_hook(target, capture);
    assert(milestones.size() == 1);
    assert(milestones[0].find("first_ea=31ee7700") != std::string::npos);
    bounded.append(record{}, capture); // Empty observation is not a target hit.
    assert(milestones.size() == 1);
    for (unsigned i = 0; i < 300; ++i) bounded.append(partial, capture);
    assert(milestones.size() == 2);
    assert(milestones[1].find("offset=80 length=4") != std::string::npos);
    bad.outcome = -1;
    bounded.append(bad, capture); // Invalid intended data alone is not a read failure.
    assert(lines.empty());
    bad.outcome = 2;
    bounded.append(bad, capture);
    assert(lines.size() == capacity + 2);
    assert(lines.front().find("count=302 retained=256") != std::string::npos);
    assert(lines[1].find("seq=47 ") != std::string::npos);
    assert(lines[capacity].find("outcome=2") != std::string::npos);
    bounded.append(bad, capture);
    assert(lines.size() == capacity + 2); // one dump per process/journal

    lines.clear();
    milestones.clear();
    std::uint64_t stamp = 128;
    std::uint32_t address = target;
    auto good = bad; good.bytes[0x50] = 0; good.outcome = -1;
    { write_scope attempt(good, capture); attempt.finish(false); }
    try { write_scope attempt(good, capture); throw std::runtime_error("test"); }
    catch (const std::runtime_error&) {}
    try
    {
        read_scope read(7, 0xf00, target, 0x2700, data.data(), stamp, address, capture);
        throw std::runtime_error("test");
    }
    catch (const std::runtime_error&) {}
    assert(lines.empty());
    assert(milestones.size() == 2); // TARGET write, then READY even on read unwind.
    { read_scope read(7, 0xf00, target, 0x2700, data.data(), stamp, address, capture); }
    assert(lines.size() == 7); // two attempts/failures, one accepted read, boundaries
    assert(lines[2].find("outcome=0") != std::string::npos);
    assert(lines[4].find("outcome=0") != std::string::npos);
    assert(lines[5].find("outcome=2") != std::string::npos);

    lines.clear();
    milestones.clear();
    journal concurrent;
    std::vector<std::thread> workers;
    for (int t = 0; t < 4; ++t)
        workers.emplace_back([&] {
            for (int i = 0; i < 1000; ++i) {
                concurrent.observe_read_hook(target, capture);
                concurrent.append(good, capture);
            }
        });
    for (auto& worker : workers) worker.join();
    concurrent.append(bad, capture);
    assert(lines.front().find("count=4001 retained=256") != std::string::npos);
    assert(lines.size() == capacity + 2);
    assert(milestones.size() == 2); // One READY and TARGET despite concurrent callers.
    std::puts("SPURS trace bounds, overlap, trigger, outcomes, unwind, liveness and concurrency PASS");
}
