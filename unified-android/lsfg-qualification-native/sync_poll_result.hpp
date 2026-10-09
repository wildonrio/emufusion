#pragma once
#include <poll.h>
#include <cerrno>

namespace emufusion::lsfg {
// A signaled sync fence is readable. Error, hangup, or invalid descriptor
// events do not establish successful completion, even alongside readability.
inline bool successfulSyncPoll(int result, short events) {
    return result == 1 && (events & POLLIN) != 0 &&
            (events & (POLLERR | POLLHUP | POLLNVAL)) == 0;
}

enum class SyncCompletion { Pending, Complete, Failed };
// Borrowed FD. -1 is the Vulkan SYNC_FD already-signaled sentinel, not an
// absent submission. Callers use values below -1 for absent/failed work.
inline SyncCompletion pollSyncCompletion(int fd) {
    if (fd == -1) return SyncCompletion::Complete;
    if (fd < -1) return SyncCompletion::Failed;
    pollfd descriptor{fd, POLLIN, 0};
    const int result = ::poll(&descriptor, 1, 0);
    if (result == 0 || (result < 0 && errno == EINTR)) return SyncCompletion::Pending;
    return successfulSyncPoll(result, descriptor.revents) ?
            SyncCompletion::Complete : SyncCompletion::Failed;
}
}
