/* Cold Quick Resume must survive BlastEm's deferred first-run CPU reset. */
#include "../lucent_libretro_host.c"
#include <assert.h>

static bool started;
static unsigned runs, restores;
static uint32_t guest;

static void run(void) {
    ++runs;
    if (!started) {
        guest = 0; /* start_genesis(NULL) resets the 68K on its first run. */
        started = true;
    }
    ++guest;
    video_callback(&guest, 1, 1, sizeof(guest));
    push_audio_frame(200, -200);
}

static bool restore(const void *bytes, size_t size) {
    ++restores;
    if (size != sizeof(guest)) return false;
    memcpy(&guest, bytes, sizeof(guest));
    return true; /* BlastEm accepts the state even before its first reset. */
}

static void init(lucent_retro_host *host, const char *name) {
    memset(host, 0, sizeof(*host));
    host->system_info.library_name = name;
    host->game_loaded = true;
    host->run = run;
    host->unserialize = restore;
    host->pixel_format = RETRO_PIXEL_FORMAT_XRGB8888;
    host->audio_ring = calloc(AUDIO_RING_SAMPLES, sizeof(int16_t));
    assert(host->audio_ring);
    started = false;
    guest = runs = restores = 0;
}

static void finish(lucent_retro_host *host) {
    free(host->audio_ring);
    free(host->video_bytes);
    active_host = NULL;
}

int main(void) {
    lucent_retro_host host;
    lucent_retro_video_info video;
    char error[256] = {0};
    uint32_t saved = 4200;
    int16_t audio[8];

    init(&host, "BlastEm");
    host.paused = true;
    assert(lucent_retro_unserialize(&host, &saved, sizeof(saved), error, sizeof(error)));
    assert(runs == 1 && restores == 1 && guest == saved);
    assert(host.paused); /* Bootstrap must not resume the visible session. */
    assert(!lucent_retro_latest_video_info(&host, &video));
    assert(lucent_retro_drain_audio(&host, audio, 4) == 0);
    assert(lucent_retro_last_run_audio_duration_ns(&host) == 0);
    lucent_retro_set_paused(&host, false);
    assert(lucent_retro_run_frame(&host, error, sizeof(error)));
    assert(guest == saved + 1 && runs == 2);
    assert(lucent_retro_latest_video_info(&host, &video));

    /* An in-session rewind must not insert another guest frame. */
    assert(lucent_retro_unserialize(&host, &saved, sizeof(saved), error, sizeof(error)));
    assert(runs == 2 && restores == 2 && guest == saved);
    assert(lucent_retro_run_frame(&host, error, sizeof(error)));
    assert(guest == saved + 1);
    finish(&host);

    /* Existing SRAM bootstrap frames already satisfy the requirement. */
    init(&host, "BlastEm");
    assert(lucent_retro_run_frame(&host, error, sizeof(error)));
    assert(lucent_retro_unserialize(&host, &saved, sizeof(saved), error, sizeof(error)));
    assert(runs == 1 && guest == saved);
    finish(&host);

    /* Never prime arbitrary cores or mutate anything for an invalid request. */
    init(&host, "Other core");
    assert(lucent_retro_unserialize(&host, &saved, sizeof(saved), error, sizeof(error)));
    assert(runs == 0 && guest == saved);
    finish(&host);
    init(&host, "BlastEm");
    assert(!lucent_retro_unserialize(&host, NULL, sizeof(saved), error, sizeof(error)));
    assert(runs == 0 && restores == 0);
    assert(!lucent_retro_unserialize(&host, &saved, 1, error, sizeof(error)));
    assert(runs == 1 && restores == 1); /* Core rejection is still reported. */
    finish(&host);
    puts("BlastEm cold restore, paused bootstrap, media discard and isolation passed");
    return 0;
}
