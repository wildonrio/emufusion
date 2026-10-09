/* Exercise production core-option selection, including explicit overrides. */
#include "../lucent_libretro_host.c"
#include <assert.h>

static void check(const char *choices, const char *override, const char *expected) {
    lucent_retro_host host = {0};
    host.core_path = "liblucent_core_flycast.so";
    struct retro_variable definitions[] = {
        {"reicast_internal_resolution", choices}, {NULL, NULL}
    };
    if (override) {
        host.core_override_count = 1;
        host.core_overrides[0].key = strdup("reicast_internal_resolution");
        host.core_overrides[0].value = strdup(override);
    }
    assert(register_core_variable_defaults(&host, definitions));
    assert(host.core_variable_count == 1);
    assert(strcmp(host.core_variables[0].value, expected) == 0);
    free(host.core_variables[0].key);
    free(host.core_variables[0].value);
    free_core_overrides(&host);
}

int main(void) {
    const char *choices = "Resolution; 1440x1080|640x480|1280x960";
    check(choices, NULL, "640x480");
    check(choices, "1280x960", "1280x960");
    check(choices, "320x240", "640x480"); /* Unadvertised override rejected. */
    check("Resolution; 1280x960|1440x1080", NULL, "1280x960");
    check("Resolution; 640x480", NULL, "640x480");
    puts("Dreamcast native default, supported override and fallback pass");
    return 0;
}
