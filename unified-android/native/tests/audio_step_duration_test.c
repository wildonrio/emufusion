/* Exercise the production run/callback/resample/drain paths. */
#include "../lucent_libretro_host.c"
#include <assert.h>

static unsigned generated_frames;
static void run(void) {
    for (unsigned i = 0; i < generated_frames; ++i)
        audio_sample_callback(0, 0); /* silence still advances media time */
}

int main(void) {
    lucent_retro_host host = {0};
    char error[256] = {0};
    host.game_loaded = true;
    host.audio_input_rate = host.audio_output_rate = 44100.0;
    host.audio_timing_multiplier = 1.0;
    host.audio_ring = calloc(AUDIO_RING_SAMPLES, sizeof(int16_t));
    host.run = run;
    assert(host.audio_ring);
    const unsigned steps[] = {735, 1470, 2205, 735, 0, 1470};
    for (unsigned i = 0; i < sizeof(steps) / sizeof(steps[0]); ++i) {
        generated_frames = steps[i];
        assert(lucent_retro_run_frame(&host, error, sizeof(error)));
        uint64_t ns = lucent_retro_last_run_audio_duration_ns(&host);
        assert(llabs((long long)ns - (long long)(steps[i] * 1000000000.0 / 44100.0)) <= 1);
        int16_t samples[8192];
        lucent_retro_drain_audio(&host, samples, 4096);
        assert(lucent_retro_last_run_audio_duration_ns(&host) == ns);
    }
    /* Overflow cannot erase generated time and silently accelerate gameplay. */
    generated_frames = AUDIO_RING_SAMPLES;
    assert(lucent_retro_run_frame(&host, error, sizeof(error)));
    assert(host.audio_count == AUDIO_RING_SAMPLES);
    assert(lucent_retro_last_run_audio_duration_ns(&host) > 5000000000ull);
    host.audio_read = host.audio_count = 0;

    /* Existing display correction is counted once, after resampling. */
    host.audio_timing_multiplier = 1.001;
    reset_audio_resampler(&host);
    generated_frames = 44100;
    assert(lucent_retro_run_frame(&host, error, sizeof(error)));
    uint64_t ns = lucent_retro_last_run_audio_duration_ns(&host);
    assert(ns > 998970000ull && ns < 999030000ull);
    host.audio_timing_multiplier = 0.999;
    reset_audio_resampler(&host);
    assert(lucent_retro_run_frame(&host, error, sizeof(error)));
    ns = lucent_retro_last_run_audio_duration_ns(&host);
    assert(ns > 1000970000ull && ns < 1001030000ull);
    host.game_loaded = false;
    assert(lucent_retro_last_run_audio_duration_ns(&host) == 0);
    assert(lucent_retro_last_run_audio_duration_ns(NULL) == 0);
    active_host = NULL;
    free(host.audio_ring);
    puts("PCM step duration: 60/30/20 Hz, transitions, silence, drain, overflow, resampling passed");
    return 0;
}
