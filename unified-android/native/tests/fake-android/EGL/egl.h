#ifndef LUCENT_FAKE_EGL_H
#define LUCENT_FAKE_EGL_H
#include <stdint.h>
typedef void *EGLDisplay;
typedef void *EGLConfig;
typedef void *EGLContext;
typedef void *EGLSurface;
typedef int32_t EGLint;
typedef uint32_t EGLBoolean;
typedef void (*__eglMustCastToProperFunctionPointerType)(void);
#define EGL_FALSE 0
#define EGL_TRUE 1
#define EGL_DEFAULT_DISPLAY ((void *)0)
#define EGL_NO_DISPLAY ((EGLDisplay)0)
#define EGL_NO_CONTEXT ((EGLContext)0)
#define EGL_NO_SURFACE ((EGLSurface)0)
#define EGL_OPENGL_ES_API 0x30A0
#define EGL_SURFACE_TYPE 0x3033
#define EGL_WINDOW_BIT 0x0004
#define EGL_PBUFFER_BIT 0x0001
#define EGL_RENDERABLE_TYPE 0x3040
#define EGL_OPENGL_ES2_BIT 0x0004
#define EGL_RED_SIZE 0x3024
#define EGL_GREEN_SIZE 0x3023
#define EGL_BLUE_SIZE 0x3022
#define EGL_ALPHA_SIZE 0x3021
#define EGL_DEPTH_SIZE 0x3025
#define EGL_STENCIL_SIZE 0x3026
#define EGL_NONE 0x3038
#define EGL_WIDTH 0x3057
#define EGL_HEIGHT 0x3056
#define EGL_CONTEXT_CLIENT_VERSION 0x3098
#define EGL_NATIVE_VISUAL_ID 0x302E
#define EGL_SUCCESS 0x3000
#define EGL_CONTEXT_LOST 0x300E
#define EGL_EXTENSIONS 0x3055
const char *eglQueryString(EGLDisplay display, EGLint name);
EGLBoolean eglSurfaceAttrib(EGLDisplay display, EGLSurface surface, EGLint name, EGLint value);
EGLDisplay eglGetDisplay(void *display_id);
EGLBoolean eglInitialize(EGLDisplay display, EGLint *major, EGLint *minor);
EGLBoolean eglBindAPI(EGLint api);
EGLBoolean eglChooseConfig(EGLDisplay display, const EGLint *attributes,
                           EGLConfig *configs, EGLint size, EGLint *count);
EGLContext eglCreateContext(EGLDisplay display, EGLConfig config,
                            EGLContext shared, const EGLint *attributes);
EGLSurface eglCreatePbufferSurface(EGLDisplay display, EGLConfig config,
                                   const EGLint *attributes);
EGLSurface eglCreateWindowSurface(EGLDisplay display, EGLConfig config,
                                  void *window, const EGLint *attributes);
EGLBoolean eglMakeCurrent(EGLDisplay display, EGLSurface draw,
                          EGLSurface read, EGLContext context);
EGLContext eglGetCurrentContext(void);
EGLBoolean eglDestroySurface(EGLDisplay display, EGLSurface surface);
EGLBoolean eglDestroyContext(EGLDisplay display, EGLContext context);
EGLBoolean eglGetConfigAttrib(EGLDisplay display, EGLConfig config,
                              EGLint attribute, EGLint *value);
__eglMustCastToProperFunctionPointerType eglGetProcAddress(const char *name);
EGLBoolean eglSwapBuffers(EGLDisplay display, EGLSurface surface);
EGLBoolean eglTerminate(EGLDisplay display);
EGLint eglGetError(void);
#endif
