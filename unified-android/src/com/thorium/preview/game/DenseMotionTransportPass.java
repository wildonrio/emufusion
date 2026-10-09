package com.thorium.preview.game;

import static android.opengl.GLES30.*;

/** Experimental, GL-thread-owned transport targets. Not connected to gameplay.
 * Inputs are separate validated confidence and signed-Q8.8 packed raw motion.
 * Caller must retain the resulting targets until synthesis has consumed them.
 */
final class DenseMotionTransportPass implements AutoCloseable {
    private final Thread owner = Thread.currentThread();
    private final int width, height;
    private final int[] targets = new int[2];
    private int program, framebuffer, depth, vao, sampler;
    private boolean closed;
    private DenseMotionCompactGeometry compact;

    DenseMotionTransportPass(int width, int height) {
        this(width, height, false);
    }

    DenseMotionTransportPass(int width, int height, boolean compactMode) {
        DenseMotionTransportShaders.instanceCount(width, height);
        // Two RGBA32F targets plus conservatively four bytes/pixel for depth.
        if ((long) width * height * (compactMode ? 52L : 36L) > (128L << 20)) throw new IllegalArgumentException("Transport target too large");
        this.width = width;
        this.height = height;
        if (integer(GL_MAJOR_VERSION) < 3) throw new IllegalStateException("GLES3 required");
        if (compactMode && integer(GL_MAJOR_VERSION)==3 && integer(GL_MINOR_VERSION)<1)
            throw new IllegalStateException("Compact transport requires GLES3.1");
        String extensions = glGetString(GL_EXTENSIONS);
        if (extensions == null || !(" " + extensions + " ").contains(" GL_EXT_color_buffer_float ")) {
            throw new IllegalStateException("Float color targets required for verified transport precision");
        }
        int limit = integer(GL_MAX_TEXTURE_SIZE);
        if (width > limit || height > limit) throw new IllegalArgumentException("Texture limit exceeded");
        State saved = new State();
        try {
            program = link(compactMode);
            if(compactMode)compact=new DenseMotionCompactGeometry(width,height);
            int[] id = new int[1];
            glGenFramebuffers(1, id, 0); framebuffer = id[0];
            glGenRenderbuffers(1, id, 0); depth = id[0];
            glGenVertexArrays(1, id, 0); vao = id[0];
            glGenSamplers(1, id, 0); sampler = id[0];
            if (framebuffer == 0 || depth == 0 || vao == 0 || sampler == 0) {
                throw new IllegalStateException("Transport object allocation failed");
            }
            glSamplerParameteri(sampler, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
            glSamplerParameteri(sampler, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
            glSamplerParameteri(sampler, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
            glSamplerParameteri(sampler, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
            glBindRenderbuffer(GL_RENDERBUFFER, depth);
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height);
            glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, depth);
            glActiveTexture(GL_TEXTURE0);
            glGenTextures(2, targets, 0);
            for (int texture : targets) {
                if (texture == 0) throw new IllegalStateException("Transport texture allocation failed");
                glBindTexture(GL_TEXTURE_2D, texture);
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
                // RGBA8 failed36 and RGBA16F failed2 host image fixtures.
                // No silent lower-precision fallback until an encoding passes.
                glTexStorage2D(GL_TEXTURE_2D, 1, GL_RGBA32F, width, height);
                attach(texture);
            }
        } catch (RuntimeException failure) {
            close();
            throw failure;
        } finally {
            saved.restore();
        }
    }

    int render(int direction, int validatedTexture, int packedRawTexture, int sourceWidth, int sourceHeight,
               float phase, float cameraX, float cameraY, float rangeX, float rangeY) {
        return renderInternal(direction, validatedTexture, packedRawTexture, 0, sourceWidth, sourceHeight,
                phase, cameraX, cameraY, rangeX, rangeY);
    }

    int renderWithSeed(int direction, int validatedTexture, int packedRawTexture, int cameraSeedTexture,
                       int sourceWidth, int sourceHeight, float phase, float rangeX, float rangeY) {
        if (cameraSeedTexture <= 0) throw new IllegalArgumentException("Missing camera seed");
        return renderInternal(direction, validatedTexture, packedRawTexture, cameraSeedTexture,
                sourceWidth, sourceHeight, phase, 0, 0, rangeX, rangeY);
    }

    private int renderInternal(int direction, int validatedTexture, int packedRawTexture, int cameraSeedTexture,
                               int sourceWidth, int sourceHeight, float phase, float cameraX, float cameraY,
                               float rangeX, float rangeY) {
        checkOwner();
        if (closed) throw new IllegalStateException("Transport closed");
        if (direction < 0 || direction > 1 || validatedTexture <= 0 || packedRawTexture <= 0
                || validatedTexture == packedRawTexture
                || !Float.isFinite(phase) || phase < 0 || phase > 1
                || !Float.isFinite(cameraX) || !Float.isFinite(cameraY)
                || !Float.isFinite(rangeX) || !Float.isFinite(rangeY) || rangeX <= 0 || rangeY <= 0) {
            throw new IllegalArgumentException("Invalid transport input");
        }
        int instances = DenseMotionTransportShaders.instanceCount(sourceWidth, sourceHeight);
        // Source/output rescaling needs a different footprint contract. Refuse
        // it until tested rather than silently drawing holes between cells.
        if (sourceWidth != width || sourceHeight != height) throw new IllegalArgumentException("Unverified source scaling");
        if (validatedTexture == targets[0] || validatedTexture == targets[1]) throw new IllegalArgumentException("Texture feedback");
        if (packedRawTexture == targets[0] || packedRawTexture == targets[1]) throw new IllegalArgumentException("Raw texture feedback");
        if (cameraSeedTexture != 0 && (cameraSeedTexture == targets[0] || cameraSeedTexture == targets[1])) throw new IllegalArgumentException("Seed texture feedback");
        State saved = new State();
        try {
            glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
            attach(targets[direction]);
            glViewport(0, 0, width, height);
            for (int cap : State.CAPS) glDisable(cap);
            glEnable(GL_DEPTH_TEST);
            glDepthFunc(GL_LESS); glDepthMask(true); glDepthRangef(0, 1);
            glColorMask(true, true, true, true);
            glClearColor(128f / 255f, 128f / 255f, 0, 0);
            glClearDepthf(1);
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
            glUseProgram(program); glBindVertexArray(vao);
            glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, validatedTexture);
            glBindSampler(0, sampler);
            glUniform1i(glGetUniformLocation(program, "field"), 0);
            glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, packedRawTexture);
            glBindSampler(1, sampler);
            glUniform1i(glGetUniformLocation(program, "rawField"), 1);
            glUniform1f(glGetUniformLocation(program, "useRaw"), 1);
            glUniform2f(glGetUniformLocation(program, "sourceSize"), sourceWidth, sourceHeight);
            glActiveTexture(GL_TEXTURE2);
            glBindTexture(GL_TEXTURE_2D, cameraSeedTexture != 0 ? cameraSeedTexture : packedRawTexture);
            glBindSampler(2, sampler);
            glUniform1i(glGetUniformLocation(program, "cameraSeed"), 2);
            glUniform1f(glGetUniformLocation(program, "useCameraSeed"), cameraSeedTexture != 0 ? 1 : 0);
            glUniform1f(glGetUniformLocation(program, "phase"), phase);
            glUniform2i(glGetUniformLocation(program, "gridSize"), sourceWidth, sourceHeight);
            glUniform2f(glGetUniformLocation(program, "size"), width, height);
            glUniform2f(glGetUniformLocation(program, "camera"), cameraX, cameraY);
            glUniform2f(glGetUniformLocation(program, "flowRange"), rangeX, rangeY);
            if(compact!=null)compact.draw(width,height,program);
            else glDrawArraysInstanced(GL_TRIANGLE_STRIP, 0, 4, instances);
            return targets[direction];
        } finally {
            saved.restore();
        }
    }

    void enableDiagnosticTiming() {
        checkOwner();
        if(closed || compact==null)throw new IllegalStateException("Open compact pass required");
        compact.diagnosticTiming=true;
    }

    long[] diagnosticTimes() {
        checkOwner();
        if(closed || compact==null || !compact.diagnosticTiming)throw new IllegalStateException("Diagnostic timing not enabled");
        return new long[]{compact.computeNs,compact.drawNs};
    }

    private void attach(int texture) {
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
            throw new IllegalStateException("Incomplete transport framebuffer");
        }
    }

    static int compile(int kind, String source) {
        int shader = glCreateShader(kind);
        glShaderSource(shader, source); glCompileShader(shader);
        int[] ok = new int[1]; glGetShaderiv(shader, GL_COMPILE_STATUS, ok, 0);
        if (ok[0] == 0) {
            String error = glGetShaderInfoLog(shader); glDeleteShader(shader);
            throw new IllegalStateException(error);
        }
        return shader;
    }

    private static int link(boolean compactMode) {
        int vertex = 0, fragment = 0, result = 0;
        try {
            vertex = compile(GL_VERTEX_SHADER, compactMode ? DenseMotionTransportShaders.compactVertex() : DenseMotionTransportShaders.instancedVertex());
            fragment = compile(GL_FRAGMENT_SHADER, compactMode ? DenseMotionTransportShaders.instancedFragment().replace("#version 300 es", "#version 310 es") : DenseMotionTransportShaders.instancedFragment());
            result = glCreateProgram(); glAttachShader(result, vertex); glAttachShader(result, fragment);
            glLinkProgram(result);
            int[] ok = new int[1]; glGetProgramiv(result, GL_LINK_STATUS, ok, 0);
            if (ok[0] == 0) throw new IllegalStateException(glGetProgramInfoLog(result));
            return result;
        } catch (RuntimeException failure) {
            if (result != 0) glDeleteProgram(result);
            throw failure;
        } finally {
            if (vertex != 0) glDeleteShader(vertex);
            if (fragment != 0) glDeleteShader(fragment);
        }
    }

    private void checkOwner() {
        if (Thread.currentThread() != owner) throw new IllegalStateException("Wrong GL thread");
    }

    @Override public void close() {
        checkOwner();
        if (closed) return;
        closed = true;
        if(compact!=null)compact.close();
        glDeleteTextures(2, targets, 0);
        if (depth != 0) glDeleteRenderbuffers(1, new int[]{depth}, 0);
        if (framebuffer != 0) glDeleteFramebuffers(1, new int[]{framebuffer}, 0);
        if (vao != 0) glDeleteVertexArrays(1, new int[]{vao}, 0);
        if (sampler != 0) glDeleteSamplers(1, new int[]{sampler}, 0);
        if (program != 0) glDeleteProgram(program);
    }

    private static int integer(int key) { int[] value = new int[1]; glGetIntegerv(key, value, 0); return value[0]; }
    private static float[] floats(int key, int size) { float[] value = new float[size]; glGetFloatv(key, value, 0); return value; }
    private static boolean[] booleans(int key, int size) { boolean[] value = new boolean[size]; glGetBooleanv(key, value, 0); return value; }

    private static final class State {
        static final int[] CAPS = {GL_BLEND, GL_SCISSOR_TEST, GL_CULL_FACE, GL_DEPTH_TEST,
                GL_STENCIL_TEST, GL_DITHER, GL_RASTERIZER_DISCARD, GL_SAMPLE_COVERAGE,
                GL_SAMPLE_ALPHA_TO_COVERAGE, GL_POLYGON_OFFSET_FILL};
        final boolean[] enabled = new boolean[CAPS.length];
        final int program = integer(GL_CURRENT_PROGRAM), vao = integer(GL_VERTEX_ARRAY_BINDING);
        final int draw = integer(GL_DRAW_FRAMEBUFFER_BINDING), read = integer(GL_READ_FRAMEBUFFER_BINDING);
        final int renderbuffer = integer(GL_RENDERBUFFER_BINDING), active = integer(GL_ACTIVE_TEXTURE);
        final int depthFunction = integer(GL_DEPTH_FUNC);
        final int[] viewport = new int[4];
        final float[] clear = floats(GL_COLOR_CLEAR_VALUE, 4), depthClear = floats(GL_DEPTH_CLEAR_VALUE, 1), range = floats(GL_DEPTH_RANGE, 2);
        final boolean[] colorMask = booleans(GL_COLOR_WRITEMASK, 4), depthMask = booleans(GL_DEPTH_WRITEMASK, 1);
        final int[] textures = new int[3], samplers = new int[3];
        State() {
            glGetIntegerv(GL_VIEWPORT, viewport, 0);
            for (int i = 0; i < CAPS.length; i++) enabled[i] = glIsEnabled(CAPS[i]);
            for (int unit = 0; unit < textures.length; unit++) {
                glActiveTexture(GL_TEXTURE0 + unit);
                textures[unit] = integer(GL_TEXTURE_BINDING_2D);
                samplers[unit] = integer(GL_SAMPLER_BINDING);
            }
            glActiveTexture(active);
        }
        void restore() {
            glUseProgram(program); glBindVertexArray(vao);
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, draw); glBindFramebuffer(GL_READ_FRAMEBUFFER, read);
            glBindRenderbuffer(GL_RENDERBUFFER, renderbuffer);
            glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
            glDepthFunc(depthFunction); glDepthMask(depthMask[0]); glDepthRangef(range[0], range[1]);
            glColorMask(colorMask[0], colorMask[1], colorMask[2], colorMask[3]);
            glClearColor(clear[0], clear[1], clear[2], clear[3]); glClearDepthf(depthClear[0]);
            for (int i = 0; i < CAPS.length; i++) { if (enabled[i]) glEnable(CAPS[i]); else glDisable(CAPS[i]); }
            for (int unit = 0; unit < textures.length; unit++) {
                glActiveTexture(GL_TEXTURE0 + unit);
                glBindTexture(GL_TEXTURE_2D, textures[unit]); glBindSampler(unit, samplers[unit]);
            }
            glActiveTexture(active);
        }
    }
}
