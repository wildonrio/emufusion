/* Host-only execution of the actual interpolation fragment shader.
 * Known rigid translation supplies an exact midpoint, not another flow solver.
 * macOS: clang -Wno-deprecated-declarations -framework OpenGL this.c -o runner
 */
#include <OpenGL/OpenGL.h>
#include <OpenGL/gl.h>
#include <OpenGL/glext.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

enum { W = 64, H = 32 };
/* Host fixture estimator, horizontal motion only; not Android integration. */
static float dominantX(const float *data) {
    int counts[256]={0},best=0;float encoded=128.f/255.f;
    for(int i=0;i<W*H;++i) if(data[i*4+2]>=48.f/255.f) {
        int bin=(int)lroundf(data[i*4]*255.f);
        if(bin<0 || bin>255) continue;
        if(++counts[bin]>best){best=counts[bin];encoded=data[i*4];}
    }
    float v=(encoded*255-128)/127;return copysignf(v*v*.5f,v);
}
static void fail(const char *s) { fprintf(stderr, "%s\n", s); exit(2); }
static char *readShader(const char *path) {
    if(!path)fail("shared shader path missing");
    FILE *file=fopen(path,"rb");if(!file)fail("shared shader open failed");
    fseek(file,0,SEEK_END);long size=ftell(file);rewind(file);
    if(size<=0 || size>1000000)fail("shared shader size invalid");
    char *text=calloc(size+1,1);
    if(fread(text,1,size,file)!=(size_t)size)fail("shared shader read failed");
    fclose(file);return text;
}
static GLuint shader(GLenum kind, const char *text) {
    GLuint s = glCreateShader(kind);
    glShaderSource(s, 1, &text, NULL); glCompileShader(s);
    GLint ok; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[16384]; glGetShaderInfoLog(s, sizeof log, NULL, log); fail(log); }
    return s;
}
static void scalar(GLuint p, const char *name, float v) {
    glUniform1f(glGetUniformLocation(p, name), v);
}
static GLuint texture(GLuint p, const char *name, int unit, const float *data) {
    GLuint t; glGenTextures(1, &t); glActiveTexture(GL_TEXTURE0 + unit);
    glBindTexture(GL_TEXTURE_2D, t);
    int filter=(strcmp(name,"uPrevious")==0 || strcmp(name,"uCurrent")==0)?GL_LINEAR:GL_NEAREST;
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    int validated=strcmp(name,"uForwardMotion")==0 || strcmp(name,"uBackwardMotion")==0;
    glTexImage2D(GL_TEXTURE_2D, 0, validated && getenv("EMUFUSION_QA_RGBA8_INPUT")?GL_RGBA8:GL_RGBA32F_ARB, W, H, 0, GL_RGBA, GL_FLOAT, data);
    glUniform1i(glGetUniformLocation(p, name), unit); return t;
}
/* Experimental GPU forward transport, not part of the Android renderer yet.
 * Camera-relative motion priority is a fixture policy, not general occlusion
 * inference. Each quad transports one endpoint pixel's reconstruction support.
 */
static void quad(float u,float v,float extra) {
    glVertexAttrib2f(2,extra,extra);
    glVertexAttrib2f(1,-1,-1);glVertex2f(u,v);glVertexAttrib2f(1,1,-1);glVertex2f(u,v);
    glVertexAttrib2f(1,1,1);glVertex2f(u,v);glVertexAttrib2f(1,-1,1);glVertex2f(u,v);
}
/* Readback is only for host mesh construction and independent classifier QA.
 * Production will need GPU-resident compaction; this is not that implementation. */
static void classify(GLuint source,GLuint raw,unsigned char *flags,int side) {
    char *fs=readShader(getenv("EMUFUSION_TRANSPORT_CLASSIFY"));
    GLuint p=glCreateProgram(),v=shader(GL_VERTEX_SHADER,"#version 120\nvoid main(){gl_Position=gl_Vertex;}"),f=shader(GL_FRAGMENT_SHADER,fs);
    free(fs);glAttachShader(p,v);glAttachShader(p,f);glLinkProgram(p);
    GLint ok;glGetProgramiv(p,GL_LINK_STATUS,&ok);if(!ok)fail("classifier link failed");
    glUseProgram(p);
    glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,source);
    glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,raw);
    glUniform1i(glGetUniformLocation(p,"field"),0);glUniform1i(glGetUniformLocation(p,"rawField"),1);
    glUniform2f(glGetUniformLocation(p,"sourceSize"),W,H);
    scalar(p,"tileSide",side);
    GLuint out,fb;glGenTextures(1,&out);glActiveTexture(GL_TEXTURE9);glBindTexture(GL_TEXTURE_2D,out);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,W/side,H/side,0,GL_RGBA,GL_UNSIGNED_BYTE,NULL);
    glGenFramebuffersEXT(1,&fb);glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,fb);
    glFramebufferTexture2DEXT(GL_FRAMEBUFFER_EXT,GL_COLOR_ATTACHMENT0_EXT,GL_TEXTURE_2D,out,0);
    if(glCheckFramebufferStatusEXT(GL_FRAMEBUFFER_EXT)!=GL_FRAMEBUFFER_COMPLETE_EXT)fail("classifier FBO incomplete");
    glDisable(GL_DEPTH_TEST);glViewport(0,0,W/side,H/side);
    glBegin(GL_QUADS);glVertex2f(-1,-1);glVertex2f(1,-1);glVertex2f(1,1);glVertex2f(-1,1);glEnd();
    glReadPixels(0,0,W/side,H/side,GL_RGBA,GL_UNSIGNED_BYTE,flags);
    glDeleteFramebuffersEXT(1,&fb);glDeleteTextures(1,&out);
    glDeleteProgram(p);glDeleteShader(v);glDeleteShader(f);
}
/* Host reference for hierarchical exact merging, no approximate flow equality.
 * Large coherent regions must shrink by more than the 2x2 path's maximum 4x
 * before that path is worth translating into GPU compaction. */
static int emitRegion(const float *fields,const float *rawFields,const unsigned char flags[3][W*H],int x,int y,int side) {
    int equal=1,base=(y*W+x)*4;
    for(int dy=0;dy<side && equal;dy++)for(int dx=0;dx<side && equal;dx++)for(int c=0;c<4;c++) {
        int i=((y+dy)*W+x+dx)*4+c;
        equal &= fields[i]==fields[base+c] && rawFields[i]==rawFields[base+c];
    }
    if(side>1) {
        int level=side==8?2:(side==4?1:0);
        int gpu=flags[level][((y/side)*(W/side)+x/side)*4]==255;
        if(gpu!=equal)fail("GPU hierarchy differs from CPU reference");
        equal=gpu;
    }
    if(equal) {
        quad((x+side*.5f)/W,(y+side*.5f)/H,(side-1)*.5f);
        return 1;
    }
    int half=side/2;
    return emitRegion(fields,rawFields,flags,x,y,half)+emitRegion(fields,rawFields,flags,x+half,y,half)
        +emitRegion(fields,rawFields,flags,x,y+half,half)+emitRegion(fields,rawFields,flags,x+half,y+half,half);
}
static GLuint transport(GLuint source, float phase, float camera, GLuint raw) {
    char *vs=readShader(getenv("EMUFUSION_TRANSPORT_VERTEX"));
    char *fs=readShader(getenv("EMUFUSION_TRANSPORT_FRAGMENT"));
    GLuint p=glCreateProgram(), v=shader(GL_VERTEX_SHADER,vs), f=shader(GL_FRAGMENT_SHADER,fs);
    glAttachShader(p,v);glAttachShader(p,f);
    glBindAttribLocation(p,0,"aSourceUv");glBindAttribLocation(p,1,"aCorner");glBindAttribLocation(p,2,"aExtraRadius");glLinkProgram(p);
    free(vs);free(fs);
    GLint ok;glGetProgramiv(p,GL_LINK_STATUS,&ok);if(!ok)fail("transport link failed");
    glUseProgram(p);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,source);
    glUniform1i(glGetUniformLocation(p,"field"),0);scalar(p,"phase",phase);
    glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,raw);
    glUniform1i(glGetUniformLocation(p,"rawField"),1);
    scalar(p,"useRaw",getenv("EMUFUSION_QA_RAW_DISPLACEMENT")?1:0);
    glUniform2f(glGetUniformLocation(p,"sourceSize"),W,H);
    glUniform2f(glGetUniformLocation(p,"camera"),camera,0);
    glUniform2f(glGetUniformLocation(p,"flowRange"),.5f,.5f);
    glUniform2f(glGetUniformLocation(p,"size"),W,H);
    GLuint out,fb,depth;glGenTextures(1,&out);glActiveTexture(GL_TEXTURE9);glBindTexture(GL_TEXTURE_2D,out);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    GLint transportFormat=getenv("EMUFUSION_QA_RGBA8_TRANSPORT")?GL_RGBA8:
        (getenv("EMUFUSION_QA_RGBA16F_TRANSPORT")?GL_RGBA16F_ARB:GL_RGBA32F_ARB);
    glTexImage2D(GL_TEXTURE_2D,0,transportFormat,W,H,0,GL_RGBA,GL_FLOAT,NULL);
    glGenFramebuffersEXT(1,&fb);glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,fb);
    glFramebufferTexture2DEXT(GL_FRAMEBUFFER_EXT,GL_COLOR_ATTACHMENT0_EXT,GL_TEXTURE_2D,out,0);
    glGenRenderbuffersEXT(1,&depth);glBindRenderbufferEXT(GL_RENDERBUFFER_EXT,depth);
    glRenderbufferStorageEXT(GL_RENDERBUFFER_EXT,GL_DEPTH_COMPONENT24,W,H);
    glFramebufferRenderbufferEXT(GL_FRAMEBUFFER_EXT,GL_DEPTH_ATTACHMENT_EXT,GL_RENDERBUFFER_EXT,depth);
    if(glCheckFramebufferStatusEXT(GL_FRAMEBUFFER_EXT)!=GL_FRAMEBUFFER_COMPLETE_EXT)fail("transport FBO incomplete");
    glViewport(0,0,W,H);glClearColor(128.f/255.f,128.f/255.f,0,0);glClearDepth(1);
    glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);glEnable(GL_DEPTH_TEST);glDepthFunc(GL_LESS);
    int hierarchical=getenv("EMUFUSION_QA_HIERARCHICAL")!=NULL;
    int coalesce=hierarchical || getenv("EMUFUSION_QA_COALESCE")!=NULL;
    float fields[W*H*4],rawFields[W*H*4];
    unsigned char flags[3][W*H];
    // Host proof only: a production implementation must classify on GPU,
    // never perform these synchronous readbacks during gameplay.
    if(coalesce) {
        glActiveTexture(GL_TEXTURE0);glGetTexImage(GL_TEXTURE_2D,0,GL_RGBA,GL_FLOAT,fields);
        glActiveTexture(GL_TEXTURE1);glGetTexImage(GL_TEXTURE_2D,0,GL_RGBA,GL_FLOAT,rawFields);
        classify(source,raw,flags[0],2);
        if(hierarchical) {
            classify(source,raw,flags[1],4);
            classify(source,raw,flags[2],8);
        }
        glUseProgram(p);glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,fb);
        glViewport(0,0,W,H);glEnable(GL_DEPTH_TEST);
    }
    glBegin(GL_QUADS);
    int quads=0;
    if(hierarchical) {
        for(int y=0;y<H;y+=8)for(int x=0;x<W;x+=8)
            quads+=emitRegion(fields,rawFields,flags,x,y,8);
    } else
    for(int y=0;y<H;y+=2)for(int x=0;x<W;x+=2) {
        int equal=coalesce,base=(y*W+x)*4;
        if(coalesce)for(int dy=0;dy<2;dy++)for(int dx=0;dx<2;dx++)for(int c=0;c<4;c++) {
            int i=((y+dy)*W+x+dx)*4+c;
            equal &= fields[i]==fields[base+c] && rawFields[i]==rawFields[base+c];
        }
        if(coalesce) {
            int gpu=flags[0][((y/2)*(W/2)+x/2)*4]==255;
            if(gpu!=equal)fail("GPU tile classification differs from CPU reference");
            equal=gpu;
        }
        if(equal)quad((x+1.f)/W,(y+1.f)/H,.5f);
        else for(int dy=0;dy<2;dy++)for(int dx=0;dx<2;dx++)quad((x+dx+.5f)/W,(y+dy+.5f)/H,0);
    }
    glEnd();glDisable(GL_DEPTH_TEST);
    if(hierarchical)fprintf(stderr,"hierarchical_quads=%d original_quads=%d\n",quads,W*H);
    glDeleteFramebuffersEXT(1,&fb);glDeleteRenderbuffersEXT(1,&depth);
    glDeleteProgram(p);glDeleteShader(v);glDeleteShader(f);return out;
}
int main(int argc, char **argv) {
    if (argc < 2 || argc > 6) fail("usage: runner actual-interpolation.glsl [forward|reverse] [contrast-byte] [local|global] [transport]");
    int reverse=argc>=3 && strcmp(argv[2],"reverse")==0;
    int objectOffset=getenv("EMUFUSION_QA_UNALIGNED_OBJECT")?1:0;
    int contrast=argc>=4?atoi(argv[3]):255;
    int opposedBackground=argc>=5 && strcmp(argv[4],"opposed-background")==0;
    int fastBackground=opposedBackground || (argc>=5 && strcmp(argv[4],"fast-background")==0);
    int scrolling=fastBackground || (argc>=5 && strcmp(argv[4],"scrolling")==0);
    int backgroundShift=opposedBackground?-24:(fastBackground?24:(scrolling?4:0));
    int local=scrolling || (argc>=5 && strcmp(argv[4],"local")==0);
    int transported=argc==6 && strcmp(argv[5],"transport")==0;
    if(contrast<1 || contrast>255) fail("contrast must be 1..255");
    FILE *file = fopen(argv[1], "rb"); if (!file) fail("shader file missing");
    fseek(file, 0, SEEK_END); long n = ftell(file); rewind(file);
    if (n <= 0 || n > 1000000) fail("invalid shader length");
    char *fragment = calloc(n + 1, 1);
    if (fread(fragment, 1, n, file) != (size_t)n) fail("shader read failed"); fclose(file);
    CGLPixelFormatAttribute attrs[] = { kCGLPFAAccelerated, 0 };
    CGLPixelFormatObj format; GLint count; CGLContextObj context;
    if (CGLChoosePixelFormat(attrs, &format, &count) || !format) fail("no CGL format");
    if (CGLCreateContext(format, NULL, &context)) fail("no CGL context");
    CGLDestroyPixelFormat(format); CGLSetCurrentContext(context);
    const char *vertex = "#version 120\nvarying vec2 vTexCoord; void main(){gl_Position=gl_Vertex;vTexCoord=gl_MultiTexCoord0.xy;}";
    GLuint p = glCreateProgram(); glAttachShader(p, shader(GL_VERTEX_SHADER, vertex));
    glAttachShader(p, shader(GL_FRAGMENT_SHADER, fragment)); glLinkProgram(p);
    GLint ok; glGetProgramiv(p, GL_LINK_STATUS, &ok); if (!ok) fail("shader link failed");
    glUseProgram(p);
    float a[W*H*4], b[W*H*4], f[W*H*4], back[W*H*4], zero[W*H*4];
    for (int y=0; y<H; ++y) for (int x=0; x<W; ++x) {
        int i=(y*W+x)*4;
        for(int c=0;c<4;++c) {
            int hud=x>=44 && x<48 && y>=2 && y<6;
            a[i+c] = c==3 || hud ? 1.f : (x>=12+objectOffset && x<20+objectOffset && y>=8 && y<24)*contrast/255.f;
            b[i+c] = c==3 || hud ? 1.f : (x>=28+objectOffset && x<36+objectOffset && y>=8 && y<24)*contrast/255.f;
            if(scrolling && c<3 && !hud) {
                if(!(x>=12+objectOffset && x<20+objectOffset && y>=8 && y<24)) a[i+c]=(32.f+x)/255.f;
                if(!(x>=28+objectOffset && x<36+objectOffset && y>=8 && y<24)) b[i+c]=(32.f+x-backgroundShift)/255.f;
            }
            zero[i+c]=0;
        }
        f[i]=(128.f+127.f*sqrtf(.5f))/255.f;
        back[i]=(128.f-127.f*sqrtf(.5f))/255.f;
        // Exact endpoint-domain motion: only the object moves; background
        // pixels stay still. Newly covered/disoccluded pixels have no valid
        // reciprocal correspondence. Unlike a constant camera pan, these
        // fields must be transported to the intermediate coordinate system.
        if(local) {
            float background=copysignf(sqrtf(fabsf(backgroundShift/32.f))*127.f,backgroundShift);
            if(!(x>=12+objectOffset && x<20+objectOffset && y>=8 && y<24)) f[i]=(128.f+background)/255.f;
            if(!(x>=28+objectOffset && x<36+objectOffset && y>=8 && y<24)) back[i]=(128.f-background)/255.f;
            if(x>=44 && x<48 && y>=2 && y<6) f[i]=back[i]=128.f/255.f;
        }
        f[i+1]=back[i+1]=128.f/255.f;
        f[i+2]=back[i+2]=.8f; f[i+3]=back[i+3]=1;
        if(local && y>=8 && y<24) {
            int shift=backgroundShift;
            if(x>=28+objectOffset-shift && x<36+objectOffset-shift) f[i+2]=0; // Background covered at B.
            if(x>=12+objectOffset+shift && x<20+objectOffset+shift) back[i+2]=0; // Background revealed at B.
            // Visible foreground still has its exact reciprocal match.
            if(x>=12+objectOffset && x<20+objectOffset) f[i+2]=.8f;
            if(x>=28+objectOffset && x<36+objectOffset) back[i+2]=.8f;
        }
    }
    float rawF[W*H*4],rawB[W*H*4];
    memcpy(rawF,f,sizeof f);memcpy(rawB,back,sizeof back);
    // Match Android validation's zero-vector encoding for rejected cells.
    // Kept opt-in so the retained-vector prototype remains a paired control.
    if(getenv("EMUFUSION_QA_CLEAR_REJECTED_FLOW")) {
        for(int i=0;i<W*H;++i) {
            if(f[i*4+2]<40.f/255.f) f[i*4]=f[i*4+1]=128.f/255.f;
            if(back[i*4+2]<40.f/255.f) back[i*4]=back[i*4+1]=128.f/255.f;
        }
    }
    GLuint previous=texture(p,"uPrevious",0,reverse?b:a), current=texture(p,"uCurrent",1,reverse?a:b);
    GLuint forwardTex=texture(p,"uForwardMotion",2,reverse?back:f), backwardTex=texture(p,"uBackwardMotion",3,reverse?f:back);
    float cameraF=dominantX(reverse?back:f),cameraB=dominantX(reverse?f:back);
    glUniform2f(glGetUniformLocation(p,"uEndpointCameraForward"),cameraF,0);
    glUniform2f(glGetUniformLocation(p,"uEndpointCameraBackward"),cameraB,0);
    glActiveTexture(GL_TEXTURE10);glBindTexture(GL_TEXTURE_2D,forwardTex);
    glUniform1i(glGetUniformLocation(p,"uEndpointForward"),10);
    glActiveTexture(GL_TEXTURE11);glBindTexture(GL_TEXTURE_2D,backwardTex);
    glUniform1i(glGetUniformLocation(p,"uEndpointBackward"),11);
    GLuint rawForwardTex=forwardTex,rawBackwardTex=backwardTex;
    if(getenv("EMUFUSION_QA_RETAIN_RAW_FLOW")) {
        if(getenv("EMUFUSION_QA_PACKED_RAW_FLOW")) {
            float *planes[]={rawF,rawB};
            for(int plane=0;plane<2;++plane)for(int i=0;i<W*H;++i) {
                float *pixel=planes[plane]+i*4;
                float dx=(pixel[0]*255-128)/127,dy=(pixel[1]*255-128)/127;
                int qx=(int)lroundf(copysignf(dx*dx*.5f*W,dx)*256);
                int qy=(int)lroundf(copysignf(dy*dy*.5f*H,dy)*256);
                unsigned ux=(unsigned)qx&65535u,uy=(unsigned)qy&65535u;
                pixel[0]=(ux>>8)/255.f;pixel[1]=(ux&255)/255.f;
                pixel[2]=(uy>>8)/255.f;pixel[3]=(uy&255)/255.f;
            }
            scalar(p,"uEndpointPacked",1);
        }
        rawForwardTex=texture(p,"uEndpointForward",10,reverse?rawB:rawF);
        rawBackwardTex=texture(p,"uEndpointBackward",11,reverse?rawF:rawB);
    }
    texture(p,"uGlobalForwardMotion",4,zero); texture(p,"uGlobalBackwardMotion",5,zero);
    texture(p,"uDenseSeedForwardTex",6,zero); texture(p,"uDenseSeedBackwardTex",7,zero);
    texture(p,"uDenseCutTex",8,zero);
    scalar(p,"uDenseEncoding",1); scalar(p,"uDenseSeedEnabled",0); scalar(p,"uDenseCutEnabled",0);
    if(getenv("EMUFUSION_QA_GPU_SYNTHESIS_SEEDS")) {
        float seeds[2][W*H*4];float cameras[]={cameraF,cameraB};
        const char *names[]={"uDenseSeedForwardTex","uDenseSeedBackwardTex"};
        for(int d=0;d<2;d++) {
            unsigned q=(unsigned)(int)lroundf(cameras[d]*W*256)&65535u;
            for(int i=0;i<W*H;i++) {
                seeds[d][i*4]=(q>>8)/255.f;seeds[d][i*4+1]=(q&255)/255.f;
                seeds[d][i*4+2]=seeds[d][i*4+3]=0;
            }
            texture(p,names[d],6+d,seeds[d]);
        }
        scalar(p,"uDenseSeedEnabled",1);
        // Conflicting CPU values prove synthesis consumes the GPU seeds.
        glUniform2f(glGetUniformLocation(p,"uEndpointCameraForward"),0,0);
        glUniform2f(glGetUniformLocation(p,"uEndpointCameraBackward"),0,0);
    }
    glUniform2f(glGetUniformLocation(p,"uFlowRange"),.5f,.5f);
    glUniform2f(glGetUniformLocation(p,"uDenseSeedSourceSize"),W,H);
    GLuint output, fb; glGenTextures(1,&output); glActiveTexture(GL_TEXTURE9);
    glBindTexture(GL_TEXTURE_2D,output);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,W,H,0,GL_RGBA,GL_UNSIGNED_BYTE,NULL);
    glGenFramebuffersEXT(1,&fb); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,fb);
    glFramebufferTexture2DEXT(GL_FRAMEBUFFER_EXT,GL_COLOR_ATTACHMENT0_EXT,GL_TEXTURE_2D,output,0);
    if(glCheckFramebufferStatusEXT(GL_FRAMEBUFFER_EXT)!=GL_FRAMEBUFFER_COMPLETE_EXT) fail("incomplete FBO");
    glViewport(0,0,W,H); glDisable(GL_BLEND); glDisable(GL_DITHER);
    int totalErrors=0;
    const float phases[]={0,.03125f,.25f,.46875f,.5f,.53125f,.75f,.96875f,1};
    for(int phaseIndex=0;phaseIndex<9;++phaseIndex) {
        float phase=phases[phaseIndex];
        GLuint tf=0,tb=0;
        if(transported) {
            tf=transport(forwardTex,phase,cameraF,rawForwardTex);tb=transport(backwardTex,1-phase,cameraB,rawBackwardTex);
            glUseProgram(p);glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,fb);
            glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,previous);
            glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,current);
            glActiveTexture(GL_TEXTURE2);glBindTexture(GL_TEXTURE_2D,tf);
            glActiveTexture(GL_TEXTURE3);glBindTexture(GL_TEXTURE_2D,tb);
        }
        scalar(p,"uPhase",phase);
        glBegin(GL_QUADS);
        glTexCoord2f(0,0);glVertex2f(-1,-1); glTexCoord2f(1,0);glVertex2f(1,-1);
        glTexCoord2f(1,1);glVertex2f(1,1); glTexCoord2f(0,1);glVertex2f(-1,1); glEnd();
        unsigned char pixels[W*H*4]; glReadPixels(0,0,W,H,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
        if(glGetError()!=GL_NO_ERROR) fail("GL execution error");
        int errors=0, visible=0, missing=0, extra=0, hudRowErrors=0, objectRowErrors=0;
        for(int y=0;y<H;++y) for(int x=0;x<W;++x) {
            // Scrolling-edge content outside the endpoint images is unknown;
            // this case verifies interior layers, not invented offscreen data.
            if(scrolling && (x<8 || x>=56)) continue;
            if(fastBackground && (x<24 || x>=40)) continue;
            float start=objectOffset+(reverse?28-phase*16:12+phase*16);
            int hud=x>=44 && x<48 && y>=2 && y<6;
            // Analytic area coverage of a translating unit-pixel rectangle.
            // With linear endpoint reconstruction, a half-pixel boundary
            // contributes half intensity, not a full pixel snapped sideways.
            float coverage=fmaxf(0,fminf(x+1,start+8)-fmaxf(x,start));
            int expected=hud?255:(int)lroundf(coverage*(y>=8 && y<24)*contrast);
            if(scrolling && !hud) {
                float objectCoverage=coverage*(y>=8 && y<24);
                float background=32+x-backgroundShift*(reverse?1-phase:phase);
                expected=(int)lroundf(objectCoverage*contrast+(1-objectCoverage)*background);
            }
            int actual=pixels[(y*W+x)*4]; visible+=actual>contrast/2;
            missing+=expected>contrast/2 && actual<=contrast/2;
            extra+=expected<=contrast/2 && actual>contrast/2;
            int pixelError=0;
            for(int c=0;c<3;++c) pixelError |= abs(pixels[(y*W+x)*4+c]-expected)>1;
            if(pixelError && getenv("EMUFUSION_QA_PIXEL_ERRORS") && (errors<6 || y==8))
                fprintf(stderr,"pixel scrolling=%d phase=%.5f reverse=%d x=%d y=%d expected=%d actual=%d\n",scrolling,phase,reverse,x,y,expected,actual);
            errors+=pixelError;
            if(y>=2 && y<6) hudRowErrors+=pixelError;
            if(y>=8 && y<24) objectRowErrors+=pixelError;
        }
        printf("background_shift=%d scrolling=%d local=%d contrast=%d reverse=%d phase=%.5f expected_white=144 actual_white=%d mismatched_pixels=%d missing=%d extra=%d\n",backgroundShift,scrolling,local,contrast,reverse,phase,visible,errors,missing,extra);
        totalErrors+=errors;
        if(errors && getenv("EMUFUSION_QA_PIXEL_ERRORS"))
            fprintf(stderr,"regions phase=%.5f reverse=%d hud_rows=%d object_rows=%d other=%d\n",phase,reverse,hudRowErrors,objectRowErrors,errors-hudRowErrors-objectRowErrors);
        if(transported){glDeleteTextures(1,&tf);glDeleteTextures(1,&tb);}
    }
    CGLSetCurrentContext(NULL); CGLDestroyContext(context); free(fragment);
    return totalErrors ? 1 : 0;
}
