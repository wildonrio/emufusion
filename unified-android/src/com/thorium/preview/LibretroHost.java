package com.thorium.preview;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.concurrent.TimeUnit;

/**
 * Lifecycle-safe Java boundary for EmuFusion's independent libretro API host.
 *
 * Core binaries are never downloaded by this class. The caller must pass a
 * core under the app-private trusted directory after EngineRegistry has
 * approved its exact source/build identity.
 */
public final class LibretroHost implements Closeable {
    private static final int MAX_VIDEO_DIMENSION = 8192;
    private static final long MAX_VIDEO_BYTES = 128L * 1024L * 1024L;
    private static final int VIDEO_BUFFER_POOL_SIZE = 3;
    public static final class VideoFrame {
        public int width;
        public int height;
        public int pitch;
        public int pixelFormat;
        public int sequence;
        public int byteSize;
        public byte[] pixels;
        /** Scheduled core-clock due time (System.nanoTime domain) or zero. */
        public long producerTimestampNs;

        private final LibretroHost owner;
        private boolean leased;

        private VideoFrame(LibretroHost owner) {
            this.owner = owner;
        }

        private void acquire(int[] info, int byteSize) {
            width = info[0];
            height = info[1];
            pitch = info[2];
            pixelFormat = info[3];
            this.byteSize = byteSize;
            sequence = info[5];
            producerTimestampNs = 0L;
            if (pixels == null || pixels.length < byteSize)
                pixels = new byte[reusableVideoCapacity(byteSize)];
            leased = true;
        }

        /** Returns this immutable-for-the-lease frame to the bounded pool. */
        public void release() {
            owner.recycleVideoFrame(this);
        }
    }

    public static final class AvInfo {
        public final double framesPerSecond;
        public final double sampleRate;
        public final float aspectRatio;
        public final int baseWidth;
        public final int baseHeight;

        AvInfo(double[] info) {
            framesPerSecond = info[0];
            sampleRate = info[1];
            aspectRatio = (float)info[2];
            baseWidth = (int)info[3];
            baseHeight = (int)info[4];
        }
    }

    static {
        System.loadLibrary("lucent_libretro_host");
    }

    // Volatile: checkOpen() is also read by the unsynchronized input setters.
    private volatile long handle;
    private final PendingHostInput pendingInput = new PendingHostInput();
    private final PendingHostInput.Sink nativeInput = new PendingHostInput.Sink() {
        @Override public void joypadButton(int port, int button, boolean pressed) {
            nativeSetJoypadButton(handle, port, button, pressed);
        }
        @Override public void analogAxis(int port, int index, int id, int value) {
            nativeSetAnalogAxis(handle, port, index, id, value);
        }
        @Override public void pointer(int port, int x, int y, boolean pressed) {
            nativeSetPointer(handle, port, x, y, pressed);
        }
        @Override public void paused(boolean paused) {
            nativeSetPaused(handle, paused);
        }
    };
    private final Object frameBoundary = new Object();
    private boolean frameRunning;
    private final int[] videoInfoScratch = new int[6];
    private final ArrayDeque<VideoFrame> availableVideoFrames = new ArrayDeque<>();
    private long videoBufferAllocations;
    private long videoPoolExhaustions;

    /**
     * Keep one bounded capacity per owned frame instead of reallocating all
     * three buffers whenever a core changes video mode. PS1 titles commonly
     * alternate between several smaller geometries during normal gameplay;
     * exact-size arrays turned each transition into a stop-the-world burst.
     */
    private static int reusableVideoCapacity(int requiredBytes) {
        int capacity = 64 * 1024;
        while (capacity < requiredBytes && capacity < MAX_VIDEO_BYTES)
            capacity <<= 1;
        return Math.max(requiredBytes, capacity);
    }

    public LibretroHost(File core, File trustedCoreDirectory, File systemDirectory,
                        File saveDirectory) throws IOException {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory, true);
    }

    public LibretroHost(File core, File trustedCoreDirectory, File systemDirectory,
                        File saveDirectory,
                        boolean widescreenEnhancementsEnabled) throws IOException {
        if (core == null || trustedCoreDirectory == null || systemDirectory == null ||
                saveDirectory == null) throw new IllegalArgumentException("all paths are required");
        File canonicalCore = core.getCanonicalFile();
        File canonicalRoot = trustedCoreDirectory.getCanonicalFile();
        if (!isInside(canonicalCore, canonicalRoot))
            throw new SecurityException("core must be in EmuFusion's app-private trusted directory");
        if (!systemDirectory.isDirectory() && !systemDirectory.mkdirs())
            throw new IOException("cannot create system directory");
        if (!saveDirectory.isDirectory() && !saveDirectory.mkdirs())
            throw new IOException("cannot create save directory");
        handle = nativeCreate(canonicalCore.getPath(), canonicalRoot.getPath(),
                systemDirectory.getCanonicalPath(), saveDirectory.getCanonicalPath(),
                widescreenEnhancementsEnabled);
        for (int index = 0; index < VIDEO_BUFFER_POOL_SIZE; index++)
            availableVideoFrames.addLast(new VideoFrame(this));
    }

    public synchronized void loadGame(File game) throws IOException {
        checkOpen();
        if (game == null || !game.isFile()) throw new IOException("game content does not exist");
        nativeLoadGame(handle, game.getCanonicalPath());
    }

    /**
     * Selects the controller a core emulates on a port. Loading a game resets
     * port 0 to a plain RetroPad, so a system whose device is something else
     * must set it afterwards -- Dolphin only attaches a Wii Nunchuk for
     * RETRO_DEVICE_WIIMOTE_NC, and games that require the extension refuse
     * input without it.
     */
    public synchronized void setControllerPortDevice(int port, int device) {
        checkOpen();
        nativeSetControllerPortDevice(handle, port, device);
    }

    /**
     * Power-cycles the loaded content in place (libretro {@code retro_reset}).
     * Unlike an unload/load pair this keeps the core's battery-backed save RAM
     * in memory, so a reset behaves like the console's reset button rather
     * than pulling the cartridge.
     */
    public synchronized void reset() {
        checkOpen();
        nativeReset(handle);
    }

    /**
     * Applies an ordered set of cheat codes, replacing whatever the core held.
     *
     * <p>Always the whole enabled set, never a single toggle: libretro has no
     * "remove one cheat" call, and slot numbers are positional, so turning one
     * cheat off means clearing and re-applying the rest. Codes go to the core
     * verbatim because only it knows its own dialect (Game Genie, raw
     * address:value, multi-line joined with '+').
     *
     * @param codes enabled codes in display order; empty clears all cheats
     */
    public synchronized void applyCheats(java.util.List<String> codes) {
        checkOpen();
        nativeCheatReset(handle);
        if (codes == null) return;
        int slot = 0;
        for (String code : codes) {
            if (code == null || code.trim().isEmpty()) continue;
            nativeCheatSet(handle, slot++, true, code.trim());
        }
    }

    /**
     * Unloads the active game. Cores with a EmuFusion exit-persistence extension
     * may reject this call; in that case the host and game remain open.
     */
    public synchronized void unloadGame() {
        checkOpen();
        nativeUnloadGame(handle);
    }

    public synchronized void runFrame() {
        checkOpen();
        pendingInput.applyTo(nativeInput);
        synchronized (frameBoundary) { frameRunning = true; }
        try {
            nativeRunFrame(handle);
        } finally {
            synchronized (frameBoundary) {
                frameRunning = false;
                frameBoundary.notifyAll();
            }
        }
    }

    /*
     * Pause, resume and the input setters below are called from the UI thread.
     * They only record the request; runFrame applies it before the next
     * retro_run. Taking this monitor here instead waited for the frame in
     * progress, so a slow or wedged core blocked touch dispatch into an ANR
     * and kept the pause menu from opening. A paused request still stops the
     * very next frame: runFrame applies it before calling into the core.
     */
    public void pause() {
        checkOpen();
        pendingInput.setPaused(true);
    }

    public void resume() {
        checkOpen();
        pendingInput.setPaused(false);
    }

    /**
     * Waits up to {@code timeoutMillis} for a retro_run already in progress to
     * return. pause() no longer blocks on the frame; callers that must not
     * proceed while the core is still running a frame wait here, bounded, and
     * take their fail-closed path on false.
     */
    public boolean awaitFrameBoundary(long timeoutMillis) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis);
        synchronized (frameBoundary) {
            while (frameRunning) {
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0L) return false;
                TimeUnit.NANOSECONDS.timedWait(frameBoundary, remaining);
            }
            return true;
        }
    }

    /** Uses libretro joypad IDs 0..15 after EmuFusion's canonical mapping. */
    public void setJoypadButton(int port, int retroJoypadId, boolean pressed) {
        checkOpen();
        pendingInput.setJoypadButton(port, retroJoypadId, pressed);
    }

    /**
     * Sets one standard libretro analog axis from an Android-style normalized
     * value. Index 0 is the left stick, 1 is the right stick; IDs 0/1 are X/Y.
     */
    public void setAnalogAxis(int port, int retroAnalogIndex,
                              int retroAnalogId, float normalizedValue) {
        checkOpen();
        if (Float.isNaN(normalizedValue)) normalizedValue = 0f;
        float clamped = Math.max(-1f, Math.min(1f, normalizedValue));
        int signedValue = clamped <= -1f ? Short.MIN_VALUE
                : Math.round(clamped * Short.MAX_VALUE);
        pendingInput.setAnalogAxis(port, retroAnalogIndex, retroAnalogId, signedValue);
    }

    /** Sets an exact signed libretro axis value for tests and specialized input. */
    public void setAnalogAxisRaw(int port, int retroAnalogIndex,
                                 int retroAnalogId, short value) {
        checkOpen();
        pendingInput.setAnalogAxis(port, retroAnalogIndex, retroAnalogId, value);
    }

    /** Sets one standard libretro pointer coordinate and contact state. */
    public void setPointer(int port, short x, short y, boolean pressed) {
        checkOpen();
        pendingInput.setPointer(port, x, y, pressed);
    }

    /**
     * Returns the newest tightly-copied software frame, or null before first
     * video or while all three bounded buffers are owned by presentation.
     * Callers must release every non-null frame exactly once. After geometry
     * warm-up this path allocates neither a frame-sized Java array nor a native
     * staging buffer on each core callback.
     */
    public synchronized VideoFrame latestVideoFrame() {
        checkOpen();
        if (!nativeReadVideoInfo(handle, videoInfoScratch)) return null;
        long width = videoInfoScratch[0];
        long height = videoInfoScratch[1];
        long pitch = videoInfoScratch[2];
        long byteSize = videoInfoScratch[4];
        int bytesPerPixel = videoInfoScratch[3] == 1 ? 4 : 2;
        if (videoInfoScratch[3] < 0 || videoInfoScratch[3] > 2 ||
                width < 1 || height < 1 ||
                width > MAX_VIDEO_DIMENSION || height > MAX_VIDEO_DIMENSION ||
                pitch < width * bytesPerPixel || byteSize != pitch * height ||
                byteSize < 1 || byteSize > MAX_VIDEO_BYTES) return null;
        VideoFrame frame = availableVideoFrames.pollFirst();
        if (frame == null) {
            videoPoolExhaustions++;
            return null;
        }
        boolean needsAllocation = frame.pixels == null ||
                frame.pixels.length < videoInfoScratch[4];
        frame.acquire(videoInfoScratch, videoInfoScratch[4]);
        if (needsAllocation) videoBufferAllocations++;
        if (!nativeCopyVideoFrameInto(handle, frame.pixels)) {
            recycleVideoFrame(frame);
            return null;
        }
        return frame;
    }

    public synchronized long videoBufferAllocationCount() {
        return videoBufferAllocations;
    }

    public synchronized long videoPoolExhaustionCount() {
        return videoPoolExhaustions;
    }

    private synchronized void recycleVideoFrame(VideoFrame frame) {
        if (frame == null || frame.owner != this || !frame.leased) return;
        frame.leased = false;
        availableVideoFrames.addLast(frame);
    }

    /** Returns interleaved signed 16-bit stereo PCM, up to maxFrames. */
    public synchronized short[] drainAudio(int maxFrames) {
        checkOpen();
        if (maxFrames <= 0) throw new IllegalArgumentException("maxFrames must be positive");
        return nativeDrainAudio(handle, maxFrames);
    }

    public synchronized AvInfo avInfo() {
        checkOpen();
        double[] info = nativeAvInfo(handle);
        if (info == null || info.length != 5)
            throw new IllegalStateException("AV timing is unavailable before loading a game");
        return new AvInfo(info);
    }

    /** Keeps PCM duration aligned when a near-standard core clock is paced at
     * an exact physical-display divisor. */
    public synchronized void setSynchronizedVideoRate(
            double declaredHz, double synchronizedHz) {
        checkOpen();
        nativeSetSynchronizedVideoRate(handle, declaredHz, synchronizedHz);
    }

    public synchronized byte[] serialize() {
        checkOpen();
        return nativeSerialize(handle);
    }

    public synchronized void unserialize(byte[] state) {
        checkOpen();
        if (state == null || state.length == 0)
            throw new IllegalArgumentException("serialized state is required");
        nativeUnserialize(handle, state);
    }

    public synchronized String libraryName() {
        checkOpen();
        return nativeLibraryName(handle);
    }

    public synchronized String libraryVersion() {
        checkOpen();
        return nativeLibraryVersion(handle);
    }

    /** Returns a snapshot suitable for atomic persistence, or null when absent. */
    public synchronized byte[] readSaveRam() {
        checkOpen();
        return nativeReadSaveRam(handle);
    }

    public synchronized void writeSaveRam(byte[] saveRam) {
        checkOpen();
        if (saveRam == null) throw new IllegalArgumentException("save RAM is required");
        nativeWriteSaveRam(handle, saveRam);
    }

    @Override public synchronized void close() {
        if (handle == 0) return;
        nativeDestroy(handle);
        handle = 0;
    }

    private void checkOpen() {
        if (handle == 0) throw new IllegalStateException("core host is closed");
    }

    private static boolean isInside(File file, File directory) {
        String path = file.getPath();
        String root = directory.getPath();
        return path.startsWith(root + File.separator);
    }

    private static native long nativeCreate(String corePath, String trustedRoot,
                                            String systemDirectory, String saveDirectory,
                                            boolean widescreenEnhancementsEnabled);
    private static native void nativeLoadGame(long handle, String gamePath);
    private static native void nativeSetControllerPortDevice(
            long handle, int port, int device);
    private static native void nativeReset(long handle);
    private static native void nativeCheatReset(long handle);
    private static native void nativeCheatSet(long handle, int index, boolean enabled,
                                              String code);
    private static native void nativeUnloadGame(long handle);
    private static native void nativeRunFrame(long handle);
    private static native void nativeSetPaused(long handle, boolean paused);
    private static native void nativeSetJoypadButton(long handle, int port, int button,
                                                     boolean pressed);
    private static native void nativeSetAnalogAxis(long handle, int port, int index,
                                                   int id, int value);
    private static native void nativeSetPointer(long handle, int port, int x, int y,
                                                boolean pressed);
    private static native boolean nativeReadVideoInfo(long handle, int[] result);
    private static native boolean nativeCopyVideoFrameInto(long handle, byte[] destination);
    private static native short[] nativeDrainAudio(long handle, int maxFrames);
    private static native double[] nativeAvInfo(long handle);
    private static native void nativeSetSynchronizedVideoRate(
            long handle, double declaredHz, double synchronizedHz);
    private static native byte[] nativeSerialize(long handle);
    private static native void nativeUnserialize(long handle, byte[] state);
    private static native String nativeLibraryName(long handle);
    private static native String nativeLibraryVersion(long handle);
    private static native byte[] nativeReadSaveRam(long handle);
    private static native void nativeWriteSaveRam(long handle, byte[] saveRam);
    private static native void nativeDestroy(long handle);
}
