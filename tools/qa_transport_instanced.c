#include <OpenGL/OpenGL.h>
#include <OpenGL/gl3.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

static void fail(const char *message) { fprintf(stderr,"%s\n",message);exit(2); }
static GLuint compile(GLenum type,const char *path) {
    FILE *file=fopen(path,"rb");if(!file)fail("missing shader");
    fseek(file,0,SEEK_END);long size=ftell(file);rewind(file);
    if(size<1 || size>1000000)fail("invalid shader size");
    char *source=calloc(size+1,1);if(fread(source,1,size,file)!=(size_t)size)fail("short read");fclose(file);
    GLuint shader=glCreateShader(type);const char *text=source;
    glShaderSource(shader,1,&text,NULL);glCompileShader(shader);free(source);
    GLint ok;glGetShaderiv(shader,GL_COMPILE_STATUS,&ok);
    if(!ok){char log[8192];glGetShaderInfoLog(shader,sizeof log,NULL,log);fail(log);}return shader;
}
static GLuint tex(int unit,GLint format,const void *data,GLenum type) {
    GLuint texture;glGenTextures(1,&texture);glActiveTexture(GL_TEXTURE0+unit);glBindTexture(GL_TEXTURE_2D,texture);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D,0,format,64,32,0,GL_RGBA,type,data);return texture;
}
int main(int argc,char **argv) {
    if(argc!=3)fail("usage: runner vertex fragment");
    CGLPixelFormatAttribute attributes[]={kCGLPFAOpenGLProfile,(CGLPixelFormatAttribute)kCGLOGLPVersion_3_2_Core,kCGLPFAAccelerated,0};
    CGLPixelFormatObj format;CGLContextObj context;GLint count;
    if(CGLChoosePixelFormat(attributes,&format,&count)||!format)fail("no core format");
    if(CGLCreateContext(format,NULL,&context))fail("no core context");CGLDestroyPixelFormat(format);CGLSetCurrentContext(context);
    GLuint program=glCreateProgram();glAttachShader(program,compile(GL_VERTEX_SHADER,argv[1]));glAttachShader(program,compile(GL_FRAGMENT_SHADER,argv[2]));glLinkProgram(program);
    GLint ok;glGetProgramiv(program,GL_LINK_STATUS,&ok);if(!ok){char log[8192];glGetProgramInfoLog(program,sizeof log,NULL,log);fail(log);}
    glUseProgram(program);
    unsigned char valid[64*32*4],raw[64*32*4];
    for(int i=0;i<64*32;i++) {
        valid[i*4]=218;valid[i*4+1]=128;valid[i*4+2]=204;valid[i*4+3]=255;
        raw[i*4]=16;raw[i*4+1]=0;raw[i*4+2]=0;raw[i*4+3]=0; // +16 px Q8.8.
    }
    tex(0,GL_RGBA8,valid,GL_UNSIGNED_BYTE);tex(1,GL_RGBA8,raw,GL_UNSIGNED_BYTE);
    GLuint output=tex(2,GL_RGBA32F,NULL,GL_FLOAT),fb,vao;
    glGenFramebuffers(1,&fb);glBindFramebuffer(GL_FRAMEBUFFER,fb);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,output,0);
    if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)fail("bad target");
    glGenVertexArrays(1,&vao);glBindVertexArray(vao);glViewport(0,0,64,32);glDisable(GL_DITHER);
    glUniform1i(glGetUniformLocation(program,"field"),0);glUniform1i(glGetUniformLocation(program,"rawField"),1);
    glUniform1f(glGetUniformLocation(program,"useRaw"),1);
    glUniform2f(glGetUniformLocation(program,"size"),64,32);glUniform2f(glGetUniformLocation(program,"sourceSize"),64,32);
    glUniform2i(glGetUniformLocation(program,"gridSize"),64,32);
    glUniform2f(glGetUniformLocation(program,"camera"),.25,0);glUniform2f(glGetUniformLocation(program,"flowRange"),.5,.5);
    const float phases[]={0,.03125,.5,1};int failures=0;
    for(int control=0;control<2;control++)for(int p=0;p<4;p++) {
        glClearColor(128.f/255,128.f/255,0,0);glClear(GL_COLOR_BUFFER_BIT);
        glUniform1f(glGetUniformLocation(program,"phase"),phases[p]);
        glDrawArraysInstanced(GL_TRIANGLE_STRIP,0,4,64*(control?31:32));
        float pixels[64*32*4];glReadPixels(0,0,64,32,GL_RGBA,GL_FLOAT,pixels);
        if(glGetError()!=GL_NO_ERROR)fail("GL execution error");
        int errors=0;
        for(int y=0;y<32;y++)for(int x=0;x<64;x++) {
            int expected=x>phases[p]*16-1;
            float *pixel=pixels+(y*64+x)*4;
            int actual=pixel[2]>.5;
            if(actual!=expected)errors++;
            else if(actual) {
                float encoded=(pixel[0]*255-128)/127;
                if(fabsf(encoded*encoded*32-16)>.001)errors++;
            }
        }
        printf("control=%d phase=%.5f errors=%d\n",control,phases[p],errors);
        if((!control && errors) || (control && !errors))failures++;
    }
    // Two source pixels arrive at (20,10): 16px foreground and24px camera
    // background. Correct24px seed must select16; a zero seed selects24.
    memset(valid,0,sizeof valid);memset(raw,0,sizeof raw);
    int first=(10*64+12)*4,second=(10*64+8)*4;
    valid[first+2]=valid[second+2]=204;raw[first]=16;raw[second]=24;
    glActiveTexture(GL_TEXTURE0);glTexSubImage2D(GL_TEXTURE_2D,0,0,0,64,32,GL_RGBA,GL_UNSIGNED_BYTE,valid);
    glActiveTexture(GL_TEXTURE1);glTexSubImage2D(GL_TEXTURE_2D,0,0,0,64,32,GL_RGBA,GL_UNSIGNED_BYTE,raw);
    unsigned char seed[64*32*4];memset(seed,0,sizeof seed);
    for(int i=0;i<64*32;i++)seed[i*4]=24;
    tex(3,GL_RGBA8,seed,GL_UNSIGNED_BYTE);
    glUniform1i(glGetUniformLocation(program,"cameraSeed"),3);
    GLuint depth;glGenRenderbuffers(1,&depth);glBindRenderbuffer(GL_RENDERBUFFER,depth);
    glRenderbufferStorage(GL_RENDERBUFFER,GL_DEPTH_COMPONENT24,64,32);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER,GL_DEPTH_ATTACHMENT,GL_RENDERBUFFER,depth);
    if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)fail("depth target incomplete");
    glEnable(GL_DEPTH_TEST);glDepthFunc(GL_LESS);glDepthMask(GL_TRUE);glClearDepth(1);
    for(int mode=0;mode<3;mode++) {
        glUniform2f(glGetUniformLocation(program,"camera"),mode==1?0:.375,0);
        glUniform1f(glGetUniformLocation(program,"useCameraSeed"),mode==0?0:1);
        if(mode==2) {
            memset(seed,0,sizeof seed);glActiveTexture(GL_TEXTURE3);
            glTexSubImage2D(GL_TEXTURE_2D,0,0,0,64,32,GL_RGBA,GL_UNSIGNED_BYTE,seed);
        }
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        glUniform1f(glGetUniformLocation(program,"phase"),.5);
        glDrawArraysInstanced(GL_TRIANGLE_STRIP,0,4,64*32);
        float pixel[4];glReadPixels(20,10,1,1,GL_RGBA,GL_FLOAT,pixel);
        if(glGetError()!=GL_NO_ERROR)fail("seed overlap GL error");
        float c=(pixel[0]*255-128)/127, displacement=c*c*32;
        int expected=mode==2?24:16;
        int pass=pixel[2]>.5 && fabsf(displacement-expected)<.001;
        printf("seed_mode=%d selected=%.3f expected=%d %s\n",mode,displacement,expected,pass?"PASS":"FAIL");
        if(!pass)failures++;
    }
    CGLSetCurrentContext(NULL);CGLDestroyContext(context);return failures?1:0;
}
