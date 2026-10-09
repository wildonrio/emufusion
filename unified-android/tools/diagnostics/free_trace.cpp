// Temporary, opt-in crash investigation. Not linked into normal EmuFusion.
// Records direct free callers without walking stacks or allocating per event.
// This does not identify the original allocation or a post-free writer.
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace {
using FreeFn = void (*)(void*);
using AbortFn = void (*)();
std::atomic<FreeFn> next_free{};
std::atomic<AbortFn> next_abort{};
std::atomic_flag resolving_free = ATOMIC_FLAG_INIT;
constexpr uint64_t capacity = 4096;
struct Record { uint64_t sequence, pointer, caller, tid; };
struct Slot {
    std::atomic_flag busy = ATOMIC_FLAG_INIT;
    Record record{};
};
Slot slots[capacity];
Record snapshot[capacity];
std::atomic<uint64_t> sequence{}, dropped{};
std::atomic_flag dumped = ATOMIC_FLAG_INIT;
int trace_fd = -1, maps_fd = -1;
struct Header {
    char magic[8];
    uint64_t pid, capacity, record_size, sequence, dropped, skipped, captured, version;
};
static_assert(sizeof(Header) == 72 && sizeof(Record) == 32);
static_assert(std::atomic<uint64_t>::is_always_lock_free);
static_assert(std::atomic<FreeFn>::is_always_lock_free);

bool WriteAll(int fd, const void* data, size_t bytes) {
    const char* cursor = static_cast<const char*>(data);
    while (bytes != 0) {
        const auto written = write(fd, cursor, bytes);
        if (written <= 0) return false;
        cursor += written;
        bytes -= static_cast<size_t>(written);
    }
    return true;
}

void RecordFree(void* pointer, void* caller) {
    if (!pointer || trace_fd < 0) return;
    const uint64_t id = sequence.fetch_add(1, std::memory_order_relaxed) + 1;
    auto& slot = slots[(id - 1) % capacity];
    // Never wait in an allocator hook. Collisions are counted, not fabricated.
    if (slot.busy.test_and_set(std::memory_order_acquire)) {
        dropped.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    slot.record = {id, reinterpret_cast<uintptr_t>(pointer),
                   reinterpret_cast<uintptr_t>(caller),
                   static_cast<uint64_t>(syscall(SYS_gettid))};
    slot.busy.clear(std::memory_order_release);
}

void Dump() {
    if (trace_fd < 0 || dumped.test_and_set(std::memory_order_acq_rel)) return;
    const auto end = sequence.load(std::memory_order_acquire);
    const auto begin = end > capacity ? end - capacity + 1 : 1;
    Header header{{'E','F','R','E','E','0','0','1'}, static_cast<uint64_t>(getpid()),
                  capacity, sizeof(Record), end,
                  dropped.load(std::memory_order_acquire), 0, 0, 1};
    for (size_t i = 0; i < capacity; ++i) {
        auto& slot = slots[i];
        if (slot.busy.test_and_set(std::memory_order_acquire)) {
            ++header.skipped;
            continue;
        }
        const auto record = slot.record;
        slot.busy.clear(std::memory_order_release);
        if (record.sequence >= begin && record.sequence <= end) {
            snapshot[i] = record;
            ++header.captured;
        }
    }
    // Files were created exclusively by this instance. No other file is replaced.
    WriteAll(trace_fd, &header, sizeof(header));
    WriteAll(trace_fd, snapshot, sizeof(snapshot));
    const int input = open("/proc/self/maps", O_RDONLY | O_CLOEXEC);
    if (input >= 0 && maps_fd >= 0) {
        char buffer[4096];
        ssize_t count;
        while ((count = read(input, buffer, sizeof(buffer))) > 0) {
            if (!WriteAll(maps_fd, buffer, static_cast<size_t>(count))) break;
        }
    }
    if (input >= 0) close(input);
}

__attribute__((constructor)) void Initialize() {
    next_free.store(reinterpret_cast<FreeFn>(dlsym(RTLD_NEXT, "free")),
                    std::memory_order_release);
    next_abort.store(reinterpret_cast<AbortFn>(dlsym(RTLD_NEXT, "abort")),
                     std::memory_order_release);
    if (!next_free.load() || !next_abort.load()) _exit(121);
    // No implicit output location. This library is only for an explicit probe.
    const char* directory = getenv("EMUFUSION_FREE_TRACE_DIR");
    if (!directory || !*directory) return;
    char path[1024];
    int length = snprintf(path, sizeof(path), "%s/free-%d.bin", directory, getpid());
    if (length < 0 || static_cast<size_t>(length) >= sizeof(path)) _exit(122);
    trace_fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    length = snprintf(path, sizeof(path), "%s/free-%d.maps", directory, getpid());
    if (length < 0 || static_cast<size_t>(length) >= sizeof(path)) _exit(122);
    maps_fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (trace_fd < 0 || maps_fd < 0) _exit(123);
}
} // namespace

extern "C" __attribute__((visibility("default"), noinline)) void free(void* pointer) {
    auto function = next_free.load(std::memory_order_acquire);
    // malloc_debug initialization can free before this preload's constructor.
    // Resolve once on that early path, but fail explicitly on resolver recursion
    // instead of leaking allocations or silently bypassing the real allocator.
    if (!function) {
        if (!pointer) return;
        if (resolving_free.test_and_set(std::memory_order_acq_rel)) _exit(125);
        function = reinterpret_cast<FreeFn>(dlsym(RTLD_NEXT, "free"));
        if (!function || function == &free) _exit(124);
        next_free.store(function, std::memory_order_release);
        resolving_free.clear(std::memory_order_release);
    }
    RecordFree(pointer, __builtin_extract_return_addr(__builtin_return_address(0)));
    function(pointer);
}

extern "C" __attribute__((visibility("default"), noinline, noreturn)) void abort() {
    Dump();
    const auto function = next_abort.load(std::memory_order_acquire);
    if (function) function();
    _exit(134);
}

extern "C" __attribute__((visibility("default"))) void emufusion_free_trace_dump() {
    Dump();
}
