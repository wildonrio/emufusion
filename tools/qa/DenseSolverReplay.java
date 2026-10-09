package com.thorium.preview.game;

import java.nio.*;
import java.nio.file.*;
import java.util.Map;
import static android.opengl.GLES30.*;

/** One additional reciprocal refinement on captured finalized fields.
 * Not reconstruction of the original pyramid or its intermediate priors. */
final class DenseSolverReplay {
    static void run(Map<String,Integer> t,Map<String,int[]> sizes,int width,int height,
                    float limit,String path,String output) throws java.io.IOException {
        String current=new String(Files.readAllBytes(Paths.get(path)),java.nio.charset.StandardCharsets.UTF_8);
        String guard="vec2 proposed=floor(mix(b,smooth,w)*256.0+.5)/256.0;if(objective(proposed)+.000001<objective(b))b=proposed;gl_FragColor=enc(b);";
        if(!current.contains(guard))throw new AssertionError("guard absent");
        Files.createDirectory(Paths.get(output));
        for(String name:new String[]{"previousFull","currentFull"}) {
            glBindTexture(GL_TEXTURE_2D,t.get(name));
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        }
        for(boolean guarded:new boolean[]{false,true})for(int d=0;d<2;d++) {
            String source=guarded?current:current.replace(guard,"b=mix(b,smooth,w);gl_FragColor=enc(b);");
            String fragment="#version 300 es\n"+source.replace("varying vec2 vTexCoord;","in vec2 vTexCoord;out vec4 resultColor;")
                .replace("texture2D(","texture(").replace("gl_FragColor","resultColor").replaceAll("\\bsmooth\\b","neighborSmooth");
            int vs=DenseMotionRealSynthesis.shader(GL_VERTEX_SHADER,"#version 300 es\nout vec2 vTexCoord;void main(){vec2 q=vec2(float(gl_VertexID&1),float((gl_VertexID>>1)&1));vTexCoord=q;gl_Position=vec4(q*2.-1.,0.,1.);}");
            int fs=DenseMotionRealSynthesis.shader(GL_FRAGMENT_SHADER,fragment),p=glCreateProgram();
            glAttachShader(p,vs);glAttachShader(p,fs);glLinkProgram(p);int[] ok=new int[1];glGetProgramiv(p,GL_LINK_STATUS,ok,0);
            if(ok[0]==0)throw new AssertionError(glGetProgramInfoLog(p));
            int[] shape=sizes.get("final"+d),reverse=sizes.get("final"+(1-d));int w=shape[0],h=shape[1];
            int[] tex=new int[1],fb=new int[1],vao=new int[1];glGenTextures(1,tex,0);glBindTexture(GL_TEXTURE_2D,tex[0]);
            glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,null);
            glGenFramebuffers(1,fb,0);glBindFramebuffer(GL_FRAMEBUFFER,fb[0]);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,tex[0],0);
            if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)throw new AssertionError("replay framebuffer");
            glGenVertexArrays(1,vao,0);glBindVertexArray(vao[0]);glUseProgram(p);
            DenseMotionRealSynthesis.bind(p,"uReference",0,t.get(d==0?"previousFull":"currentFull"));
            DenseMotionRealSynthesis.bind(p,"uTarget",1,t.get(d==0?"currentFull":"previousFull"));
            DenseMotionRealSynthesis.bind(p,"uPriorFlow",2,t.get("final"+d));
            DenseMotionRealSynthesis.bind(p,"uReciprocalFlow",3,t.get("final"+(1-d)));
            DenseMotionRealSynthesis.bind(p,"uTemporalFlow",4,t.get("validated"+d));
            DenseMotionRealSynthesis.bind(p,"uGlobalSeed",5,t.get("seed"+d));
            DenseMotionRealSynthesis.scalar(p,"uHasPrior",1);DenseMotionRealSynthesis.scalar(p,"uUseReciprocalGuide",1);
            DenseMotionRealSynthesis.scalar(p,"uUseNeighborProposal",1);DenseMotionRealSynthesis.scalar(p,"uReciprocalMargin",.006f);
            DenseMotionRealSynthesis.scalar(p,"uNeighborMargin",.002f);DenseMotionRealSynthesis.scalar(p,"uCycleObjectiveWeight",.006f);
            DenseMotionRealSynthesis.scalar(p,"uTemporalLimit",limit);
            DenseMotionRealSynthesis.vector(p,"uAnalysisTexel",1f/w,1f/h);DenseMotionRealSynthesis.vector(p,"uPriorTexel",1f/w,1f/h);
            DenseMotionRealSynthesis.vector(p,"uReciprocalTexel",1f/reverse[0],1f/reverse[1]);
            DenseMotionRealSynthesis.vector(p,"uSourceSize",width,height);DenseMotionRealSynthesis.vector(p,"uUpdateStep",1,1);
            glViewport(0,0,w,h);glDisable(GL_BLEND);glDisable(GL_DEPTH_TEST);glDisable(GL_DITHER);
            glDrawArrays(GL_TRIANGLE_STRIP,0,4);ByteBuffer pixels=ByteBuffer.allocateDirect(w*h*4);
            glReadPixels(0,0,w,h,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
            if(glGetError()!=GL_NO_ERROR)throw new AssertionError("replay GL error");
            byte[] bytes=new byte[pixels.capacity()];pixels.get(bytes);
            Files.write(Paths.get(output,(guarded?"guarded":"baseline")+"-"+d+".rgba"),bytes);
            System.out.println("SOLVER_REPLAY guarded="+guarded+" direction="+d+" size="+w+"x"+h+" additional_pass=true");
            glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,fb,0);glDeleteTextures(1,tex,0);
            glDeleteVertexArrays(1,vao,0);glDeleteProgram(p);glDeleteShader(vs);glDeleteShader(fs);
        }
    }
}
