/*
 * Host runner for the exported learned-estimator shaders (macOS, OpenGL 4.1
 * core via CGL). Reads a command script on stdin; GLSL ES 3.00 sources are
 * translated to "#version 410" by swapping the version line.
 *
 *   tex  NAME W H rgba8|rgba16f [FILE]   create (FILE: W*H*4 float32, top row first)
 *   prog NAME VERT FRAG
 *   use  PROG
 *   i1 NAME v | f1 NAME v | i2 NAME a b | f2 NAME a b | sampler NAME TEX UNIT
 *   draw W H TEX[,TEX...]                 render into the listed targets
 *   read TEX FILE                         write W*H*4 float32, top row first
 *
 * Build: cc -O2 -o gl_harness gl_harness.c -framework OpenGL
 */
#include <OpenGL/OpenGL.h>
#include <OpenGL/gl3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { char name[64]; GLuint id; int w, h; int half; } Tex;
typedef struct { char name[64]; GLuint id; } Prog;
static Tex texs[16384]; static int ntex;
static Prog progs[64]; static int nprog;
static GLuint current;

static Tex *find_tex(const char *n) {
    for (int i = 0; i < ntex; ++i) if (!strcmp(texs[i].name, n)) return &texs[i];
    fprintf(stderr, "no texture %s\n", n); exit(2);
}

static char *slurp(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) { fprintf(stderr, "open %s\n", path); exit(2); }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *s = malloc(n + 64); fread(s, 1, n, f); s[n] = 0; fclose(f);
    char *v = strstr(s, "#version 300 es");
    if (v) memcpy(v, "#version 410   ", 15);
    /* desktop GLSL rejects a precision statement for sampler2D */
    char *p = strstr(s, "precision highp sampler2D;");
    if (p) memset(p, ' ', strlen("precision highp sampler2D;"));
    return s;
}

static GLuint compile(GLenum type, const char *path) {
    char *src = slurp(path);
    GLuint sh = glCreateShader(type);
    glShaderSource(sh, 1, (const char **)&src, NULL); glCompileShader(sh);
    GLint ok; glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[8192]; glGetShaderInfoLog(sh, sizeof log, NULL, log); fprintf(stderr, "%s: %s\n", path, log); exit(3); }
    free(src); return sh;
}

int main(void) {
    CGLPixelFormatAttribute attrs[] = { kCGLPFAOpenGLProfile, (CGLPixelFormatAttribute)kCGLOGLPVersion_3_2_Core,
                                        kCGLPFAAccelerated, (CGLPixelFormatAttribute)0 };
    CGLPixelFormatObj pf; GLint npf; CGLContextObj ctx;
    if (CGLChoosePixelFormat(attrs, &pf, &npf) || CGLCreateContext(pf, NULL, &ctx) || CGLSetCurrentContext(ctx)) {
        fprintf(stderr, "no GL context\n"); return 1;
    }
    GLuint vao, fbo; glGenVertexArrays(1, &vao); glBindVertexArray(vao); glGenFramebuffers(1, &fbo);
    char cmd[64];
    while (scanf("%63s", cmd) == 1) {
        if (!strcmp(cmd, "tex")) {
            if (ntex >= 16384) { fprintf(stderr, "too many textures\n"); return 2; } Tex *t = &texs[ntex++]; char fmt[16], file[1024]; int c;
            scanf("%63s %d %d %15s", t->name, &t->w, &t->h, fmt); t->half = !strcmp(fmt, "rgba16f");
            file[0] = 0; while ((c = getchar()) == ' '); if (c != '\n' && c != EOF) { ungetc(c, stdin); scanf("%1023s", file); }
            float *data = NULL;
            if (file[0]) {
                data = malloc((size_t)t->w * t->h * 16); FILE *f = fopen(file, "rb");
                if (!f || fread(data, 16, (size_t)t->w * t->h, f) != (size_t)t->w * t->h) { fprintf(stderr, "read %s\n", file); return 2; }
                fclose(f);
                /* flip to GL bottom-up rows */
                float *flip = malloc((size_t)t->w * t->h * 16);
                for (int y = 0; y < t->h; ++y) memcpy(flip + (size_t)y * t->w * 4, data + (size_t)(t->h - 1 - y) * t->w * 4, (size_t)t->w * 16);
                free(data); data = flip;
            }
            glGenTextures(1, &t->id); glBindTexture(GL_TEXTURE_2D, t->id);
            glTexImage2D(GL_TEXTURE_2D, 0, t->half ? GL_RGBA16F : GL_RGBA8, t->w, t->h, 0, GL_RGBA, GL_FLOAT, data);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
            free(data);
        } else if (!strcmp(cmd, "prog")) {
            Prog *p = &progs[nprog++]; char vs[1024], fs[1024];
            scanf("%63s %1023s %1023s", p->name, vs, fs);
            p->id = glCreateProgram();
            glAttachShader(p->id, compile(GL_VERTEX_SHADER, vs)); glAttachShader(p->id, compile(GL_FRAGMENT_SHADER, fs));
            for (int i = 0; i < 4; ++i) { char n[8]; snprintf(n, sizeof n, "o%d", i); glBindFragDataLocation(p->id, i, n); }
            glLinkProgram(p->id); GLint ok; glGetProgramiv(p->id, GL_LINK_STATUS, &ok);
            if (!ok) { char log[8192]; glGetProgramInfoLog(p->id, sizeof log, NULL, log); fprintf(stderr, "link %s: %s\n", p->name, log); return 3; }
        } else if (!strcmp(cmd, "use")) {
            char n[64]; scanf("%63s", n); current = 0;
            for (int i = 0; i < nprog; ++i) if (!strcmp(progs[i].name, n)) current = progs[i].id;
            if (!current) { fprintf(stderr, "no program %s\n", n); return 2; }
            glUseProgram(current);
        } else if (!strcmp(cmd, "i1")) { char n[64]; int v; scanf("%63s %d", n, &v); glUniform1i(glGetUniformLocation(current, n), v);
        } else if (!strcmp(cmd, "f1")) { char n[64]; float v; scanf("%63s %f", n, &v); glUniform1f(glGetUniformLocation(current, n), v);
        } else if (!strcmp(cmd, "i2")) { char n[64]; int a, b; scanf("%63s %d %d", n, &a, &b); glUniform2i(glGetUniformLocation(current, n), a, b);
        } else if (!strcmp(cmd, "f2")) { char n[64]; float a, b; scanf("%63s %f %f", n, &a, &b); glUniform2f(glGetUniformLocation(current, n), a, b);
        } else if (!strcmp(cmd, "sampler")) {
            char n[64], tn[64]; int unit; scanf("%63s %63s %d", n, tn, &unit);
            glActiveTexture(GL_TEXTURE0 + unit); glBindTexture(GL_TEXTURE_2D, find_tex(tn)->id);
            glUniform1i(glGetUniformLocation(current, n), unit);
        } else if (!strcmp(cmd, "draw")) {
            int w, h; char list[1024]; scanf("%d %d %1023s", &w, &h, list);
            glBindFramebuffer(GL_FRAMEBUFFER, fbo);
            GLenum bufs[4]; int n = 0; char *save = NULL;
            for (char *tok = strtok_r(list, ",", &save); tok; tok = strtok_r(NULL, ",", &save)) {
                glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0 + n, GL_TEXTURE_2D, find_tex(tok)->id, 0);
                bufs[n] = GL_COLOR_ATTACHMENT0 + n; ++n;
            }
            for (int i = n; i < 4; ++i) glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0 + i, GL_TEXTURE_2D, 0, 0);
            glDrawBuffers(n, bufs);
            if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) { fprintf(stderr, "fbo incomplete\n"); return 4; }
            glViewport(0, 0, w, h); glDrawArrays(GL_TRIANGLES, 0, 3);
        } else if (!strcmp(cmd, "read")) {
            char tn[64], file[1024]; scanf("%63s %1023s", tn, file); Tex *t = find_tex(tn);
            float *data = malloc((size_t)t->w * t->h * 16);
            glBindFramebuffer(GL_FRAMEBUFFER, fbo);
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, t->id, 0);
            for (int i = 1; i < 4; ++i) glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0 + i, GL_TEXTURE_2D, 0, 0);
            glReadBuffer(GL_COLOR_ATTACHMENT0);
            glReadPixels(0, 0, t->w, t->h, GL_RGBA, GL_FLOAT, data);
            FILE *f = fopen(file, "wb");
            for (int y = t->h - 1; y >= 0; --y) fwrite(data + (size_t)y * t->w * 4, 16, t->w, f);
            fclose(f); free(data);
        } else { fprintf(stderr, "unknown command %s\n", cmd); return 2; }
        GLenum err = glGetError(); if (err) { fprintf(stderr, "GL error 0x%x after %s\n", err, cmd); return 5; }
    }
    return 0;
}
