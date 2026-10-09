#ifndef LUCENT_FAKE_GLES2_H
#define LUCENT_FAKE_GLES2_H
typedef unsigned char GLubyte;
typedef unsigned int GLenum;
typedef unsigned int GLuint;
typedef int GLint;
typedef int GLsizei;
#define GL_VERSION 0x1F02
#define GL_EXTENSIONS 0x1F03
#define GL_NO_ERROR 0
const GLubyte *glGetString(GLenum name);
GLenum glGetError(void);
void glGetIntegerv(GLenum name, GLint *value);
#endif
