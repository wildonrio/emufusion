package com.thorium.preview.game;

import java.nio.*;
import java.nio.file.*;
import static android.opengl.GLES30.*;

/** Actual runtime solver shader ablation, not full gameplay qualification. */
final class DenseSolverSmoothingTest {
    static int W=32,H=24;
    static boolean timing;
    static boolean reciprocalTest;
    static int texture(byte[] pixels, boolean linear) {
        int[] t=new int[1];glGenTextures(1,t,0);glBindTexture(GL_TEXTURE_2D,t[0]);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,linear?GL_LINEAR:GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,linear?GL_LINEAR:GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        ByteBuffer b=ByteBuffer.allocateDirect(pixels.length);b.put(pixels).flip();
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,W,H,0,GL_RGBA,GL_UNSIGNED_BYTE,b);return t[0];
    }
    static float render(String source,float consensus) {
        String fragment="#version 300 es\n"+source.replace("varying vec2 vTexCoord;","in vec2 vTexCoord;out vec4 resultColor;")
            .replace("texture2D(","texture(").replace("gl_FragColor","resultColor")
            .replaceAll("\\bsmooth\\b","neighborSmooth"); // reserved interpolation keyword in ES3
        int vs=DenseMotionRealSynthesis.shader(GL_VERTEX_SHADER,"#version 300 es\nout vec2 vTexCoord;void main(){vec2 q=vec2(float(gl_VertexID&1),float((gl_VertexID>>1)&1));vTexCoord=q;gl_Position=vec4(q*2.-1.,0.,1.);}");
        int fs=DenseMotionRealSynthesis.shader(GL_FRAGMENT_SHADER,fragment),p=glCreateProgram();
        glAttachShader(p,vs);glAttachShader(p,fs);glLinkProgram(p);
        int[] ok=new int[1];glGetProgramiv(p,GL_LINK_STATUS,ok,0);
        if(ok[0]==0)throw new AssertionError(glGetProgramInfoLog(p));
        byte[] target=new byte[W*H*4],reference=new byte[W*H*4],prior=new byte[W*H*4];
        java.util.Random random=new java.util.Random(27);
        for(int i=0;i<W*H;i++){byte v=(byte)(100+random.nextInt(20));for(int c=0;c<3;c++)target[i*4+c]=v;target[i*4+3]=(byte)255;}
        for(int y=0;y<H;y++)for(int x=0;x<W;x++)System.arraycopy(target,(y*W+Math.max(0,x-4))*4,reference,(y*W+x)*4,4);
        prior[(12*W+12)*4]=4; // Exact center match surrounded by wrong zero proposals.
        if(reciprocalTest)java.util.Arrays.fill(prior,(byte)0);
        int a=texture(reference,true),b=texture(target,true),c=texture(prior,false),out=texture(new byte[W*H*4],false);
        int reciprocal=0;
        if(reciprocalTest){
            byte[] reverse=new byte[W*H*4];
            for(int i=0;i<W*H;i++)reverse[i*4]=(byte)252; // Q8.8 -4px
            reciprocal=texture(reverse,false);
        }
        int[] fb=new int[1],vao=new int[1];glGenFramebuffers(1,fb,0);glBindFramebuffer(GL_FRAMEBUFFER,fb[0]);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,out,0);
        if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)throw new AssertionError("solver framebuffer");
        glGenVertexArrays(1,vao,0);glBindVertexArray(vao[0]);glUseProgram(p);
        DenseMotionRealSynthesis.bind(p,"uReference",0,a);DenseMotionRealSynthesis.bind(p,"uTarget",1,b);
        for(String name:new String[]{"uPriorFlow","uReciprocalFlow","uTemporalFlow","uGlobalSeed"})DenseMotionRealSynthesis.bind(p,name,2,c);
        for(String name:new String[]{"uAnalysisTexel","uPriorTexel","uReciprocalTexel"})DenseMotionRealSynthesis.vector(p,name,1f/W,1f/H);
        DenseMotionRealSynthesis.vector(p,"uSourceSize",W,H);
        DenseMotionRealSynthesis.scalar(p,"uHasPrior",1);DenseMotionRealSynthesis.scalar(p,"uFinalConsensus",consensus);
        if(reciprocalTest){
            DenseMotionRealSynthesis.bind(p,"uReciprocalFlow",3,reciprocal);
            DenseMotionRealSynthesis.scalar(p,"uUseReciprocalGuide",1);
            DenseMotionRealSynthesis.scalar(p,"uReciprocalMargin",.002f);
            DenseMotionRealSynthesis.scalar(p,"uTemporalLimit",47);
            DenseMotionRealSynthesis.scalar(p,"uBypassSearch",1);
        }
        if(timing)DenseMotionRealSynthesis.vector(p,"uUpdateStep",reciprocalTest?1f:.25f,reciprocalTest?1f:.25f);
        glViewport(0,0,W,H);glDisable(GL_BLEND);glDisable(GL_DEPTH_TEST);glDisable(GL_DITHER);
        glDrawArrays(GL_TRIANGLE_STRIP,0,4);
        if(timing) {
            long[] samples=new long[20];
            for(int i=-5;i<samples.length;i++) {
                glFinish();long start=System.nanoTime();
                glDrawArrays(GL_TRIANGLE_STRIP,0,4);glFinish();
                if(i>=0)samples[i]=System.nanoTime()-start;
            }
            java.util.Arrays.sort(samples);
            System.out.println("SOLVER_TIMING size="+W+"x"+H+" guarded="+source.contains("vec2 proposed=")+" consensus="+consensus+
                " reciprocal_test="+reciprocalTest+" guidance_fix="+source.contains("uUseTemporalGuide<.5&&uUseReciprocalGuide<.5")+
                " median_us="+(samples[10]/1000.0)+" p95_us="+(samples[18]/1000.0)+" max_us="+(samples[19]/1000.0)+" synchronized_wall=true");
        }
        ByteBuffer pixel=ByteBuffer.allocateDirect(4);glReadPixels(12,12,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel);
        if(glGetError()!=GL_NO_ERROR)throw new AssertionError("solver GL error");
        int q=(pixel.get(0)&255)*256+(pixel.get(1)&255);if(q>=32768)q-=65536;
        glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,fb,0);glDeleteVertexArrays(1,vao,0);
        glDeleteTextures(4,new int[]{a,b,c,out},0);
        if(reciprocal!=0)glDeleteTextures(1,new int[]{reciprocal},0);
        glDeleteProgram(p);glDeleteShader(vs);glDeleteShader(fs);return q/256f;
    }
    static void guidance(String path) throws Exception {
        String base=new String(Files.readAllBytes(Paths.get(path)),java.nio.charset.StandardCharsets.UTF_8);
        String old="uBypassSearch>.5&&uUseTemporalGuide<.5";
        String fixed=old+"&&uUseReciprocalGuide<.5&&uUseGlobalSeed<.5&&uUseNeighborProposal<.5";
        if(base.contains(fixed))base=base.replace(fixed,old);
        if(!base.contains(old))throw new AssertionError("bypass contract missing");
        reciprocalTest=true;
        try {
            float before=render(base,0),after=render(base.replace(old,fixed),0);
            System.out.println("SOLVER_GUIDANCE expected=4 bypassed="+before+" evaluated="+after);
            if(before!=0 || after!=4)throw new AssertionError("reciprocal bypass regression");
        } finally {reciprocalTest=false;}
    }
    static void guidanceTiming(String path) throws Exception {
        guidance(path);
        String base=new String(Files.readAllBytes(Paths.get(path)),java.nio.charset.StandardCharsets.UTF_8);
        String old="uBypassSearch>.5&&uUseTemporalGuide<.5";
        String fixed=old+"&&uUseReciprocalGuide<.5&&uUseGlobalSeed<.5&&uUseNeighborProposal<.5";
        if(base.contains(fixed))base=base.replace(fixed,old);
        timing=true;reciprocalTest=true;
        try {
            for(int[] size:new int[][]{{128,72},{192,144},{256,192}}){
                W=size[0];H=size[1];render(base,0);render(base.replace(old,fixed),0);
            }
        } finally {timing=false;reciprocalTest=false;W=32;H=24;}
    }
    static void run(String path) throws Exception {
        String base=new String(Files.readAllBytes(Paths.get(path)),java.nio.charset.StandardCharsets.UTF_8);
        String old="b=mix(b,smooth,w);gl_FragColor=enc(b);";
        String guard="vec2 proposed=floor(mix(b,smooth,w)*256.0+.5)/256.0;if(objective(proposed)+.000001<objective(b))b=proposed;gl_FragColor=enc(b);";
        // Accept current production source too, reconstructing only the prior
        // unconditional assignment for the negative control.
        if(base.contains(guard))base=base.replace(guard,old);
        if(!base.contains(old))throw new AssertionError("smoothing token missing");
        for(float consensus:new float[]{0,1}) {
            float before=render(base,consensus),after=render(base.replace(old,guard),consensus);
            System.out.println("SOLVER_SMOOTHING consensus="+consensus+" expected=4 baseline="+before+" guarded="+after);
            if(Math.abs(before-4)<.1||after!=4)throw new AssertionError("smoothing regression");
        }
    }
    static void benchmark(String path) throws Exception {
        run(path); // Require the known-defect regression before timing.
        String current=new String(Files.readAllBytes(Paths.get(path)),java.nio.charset.StandardCharsets.UTF_8);
        String guard="vec2 proposed=floor(mix(b,smooth,w)*256.0+.5)/256.0;if(objective(proposed)+.000001<objective(b))b=proposed;gl_FragColor=enc(b);";
        if(!current.contains(guard))throw new AssertionError("current guarded source required");
        String baseline=current.replace(guard,"b=mix(b,smooth,w);gl_FragColor=enc(b);");
        timing=true;
        try {
            for(int[] size:new int[][]{{128,72},{192,144},{256,192}}) {
                W=size[0];H=size[1];
                for(float consensus:new float[]{0,1}){render(baseline,consensus);render(current,consensus);}
            }
        } finally {timing=false;W=32;H=24;}
    }
}
