package com.thorium.preview;

import android.view.Surface;
import com.thorium.preview.game.FrameGenerationRendererRegistry;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;

/**
 * Explicitly experimental Phase 2 GLES bridge.
 *
 * <p>This class is not selected by EmuFusion's production engine catalog. A
 * qualification caller must keep attach, run/present, recreate, detach, and
 * close on one dedicated render thread. The ordinary {@link LibretroHost}
 * remains software-only and cannot accidentally enable this path.</p>
 */
public final class ExperimentalGlesLibretroHost implements Closeable {
    interface Bindings {
        long create(String core, String root, String system, String save,
                    int presentationPolicy);
        default long create(String core, String root, String system, String save,
                            int presentationPolicy, int sourceTimelinePolicy) {
            if (sourceTimelinePolicy != SOURCE_TIMELINE_DEFAULT)
                throw new UnsupportedOperationException(
                        "source timeline policy is not supported by this binding");
            return create(core, root, system, save, presentationPolicy);
        }
        default long create(String core, String root, String system, String save,
                            int presentationPolicy, int sourceTimelinePolicy,
                            boolean widescreenEnhancementsEnabled) {
            if (!widescreenEnhancementsEnabled)
                throw new UnsupportedOperationException(
                        "widescreen preference is not supported by this binding");
            return create(core, root, system, save, presentationPolicy,
                    sourceTimelinePolicy);
        }
        void loadGame(long handle, String game);
        void setControllerPortDevice(long handle, int port, int device);
        void reset(long handle);
        void cheatReset(long handle);
        void cheatSet(long handle, int index, boolean enabled, String code);
        void setPresentationAspect(long handle, float aspect);
        void attach(long handle, Surface surface);
        void recreate(long handle, Surface surface);
        default void setFgTimestamp(long handle, boolean enabled) {
            if (enabled) throw new UnsupportedOperationException(
                    "FG timestamp ownership is unsupported by this binding");
        }
        void resize(long handle);
        boolean runAndPresent(long handle);
        default int runAndPresentStatus(long handle) {
            return runAndPresent(handle) ? 2 : 1;
        }
        default int runWithoutPresentStatus(long handle) {
            throw new UnsupportedOperationException("offscreen guest step unavailable");
        }
        void detach(long handle);
        void setPaused(long handle, boolean paused);
        void setJoypadButton(long handle, int port, int button, boolean pressed);
        void setAnalogAxis(long handle, int port, int index, int id, int value);
        void setPointer(long handle, int port, int x, int y, boolean pressed);
        int[] hardwareInfo(long handle);
        short[] drainAudio(long handle, int maxFrames);
        default long lastRunAudioDurationNanos(long handle) { return 0L; }
        double[] avInfo(long handle);
        default void setSynchronizedVideoRate(long handle, double declaredHz,
                                              double synchronizedHz) {
            if (Math.abs(declaredHz - synchronizedHz) > 1.0e-9)
                throw new UnsupportedOperationException(
                        "synchronized video rate is unsupported by this binding");
        }
        boolean stateReady(long handle);
        byte[] serialize(long handle);
        void unserialize(long handle, byte[] state);
        byte[] readSaveRam(long handle);
        void writeSaveRam(long handle, byte[] saveRam);
        void destroy(long handle);
    }

    private static final class JniBindings implements Bindings {
        static { System.loadLibrary("lucent_libretro_host"); }
        static final JniBindings INSTANCE = new JniBindings();
        @Override public long create(String core, String root, String system, String save,
                                     int presentationPolicy) {
            return create(core, root, system, save, presentationPolicy,
                    SOURCE_TIMELINE_DEFAULT);
        }
        @Override public long create(String core, String root, String system, String save,
                                     int presentationPolicy, int sourceTimelinePolicy) {
            return create(core, root, system, save, presentationPolicy,
                    sourceTimelinePolicy, true);
        }
        @Override public long create(String core, String root, String system, String save,
                                     int presentationPolicy, int sourceTimelinePolicy,
                                     boolean widescreenEnhancementsEnabled) {
            return nativeCreateGles(core, root, system, save, presentationPolicy,
                    sourceTimelinePolicy, widescreenEnhancementsEnabled);
        }
        @Override public void loadGame(long handle, String game) {
            nativeLoadGameGles(handle, game);
        }
        @Override public void setControllerPortDevice(long handle, int port, int device) {
            nativeSetControllerPortDeviceGles(handle, port, device);
        }
        @Override public void reset(long handle) { nativeResetGles(handle); }
        @Override public void cheatReset(long handle) { nativeCheatResetGles(handle); }
        @Override public void cheatSet(long handle, int index, boolean enabled, String code) {
            nativeCheatSetGles(handle, index, enabled, code);
        }
        @Override public void setPresentationAspect(long handle, float aspect) {
            nativeSetPresentationAspectGles(handle, aspect);
        }
        @Override public void attach(long handle, Surface surface) {
            nativeAttachSurfaceGles(handle, surface);
        }
        @Override public void recreate(long handle, Surface surface) {
            nativeRecreateSurfaceGles(handle, surface);
        }
        @Override public void setFgTimestamp(long handle, boolean enabled) {
            nativeSetFgTimestampGles(handle, enabled);
        }
        @Override public void resize(long handle) {
            nativeResizeSurfaceGles(handle);
        }
        @Override public boolean runAndPresent(long handle) {
            return runAndPresentStatus(handle) == 2;
        }
        @Override public int runAndPresentStatus(long handle) {
            return nativeRunAndPresentStatusGles(handle);
        }
        @Override public int runWithoutPresentStatus(long handle) {
            return nativeRunWithoutPresentStatusGles(handle);
        }
        @Override public void detach(long handle) { nativeDetachSurfaceGles(handle); }
        @Override public void setPaused(long handle, boolean paused) {
            nativeSetPausedGles(handle, paused);
        }
        @Override public void setJoypadButton(long handle, int port, int button,
                                              boolean pressed) {
            nativeSetJoypadButtonGles(handle, port, button, pressed);
        }
        @Override public void setAnalogAxis(long handle, int port, int index,
                                            int id, int value) {
            nativeSetAnalogAxisGles(handle, port, index, id, value);
        }
        @Override public void setPointer(long handle, int port, int x, int y,
                                         boolean pressed) {
            nativeSetPointerGles(handle, port, x, y, pressed);
        }
        @Override public int[] hardwareInfo(long handle) {
            return nativeHardwareInfoGles(handle);
        }
        @Override public short[] drainAudio(long handle, int maxFrames) {
            return nativeDrainAudioGles(handle, maxFrames);
        }
        @Override public double[] avInfo(long handle) { return nativeAvInfoGles(handle); }
        @Override public long lastRunAudioDurationNanos(long handle) {
            return nativeLastRunAudioDurationNanosGles(handle);
        }
        @Override public void setSynchronizedVideoRate(long handle,
                                                       double declaredHz,
                                                       double synchronizedHz) {
            nativeSetSynchronizedVideoRateGles(
                    handle, declaredHz, synchronizedHz);
        }
        @Override public boolean stateReady(long handle) { return nativeStateReadyGles(handle); }
        @Override public byte[] serialize(long handle) { return nativeSerializeGles(handle); }
        @Override public void unserialize(long handle, byte[] state) {
            nativeUnserializeGles(handle, state);
        }
        @Override public byte[] readSaveRam(long handle) {
            return nativeReadSaveRamGles(handle);
        }
        @Override public void writeSaveRam(long handle, byte[] saveRam) {
            nativeWriteSaveRamGles(handle, saveRam);
        }
        @Override public void destroy(long handle) { nativeDestroyGles(handle); }
    }

    public static final class AvInfo {
        public final double framesPerSecond;
        public final double sampleRate;
        public final float aspectRatio;
        public final int baseWidth;
        public final int baseHeight;

        AvInfo(double[] values) {
            framesPerSecond = values[0];
            sampleRate = values[1];
            aspectRatio = (float) values[2];
            baseWidth = (int) values[3];
            baseHeight = (int) values[4];
        }
    }

    public static final class HardwareInfo {
        public final boolean negotiated;
        public final boolean contextReady;
        public final int contextType;
        public final int majorVersion;
        public final int minorVersion;
        public final boolean bottomLeftOrigin;
        public final int frameSequence;

        HardwareInfo(int[] values) {
            negotiated = values[0] != 0;
            contextReady = values[1] != 0;
            contextType = values[2];
            majorVersion = values[3];
            minorVersion = values[4];
            bottomLeftOrigin = values[5] != 0;
            frameSequence = values[6];
        }
    }

    private final Bindings bindings;
    private long handle;
    private boolean lastFrameExecuted;

    public static final int PRESENT_AUTO = 0;
    public static final int PRESENT_FRONTEND_FBO = 1;
    public static final int PRESENT_DIRECT_WINDOW = 2;
    public static final int SOURCE_TIMELINE_DEFAULT = 0;
    public static final int SOURCE_TIMELINE_MUPEN_VI_ORIGIN = 1;
    // Independent bit: crops a frontend-FBO GLideN64 target's sentinel
    // padding regardless of frame-generation mode. See the native
    // lucent_retro_source_timeline_policy enum for the full rationale.
    public static final int SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS = 2;

    public ExperimentalGlesLibretroHost(File core, File trustedCoreDirectory,
                                        File systemDirectory, File saveDirectory)
            throws IOException {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory,
                PRESENT_AUTO, SOURCE_TIMELINE_DEFAULT, JniBindings.INSTANCE);
    }

    public ExperimentalGlesLibretroHost(File core, File trustedCoreDirectory,
                                        File systemDirectory, File saveDirectory,
                                        int presentationPolicy)
            throws IOException {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory,
                presentationPolicy, SOURCE_TIMELINE_DEFAULT, JniBindings.INSTANCE);
    }

    public ExperimentalGlesLibretroHost(File core, File trustedCoreDirectory,
                                        File systemDirectory, File saveDirectory,
                                        int presentationPolicy, int sourceTimelinePolicy)
            throws IOException {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory,
                presentationPolicy, sourceTimelinePolicy, true,
                JniBindings.INSTANCE);
    }

    public ExperimentalGlesLibretroHost(File core, File trustedCoreDirectory,
                                        File systemDirectory, File saveDirectory,
                                        int presentationPolicy, int sourceTimelinePolicy,
                                        boolean widescreenEnhancementsEnabled)
            throws IOException {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory,
                presentationPolicy, sourceTimelinePolicy,
                widescreenEnhancementsEnabled, JniBindings.INSTANCE);
    }

    ExperimentalGlesLibretroHost(File core, File trustedCoreDirectory,
                                 File systemDirectory, File saveDirectory,
                                 Bindings bindings) throws IOException {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory,
                PRESENT_AUTO, SOURCE_TIMELINE_DEFAULT, bindings);
    }

    ExperimentalGlesLibretroHost(File core, File trustedCoreDirectory,
                                 File systemDirectory, File saveDirectory,
                                 int presentationPolicy,
                                 Bindings bindings) throws IOException {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory,
                presentationPolicy, SOURCE_TIMELINE_DEFAULT, bindings);
    }

    ExperimentalGlesLibretroHost(File core, File trustedCoreDirectory,
                                 File systemDirectory, File saveDirectory,
                                 int presentationPolicy, int sourceTimelinePolicy,
                                 Bindings bindings) throws IOException {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory,
                presentationPolicy, sourceTimelinePolicy, true, bindings);
    }

    ExperimentalGlesLibretroHost(File core, File trustedCoreDirectory,
                                 File systemDirectory, File saveDirectory,
                                 int presentationPolicy, int sourceTimelinePolicy,
                                 boolean widescreenEnhancementsEnabled,
                                 Bindings bindings) throws IOException {
        if (core == null || trustedCoreDirectory == null || systemDirectory == null ||
                saveDirectory == null) throw new IllegalArgumentException("all paths are required");
        if (bindings == null) throw new IllegalArgumentException("bindings are required");
        if (presentationPolicy < PRESENT_AUTO ||
                presentationPolicy > PRESENT_DIRECT_WINDOW)
            throw new IllegalArgumentException("unknown presentation policy");
        if (sourceTimelinePolicy < SOURCE_TIMELINE_DEFAULT ||
                (sourceTimelinePolicy & ~(SOURCE_TIMELINE_MUPEN_VI_ORIGIN |
                        SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS)) != 0)
            throw new IllegalArgumentException("unknown source timeline policy");
        this.bindings = bindings;
        File canonicalCore = core.getCanonicalFile();
        File canonicalRoot = trustedCoreDirectory.getCanonicalFile();
        if (!canonicalCore.getPath().startsWith(canonicalRoot.getPath() + File.separator))
            throw new SecurityException("core must be in EmuFusion's app-private trusted directory");
        if (!systemDirectory.isDirectory() && !systemDirectory.mkdirs())
            throw new IOException("cannot create system directory");
        if (!saveDirectory.isDirectory() && !saveDirectory.mkdirs())
            throw new IOException("cannot create save directory");
        handle = bindings.create(canonicalCore.getPath(), canonicalRoot.getPath(),
                systemDirectory.getCanonicalPath(), saveDirectory.getCanonicalPath(),
                presentationPolicy, sourceTimelinePolicy,
                widescreenEnhancementsEnabled);
        if (handle == 0) throw new IllegalStateException("native GLES session was not created");
    }

    public synchronized void loadGame(File game) throws IOException {
        checkOpen();
        if (game == null || !game.isFile()) throw new IOException("game content does not exist");
        bindings.loadGame(handle, game.getCanonicalPath());
    }

    /**
     * Selects the controller a core emulates on a port. Loading a game resets
     * port 0 to a plain RetroPad, so a system whose device is something else
     * must set it afterwards -- Dolphin only attaches the Wii Nunchuk for
     * RETRO_DEVICE_WIIMOTE_NC, and titles that require the extension (Super
     * Mario Galaxy 2) accept no input without it. Wii and GameCube run on this
     * hardware path, so the call has to exist here as well as on the software
     * host.
     */
    public synchronized void setControllerPortDevice(int port, int device) {
        checkOpen();
        bindings.setControllerPortDevice(handle, port, device);
    }

    /**
     * Power-cycles the loaded content in place (libretro {@code retro_reset}).
     * Must run on the render-owning thread like every other call here.
     */
    public synchronized void reset() {
        checkOpen();
        bindings.reset(handle);
    }

    /** Replaces the live core's complete cheat slot set without restarting content. */
    public synchronized void applyCheats(java.util.List<String> codes) {
        checkOpen();
        bindings.cheatReset(handle);
        if (codes == null) return;
        int slot = 0;
        for (String code : codes) {
            if (code == null || code.trim().isEmpty()) continue;
            bindings.cheatSet(handle, slot++, true, code.trim());
        }
    }

    /** Sets the frontend-resolved display aspect before attaching a Surface. */
    public synchronized void setPresentationAspect(float aspect) {
        checkOpen();
        if (!Float.isFinite(aspect) || aspect <= 0.1f || aspect >= 10f)
            throw new IllegalArgumentException("a plausible presentation aspect is required");
        bindings.setPresentationAspect(handle, aspect);
    }

    public synchronized void attachSurface(Surface surface) {
        checkOpen();
        if (surface == null || !surface.isValid())
            throw new IllegalArgumentException("valid Android Surface is required");
        bindings.attach(handle, surface);
        bindings.setFgTimestamp(handle,
                FrameGenerationRendererRegistry.isFrameGenerationInput(surface));
    }

    /** Rebuilds EGL after surface replacement or EGL_CONTEXT_LOST. */
    public synchronized void recreateSurface(Surface surface) {
        checkOpen();
        if (surface == null || !surface.isValid())
            throw new IllegalArgumentException("valid Android Surface is required");
        bindings.recreate(handle, surface);
        // Native recreation detaches first, clearing the previous ownership.
        bindings.setFgTimestamp(handle,
                FrameGenerationRendererRegistry.isFrameGenerationInput(surface));
    }

    /**
     * Non-destructive presentation refresh after the same live Surface's
     * buffer geometry changed. Never rebuilds EGL and never invokes the
     * core's context_destroy/context_reset callbacks: duplicate or resize
     * notifications of one live Surface must not force hardware cores
     * through the ordered destroy/recreate transition.
     */
    public synchronized void surfaceResized() {
        checkOpen();
        bindings.resize(handle);
    }

    /** A resume warmup may skip execution; true only when a game image swapped. */
    public synchronized boolean runFrameAndPresent() {
        checkOpen();
        lastFrameExecuted = false;
        int status = bindings.runAndPresentStatus(handle);
        if (status < 0 || status > 2)
            throw new IllegalStateException("invalid GLES execution status: " + status);
        lastFrameExecuted = status != 0;
        return status == 2;
    }

    public synchronized boolean didRunFrame() { return lastFrameExecuted; }

    /** Executes a guest step into its frontend FBO without enqueueing a stale display. */
    public synchronized void runFrameWithoutPresent() {
        checkOpen();
        lastFrameExecuted = false;
        int status = bindings.runWithoutPresentStatus(handle);
        if (status < 0 || status > 1)
            throw new IllegalStateException("invalid offscreen execution status: " + status);
        lastFrameExecuted = status == 1;
    }

    public synchronized long lastRunAudioDurationNanos() {
        checkOpen();
        return lastFrameExecuted ? bindings.lastRunAudioDurationNanos(handle) : 0L;
    }

    public synchronized void detachSurface() {
        checkOpen();
        bindings.detach(handle);
    }

    public synchronized void pause() { checkOpen(); bindings.setPaused(handle, true); }
    public synchronized void resume() { checkOpen(); bindings.setPaused(handle, false); }

    public synchronized void setJoypadButton(int port, int button, boolean pressed) {
        checkOpen();
        bindings.setJoypadButton(handle, port, button, pressed);
    }

    public synchronized void setAnalogAxis(int port, int index, int id, float value) {
        checkOpen();
        if (Float.isNaN(value)) value = 0f;
        float clamped = Math.max(-1f, Math.min(1f, value));
        int signed = clamped <= -1f ? Short.MIN_VALUE :
                Math.round(clamped * Short.MAX_VALUE);
        bindings.setAnalogAxis(handle, port, index, id, signed);
    }

    /** Sets one exact libretro pointer coordinate and contact state. */
    public synchronized void setPointer(int port, short x, short y, boolean pressed) {
        checkOpen();
        bindings.setPointer(handle, port, x, y, pressed);
    }

    public synchronized HardwareInfo hardwareInfo() {
        checkOpen();
        int[] values = bindings.hardwareInfo(handle);
        if (values == null || values.length != 7)
            throw new IllegalStateException("hardware negotiation is unavailable");
        return new HardwareInfo(values);
    }

    public synchronized short[] drainAudio(int maxFrames) {
        checkOpen();
        if (maxFrames <= 0) return new short[0];
        short[] samples = bindings.drainAudio(handle, maxFrames);
        return samples == null ? new short[0] : samples;
    }

    public synchronized AvInfo avInfo() {
        checkOpen();
        double[] values = bindings.avInfo(handle);
        if (values == null || values.length != 5)
            throw new IllegalStateException("AV timing is unavailable before loading a game");
        return new AvInfo(values);
    }

    public synchronized void setSynchronizedVideoRate(
            double declaredHz, double synchronizedHz) {
        checkOpen();
        bindings.setSynchronizedVideoRate(handle, declaredHz, synchronizedHz);
    }

    public synchronized byte[] serialize() {
        checkOpen();
        byte[] state = bindings.serialize(handle);
        if (state == null || state.length == 0)
            throw new IllegalStateException("core did not serialize a usable state");
        return state;
    }

    public synchronized void unserialize(byte[] state) {
        checkOpen();
        if (state == null || state.length == 0)
            throw new IllegalArgumentException("serialized state is required");
        bindings.unserialize(handle, state);
    }

    public synchronized byte[] readSaveRam() {
        checkOpen();
        return bindings.readSaveRam(handle);
    }

    public synchronized void writeSaveRam(byte[] saveRam) {
        checkOpen();
        if (saveRam == null) throw new IllegalArgumentException("save RAM is required");
        bindings.writeSaveRam(handle, saveRam);
    }

    public synchronized boolean stateReady() {
        checkOpen();
        return bindings.stateReady(handle);
    }

    @Override public synchronized void close() {
        if (handle == 0) return;
        bindings.destroy(handle);
        handle = 0;
    }

    private void checkOpen() {
        if (handle == 0) throw new IllegalStateException("GLES core host is closed");
    }

    private static native long nativeCreateGles(String corePath, String trustedRoot,
                                                 String systemDirectory, String saveDirectory,
                                                 int presentationPolicy,
                                                 int sourceTimelinePolicy,
                                                 boolean widescreenEnhancementsEnabled);
    private static native void nativeLoadGameGles(long handle, String gamePath);
    private static native void nativeSetControllerPortDeviceGles(long handle, int port,
                                                                 int device);
    private static native void nativeResetGles(long handle);
    private static native void nativeCheatResetGles(long handle);
    private static native void nativeCheatSetGles(long handle, int index,
                                                  boolean enabled, String code);
    private static native void nativeSetPresentationAspectGles(long handle, float aspect);
    private static native void nativeSetFgTimestampGles(long handle, boolean enabled);
    private static native void nativeAttachSurfaceGles(long handle, Surface surface);
    private static native void nativeRecreateSurfaceGles(long handle, Surface surface);
    private static native void nativeResizeSurfaceGles(long handle);
    private static native int nativeRunAndPresentStatusGles(long handle);
    private static native int nativeRunWithoutPresentStatusGles(long handle);
    private static native void nativeDetachSurfaceGles(long handle);
    private static native void nativeSetPausedGles(long handle, boolean paused);
    private static native void nativeSetJoypadButtonGles(long handle, int port, int button,
                                                         boolean pressed);
    private static native void nativeSetAnalogAxisGles(long handle, int port, int index,
                                                       int id, int value);
    private static native void nativeSetPointerGles(long handle, int port, int x, int y,
                                                    boolean pressed);
    private static native int[] nativeHardwareInfoGles(long handle);
    private static native short[] nativeDrainAudioGles(long handle, int maxFrames);
    private static native double[] nativeAvInfoGles(long handle);
    private static native long nativeLastRunAudioDurationNanosGles(long handle);
    private static native void nativeSetSynchronizedVideoRateGles(
            long handle, double declaredHz, double synchronizedHz);
    private static native boolean nativeStateReadyGles(long handle);
    private static native byte[] nativeSerializeGles(long handle);
    private static native void nativeUnserializeGles(long handle, byte[] state);
    private static native byte[] nativeReadSaveRamGles(long handle);
    private static native void nativeWriteSaveRamGles(long handle, byte[] saveRam);
    private static native void nativeDestroyGles(long handle);
}
