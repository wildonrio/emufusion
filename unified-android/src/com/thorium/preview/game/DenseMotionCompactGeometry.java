package com.thorium.preview.game;

import static android.opengl.GLES31.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.IntBuffer;

/** Experimental GPU-only transport geometry. Caller owns the GL thread/context. */
final class DenseMotionCompactGeometry implements AutoCloseable {
    private int program;
    boolean diagnosticTiming;
    long computeNs, drawNs;
    private final int[] buffers = new int[2];
    private final IntBuffer reset = ByteBuffer.allocateDirect(16).order(ByteOrder.nativeOrder()).asIntBuffer();

    DenseMotionCompactGeometry(int width, int height) {
        long bytes = (long) DenseMotionTransportShaders.instanceCount(width, height) * 16;
        int[] limit = new int[1];
        glGetIntegerv(GL_MAX_SHADER_STORAGE_BLOCK_SIZE, limit, 0);
        if (bytes > limit[0]) throw new IllegalArgumentException("Compact node storage exceeds GPU limit");
        reset.put(new int[]{4, 0, 0, 0}).position(0);
        int[] previous = new int[1];glGetIntegerv(GL_SHADER_STORAGE_BUFFER_BINDING, previous, 0);
        int shader = 0;
        try {
            shader = DenseMotionTransportPass.compile(GL_COMPUTE_SHADER, DenseMotionTransportShaders.COMPACT);
            program = glCreateProgram();glAttachShader(program, shader);glLinkProgram(program);
            int[] ok = new int[1];glGetProgramiv(program, GL_LINK_STATUS, ok, 0);
            if (ok[0] == 0) throw new IllegalStateException(glGetProgramInfoLog(program));
            glGenBuffers(2, buffers, 0);
            if (buffers[0] == 0 || buffers[1] == 0) throw new IllegalStateException("Compact allocation failed");
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[0]);glBufferData(GL_SHADER_STORAGE_BUFFER, 16, null, GL_DYNAMIC_DRAW);
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, buffers[1]);glBufferData(GL_SHADER_STORAGE_BUFFER, (int) bytes, null, GL_DYNAMIC_DRAW);
            if (glGetError() != GL_NO_ERROR) throw new IllegalStateException("Compact storage allocation failed");
        } catch (RuntimeException failure) { close();throw failure; }
        finally {
            if (shader != 0) glDeleteShader(shader);
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, previous[0]);
        }
    }

    /** Input texture units 0/1 and transport uniforms must already be bound. */
    void draw(int width, int height, int transportProgram) {
        int[] generic = new int[1], indirect = new int[1], binding = new int[2];
        long[][] start = new long[2][1], size = new long[2][1];
        glGetIntegerv(GL_SHADER_STORAGE_BUFFER_BINDING, generic, 0);
        glGetIntegerv(GL_DRAW_INDIRECT_BUFFER_BINDING, indirect, 0);
        for (int i=0;i<2;i++) {
            glGetIntegeri_v(GL_SHADER_STORAGE_BUFFER_BINDING,i,binding,i);
            glGetInteger64i_v(GL_SHADER_STORAGE_BUFFER_START,i,start[i],0);
            glGetInteger64i_v(GL_SHADER_STORAGE_BUFFER_SIZE,i,size[i],0);
        }
        try {
            if(diagnosticTiming)glFinish();
            long started=diagnosticTiming?System.nanoTime():0;
            glMemoryBarrier(GL_BUFFER_UPDATE_BARRIER_BIT | GL_SHADER_STORAGE_BARRIER_BIT);
            glBindBuffer(GL_SHADER_STORAGE_BUFFER,buffers[0]);reset.position(0);
            glBufferSubData(GL_SHADER_STORAGE_BUFFER,0,16,reset);
            glBindBufferBase(GL_SHADER_STORAGE_BUFFER,0,buffers[0]);
            glBindBufferBase(GL_SHADER_STORAGE_BUFFER,1,buffers[1]);
            glUseProgram(program);
            glUniform1i(glGetUniformLocation(program,"field"),0);
            glUniform1i(glGetUniformLocation(program,"rawField"),1);
            glUniform2i(glGetUniformLocation(program,"sourceGrid"),width,height);
            glDispatchCompute((width+7)/8,(height+7)/8,1);
            glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT | GL_COMMAND_BARRIER_BIT);
            if(diagnosticTiming){glFinish();computeNs=System.nanoTime()-started;started=System.nanoTime();}
            glUseProgram(transportProgram);
            glBindBuffer(GL_DRAW_INDIRECT_BUFFER,buffers[0]);
            glDrawArraysIndirect(GL_TRIANGLE_STRIP,0);
            if(diagnosticTiming){glFinish();drawNs=System.nanoTime()-started;}
        } finally {
            glUseProgram(transportProgram);
            for (int i=0;i<2;i++) {
                if (binding[i]!=0 && size[i][0]>0)
                    glBindBufferRange(GL_SHADER_STORAGE_BUFFER,i,binding[i],(int)start[i][0],(int)size[i][0]);
                else glBindBufferBase(GL_SHADER_STORAGE_BUFFER,i,binding[i]);
            }
            glBindBuffer(GL_SHADER_STORAGE_BUFFER,generic[0]);
            glBindBuffer(GL_DRAW_INDIRECT_BUFFER,indirect[0]);
        }
    }

    @Override public void close() {
        glDeleteBuffers(2,buffers,0);buffers[0]=buffers[1]=0;
        if(program!=0)glDeleteProgram(program);program=0;
    }
}
