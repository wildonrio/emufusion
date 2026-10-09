/* Execute the production host policy, not a reimplementation of it. */
#include "../lucent_libretro_host.c"
#include <assert.h>

static void check(const char *key, const char *choices,
                  const char *override, const char *expected) {
    lucent_retro_host host = {0};
    host.core_path = "liblucent_core_test.so";
    struct retro_variable definitions[] = {{key, choices}, {NULL, NULL}};
    if (override) {
        host.core_override_count = 1;
        host.core_overrides[0].key = strdup(key);
        host.core_overrides[0].value = strdup(override);
    }
    assert(register_core_variable_defaults(&host, definitions));
    assert(host.core_variable_count == 1);
    assert(strcmp(host.core_variables[0].value, expected) == 0);
    free(host.core_variables[0].key);
    free(host.core_variables[0].value);
    free_core_overrides(&host);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    if (strcmp(argv[1], "psp") == 0) {
        const char *key = "ppsspp_internal_resolution";
        const char *choices = "Rendering Resolution; 1920x1088|480x272|960x544";
        check(key, choices, NULL, "480x272");
        check(key, choices, "1920x1088", "1920x1088");
        check(key, choices, "960x544", "960x544");
        check(key, choices, "320x240", "480x272");
        check(key, "Resolution; 960x544|1920x1088", NULL, "960x544");
        check(key, "Resolution; 480x272", NULL, "480x272");
        check("ppsspp_cropto16x9", "Crop; enabled|disabled", NULL, "disabled");
    } else {
        assert(strcmp(argv[1], "n64") == 0);
        const char *key = "mupen64plus-43screensize";
        const char *choices = "4:3 Resolution; 1440x1080|320x240|640x480|960x720";
        check(key, choices, NULL, "640x480");
        check(key, choices, "1440x1080", "1440x1080");
        check(key, choices, "320x240", "320x240");
        check(key, choices, "1920x1080", "640x480");
        check(key, "Resolution; 960x720|1440x1080", NULL, "960x720");
        check(key, "Resolution; 640x480", NULL, "640x480");
        check("mupen64plus-aspect", "Aspect; 16:9|4:3", NULL, "4:3");
        check("mupen64plus-EnableOverscan", "Crop; Enabled|Disabled", NULL, "Disabled");
    }
    check("unrelated_resolution", "Resolution; 1280x720|640x480", NULL, "1280x720");
    puts("Portable core default, explicit override, fallback and geometry policy pass");
    return 0;
}
