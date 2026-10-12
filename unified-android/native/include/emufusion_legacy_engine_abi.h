/*
 * Engine hooks exported before the Lucent -> EmuFusion rename.
 *
 * Engines export their EmuFusion hooks as emufusion_* / retro_emufusion_*.
 * Engines built before the rename (rename phase C2) still export the same
 * hooks, with the same ABI, under the former product prefix. Until each
 * packaged engine has been rebuilt, the host asks for the EmuFusion name first
 * and then for the former one.
 *
 * This is the only native file that may name the former prefix
 * (tools/tests/test_legacy_name_migration.py). Delete it, and route
 * emufusion_engine_dlsym back to dlsym, once no packaged engine exports it.
 */
#ifndef EMUFUSION_LEGACY_ENGINE_ABI_H
#define EMUFUSION_LEGACY_ENGINE_ABI_H

#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

#define EMUFUSION_LEGACY_ENGINE_PREFIX "lucent_"
#define EMUFUSION_LEGACY_RETRO_PREFIX "retro_lucent_"
/* Test fixtures only: the former spelling of an emufusion_<suffix> export. */
#define EMUFUSION_LEGACY_ENGINE_SYMBOL(suffix) lucent_##suffix
#define EMUFUSION_LEGACY_RETRO_SYMBOL(suffix) retro_lucent_##suffix

/*
 * dlsym(library, name), then the former spelling of name when it has no
 * definition. Like dlsym, the caller reads dlerror() for the reason.
 */
static inline void *emufusion_engine_dlsym(void *library, const char *name) {
    static const char *const prefixes[][2] = {
        {"retro_emufusion_", EMUFUSION_LEGACY_RETRO_PREFIX},
        {"emufusion_", EMUFUSION_LEGACY_ENGINE_PREFIX},
    };
    char legacy[160];
    void *symbol;
    size_t i;
    dlerror();
    symbol = dlsym(library, name);
    if (symbol || !name) return symbol;
    for (i = 0; i < sizeof(prefixes) / sizeof(prefixes[0]); ++i) {
        size_t length = strlen(prefixes[i][0]);
        int written;
        if (strncmp(name, prefixes[i][0], length) != 0) continue;
        written = snprintf(legacy, sizeof(legacy), "%s%s", prefixes[i][1], name + length);
        if (written < 0 || (size_t)written >= sizeof(legacy)) return NULL;
        dlerror();
        return dlsym(library, legacy);
    }
    return NULL;
}

#endif
