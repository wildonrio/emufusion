#include "../eden_direct_present_pacer.h"
#include <cassert>
#include <iostream>
using Lucent::Trial::DirectPresentPacer;
constexpr uint64_t start = 1000000000000ULL;
constexpr uint64_t refresh = 8336096;

DirectPresentPacer Warm() {
    DirectPresentPacer p;
    assert(p.Configure(8333333));
    for (uint32_t i = 1; i <= 65; ++i)
        p.Feedback(i, start + i * 2 * refresh, start + i * 2 * refresh + 1000000);
    assert(p.Samples() == 64);
    assert(std::abs(p.RefreshNs() - refresh) < 1);
    return p;
}
int main() {
    DirectPresentPacer cold;
    assert(!cold.Configure(0));
    assert(cold.Schedule(1, start, 16666667) == 0);
    assert(cold.Configure(8333333));
    assert(cold.Schedule(1, start, 16666667) == 0);
    auto p = Warm();
    const auto now = start + 66 * 2 * refresh - 10000000;
    assert(p.HasRecentFeedback(66, now));
    const auto last_actual = start + 65 * 2 * refresh;
    assert(p.HasRecentFeedback(81, last_actual + 250000000));
    assert(!p.HasRecentFeedback(82, now));
    assert(!p.HasRecentFeedback(66, last_actual + 250000001));
    assert(!p.HasRecentFeedback(66, last_actual - 1));
    assert(!p.HasRecentFeedback(65, now));
    assert(!cold.HasRecentFeedback(66, now));
    auto a = p.Schedule(66, now, 16666667);
    auto b = p.Schedule(67, now + 16666667, 16666667);
    assert(a && b - a == 2 * refresh);
    assert(p.Schedule(68, now + 30000000, 12500000) == 0); // 80/120 invalid
    assert(p.Schedule(68, now + 30000000, 0) == 0);
    assert(p.Schedule(69, now + 300000000, 16666667) == 0); // stale feedback
    assert(p.Schedule(60, now, 16666667) == 0); // old/wrapped present ID
    auto q = Warm();
    auto count = q.Samples();
    q.Feedback(66, now + 1, now); // future
    q.Feedback(64, start, now); // stale ID
    q.Feedback(66, start, now); // backwards time
    assert(q.Samples() == count);
    assert(q.Schedule(66, now, 25000000) > 0); // 40/120 three-refresh direct
    assert(q.Configure(16666666)); // swapchain/mode replacement clears phase
    assert(q.Samples() == 0 && q.Schedule(67, now, 16666667) == 0);
    auto slow = Warm();
    assert(slow.Schedule(66, now, 33333333) > 0); // 30/120 four-refresh direct
    auto stalled = Warm();
    assert(stalled.Schedule(66, now + 50000000, 16666667) == 0);
    assert(stalled.Resets() == 1);
    // One late physical hold must not move every later source frame's target
    // by half a 60-Hz source period on a 120-Hz display.
    auto late = Warm();
    const auto first_target = late.Schedule(66, now, 16666667);
    const auto late_actual = start + 66 * 2 * refresh + refresh;
    late.Feedback(66, late_actual, late_actual + 1000000);
    const auto next_target = late.Schedule(67, late_actual + 1000000, 16666667);
    assert(next_target - first_target == 2 * refresh);
    // Account for missing calls by source ID, rather than scheduling the next
    // seen ID just one period later. Duplicate IDs cannot advance the phase.
    const auto skipped_target = late.Schedule(69, late_actual + 1000000, 16666667);
    assert(skipped_target - next_target == 4 * refresh);
    assert(late.Schedule(69, late_actual + 1000000, 16666667) == 0);
    auto stable_phase = Warm();
    uint64_t previous_target = 0;
    for (uint32_t id = 66; id < 6066; ++id) {
        const auto submit_now = start + id * 2 * refresh - 6000000;
        if (id > 66) {
            const auto previous = id - 1;
            const auto actual = start + previous * 2 * refresh +
                                (previous % 240 == 0 ? refresh : 0);
            stable_phase.Feedback(previous, actual, submit_now);
        }
        const auto target = stable_phase.Schedule(id, submit_now, 16666667);
        assert(target != 0);
        if (previous_target) assert(target - previous_target == 2 * refresh);
        previous_target = target;
    }
    assert(stable_phase.Resets() == 0);
    std::cout << "Direct native pacing candidate: host cases passed; device unverified\n";
}
