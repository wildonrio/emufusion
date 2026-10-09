package com.thorium.preview;

import android.os.Build;
import android.view.Surface;
import com.thorium.preview.game.FrameGenerationRendererRegistry;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;

/** Android Vulkan hardware-render libretro bridge owned entirely by EmuFusion. */
public final class ExperimentalVulkanLibretroHost implements Closeable {
    static {
        if (Build.VERSION.SDK_INT >= 24) System.loadLibrary("lucent_vulkan_host");
    }

    private long handle;

    public ExperimentalVulkanLibretroHost(File core, File trustedCoreDirectory,
                                          File systemDirectory,
                                          File saveDirectory) throws IOException {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory, true);
    }

    public ExperimentalVulkanLibretroHost(File core, File trustedCoreDirectory,
                                          File systemDirectory,
                                          File saveDirectory,
                                          boolean widescreenEnhancementsEnabled)
            throws IOException {
        if (Build.VERSION.SDK_INT < 24)
            throw new UnsupportedOperationException("Vulkan requires Android 7.0+");
        if (core == null || trustedCoreDirectory == null ||
                systemDirectory == null || saveDirectory == null)
            throw new IllegalArgumentException("all paths are required");
        File canonicalCore = core.getCanonicalFile();
        File canonicalRoot = trustedCoreDirectory.getCanonicalFile();
        if (!canonicalCore.getPath().startsWith(
                canonicalRoot.getPath() + File.separator))
            throw new SecurityException(
                    "core must be in EmuFusion's app-private trusted directory");
        if (!systemDirectory.isDirectory() && !systemDirectory.mkdirs())
            throw new IOException("cannot create system directory");
        if (!saveDirectory.isDirectory() && !saveDirectory.mkdirs())
            throw new IOException("cannot create save directory");
        handle = nativeCreateVulkan(canonicalCore.getPath(),
                canonicalRoot.getPath(), systemDirectory.getCanonicalPath(),
                saveDirectory.getCanonicalPath(), widescreenEnhancementsEnabled);
        if (handle == 0)
            throw new IllegalStateException("native Vulkan session was not created");
    }

    public synchronized void loadGame(File game) throws IOException {
        checkOpen();
        if (game == null || !game.isFile())
            throw new IOException("game content does not exist");
        nativeLoadGameVulkan(handle, game.getCanonicalPath());
    }

    /** Sets the frontend-resolved display aspect before attaching a Surface. */
    public synchronized void setPresentationAspect(float aspect) {
        checkOpen();
        if (!Float.isFinite(aspect) || aspect <= 0.1f || aspect >= 10f)
            throw new IllegalArgumentException("a plausible presentation aspect is required");
        nativeSetPresentationAspectVulkan(handle, aspect);
    }

    public synchronized void setSecondaryPresentationRotation(int clockwiseDegrees) {
        checkOpen();
        if (clockwiseDegrees != 0 && clockwiseDegrees != 90)
            throw new IllegalArgumentException(
                    "secondary rotation must be 0 or 90 degrees clockwise");
        nativeSetSecondaryPresentationRotationVulkan(handle, clockwiseDegrees);
    }

    public synchronized void attachSurface(Surface surface) {
        checkSurface(surface);
        configureFgTimestamp(surface, false);
        nativeAttachSurfaceVulkan(handle, surface);
    }

    public synchronized void recreateSurface(Surface surface) {
        checkSurface(surface);
        configureFgTimestamp(surface, false);
        nativeRecreateSurfaceVulkan(handle, surface);
    }

    public synchronized boolean runFrameAndPresent() {
        checkOpen();
        return nativeRunAndPresentVulkan(handle);
    }

    public synchronized void detachSurface() {
        checkOpen();
        nativeDetachSurfaceVulkan(handle);
        configureFgTimestamp(null, false);
    }

    public synchronized void attachSecondarySurface(Surface surface) {
        checkSurface(surface);
        configureFgTimestamp(surface, true);
        nativeAttachSecondarySurfaceVulkan(handle, surface);
    }

    public synchronized void detachSecondarySurface() {
        checkOpen();
        nativeDetachSecondarySurfaceVulkan(handle);
        configureFgTimestamp(null, true);
    }

    private void configureFgTimestamp(Surface surface, boolean secondary) {
        nativeSetFgTimestampVulkan(handle, secondary,
                FrameGenerationRendererRegistry.isFrameGenerationInput(surface));
    }

    public synchronized void pause() {
        checkOpen();
        nativeSetPausedVulkan(handle, true);
    }

    public synchronized void resume() {
        checkOpen();
        nativeSetPausedVulkan(handle, false);
    }

    public synchronized void setJoypadButton(int port, int button,
                                              boolean pressed) {
        checkOpen();
        nativeSetJoypadButtonVulkan(handle, port, button, pressed);
    }

    public synchronized void setAnalogAxis(int port, int index, int id,
                                            float value) {
        checkOpen();
        if (Float.isNaN(value)) value = 0f;
        float clamped = Math.max(-1f, Math.min(1f, value));
        int signed = clamped <= -1f ? Short.MIN_VALUE :
                Math.round(clamped * Short.MAX_VALUE);
        nativeSetAnalogAxisVulkan(handle, port, index, id, signed);
    }

    public synchronized void setPointer(int port, short x, short y,
                                        boolean pressed) {
        checkOpen();
        nativeSetPointerVulkan(handle, port, x, y, pressed);
    }

    public synchronized void setControllerPortDevice(int port, int device) {
        checkOpen();
        nativeSetControllerPortDeviceVulkan(handle, port, device);
    }

    /** Resets the loaded game without replacing its Vulkan context or saves. */
    public synchronized void reset() {
        checkOpen();
        nativeResetVulkan(handle);
    }

    /** Replaces all live cheat slots, including clearing an empty selection. */
    public synchronized void applyCheats(java.util.List<String> codes) {
        checkOpen();
        nativeCheatResetVulkan(handle);
        if (codes == null) return;
        int slot = 0;
        for (String code : codes) {
            if (code == null || code.trim().isEmpty()) continue;
            nativeCheatSetVulkan(handle, slot++, true, code.trim());
        }
    }

    public synchronized short[] drainAudio(int maxFrames) {
        checkOpen();
        if (maxFrames <= 0) return new short[0];
        short[] samples = nativeDrainAudioVulkan(handle, maxFrames);
        return samples == null ? new short[0] : samples;
    }

    public synchronized ExperimentalGlesLibretroHost.AvInfo avInfo() {
        checkOpen();
        double[] values = nativeAvInfoVulkan(handle);
        if (values == null || values.length != 5)
            throw new IllegalStateException("AV timing is unavailable");
        return new ExperimentalGlesLibretroHost.AvInfo(values);
    }

    public synchronized void setSynchronizedVideoRate(
            double declaredHz, double synchronizedHz) {
        checkOpen();
        nativeSetSynchronizedVideoRateVulkan(
                handle, declaredHz, synchronizedHz);
    }

    public synchronized byte[] serialize() {
        checkOpen();
        byte[] state = nativeSerializeVulkan(handle);
        if (state == null || state.length == 0)
            throw new IllegalStateException("core did not serialize a usable state");
        return state;
    }

    public synchronized boolean stateReady() {
        checkOpen();
        return nativeStateReadyVulkan(handle);
    }

    public synchronized void unserialize(byte[] state) {
        checkOpen();
        if (state == null || state.length == 0)
            throw new IllegalArgumentException("serialized state is required");
        nativeUnserializeVulkan(handle, state);
    }

    public synchronized byte[] readSaveRam() {
        checkOpen();
        return nativeReadSaveRamVulkan(handle);
    }

    public synchronized void writeSaveRam(byte[] saveRam) {
        checkOpen();
        if (saveRam == null) throw new IllegalArgumentException("save RAM is required");
        nativeWriteSaveRamVulkan(handle, saveRam);
    }

    @Override public synchronized void close() {
        if (handle == 0) return;
        long active = handle;
        handle = 0;
        nativeDestroyVulkan(active);
    }

    private void checkOpen() {
        if (handle == 0) throw new IllegalStateException("Vulkan host is closed");
    }

    private void checkSurface(Surface surface) {
        checkOpen();
        if (surface == null || !surface.isValid())
            throw new IllegalArgumentException("valid Android Surface is required");
    }

    private static native long nativeCreateVulkan(
            String core, String root, String system, String save,
            boolean widescreenEnhancementsEnabled);
    private static native void nativeLoadGameVulkan(long handle, String game);
    private static native void nativeSetPresentationAspectVulkan(
            long handle, float aspect);
    private static native void nativeSetSecondaryPresentationRotationVulkan(
            long handle, int clockwiseDegrees);
    private static native void nativeAttachSurfaceVulkan(long handle, Surface surface);
    private static native void nativeSetFgTimestampVulkan(
            long handle, boolean secondary, boolean enabled);
    private static native void nativeRecreateSurfaceVulkan(long handle, Surface surface);
    private static native boolean nativeRunAndPresentVulkan(long handle);
    private static native void nativeDetachSurfaceVulkan(long handle);
    private static native void nativeAttachSecondarySurfaceVulkan(
            long handle, Surface surface);
    private static native void nativeDetachSecondarySurfaceVulkan(long handle);
    private static native void nativeSetPausedVulkan(long handle, boolean paused);
    private static native void nativeSetJoypadButtonVulkan(
            long handle, int port, int button, boolean pressed);
    private static native void nativeSetAnalogAxisVulkan(
            long handle, int port, int index, int id, int value);
    private static native void nativeSetPointerVulkan(
            long handle, int port, int x, int y, boolean pressed);
    private static native void nativeSetControllerPortDeviceVulkan(
            long handle, int port, int device);
    private static native void nativeCheatResetVulkan(long handle);
    private static native void nativeResetVulkan(long handle);
    private static native void nativeCheatSetVulkan(
            long handle, int index, boolean enabled, String code);
    private static native short[] nativeDrainAudioVulkan(long handle, int maxFrames);
    private static native double[] nativeAvInfoVulkan(long handle);
    private static native void nativeSetSynchronizedVideoRateVulkan(
            long handle, double declaredHz, double synchronizedHz);
    private static native byte[] nativeSerializeVulkan(long handle);
    private static native boolean nativeStateReadyVulkan(long handle);
    private static native void nativeUnserializeVulkan(long handle, byte[] state);
    private static native byte[] nativeReadSaveRamVulkan(long handle);
    private static native void nativeWriteSaveRamVulkan(long handle, byte[] saveRam);
    private static native void nativeDestroyVulkan(long handle);
}
