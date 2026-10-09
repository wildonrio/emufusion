#define _POSIX_C_SOURCE 200809L

#include "../include/lucent_libretro_host.h"

#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define CHECK(value, message) do { \
    if (!(value)) { \
        fprintf(stderr, "%s: %s\n", message, error); \
        return 1; \
    } \
} while (0)

int main(int argc, char **argv) {
    char error[512] = {0};
    bool expect_success;
    bool loaded;
    lucent_retro_host *host;
    if (argc != 8) {
        fprintf(stderr, "usage: dolphin_quarantine_test CORE TRUSTED_ROOT "
                "SYSTEM_DIR SAVE_DIR GAME MARKER success|reject\n");
        return 2;
    }
    expect_success = strcmp(argv[7], "success") == 0;
    if (!expect_success && strcmp(argv[7], "reject") != 0) {
        fprintf(stderr, "expected success or reject mode\n");
        return 2;
    }
    unlink(argv[6]);
    CHECK(setenv("LUCENT_MOCK_DLCLOSE_MARKER_PATH", argv[6], 1) == 0,
          "could not configure DSO finalizer marker");
    host = lucent_retro_create(
            argv[1], argv[2], argv[3], argv[4], error, sizeof(error));
    CHECK(host, "could not create Dolphin mock host");
    loaded = lucent_retro_load_game(host, argv[5], error, sizeof(error));
    if (expect_success) {
        CHECK(loaded, "completed Dolphin mock rejected content");
        CHECK(lucent_retro_unload_game(host, error, sizeof(error)),
              "completed Dolphin mock did not unload game");
    } else {
        CHECK(!loaded, "rejecting Dolphin mock accepted content");
    }
    lucent_retro_destroy(host);
    if (expect_success) {
        CHECK(access(argv[6], F_OK) == 0,
              "completed Dolphin mapping was not finalized by dlclose");
    } else {
        errno = 0;
        CHECK(access(argv[6], F_OK) != 0 && errno == ENOENT,
              "rejected Dolphin mapping reached its crash-prone finalizers");
    }
    printf("Dolphin %s-load teardown gate passed\n",
           expect_success ? "completed" : "rejected");
    return 0;
}
