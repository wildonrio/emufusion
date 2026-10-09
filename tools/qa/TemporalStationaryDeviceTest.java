package com.thorium.preview.game;

import android.opengl.*;
import java.nio.*;
import java.nio.file.*;
import static android.opengl.GLES20.*;

/** Headless candidate only. No activity, window, or wakelock. */
public final class TemporalStationaryDeviceTest {
    static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
    static int shader(int type,String text){
        int s=glCreateShader(type);glShaderSource(s,text);glCompileShader(s);
        int[] ok=new int[1];glGetShaderiv(s,GL_COMPILE_STATUS,ok,0);
        check(ok[0]!=0,glGetShaderInfoLog(s));return s;
    }
    public static void main(String[] args)throws Exception {
        Path dir=Paths.get(args[0]);int w=Integer.parseInt(args[1]),h=Integer.parseInt(args[2]);
        EGLDisplay d=EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        check(EGL14.eglInitialize(d,new int[2],0,new int[2],0),"initialize");
        EGLConfig[] configs=new EGLConfig[1];int[] count=new int[1];
        check(EGL14.eglChooseConfig(d,new int[]{EGL14.EGL_RENDERABLE_TYPE,4,
            EGL14.EGL_SURFACE_TYPE,EGL14.EGL_PBUFFER_BIT,EGL14.EGL_NONE},0,configs,0,1,count,0)&&count[0]>0,"config");
        EGLContext c=EGL14.eglCreateContext(d,configs[0],EGL14.EGL_NO_CONTEXT,
            new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,2,EGL14.EGL_NONE},0);
        EGLSurface surface=EGL14.eglCreatePbufferSurface(d,configs[0],
            new int[]{EGL14.EGL_WIDTH,w,EGL14.EGL_HEIGHT,h,EGL14.EGL_NONE},0);
        check(EGL14.eglMakeCurrent(d,surface,surface,c),"current");
        try {
            int program=glCreateProgram();
            glAttachShader(program,shader(GL_VERTEX_SHADER,"attribute vec2 p;varying vec2 vTexCoord;void main(){vTexCoord=p*.5+.5;gl_Position=vec4(p,0.,1.);}"));
            glAttachShader(program,shader(GL_FRAGMENT_SHADER,new String(Files.readAllBytes(dir.resolve("guard.glsl")),"UTF-8")));
            glBindAttribLocation(program,0,"p");glLinkProgram(program);int[] ok=new int[1];glGetProgramiv(program,GL_LINK_STATUS,ok,0);check(ok[0]!=0,glGetProgramInfoLog(program));
            glUseProgram(program);
            String[] names={"left","right","following","generated"};
            String[] uniforms={"uLeft","uRight","uFollowing","uGenerated"};
            for(int i=0;i<4;i++) {
                byte[] raw=Files.readAllBytes(dir.resolve(names[i]+".rgba"));check(raw.length==w*h*4,"input size");
                ByteBuffer pixels=ByteBuffer.allocateDirect(raw.length);pixels.put(raw).flip();
                glActiveTexture(GL_TEXTURE0+i);int texture=DensePyramidDeviceTest.texture(w,h,pixels);
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
                glUniform1i(glGetUniformLocation(program,uniforms[i]),i);
            }
            glActiveTexture(GL_TEXTURE0+4);int out=DensePyramidDeviceTest.texture(w,h,null);
            int[] fb=new int[1];glGenFramebuffers(1,fb,0);glBindFramebuffer(GL_FRAMEBUFFER,fb[0]);
            glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,out,0);
            check(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"framebuffer");
            FloatBuffer quad=ByteBuffer.allocateDirect(32).order(ByteOrder.nativeOrder()).asFloatBuffer();
            quad.put(new float[]{-1,-1,1,-1,-1,1,1,1}).flip();int attr=glGetAttribLocation(program,"p");
            glEnableVertexAttribArray(attr);glVertexAttribPointer(attr,2,GL_FLOAT,false,0,quad);
            int scale=args.length>3?Integer.parseInt(args[3]):1;
            check(scale>0,"native sample scale");
            glUniform2f(glGetUniformLocation(program,"uTexel"),(float)scale/w,(float)scale/h);
            glViewport(0,0,w,h);glDisable(GL_DITHER);glDisable(GL_BLEND);
            for(int enabled=0;enabled<=1;enabled++) {
                glUniform1i(glGetUniformLocation(program,"uHasFollowing"),enabled);
                glDrawArrays(GL_TRIANGLE_STRIP,0,4);glFinish();
                ByteBuffer pixels=ByteBuffer.allocateDirect(w*h*4);glReadPixels(0,0,w,h,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
                byte[] raw=new byte[w*h*4];pixels.get(raw);Files.write(dir.resolve("output-"+enabled+".rgba"),raw);
            }
            long start=System.nanoTime();
            for(int i=0;i<100;i++){glDrawArrays(GL_TRIANGLE_STRIP,0,4);glFinish();}
            check(glGetError()==GL_NO_ERROR,"GL error");
            System.out.println("GUARD_DRAW_FINISH_MEAN_NS="+(System.nanoTime()-start)/100);
            // Two-pass candidate: native-resolution agreement, then full output.
            int composite=glCreateProgram();
            glAttachShader(composite,shader(GL_VERTEX_SHADER,"attribute vec2 p;varying vec2 vTexCoord;void main(){vTexCoord=p*.5+.5;gl_Position=vec4(p,0.,1.);}"));
            glAttachShader(composite,shader(GL_FRAGMENT_SHADER,new String(Files.readAllBytes(dir.resolve("composite.glsl")),"UTF-8")));
            glBindAttribLocation(composite,0,"p");glLinkProgram(composite);
            glGetProgramiv(composite,GL_LINK_STATUS,ok,0);check(ok[0]!=0,glGetProgramInfoLog(composite));
            glUseProgram(composite);
            glUniform1i(glGetUniformLocation(composite,"uLeft"),0);
            glUniform1i(glGetUniformLocation(composite,"uGenerated"),3);
            glUniform1i(glGetUniformLocation(composite,"uMask"),5);
            glActiveTexture(GL_TEXTURE0+5);int mask=DensePyramidDeviceTest.texture(w/scale,h/scale,null);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
            for(int enabled=0;enabled<=1;enabled++) {
                glUseProgram(program);glUniform1i(glGetUniformLocation(program,"uHasFollowing"),enabled);
                twoPass(program,composite,mask,out,w,h,scale);glFinish();
                ByteBuffer pixels=ByteBuffer.allocateDirect(w*h*4);glReadPixels(0,0,w,h,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
                byte[] raw=new byte[w*h*4];pixels.get(raw);Files.write(dir.resolve("split-"+enabled+".rgba"),raw);
            }
            start=System.nanoTime();
            for(int i=0;i<100;i++){twoPass(program,composite,mask,out,w,h,scale);glFinish();}
            System.out.println("SPLIT_DRAW_FINISH_MEAN_NS="+(System.nanoTime()-start)/100);
            check(glGetError()==GL_NO_ERROR,"split GL error");
            System.out.println("GPU="+glGetString(GL_RENDERER));
        } finally {
            EGL14.eglMakeCurrent(d,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);
            EGL14.eglDestroySurface(d,surface);EGL14.eglDestroyContext(d,c);EGL14.eglTerminate(d);
        }
    }
    static void twoPass(int program,int composite,int mask,int out,int w,int h,int scale) {
        glUseProgram(program);glUniform1i(glGetUniformLocation(program,"uMaskOnly"),1);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,mask,0);
        glViewport(0,0,w/scale,h/scale);glDrawArrays(GL_TRIANGLE_STRIP,0,4);
        glUseProgram(composite);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,out,0);
        glViewport(0,0,w,h);glDrawArrays(GL_TRIANGLE_STRIP,0,4);
    }
}
