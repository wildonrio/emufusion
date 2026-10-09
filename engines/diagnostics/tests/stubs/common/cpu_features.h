#pragma once
#include <chrono>
#include <cstdint>
namespace Common {
inline int64_t test_time_ns = 1000000000000LL;
struct TestWallClock {
    std::chrono::nanoseconds GetTimeNS() const {
        return std::chrono::nanoseconds{test_time_ns};
    }
};
inline TestWallClock g_wall_clock;
}
