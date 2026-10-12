#ifndef EMUFUSION_FAKE_ANDROID_LOG_H
#define EMUFUSION_FAKE_ANDROID_LOG_H
#include <stdarg.h>
#define ANDROID_LOG_DEBUG 3
#define ANDROID_LOG_INFO 4
#define ANDROID_LOG_WARN 5
#define ANDROID_LOG_ERROR 6
static inline int __android_log_print(int priority, const char *tag,
                                      const char *format, ...) {
    (void)priority;
    (void)tag;
    (void)format;
    return 0;
}
static inline int __android_log_vprint(int priority, const char *tag,
                                       const char *format, va_list arguments) {
    (void)priority;
    (void)tag;
    (void)format;
    (void)arguments;
    return 0;
}
#endif
