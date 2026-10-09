// Standalone diagnostic self-test; never runs in the game application.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <thread>
#include <vector>

extern "C" __attribute__((noinline)) void known_free_site(void* pointer) {
    free(pointer);
}

bool DebugAllocatorMapped() {
    // Android loads malloc_debug in its allocator namespace, so a default-
    // namespace RTLD_NOLOAD query can fail even when it is present.
    FILE* maps = fopen("/proc/self/maps", "r");
    if (!maps) return false;
    char line[2048];
    bool found = false;
    while (fgets(line, sizeof(line), maps)) {
        if (strstr(line, "/libc_malloc_debug.so")) found = true;
    }
    fclose(maps);
    return found;
}

int main(int argc, char** argv) {
    auto dump = reinterpret_cast<void(*)()>(dlsym(RTLD_DEFAULT, "emufusion_free_trace_dump"));
    if (!dump || argc != 2) return 20;
    if (!strcmp(argv[1], "stress")) {
        std::vector<std::thread> threads;
        for (int t = 0; t < 4; ++t) threads.emplace_back([] {
            for (int i = 0; i < 10000; ++i) known_free_site(malloc(64));
        });
        for (auto& thread : threads) thread.join();
        dump();
        return 0;
    }
    const bool corrupt = !strcmp(argv[1], "quarantine-abort");
    if (corrupt && !DebugAllocatorMapped()) return 21;
    void* victim = malloc(32);
    void* trigger = malloc(48);
    if (!victim || !trigger) return 22;
    fprintf(stderr, "probe victim=%p trigger=%p known_free_site=%p\n",
            victim, trigger, reinterpret_cast<void*>(&known_free_site));
    known_free_site(victim);
    if (corrupt) {
        // Deliberate, contained fixture: requires the loaded quarantine above.
        // The probe is compiled -O0 -fno-builtin; not emulator/game code.
        *static_cast<volatile unsigned char*>(victim) = 0;
        known_free_site(trigger); // free_track=1 should evict victim and abort.
        return 23;
    }
    known_free_site(trigger);
    dump();
    return 0;
}
