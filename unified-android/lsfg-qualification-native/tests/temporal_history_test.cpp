#include "../temporal_history.hpp"
#include <cassert>
using namespace emufusion::lsfg;
int main() {
    TemporalHistory h;
    using A = TemporalHistory::Admission;
    assert(h.begin({}) == A::Invalid);
    assert(h.inspect({1, 1, 1, 100}) == A::Accepted);
    assert(h.inspect({1, 1, 1, 100}) == A::Accepted);
    assert(!h.lastCompleted() && h.nextInput() == 0);
    for (uint64_t i = 1; i <= 3; ++i) {
        assert(h.nextInput() == (i - 1) % 2);
        assert(h.begin({1, 1, i, i * 100}) == A::Accepted);
        assert(!h.historyReady());
        assert(h.begin({1, 1, i, i * 100}) == A::Busy);
        assert(!h.resetAfterBackendRecreation());
        assert(h.complete(true));
        assert(!h.complete(true));
    }
    assert(h.historyReady());
    assert(h.begin({1, 1, 5, 500}) == A::RecreateRequired); // dropped source
    assert(h.begin({1, 2, 4, 400}) == A::RecreateRequired); // timeline reset
    assert(h.begin({2, 1, 4, 400}) == A::RecreateRequired); // new game
    assert(h.begin({1, 1, 4, 300}) == A::RecreateRequired); // repeated timestamp
    assert(h.begin({1, 1, 4, 400}) == A::Accepted);
    assert(!h.complete(false));
    assert(!h.historyReady());
    assert(h.begin({1, 1, 4, 400}) == A::RecreateRequired);
    assert(h.resetAfterBackendRecreation());
    assert(h.nextInput() == 0 && !h.lastCompleted());
    assert(h.begin({2, 7, 900, 1000}) == A::Accepted);
    assert(h.complete(true));
    assert(!h.historyReady());
}
