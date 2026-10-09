/* A render-threaded core can grow its state after serialize_size resumes it. */
#include "../lucent_libretro_host.c"
#include <stdio.h>

static size_t reported;
static unsigned queries, writes;
static int mode;
static size_t query(void) {
    ++queries;
    return reported;
}
static bool capture(void *data, size_t size) {
    ++writes;
    if (mode == 1 && writes == 1) { reported = 8; return false; }
    if (mode == 2) { reported += 4; return false; }
    if (mode == 3) return false;
    if (mode == 4) { reported = MAX_STATE_BYTES + 1u; return false; }
    if (mode == 5) { reported = 0; return false; }
    if (mode == 6) { reported = 2; return false; }
    if (size != reported) return false;
    memset(data, 0x5a, size);
    return true;
}
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "mode=%d line=%d error=%s\n", mode, __LINE__, error); return 1; } } while (0)
int main(void) {
    lucent_retro_host host = {0};
    char error[128] = {0};
    host.game_loaded = true;
    host.serialize_size = query;
    host.serialize = capture;
    for (mode = 0; mode <= 6; ++mode) {
        void *data = (void *)1;
        size_t size = 1;
        reported = 4; queries = writes = 0;
        bool result = lucent_retro_serialize_alloc(&host, &data, &size, error, sizeof(error));
        if (mode <= 1) {
            CHECK(result && data && size == (mode == 1 ? 8u : 4u));
            for (size_t i = 0; i < size; ++i) CHECK(((unsigned char *)data)[i] == 0x5a);
            CHECK(writes == (mode == 1 ? 2u : 1u));
            free(data);
        } else {
            CHECK(!result && !data && size == 0);
            CHECK(writes == (mode == 2 ? 3u : 1u));
        }
        CHECK(queries <= 3);
    }
    puts("state capture growth: bounded retry and all failure paths passed");
    return 0;
}
