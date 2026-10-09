#pragma once
#include <chrono>
#include <cstdint>

namespace lucent_render_progress {
// Owner-local, per-call-site sampling. Counters are calls, NOT unique game frames.
struct Gate {
    std::uint64_t calls = 0;
    std::uint64_t last_ms = 0;
    bool initialized = false;

    bool sample(std::uint64_t now_ms) {
        ++calls;
        if (initialized && now_ms >= last_ms && now_ms - last_ms < 1000)
            return false;
        initialized = true;
        last_ms = now_ms;
        return true;
    }
};

inline std::uint64_t monotonic_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
} // namespace lucent_render_progress

// Arguments are evaluated only when a sample is due. No guest memory access,
// synchronization with emulation threads, image readback or GPU wait is added.
#define LUCENT_RENDER_PROGRESS(format, ...) do { \
    static thread_local lucent_render_progress::Gate lucent_progress_gate; \
    if (lucent_progress_gate.sample(lucent_render_progress::monotonic_ms())) \
        __android_log_print(ANDROID_LOG_INFO, "LucentRenderProgress", \
            "calls=%llu " format, \
            static_cast<unsigned long long>(lucent_progress_gate.calls), __VA_ARGS__); \
} while (false)
