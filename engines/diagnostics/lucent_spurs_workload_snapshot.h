#pragma once

// Diagnostic only: caller supplies owner-thread snapshots, not guest pointers.
#include <cstdint>
#include <cstdio>

namespace lucent_spurs_workload
{
inline uint64_t big_endian(const unsigned char* bytes, unsigned count) noexcept
{
    uint64_t value = 0;
    for (unsigned i = 0; i < count; ++i) value = (value << 8) | bytes[i];
    return value;
}

template <unsigned N>
inline void hex(const unsigned char (&bytes)[N], char (&out)[N * 2 + 1]) noexcept
{
    constexpr char digits[] = "0123456789abcdef";
    for (unsigned i = 0; i < N; ++i)
    {
        out[2 * i] = digits[bytes[i] >> 4];
        out[2 * i + 1] = digits[bytes[i] & 15];
    }
    out[N * 2] = 0;
}

struct snapshot
{
    uint32_t spurs, group_id, index, max_num, max_run, running;
    bool entered_wait, waited;
    // Pinned cellSpurs.h: LS 0x180..0x1ff. No reread of arbitrary guest EA.
    unsigned char kernel[128]{};
    // Owner's accepted reservation buffer; may be stale when raddr == 0.
    unsigned char reservation[128]{};
};

template <typename Sink>
inline void emit(const char* command_line, const snapshot& s, Sink&& sink) noexcept
{
    char kernel[257], reservation[257], line[2304];
    hex(s.kernel, kernel);
    hex(s.reservation, reservation);
    const uint64_t context_spurs = big_endian(s.kernel + 0x40, 8);
    const bool valid = context_spurs == s.spurs;
    // Decoded fields are meaningful ONLY when ctx_matches=1; retain raw bytes
    // so incompatible LLE layouts cannot silently masquerade as HLE structures.
    std::snprintf(line, sizeof(line),
        "workload_v=1 %s spurs=%08x group=%08x index=%u max_num=%u max_run=%u running=%u "
        "entered_wait=%u waited=%u ctx_spurs=%016llx ctx_matches=%u "
        "wkl_addr=%016llx wkl_id=%u idle=%u runnable1=%04x runnable2=%04x "
        "kernel_ls180=%s owner_rdata=%s",
        command_line, s.spurs, s.group_id, s.index, s.max_num, s.max_run, s.running,
        unsigned(s.entered_wait), unsigned(s.waited),
        static_cast<unsigned long long>(context_spurs), unsigned(valid),
        static_cast<unsigned long long>(big_endian(s.kernel + 0x50, 8)),
        unsigned(big_endian(s.kernel + 0x5c, 4)), unsigned(s.kernel[0x6b]),
        unsigned(big_endian(s.kernel + 0x6c, 2)), unsigned(big_endian(s.kernel + 0x6e, 2)),
        kernel, reservation);
    sink(line);
}
}
