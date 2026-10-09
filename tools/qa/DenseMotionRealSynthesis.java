package com.thorium.preview.game;

import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.util.Map;
import static android.opengl.GLES30.*;

/** Offline real-pair diagnostic. Cut admission disabled because LFD1 lacks it.
 * Not a deployed renderer and not presentation/cadence qualification. */
final class DenseMotionRealSynthesis {
    static int shader(int kind,String source) {
        int s=glCreateShader(kind);glShaderSource(s,source);glCompileShader(s);
        int[] ok=new int[1];glGetShaderiv(s,GL_COMPILE_STATUS,ok,0);
        if(ok[0]==0)throw new IllegalStateException(glGetShaderInfoLog(s));return s;
    }
    static void scalar(int p,String name,float value){glUniform1f(glGetUniformLocation(p,name),value);}
    static void vector(int p,String name,float x,float y){glUniform2f(glGetUniformLocation(p,name),x,y);}
    static void bind(int p,String name,int unit,int texture) {
        glActiveTexture(GL_TEXTURE0+unit);glBindTexture(GL_TEXTURE_2D,texture);
        glUniform1i(glGetUniformLocation(p,name),unit);
    }
    static void run(Map<String,Integer> inputs,int width,int height,float limit,
                    String shaderPath,String output,boolean production) throws IOException {
        String base=new String(Files.readAllBytes(Paths.get(shaderPath)),java.nio.charset.StandardCharsets.UTF_8);
        String fragment=(production ? base : DenseMotionSynthesisShader.build(base))
            .replace("varying vec2 vTexCoord;","in vec2 vTexCoord;\nout vec4 resultColor;")
            .replace("texture2D(","texture(").replace("gl_FragColor","resultColor");
        int vs=shader(GL_VERTEX_SHADER,"#version 300 es\nout vec2 vTexCoord;void main(){vec2 q=vec2(float(gl_VertexID&1),float((gl_VertexID>>1)&1));vTexCoord=q;gl_Position=vec4(q*2.-1.,0.,1.);}");
        int fs=shader(GL_FRAGMENT_SHADER,"#version 300 es\n"+fragment);
        int p=glCreateProgram();glAttachShader(p,vs);glAttachShader(p,fs);glLinkProgram(p);
        int[] ok=new int[1];glGetProgramiv(p,GL_LINK_STATUS,ok,0);
        if(ok[0]==0)throw new IllegalStateException(glGetProgramInfoLog(p));
        int[] target=new int[1],fb=new int[1],vao=new int[1];
        glGenTextures(1,target,0);glBindTexture(GL_TEXTURE_2D,target[0]);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,width,height,0,GL_RGBA,GL_UNSIGNED_BYTE,null);
        glGenFramebuffers(1,fb,0);glGenVertexArrays(1,vao,0);
        Files.createDirectory(Paths.get(output));
        // Product history textures use linear image sampling; packed motion
        // textures remain nearest so Q8.8 bytes are never interpolated.
        for(String name:new String[]{"previousFull","currentFull"}) {
            glBindTexture(GL_TEXTURE_2D,inputs.get(name));
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        }
        try(DenseMotionTransportPass transport=new DenseMotionTransportPass(width,height)) {
            for(float phase:new float[]{0,.5f,1}) {
                // Normal Built-in samples endpoint-local validated fields;
                // it does not use the experimental midpoint transport pass.
                int backward=production ? inputs.get("validated0") : transport.renderWithSeed(0,inputs.get("validated0"),inputs.get("final0"),inputs.get("seed0"),width,height,1-phase,limit/width,limit/height);
                int forward=production ? inputs.get("validated1") : transport.renderWithSeed(1,inputs.get("validated1"),inputs.get("final1"),inputs.get("seed1"),width,height,phase,limit/width,limit/height);
                glBindFramebuffer(GL_FRAMEBUFFER,fb[0]);
                glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,target[0],0);
                if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)throw new IllegalStateException("synthesis FBO");
                glViewport(0,0,width,height);glDisable(GL_BLEND);glDisable(GL_DEPTH_TEST);glDisable(GL_SCISSOR_TEST);glDisable(GL_DITHER);
                glColorMask(true,true,true,true);glUseProgram(p);glBindVertexArray(vao[0]);
                bind(p,"uPrevious",0,inputs.get("previousFull"));bind(p,"uCurrent",1,inputs.get("currentFull"));
                bind(p,"uBackwardMotion",2,backward);bind(p,"uForwardMotion",3,forward);
                bind(p,"uGlobalBackwardMotion",4,inputs.get("validated0"));bind(p,"uGlobalForwardMotion",5,inputs.get("validated1"));
                bind(p,"uDenseSeedBackwardTex",6,inputs.get("seed0"));bind(p,"uDenseSeedForwardTex",7,inputs.get("seed1"));
                bind(p,"uDenseCutTex",8,inputs.get("seed0"));
                bind(p,"uEndpointBackward",9,inputs.get("final0"));bind(p,"uEndpointForward",10,inputs.get("final1"));
                vector(p,"uFlowRange",limit/width,limit/height);vector(p,"uDenseSeedSourceSize",width,height);
                scalar(p,"uPhase",phase);scalar(p,"uDenseEncoding",1);scalar(p,"uDenseSeedEnabled",production ? 0 : 1);
                scalar(p,"uDenseCutEnabled",0);scalar(p,"uEndpointPacked",1);
                glDrawArrays(GL_TRIANGLE_STRIP,0,4);
                ByteBuffer pixels=ByteBuffer.allocateDirect(width*height*4);
                glReadPixels(0,0,width,height,GL_RGBA,GL_UNSIGNED_BYTE,pixels);
                if(glGetError()!=GL_NO_ERROR)throw new IllegalStateException("synthesis GL error");
                byte[] bytes=new byte[pixels.capacity()];pixels.get(bytes);
                Files.write(Paths.get(output,"phase-"+phase+".rgba"),bytes);
                System.out.println("REAL_SYNTHESIS phase="+phase+" size="+width+"x"+height+" cut_admission_disabled=true production_synthesis="+production);
            }
        } finally {
            glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,fb,0);glDeleteTextures(1,target,0);
            glDeleteVertexArrays(1,vao,0);glDeleteProgram(p);glDeleteShader(vs);glDeleteShader(fs);
        }
    }
}
