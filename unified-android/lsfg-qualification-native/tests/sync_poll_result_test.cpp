#include "../sync_poll_result.hpp"
#include <cassert>
#include <initializer_list>
#include <unistd.h>
int main() {
    using emufusion::lsfg::successfulSyncPoll;
    assert(successfulSyncPoll(1, POLLIN));
    assert(!successfulSyncPoll(0, POLLIN));
    assert(!successfulSyncPoll(-1, POLLIN));
    assert(!successfulSyncPoll(1, 0));
    for (short error : {short(POLLERR), short(POLLHUP), short(POLLNVAL)}) {
        assert(!successfulSyncPoll(1, error));
        assert(!successfulSyncPoll(1, short(POLLIN | error)));
    }
    using emufusion::lsfg::pollSyncCompletion;
    using C = emufusion::lsfg::SyncCompletion;
    assert(pollSyncCompletion(-1) == C::Complete);
    assert(pollSyncCompletion(-2) == C::Failed);
    assert(pollSyncCompletion(-3) == C::Failed);
    // Pipes exercise poll states, not GPU synchronization semantics.
    int descriptors[2];
    assert(pipe(descriptors) == 0);
    assert(pollSyncCompletion(descriptors[0]) == C::Pending);
    assert(write(descriptors[1], "x", 1) == 1);
    assert(pollSyncCompletion(descriptors[0]) == C::Complete);
    close(descriptors[1]);
    assert(pollSyncCompletion(descriptors[0]) == C::Failed); // readable plus HUP
    close(descriptors[0]);
    assert(pollSyncCompletion(descriptors[0]) == C::Failed);
}
