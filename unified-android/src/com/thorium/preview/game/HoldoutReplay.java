package com.thorium.preview.game;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.PixelFormat;
import android.media.Image;
import android.media.ImageReader;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLExt;
import android.opengl.EGLSurface;
import android.opengl.GLES20;
import android.opengl.GLUtils;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.SystemClock;
import android.util.Log;

import java.io.File;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * QA only: plays saved hold-out triplets into a real DisplayFrameGenerator
 * with hold-out scoring on, so the production synthesis is scored on the same
 * frames every time and without an emulator running (fan noise and heat,
 * 2026-10-24).
 *
 * <p>A case directory holds numbered triplet folders, each with A.png, B.png
 * and C.png of one size: two real frames and the real frame between them.
 * Triplets stream back to back one source period apart, as a game's frames
 * would (generation qualifies on a steady source; pauses reset it). Each
 * triplet's times are registered (DisplayFrameGenerator.replayReferences):
 * hold-out mode withholds B and scores the image generated for exactly the
 * pair (A, C) against it ("Hold-out pair" per triplet); nothing that spans two
 * triplets is ever scored.
 *
 * <p>Runs as its own process from adb, never inside the app:
 * {@code app_process -Djava.library.path=<app lib dir> /system/bin
 * com.thorium.preview.game.HoldoutReplay CASE_DIR [REFRESH_HZ] [LEVELS]} with
 * the installed APK as CLASSPATH (tools/qa/replay_bench.py). The product
 * keeps no exported entry point for it.
 */
final class HoldoutReplay {
    private static final String TAG = "EmuFusionReplay";
    private static final double SOURCE_HZ = 30.0;
    private static final long SOURCE_PERIOD_NS = Math.round(1e9 / SOURCE_HZ);
    // The last scores are published on the generator's one-second tick.
    private static final long DRAIN_MS = 2_500L;

    private static final String VERTEX =
            "attribute vec2 aPosition;\n" +
            "varying vec2 vTexCoord;\n" +
            "void main() {\n" +
            "  vTexCoord = vec2(aPosition.x * 0.5 + 0.5, 0.5 - aPosition.y * 0.5);\n" +
            "  gl_Position = vec4(aPosition, 0.0, 1.0);\n" +
            "}\n";
    private static final String FRAGMENT =
            "precision mediump float;\n" +
            "uniform sampler2D uImage;\n" +
            "varying vec2 vTexCoord;\n" +
            "void main() { gl_FragColor = texture2D(uImage, vTexCoord); }\n";

    // Production (24: DIS refined per phase), DIS without the per-phase
    // refinement (21), and the block matcher's prepared warp (115).
    static final int[] DEFAULT_LEVELS = {24, 21, 115};

    private HoldoutReplay() {}

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("usage: HoldoutReplay CASE_DIR [REFRESH_HZ] [LEVELS a,b,c] [DUMP_DIR [field]]");
            System.exit(2);
        }
        float refreshHz = args.length > 1 ? Float.parseFloat(args[1]) : 120f;
        int[] levels = args.length > 2 ?
                TimelineSchedulerSwitch.parseHoldoutLevels(args[2]) : DEFAULT_LEVELS;
        // Optional: every scored triplet's generated, reference and motion planes.
        if (args.length > 3) DisplayFrameGenerator.replayDumpDirectory = new File(args[3]);
        // "field": only synthesis 24's DIS field per triplet (training data).
        DisplayFrameGenerator.replayDumpFieldOnly = args.length > 4 && "field".equals(args[4]);
        try {
            run(new File(args[0]), refreshHz, levels);
        } catch (Throwable failure) {
            Log.e(TAG, "Replay failed", failure);
            failure.printStackTrace();
            System.exit(1);
        }
        System.exit(0);
    }

    /** Triplet folders of one case, in name order; empty when none. */
    static List<File> triplets(File caseDirectory) {
        List<File> found = new ArrayList<>();
        File[] children = caseDirectory.listFiles(File::isDirectory);
        if (children == null) return found;
        Arrays.sort(children);
        for (File child : children)
            if (new File(child, "A.png").isFile() && new File(child, "B.png").isFile() &&
                    new File(child, "C.png").isFile())
                found.add(child);
        return found;
    }

    /** Scores every triplet of one case with a fresh generator. Blocks. */
    static void run(File caseDirectory, float refreshHz, int[] levels) throws Exception {
        List<File> triplets = triplets(caseDirectory);
        if (triplets.isEmpty())
            throw new IllegalArgumentException("no triplets in " + caseDirectory);
        Bitmap first = decode(new File(triplets.get(0), "A.png"));
        int width = first.getWidth();
        int height = first.getHeight();
        first.recycle();
        TimelineSchedulerSwitch.configureForReplay(levels);
        Log.i(TAG, "Replay start case=" + caseDirectory.getName() + " triplets=" +
                triplets.size() + " size=" + width + "x" + height + " refreshHz=" + refreshHz +
                " levels=" + Arrays.toString(levels));

        HandlerThread drainThread = new HandlerThread("emufusion-replay-output");
        drainThread.start();
        ImageReader output = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 3);
        output.setOnImageAvailableListener(reader -> {
            Image image = reader.acquireLatestImage();
            if (image != null) image.close();
        }, new Handler(drainThread.getLooper()));
        DisplayFrameGenerator generator = null;
        Producer producer = null;
        try {
            DisplayFrameGenerator.replayOffscreen = true;
            // Display 0 with dense motion requested, as an in-window game's
            // top-screen generator is.
            generator = new DisplayFrameGenerator(output.getSurface(), width, height,
                    width, height, refreshHz, "qa-replay", 0, () -> false, () -> true);
            generator.setAuthoritativeSourceHz(SOURCE_HZ);
            generator.setProducerTimelineHz(SOURCE_HZ);
            producer = new Producer(generator.inputSurface(), width, height);
            int submitted = 0;
            long dueNs = System.nanoTime() + SOURCE_PERIOD_NS;
            for (File triplet : triplets) {
                Bitmap[] frames = {decode(new File(triplet, "A.png")),
                        decode(new File(triplet, "B.png")), decode(new File(triplet, "C.png"))};
                try {
                    if (!sameSize(frames, width, height)) {
                        Log.w(TAG, "Replay skipped " + triplet.getName() + ": size differs");
                        continue;
                    }
                    // A slow decode delays the stream rather than squeezing it.
                    dueNs = Math.max(dueNs, System.nanoTime());
                    long referenceNs = dueNs + SOURCE_PERIOD_NS;
                    DisplayFrameGenerator.replayReferences.put(referenceNs,
                            new long[]{dueNs, referenceNs + SOURCE_PERIOD_NS});
                    Log.i(TAG, "Replay triplet name=" + triplet.getName() +
                            " referenceNs=" + referenceNs);
                    for (Bitmap frame : frames) {
                        sleepUntil(dueNs);
                        producer.submit(frame, dueNs);
                        dueNs += SOURCE_PERIOD_NS;
                    }
                    ++submitted;
                } finally {
                    for (Bitmap frame : frames) if (frame != null) frame.recycle();
                }
            }
            SystemClock.sleep(DRAIN_MS);
            Log.i(TAG, "Replay done case=" + caseDirectory.getName() + " submitted=" + submitted);
        } finally {
            if (producer != null) producer.release();
            if (generator != null) generator.close();
            output.close();
            drainThread.quitSafely();
        }
    }

    private static Bitmap decode(File file) {
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inPreferredConfig = Bitmap.Config.ARGB_8888;
        options.inScaled = false;
        Bitmap bitmap = BitmapFactory.decodeFile(file.getAbsolutePath(), options);
        if (bitmap == null) throw new IllegalArgumentException("unreadable " + file);
        return bitmap;
    }

    private static boolean sameSize(Bitmap[] frames, int width, int height) {
        for (Bitmap frame : frames)
            if (frame.getWidth() != width || frame.getHeight() != height) return false;
        return true;
    }

    private static void sleepUntil(long dueNs) {
        long waitMs = (dueNs - System.nanoTime()) / 1_000_000L;
        if (waitMs > 0L) SystemClock.sleep(waitMs);
    }

    /** A GLES producer on the generator's input, as an emulator's would be. */
    private static final class Producer {
        private final EGLDisplay display;
        private final EGLContext context;
        private final EGLSurface surface;
        private final int width, height, program, texture;
        private final FloatBuffer quad;

        Producer(android.view.Surface input, int width, int height) {
            this.width = width;
            this.height = height;
            display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
            int[] version = new int[2];
            if (!EGL14.eglInitialize(display, version, 0, version, 1))
                throw new IllegalStateException("eglInitialize failed");
            int[] attributes = {EGL14.EGL_RED_SIZE, 8, EGL14.EGL_GREEN_SIZE, 8,
                    EGL14.EGL_BLUE_SIZE, 8, EGL14.EGL_ALPHA_SIZE, 8,
                    EGL14.EGL_RENDERABLE_TYPE, EGL14.EGL_OPENGL_ES2_BIT,
                    EGL14.EGL_SURFACE_TYPE, EGL14.EGL_WINDOW_BIT, EGL14.EGL_NONE};
            EGLConfig[] configs = new EGLConfig[1];
            int[] count = new int[1];
            if (!EGL14.eglChooseConfig(display, attributes, 0, configs, 0, 1, count, 0) ||
                    count[0] < 1)
                throw new IllegalStateException("no RGBA8888 window config");
            context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT,
                    new int[]{EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE}, 0);
            surface = EGL14.eglCreateWindowSurface(display, configs[0], input,
                    new int[]{EGL14.EGL_NONE}, 0);
            if (context == EGL14.EGL_NO_CONTEXT || surface == EGL14.EGL_NO_SURFACE ||
                    !EGL14.eglMakeCurrent(display, surface, surface, context))
                throw new IllegalStateException("replay producer EGL setup failed");
            program = link(VERTEX, FRAGMENT);
            int[] name = new int[1];
            GLES20.glGenTextures(1, name, 0);
            texture = name[0];
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER,
                    GLES20.GL_NEAREST);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER,
                    GLES20.GL_NEAREST);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S,
                    GLES20.GL_CLAMP_TO_EDGE);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T,
                    GLES20.GL_CLAMP_TO_EDGE);
            quad = ByteBuffer.allocateDirect(8 * 4).order(ByteOrder.nativeOrder())
                    .asFloatBuffer().put(new float[]{-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f});
            quad.position(0);
        }

        /** Draws one frame 1:1 and queues it with its source timestamp. */
        void submit(Bitmap frame, long timestampNs) {
            GLES20.glViewport(0, 0, width, height);
            GLES20.glUseProgram(program);
            GLES20.glActiveTexture(GLES20.GL_TEXTURE0);
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture);
            GLUtils.texImage2D(GLES20.GL_TEXTURE_2D, 0, frame, 0);
            GLES20.glUniform1i(GLES20.glGetUniformLocation(program, "uImage"), 0);
            int position = GLES20.glGetAttribLocation(program, "aPosition");
            GLES20.glEnableVertexAttribArray(position);
            GLES20.glVertexAttribPointer(position, 2, GLES20.GL_FLOAT, false, 0, quad);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
            GLES20.glDisableVertexAttribArray(position);
            EGLExt.eglPresentationTimeANDROID(display, surface, timestampNs);
            if (!EGL14.eglSwapBuffers(display, surface))
                throw new IllegalStateException("replay swap failed 0x" +
                        Integer.toHexString(EGL14.eglGetError()));
        }

        void release() {
            EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE,
                    EGL14.EGL_NO_CONTEXT);
            EGL14.eglDestroySurface(display, surface);
            EGL14.eglDestroyContext(display, context);
            EGL14.eglReleaseThread();
        }

        private static int link(String vertexSource, String fragmentSource) {
            int vertex = compile(GLES20.GL_VERTEX_SHADER, vertexSource);
            int fragment = compile(GLES20.GL_FRAGMENT_SHADER, fragmentSource);
            int linked = GLES20.glCreateProgram();
            GLES20.glAttachShader(linked, vertex);
            GLES20.glAttachShader(linked, fragment);
            GLES20.glLinkProgram(linked);
            int[] status = new int[1];
            GLES20.glGetProgramiv(linked, GLES20.GL_LINK_STATUS, status, 0);
            if (status[0] == 0)
                throw new IllegalStateException("replay program: " +
                        GLES20.glGetProgramInfoLog(linked));
            return linked;
        }

        private static int compile(int type, String source) {
            int shader = GLES20.glCreateShader(type);
            GLES20.glShaderSource(shader, source);
            GLES20.glCompileShader(shader);
            int[] status = new int[1];
            GLES20.glGetShaderiv(shader, GLES20.GL_COMPILE_STATUS, status, 0);
            if (status[0] == 0)
                throw new IllegalStateException("replay shader: " +
                        GLES20.glGetShaderInfoLog(shader));
            return shader;
        }
    }
}
