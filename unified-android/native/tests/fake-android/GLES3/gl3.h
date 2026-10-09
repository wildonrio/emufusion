#ifndef LUCENT_FAKE_GLES3_H
#define LUCENT_FAKE_GLES3_H

#include <stddef.h>

typedef unsigned char GLubyte;
typedef unsigned char GLboolean;
typedef unsigned int GLenum;
typedef unsigned int GLuint;
typedef unsigned int GLbitfield;
typedef int GLint;
typedef int GLsizei;
typedef float GLfloat;

#define GL_VERSION 0x1F02
#define GL_TEXTURE_2D 0x0DE1
#define GL_TEXTURE_MIN_FILTER 0x2801
#define GL_TEXTURE_MAG_FILTER 0x2800
#define GL_TEXTURE_WRAP_S 0x2802
#define GL_TEXTURE_WRAP_T 0x2803
#define GL_LINEAR 0x2601
#define GL_CLAMP_TO_EDGE 0x812F
#define GL_RGBA8 0x8058
#define GL_RGBA 0x1908
#define GL_UNSIGNED_BYTE 0x1401
#define GL_FRAMEBUFFER 0x8D40
#define GL_READ_FRAMEBUFFER 0x8CA8
#define GL_DRAW_FRAMEBUFFER 0x8CA9
#define GL_READ_FRAMEBUFFER_BINDING 0x8CAA
#define GL_DRAW_FRAMEBUFFER_BINDING 0x8CA6
#define GL_RENDERBUFFER 0x8D41
#define GL_COLOR_ATTACHMENT0 0x8CE0
#define GL_DEPTH_ATTACHMENT 0x8D00
#define GL_STENCIL_ATTACHMENT 0x8D20
#define GL_DEPTH_STENCIL_ATTACHMENT 0x821A
#define GL_DEPTH24_STENCIL8 0x88F0
#define GL_DEPTH_COMPONENT16 0x81A5
#define GL_STENCIL_INDEX8 0x8D48
#define GL_FRAMEBUFFER_COMPLETE 0x8CD5
#define GL_NO_ERROR 0
#define GL_COLOR_BUFFER_BIT 0x00004000
#define GL_COLOR_CLEAR_VALUE 0x0C22
#define GL_COLOR_WRITEMASK 0x0C23
#define GL_SCISSOR_TEST 0x0C11
#define GL_VIEWPORT 0x0BA2
#define GL_FALSE 0
#define GL_TRUE 1

const GLubyte *glGetString(GLenum name);
void glGenTextures(GLsizei count, GLuint *textures);
void glBindTexture(GLenum target, GLuint texture);
void glTexParameteri(GLenum target, GLenum name, GLint value);
void glTexImage2D(GLenum target, GLint level, GLint internal_format,
                  GLsizei width, GLsizei height, GLint border,
                  GLenum format, GLenum type, const void *pixels);
void glViewport(GLint x, GLint y, GLsizei width, GLsizei height);
void glClearColor(GLfloat red, GLfloat green, GLfloat blue, GLfloat alpha);
void glClear(GLbitfield mask);
void glGetFloatv(GLenum name, GLfloat *values);
void glGetBooleanv(GLenum name, GLboolean *values);
void glGetIntegerv(GLenum name, GLint *values);
GLboolean glIsEnabled(GLenum capability);
void glDisable(GLenum capability);
void glEnable(GLenum capability);
void glColorMask(GLboolean red, GLboolean green, GLboolean blue,
                 GLboolean alpha);
void glReadPixels(GLint x, GLint y, GLsizei width, GLsizei height,
                  GLenum format, GLenum type, void *pixels);
void glDeleteTextures(GLsizei count, const GLuint *textures);
void glGenFramebuffers(GLsizei count, GLuint *framebuffers);
void glBindFramebuffer(GLenum target, GLuint framebuffer);
void glFramebufferTexture2D(GLenum target, GLenum attachment,
                            GLenum texture_target, GLuint texture,
                            GLint level);
GLenum glCheckFramebufferStatus(GLenum target);
GLenum glGetError(void);
void glDeleteFramebuffers(GLsizei count, const GLuint *framebuffers);
void glGenRenderbuffers(GLsizei count, GLuint *renderbuffers);
void glBindRenderbuffer(GLenum target, GLuint renderbuffer);
void glRenderbufferStorage(GLenum target, GLenum format,
                           GLsizei width, GLsizei height);
void glFramebufferRenderbuffer(GLenum target, GLenum attachment,
                               GLenum renderbuffer_target,
                               GLuint renderbuffer);
void glDeleteRenderbuffers(GLsizei count, const GLuint *renderbuffers);
void glBlitFramebuffer(GLint source_x0, GLint source_y0,
                       GLint source_x1, GLint source_y1,
                       GLint destination_x0, GLint destination_y0,
                       GLint destination_x1, GLint destination_y1,
                       unsigned mask, GLenum filter);

#endif
