/* Execute the production load/runtime AV and PCM paths, not a formula copy. */
#include "../lucent_libretro_host.c"
#include <assert.h>

static double mock_fps = 60.0;
static double mock_rate = 44100.0;
static unsigned mock_width = 160, mock_height = 144;
static bool load(const struct retro_game_info *game) { return game != NULL; }
static void ports(unsigned port, unsigned device) { (void)port; (void)device; }
static void av(struct retro_system_av_info *info) {
    memset(info, 0, sizeof(*info));
    info->timing.fps = mock_fps;
    info->timing.sample_rate = mock_rate;
    info->geometry.base_width = mock_width;
    info->geometry.base_height = mock_height;
}

int main(void) {
    const char *version = "3c4cfcf54dfe9e36070815e76ee2bab9e754104f";
    const double video_clock = 3579545.0 / (228.0 * 262.0);
    const double pcm_clock = 807.0 * 3579545.0 / 65536.0;
    lucent_retro_host host = {0};
    lucent_retro_av_info result;
    char error[256] = {0};
    host.system_info.library_name = "Gearsystem";
    host.system_info.library_version = version;
    host.system_info.need_fullpath = true;
    host.load_game = load;
    host.set_controller_port_device = ports;
    host.get_system_av_info = av;
    host.audio_ring = calloc(AUDIO_RING_SAMPLES, sizeof(int16_t));
    assert(host.audio_ring);
    /* Exact 60 and nearby measured panel clocks must all stay bounded. */
    const double targets[] = {60.0, 59.98785, 60.025};
    for (unsigned test = 0; test < sizeof(targets) / sizeof(targets[0]); ++test) {
        host.game_loaded = false;
        assert(lucent_retro_load_game(&host, "timing-fixture", error, sizeof(error)));
        assert(lucent_retro_get_av_info(&host, &result));
        assert(fabs(result.frames_per_second - video_clock) < 1e-10);
        assert(result.sample_rate == 44100.0 && host.audio_output_rate == 44100.0);
        assert(fabs(host.audio_input_rate - pcm_clock) < 1e-10);
        assert(result.base_width == 160 && result.base_height == 144);
        assert(fabs(targets[test] / video_clock - 1.0) < 0.0075);
        assert(lucent_retro_set_synchronized_video_rate(
                &host, result.frames_per_second, targets[test], error, sizeof(error)));
        uint64_t input_frames = 0, output_frames = 0;
        for (uint64_t frame = 1; frame <= 18000; ++frame) {
            /* Exact integer Blip time: CPU cycles * factor, shifted 16 bits. */
            uint64_t produced = frame * 228u * 262u * 807u / 65536u;
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
                assert(fabs(host.current_av_info.timing.fps - video_clock) < 1e-10);
                assert(fabs(host.audio_input_rate - pcm_clock) < 1e-10);
                assert(host.audio_output_rate == 44100.0);
            }
        }
        double expected = 18000.0 * 44100.0 / targets[test];
        assert(fabs((double)output_frames - expected) <= 3.0);
        printf("GG 18000 vblanks at %.5f Hz: input=%llu output=%llu expected=%.3f\n",
                targets[test], (unsigned long long)input_frames,
                (unsigned long long)output_frames, expected);
    }
    /* No change to PAL, SMS/FM, revisions, different PCM rates, or valid AV. */
    for (unsigned test = 0; test < 9; ++test) {
        host.game_loaded = false;
        host.system_info.library_name = test == 0 ? "Other" : test == 1 ? NULL : "Gearsystem";
        host.system_info.library_version = test == 2 ? "future" : test == 3 ? NULL : version;
        mock_fps = test == 4 ? 50.0 : test == 5 ? video_clock : 60.0;
        mock_rate = test == 6 ? 48000.0 : 44100.0;
        mock_width = test == 7 ? 256 : 160;
        mock_height = test == 8 ? 192 : 144;
        assert(lucent_retro_load_game(&host, "timing-fixture", error, sizeof(error)));
        assert(host.current_av_info.timing.fps == mock_fps);
        assert(host.audio_input_rate == mock_rate);
    }
    active_host = NULL;
    free(host.audio_ring);
    puts("GG load/runtime AV, PCM balance, geometry preservation and isolation passed");
    return 0;
}
