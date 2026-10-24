#include "../include/emufusion_libretro_host.h"

#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/*
 * Run-ahead against the mock core, whose state is a counter that every frame
 * advances by one and whose image and sound are that counter. With one frame
 * of run-ahead the image is one frame ahead of the true state, the sound is
 * the true frame's alone, and savestates taken between frames are the true
 * state. A core whose savestates miss state, or that says they are
 * incomplete, keeps ordinary frames.
 */
#define CHECK(value, message) do { if (!(value)) { \
    fprintf(stderr, "%s (run %u): %s\n", message, run, error); return 1; } } while (0)
#define FIRST_CHECK_RUN 120u

typedef void (*fn_set_boolean)(bool);
static fn_set_boolean set_noisy_state;
typedef bool (*fn_report_quirks)(uint64_t);

static uint32_t state_value(emufusion_retro_host *host, char *error, size_t error_size) {
    uint32_t state = 0;
    if (emufusion_retro_serialize_size(host) != sizeof(state) ||
            !emufusion_retro_serialize(host, &state, sizeof(state), error, error_size))
        return UINT32_MAX;
    return state;
}

static uint32_t noisy_counter(emufusion_retro_host *host, char *error, size_t error_size) {
    uint32_t state[2] = {0, 0};
    if (emufusion_retro_serialize_size(host) != sizeof(state) ||
            !emufusion_retro_serialize(host, state, sizeof(state), error, error_size))
        return UINT32_MAX;
    return state[0];
}

static uint16_t image(emufusion_retro_host *host) {
    uint16_t pixel = 0;
    if (!emufusion_retro_copy_video_frame(host, &pixel, sizeof(pixel))) return 0xffffu;
    return pixel;
}

/* The mock plays (0, 0) then (counter, -counter) each frame. */
static size_t sound(emufusion_retro_host *host, int16_t *samples, size_t capacity) {
    return emufusion_retro_drain_audio(host, samples, capacity / 2);
}

static emufusion_retro_host *open_game(char **argv, char *error, size_t size) {
    emufusion_retro_host *host = emufusion_retro_create(argv[1], argv[2], argv[3], argv[4],
                                                        error, size);
    if (host && !emufusion_retro_load_game(host, argv[5], error, size)) {
        emufusion_retro_destroy(host);
        return NULL;
    }
    return host;
}

int main(int argc, char **argv) {
    char error[512] = {0};
    int16_t samples[64];
    unsigned run = 0;
    uint32_t start;
    void *mock;
    fn_set_boolean set_hidden_state;
    fn_report_quirks report_quirks;
    emufusion_retro_host *host;
    if (argc != 6) {
        fprintf(stderr, "usage: runahead_host_test CORE TRUSTED_ROOT SYSTEM_DIR SAVE_DIR GAME\n");
        return 2;
    }
    host = open_game(argv, error, sizeof(error));
    CHECK(host, "create/load failed");
    mock = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    CHECK(mock, "could not reopen mock core");
    set_hidden_state = (fn_set_boolean)dlsym(mock, "emufusion_mock_set_hidden_state");
    report_quirks = (fn_report_quirks)dlsym(mock, "emufusion_mock_report_serialization_quirks");
    set_noisy_state = (fn_set_boolean)dlsym(mock, "emufusion_mock_set_noisy_state");
    CHECK(set_hidden_state && report_quirks && set_noisy_state, "mock probes missing");

    start = state_value(host, error, sizeof(error));
    emufusion_retro_set_runahead(host, 1);
    for (run = 1; run < FIRST_CHECK_RUN; run++) {
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
        CHECK(state_value(host, error, sizeof(error)) == start + run, "state before the check");
        CHECK(image(host) == (uint16_t)(start + run), "frames before the check are ordinary");
        CHECK(sound(host, samples, 64) == 2 && samples[2] == (int16_t)(start + run),
              "sound before the check");
    }
    for (; run <= 3u * FIRST_CHECK_RUN; run++) {
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
        CHECK(state_value(host, error, sizeof(error)) == start + run,
              "the true state advances one frame per step, check replays included");
        CHECK(image(host) == (uint16_t)(start + run + 1u), "the image is one frame ahead");
        CHECK(sound(host, samples, 64) == 2 && samples[2] == (int16_t)(start + run),
              "only the true frame is heard; replays and the image frame are silent");
    }
    {
        /* Loading a savestate right after a sampled prediction (run 360): the
         * prediction is dropped, not mistaken for a diverging core. */
        uint32_t earlier = start + 100u;
        CHECK(run == 3u * FIRST_CHECK_RUN + 1u && emufusion_retro_unserialize(
                      host, &earlier, sizeof(earlier), error, sizeof(error)), "load failed");
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
        CHECK(state_value(host, error, sizeof(error)) == earlier + 1u &&
              image(host) == (uint16_t)(earlier + 2u), "run-ahead continues after a load");
        start = earlier + 1u - run;
        run++;
    }
    emufusion_retro_set_runahead(host, 0);
    CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
    CHECK(image(host) == (uint16_t)(start + run) &&
          state_value(host, error, sizeof(error)) == start + run, "off shows the true frame");
    run++;
    emufusion_retro_set_runahead(host, 2);
    CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
    CHECK(image(host) == (uint16_t)(start + run + 2u) &&
          state_value(host, error, sizeof(error)) == start + run, "two frames ahead");
    emufusion_retro_destroy(host);

    /* Savestates that miss state: replay differs, ordinary frames stay
     * (an ordinary frame shows exactly the state the step ended in). */
    host = open_game(argv, error, sizeof(error));
    CHECK(host, "create/load failed");
    set_hidden_state(true);
    emufusion_retro_set_runahead(host, 1);
    for (run = 1; run < FIRST_CHECK_RUN + 50u; run++) {
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
        CHECK(image(host) == (uint16_t)state_value(host, error, sizeof(error)),
              "a failed check keeps ordinary frames");
    }
    set_hidden_state(false);
    emufusion_retro_destroy(host);

    /* A core that diverges after the check: the predicted frame's state stops
     * matching the true frame's, and run-ahead turns off within a sample. */
    host = open_game(argv, error, sizeof(error));
    CHECK(host, "create/load failed");
    emufusion_retro_set_runahead(host, 1);
    for (run = 1; run <= FIRST_CHECK_RUN + 10u; run++)
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
    CHECK(image(host) == (uint16_t)(state_value(host, error, sizeof(error)) + 1u),
          "run-ahead is on before the divergence");
    set_hidden_state(true);
    for (; run <= FIRST_CHECK_RUN + 10u + 2u * 120u; run++)
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
    for (; run <= FIRST_CHECK_RUN + 20u + 2u * 120u; run++) {
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
        CHECK(image(host) == (uint16_t)state_value(host, error, sizeof(error)),
              "a diverging core returns to ordinary frames");
    }
    set_hidden_state(false);
    emufusion_retro_destroy(host);

    /* Unstable state bytes but identical images: run ahead, and compare the
     * predicted image with the true one; a later divergence turns it off. */
    host = open_game(argv, error, sizeof(error));
    CHECK(host, "create/load failed");
    set_noisy_state(true);
    emufusion_retro_set_runahead(host, 1);
    for (run = 1; run <= FIRST_CHECK_RUN + 10u; run++)
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
    {
        uint16_t before = image(host);
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
        CHECK((uint16_t)(image(host) - before) == 1u, "noisy-state core runs ahead");
        run++;
    }
    set_hidden_state(true);
    for (; run <= FIRST_CHECK_RUN + 10u + 2u * 120u; run++)
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
    for (; run <= FIRST_CHECK_RUN + 20u + 2u * 120u; run++) {
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
        CHECK(image(host) == (uint16_t)noisy_counter(host, error, sizeof(error)),
              "a predicted image that differs returns the core to ordinary frames");
    }
    set_hidden_state(false);
    set_noisy_state(false);
    emufusion_retro_destroy(host);

    /* A core that says its savestates are incomplete is never run ahead. */
    host = open_game(argv, error, sizeof(error));
    CHECK(host, "create/load failed");
    report_quirks(1u);
    start = state_value(host, error, sizeof(error));
    emufusion_retro_set_runahead(host, 1);
    for (run = 1; run < FIRST_CHECK_RUN + 50u; run++) {
        CHECK(emufusion_retro_run_frame(host, error, sizeof(error)), "run failed");
        CHECK(image(host) == (uint16_t)(start + run), "incomplete savestates keep ordinary frames");
    }
    emufusion_retro_destroy(host);
    dlclose(mock);
    printf("run-ahead host test passed\n");
    return 0;
}
