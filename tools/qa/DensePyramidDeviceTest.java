package com.thorium.preview.game;

import android.opengl.*;
import java.nio.*;
import java.nio.file.*;
import static android.opengl.GLES20.*;

/** Isolated actual pyramid shader test. No window, activity or wakelock. */
public final class DensePyramidDeviceTest {
    static int program,fb;
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static int shader(int type,String source){
        int s=glCreateShader(type);glShaderSource(s,source);glCompileShader(s);
        int[] ok=new int[1];glGetShaderiv(s,GL_COMPILE_STATUS,ok,0);
        check(ok[0]!=0,glGetShaderInfoLog(s));return s;
    }
    static int texture(int w,int h,ByteBuffer pixels){
        int[] id=new int[1];glGenTextures(1,id,0);glBindTexture(GL_TEXTURE_2D,id[0]);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
        return id[0];
    }
    static int draw(int source,int sw,int sh,int w,int h,float tap){
        int out=texture(w,h,null);
        glBindFramebuffer(GL_FRAMEBUFFER,fb);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,out,0);
        check(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"framebuffer");
        glUseProgram(program);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,source);
        glUniform1i(glGetUniformLocation(program,"uTexture"),0);
        glUniform2f(glGetUniformLocation(program,"uInputTexel"),1f/sw,1f/sh);
        glUniform1f(glGetUniformLocation(program,"uTapScale"),tap);
        glViewport(0,0,w,h);glDrawArrays(GL_TRIANGLE_STRIP,0,4);
        check(glGetError()==GL_NO_ERROR,"draw");return out;
    }
    static double[] measure(){
        ByteBuffer b=ByteBuffer.allocateDirect(96*72*4);
        glReadPixels(0,0,96,72,GL_RGBA,GL_UNSIGNED_BYTE,b);
        double sum=0,square=0,error=0;int count=0;
        // Exclude clamp boundaries. Analytical samples are known input sine,
        // not a hidden game frame or an assertion of interpolation accuracy.
        for(int y=2;y<70;y++)for(int x=2;x<94;x++){
            double v=b.get((y*96+x)*4)&255;
            double expected=128+80*Math.sin(2*Math.PI*((x+.5)*256/96)/8);
            sum+=v;square+=v*v;error+=Math.abs(v-expected);count++;
        }
        return new double[]{Math.sqrt(square/count-Math.pow(sum/count,2)),error/count};
    }
    public static void main(String[] args)throws Exception{
        EGLDisplay d=EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        check(EGL14.eglInitialize(d,new int[2],0,new int[2],0),"initialize");
        EGLConfig[] configs=new EGLConfig[1];int[] count=new int[1];
        check(EGL14.eglChooseConfig(d,new int[]{EGL14.EGL_RENDERABLE_TYPE,4,
            EGL14.EGL_SURFACE_TYPE,EGL14.EGL_PBUFFER_BIT,EGL14.EGL_NONE},0,configs,0,1,count,0)&&count[0]>0,"config");
        EGLContext c=EGL14.eglCreateContext(d,configs[0],EGL14.EGL_NO_CONTEXT,
            new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,2,EGL14.EGL_NONE},0);
        EGLSurface s=EGL14.eglCreatePbufferSurface(d,configs[0],
            new int[]{EGL14.EGL_WIDTH,96,EGL14.EGL_HEIGHT,72,EGL14.EGL_NONE},0);
        check(EGL14.eglMakeCurrent(d,s,s,c),"current");
        try{
            System.out.println("GPU="+glGetString(GL_RENDERER)+" context="+glGetString(GL_VERSION));
            String fragment=new String(Files.readAllBytes(Paths.get(args[0])),"UTF-8");
            program=glCreateProgram();
            glAttachShader(program,shader(GL_VERTEX_SHADER,"attribute vec2 p;varying vec2 vTexCoord;void main(){vTexCoord=p*.5+.5;gl_Position=vec4(p,0.,1.);}"));
            glAttachShader(program,shader(GL_FRAGMENT_SHADER,fragment));glLinkProgram(program);
            int[] ok=new int[1];glGetProgramiv(program,GL_LINK_STATUS,ok,0);check(ok[0]!=0,glGetProgramInfoLog(program));
            FloatBuffer quad=ByteBuffer.allocateDirect(32).order(ByteOrder.nativeOrder()).asFloatBuffer();
            quad.put(new float[]{-1,-1,1,-1,-1,1,1,1}).flip();
            int attr=glGetAttribLocation(program,"p");glEnableVertexAttribArray(attr);glVertexAttribPointer(attr,2,GL_FLOAT,false,0,quad);
            int[] f=new int[1];glGenFramebuffers(1,f,0);fb=f[0];glDisable(GL_DITHER);glDisable(GL_BLEND);
            ByteBuffer pixels=ByteBuffer.allocateDirect(256*192*4);
            for(int y=0;y<192;y++)for(int x=0;x<256;x++){
                byte v=(byte)Math.round(128+80*Math.sin(2*Math.PI*(x+.5)/8));pixels.put(v).put(v).put(v).put((byte)255);
            }
            pixels.flip();int source=texture(256,192,pixels);
            int box=draw(source,256,192,64,48,1);
            int tiny=draw(box,64,48,16,12,1);
            draw(tiny,16,12,96,72,.5f);double[] old=measure();
            draw(source,256,192,96,72,.5f);double[] fixed=measure();
            System.out.println("PYRAMID_DETAIL old_std="+old[0]+" fixed_std="+fixed[0]+" old_mae="+old[1]+" fixed_mae="+fixed[1]);
            check(old[0]<1 && fixed[0]>30 && fixed[1]<old[1],"detail preservation");
            System.out.println("PASS shader-only spatial-detail fixture; not full motion or timing acceptance");
        }finally{
            EGL14.eglMakeCurrent(d,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);
            EGL14.eglDestroySurface(d,s);EGL14.eglDestroyContext(d,c);EGL14.eglTerminate(d);
        }
    }
}
