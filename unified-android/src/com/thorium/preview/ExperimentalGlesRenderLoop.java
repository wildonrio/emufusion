package com.thorium.preview;

import android.util.Log;
import android.view.Surface;

import com.thorium.lucent.timing.DisplaySyncPolicy;
import com.thorium.preview.game.FrameGenerationRendererRegistry;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.FutureTask;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.Callable;

/**
 * Qualification-only render-thread owner for the experimental GLES bridge.
 * It has no production catalog or EngineSession route.
 */
public final class ExperimentalGlesRenderLoop implements Closeable {
    private static final String TAG = "LucentGlesLoop";

    public interface Listener {
        void onReady();
        void onFramePresented();
        default void onFrameExecutedWithoutPresentation() {}
        void onContextLost();
        void onError(Throwable failure);
    }

    /** Optional display ticks only; owns no Surface, renderer or guest state. */
    public interface DisplayClock {
        void configure(double declaredHz, double sourceHz, boolean enabled);
        long awaitDueTimeNs() throws InterruptedException;
        double measuredSourceHz();
        void suspend();
        void close();
    }

    interface Host extends Closeable {
        void attach(Surface surface);
        void recreate(Surface surface);
        /**
         * Refreshes presentation for the named live Surface's new buffer
         * geometry. Implementations must keep Surface identity: a resize
         * never pays the ordered destroy/recreate price.
         */
        void resize(Surface surface);
        boolean runAndPresent();
        default boolean supportsPresentationRecovery() { return false; }
        /** Recover bounded clock debt while still presenting every guest frame. */
        default boolean retainsFrameDebt() { return false; }
        default void runWithoutPresent() {
            throw new UnsupportedOperationException("presentation recovery unavailable");
        }
        default boolean didRunFrame() { return true; }
        default boolean usesAudioPacing() { return false; }
        default long lastRunAudioDurationNanos() { return 0L; }
        void detach();
        void attachSecondary(Surface surface);
        void detachSecondary();
        void pause();
        void resume();
        void setJoypadButton(int port, int button, boolean pressed);
        void setAnalogAxis(int port, int index, int id, float value);
        void setPointer(int port, short x, short y, boolean pressed);
        void setControllerPortDevice(int port, int device);
        void reset();
        void applyCheats(java.util.List<String> codes);
        short[] drainAudio(int maxFrames);
        ExperimentalGlesLibretroHost.AvInfo avInfo();
        default void setSynchronizedVideoRate(
                double declaredHz, double synchronizedHz) {
            if (Math.abs(declaredHz - synchronizedHz) > 1.0e-9)
                throw new UnsupportedOperationException(
                        "synchronized video rate is unsupported by this host");
        }
        void setPresentationAspect(float aspect);
        void setSecondaryPresentationRotation(int clockwiseDegrees);
        boolean stateReady();
        byte[] serialize();
        void unserialize(byte[] state);
        byte[] readSaveRam();
        void writeSaveRam(byte[] saveRam);
    }

    interface HostFactory {
        Host createAndLoad() throws Exception;
    }

    private static final long DEFAULT_FRAME_DELAY_NANOS = 1_000_000_000L / 60L;
    // UI-thread destroy callbacks release their Surface the moment they
    // return; the native detach must finish first, but may never stall the
    // UI thread longer than this bound.
    private static final long SURFACE_DETACH_WAIT_MILLIS = 250L;

    private final ScheduledExecutorService executor;
    private final HostFactory factory;
    private final Listener listener;
    private final boolean useCoreCadence;
    private volatile long frameDelayNanos;
    // Frame-generation tier pacing (protocol 2026-09-01): exact clock the
    // core is paced at (0 = its synchronized clock) plus the work-time ring
    // the host uses to prove headroom before lifting a pace.
    private volatile double declaredCoreHz;
    private volatile double synchronizedCoreHz;
    private volatile double pacedCoreHz;
    private static final int WORK_RING_SECONDS = 15;
    private final long[] workWorstNsRing = new long[WORK_RING_SECONDS];
    private int workRingFilled;
    private int workRingIndex;
    private long workSecondStartNs;
    private long workSecondWorstNs;
    private int workSecondFrames;
    private volatile double achievedCoreHzSnapshot;
    private volatile double frameWorkCapacityHzSnapshot;
    private volatile boolean closed;
    private volatile Thread renderThread;
    private final Object closeLock = new Object();
    private final java.util.List<Runnable> closeCallbacks = new java.util.ArrayList<>();
    private boolean teardownCompleted;
    // A close request is not proof that native teardown returned. In particular,
    // a caller timing out must leave this owner-thread task running, not cancel it.
    private final FutureTask<Void> closeTask = new FutureTask<Void>(() -> {
        teardown();
        return null;
    }) {
        @Override protected void done() {
            try { get(); }
            catch (Throwable failure) {
                reportError(failure);
                return; // A failed native close never authorizes process teardown.
            }
            java.util.List<Runnable> callbacks;
            synchronized (closeLock) {
                teardownCompleted = true;
                callbacks = new java.util.ArrayList<>(closeCallbacks);
                closeCallbacks.clear();
            }
            for (Runnable callback : callbacks) {
                try { callback.run(); }
                catch (Throwable failure) { reportError(failure); }
            }
        }
    };

    /* Render-thread state. */
    private Host host;
    private boolean ready;
    private boolean resumeRequested;
    private boolean surfaceAttached;
    /** Identity of the Surface that currently owns GL presentation state. */
    private Surface attachedSurface;
    /**
     * Deterministic lifecycle generation: bumped on every accepted attach,
     * replacement, duplicate absorption, and detach so physical logs can
     * prove which Surface identity each EGL/context transition belonged to.
     */
    private long surfaceGeneration;
    private Surface secondarySurface;
    private boolean secondarySurfaceAttached;
    private boolean awaitingRecreate;
    private boolean frameScheduled;
    private long nextFrameDeadlineNanos;
    private boolean audioPaced;
    private boolean hasPresentedSinceClockReset;
    private int consecutiveRecoverySteps;
    private DisplayClock displayClock;
    private boolean displayClockWasActive;
    private double displayAudioClockHz;
    private long displayAudioClockUpdatedNs;

    /** Transfers the ticker's lifetime to this render owner, including failure cleanup. */
    public void setDisplayClock(DisplayClock clock) {
        if (clock == null) throw new IllegalArgumentException("display clock required");
        try {
            call(() -> {
                if (displayClock != null)
                    throw new IllegalStateException("display clock already installed");
                displayClock = clock;
                return null;
            });
        } catch (RuntimeException | Error failure) {
            clock.close();
            throw failure;
        }
    }

    public ExperimentalGlesRenderLoop(
            File core, File trustedCoreDirectory, File systemDirectory,
            File saveDirectory, File game, Listener listener) {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory, game,
                ExperimentalGlesLibretroHost.PRESENT_AUTO, listener);
    }

    public ExperimentalGlesRenderLoop(
            File core, File trustedCoreDirectory, File systemDirectory,
            File saveDirectory, File game, int presentationPolicy,
            Listener listener) {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory, game,
                presentationPolicy,
                ExperimentalGlesLibretroHost.SOURCE_TIMELINE_DEFAULT,
                listener);
    }

    public ExperimentalGlesRenderLoop(
            File core, File trustedCoreDirectory, File systemDirectory,
            File saveDirectory, File game, int presentationPolicy,
            int sourceTimelinePolicy, Listener listener) {
        this(core, trustedCoreDirectory, systemDirectory, saveDirectory, game,
                presentationPolicy, sourceTimelinePolicy, true, listener);
    }

    public ExperimentalGlesRenderLoop(
            File core, File trustedCoreDirectory, File systemDirectory,
            File saveDirectory, File game, int presentationPolicy,
            int sourceTimelinePolicy, boolean widescreenEnhancementsEnabled,
            Listener listener) {
        this(() -> {
            final ExperimentalGlesLibretroHost nativeHost =
                    new ExperimentalGlesLibretroHost(core, trustedCoreDirectory,
                            systemDirectory, saveDirectory, presentationPolicy,
                            sourceTimelinePolicy, widescreenEnhancementsEnabled);
            try {
                nativeHost.loadGame(game);
            } catch (IOException | RuntimeException | Error failure) {
                nativeHost.close();
                throw failure;
            }
            return new Host() {
                @Override public void attach(Surface surface) {
                    nativeHost.attachSurface(surface);
                }
                @Override public void recreate(Surface surface) {
                    nativeHost.recreateSurface(surface);
                }
                @Override public void resize(Surface surface) {
                    nativeHost.surfaceResized();
                }
                @Override public boolean runAndPresent() {
                    return nativeHost.runFrameAndPresent();
                }
                @Override public boolean supportsPresentationRecovery() {
                    // Qualified separately: never silently change another core,
                    // direct-window renderer, Vulkan path or FG source stream.
                    return "liblucent_core_ppsspp.so".equals(core.getName()) &&
                            presentationPolicy == ExperimentalGlesLibretroHost.PRESENT_FRONTEND_FBO;
                }
                @Override public void runWithoutPresent() {
                    nativeHost.runFrameWithoutPresent();
                }
                @Override public boolean didRunFrame() {
                    return nativeHost.didRunFrame();
                }
                @Override public boolean usesAudioPacing() {
                    return "liblucent_core_flycast.so".equals(core.getName());
                }
                @Override public long lastRunAudioDurationNanos() {
                    return nativeHost.lastRunAudioDurationNanos();
                }
                @Override public void detach() { nativeHost.detachSurface(); }
                @Override public void attachSecondary(Surface surface) {
                    throw new UnsupportedOperationException(
                            "secondary hardware surface requires Vulkan");
                }
                @Override public void detachSecondary() {}
                @Override public void pause() { nativeHost.pause(); }
                @Override public void resume() { nativeHost.resume(); }
                @Override public void setJoypadButton(int port, int button,
                                                      boolean pressed) {
                    nativeHost.setJoypadButton(port, button, pressed);
                }
                @Override public void setAnalogAxis(int port, int index, int id,
                                                    float value) {
                    nativeHost.setAnalogAxis(port, index, id, value);
                }
                @Override public void setPointer(int port, short x, short y,
                                                 boolean pressed) {
                    nativeHost.setPointer(port, x, y, pressed);
                }
                @Override public void setControllerPortDevice(int port, int device) {
                    nativeHost.setControllerPortDevice(port, device);
                }
                @Override public void reset() { nativeHost.reset(); }
                @Override public void applyCheats(java.util.List<String> codes) {
                    nativeHost.applyCheats(codes);
                }
                @Override public short[] drainAudio(int maxFrames) {
                    return nativeHost.drainAudio(maxFrames);
                }
                @Override public ExperimentalGlesLibretroHost.AvInfo avInfo() {
                    return nativeHost.avInfo();
                }
                @Override public void setSynchronizedVideoRate(
                        double declaredHz, double synchronizedHz) {
                    nativeHost.setSynchronizedVideoRate(
                            declaredHz, synchronizedHz);
                }
                @Override public void setPresentationAspect(float aspect) {
                    nativeHost.setPresentationAspect(aspect);
                }
                @Override public void setSecondaryPresentationRotation(
                        int clockwiseDegrees) {
                    if (clockwiseDegrees != 0)
                        throw new UnsupportedOperationException(
                                "secondary rotation requires Vulkan");
                }
                @Override public boolean stateReady() { return nativeHost.stateReady(); }
                @Override public byte[] serialize() { return nativeHost.serialize(); }
                @Override public void unserialize(byte[] state) {
                    nativeHost.unserialize(state);
                }
                @Override public byte[] readSaveRam() { return nativeHost.readSaveRam(); }
                @Override public void writeSaveRam(byte[] saveRam) {
                    nativeHost.writeSaveRam(saveRam);
                }
                @Override public void close() { nativeHost.close(); }
            };
        }, listener, DEFAULT_FRAME_DELAY_NANOS, true);
    }

    public static ExperimentalGlesRenderLoop createVulkan(
            File core, File trustedCoreDirectory, File systemDirectory,
            File saveDirectory, File game, Listener listener) {
        return createVulkan(core, trustedCoreDirectory, systemDirectory,
                saveDirectory, game, true, listener);
    }

    public static ExperimentalGlesRenderLoop createVulkan(
            File core, File trustedCoreDirectory, File systemDirectory,
            File saveDirectory, File game,
            boolean widescreenEnhancementsEnabled, Listener listener) {
        return new ExperimentalGlesRenderLoop(() -> {
            final ExperimentalVulkanLibretroHost nativeHost =
                    new ExperimentalVulkanLibretroHost(core,
                            trustedCoreDirectory, systemDirectory,
                            saveDirectory, widescreenEnhancementsEnabled);
            try {
                nativeHost.loadGame(game);
            } catch (IOException | RuntimeException | Error failure) {
                nativeHost.close();
                throw failure;
            }
            return new Host() {
                @Override public void attach(Surface surface) {
                    nativeHost.attachSurface(surface);
                }
                @Override public void recreate(Surface surface) {
                    nativeHost.recreateSurface(surface);
                }
                // Vulkan swapchains must be rebuilt for new geometry; that
                // runtime keeps its proven recreate instead of a second path.
                @Override public void resize(Surface surface) {
                    nativeHost.recreateSurface(surface);
                }
                @Override public boolean runAndPresent() {
                    return nativeHost.runFrameAndPresent();
                }
                @Override public boolean retainsFrameDebt() {
                    return retainsVulkanFrameDebt(core.getName());
                }
                @Override public void detach() { nativeHost.detachSurface(); }
                @Override public void attachSecondary(Surface surface) {
                    nativeHost.attachSecondarySurface(surface);
                }
                @Override public void detachSecondary() {
                    nativeHost.detachSecondarySurface();
                }
                @Override public void pause() { nativeHost.pause(); }
                @Override public void resume() { nativeHost.resume(); }
                @Override public void setJoypadButton(int port, int button,
                                                      boolean pressed) {
                    nativeHost.setJoypadButton(port, button, pressed);
                }
                @Override public void setAnalogAxis(int port, int index, int id,
                                                    float value) {
                    nativeHost.setAnalogAxis(port, index, id, value);
                }
                @Override public void setPointer(int port, short x, short y,
                                                 boolean pressed) {
                    nativeHost.setPointer(port, x, y, pressed);
                }
                @Override public void setControllerPortDevice(int port, int device) {
                    nativeHost.setControllerPortDevice(port, device);
                }
                @Override public void reset() { nativeHost.reset(); }
                @Override public void applyCheats(java.util.List<String> codes) {
                    nativeHost.applyCheats(codes);
                }
                @Override public short[] drainAudio(int maxFrames) {
                    return nativeHost.drainAudio(maxFrames);
                }
                @Override public ExperimentalGlesLibretroHost.AvInfo avInfo() {
                    return nativeHost.avInfo();
                }
                @Override public void setSynchronizedVideoRate(
                        double declaredHz, double synchronizedHz) {
                    nativeHost.setSynchronizedVideoRate(
                            declaredHz, synchronizedHz);
                }
                @Override public void setPresentationAspect(float aspect) {
                    nativeHost.setPresentationAspect(aspect);
                }
                @Override public void setSecondaryPresentationRotation(
                        int clockwiseDegrees) {
                    nativeHost.setSecondaryPresentationRotation(clockwiseDegrees);
                }
                @Override public boolean stateReady() { return nativeHost.stateReady(); }
                @Override public byte[] serialize() { return nativeHost.serialize(); }
                @Override public void unserialize(byte[] state) {
                    nativeHost.unserialize(state);
                }
                @Override public byte[] readSaveRam() { return nativeHost.readSaveRam(); }
                @Override public void writeSaveRam(byte[] saveRam) {
                    nativeHost.writeSaveRam(saveRam);
                }
                @Override public void close() { nativeHost.close(); }
            };
        }, listener, DEFAULT_FRAME_DELAY_NANOS, true);
    }

    ExperimentalGlesRenderLoop(HostFactory factory, Listener listener,
                                long frameDelayNanos) {
        this(factory, listener, frameDelayNanos, false);
    }

    ExperimentalGlesRenderLoop(HostFactory factory, Listener listener,
                                       long frameDelayNanos, boolean useCoreCadence) {
        if (factory == null || listener == null || frameDelayNanos < 0)
            throw new IllegalArgumentException("factory, listener, and frame delay are required");
        this.factory = factory;
        this.listener = listener;
        this.frameDelayNanos = frameDelayNanos;
        this.useCoreCadence = useCoreCadence;
        executor = Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(() -> {
                renderThread = Thread.currentThread();
                runnable.run();
            }, "lucent-experimental-gles");
            thread.setDaemon(true);
            return thread;
        });
        post(this::initialize);
    }

    public void attachSurface(Surface surface) {
        requireSurface(surface);
        post(() -> {
            requireReady();
            if (surfaceAttached && attachedSurface == surface) {
                // Duplicate notification for the same live Surface (the
                // deferred engine-ready attach races the ordinary surface
                // callback). EGL objects and the core context already belong
                // to this generation; a destructive recreate here forces a
                // second core context reset that crashes cores such as
                // Mupen64Plus-Next before gameplay. While a context loss is
                // still unresolved, leave recovery to the queued explicit
                // recreate; otherwise absorb the notification as a
                // dimension-only refresh and keep rendering.
                if (awaitingRecreate) {
                    Log.i(TAG, "Duplicate same-surface attach ignored"
                            + " while context loss awaits recreation"
                            + " generation=" + surfaceGeneration
                            + " surface=" + System.identityHashCode(surface));
                    return;
                }
                ++surfaceGeneration;
                Log.i(TAG, "Duplicate same-surface attach absorbed"
                        + " generation=" + surfaceGeneration
                        + " surface=" + System.identityHashCode(surface));
                host.resize(surface);
                finishAttach();
                return;
            }
            boolean replacement = surfaceAttached;
            if (replacement) {
                if (secondarySurfaceAttached) {
                    host.detachSecondary();
                    secondarySurfaceAttached = false;
                }
                try {
                    host.recreate(surface);
                } catch (Throwable failure) {
                    // Native recreate detaches before attaching; a partial
                    // failure leaves no live EGL ownership to claim.
                    surfaceAttached = false;
                    attachedSurface = null;
                    throw failure;
                }
            } else {
                host.attach(surface);
            }
            surfaceAttached = true;
            attachedSurface = surface;
            ++surfaceGeneration;
            Log.i(TAG, (replacement ? "Surface replaced" : "Surface attached")
                    + " generation=" + surfaceGeneration
                    + " surface=" + System.identityHashCode(surface));
            finishAttach();
        });
    }

    public void recreateSurface(Surface surface) {
        requireSurface(surface);
        post(() -> {
            requireReady();
            if (!surfaceAttached)
                throw new IllegalStateException("no GLES surface exists to recreate");
            if (secondarySurfaceAttached) {
                host.detachSecondary();
                secondarySurfaceAttached = false;
            }
            host.recreate(surface);
            surfaceAttached = true;
            attachedSurface = surface;
            ++surfaceGeneration;
            Log.i(TAG, "Explicit surface recreation"
                    + " generation=" + surfaceGeneration
                    + " surface=" + System.identityHashCode(surface));
            finishAttach();
        });
    }

    /**
     * Non-destructive refresh after the same live Surface's buffer geometry
     * changed. A resize never replaces Surface identity, so it must not pay
     * the ordered destroy/recreate price; native presentation geometry is
     * rebuilt inside the existing context instead. A geometry report under a
     * different Surface object is a genuine replacement and recreates.
     */
    public void resizeSurface(Surface surface) {
        requireSurface(surface);
        post(() -> {
            requireReady();
            if (!surfaceAttached) {
                // A resize ahead of the first accepted attach carries no
                // ownership to refresh; the later attach reads current
                // geometry anyway.
                Log.i(TAG, "Resize before attach ignored"
                        + " surface=" + System.identityHashCode(surface));
                return;
            }
            if (attachedSurface != surface) {
                Log.i(TAG, "Resize carried a new Surface identity; recreating"
                        + " generation=" + (surfaceGeneration + 1)
                        + " old=" + System.identityHashCode(attachedSurface)
                        + " new=" + System.identityHashCode(surface));
                if (secondarySurfaceAttached) {
                    host.detachSecondary();
                    secondarySurfaceAttached = false;
                }
                try {
                    host.recreate(surface);
                } catch (Throwable failure) {
                    surfaceAttached = false;
                    attachedSurface = null;
                    throw failure;
                }
                surfaceAttached = true;
                attachedSurface = surface;
                ++surfaceGeneration;
                finishAttach();
                return;
            }
            if (awaitingRecreate) {
                // Recovery owns this context: the queued explicit recreate
                // rebuilds presentation at the current geometry. Running a
                // refresh here would touch the dead context and deliver a
                // second context_lost to the core.
                Log.i(TAG, "Resize ignored while context loss awaits recreation"
                        + " generation=" + surfaceGeneration
                        + " surface=" + System.identityHashCode(surface));
                return;
            }
            if (secondarySurfaceAttached) {
                // Vulkan recreate-style refreshes drop the native secondary
                // swapchain; mirror that bookkeeping so finishAttach can
                // rebuild it instead of stranding the lower display.
                host.detachSecondary();
                secondarySurfaceAttached = false;
            }
            host.resize(surface);
            Log.i(TAG, "Surface resized in place generation=" + surfaceGeneration
                    + " surface=" + System.identityHashCode(surface));
            finishAttach();
        });
    }

    /** Shared tail after GL ownership settled: secondary, resume, scheduling. */
    private void finishAttach() {
        attachPendingSecondary();
        awaitingRecreate = false;
        if (resumeRequested) {
            host.resume();
            resetFrameClock();
        }
        scheduleFrame();
    }

    public void detachSurface() {
        post(() -> {
            requireReady();
            if (secondarySurfaceAttached) host.detachSecondary();
            secondarySurfaceAttached = false;
            if (surfaceAttached) host.detach();
            surfaceAttached = false;
            attachedSurface = null;
            ++surfaceGeneration;
            awaitingRecreate = false;
            nextFrameDeadlineNanos = 0L;
            suspendDisplayClock();
        });
    }

    /**
     * Synchronous, bounded variant of {@link #detachSurface()} for the
     * TextureView destroy callback, which releases the game Surface as soon
     * as it returns.
     *
     * @return false when the bound elapsed first; the queued detach then
     *         completes asynchronously on the render thread instead of
     *         blocking the UI thread further.
     */
    public boolean detachSurfaceAndWait() {
        return awaitDetach(() -> {
            if (host == null) return;
            if (secondarySurfaceAttached) host.detachSecondary();
            secondarySurfaceAttached = false;
            if (surfaceAttached) host.detach();
            surfaceAttached = false;
            attachedSurface = null;
            ++surfaceGeneration;
            awaitingRecreate = false;
            nextFrameDeadlineNanos = 0L;
            suspendDisplayClock();
        });
    }

    public void attachSecondarySurface(Surface surface) {
        requireSurface(surface);
        post(() -> {
            requireReady();
            if (secondarySurfaceAttached) host.detachSecondary();
            secondarySurface = surface;
            secondarySurfaceAttached = false;
            attachPendingSecondary();
        });
    }

    public void detachSecondarySurface() {
        post(() -> {
            requireReady();
            if (secondarySurfaceAttached) host.detachSecondary();
            secondarySurfaceAttached = false;
            secondarySurface = null;
        });
    }

    /** Completes the native lower-swapchain detach before its SurfaceView may
     * be removed by the lower-display preview Activity. */
    public void detachSecondarySurfaceAndWait() {
        call(() -> {
            if (secondarySurfaceAttached) host.detachSecondary();
            secondarySurfaceAttached = false;
            secondarySurface = null;
            return null;
        });
    }

    /**
     * Bounded variant of {@link #detachSecondarySurfaceAndWait()} for the
     * lower SurfaceView destroy callback, whose Surface also dies on return.
     *
     * @return false when the bound elapsed and the detach will finish
     *         asynchronously on the render thread.
     */
    public boolean detachSecondarySurfaceAndWaitBounded() {
        return awaitDetach(() -> {
            if (host != null && secondarySurfaceAttached) host.detachSecondary();
            secondarySurfaceAttached = false;
            secondarySurface = null;
        });
    }

    private boolean awaitDetach(Runnable detach) {
        if (closed) return true;
        if (Thread.currentThread() == renderThread) {
            detach.run();
            return true;
        }
        final CountDownLatch finished = new CountDownLatch(1);
        try {
            executor.execute(() -> {
                try { if (!closed) detach.run(); }
                catch (Throwable failure) { reportError(failure); }
                finally { finished.countDown(); }
            });
        } catch (java.util.concurrent.RejectedExecutionException rejected) {
            return true;
        }
        try {
            return finished.await(SURFACE_DETACH_WAIT_MILLIS, TimeUnit.MILLISECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return false;
        }
    }

    public void resume() {
        post(() -> {
            requireReady();
            resumeRequested = true;
            if (surfaceAttached && !awaitingRecreate) host.resume();
            resetFrameClock();
            scheduleFrame();
        });
    }

    public void pause() {
        post(() -> {
            requireReady();
            resumeRequested = false;
            nextFrameDeadlineNanos = 0L;
            suspendDisplayClock();
            host.pause();
        });
    }

    /** Bytes captured before a background detach; publication needs no core calls. */
    public static final class PausedState {
        public final byte[] saveRam;
        public final byte[] state;
        public final Throwable stateFailure;

        private PausedState(byte[] saveRam, byte[] state, Throwable stateFailure) {
            this.saveRam = saveRam;
            this.state = state;
            this.stateFailure = stateFailure;
        }
    }

    /**
     * Enqueue now, not from a later disk-worker task: Android's onPause queues
     * detach immediately after returning from the session's pause callback.
     * The returned future never blocks that callback. Detach retains its own
     * 250 ms UI bound even if this capture takes longer; both operations still
     * execute in order on the render owner. Missing/lost surfaces yield no
     * snapshot, and state failures preserve any already-captured ordinary SRAM.
     */
    public Future<PausedState> pauseAndCaptureState(boolean includeRuntimeState) {
        if (closed) throw new IllegalStateException("experimental GLES loop is closed");
        FutureTask<PausedState> capture = new FutureTask<>(() -> {
            requireReady();
            resumeRequested = false;
            nextFrameDeadlineNanos = 0L;
            suspendDisplayClock();
            host.pause();
            if (!surfaceAttached || awaitingRecreate || attachedSurface == null ||
                    !attachedSurface.isValid()) return null;
            byte[] saveRam = host.readSaveRam();
            if (!includeRuntimeState) return new PausedState(saveRam, null, null);
            try {
                byte[] state = host.serialize();
                if (state == null || state.length == 0)
                    throw new IllegalStateException("core returned no background state");
                return new PausedState(saveRam, state, null);
            } catch (Throwable failure) {
                return new PausedState(saveRam, null, failure);
            }
        });
        executor.execute(capture);
        return capture;
    }

    /**
     * Exit-only render barrier. Unlike ordinary menu/background pause, this is
     * synchronous: all earlier frame work finishes on the owning render thread
     * and no later frame can be scheduled before the caller changes Android
     * view z-order or surface ownership.
     */
    public void pauseAndWait() {
        call(() -> {
            resumeRequested = false;
            nextFrameDeadlineNanos = 0L;
            suspendDisplayClock();
            host.pause();
            return null;
        });
    }

    /** Recovery needs actual successful detach, unlike best-effort UI teardown. */
    public void pauseAndDetachForPresentationRecovery() {
        call(() -> {
            resumeRequested = false;
            nextFrameDeadlineNanos = 0L;
            suspendDisplayClock();
            host.pause();
            if (secondarySurfaceAttached) host.detachSecondary();
            secondarySurfaceAttached = false;
            if (surfaceAttached) host.detach();
            surfaceAttached = false;
            attachedSurface = null;
            ++surfaceGeneration;
            awaitingRecreate = false;
            return null;
        });
    }

    public void setJoypadButton(int port, int button, boolean pressed) {
        post(() -> {
            requireReady();
            host.setJoypadButton(port, button, pressed);
        });
    }

    public void setAnalogAxis(int port, int index, int id, float value) {
        post(() -> {
            requireReady();
            host.setAnalogAxis(port, index, id, value);
        });
    }

    public void setPointer(int port, short x, short y, boolean pressed) {
        post(() -> {
            requireReady();
            host.setPointer(port, x, y, pressed);
        });
    }

    /**
     * Selects the controller a core emulates on a port, on the render-owning
     * thread. Synchronous: the caller runs right after the game load and the
     * first frame must not be scheduled before the device is attached, or a
     * Nunchuk-only Wii title boots deaf.
     */
    public void setControllerPortDevice(final int port, final int device) {
        call(() -> { host.setControllerPortDevice(port, device); return null; });
    }

    /**
     * Power-cycles the loaded content on the render-owning thread. Synchronous
     * so a caller can report whether the reset actually happened instead of
     * claiming one that a later frame may still reject.
     */
    public void reset() {
        call(() -> { host.reset(); return null; });
    }

    /** Replaces every live cheat slot synchronously on the render-owner thread. */
    public void applyCheats(final java.util.List<String> codes) {
        final java.util.List<String> snapshot = codes == null ?
                java.util.Collections.<String>emptyList() :
                new java.util.ArrayList<>(codes);
        call(() -> { host.applyCheats(snapshot); return null; });
    }

    /** Drains native PCM on the render thread; safe to call from any thread. */
    public short[] drainAudio(final int maxFrames) {
        if (maxFrames <= 0) return new short[0];
        return call(() -> host.drainAudio(maxFrames));
    }

    public ExperimentalGlesLibretroHost.AvInfo avInfo() {
        return call(() -> host.avInfo());
    }

    public void setPresentationAspect(final float aspect) {
        call(() -> { host.setPresentationAspect(aspect); return null; });
    }

    public void setSecondaryPresentationRotation(final int clockwiseDegrees) {
        call(() -> {
            host.setSecondaryPresentationRotation(clockwiseDegrees);
            return null;
        });
    }

    public byte[] serialize() { return call(() -> host.serialize()); }

    public boolean stateReady() { return call(() -> host.stateReady()); }

    public void unserialize(final byte[] state) {
        unserialize(state, false);
    }

    /**
     * Restores guest state and, for cores which require it, migrates the live
     * presentation context in one render-owner operation. No frame may present
     * the restored guest through the pre-restore context, and success is not
     * returned until the migration has actually finished.
     */
    public void unserialize(final byte[] state, final boolean recreatePresentation) {
        if (state == null || state.length == 0)
            throw new IllegalArgumentException("serialized state is required");
        call(() -> {
            Surface current = attachedSurface;
            if (recreatePresentation) {
                if (!surfaceAttached)
                    throw new IllegalStateException("restore requires an attached presentation surface");
                requireSurface(current); // Reject before mutating the guest.
            }
            host.unserialize(state);
            if (recreatePresentation) {
                // Block any already-scheduled frame if migration fails. The
                // caller must receive that failure, not a later async success.
                awaitingRecreate = true;
                try {
                    if (secondarySurfaceAttached) {
                        host.detachSecondary();
                        secondarySurfaceAttached = false;
                    }
                    host.recreate(current);
                    ++surfaceGeneration;
                    attachPendingSecondary();
                    if (resumeRequested) host.resume();
                    resetFrameClock();
                    awaitingRecreate = false;
                    Log.i(TAG, "Renderer migration completed after state restore"
                            + " generation=" + surfaceGeneration);
                } catch (RuntimeException | Error failure) {
                    try { host.pause(); } catch (Throwable ignored) {}
                    throw failure;
                }
            }
            return null;
        });
    }

    public byte[] readSaveRam() { return call(() -> host.readSaveRam()); }

    public void writeSaveRam(final byte[] saveRam) {
        if (saveRam == null) throw new IllegalArgumentException("save RAM is required");
        call(() -> { host.writeSaveRam(saveRam); return null; });
    }

    /** Nonblocking; callbacks run only after successful native close, exactly once each. */
    public void closeWhenComplete(Runnable completion) {
        if (completion == null) throw new IllegalArgumentException("completion required");
        boolean complete;
        synchronized (closeLock) {
            complete = teardownCompleted;
            if (!complete) closeCallbacks.add(completion);
        }
        requestClose();
        if (complete) completion.run();
    }

    private void requestClose() {
        synchronized (closeLock) {
            if (closed) return;
            closed = true;
            // Always queue: asynchronous close must not block a UI caller or
            // tear down reentrantly inside a render listener's callback.
            executor.execute(closeTask);
            executor.shutdown();
        }
    }

    @Override public void close() { close(10, TimeUnit.SECONDS); }

    // Same production wait with a shorter bound for deterministic host tests.
    void close(long timeout, TimeUnit unit) {
        requestClose();
        if (Thread.currentThread() == renderThread) {
            closeTask.run(); // FutureTask absorbs the already-queued duplicate.
            return;
        }
        try {
            closeTask.get(timeout, unit);
        } catch (TimeoutException timeoutFailure) {
            throw new IllegalStateException("timed out closing experimental GLES thread",
                    timeoutFailure);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("interrupted closing experimental GLES thread",
                                            interrupted);
        } catch (java.util.concurrent.ExecutionException failure) {
            throw new IllegalStateException("failed closing experimental GLES thread",
                    failure.getCause());
        }
    }

    private void initialize() {
        try {
            host = factory.createAndLoad();
            if (host == null) throw new IllegalStateException("GLES host factory returned null");
            audioPaced = host.usesAudioPacing();
            if (useCoreCadence) {
                ExperimentalGlesLibretroHost.AvInfo av = host.avInfo();
                double synchronizedHz =
                        DisplaySyncPolicy.synchronizedSourceHz(av.framesPerSecond);
                host.setSynchronizedVideoRate(av.framesPerSecond, synchronizedHz);
                frameDelayNanos = frameDelayNanos(synchronizedHz);
                declaredCoreHz = av.framesPerSecond;
                synchronizedCoreHz = synchronizedHz;
                pacedCoreHz = 0.0;
                Log.i(TAG, String.format(Locale.ROOT,
                        "Display-synchronized hardware core declaredHz=%.6f " +
                        "synchronizedHz=%.6f panelHz=%.0f uniform=%s",
                        av.framesPerSecond, synchronizedHz,
                        DisplaySyncPolicy.panelRefreshHz(synchronizedHz),
                        DisplaySyncPolicy.isUniformOnThor(synchronizedHz)));
            }
            if (audioPaced) Log.i(TAG,
                    "Render-driven core uses generated PCM duration for guest pacing");
            ready = true;
            listener.onReady();
        } catch (Throwable failure) {
            reportError(failure);
        }
    }

    private void scheduleFrame() {
        if (closed || !ready || !resumeRequested || !surfaceAttached ||
                awaitingRecreate || frameScheduled) return;
        long delayNanos = 0L;
        if (frameDelayNanos > 0L) {
            long now = System.nanoTime();
            if (canRecoverPresentation() || host.retainsFrameDebt() ?
                    shouldRebaseFrameClock(now, nextFrameDeadlineNanos, frameDelayNanos) :
                    nextFrameDeadlineNanos == 0L || now - nextFrameDeadlineNanos > frameDelayNanos * 4L)
                nextFrameDeadlineNanos = now;
            delayNanos = Math.max(0L, nextFrameDeadlineNanos - now);
        }
        frameScheduled = true;
        executor.schedule(() -> {
            frameScheduled = false;
            if (closed || !resumeRequested || !surfaceAttached || awaitingRecreate) return;
            boolean displayDriven = false;
            long producedAudioDurationNs = 0L;
            try {
                double measuredHz = awaitDisplayClockHz();
                // A close can be requested while the optional ticker is waiting.
                if (closed) return;
                displayDriven = measuredHz > 0.0;
                updateDisplayAudioClock(measuredHz);
                long workStartNs = System.nanoTime();
                boolean recover = !displayDriven && hasPresentedSinceClockReset &&
                        canRecoverPresentation() && consecutiveRecoverySteps < 4 &&
                        nextFrameDeadlineNanos > 0L && frameDelayNanos > 0L &&
                        workStartNs - nextFrameDeadlineNanos > frameDelayNanos * 2L;
                boolean presented;
                if (recover) {
                    host.runWithoutPresent();
                    presented = false;
                    consecutiveRecoverySteps++;
                } else {
                    presented = host.runAndPresent();
                    consecutiveRecoverySteps = 0;
                }
                if (audioPaced && host.didRunFrame())
                    producedAudioDurationNs = host.lastRunAudioDurationNanos();
                recordFrameWork(workStartNs, System.nanoTime());
                if (presented) {
                    hasPresentedSinceClockReset = true;
                    listener.onFramePresented();
                } else if (host.didRunFrame()) {
                    // Guest PCM must not depend on whether its image was swapped.
                    // This callback is deliberately NOT a presentation claim.
                    listener.onFrameExecutedWithoutPresentation();
                }
            } catch (Throwable failure) {
                if (isContextLoss(failure)) {
                    awaitingRecreate = true;
                    suspendDisplayClock();
                    try { host.pause(); } catch (Throwable ignored) {}
                    listener.onContextLost();
                    return;
                }
                resumeRequested = false;
                suspendDisplayClock();
                try { host.pause(); } catch (Throwable ignored) {}
                reportError(failure);
                return;
            }
            if (displayDriven) {
                // The next tick, not a second nominal-clock sleep, owns the
                // next guest step. Keep rendering and audio on this same clock.
                nextFrameDeadlineNanos = 0L;
            } else if (frameDelayNanos > 0L)
                nextFrameDeadlineNanos += guestStepDurationNanos(
                        audioPaced, producedAudioDurationNs, frameDelayNanos);
            scheduleFrame();
        }, delayNanos, TimeUnit.NANOSECONDS);
    }

    private boolean canRecoverPresentation() {
        return host != null && host.supportsPresentationRecovery() &&
                attachedSurface != null && attachedSurface.isValid() &&
                !FrameGenerationRendererRegistry.isFrameGenerationInput(attachedSurface);
    }

    private double awaitDisplayClockHz() throws InterruptedException {
        DisplayClock clock = displayClock;
        // A render-driven retro_run is not one vblank: e.g. a 30 FPS Flycast
        // scene produces ~1470 PCM frames per call, a 60 FPS scene ~735.
        // Fixed display ticks here ran 30 FPS scenes at twice game speed.
        if (clock == null || !useCoreCadence || audioPaced) return 0.0;
        try {
            boolean direct = attachedSurface != null && attachedSurface.isValid() &&
                    !FrameGenerationRendererRegistry.isFrameGenerationInput(attachedSurface);
            clock.configure(declaredCoreHz, 1_000_000_000.0 / frameDelayNanos, direct);
            if (!direct || clock.awaitDueTimeNs() == 0L) return 0.0;
            double measuredHz = clock.measuredSourceHz();
            if (DisplaySyncPolicy.permitsCoreClockCorrection(declaredCoreHz, measuredHz))
                return measuredHz;
            clock.suspend();
        } catch (RuntimeException unavailable) {
            // Display timing is optional. Losing it must not stop normal gameplay.
            Log.w(TAG, "Display tick source failed; restoring absolute hardware clock", unavailable);
            closeDisplayClock();
        }
        return 0.0;
    }

    private void updateDisplayAudioClock(double observedHz) {
        if (!useCoreCadence || (displayClock == null && !displayClockWasActive)) return;
        boolean displayDriven = observedHz > 0.0;
        double nominalHz = 1_000_000_000.0 / frameDelayNanos;
        double measuredHz = displayDriven ? observedHz : nominalHz;
        boolean changedPath = displayClockWasActive != displayDriven;
        long now = System.nanoTime();
        if (displayAudioClockHz == 0.0) displayAudioClockHz = nominalHz;
        if (DisplaySyncPolicy.permitsCoreClockCorrection(declaredCoreHz, measuredHz) &&
                (changedPath || now - displayAudioClockUpdatedNs >= 2_000_000_000L) &&
                Math.abs(measuredHz - displayAudioClockHz) > 0.001) {
            host.setSynchronizedVideoRate(declaredCoreHz, measuredHz);
            displayAudioClockHz = measuredHz;
            displayAudioClockUpdatedNs = now;
        }
        if (changedPath) {
            // Lost display callbacks resume the ordinary absolute timeline
            // without a burst of deadlines left over from before the wait.
            if (!displayDriven) resetFrameClock();
            Log.i(TAG, "Direct hardware display tick clock active=" + displayDriven +
                    " measuredHz=" + measuredHz + " audioClockHz=" + displayAudioClockHz);
            displayClockWasActive = displayDriven;
        }
    }

    private void suspendDisplayClock() {
        if (displayClock == null) return;
        try { displayClock.suspend(); }
        catch (RuntimeException unavailable) {
            Log.w(TAG, "Display tick suspend failed; retaining absolute hardware clock", unavailable);
            closeDisplayClock();
        }
    }

    private void closeDisplayClock() {
        DisplayClock clock = displayClock;
        displayClock = null;
        if (clock == null) return;
        try { clock.close(); }
        catch (RuntimeException unavailable) {
            // An optional ticker failure must not strand the native host on exit.
            Log.w(TAG, "Display tick cleanup failed", unavailable);
        }
    }

    /** Render-thread only: folds one core frame's work time into the ring. */
    private void recordFrameWork(long startNs, long endNs) {
        if (!host.didRunFrame()) {
            // Surface warmup is neither emulator throughput nor GPU headroom.
            // Restart measurement after it, excluding the paused wall time too.
            workSecondStartNs = 0L;
            workSecondWorstNs = 0L;
            workSecondFrames = 0;
            workRingFilled = 0;
            workRingIndex = 0;
            achievedCoreHzSnapshot = 0.0;
            frameWorkCapacityHzSnapshot = 0.0;
            return;
        }
        long work = Math.max(0L, endNs - startNs);
        if (workSecondStartNs == 0L) workSecondStartNs = startNs;
        if (work > workSecondWorstNs) workSecondWorstNs = work;
        ++workSecondFrames;
        if (endNs - workSecondStartNs < 1_000_000_000L) return;
        double seconds = (endNs - workSecondStartNs) / 1_000_000_000.0;
        achievedCoreHzSnapshot = workSecondFrames / seconds;
        workWorstNsRing[workRingIndex] = workSecondWorstNs;
        workRingIndex = (workRingIndex + 1) % WORK_RING_SECONDS;
        if (workRingFilled < WORK_RING_SECONDS) ++workRingFilled;
        long worst = 0L;
        for (int index = 0; index < workRingFilled; ++index)
            worst = Math.max(worst, workWorstNsRing[index]);
        frameWorkCapacityHzSnapshot = workRingFilled >= 10 && worst > 0L ?
                1_000_000_000.0 / worst : 0.0;
        workSecondStartNs = endNs;
        workSecondWorstNs = 0L;
        workSecondFrames = 0;
    }

    public double pacedVideoHz() { return pacedCoreHz; }
    public double achievedCoreHz() { return achievedCoreHzSnapshot; }
    public double sustainedFrameWorkCapacityHz() {
        // Hardware cores queue GPU work asynchronously: runAndPresent()
        // returns before the GPU finishes, so its wall time overstates
        // headroom and drove a false 40->60 probe every minute on Dolphin
        // (run gc-b20).  Report no headroom; a paced hardware core stays
        // paced until the tier itself climbs.
        return 0.0;
    }

    /**
     * Applies only a small correction of the original declared core clock;
     * zero restores the synchronized clock.  Only host-cadenced cores can be
     * paced.  The change is applied on the render thread through the same
     * declared/clock audio-multiplier call the clock synchronization uses.
     */
    public boolean setPacedVideoHz(double hz) {
        double synchronizedHz = synchronizedCoreHz;
        double declaredHz = declaredCoreHz;
        if (closed || !useCoreCadence || !(synchronizedHz > 1.0) ||
                !(declaredHz > 1.0)) return false;
        double target = hz;
        if (hz != 0.0 && !DisplaySyncPolicy.permitsCoreClockCorrection(declaredHz, hz))
            return false;
        if (Math.abs(target - pacedCoreHz) < 1.0e-4) return true;
        double clock = target > 0.0 ? target : synchronizedHz;
        pacedCoreHz = target;
        post(() -> {
            if (!ready || host == null) return;
            host.setSynchronizedVideoRate(declaredHz, clock);
            displayAudioClockHz = clock;
            displayAudioClockUpdatedNs = 0L;
            frameDelayNanos = frameDelayNanos(clock);
            resetFrameClock();
            Log.i(TAG, String.format(Locale.ROOT,
                    "Tier pacing hardware core declaredHz=%.6f " +
                    "synchronizedHz=%.6f pacedHz=%.3f coreClockHz=%.6f",
                    declaredHz, synchronizedHz, target, clock));
        });
        return true;
    }

    /**
     * Frame deadlines are absolute.  Scheduling a full frame interval after
     * emulation/GPU work makes a nominal 60 Hz core run at
     * {@code 1 / (16.7 ms + work time)}, starving its real-time audio stream.
     */
    private void resetFrameClock() {
        nextFrameDeadlineNanos = System.nanoTime();
        hasPresentedSinceClockReset = false;
        consecutiveRecoverySteps = 0;
        suspendDisplayClock();
    }

    static boolean retainsVulkanFrameDebt(String coreFileName) {
        // PS2 may recover short JIT/presentation stalls by running subsequent
        // frames immediately. This does NOT enable offscreen execution: every
        // step still acquires, submits and presents through the Vulkan host,
        // including when its destination is a frame-generation input surface.
        // Keep unrelated Vulkan cores on their existing policy.
        return "liblucent_core_armsx2.so".equals(coreFileName) ||
                "liblucent_core_armsx2_16k.so".equals(coreFileName);
    }

    static boolean shouldRebaseFrameClock(long now, long deadline, long period) {
        // A four-frame cutoff is only67ms at60Hz. A transient JIT/render stall
        // then permanently discards guest time and its PCM, draining the audio
        // reserve even when the core has enough headroom to catch up afterward.
        // Retain at most a quarter second of debt (or four slow-core frames).
        // Lifecycle resume resets the clock separately; long freezes still
        // rebase instead of replaying seconds of stale input/emulation.
        long boundedDebt = Math.max(250_000_000L, period * 4L);
        return deadline == 0L || now - deadline > boundedDebt;
    }

    static long guestStepDurationNanos(boolean audioPaced, long audioNs, long nominalNs) {
        // Loading/no-audio steps still yield; silent PCM counts normally.
        return audioPaced && audioNs > 0L ? audioNs : nominalNs;
    }

    static long frameDelayNanos(double framesPerSecond) {
        if (!Double.isFinite(framesPerSecond) || framesPerSecond <= 1.0 ||
                framesPerSecond >= 1000.0)
            return DEFAULT_FRAME_DELAY_NANOS;
        return Math.max(1L, Math.round(1_000_000_000.0 / framesPerSecond));
    }

    private void teardown() throws IOException {
        closeDisplayClock();
        Host current = host;
        host = null;
        ready = false;
        resumeRequested = false;
        if (current == null) return;
        try { current.pause(); } catch (Throwable failure) { reportError(failure); }
        if (secondarySurfaceAttached) {
            try { current.detachSecondary(); }
            catch (Throwable failure) { reportError(failure); }
        }
        secondarySurfaceAttached = false;
        secondarySurface = null;
        if (surfaceAttached) {
            try { current.detach(); } catch (Throwable failure) { reportError(failure); }
        }
        surfaceAttached = false;
        attachedSurface = null;
        awaitingRecreate = false;
        nextFrameDeadlineNanos = 0L;
        current.close();
    }

    private void attachPendingSecondary() {
        if (!surfaceAttached || secondarySurfaceAttached || secondarySurface == null ||
                !secondarySurface.isValid()) return;
        host.attachSecondary(secondarySurface);
        secondarySurfaceAttached = true;
    }

    private void post(Runnable action) {
        if (closed) throw new IllegalStateException("experimental GLES loop is closed");
        executor.execute(() -> {
            try { action.run(); }
            catch (Throwable failure) { reportError(failure); }
        });
    }

    private <T> T call(Callable<T> action) {
        if (closed) throw new IllegalStateException("experimental GLES loop is closed");
        if (Thread.currentThread() == renderThread) {
            requireReady();
            try { return action.call(); }
            catch (RuntimeException | Error failure) { throw failure; }
            catch (Exception failure) {
                throw new IllegalStateException("experimental GLES call failed", failure);
            }
        }
        FutureTask<T> task = new FutureTask<>(() -> {
            requireReady();
            return action.call();
        });
        executor.execute(task);
        try {
            return task.get(10, TimeUnit.SECONDS);
        } catch (TimeoutException timeout) {
            task.cancel(false);
            throw new IllegalStateException("timed out waiting for experimental GLES thread",
                                            timeout);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("interrupted waiting for experimental GLES thread",
                                            interrupted);
        } catch (java.util.concurrent.ExecutionException failed) {
            Throwable cause = failed.getCause();
            if (cause instanceof RuntimeException) throw (RuntimeException) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw new IllegalStateException("experimental GLES call failed", cause);
        }
    }

    private void requireReady() {
        if (!ready || host == null)
            throw new IllegalStateException("experimental GLES host is not ready");
    }

    private static void requireSurface(Surface surface) {
        if (surface == null || !surface.isValid())
            throw new IllegalArgumentException("valid Android Surface is required");
    }

    private static boolean isContextLoss(Throwable failure) {
        for (Throwable current = failure; current != null; current = current.getCause()) {
            String message = current.getMessage();
            if (message == null) continue;
            String normalized = message.toLowerCase(Locale.US);
            if (normalized.contains("context lost") || normalized.contains("0x300e"))
                return true;
        }
        return false;
    }

    private void reportError(Throwable failure) {
        try { listener.onError(failure); } catch (Throwable ignored) {}
    }
}
