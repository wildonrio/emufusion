package com.emufusion.rifebenchmark;

import android.media.Image;
import android.media.ImageReader;
import android.opengl.*;
import java.nio.*;

/** Offscreen GPU producer for exact, bottom-up RGBA endpoint fixtures. */
final class NativeRifeGpuInputs implements AutoCloseable {
    private final EGLDisplay display;
    private final EGLContext context;
    private final EGLSurface surface;
    private final int program, texture;
    private final FloatBuffer vertices;
    private final int width, height;

    NativeRifeGpuInputs(ImageReader reader) {
        width=reader.getWidth(); height=reader.getHeight();
        display=EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        check(EGL14.eglInitialize(display,new int[2],0,new int[2],0),"initialize");
        EGLConfig[] configs=new EGLConfig[1];
        int[] count=new int[1];
        check(EGL14.eglChooseConfig(display,new int[]{EGL14.EGL_SURFACE_TYPE,EGL14.EGL_WINDOW_BIT,
            EGL14.EGL_RENDERABLE_TYPE,EGL14.EGL_OPENGL_ES2_BIT,EGL14.EGL_RED_SIZE,8,
            EGL14.EGL_GREEN_SIZE,8,EGL14.EGL_BLUE_SIZE,8,EGL14.EGL_ALPHA_SIZE,8,EGL14.EGL_NONE},
            0,configs,0,1,count,0) && count[0]==1,"config");
        context=EGL14.eglCreateContext(display,configs[0],EGL14.EGL_NO_CONTEXT,
            new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,2,EGL14.EGL_NONE},0);
        surface=EGL14.eglCreateWindowSurface(display,configs[0],reader.getSurface(),
            new int[]{EGL14.EGL_NONE},0);
        check(EGL14.eglMakeCurrent(display,surface,surface,context),"make current");
        int vs=shader(GLES20.GL_VERTEX_SHADER,"attribute vec2 p; varying vec2 uv; void main(){gl_Position=vec4(p,0.,1.);uv=p*.5+.5;}");
        int fs=shader(GLES20.GL_FRAGMENT_SHADER,"precision highp float; varying vec2 uv; uniform sampler2D image; void main(){gl_FragColor=texture2D(image,uv);}");
        program=GLES20.glCreateProgram(); GLES20.glAttachShader(program,vs); GLES20.glAttachShader(program,fs);
        GLES20.glLinkProgram(program); int[] status=new int[1];
        GLES20.glGetProgramiv(program,GLES20.GL_LINK_STATUS,status,0);
        check(status[0]!=0,"link "+GLES20.glGetProgramInfoLog(program));
        GLES20.glDeleteShader(vs); GLES20.glDeleteShader(fs);
        int[] textures=new int[1]; GLES20.glGenTextures(1,textures,0); texture=textures[0];
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D,texture);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,GLES20.GL_TEXTURE_MIN_FILTER,GLES20.GL_NEAREST);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,GLES20.GL_TEXTURE_MAG_FILTER,GLES20.GL_NEAREST);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,GLES20.GL_TEXTURE_WRAP_S,GLES20.GL_CLAMP_TO_EDGE);
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D,GLES20.GL_TEXTURE_WRAP_T,GLES20.GL_CLAMP_TO_EDGE);
        vertices=ByteBuffer.allocateDirect(32).order(ByteOrder.nativeOrder()).asFloatBuffer();
        vertices.put(new float[]{-1,-1,1,-1,-1,1,1,1}).position(0);
    }
    private static void check(boolean value,String label) {
        if(!value) throw new IllegalStateException("GPU fixture "+label);
    }
    private static int shader(int type,String source) {
        int shader=GLES20.glCreateShader(type); GLES20.glShaderSource(shader,source); GLES20.glCompileShader(shader);
        int[] status=new int[1]; GLES20.glGetShaderiv(shader,GLES20.GL_COMPILE_STATUS,status,0);
        check(status[0]!=0,GLES20.glGetShaderInfoLog(shader)); return shader;
    }
    Image upload(ImageReader reader,byte[] rgba,long timestamp) throws Exception {
        return upload(reader,rgba,timestamp,true);
    }
    Image upload(ImageReader reader,byte[] rgba,long timestamp,boolean verifyPixels) throws Exception {
        return upload(reader,rgba,timestamp,verifyPixels,true);
    }
    Image upload(ImageReader reader,byte[] rgba,long timestamp,boolean verifyPixels,boolean waitFence) throws Exception {
        return upload(reader,rgba,timestamp,verifyPixels,waitFence,false);
    }
    Image upload(ImageReader reader,byte[] rgba,long timestamp,boolean verifyPixels,boolean waitFence,boolean deferAcquire) throws Exception {
        long begin=System.nanoTime();
        check(rgba.length==width*height*4,"input size");
        ByteBuffer pixels=ByteBuffer.allocateDirect(rgba.length); pixels.put(rgba).rewind();
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D,texture);
        GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D,0,GLES20.GL_RGBA,width,height,0,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,pixels);
        GLES20.glViewport(0,0,width,height); GLES20.glDisable(GLES20.GL_DITHER); GLES20.glDisable(GLES20.GL_BLEND);
        GLES20.glUseProgram(program); int position=GLES20.glGetAttribLocation(program,"p");
        GLES20.glEnableVertexAttribArray(position);
        GLES20.glVertexAttribPointer(position,2,GLES20.GL_FLOAT,false,0,vertices);
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP,0,4);
        // Fixture-only verification, before timed inference; independent of producer fence.
        if(verifyPixels) {
            ByteBuffer checkPixels=ByteBuffer.allocateDirect(rgba.length);
            GLES20.glReadPixels(0,0,width,height,GLES20.GL_RGBA,GLES20.GL_UNSIGNED_BYTE,checkPixels);
            for(int i=0;i<rgba.length;i++) check(checkPixels.get(i)==rgba[i],"render byte "+i);
        }
        check(GLES20.glGetError()==GLES20.GL_NO_ERROR,"GL error");
        long drawn=System.nanoTime();
        check(EGLExt.eglPresentationTimeANDROID(display,surface,timestamp),"timestamp");
        check(EGL14.eglSwapBuffers(display,surface),"swap");
        long swapped=System.nanoTime();
        if(deferAcquire) {
            // Keep producer costs observable even when acquisition is deferred.
            System.out.println("QUEUED_UPLOAD_PHASES,"+timestamp+","+(drawn-begin)+","+(swapped-drawn));
            return null;
        }
        long deadline=System.nanoTime()+2_000_000_000L;
        Image image;
        while((image=reader.acquireNextImage())==null && System.nanoTime()<deadline) Thread.sleep(1);
        check(image!=null && image.getTimestamp()==timestamp,"acquired identity");
        long acquired=System.nanoTime();
        try(android.hardware.SyncFence fence=image.getFence()) {
            check(fence.isValid(),"producer fence validity");
            if(waitFence) check(fence.await(java.time.Duration.ofSeconds(2)),"producer fence");
        }
        System.out.println((verifyPixels ? "GPU_INPUT_EXACT" : "GPU_INPUT_UPLOADED")+" bytes="+rgba.length+" timestamp="+timestamp);
        System.out.println("UPLOAD_PHASES,"+timestamp+","+(drawn-begin)+","+(swapped-drawn)+","+(acquired-swapped)+","+(System.nanoTime()-acquired));
        return image;
    }
    public void close() {
        GLES20.glDeleteTextures(1,new int[]{texture},0); GLES20.glDeleteProgram(program);
        EGL14.eglMakeCurrent(display,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);
        EGL14.eglDestroySurface(display,surface); EGL14.eglDestroyContext(display,context); EGL14.eglTerminate(display);
    }
}
