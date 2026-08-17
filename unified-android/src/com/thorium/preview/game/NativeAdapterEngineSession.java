package com.thorium.preview.game;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.net.Uri;
import android.os.Build;
import android.os.SystemClock;
import android.util.Log;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.Surface;

import com.thorium.lucent.input.CanonicalControl;
import com.thorium.lucent.input.DeviceCatalog;
import com.thorium.lucent.input.FileRemapStore;
import com.thorium.lucent.input.GamepadDescriptor;
import com.thorium.lucent.input.InputRouter;
import com.thorium.lucent.input.InputSignal;
import com.thorium.lucent.input.android.AndroidDeviceScanner;
import com.thorium.lucent.input.android.AndroidGamingDeviceDetector;
import com.thorium.lucent.audio.PcmAudioQueue;
import com.thorium.lucent.emulators.NativeAdapterStopPolicy;
import com.thorium.lucent.state.DurableBlobStore;
import com.thorium.preview.NativeAdapterHost;
import com.thorium.preview.AppVolumeController;
import com.thorium.preview.SecondaryGameplaySurfaceRouter;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Drives a Phase 3 native-adapter engine in-process. Three are described by the
 * Phase 3 registry and each has an independently opted-in, hash-pinned adapter:
 * Switch/Eden ({@code LUCENT_INCLUDE_PHASE3_EDEN=1}), Wii U/Cemu
 * ({@code LUCENT_INCLUDE_PHASE3_CEMU=1}), and PlayStation 3/aPS3e
 * ({@code LUCENT_INCLUDE_PHASE3_APS3E=1}).
 *
 * It reuses the render-owner discipline proven by {@link PpssppGlesEngineSession}:
 * one dedicated thread owns every adapter call, the surface is quiesced before
 * detach, input maps to the {@code lucent_native_control} ordinals, and audio is
 * pulled into a Lucent-owned {@link AudioTrack}. Capabilities are reported
 * honestly. Eden and Cemu report no Quick Resume; aPS3e reports it only because
 * its RPCS3-derived core serializes and validates a real savestate. Held-Stop
 * therefore either commits that exact adapter state or preserves the prior
 * checkpoint and reports failure—it never substitutes a screenshot or claims
 * a normal save is an exact resume point. If the adapter {@code .so} is absent
 * the session fails closed, and so does an adapter whose user-supplied
 * keys/firmware are missing (see
 * {@link NativeAdapterSystemDirectory}).
 *
 * Dual screen: the Wii U TV output uses display 0 (the primary surface) and the
 * GamePad view uses display 4 via {@link SecondaryGameplaySurfaceRouter}, the
 * same path DS/3DS use. Switch is single-screen and Eden reports
 * {@code dual_screen=false}, so it never requests the secondary display.
 */
final class NativeAdapterEngineSession implements EngineSession,
        SecondaryGameplaySurfaceRouter.Listener {
    private static final String TAG = "LucentPhase3Engine";
    private static final int OUTPUT_SAMPLE_RATE = 48_000;
    // JNI byte arrays are signed-int sized.  A compressed RPCS3 state is much
    // larger than a libretro state, so keep a generous but explicit OOM guard.
    private static final int MAX_QUICK_RESUME_BYTES = 1024 * 1024 * 1024;
    private static final float AXIS_DEAD_ZONE = 0.08f;

    /**
     * Cadence of the render-owner loop while a game is running.
     *
     * <p>Both Phase 3 adapters present from an engine thread of their own, so
     * their {@code run_frame} is a liveness poll that returns an atomic boolean
     * and nothing else: Eden's returns {@code EmulationSession::IsRunning()}
     * and Cemu's returns {@code CafeSystem::IsTitleRunning()}. Unlike the
     * libretro sessions, whose {@code runFrame} actually advances a frame and
     * which are paced by {@code AbsoluteFramePacer}, this loop therefore has
     * nothing in it that blocks. Left unpaced it free-ran at CPU speed: it held
     * a core at 100% for the whole session, took the native PCM ring's mutex
     * and allocated a Java {@code short[]} on every single pass, and left the
     * engine's own timing, CPU, GPU and audio threads to fight over what was
     * left of an already oversubscribed SoC.
     *
     * <p>Four milliseconds still polls liveness 250 times a second, and still
     * drains the ring far faster than either engine fills it -- both push one
     * 5 ms block at a time, and a drain takes up to 2048 frames -- so neither
     * audio latency nor failure detection changes.
     */
    private static final long RENDER_TICK_MS = 4L;
    /** Cadence while parked: no surface, or the session is paused. */
    private static final long IDLE_TICK_MS = 8L;
    /**
     * Bound on how long a caller waits for the render owner to pick up its
     * work. Normally a tick or two; the exception is the very first pass, where
     * the queue sits behind {@code start()} loading a title. Missing the bound
     * is not an error -- the action stays queued and still runs in order -- so
     * this exists only to keep a lifecycle callback off an unbounded wait.
     */
    private static final long RENDER_TASK_TIMEOUT_MS = 250L;
    /** RPCS3 savestates are large and are compressed on the render owner. */
    private static final long QUICK_RESUME_TASK_TIMEOUT_MS = 60_000L;
    /**
     * How long the render owner holds the very first {@code start()} back while
     * an accepted secondary display is still bringing its Surface up.
     *
     * <p>An engine that reports {@code dual_screen} is told about both of its
     * windows exactly once, at {@code start()}: that is where Cemu binds
     * {@code canvas_pad}, sets {@code pad_open} and builds the second
     * swapchain. The two surfaces do NOT arrive together. The primary is a
     * {@code SurfaceView} in this window, the secondary is a
     * {@code SurfaceView} inside the lower display's Activity, and the request
     * for the second one is only posted to that Activity's UI thread as
     * {@link #prepare} finishes -- it lands a handful of milliseconds AFTER the
     * render owner is already free to start. Measured on the Thor the gap is
     * about 9 ms, which is comfortably inside the window {@code start()} itself
     * occupies, so whether the GamePad view existed at {@code start()} was
     * decided by a coin toss between two threads.
     *
     * <p>Losing that toss is silent and total: {@code start()} sees a null
     * lower window, the adapter takes its single-window branch, and the second
     * display never shows guest output for the rest of the session. Waiting is
     * therefore the correct default, and the bound only exists so that a
     * secondary display which never produces a Surface at all -- panel asleep,
     * Activity refused, display pulled -- can never hold a launch hostage. On
     * expiry the session starts single-window exactly as before, and if the
     * Surface does turn up later it is still delivered through
     * {@link #onSecondarySurfaceAvailable}.
     */
    private static final long SECONDARY_SURFACE_WAIT_MS = 2_000L;

    /* lucent_native_control ordinals (stable across ABI v1). */
    private static final int PAD_A = 0, PAD_B = 1, PAD_X = 2, PAD_Y = 3;
    private static final int PAD_L = 4, PAD_R = 5, PAD_ZL = 6, PAD_ZR = 7;
    private static final int PAD_DPAD_UP = 8, PAD_DPAD_DOWN = 9;
    private static final int PAD_DPAD_LEFT = 10, PAD_DPAD_RIGHT = 11;
    private static final int PAD_START = 12, PAD_SELECT = 13, PAD_HOME = 14;
    private static final int PAD_LSTICK_X = 15, PAD_LSTICK_Y = 16;
    private static final int PAD_RSTICK_X = 17, PAD_RSTICK_Y = 18;

    private final Context context;
    private final Context appContext;
    private final NativeAdapterCatalog.Entry entry;
    private final ExecutorService lifecycle = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "lucent-phase3-lifecycle");
        thread.setDaemon(true);
        return thread;
    });
    private final AtomicBoolean stopping = new AtomicBoolean(false);
    private final AtomicBoolean released = new AtomicBoolean(false);
    private final AtomicBoolean audioFailureReported = new AtomicBoolean(false);
    /**
     * Adapter calls that arrive on another thread and have to be handed to the
     * render owner. The ABI is explicit that "all calls for one engine instance
     * are serialized by Lucent on a single render-owner thread", and both
     * engines rely on it: Eden's {@code SurfaceChanged} reads {@code m_window}
     * with no lock while {@code ShutdownEmulation} resets it, and Cemu's
     * {@code InitializeSurface} replaces the live swapchains outright while its
     * own Latte thread still holds a reference to them.
     */
    private final BlockingQueue<RenderTask> renderTasks = new LinkedBlockingQueue<>();

    private volatile Listener listener;
    private volatile NativeAdapterHost host;
    private volatile NativeAdapterHost.Capabilities capabilities;
    private volatile Surface surface;
    private volatile Surface secondarySurface;
    private volatile String secondarySurfaceSize = "";
    private volatile boolean secondaryDisplayRequested;
    /**
     * Uptime at which the render owner first became able to start, or 0 before
     * that. Render owner only; it exists to bound {@link #SECONDARY_SURFACE_WAIT_MS}
     * from the moment the wait actually begins rather than from {@code prepare},
     * so a session that is resumed late still gets the full grace period.
     */
    private long secondaryWaitBeganUptimeMs;
    private volatile boolean prepared;
    private volatile boolean started;
    private volatile boolean resumeRequested;
    private volatile boolean restoreAttempted;
    private volatile Thread renderThread;
    private volatile AudioTrack audioTrack;
    private volatile PcmAudioQueue audioQueue;
    private int primedAudioSamples;
    private int audioPrimeSamplesTarget;
    private volatile boolean audioStartedOnce;
    /**
     * The focus this session holds while it plays. Declared final and built in
     * the constructor so no teardown path can reach a null one and leak focus.
     */
    private final EngineAudioFocus audioFocus;
    private volatile Runnable firstFrameCallback;
    private GameLaunchRequest request;
    private InputRouter inputRouter;
    private List<GamepadDescriptor> devices = new ArrayList<>();
    private File saveDirectory;
    private File saveRamFile;
    private volatile long prepareStartedUptimeMs;

    NativeAdapterEngineSession(Context context, NativeAdapterCatalog.Entry entry) {
        if (context == null || entry == null)
            throw new IllegalArgumentException("context and Phase 3 entry are required");
        this.context = context;
        this.appContext = context.getApplicationContext();
        this.entry = entry;
        this.audioFocus = new EngineAudioFocus(appContext, TAG, entry.id,
                new EngineAudioFocus.Listener() {
                    @Override public void onAudioFocusSuppressed() {
                        silenceForAudioFocusLoss();
                    }

                    @Override public void onAudioFocusRestored() {
                        resumeAfterAudioFocusGain();
                    }
                });
    }

    @Override public void prepare(GameLaunchRequest request, Listener callback) {
        if (request == null || callback == null)
            throw new IllegalArgumentException("launch request and listener are required");
        listener = callback;
        this.request = request;
        prepareStartedUptimeMs = SystemClock.uptimeMillis();
        lifecycle.execute(() -> {
            try {
                if (!entry.id.equals(request.engineId) || !entry.supports(request.systemId))
                    throw new IllegalStateException("Phase 3 adapter does not support " +
                            request.systemId);
                if (stopping.get() || released.get()) return;
                requestPinnedWiiUSecondaryDisplay(request);
                File game = resolveGameFile(request.contentUri);
                File trusted = new File(appContext.getApplicationInfo().nativeLibraryDir)
                        .getCanonicalFile();
                // Fail closed: the adapter .so must be present and hash-verified.
                if (entry.coreFile == null || !entry.coreFile.isFile())
                    throw new IllegalStateException("Native adapter is not installed");
                // Phase 3 images are routinely tens of gigabytes. Hashing the
                // entire image here used to happen twice before dlopen (once
                // for this directory and once for the input profile), making
                // Switch and Wii U sit on a black Surface for 70+ seconds even
                // when the native adapter itself loaded content in under a
                // second. Hash the small canonical library identity instead;
                // the emulator-owned NAND/save tree remains unchanged.
                String gameIdentity = launchIdentity(request, game);
                // aPS3e's real Quick Resume vault predates this launch-latency
                // fix and is keyed by the executable bytes. Its EBOOT is small
                // enough to retain that compatibility; only disc/container
                // adapters use the constant-time identity on the hot path.
                String saveIdentity = "aps3e".equals(entry.id)
                        ? contentSha256Short(game) : gameIdentity;
                saveDirectory = new File(appContext.getFilesDir(),
                        "engine-saves/" + entry.id + "/" + saveIdentity);
                if (!saveDirectory.isDirectory() && !saveDirectory.mkdirs())
                    throw new IllegalStateException("Cannot create adapter save directory");
                saveRamFile = new File(saveDirectory, "adapter-save.bin");

                long phaseStarted = SystemClock.uptimeMillis();
                if ("aps3e".equals(entry.id)) {
                    NativeAdapterSystemDirectory.prepareForOpen(appContext,
                            entry.id, request.systemId);
                    logLaunchPhase("adapter-preopen-environment", phaseStarted);
                    phaseStarted = SystemClock.uptimeMillis();
                }
                NativeAdapterHost created = new NativeAdapterHost(entry.coreFile, trusted);
                logLaunchPhase("adapter-open", phaseStarted);
                capabilities = created.describe();
                if (isPinnedWiiUDualScreenRoute(request) && !capabilities.dualScreen)
                    throw new IllegalStateException(
                            "Pinned Cemu adapter did not report its required dual screen");
                // The system directory is resolved from the adapter's OWN
                // capability report, so an engine that declares user-supplied
                // keys/firmware (Eden reports required_firmware=2) fails closed
                // here instead of booting into an undecryptable state. Nothing
                // is ever bundled: user files are copied into the app-private
                // per-engine root, exactly like LibretroEngineSpec.installSystem.
                phaseStarted = SystemClock.uptimeMillis();
                File system = NativeAdapterSystemDirectory.resolve(appContext,
                        entry.id, request.systemId, capabilities.requiredFirmware);
                logLaunchPhase("system-directory", phaseStarted);
                phaseStarted = SystemClock.uptimeMillis();
                created.create();
                logLaunchPhase("adapter-create", phaseStarted);
                phaseStarted = SystemClock.uptimeMillis();
                created.loadContent(system, saveDirectory, game.getPath());
                logLaunchPhase("content-load", phaseStarted);
                host = created;

                inputRouter = new InputRouter(DeviceCatalog.standard(),
                        new FileRemapStore(new File(appContext.getFilesDir(),
                                "controls/remaps.properties")),
                        AndroidGamingDeviceDetector.isKnownGamingHandheld());
                inputRouter.setGame(request.systemId, gameIdentity);
                refreshDevices();

                prepared = true;
                startRenderThread();
                boolean quickResume = NativeAdapterStopPolicy.reportsQuickResume(
                        entry.id, capabilities.hasQuickResume);
                // A false Quick Resume is never advertised for this engine.
                callback.onRestoreAvailabilityChanged(
                        quickResume && hasRestorableState());
                callback.onSessionReady();
                Log.i(TAG, "Adapter ready engine=" + entry.id + " system=" +
                        request.systemId + " quickResume=" +
                        quickResume + " persistentSave=" +
                        capabilities.hasPersistentSave + " dualScreen=" +
                        capabilities.dualScreen + " elapsedMs=" +
                        (SystemClock.uptimeMillis() - prepareStartedUptimeMs));
            } catch (Throwable failure) {
                releaseSecondaryDisplay();
                closeHost();
                // A session that never started must not keep the focus its
                // aborted preparation took, or every other app stays ducked.
                audioFocus.abandon();
                Log.e(TAG, "Unable to prepare adapter engine=" + entry.id +
                        " system=" + request.systemId, failure);
                callback.onSessionError("EmuFusion could not start " + entry.id + ".", failure);
            }
        });
    }

    private void logLaunchPhase(String phase, long phaseStartedUptimeMs) {
        long now = SystemClock.uptimeMillis();
        Log.i(TAG, "Launch phase engine=" + entry.id + " system=" +
                (request == null ? "?" : request.systemId) + " phase=" + phase +
                " phaseMs=" + (now - phaseStartedUptimeMs) + " totalMs=" +
                (now - prepareStartedUptimeMs));
    }

    private void startRenderThread() {
        Thread thread = new Thread(this::renderLoop, "lucent-phase3-render");
        thread.setDaemon(true);
        renderThread = thread;
        thread.start();
    }

    /** Wall-clock of the last speed line, so the log stays readable at 60fps. */
    private long lastSpeedReportUptimeMs;
    private static final long SPEED_REPORT_INTERVAL_MS = 2000L;

    /**
     * Runs once, on the render owner, the first time the engine reports a
     * non-zero emulated frame rate -- i.e. the first moment the guest is
     * demonstrably advancing rather than still loading.
     *
     * <p>The in-window host uses it to drop the black curtain it holds over the
     * gameplay layer. That curtain exists because a SurfaceView punches a
     * transparent hole through this window: until the engine has published a
     * frame, its layer has no buffer, and what shows through the hole is the
     * still-attached Qt library. Nothing else in Lucent needs this, so it stays
     * off {@link EngineSession.Listener}.
     */
    void setFirstFrameCallback(Runnable callback) {
        firstFrameCallback = callback;
    }

    /**
     * Parks the render owner and drops the surface, and does not return until
     * the owner has observed both.
     *
     * <p>A SurfaceView disconnects its Surface as soon as
     * {@code surfaceDestroyed} returns, so the caller on the UI thread has to
     * know that no frame is in flight against it. The queued barrier gives
     * exactly that: the render loop drains its task queue at the top of each
     * pass, so once the barrier has run, any pass that read the old surface has
     * already finished and the next one will park on the null.
     */
    void detachSurfaceAndWait() {
        surface = null;
        runOnRenderThread(() -> { });
    }

    /**
     * Logs the engine's own averaged emulated-frame rate once every two
     * seconds.
     *
     * <p>Deliberately the engine's counter and not a present-rate: a surface
     * swapping at the panel refresh says nothing about whether the guest
     * advanced, so a "runs at 60fps" claim measured from presents would be
     * meaningless. An adapter that publishes no hook logs nothing at all
     * rather than a misleading zero.
     */
    private void reportEngineSpeed(NativeAdapterHost active) {
        long now = android.os.SystemClock.uptimeMillis();
        boolean awaitingFirstFrame = firstFrameCallback != null;
        // The first-frame signal must not inherit the log throttle: a curtain
        // held for up to two extra seconds after the game is already running is
        // a visible stall.
        if (!awaitingFirstFrame &&
                now - lastSpeedReportUptimeMs < SPEED_REPORT_INTERVAL_MS) return;
        double fps;
        try {
            fps = active.averageFps();
        } catch (Throwable ignored) {
            return;
        }
        if (!NativeAdapterHost.isMeasuredFps(fps)) return;
        if (awaitingFirstFrame && fps > 0.0) {
            Log.i(TAG, "First guest frame engine=" + entry.id + " system=" +
                    (request == null ? "?" : request.systemId) + " totalMs=" +
                    (now - prepareStartedUptimeMs));
            Runnable callback = firstFrameCallback;
            firstFrameCallback = null;
            if (callback != null) runQuietly(callback);
        }
        if (now - lastSpeedReportUptimeMs < SPEED_REPORT_INTERVAL_MS) return;
        lastSpeedReportUptimeMs = now;
        Log.i(TAG, "engine speed engine=" + entry.id + " system=" +
                (request == null ? "?" : request.systemId) +
                " averageGameFps=" + String.format(java.util.Locale.US, "%.1f", fps));
    }

    /** The single render owner: every adapter surface/frame/audio call runs here. */
    private void renderLoop() {
        try {
            // stopping is the one-shot Stop ownership flag, not permission to
            // abandon queued final work. PS3 Quick Resume is deliberately
            // serialized on this same owner after stopping becomes true; the
            // lifecycle thread ends the loop by clearing prepared only after
            // that task has either committed or failed.
            while (prepared && !released.get()) {
                // Before the surface and resume checks, so a pause, a resume or
                // a surface rebind still lands while the loop is parked.
                drainRenderTasks();
                Surface current = surface;
                if (!resumeRequested || current == null || !current.isValid()) {
                    sleepQuietly(IDLE_TICK_MS);
                    continue;
                }
                NativeAdapterHost active = host;
                if (active == null) break;
                if (!started) {
                    if (!secondaryReadyToStart()) {
                        sleepQuietly(IDLE_TICK_MS);
                        continue;
                    }
                    Surface lower = secondarySurface;
                    long startPhase = SystemClock.uptimeMillis();
                    active.start(current, lower);
                    logLaunchPhase("engine-start", startPhase);
                    started = true;
                    restoreQuickResume(active);
                    ensureAudioTrack();
                    // start() is the only call that opens the engine's second
                    // window, and it took whatever lower surface existed at the
                    // instant it was invoked. It is a long call -- Vulkan device
                    // and swapchain creation, then the title launch -- so a
                    // Surface that arrived while it was running was published to
                    // the field but never handed to the adapter: the callback
                    // below forwards nothing until `started` is true, and by
                    // then start() has already read its copy. Reconciling here
                    // closes that window for good, and costs nothing when the
                    // two agree, which after the wait above they almost always do.
                    Surface latest = secondarySurface;
                    if (latest != lower && current.isValid()) {
                        Log.i(TAG, "Secondary surface arrived during start; rebinding engine=" +
                                entry.id + " secondary=" + describeSecondary(latest));
                        active.surfaceRecreated(current, latest);
                    }
                }
                active.runFrame();
                drainAudioToTrack(active);
                reportEngineSpeed(active);
                sleepQuietly(RENDER_TICK_MS);
            }
        } catch (Throwable failure) {
            if (stopping.get() || released.get()) {
                Log.w(TAG, "Late render callback during quiesced stop engine=" +
                        entry.id, failure);
                return;
            }
            prepared = false;
            Listener callback = listener;
            releaseSecondaryDisplay();
            Log.e(TAG, "Adapter render loop stopped engine=" + entry.id, failure);
            if (callback != null)
                callback.onSessionError("The native adapter stopped.", failure);
        } finally {
            // Nothing else will ever run this queue, so release its waiters
            // rather than leaving a lifecycle callback on its full bound.
            abandonRenderTasks();
        }
    }

    /**
     * Whether the first {@code start()} may go ahead. Render owner only.
     *
     * <p>Answers true immediately for every single-screen session, so nothing
     * outside the Wii U path pays for this at all: {@code secondaryDisplayRequested}
     * is set only when the engine itself reported {@code dual_screen} AND the
     * router accepted the lower display. When it is set, the second window has
     * to be in hand before the engine is told about its windows, because it is
     * never told again -- see {@link #SECONDARY_SURFACE_WAIT_MS}.
     */
    private boolean secondaryReadyToStart() {
        if (!secondaryDisplayRequested) return true;
        Surface lower = secondarySurface;
        long now = SystemClock.uptimeMillis();
        if (secondaryWaitBeganUptimeMs == 0L) secondaryWaitBeganUptimeMs = now;
        if (lower != null && lower.isValid()) {
            Log.i(TAG, "Starting with the GamePad view attached engine=" + entry.id +
                    " secondary=" + describeSecondary(lower) + " waitedMs=" +
                    (now - secondaryWaitBeganUptimeMs));
            return true;
        }
        if (now - secondaryWaitBeganUptimeMs < SECONDARY_SURFACE_WAIT_MS) return false;
        // Fail forward, never hang: a launch must still happen without a second
        // display. If its Surface turns up afterwards, onSecondarySurfaceAvailable
        // rebinds it, because by then `started` is true.
        Log.w(TAG, "Secondary gameplay surface did not arrive within " +
                SECONDARY_SURFACE_WAIT_MS + "ms; starting single-window engine=" +
                entry.id + " system=" + (request == null ? "?" : request.systemId));
        return true;
    }

    private String describeSecondary(Surface value) {
        if (value == null) return "none";
        String size = secondarySurfaceSize;
        return size.isEmpty() ? "attached" : size;
    }

    @Override public void attachSurface(Surface value, int width, int height) {
        voidDimensions(width, height);
        surface = value;
        NativeAdapterHost active = host;
        if (prepared && started && active != null && value != null && value.isValid())
            runOnRenderThread(() -> active.surfaceRecreated(value, secondarySurface));
    }

    @Override public void resizeSurface(int width, int height) {
        voidDimensions(width, height);
        Surface current = surface;
        NativeAdapterHost active = host;
        if (prepared && started && active != null && current != null && current.isValid())
            runOnRenderThread(() -> active.surfaceRecreated(current, secondarySurface));
    }

    @Override public void detachSurface() {
        surface = null;
    }

    @Override public void onSecondarySurfaceAvailable(Surface value, int width, int height) {
        voidDimensions(width, height);
        secondarySurface = value;
        secondarySurfaceSize = width + "x" + height;
        NativeAdapterHost active = host;
        Surface current = surface;
        boolean live = prepared && started && active != null &&
                current != null && current.isValid();
        Log.i(TAG, "Secondary gameplay surface available engine=" + entry.id +
                " size=" + width + "x" + height + " started=" + started +
                " delivery=" + (live ? "rebind" : "start"));
        if (live) runOnRenderThread(() -> active.surfaceRecreated(current, value));
    }

    @Override public void onSecondarySurfaceDestroyed() {
        secondarySurface = null;
        NativeAdapterHost active = host;
        Surface current = surface;
        if (prepared && started && active != null && current != null && current.isValid())
            runOnRenderThread(() -> active.surfaceRecreated(current, null));
    }

    @Override public void onSecondaryTouch(float normalizedX, float normalizedY,
                                           boolean pressed) {
        NativeAdapterHost active = host;
        if (active == null || !started) return;
        active.setControl(19, normalizedX);       // LUCENT_PAD_TOUCH_X
        active.setControl(20, normalizedY);       // LUCENT_PAD_TOUCH_Y
        active.setControl(21, pressed ? 1f : 0f); // LUCENT_PAD_TOUCH_PRESSED
    }

    @Override public void resume() {
        resumeRequested = true;
        // Must mirror pause(): pause() puts the ENGINE into its paused state,
        // and restarting only this loop leaves the engine paused forever.
        //
        // That asymmetry froze Switch games a few minutes in. Eden's audio pump
        // only pulls while the system is unpaused, so a still-paused engine
        // stops draining the guest's audio queue; the queue backs up, the guest
        // stops advancing, and the emulated CPU threads spin -- 229% CPU, zero
        // presented frames, and no response to input, with no crash to point at.
        // Set resumeRequested first so the loop is live before the engine is.
        NativeAdapterHost active = host;
        if (started && active != null) runOnRenderThread(active::resume);
        // Re-acquires focus this session gave up when it went to the
        // background, or lost permanently to another app while it was there.
        audioFocus.request();
        AudioTrack audio = audioTrack;
        if (audio != null && audioStartedOnce)
            try { audio.play(); } catch (IllegalStateException ignored) {}
    }

    @Override public void pause(PauseReason reason) {
        resumeRequested = false;
        NativeAdapterHost active = host;
        if (started && active != null) runOnRenderThread(active::pause);
        AudioTrack audio = audioTrack;
        if (audio != null) try { audio.pause(); } catch (IllegalStateException ignored) {}
        // Kept across a Lucent-menu pause: this is still the foreground game.
        // Given back when Android backgrounds it, which is the point another
        // app expects to be able to take it.
        if (reason == PauseReason.ANDROID_BACKGROUND) audioFocus.abandon();
    }

    private void silenceForAudioFocusLoss() {
        // Nothing here attenuates the track: EmuFusion produces no sound at all
        // while another app owns the output, and drainAudioToTrack keeps
        // draining the guest queue and discards it so the guest never stalls.
        AudioTrack audio = audioTrack;
        if (audio != null) try { audio.pause(); } catch (IllegalStateException ignored) {}
    }

    private void resumeAfterAudioFocusGain() {
        // Only if the session was actually running. Focus can come back while
        // the game sits paused in the Lucent menu, and restarting the track
        // there would play over a menu the player is still reading.
        AudioTrack audio = audioTrack;
        if (audio != null && audioStartedOnce && resumeRequested)
            try { audio.play(); } catch (IllegalStateException ignored) {}
    }

    @Override public void quiesceForExit() {
        resumeRequested = false;
        NativeAdapterHost active = host;
        if (started && active != null) runOnRenderThread(active::pause);
        AudioTrack audio = audioTrack;
        if (audio != null) try { audio.pause(); } catch (IllegalStateException ignored) {}
        Log.i(TAG, "Render loop quiesced before library reveal engine=" + entry.id +
                " system=" + (request == null ? "" : request.systemId));
    }

    @Override public boolean openControls() {
        if (!(context instanceof Activity) || inputRouter == null) return false;
        Activity activity = (Activity) context;
        activity.runOnUiThread(() -> new AlertDialog.Builder(context)
                .setTitle("Controls")
                .setMessage("Controller mapping for " + entry.id + " uses Lucent's shared layout.")
                .setPositiveButton("Done", null).show());
        return true;
    }

    @Override public boolean openRestoreHistory() {
        if (!(context instanceof Activity) || capabilities == null ||
                !capabilities.hasQuickResume || !hasRestorableState()) return false;
        ((Activity) context).runOnUiThread(() -> new AlertDialog.Builder(context)
                .setTitle("Quick Resume")
                .setMessage("A verified checkpoint is available for this game. " +
                        "It is restored automatically when the game starts.")
                .setPositiveButton("Done", null).show());
        return true;
    }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        NativeAdapterHost active = host;
        if (!started || active == null || inputRouter == null || event == null ||
                (event.getAction() != KeyEvent.ACTION_DOWN &&
                 event.getAction() != KeyEvent.ACTION_UP)) return false;
        GamepadDescriptor pad = device(event.getDeviceId());
        if (pad == null) { refreshDevices(); pad = device(event.getDeviceId()); }
        if (pad == null) return false;
        try {
            CanonicalControl control = inputRouter.resolve(pad,
                    InputSignal.key(event.getKeyCode()));
            int ordinal = controlOrdinal(control);
            if (ordinal < 0) return false;
            boolean pressed = event.getAction() == KeyEvent.ACTION_DOWN;
            active.setControl(ordinal, pressed ? 1f : 0f);
            if (pressed && event.getRepeatCount() == 0) {
                Log.i(TAG, "Adapter input engine=" + entry.id + " control=" +
                        control + " ordinal=" + ordinal + " deviceId=" +
                        event.getDeviceId());
            }
            return true;
        } catch (Exception ignored) { return false; }
    }

    @Override public boolean dispatchGenericMotionEvent(MotionEvent event) {
        NativeAdapterHost active = host;
        InputDevice inputDevice = event == null ? null : event.getDevice();
        if (!started || active == null || event.getAction() != MotionEvent.ACTION_MOVE ||
                inputRouter == null || inputDevice == null) return false;
        active.setControl(PAD_LSTICK_X, normalizeAxis(event, MotionEvent.AXIS_X));
        active.setControl(PAD_LSTICK_Y, normalizeAxis(event, MotionEvent.AXIS_Y));
        int rightX = inputDevice.getMotionRange(MotionEvent.AXIS_Z, event.getSource()) != null
                ? MotionEvent.AXIS_Z : MotionEvent.AXIS_RX;
        int rightY = inputDevice.getMotionRange(MotionEvent.AXIS_RZ, event.getSource()) != null
                ? MotionEvent.AXIS_RZ : MotionEvent.AXIS_RY;
        active.setControl(PAD_RSTICK_X, normalizeAxis(event, rightX));
        active.setControl(PAD_RSTICK_Y, normalizeAxis(event, rightY));
        // The Thor's physical d-pad reports AXIS_HAT_X/Y, not DPAD key
        // events. Only sticks were forwarded here, so the d-pad was dead in
        // every native-adapter game (physically confirmed against Cemu's
        // focusless Miiverse dialog, 2026-08-16).
        float hatX = event.getAxisValue(MotionEvent.AXIS_HAT_X);
        float hatY = event.getAxisValue(MotionEvent.AXIS_HAT_Y);
        active.setControl(PAD_DPAD_LEFT, hatX <= -0.5f ? 1f : 0f);
        active.setControl(PAD_DPAD_RIGHT, hatX >= 0.5f ? 1f : 0f);
        active.setControl(PAD_DPAD_UP, hatY <= -0.5f ? 1f : 0f);
        active.setControl(PAD_DPAD_DOWN, hatY >= 0.5f ? 1f : 0f);
        int hatDirections = (hatX <= -0.5f ? 1 : 0) | (hatX >= 0.5f ? 2 : 0) |
                (hatY <= -0.5f ? 4 : 0) | (hatY >= 0.5f ? 8 : 0);
        if (hatDirections != lastHatDirections) {
            lastHatDirections = hatDirections;
            if (hatDirections != 0) {
                Log.i(TAG, "Adapter input engine=" + entry.id +
                        " control=HAT directions=" + hatDirections +
                        " deviceId=" + event.getDeviceId());
            }
        }
        return true;
    }

    private int lastHatDirections;

    @Override public boolean shouldShowOnScreenControls() {
        return inputRouter != null && inputRouter.shouldShowOnScreenControls();
    }

    @Override public boolean dispatchVirtualControl(CanonicalControl control, boolean pressed) {
        NativeAdapterHost active = host;
        int ordinal = controlOrdinal(control);
        if (!started || active == null || ordinal < 0 || !shouldShowOnScreenControls())
            return false;
        active.setControl(ordinal, pressed ? 1f : 0f);
        return true;
    }

    @Override public void stop(StopReason reason, Completion completion) {
        if (completion == null) throw new IllegalArgumentException("completion required");
        if (!stopping.compareAndSet(false, true)) {
            completion.complete();
            return;
        }
        resumeRequested = false;
        lifecycle.execute(() -> {
            try {
                NativeAdapterHost active = host;
                byte[] state = null;
                if (active != null && capabilities != null &&
                        NativeAdapterStopPolicy.reportsQuickResume(
                                entry.id, capabilities.hasQuickResume)) {
                    state = serializeQuickResumeOnRenderThread(active);
                    if (state == null || state.length == 0)
                        throw new IllegalStateException(
                                "Adapter returned no Quick Resume state");
                }
                joinRenderThread();
                if (state != null) {
                    DurableBlobStore.write(saveRamFile, state,
                            MAX_QUICK_RESUME_BYTES);
                    Log.i(TAG, "Adapter Quick Resume committed engine=" + entry.id +
                            " bytes=" + state.length + " marker=quick-resume-committed");
                }
                if (active != null && capabilities != null &&
                        capabilities.hasPersistentSave) {
                    runFlushSave(active);
                }
                detachSecondaryBeforeBlank();
                releaseAudio();
                retireHost(entry.id);
                prepared = false;
                Listener callback = listener;
                if (callback != null) callback.onRestoreAvailabilityChanged(false);
                Log.i(TAG, "Adapter save flushed and session stopped engine=" +
                        entry.id + " system=" +
                        (request == null ? "" : request.systemId));
                completion.complete();
            } catch (Throwable failure) {
                Log.e(TAG, "Adapter stop teardown failed engine=" + entry.id +
                        " marker=save-failure", failure);
                Listener callback = listener;
                if (callback != null) callback.onSessionStopRejected(
                        "The current Quick Resume point could not be saved. " +
                                "Your previous checkpoint was preserved.", failure);
                // A failed or timed-out final render task must still retire its
                // owner before native stop/destroy touches the same engine.
                prepared = false;
                joinRenderThread();
                try { releaseAudio(); } catch (Throwable ignored) {}
                try { retireHost(entry.id); } catch (Throwable ignored) {}
                prepared = false;
                completion.complete();
            }
        });
    }

    /**
     * Runs the potentially long savestate operation on the ABI's one render
     * owner and propagates its real failure to the Stop transaction.
     */
    private byte[] serializeQuickResumeOnRenderThread(NativeAdapterHost active)
            throws Exception {
        if (active == null || !prepared || renderThread == null)
            throw new IllegalStateException("Adapter render owner is unavailable");
        AtomicReference<byte[]> result = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        RenderTask task = new RenderTask(() -> {
            try { result.set(active.serialize()); }
            catch (Throwable problem) { failure.set(problem); }
        });
        renderTasks.offer(task);
        if (!task.await(QUICK_RESUME_TASK_TIMEOUT_MS))
            throw new IllegalStateException("Adapter Quick Resume timed out");
        Throwable problem = failure.get();
        if (problem instanceof Exception) throw (Exception) problem;
        if (problem != null) throw new IllegalStateException(
                "Adapter Quick Resume failed", problem);
        return result.get();
    }

    @Override public void release() {
        if (!released.compareAndSet(false, true)) return;
        resumeRequested = false;
        // Before any teardown that can block or throw: focus held past the end
        // of a session mutes every other app.
        audioFocus.abandon();
        lifecycle.execute(() -> {
            joinRenderThread();
            detachSecondaryBeforeBlank();
            releaseAudio();
            closeHost();
            prepared = false;
        });
        lifecycle.shutdown();
    }

    private void runFlushSave(NativeAdapterHost active) {
        try {
            active.flushSave();
            Log.i(TAG, "Adapter durable save committed engine=" + entry.id);
        } catch (Throwable failure) {
            Log.w(TAG, "Adapter save was not updated for " + entry.id +
                    " marker=save-failure", failure);
        }
    }

    private boolean hasRestorableState() {
        return saveRamFile != null && saveRamFile.isFile();
    }

    /** Restores once, after the engine owns a real Surface and has booted. */
    private void restoreQuickResume(NativeAdapterHost active) throws Exception {
        if (restoreAttempted || active == null || capabilities == null ||
                !capabilities.hasQuickResume || !hasRestorableState()) return;
        restoreAttempted = true;
        byte[] state = DurableBlobStore.read(saveRamFile, MAX_QUICK_RESUME_BYTES);
        if (state == null || state.length == 0)
            throw new IllegalStateException("Quick Resume checkpoint is empty");
        if (!active.unserialize(state))
            throw new IllegalStateException("Adapter rejected its Quick Resume checkpoint");
        Log.i(TAG, "Adapter Quick Resume restored engine=" + entry.id +
                " bytes=" + state.length + " marker=quick-resume-restored");
    }

    private void ensureAudioTrack() {
        if (audioTrack != null) return;
        AudioTrack track = createAudioTrack(OUTPUT_SAMPLE_RATE);
        if (track == null) {
            Log.w(TAG, "Adapter audio unavailable engine=" + entry.id);
            return;
        }
        audioTrack = track;
        audioQueue = new PcmAudioQueue(Math.max(8_192,
                adapterAudioBufferBytes(OUTPUT_SAMPLE_RATE) / 2 * 3));
        audioPrimeSamplesTarget = adapterAudioBufferBytes(OUTPUT_SAMPLE_RATE) / 2;
        primedAudioSamples = 0;
        audioStartedOnce = false;
        // Focus is taken as soon as this session owns an output, not when the
        // first sample is written; the teardown paths give it back.
        audioFocus.request();
    }

    private void drainAudioToTrack(NativeAdapterHost active) {
        AudioTrack audio = audioTrack;
        PcmAudioQueue queue = audioQueue;
        if (audio == null || queue == null) return;
        short[] samples = active.drainAudio(2048);
        // Drained first, then discarded: another app owns the output, but a
        // guest audio queue that stops being pulled backs up and freezes the
        // guest outright -- the same failure the paused-engine bug produced.
        if (audioFocus.isSuppressed()) {
            queue.clear();
            return;
        }
        if (samples.length > 0) {
            int rejected = queue.offer(samples);
            if (rejected > 0)
                Log.e(TAG, "Adapter PCM FIFO overflow engine=" + entry.id +
                        " droppedFrames=" + (rejected / 2) +
                        " marker=audio-pcm-drop");
        }
        for (int attempt = 0; attempt < 8; attempt++) {
            synchronized (queue) {
                short[] head = queue.head();
                if (head == null) break;
                int offset = queue.headOffset();
                try {
                    int written = Build.VERSION.SDK_INT >= 23
                            ? audio.write(head, offset, head.length - offset,
                                    AudioTrack.WRITE_NON_BLOCKING)
                            : audio.write(head, offset, head.length - offset);
                    if (written < 0) throw new IllegalStateException(
                            "AudioTrack write failed with code " + written);
                    if (written == 0) break;
                    queue.consume(written);
                    if (!audioStartedOnce) primedAudioSamples += written;
                } catch (Throwable failure) {
                    if (audioFailureReported.compareAndSet(false, true)) {
                        Listener callback = listener;
                        if (callback != null) callback.onSessionError(
                                "EmuFusion lost audio output for this game.", failure);
                    }
                    return;
                }
            }
        }
        if (!audioStartedOnce && resumeRequested &&
                primedAudioSamples >= audioPrimeSamplesTarget) {
            try {
                audio.play();
                audioStartedOnce = true;
                Log.i(TAG, "Adapter audio playback started engine=" + entry.id +
                        " primedSamples=" + primedAudioSamples);
            } catch (IllegalStateException failure) {
                if (audioFailureReported.compareAndSet(false, true)) {
                    Listener callback = listener;
                    if (callback != null) callback.onSessionError(
                            "EmuFusion lost audio output for this game.", failure);
                }
            }
        }
    }

    private static int adapterAudioBufferBytes(int rate) {
        int minimum = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_STEREO,
                AudioFormat.ENCODING_PCM_16BIT);
        return minimum <= 0 ? 0 : Math.max(minimum, rate / 5 * 4);
    }

    @SuppressWarnings("deprecation")
    private AudioTrack createAudioTrack(int rate) {
        int bufferBytes = adapterAudioBufferBytes(rate);
        if (bufferBytes <= 0) return null;
        // Built with explicit attributes rather than the deprecated
        // stream-type constructor, so the stream mapping is asserted rather
        // than inferred. USAGE_GAME resolves to STREAM_MUSIC, the stream the
        // volume keys move, and EmuFusion sets no gain of its own anywhere:
        // the system level is the only thing that decides how loud a game is.
        //
        // The volume curve reaches this track only while the session holds
        // audio focus, so EngineAudioFocus is load-bearing here and not
        // merely good manners. Measured on the AYN Thor with mesen-s, the
        // same game and the same output thread, by alternating STREAM_MUSIC
        // between index 12 and index 0 and reading the output thread's HAL
        // signal power:
        //
        //   without a focus request: mixer gain 0 dB at index 12 AND at
        //   index 0 with "Muted: true", HAL power -33.91 dB against
        //   -34.25 dB. The mute does nothing and the game stays audible.
        //
        //   holding AUDIOFOCUS_GAIN: mixer gain -3.8 dB at index 12, which
        //   is the platform's own curve value for that index, and -inf at
        //   index 0 with the HAL recording no signal power at all. True
        //   digital silence, five of five phases in each state.
        //
        // The dead ends are recorded so they are not walked twice. The
        // cause was NOT: the output path (forcing the low-latency output
        // instead of DEEP_BUFFER moved the track and changed nothing, at
        // the cost of startup underruns), the usage constant (USAGE_MEDIA
        // measured identically), or the Odin Game Assistant (disabling it
        // changed nothing). The stock video player, which does request
        // focus, always attenuated correctly on that same thread; that gap
        // was the clue.
        //
        // One caveat worth keeping: for roughly the first two minutes of a
        // freshly launched session the gain was still seen pinned at 0 dB
        // before it began tracking, so a report of "muted but still loud"
        // right after a launch is not automatically this bug returning.
        AudioTrack track = new AudioTrack.Builder()
                .setAudioAttributes(new android.media.AudioAttributes.Builder()
                        .setUsage(android.media.AudioAttributes.USAGE_GAME)
                        .setContentType(
                                android.media.AudioAttributes.CONTENT_TYPE_MUSIC)
                        .build())
                .setAudioFormat(new AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(rate)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_STEREO)
                        .build())
                .setBufferSizeInBytes(bufferBytes)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build();
        if (track.getState() == AudioTrack.STATE_INITIALIZED) {
            // Unity gain, always. EmuFusion must never attenuate its own
            // output: the system STREAM_MUSIC level is the single authority,
            // and an app that also scales its track fights it. Set explicitly
            // rather than relying on the default.
            AppVolumeController.registerTrack(appContext, track);
            EngineAudioLog.logResolvedStream(appContext, TAG, entry.id, track);
            return track;
        }
        track.release();
        return null;
    }

    private void releaseAudio() {
        AudioTrack audio = audioTrack;
        audioTrack = null;
        PcmAudioQueue queue = audioQueue;
        audioQueue = null;
        if (queue != null) queue.clear();
        primedAudioSamples = 0;
        audioPrimeSamplesTarget = 0;
        audioStartedOnce = false;
        audioFailureReported.set(false);
        if (audio == null) return;
        try { audio.stop(); } catch (IllegalStateException ignored) {}
        AppVolumeController.unregisterTrack(audio);
        audio.release();
    }

    private void retireHost(String engineId) {
        if (!NativeAdapterStopPolicy.destroyNativeHostOnStop(engineId)) {
            Log.w(TAG, "Retaining aPS3e native host after library return engine=" +
                    engineId + " marker=aps3e-stop-no-kill");
            host = null;
            started = false;
            return;
        }
        closeHost();
    }

    private void closeHost() {
        NativeAdapterHost active = host;
        host = null;
        started = false;
        if (active == null) return;
        try { active.stop(); } catch (Throwable ignored) {}
        try { active.close(); } catch (Throwable ignored) {}
    }

    private void joinRenderThread() {
        prepared = false;
        Thread thread = renderThread;
        renderThread = null;
        if (thread == null) return;
        try { thread.join(2_000L); }
        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
    }

    /**
     * Hands one adapter call to the render owner and waits for it.
     *
     * <p>This used to run the action on the CALLING thread after clearing
     * {@code resumeRequested}, which is not the same thing at all: clearing a
     * flag does not stop a frame that is already in flight, so a pause, a
     * resume or a surface rebind arriving from the UI thread ran straight into
     * the render thread and into each other. That broke the one promise the
     * adapter ABI makes to both engines, and it also let two overlapping calls
     * clobber {@code resumeRequested} on the way out -- leaving the engine
     * paused while this loop believed it was running, which is exactly the
     * silent freeze the {@link #resume()} comment describes. Queueing the work
     * instead means the render thread runs it between frames, in order, and
     * nothing has to be juggled.
     */
    private void runOnRenderThread(Runnable action) {
        if (action == null) return;
        if (Thread.currentThread() == renderThread) { runQuietly(action); return; }
        Thread owner = renderThread;
        if (owner == null || !owner.isAlive() || !prepared ||
                stopping.get() || released.get()) {
            // There is no render owner left to hand this to. Teardown has
            // already quiesced the loop by this point, so the caller is now the
            // only thread that can reach the adapter at all.
            runQuietly(action);
            return;
        }
        RenderTask task = new RenderTask(action);
        renderTasks.add(task);
        if (!task.await(RENDER_TASK_TIMEOUT_MS))
            Log.w(TAG, "Adapter call still queued after " + RENDER_TASK_TIMEOUT_MS +
                    "ms engine=" + entry.id);
    }

    /** Runs everything queued for the render owner. Render thread only. */
    private void drainRenderTasks() {
        RenderTask task;
        while ((task = renderTasks.poll()) != null) task.run();
    }

    private void abandonRenderTasks() {
        RenderTask task;
        while ((task = renderTasks.poll()) != null) task.abandon();
    }

    private static void runQuietly(Runnable action) {
        try { action.run(); }
        catch (Throwable failure) { Log.w(TAG, "Adapter call failed", failure); }
    }

    /** One adapter call awaiting the render owner. */
    private static final class RenderTask {
        private final Runnable action;
        private final CountDownLatch finished = new CountDownLatch(1);

        RenderTask(Runnable action) { this.action = action; }

        void run() {
            try { action.run(); }
            catch (Throwable failure) {
                Log.w(TAG, "Adapter call failed on the render owner", failure);
            } finally { finished.countDown(); }
        }

        /** The render owner is gone; wake the caller instead of stranding it. */
        void abandon() { finished.countDown(); }

        boolean await(long millis) {
            try { return finished.await(millis, TimeUnit.MILLISECONDS); }
            catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                return false;
            }
        }
    }

    private void detachSecondaryBeforeBlank() {
        if (!secondaryDisplayRequested) return;
        secondarySurface = null;
        releaseSecondaryDisplay();
    }

    private void releaseSecondaryDisplay() {
        if (!secondaryDisplayRequested) return;
        secondaryDisplayRequested = false;
        secondarySurface = null;
        SecondaryGameplaySurfaceRouter.release(appContext, this);
    }

    private synchronized void refreshDevices() {
        devices = AndroidDeviceScanner.scan();
        if (inputRouter != null) inputRouter.updateDevices(devices);
    }

    private synchronized GamepadDescriptor device(int deviceId) {
        for (GamepadDescriptor descriptor : devices)
            if (descriptor.deviceId == deviceId) return descriptor;
        return null;
    }

    private static boolean isWiiUSystem(String systemId) {
        String value = systemId == null ? "" : systemId.trim().toLowerCase(Locale.US);
        return "wiiu".equals(value) || "wii-u".equals(value);
    }

    /**
     * Hands the already-resumed Thor lower display to Wii U before mapping Cemu.
     *
     * <p>Cemu's Android library performs linker relocation, JNI setup and GPU
     * discovery when {@link NativeAdapterHost} opens it. A cold open can take
     * several seconds. Waiting until after that work (and content loading) to
     * request the GamePad surface left the lower display showing its old preview
     * throughout startup, and made runtime qualification time out before Cemu
     * could be started. This route is safe to decide without executing native
     * code: {@code entry} already passed the signed opt-in, source-commit and
     * packaged-artifact hash gates, and only the pinned {@code cemu}/{@code wiiu}
     * pair reaches this method. The adapter's capability report is reconciled
     * immediately after open and a mismatch fails closed.
     */
    private void requestPinnedWiiUSecondaryDisplay(GameLaunchRequest launch) {
        if (!isPinnedWiiUDualScreenRoute(launch)) return;
        secondaryDisplayRequested = SecondaryGameplaySurfaceRouter.request(
                appContext, launch.systemId, this);
        Log.i(TAG, "Secondary gameplay display requested before adapter open engine=" +
                entry.id + " accepted=" + secondaryDisplayRequested);
    }

    private boolean isPinnedWiiUDualScreenRoute(GameLaunchRequest launch) {
        return launch != null && "cemu".equals(entry.id) &&
                "cemu".equals(launch.engineId) && isWiiUSystem(launch.systemId);
    }

    private int controlOrdinal(CanonicalControl control) {
        if (control == null) return -1;
        /*
         * Canonical face controls describe physical positions, not the letters
         * printed by a particular console. Switch and Wii U use Nintendo's
         * right=A/bottom=B/top=X/left=Y layout. The old generic Xbox ordering
         * sent Thor's printed A as native B and printed B as native A, which
         * made Eden appear to ignore the "Press A" screen even after its player
         * was connected. Keep the positional Xbox ordering for the remaining
         * native adapters, and translate the two Nintendo adapters explicitly.
         */
        boolean nintendoFaceLayout = "eden".equals(entry.id) ||
                "cemu".equals(entry.id);
        switch (control) {
            case SOUTH: return nintendoFaceLayout ? PAD_B : PAD_A;
            case EAST: return nintendoFaceLayout ? PAD_A : PAD_B;
            case WEST: return nintendoFaceLayout ? PAD_Y : PAD_X;
            case NORTH: return nintendoFaceLayout ? PAD_X : PAD_Y;
            case L1: return PAD_L;
            case R1: return PAD_R;
            case L2: return PAD_ZL;
            case R2: return PAD_ZR;
            case DPAD_UP: return PAD_DPAD_UP;
            case DPAD_DOWN: return PAD_DPAD_DOWN;
            case DPAD_LEFT: return PAD_DPAD_LEFT;
            case DPAD_RIGHT: return PAD_DPAD_RIGHT;
            case START: return PAD_START;
            case SELECT: return PAD_SELECT;
            case GUIDE: return PAD_HOME;
            default: return -1;
        }
    }

    private static float normalizeAxis(MotionEvent event, int axis) {
        float value = event.getAxisValue(axis);
        float magnitude = Math.abs(value);
        if (magnitude <= AXIS_DEAD_ZONE) return 0f;
        return Math.copySign(Math.min(1f,
                (magnitude - AXIS_DEAD_ZONE) / (1f - AXIS_DEAD_ZONE)), value);
    }

    private static void sleepQuietly(long millis) {
        try { Thread.sleep(millis); }
        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
    }

    private static File resolveGameFile(Uri uri) throws Exception {
        if (uri == null) throw new IllegalArgumentException("content URI is missing");
        String raw = "file".equals(uri.getScheme()) ? uri.getPath() :
                uri.getQueryParameter("path");
        if (raw == null || raw.trim().isEmpty())
            throw new IllegalArgumentException("content URI does not expose a local file");
        File file = new File(raw).getCanonicalFile();
        String path = file.getPath();
        if (!(path.startsWith("/storage/") || path.startsWith("/mnt/media_rw/")) ||
                !file.isFile())
            throw new IllegalArgumentException("game is outside approved Android storage");
        return file;
    }

    private static String launchIdentity(GameLaunchRequest request, File file)
            throws Exception {
        if (request == null || file == null)
            throw new IllegalArgumentException("launch identity requires request and file");
        java.security.MessageDigest digest =
                java.security.MessageDigest.getInstance("SHA-256");
        String identity = request.engineId + "\n" + request.systemId + "\n" +
                request.gameId + "\n" + file.getCanonicalPath() + "\n" + file.length();
        digest.update(identity.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        StringBuilder result = new StringBuilder(64);
        for (byte value : digest.digest())
            result.append(String.format(Locale.US, "%02x", value & 0xff));
        return result.substring(0, 32);
    }

    private static String contentSha256Short(File file) throws Exception {
        java.security.MessageDigest digest =
                java.security.MessageDigest.getInstance("SHA-256");
        java.io.InputStream input = new java.io.FileInputStream(file);
        try {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) digest.update(buffer, 0, count);
        } finally { input.close(); }
        StringBuilder result = new StringBuilder(64);
        for (byte value : digest.digest())
            result.append(String.format(Locale.US, "%02x", value & 0xff));
        return result.substring(0, 32);
    }

    private static void voidDimensions(int width, int height) {
        if (width < 0 || height < 0)
            throw new IllegalArgumentException("surface dimensions cannot be negative");
    }
}
