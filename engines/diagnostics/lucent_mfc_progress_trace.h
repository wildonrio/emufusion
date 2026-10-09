#pragma once

// Diagnostic only. Called on the SPU owner thread, never by a polling thread.
// No guest-memory reads, state writes, channel consumption, or runtime policy.
#include <cstdint>
#include <cstdio>

namespace lucent_mfc_progress
{
enum class command { other, getllar, putllc };
enum class outcome { unknown, get_ok, put_ok, put_failed };

struct observation
{
    uint32_t owner, pc, cmd, eah, eal, lsa, raddr;
    uint64_t rtime, events;
};

struct counters
{
    uint64_t get_started = 0, put_started = 0;
    uint64_t get_ok = 0, put_ok = 0, put_failed = 0;
    uint64_t stopped = 0, unwound = 0, unknown = 0;
};

struct journal
{
    static constexpr unsigned max_pairs = 600;
    static constexpr uint64_t interval_us = 1'000'000;
    counters count;
    uint32_t owner = 0;
    bool have_owner = false;
    unsigned pairs = 0;
    uint64_t last_emit = 0;

    template <typename Snapshot, typename Sink>
    void emit(const char* phase, uint64_t stamp, unsigned pair,
              Snapshot& snapshot, Sink& sink) const noexcept
    {
        const observation s = snapshot();
        char line[1024];
        std::snprintf(line, sizeof(line),
            "v=1 pair=%u phase=%s us=%llu owner=%08x pc=%05x cmd=%02x "
            "eah=%08x eal=%08x lsa=%05x raddr=%08x rtime=%016llx events=%016llx "
            "get_started=%llu get_ok=%llu put_started=%llu put_ok=%llu put_failed=%llu "
            "stopped=%llu unwound=%llu unknown=%llu budget_left=%u",
            pair, phase, static_cast<unsigned long long>(stamp), s.owner, s.pc,
            s.cmd, s.eah, s.eal, s.lsa, s.raddr,
            static_cast<unsigned long long>(s.rtime), static_cast<unsigned long long>(s.events),
            static_cast<unsigned long long>(count.get_started),
            static_cast<unsigned long long>(count.get_ok),
            static_cast<unsigned long long>(count.put_started),
            static_cast<unsigned long long>(count.put_ok),
            static_cast<unsigned long long>(count.put_failed),
            static_cast<unsigned long long>(count.stopped),
            static_cast<unsigned long long>(count.unwound),
            static_cast<unsigned long long>(count.unknown), max_pairs - pairs);
        sink(line);
    }

    template <typename Operation, typename Result, typename Snapshot, typename Clock, typename Sink>
    bool run(command cmd, uint32_t current_owner, Operation&& operation,
             Result&& result, Snapshot&& snapshot, Clock&& clock, Sink&& sink)
    {
        if (cmd == command::other) return operation();
        if (!have_owner || owner != current_owner)
        {
            owner = current_owner;
            have_owner = true;
            count = {};
            // Do not reset the output/time budget when a native thread is reused.
        }
        if (cmd == command::getllar) ++count.get_started;
        else ++count.put_started;
        // Once exhausted, do not keep querying the clock or snapshotting state.
        const uint64_t now = pairs < max_pairs ? clock() : 0;
        const bool sampled = pairs < max_pairs &&
            (pairs == 0 || (now >= last_emit && now - last_emit >= interval_us));
        const unsigned pair = sampled ? ++pairs : 0;
        if (sampled)
        {
            last_emit = now;
            emit("enter", now, pair, snapshot, sink);
        }
#if defined(__cpp_exceptions)
        try
#endif
        {
            const bool completed = operation();
            if (!completed) ++count.stopped;
            else
            {
                // Result is read only after an actual successful command return.
                // An early false return or exception cannot reuse stale status.
                switch (result())
                {
                case outcome::get_ok: ++count.get_ok; break;
                case outcome::put_ok: ++count.put_ok; break;
                case outcome::put_failed: ++count.put_failed; break;
                default: ++count.unknown; break;
                }
            }
            if (sampled) emit(completed ? "return" : "stopped", clock(), pair, snapshot, sink);
            return completed;
        }
#if defined(__cpp_exceptions)
        catch (...)
        {
            ++count.unwound;
            if (sampled) emit("unwind", clock(), pair, snapshot, sink);
            throw;
        }
#endif
    }
};
}
