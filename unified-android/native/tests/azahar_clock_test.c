/* Exercise real load/runtime AV handling and PCM resampling without Android. */
#include "../lucent_libretro_host.c"
#include <assert.h>

static double mock_fps = 60.0;
static double mock_rate = 32728.0;
static bool load(const struct retro_game_info *game) { return game != NULL; }
static void ports(unsigned port, unsigned device) { (void)port; (void)device; }
static void av(struct retro_system_av_info *info) {
    memset(info, 0, sizeof(*info));
    info->timing.fps = mock_fps;
    info->timing.sample_rate = mock_rate;
    info->geometry.base_width = 720;
    info->geometry.base_height = 240;
    info->geometry.aspect_ratio = 3.0f;
}

int main(void) {
    lucent_retro_host host = {0};
    lucent_retro_av_info result;
    char error[256] = {0};
    const double native_video = 268111856.0 / 4481136.0;
    const double native_audio = 268111856.0 / 8192.0;
    host.system_info.library_name = "Azahar";
    host.system_info.library_version = "2125.1.3";
    host.system_info.need_fullpath = true;
    host.load_game = load;
    host.set_controller_port_device = ports;
    host.get_system_av_info = av;
    host.audio_ring = calloc(AUDIO_RING_SAMPLES, sizeof(int16_t));
    assert(host.audio_ring);
    assert(lucent_retro_load_game(&host, "timing-fixture", error, sizeof(error)));
    assert(lucent_retro_get_av_info(&host, &result));
    assert(fabs(result.frames_per_second - native_video) < 1e-10);
    assert(result.sample_rate == 32728.0); /* Actual integer Android sink. */
    assert(fabs(host.audio_input_rate - native_audio) < 1e-10);
    assert(result.base_width == 720 && result.base_height == 240);
    assert(60.0 / result.frames_per_second - 1.0 < 0.0075);
    assert(lucent_retro_set_synchronized_video_rate(
            &host, result.frames_per_second, 60.0, error, sizeof(error)));
    uint64_t input_frames = 0;
    uint64_t output_frames = 0;
    /* 300 seconds of genuine GPU vblanks and 160-sample DSP callbacks. */
    for (uint64_t frame = 1; frame <= 18000; ++frame) {
        uint64_t produced = (frame * 4481136u / (8192u * 160u)) * 160u;
        while (input_frames < produced) {
            push_audio_frame(1000, -1000);
            ++input_frames;
        }
        output_frames += host.audio_count / 2u;
        host.audio_read = host.audio_count = 0;
        if (frame == 9000) {
            struct retro_system_av_info changed;
            av(&changed);
            assert(environment_callback(RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO, &changed));
            assert(fabs(host.current_av_info.timing.fps - native_video) < 1e-10);
            assert(fabs(host.audio_input_rate - native_audio) < 1e-10);
            assert(host.audio_output_rate == 32728.0);
        }
    }
    assert(llabs((long long)output_frames - 300LL * 32728) <= 161);
    printf("300s: input=%llu output=%llu expected=%d; metadata/runtime/PCM pass\n",
           (unsigned long long)input_frames, (unsigned long long)output_frames, 300 * 32728);
    /* No blanket 3DS/system default: leave other revisions/valid reports alone. */
    const char *names[] = {"Azahar", "Other", "Azahar", "Azahar", "Azahar"};
    const char *versions[] = {"new-version", "2125.1.3", NULL, "2125.1.3", "2125.1.3"};
    for (unsigned i = 0; i < 5; ++i) {
        host.game_loaded = false;
        host.system_info.library_name = names[i];
        host.system_info.library_version = versions[i];
        mock_fps = i == 3 ? native_video : 60.0;
        mock_rate = i == 4 ? 48000.0 : 32728.0;
        assert(lucent_retro_load_game(&host, "timing-fixture", error, sizeof(error)));
        assert(host.current_av_info.timing.fps == mock_fps);
        assert(host.audio_input_rate == mock_rate);
    }
    active_host = NULL;
    free(host.audio_ring);
    puts("unrelated core/version/timing isolation pass");
    return 0;
}
