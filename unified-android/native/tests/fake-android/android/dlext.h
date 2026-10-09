#ifndef LUCENT_TEST_ANDROID_DLEXT_H
#define LUCENT_TEST_ANDROID_DLEXT_H

#include <dlfcn.h>
#include <stdint.h>

enum {
    ANDROID_DLEXT_FORCE_LOAD = 0x40
};

typedef struct android_dlextinfo {
    uint64_t flags;
} android_dlextinfo;

static inline void *android_dlopen_ext(const char *filename, int flags,
                                       const android_dlextinfo *extension) {
    (void)extension;
    return dlopen(filename, flags);
}

#endif
