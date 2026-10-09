package com.thorium.preview.game;

import android.opengl.*;
import java.nio.*;
import java.util.Arrays;
import java.io.*;
import java.util.HashMap;
import static android.opengl.GLES30.*;

/** app_process headless test. No Activity, window, wakelock or application data. */
public final class DenseMotionTransportDeviceTest {
    static String synthesisShaderPath, synthesisOutput;
    static boolean productionSynthesis;
    static String solverShaderPath,solverOutput;
    static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
    static int get(int key) { int[] v=new int[1];glGetIntegerv(key,v,0);return v[0]; }
    static int texture(boolean raw) {
        return texture(raw,64,32,false);
    }
    static int texture(boolean raw,int width,int height,boolean fragmented) {
        ByteBuffer data=ByteBuffer.allocateDirect(width*height*4);
        for(int i=0;i<width*height;i++) {
            // One Q8.8 unit change forbids exact merging, without adding large motion.
            int fraction=fragmented?((i%width+i/width)&1):0;
            data.put(raw?new byte[]{16,(byte)fraction,0,0}:new byte[]{(byte)218,(byte)128,(byte)204,(byte)255});
        }
        data.flip();int[] id=new int[1];glGenTextures(1,id,0);glBindTexture(GL_TEXTURE_2D,id[0]);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,width,height,0,GL_RGBA,GL_UNSIGNED_BYTE,data);return id[0];
    }
    public static void main(String[] args) throws Exception {
        boolean captureTest=args.length==1 && "gles2-capture".equals(args[0]);
        EGLDisplay display=EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        check(EGL14.eglInitialize(display,new int[2],0,new int[2],0),"EGL initialize");
        EGLConfig[] config=new EGLConfig[1];int[] count=new int[1];
        check(EGL14.eglChooseConfig(display,new int[]{EGL14.EGL_RENDERABLE_TYPE,captureTest?4:0x40,EGL14.EGL_SURFACE_TYPE,EGL14.EGL_PBUFFER_BIT,EGL14.EGL_NONE},0,config,0,1,count,0)&&count[0]>0,"EGL config");
        EGLContext context=EGL14.eglCreateContext(display,config[0],EGL14.EGL_NO_CONTEXT,new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION,captureTest?2:3,EGL14.EGL_NONE},0);
        EGLSurface surface=EGL14.eglCreatePbufferSurface(display,config[0],new int[]{EGL14.EGL_WIDTH,captureTest?1920:64,EGL14.EGL_HEIGHT,captureTest?1080:32,EGL14.EGL_NONE},0);
        check(EGL14.eglMakeCurrent(display,surface,surface,context),"EGL current");
        try {
            if(captureTest){FullResolutionCaptureDeviceTest.run();return;}
            System.out.println("renderer="+glGetString(GL_RENDERER)+" version="+glGetString(GL_VERSION));
            if(args.length==2 && "solver-guidance".equals(args[0])){DenseSolverSmoothingTest.guidance(args[1]);return;}
            if(args.length==2 && "solver-guidance-timing".equals(args[0])){DenseSolverSmoothingTest.guidanceTiming(args[1]);return;}
            if(args.length==4 && "production-synthesis".equals(args[0])) {
                productionSynthesis=true;synthesisShaderPath=args[2];synthesisOutput=args[3];replay(args[1]);return;
            }
            if(args.length==2 && "solver-smoothing".equals(args[0])){DenseSolverSmoothingTest.run(args[1]);return;}
            if(args.length==2 && "solver-timing".equals(args[0])){DenseSolverSmoothingTest.benchmark(args[1]);return;}
            if(args.length==4 && "solver-replay".equals(args[0])){solverShaderPath=args[2];solverOutput=args[3];replay(args[1]);return;}
            if(args.length==4 && "synthesis".equals(args[0])) {
                synthesisShaderPath=args[2];synthesisOutput=args[3];replay(args[1]);return;
            }
            if(args.length==2 && "replay".equals(args[0])){replay(args[1]);return;}
            if(Arrays.asList(args).contains("compare")){compare();return;}
            boolean fragmented=Arrays.asList(args).contains("fragmented");
            int valid=texture(false,fragmented?1920:64,fragmented?1080:32,false);
            int raw=texture(true,fragmented?1920:64,fragmented?1080:32,fragmented);
            System.out.println("fragmented="+fragmented);
            boolean compact=Arrays.asList(args).contains("compact");
            System.out.println("compact="+compact);
            if(args.length>0 && "benchmark".equals(args[0])) {
                benchmark(valid,raw,compact,Arrays.asList(args).contains("stages"));
                return;
            }
            glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,raw);
            glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,valid);
            glActiveTexture(GL_TEXTURE3);
            glViewport(3,4,17,19);glEnable(GL_SCISSOR_TEST);glScissor(1,1,1,1);
            glEnable(GL_BLEND);glDepthMask(false);glColorMask(false,true,false,true);
            DenseMotionTransportPass pass=new DenseMotionTransportPass(64,32,compact);
            int[] fb=new int[1];glGenFramebuffers(1,fb,0);
            for(float phase:new float[]{0,.03125f,.5f,1}) {
                int result=pass.render(0,valid,raw,64,32,phase,.25f,0,.5f,.5f);
                check(get(GL_ACTIVE_TEXTURE)==GL_TEXTURE3,"active unit restoration");
                int[] viewport=new int[4];glGetIntegerv(GL_VIEWPORT,viewport,0);
                check(Arrays.equals(viewport,new int[]{3,4,17,19}),"viewport restoration");
                check(glIsEnabled(GL_SCISSOR_TEST)&&glIsEnabled(GL_BLEND),"enable restoration");
                glActiveTexture(GL_TEXTURE0);check(get(GL_TEXTURE_BINDING_2D)==raw,"texture0 restoration");
                glActiveTexture(GL_TEXTURE1);check(get(GL_TEXTURE_BINDING_2D)==valid,"texture1 restoration");
                glActiveTexture(GL_TEXTURE3);
                glBindFramebuffer(GL_FRAMEBUFFER,fb[0]);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,result,0);
                FloatBuffer pixels=ByteBuffer.allocateDirect(64*32*16).order(ByteOrder.nativeOrder()).asFloatBuffer();
                glReadPixels(0,0,64,32,GL_RGBA,GL_FLOAT,pixels);
                check(glGetError()==GL_NO_ERROR,"GL error after render/readback");
                int errors=0;
                for(int y=0;y<32;y++)for(int x=0;x<64;x++) {
                    int i=(y*64+x)*4;boolean expected=x>phase*16-1,actual=pixels.get(i+2)>.5;
                    if(expected!=actual) errors++;
                    else if(actual){float v=(pixels.get(i)*255-128)/127;if(Math.abs(v*v*32-16)>.001)errors++;}
                }
                check(errors==0,"transport pixels phase="+phase+" errors="+errors);
                glBindFramebuffer(GL_FRAMEBUFFER,0);
                System.out.println("phase="+phase+" pixels/state PASS");
            }
            pass.close();pass.close();
            try { pass.render(0,valid,raw,64,32,.5f,0,0,.5f,.5f);throw new AssertionError("closed accepted"); }
            catch(IllegalStateException expected) { }
            System.out.println("HEADLESS_TRANSPORT_PASS");
        } finally {
            EGL14.eglMakeCurrent(display,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_SURFACE,EGL14.EGL_NO_CONTEXT);
            EGL14.eglDestroySurface(display,surface);EGL14.eglDestroyContext(display,context);EGL14.eglTerminate(display);
        }
    }

    static FloatBuffer readTarget(int texture,int width,int height,int framebuffer) {
        glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,texture,0);
        check(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"comparison framebuffer");
        FloatBuffer data=ByteBuffer.allocateDirect(width*height*16).order(ByteOrder.nativeOrder()).asFloatBuffer();
        glReadPixels(0,0,width,height,GL_RGBA,GL_FLOAT,data);
        check(glGetError()==GL_NO_ERROR,"comparison readback");return data;
    }

    /** Replay actual LFD1 fields. Equivalence is not an artifact-quality oracle.
     * Timing is transport-only synchronized wall time, not gameplay cadence. */
    static void replay(String path) throws IOException {
        HashMap<String,Integer> textures=new HashMap<>();
        int width,height;float limit,maxLimit;
        HashMap<String,int[]> sizes=new HashMap<>();
        try(DataInputStream in=new DataInputStream(new BufferedInputStream(new FileInputStream(path)))) {
            check(in.readInt()==0x4c464431,"LFD1 magic");
            limit=in.readFloat();maxLimit=in.readFloat();in.readInt();
            width=in.readInt();height=in.readInt();int count=in.readInt();
            check(width>0&&height>0&&width<=4096&&height<=4096&&(count==6||count==10),"LFD1 geometry");
            for(int i=0;i<count;i++) {
                int n=in.readInt();check(n>0&&n<=128,"plane name");
                byte[] name=new byte[n];in.readFully(name);
                String label=new String(name,java.nio.charset.StandardCharsets.US_ASCII);
                int w=in.readInt(),h=in.readInt();check(w>0&&h>0&&w<=4096&&h<=4096,"plane extent");
                byte[] bytes=new byte[w*h*4];in.readFully(bytes);
                ByteBuffer pixels=ByteBuffer.allocateDirect(bytes.length);pixels.put(bytes).flip();
                int[] id=new int[1];glGenTextures(1,id,0);glBindTexture(GL_TEXTURE_2D,id[0]);
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
                glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
                check(textures.put(label,id[0])==null,"duplicate plane");
                sizes.put(label,new int[]{w,h});
            }
            check(in.read()==-1,"trailing LFD1 bytes");
        }
        if(solverShaderPath!=null) {
            try {DenseSolverReplay.run(textures,sizes,width,height,maxLimit,solverShaderPath,solverOutput);}
            finally {for(int texture:textures.values())glDeleteTextures(1,new int[]{texture},0);}
            return;
        }
        if(synthesisShaderPath!=null) {
            try {DenseMotionRealSynthesis.run(textures,width,height,limit,synthesisShaderPath,synthesisOutput,productionSynthesis);}
            finally {for(int texture:textures.values())glDeleteTextures(1,new int[]{texture},0);}
            return;
        }
        int[] fb=new int[1];glGenFramebuffers(1,fb,0);
        long totalErrors=0;
        try(DenseMotionTransportPass reference=new DenseMotionTransportPass(width,height);
            DenseMotionTransportPass compact=new DenseMotionTransportPass(width,height,true)) {
            for(int direction=0;direction<2;direction++) {
                int valid=textures.get("validated"+direction),raw=textures.get("final"+direction);
                for(float phase:new float[]{0,.03125f,.46875f,.5f,.53125f,.96875f,1}) {
                    FloatBuffer a=readTarget(reference.render(direction,valid,raw,width,height,phase,0,0,limit/width,limit/height),width,height,fb[0]);
                    FloatBuffer b=readTarget(compact.render(direction,valid,raw,width,height,phase,0,0,limit/width,limit/height),width,height,fb[0]);
                    int errors=0;float max=0;
                    for(int i=0;i<width*height*4;i++) {
                        float delta=Math.abs(a.get(i)-b.get(i));
                        if(!Float.isFinite(a.get(i))||!Float.isFinite(b.get(i))||delta>1e-6f)errors++;
                        max=Math.max(max,delta);
                    }
                    totalErrors+=errors;
                    System.out.println("REPLAY_COMPARE direction="+direction+" phase="+phase+" channelsDifferent="+errors+" maxDelta="+max);
                }
            }
            glBindFramebuffer(GL_FRAMEBUFFER,0);
            for(int mode=0;mode<2;mode++) {
                DenseMotionTransportPass pass=mode==0?reference:compact;
                long[] times=new long[12];
                for(int sample=-3;sample<12;sample++) {
                    glFinish();long start=System.nanoTime();
                    for(int direction=0;direction<2;direction++)
                        pass.render(direction,textures.get("validated"+direction),textures.get("final"+direction),width,height,.5f,0,0,limit/width,limit/height);
                    glFinish();long elapsed=System.nanoTime()-start;
                    check(glGetError()==GL_NO_ERROR,"replay GL error");
                    if(sample>=0)times[sample]=elapsed;
                }
                Arrays.sort(times);
                System.out.println("REPLAY_TIMING compact="+(mode==1)+" size="+width+"x"+height+" median_ns="+times[6]+" max_ns="+times[11]+" excludes_flow_synthesis_present=true");
            }
        } finally {
            glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,fb,0);
            for(int texture:textures.values())glDeleteTextures(1,new int[]{texture},0);
        }
        check(totalErrors==0,"real-field transport equivalence failed channels="+totalErrors);
        System.out.println("REPLAY_EQUIVALENCE_PASS "+path);
    }

    /** Nonuniform motion and confidence cross tile interiors, including partial
     * workgroups. Reference is original transport, not an independent image oracle. */
    static void compare() {
        for(int[] extent:new int[][]{{64,32},{63,31},{9,7},{1,1}}) {
            int width=extent[0],height=extent[1];
            int[] textures=new int[2],fb=new int[1];glGenTextures(2,textures,0);glGenFramebuffers(1,fb,0);
            for(int input=0;input<2;input++) {
                ByteBuffer data=ByteBuffer.allocateDirect(width*height*4);
                for(int y=0;y<height;y++)for(int x=0;x<width;x++) {
                    int motion=(x>=13 && x<30 && y>=5 && y<23)?16:4;
                    if(input==1)data.put(new byte[]{(byte)motion,0,0,0});
                    else data.put(new byte[]{(byte)180,(byte)128,(byte)((x>=31 && x<34)?0:204),(byte)255});
                }
                data.flip();glBindTexture(GL_TEXTURE_2D,textures[input]);
                glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
                glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,width,height,0,GL_RGBA,GL_UNSIGNED_BYTE,data);
            }
            try(DenseMotionTransportPass reference=new DenseMotionTransportPass(width,height);
                DenseMotionTransportPass compact=new DenseMotionTransportPass(width,height,true)) {
                for(float phase:new float[]{0,.03125f,.46875f,.5f,.53125f,.96875f,1}) {
                    FloatBuffer a=readTarget(reference.render(0,textures[0],textures[1],width,height,phase,4f/width,0,32f/width,32f/height),width,height,fb[0]);
                    FloatBuffer b=readTarget(compact.render(0,textures[0],textures[1],width,height,phase,4f/width,0,32f/width,32f/height),width,height,fb[0]);
                    int errors=0;for(int i=0;i<width*height*4;i++)if(!Float.isFinite(b.get(i)) || Math.abs(a.get(i)-b.get(i))>0.000001f)errors++;
                    check(errors==0,"compact/reference mismatch "+width+"x"+height+" phase="+phase+" channels="+errors);
                }
            } finally {glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,fb,0);glDeleteTextures(2,textures,0);}
            System.out.println("COMPACT_REFERENCE_PASS "+width+"x"+height+" phases=7");
        }
    }

    /** Synchronous wall timing includes Java/driver submission and GPU finish;
     * excludes source solving, synthesis, presentation and shader warmup.
     */
    static void benchmark(int valid,int raw,boolean compact,boolean stages) {
        DenseMotionTransportPass pass=new DenseMotionTransportPass(1920,1080,compact);
        if(stages)pass.enableDiagnosticTiming();
        try {
            long[] samples=new long[12];
            for(int i=-3;i<samples.length;i++) {
                glFinish();long start=System.nanoTime();
                pass.render(0,valid,raw,1920,1080,.5f,16f/1920,0,128f/1920,128f/1080);
                long[] first=stages?pass.diagnosticTimes():null;
                pass.render(1,valid,raw,1920,1080,.5f,16f/1920,0,128f/1920,128f/1080);
                glFinish();long elapsed=System.nanoTime()-start;
                check(glGetError()==GL_NO_ERROR,"benchmark GL error");
                if(i>=0){samples[i]=elapsed;System.out.println("transport_pair_ns="+elapsed);}
                if(i>=0 && stages){long[] second=pass.diagnosticTimes();System.out.println("synchronized_stage_compute_ns="+(first[0]+second[0])+" draw_ns="+(first[1]+second[1])+" instrumented=true");}
            }
            Arrays.sort(samples);
            System.out.println("TRANSPORT_1080P_PAIR median_ns="+samples[6]+" max_ns="+samples[11]
                    +" budget_120hz_ns=8333333 excludes_flow_synthesis_present=true");
        } finally { pass.close(); }
    }
}
