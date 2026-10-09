#pragma once
#include <cstdint>

namespace lucent_ppu_wait
{
struct budget
{
    static constexpr unsigned max_samples = 600;
    uint64_t calls = 0, last_us = 0;
    unsigned samples = 0, code_sites = 0;
    uint64_t sites[8]{};

    template <typename Clock>
    bool sample(Clock&& clock) noexcept
    {
        ++calls;
        if (samples >= max_samples) return false;
        const auto now = clock();
        if (samples && (now < last_us || now - last_us < 1'000'000)) return false;
        last_us = now;
        ++samples;
        return true;
    }

    bool new_code_site(uint64_t lr) noexcept
    {
        // A 32-instruction window around LR must stay within 32-bit guest memory.
        if ((lr & 3) || lr < 64 || lr > 0xffffffbfULL) return false;
        for (unsigned i = 0; i < code_sites; ++i) if (sites[i] == lr) return false;
        if (code_sites == 8) return false;
        sites[code_sites++] = lr;
        return true;
    }
};
}
