#ifndef EMUFUSION_FAKE_NATIVE_WINDOW_H
#define EMUFUSION_FAKE_NATIVE_WINDOW_H
#include <stdint.h>
typedef struct ANativeWindow { int marker; } ANativeWindow;
void ANativeWindow_acquire(ANativeWindow *window);
void ANativeWindow_release(ANativeWindow *window);
int ANativeWindow_setBuffersGeometry(ANativeWindow *window, int width,
                                     int height, int format);
int32_t ANativeWindow_getWidth(ANativeWindow *window);
int32_t ANativeWindow_getHeight(ANativeWindow *window);
#endif
