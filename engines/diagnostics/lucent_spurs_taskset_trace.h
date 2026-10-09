#pragma once

// Local diagnostic only. SPUThread.cpp includes this solely when compiled with
// LUCENT_SPURS_TASKSET_TRACE. No guest-memory reads/writes occur in this helper.
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <mutex>

namespace lucent_spurs_trace
{
constexpr std::uint32_t target = 0x31ee7680;
constexpr std::size_t capacity = 256;
using sink = void (*)(const char*);

struct record
{
    std::uint64_t sequence = 0;
    std::uint64_t operation = 0;
    std::uint64_t reservation = 0; // SPU's saved reservation, not a memory timestamp.
    std::uint32_t thread = 0;
    std::uint32_t pc = 0;
    std::uint32_t ea = 0;
    std::uint32_t lsa = 0;
    const char* kind = "";
    int outcome = -1; // -1 attempt, 0 failed, 1 completed, 2 accepted read.
    unsigned offset = 0;
    unsigned length = 0;
    std::array<unsigned char, 128> bytes{};
};

inline bool overlap(std::uint32_t ea, std::uint32_t length)
{
    return length && std::uint64_t(ea) < std::uint64_t(target) + 128 &&
           std::uint64_t(ea) + length > target;
}

inline bool invalid(const record& r)
{
    // The 128-bit running and waiting masks occupy 0x00 and 0x50.
    // Bytewise intersection is endian independent. Partial DMA snapshots
    // must never be interpreted as a complete taskset.
    if (r.offset != 0 || r.length != 128) return false;
    for (unsigned i = 0; i < 16; ++i)
        if (r.bytes[i] & r.bytes[0x50 + i]) return true;
    return false;
}

inline record snapshot(const char* kind, std::uint32_t thread, std::uint32_t pc,
                       std::uint32_t ea, std::uint32_t lsa, std::uint32_t length,
                       const void* source, std::uint64_t reservation)
{
    record r;
    r.kind = kind; r.thread = thread; r.pc = pc; r.ea = ea;
    r.lsa = lsa; r.reservation = reservation;
    if (!overlap(ea, length) || !source) return r;
    const auto first = std::uint64_t(ea) < target ? target : std::uint64_t(ea);
    const auto last = std::uint64_t(ea) + length < std::uint64_t(target) + 128
        ? std::uint64_t(ea) + length : std::uint64_t(target) + 128;
    r.offset = static_cast<unsigned>(first - target);
    r.length = static_cast<unsigned>(last - first);
    std::memcpy(r.bytes.data() + r.offset,
                static_cast<const unsigned char*>(source) + (first - ea), r.length);
    return r;
}

class journal
{
    std::mutex mutex;
    std::array<record, capacity> entries{};
    std::uint64_t count = 0;
    std::atomic<bool> dumped{false};
    std::atomic<bool> read_hook_reported{false};
    bool target_reported = false;

public:
    void observe_read_hook(std::uint32_t ea, sink output)
    {
        if (!output || read_hook_reported.load(std::memory_order_relaxed)) return;
        std::lock_guard<std::mutex> lock(mutex);
        if (read_hook_reported.load(std::memory_order_relaxed)) return;
        read_hook_reported.store(true, std::memory_order_relaxed);
        char line[160];
        std::snprintf(line, sizeof(line),
            "SPURS_TRACE READY hook=GETLLAR first_ea=%08x target=%08x", ea, target);
        output(line);
    }

    std::uint64_t append(record r, sink output)
    {
        if (!r.length || dumped.load(std::memory_order_relaxed)) return 0;
        // This lock protects only diagnostic copies, never the guest operation.
        // Observation order is NOT a claimed memory-linearization order.
        std::lock_guard<std::mutex> lock(mutex);
        if (dumped.load(std::memory_order_relaxed)) return 0;
        r.sequence = ++count;
        if (!r.operation) r.operation = r.sequence;
        entries[(count - 1) % capacity] = r;
        if (output && !target_reported)
        {
            target_reported = true;
            char line[224];
            std::snprintf(line, sizeof(line),
                "SPURS_TRACE TARGET target=%08x kind=%s outcome=%d offset=%u length=%u",
                target, r.kind, r.outcome, r.offset, r.length);
            output(line);
        }
        if (r.outcome != 2 || !invalid(r)) return r.operation;
        dumped.store(true, std::memory_order_relaxed);
        if (!output) return r.operation;
        char line[768];
        std::snprintf(line, sizeof(line),
            "SPURS_TRACE BEGIN target=%08x count=%llu retained=%llu trigger=accepted-overlap",
            target, static_cast<unsigned long long>(count),
            static_cast<unsigned long long>(count < capacity ? count : capacity));
        output(line);
        const auto begin = count > capacity ? count - capacity : 0;
        for (auto i = begin; i < count; ++i)
        {
            const auto& e = entries[i % capacity];
            char hex[257];
            static constexpr char digits[] = "0123456789abcdef";
            for (unsigned j = 0; j < 128; ++j)
            {
                hex[j * 2] = digits[e.bytes[j] >> 4];
                hex[j * 2 + 1] = digits[e.bytes[j] & 15];
            }
            hex[256] = 0;
            std::snprintf(line, sizeof(line),
                "SPURS_TRACE seq=%llu op=%llu kind=%s outcome=%d tid=%08x pc=%05x ea=%08x lsa=%05x saved_res=%llu offset=%u length=%u data=%s",
                static_cast<unsigned long long>(e.sequence),
                static_cast<unsigned long long>(e.operation), e.kind, e.outcome,
                e.thread, e.pc, e.ea, e.lsa,
                static_cast<unsigned long long>(e.reservation), e.offset, e.length, hex);
            output(line);
        }
        output("SPURS_TRACE END");
        return r.operation;
    }
};

inline journal history;

class write_scope
{
    record r;
    sink output;
    int exceptions = std::uncaught_exceptions();
public:
    write_scope(record value, sink destination) : r(value), output(destination)
    {
        r.operation = history.append(r, output);
    }
    void finish(bool completed)
    {
        if (!r.operation) return;
        r.outcome = completed ? 1 : 0;
        history.append(r, output);
        r.operation = 0;
    }
    ~write_scope()
    {
        // A completion records that the function returned, not that every
        // store took effect. Exceptions are never labeled completed.
        finish(std::uncaught_exceptions() == exceptions);
    }
};

class read_scope
{
    std::uint32_t thread, pc, ea, lsa;
    const void* accepted;
    const std::uint64_t& saved_reservation;
    const std::uint32_t& reservation_address;
    sink output;
    int exceptions = std::uncaught_exceptions();
public:
    read_scope(std::uint32_t t, std::uint32_t p, std::uint32_t e, std::uint32_t l,
               const void* data, const std::uint64_t& saved,
               const std::uint32_t& address, sink destination)
        : thread(t), pc(p), ea(e), lsa(l), accepted(data),
          saved_reservation(saved), reservation_address(address), output(destination)
    {
        // Proves this hook executes even if this launch uses a different EA.
        // No guest-memory access and at most one READY line per journal.
        history.observe_read_hook(ea, output);
    }
    ~read_scope()
    {
        if (ea != target || std::uncaught_exceptions() != exceptions ||
            reservation_address != ea) return;
        auto r = snapshot("GETLLAR", thread, pc, ea, lsa, 128,
                          accepted, saved_reservation);
        r.outcome = 2;
        history.append(r, output);
    }
};
}
