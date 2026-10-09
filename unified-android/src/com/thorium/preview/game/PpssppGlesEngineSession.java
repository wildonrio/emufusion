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
import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.lucent.cheats.CheatSelection;
import com.thorium.lucent.input.DeviceCatalog;
import com.thorium.lucent.input.FileRemapStore;
import com.thorium.lucent.input.GamepadDescriptor;
import com.thorium.lucent.input.InputRouter;
import com.thorium.lucent.input.InputSignal;
import com.thorium.lucent.input.JoypadPressLedger;
import com.thorium.lucent.input.LibretroJoypadLayout;
import com.thorium.lucent.input.SystemControlLayouts;
import com.thorium.lucent.input.WiiIrPointer;
import com.thorium.lucent.input.android.AndroidDeviceScanner;
import com.thorium.lucent.input.android.AndroidGamingDeviceDetector;
import com.thorium.lucent.audio.PcmAudioQueue;
import com.thorium.lucent.state.CheckpointScheduler;
import com.thorium.lucent.state.DurableBlobStore;
import com.thorium.lucent.state.SnapshotKind;
import com.thorium.lucent.state.QuickResumePolicy;
import com.thorium.lucent.state.StateIdentity;
import com.thorium.lucent.state.StateLoadResult;
import com.thorium.lucent.state.StateSnapshot;
import com.thorium.lucent.state.StateVault;
import com.thorium.lucent.video.DualScreenLayout;
import com.thorium.lucent.video.PresentationGeometry;
import com.thorium.preview.ExperimentalGlesRenderLoop;
import com.thorium.preview.AppVolumeController;
import com.thorium.preview.SecondaryGameplaySurfaceRouter;
import com.thorium.preview.cheats.CheatControl;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.security.MessageDigest;
import java.text.DateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.EnumMap;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Explicit, qualification-only hardware-capable libretro route. */
final class PpssppGlesEngineSession implements EngineSession,
        SecondaryGameplaySurfaceRouter.Listener,
        com.thorium.lucent.netplay.NetplayCapableSession {
    private static final String TAG = "LucentPhase2Engine";
    private static final float AXIS_DEAD_ZONE = 0.08f;
    private static final float AXIS_PRESS = 0.55f;
    private static final int MAX_SAVE_RAM_BYTES = 64 * 1024 * 1024;

    private final Context context;
    private final Context appContext;
    private final LibretroEngineSpec entry;
    private final ExecutorService lifecycle = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "lucent-phase2-lifecycle");
        thread.setDaemon(true);
        return thread;
    });
    private final AtomicBoolean stopping = new AtomicBoolean(false);
    private final Object stopLock = new Object();
    private final List<Completion> stopCompletions = new ArrayList<>();
    private boolean stopCompleted;
    private boolean destroyStopRequested;
    private final AtomicBoolean released = new AtomicBoolean(false);
    private final Object releaseLock = new Object();
    private final List<Completion> releaseCompletions = new ArrayList<>();
    private boolean releaseCompleted;
    private final AtomicBoolean audioFailureReported = new AtomicBoolean(false);
    private final AtomicBoolean backgroundCaptureRequested = new AtomicBoolean(false);

    private volatile Listener listener;
    private volatile ExperimentalGlesRenderLoop renderLoop;
    private volatile Surface surface;
    private volatile Surface secondarySurface;
    private volatile boolean secondaryDisplayRequested;
    private volatile boolean prepared;
    private volatile boolean resumeRequested;
    private final ThreeDsPhoneStylus phoneStylus = new ThreeDsPhoneStylus();
    private volatile double declaredVideoHz;
    /**
     * True when the GLES bridge deliberately publishes only core-attested
     * source boundaries instead of every libretro AV tick. The Surface PTS is
     * still stamped on the immutable core clock, but skipped carrier ticks are
     * then proven non-presenting intervals rather than lost SurfaceTexture
     * buffers. They must not be fed to DisplayFrameGenerator's every-tick
     * transport-loss detector.
     */
    private volatile boolean filteredSourceTimeline;
    private volatile AudioTrack audioTrack;
    /**
     * The focus this session holds while it plays. Declared final and built in
     * the constructor so no teardown path can reach a null one and leak focus.
     */
    private final EngineAudioFocus audioFocus;
    private volatile byte[] pendingQuickResume;
    private final AtomicBoolean quickResumeApplied = new AtomicBoolean(false);
    private StateVault vault;
    private StateIdentity identity;
    private GameLaunchRequest request;
    private volatile boolean wiiIrEnabled;
    private CheckpointScheduler checkpointScheduler;
    private InputRouter inputRouter;
    // Several physical sources can mean one libretro ID (hat, left stick,
    // BTN_DPAD_* keys). The ledger ORs them so releasing one never clears a
    // direction another source is still holding.
    private final JoypadPressLedger joypad = new JoypadPressLedger();
    private final WiiIrPointer wiiIrPointer = new WiiIrPointer();
    /**
     * Null unless a netplay match is active for this session -- see
     * LibretroEngineSession.attachNetplayRelay's doc comment for the
     * full contract, mirrored here identically. Declared before
     * joypadSink: javac rejects joypadSink's lambda body reading this
     * field's simple name otherwise, even though the lambda only runs
     * later (same forward-reference rule as joypad/wiiIrPointer ordering
     * relative to other fields in this class).
     */
    private volatile com.thorium.lucent.netplay.NetplayInputRelay netplayRelay;
    private final JoypadPressLedger.Sink joypadSink = (retroId, pressed) -> {
        ExperimentalGlesRenderLoop active = renderLoop;
        if (active != null) active.setJoypadButton(0, retroId, pressed);
        com.thorium.lucent.netplay.NetplayInputRelay relay = netplayRelay;
        if (relay != null) relay.onLocalJoypadButton(retroId, pressed);
    };

    public void attachNetplayRelay(com.thorium.lucent.netplay.NetplayInputRelay relay) {
        this.netplayRelay = relay;
    }

    public void detachNetplayRelay() {
        this.netplayRelay = null;
    }

    /**
     * The netplay integration point, mirroring LibretroEngineSession's
     * method of the same name -- see its doc comment for the full
     * rationale (native 8-port support, thread-safety, why callbacks
     * aren't routed through the UI thread first).
     */
    public void applyRemoteJoypadButton(int port, int retroId, boolean pressed) {
        if (port < 1 || port > 7)
            throw new IllegalArgumentException("remote port must be 1..7; port 0 is local input");
        ExperimentalGlesRenderLoop active = renderLoop;
        if (active != null) active.setJoypadButton(port, retroId, pressed);
    }

    public void applyRemoteAnalogAxis(int port, int retroAnalogIndex, int retroAnalogId,
                                       float normalizedValue) {
        if (port < 1 || port > 7)
            throw new IllegalArgumentException("remote port must be 1..7; port 0 is local input");
        ExperimentalGlesRenderLoop active = renderLoop;
        if (active != null) active.setAnalogAxis(port, retroAnalogIndex, retroAnalogId, normalizedValue);
    }

    /** {@link com.thorium.lucent.netplay.NetplayCapableSession}: the same serialize() Quick Resume already uses. */
    public byte[] currentSerializedStateForDesync() {
        ExperimentalGlesRenderLoop active = renderLoop;
        if (active == null) return null;
        try {
            byte[] state = active.serialize();
            return state != null && state.length > 0 ? state : null;
        } catch (Throwable ignored) {
            return null;
        }
    }
    private List<GamepadDescriptor> devices = new ArrayList<>();
    private final AtomicBoolean checkpointPending = new AtomicBoolean(false);
    private File saveRamFile;
    private long activePlayMillis;
    private long activeStartedMillis;
    private long activeFrameTickMillis;
    /** PCM drained from the core but not yet accepted by the non-blocking sink. */
    private volatile PcmAudioQueue audioQueue;
    private int primedAudioSamples;
    private int audioPrimeSamplesTarget;
    private volatile boolean audioStartedOnce;
    private final Object cheatLock = new Object();
    private CheatSelection cheats;
    private String cheatGameKey = "";
    private long audioStartedAtMillis;
    private boolean steadyAudioBufferApplied;
    private boolean audioSilenceWarned;
    private long presentedFrames;
    private volatile Runnable firstFrameCallback;
    private long frameSampleStartedAtMillis;
    private long receivedAudioFrames;
    private long writtenAudioFrames;
    private long droppedAudioFrames;
    private boolean audioDropLogged;

    PpssppGlesEngineSession(Context context, Phase2QualificationCatalog.Entry entry) {
        this(context, LibretroEngineSpec.phaseTwo(entry));
    }

    PpssppGlesEngineSession(Context context, InternalEngineCatalog.Entry entry) {
        this(context, LibretroEngineSpec.phaseOne(entry));
    }

    private PpssppGlesEngineSession(Context context, LibretroEngineSpec entry) {
        if (context == null || entry == null)
            throw new IllegalArgumentException("context and Phase 2 entry are required");
        this.context = context;
        appContext = context.getApplicationContext();
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
        wiiIrEnabled = isWiiSystem(request.systemId);
        lifecycle.execute(() -> {
            try {
                if (!entry.id.equals(request.engineId) || !entry.supports(request.systemId))
                    throw new IllegalStateException("Phase 2 engine does not support " +
                            request.systemId);
                if (!entry.isInstalled(appContext))
                    throw new IllegalStateException("Internal engine identity changed");
                if (stopping.get() || released.get()) return;
                File game = resolveGameFile(request.contentUri);
                DiscImagePreflight.validate(request.systemId, game);
                LibretroEngineSpec.SystemInstallation runtime =
                        entry.installRuntime(appContext, request.systemId);
                File system = runtime.directory;
                String gameHash = GameContentIdentityCache.sha256(appContext, game);
                prepareCheats(request, game.getName(), discGameIdentity(request.systemId, game));
                String saveRoot = request.qualificationSession.isEmpty() ?
                        "engine-saves" :
                        "engine-saves-qa/" + request.qualificationSession;
                File saves = new File(appContext.getFilesDir(),
                        saveRoot + "/" + entry.id + "/" +
                                gameHash.substring(0, 32));
                if (!saves.isDirectory() && !saves.mkdirs())
                    throw new IllegalStateException("Cannot create engine save directory");
                if (!request.qualificationSession.isEmpty())
                    Log.i(TAG, "Isolated qualification runtime state engine=" +
                            entry.id + " namespace=" + request.qualificationSession);
                String engineIdentity = entry.sourceCommit + ":sha256:" +
                        entry.coreArtifactSha256;
                if (!request.qualificationSession.isEmpty())
                    engineIdentity += ":qa:" + request.qualificationSession;
                identity = new StateIdentity(gameHash, gameHash, entry.id,
                        engineIdentity,
                        "phase2-libretro-serialize-v" +
                                entry.stateCompatibilityVersion,
                        runtime.firmwareIdentity);
                vault = StateVault.shared(new File(appContext.getFilesDir(),
                        "phase2-state-vault"));
                saveRamFile = new File(saves, "save-ram.bin");
                if (QuickResumePolicy.allowsRuntimeRestore(entry.id)) {
                    StateLoadResult quick = vault.loadQuickResume(identity);
                    if (quick.status == StateLoadResult.Status.OK) {
                        pendingQuickResume = quick.state;
                        activePlayMillis = quick.snapshot.metadata.activePlayMillis;
                    } else if (quick.status != StateLoadResult.Status.NOT_FOUND) {
                        Log.w(TAG, "Ignoring incompatible or invalid Quick Resume: " +
                                quick.status + " " + quick.detail);
                    }
                } else {
                    // Do not read the potentially huge state into Java merely
                    // to discard it.  The immutable snapshot remains in the
                    // vault; only the unsafe application step is quarantined.
                    Log.w(TAG, "Runtime state restore is quarantined; cold booting engine=" +
                            entry.id + " marker=state-restore-quarantined");
                }
                checkpointScheduler = new CheckpointScheduler(
                        CheckpointScheduler.DEFAULT_INTERVAL_MILLIS, activePlayMillis);
                inputRouter = new InputRouter(DeviceCatalog.standard(),
                        new FileRemapStore(new File(appContext.getFilesDir(),
                                "controls/remaps.properties")),
                        AndroidGamingDeviceDetector.isKnownGamingHandheld());
                inputRouter.setGame(request.systemId, gameHash);
                refreshDevices();
                ExperimentalGlesRenderLoop.Listener renderListener =
                        new ExperimentalGlesRenderLoop.Listener() {
                            @Override public void onReady() {
                                lifecycle.execute(() -> handleReady(callback));
                            }

                            @Override public void onFramePresented() {
                                Runnable first = firstFrameCallback;
                                firstFrameCallback = null;
                                if (first != null) try { first.run(); }
                                catch (Throwable ignored) {}
                                ExperimentalGlesRenderLoop active = renderLoop;
                                if (active != null) {
                                    // Hardware cores can defer their real game
                                    // boot until the first retro_run after a GL
                                    // context exists (Play! does). Restoring in
                                    // attachSurface lets that lazy boot erase a
                                    // successfully accepted snapshot. Apply it
                                    // at this first post-boot frame boundary.
                                    // PPSSPP's retro_serialize_size() pauses
                                    // its GLES emulation thread by design.
                                    // Probe readiness only while a snapshot is
                                    // genuinely pending; probing every frame
                                    // after the one-shot restore would pause
                                    // the core again with no unserialize call
                                    // left to restart it.
                                    if (pendingQuickResume != null &&
                                            active.stateReady())
                                        restoreQuickResume(active);
                                    // Always drain the native ring. A partial
                                    // AudioTrack write must never prevent later
                                    // PCM from crossing into the bounded Java
                                    // FIFO, otherwise the native ring silently
                                    // overwrites audio during JIT/render stalls.
                                    presentAudio(active.drainAudio(2048));
                                    recordFrameHealth();
                                    recordActiveProgress(active);
                                }
                            }

                            @Override public void onFrameExecutedWithoutPresentation() {
                                ExperimentalGlesRenderLoop active = renderLoop;
                                if (active != null) {
                                    // A core can produce PCM before its first image
                                    // (N64 boot) or on a step with no new picture.
                                    // Drain every executed guest step for every
                                    // hardware core; waiting for a swap strands
                                    // startup PCM and overflows the bounded FIFO.
                                    presentAudio(active.drainAudio(2048));
                                    recordActiveProgress(active);
                                }
                            }

                            @Override public void onContextLost() {
                                Surface current = surface;
                                ExperimentalGlesRenderLoop active = renderLoop;
                                if (active != null && current != null && current.isValid())
                                    active.recreateSurface(current);
                            }

                            @Override public void onError(Throwable failure) {
                                if (stopping.get() || released.get()) {
                                    // Exit owns a render-thread quiescence barrier
                                    // before the UI transition. A callback already
                                    // in flight must not invalidate the prepared
                                    // state needed for the mandatory final snapshot;
                                    // serialize/commit still fails closed on its own.
                                    Log.w(TAG, "Late renderer callback during quiesced stop " +
                                            "engine=" + entry.id, failure);
                                    return;
                                }
                                prepared = false;
                                releaseSecondaryDisplay();
                                Log.e(TAG, "Renderer stopped engine=" + entry.id +
                                        " system=" + request.systemId, failure);
                                callback.onSessionError(
                                        "The experimental renderer stopped.", failure);
                            }
                        };
                // GLideN64 honors get_current_framebuffer(), so N64 must use
                // the frontend FBO path: direct-window presentation let the
                // core draw through its own 2880x2880 viewport into the
                // 1920x1080 window, pushing gameplay off-center to the left
                // with the right edge cropped (818adab8 N64 evidence).
                final int presentationPolicy = ("flycast".equals(entry.id) ||
                        "ppsspp".equals(entry.id) ||
                        "mupen64plus-next".equals(entry.id) ||
                        "dolphin".equals(entry.id)) ?
                        com.thorium.preview.ExperimentalGlesLibretroHost
                                .PRESENT_FRONTEND_FBO :
                        com.thorium.preview.ExperimentalGlesLibretroHost
                                .PRESENT_DIRECT_WINDOW;
                /* Only the user-requested frame-generation path asks Mupen to
                 * identify game presents at VI-origin changes. Frame
                 * Generation Off retains the established VI-update behavior
                 * for maximum compatibility, and every non-N64 engine stays
                 * on the ordinary source timeline. The content-bounds crop
                 * bit is a separate concern (2026-09-06): a frontend-FBO
                 * GLideN64 target always pads its sentinel-cleared
                 * allocation around the core's real VI rectangle, so N64
                 * needs that crop whether or not frame generation is
                 * running -- it is not folded into the frame-generation
                 * gate above. */
                final int sourceTimelinePolicy =
                        ("mupen64plus-next".equals(entry.id) ?
                                com.thorium.preview.ExperimentalGlesLibretroHost
                                        .SOURCE_TIMELINE_MUPEN_CONTENT_BOUNDS :
                                com.thorium.preview.ExperimentalGlesLibretroHost
                                        .SOURCE_TIMELINE_DEFAULT) |
                        ("mupen64plus-next".equals(entry.id) &&
                                request.frameGenerationMode !=
                                        FrameGenerationSettings.Mode.OFF ?
                        com.thorium.preview.ExperimentalGlesLibretroHost
                                .SOURCE_TIMELINE_MUPEN_VI_ORIGIN :
                        com.thorium.preview.ExperimentalGlesLibretroHost
                                .SOURCE_TIMELINE_DEFAULT);
                // filteredSourceTimeline tracks only the VI-origin callback
                // filter: that is the only bit that changes what the native
                // host accepts as a frame, which is what every caller of
                // this flag (usesStampedProducerTimeline, the renderer-policy
                // log) actually cares about. The content-bounds crop bit
                // changes on-screen cropping only and must not affect it.
                filteredSourceTimeline = (sourceTimelinePolicy &
                        com.thorium.preview.ExperimentalGlesLibretroHost
                                .SOURCE_TIMELINE_MUPEN_VI_ORIGIN) != 0;
                Log.i(TAG, "Renderer policy engine=" + entry.id +
                        " policy=" + (presentationPolicy ==
                                com.thorium.preview.ExperimentalGlesLibretroHost
                                        .PRESENT_DIRECT_WINDOW ?
                                "direct-window" : "frontend-fbo") +
                        " sourceTimeline=" + (filteredSourceTimeline ?
                                "mupen-vi-origin-filtered" : "complete"));
                final boolean widescreenEnhancements =
                        WidescreenSettings.isEnabled(appContext);
                Log.i(TAG, "Built-in widescreen profile engine=" + entry.id +
                        " enabled=" + widescreenEnhancements);
                // The pinned Dolphin GLES frontend produces valid GameCube
                // frames on Thor, but device evidence shows that Wii frames
                // remain black even while the core and audio advance. Dolphin
                // exposes the standard libretro Vulkan interface, and the
                // unified Vulkan host already owns the same lifecycle for
                // Azahar/Armsx2. Route only Wii through that interface so the
                // proven GameCube path is left untouched.
                final boolean useVulkanRuntime =
                        "vulkan-libretro".equals(entry.runtime) ||
                        ("dolphin".equals(entry.id) &&
                                isWiiSystem(request.systemId));
                Log.i(TAG, "Hardware API engine=" + entry.id +
                        " system=" + request.systemId +
                        " api=" + (useVulkanRuntime ? "vulkan" : "gles"));
                final ExperimentalGlesRenderLoop loop =
                        useVulkanRuntime ?
                        ExperimentalGlesRenderLoop.createVulkan(
                                entry.coreFile, entry.coreFile.getParentFile(),
                                system, saves, game, widescreenEnhancements,
                                renderListener) :
                        new ExperimentalGlesRenderLoop(
                                entry.coreFile, entry.coreFile.getParentFile(),
                                system, saves, game,
                                presentationPolicy,
                                sourceTimelinePolicy,
                                widescreenEnhancements,
                                renderListener);
                try {
                    installDirectDisplayClock(loop);
                    configureInitialControllerPorts(loop);
                    final com.thorium.preview.ExperimentalGlesLibretroHost.AvInfo av =
                            loop.avInfo();
                    declaredVideoHz = av.framesPerSecond;
                    Log.i(TAG, "Producer clock engine=" + entry.id +
                            " declaredVideoHz=" + String.format(
                                    java.util.Locale.US, "%.9f",
                                    declaredVideoHz) +
                            " stamp=core-run-sequence" +
                            " sourceTimeline=" + (filteredSourceTimeline ?
                                    "mupen-vi-origin-filtered" : "complete"));
                    final float presentationAspect = PresentationGeometry.resolveAspect(
                            request.systemId, av.aspectRatio,
                            av.baseWidth, av.baseHeight);
                    if (!Float.isFinite(presentationAspect) ||
                            presentationAspect <= 0.1f || presentationAspect >= 10f)
                        throw new IllegalStateException(
                                "No safe presentation aspect for " + request.systemId);
                    loop.setPresentationAspect(presentationAspect);
                    Log.i(TAG, "Resolved presentation aspect engine=" + entry.id +
                            " system=" + request.systemId + " aspect=" +
                            presentationAspect);
                } catch (Throwable failure) {
                    loop.close();
                    throw failure;
                }
                if (isThreeDsSystem(request.systemId)) {
                    // The Thor's lower 3DS touch panel is intentionally
                    // portrait while the physical display remains landscape.
                    // Configure presentation before its secondary Surface can
                    // be attached by the already-resumed lower Activity.
                    loop.setSecondaryPresentationRotation(90);
                }
                renderLoop = loop;
                if (isThreeDsSystem(request.systemId)) {
                    secondaryDisplayRequested = SecondaryGameplaySurfaceRouter.request(
                            appContext, request.systemId, this);
                    Log.i(TAG, "Secondary gameplay display requested engine=" +
                            entry.id + " accepted=" + secondaryDisplayRequested);
                }
            } catch (Throwable failure) {
                releaseSecondaryDisplay();
                Log.e(TAG, "Unable to prepare engine=" + entry.id +
                        " system=" + request.systemId, failure);
                String detail = failure.getMessage();
                boolean invalidDisc = failure instanceof DiscImagePreflight.InvalidImageException || detail != null &&
                        (detail.startsWith("Invalid RVZ image:") ||
                         detail.startsWith("Invalid WIA image:") ||
                         detail.startsWith("Unexpected end of disc image header"));
                callback.onSessionError(failure instanceof Phase2QualificationCatalog.MissingFirmwareException
                        ? detail : invalidDisc
                        ? detail + " Re-copy or replace this disc image."
                        : "EmuFusion could not start " + entry.id + ".", failure);
            }
        });
    }

    @Override public void setFirstFrameCallback(Runnable callback) {
        firstFrameCallback = callback;
    }

    private void installDirectDisplayClock(ExperimentalGlesRenderLoop loop) {
        // Physical gameplay/cadence evidence currently covers Azahar only.
        // Keep other hardware routes on their retained clock until separately tested.
        if (!"azahar".equals(entry.id)) return;
        final DirectDisplayVsync clock;
        try { clock = new DirectDisplayVsync(context); }
        catch (RuntimeException unavailable) {
            Log.w(TAG, "Display tick source unavailable; retaining absolute hardware clock", unavailable);
            return;
        }
        loop.setDisplayClock(new ExperimentalGlesRenderLoop.DisplayClock() {
            @Override public void configure(double declared, double source, boolean enabled) {
                clock.configure(declared, source, enabled && netplayRelay == null);
            }
            @Override public long awaitDueTimeNs() throws InterruptedException {
                return clock.awaitDueTimeNs();
            }
            @Override public double measuredSourceHz() { return clock.measuredSourceHz(); }
            @Override public void suspend() { clock.suspend(); }
            @Override public void close() { clock.close(); }
        });
    }

    private void configureInitialControllerPorts(ExperimentalGlesRenderLoop loop) {
        if (!"flycast".equals(entry.id)) return;
        // The native host already declares port 0 as JOYPAD. Flycast defers
        // expansion-slot/VMU setup until all four ports have been declared.
        // Declare unused ports as NONE before the first retro_run; do not
        // replace VMU files or manufacture additional connected controllers.
        for (int port = 1; port < 4; port++) loop.setControllerPortDevice(port, 0);
        Log.i(TAG, "Initial controller ports configured engine=flycast " +
                "port0=joypad ports1-3=none");
    }

    @Override public void attachSurface(Surface value, int width, int height) {
        voidDimensions(width, height);
        surface = value;
        Log.i(TAG, "Surface available engine=" + entry.id + " size=" +
                width + "x" + height + " valid=" +
                (value != null && value.isValid()) + " prepared=" + prepared);
        ExperimentalGlesRenderLoop active = renderLoop;
        if (prepared && active != null && value != null && value.isValid()) {
            active.attachSurface(value);
        }
    }

    @Override public void resizeSurface(int width, int height) {
        voidDimensions(width, height);
        Log.i(TAG, "Surface resized engine=" + entry.id + " size=" +
                width + "x" + height + " prepared=" + prepared);
        Surface current = surface;
        ExperimentalGlesRenderLoop active = renderLoop;
        if (prepared && active != null && current != null && current.isValid())
            active.resizeSurface(current);
    }

    @Override public void detachSurface() {
        Log.i(TAG, "Surface detached engine=" + entry.id +
                " prepared=" + prepared);
        surface = null;
        ExperimentalGlesRenderLoop active = renderLoop;
        if (prepared && active != null) active.detachSurface();
    }

    /**
     * Bounded synchronous variant of {@link #detachSurface()} for the
     * TextureView destroy callback: Android releases that Surface as soon as
     * the callback returns, so the render thread must stop targeting it first
     * or give up within the UI-safe bound and finish detaching asynchronously.
     */
    void detachSurfaceAndWait() {
        surface = null;
        ExperimentalGlesRenderLoop active = renderLoop;
        boolean detached = true;
        if (prepared && active != null) {
            try {
                detached = active.detachSurfaceAndWait();
            } catch (RuntimeException failure) {
                Log.w(TAG, "Bounded surface detach failed engine=" + entry.id, failure);
            }
        }
        if (!detached)
            Log.w(TAG, "Surface detach exceeded its UI bound; completing " +
                    "asynchronously engine=" + entry.id);
        Log.i(TAG, "Surface detached engine=" + entry.id +
                " prepared=" + prepared + " waited=" + detached);
    }

    @Override public void onSecondarySurfaceAvailable(
            Surface value, int width, int height) {
        releasePhoneStylus();
        voidDimensions(width, height);
        secondarySurface = value;
        ExperimentalGlesRenderLoop active = renderLoop;
        if (active != null && value != null && value.isValid())
            active.attachSecondarySurface(value);
    }

    @Override public void onSecondarySurfaceDestroyed() {
        secondarySurface = null;
        ExperimentalGlesRenderLoop active = renderLoop;
        if (active == null) return;
        try {
            // The lower-display SurfaceView is removed as soon as this
            // notification returns; the swapchain detach must complete (or
            // give up within the UI bound) before that removal.
            if (!active.detachSecondarySurfaceAndWaitBounded())
                Log.w(TAG, "Lower-display detach exceeded its UI bound engine=" +
                        entry.id);
        } catch (RuntimeException failure) {
            Log.w(TAG, "Lower-display detach failed engine=" + entry.id, failure);
        }
    }

    @Override public void onSecondarySurfaceError(Throwable failure) {
        secondarySurface = null;
        Listener callback = listener;
        if (callback != null) callback.onSessionError(
                "The lower-screen renderer could not release the display. Close and reopen this game.",
                failure);
    }

    @Override public void onSecondaryTouch(
            float normalizedX, float normalizedY, boolean pressed) {
        ExperimentalGlesRenderLoop active = renderLoop;
        if (active == null || !prepared) return;
        if (request != null && isThreeDsSystem(request.systemId)) {
            active.setPointer(0,
                    DualScreenLayout.threeDsSideBySidePointerX(normalizedX),
                    DualScreenLayout.threeDsSideBySidePointerY(normalizedY),
                    pressed);
        } else {
            active.setPointer(0, DualScreenLayout.pointerCoordinate(normalizedX),
                    DualScreenLayout.lowerScreenPointerY(normalizedY), pressed);
        }
    }

    @Override public void onPrimaryTouch(MotionEvent event, int width, int height) {
        synchronized (phoneStylus) {
            ExperimentalGlesRenderLoop active = renderLoop;
            if (active == null || request == null || !isThreeDsSystem(request.systemId)) return;
            Surface lower = secondarySurface;
            // The Thor's primary panel is not its stylus panel. A primary
            // touch must not cancel input currently owned by the lower panel.
            if (lower != null && lower.isValid()) return;
            ThreeDsPhoneStylus.State point = prepared && resumeRequested &&
                    !stopping.get() && !released.get()
                    ? phoneStylus.update(event, width, height) : phoneStylus.release();
            active.setPointer(0, point.x, point.y, point.pressed);
        }
    }

    private void releasePhoneStylus() {
        synchronized (phoneStylus) {
            ThreeDsPhoneStylus.State point = phoneStylus.release();
            ExperimentalGlesRenderLoop active = renderLoop;
            if (active != null && request != null && isThreeDsSystem(request.systemId))
                active.setPointer(0, point.x, point.y, false);
        }
    }

    @Override public void resume() {
        backgroundCaptureRequested.set(false);
        resumeRequested = true;
        ExperimentalGlesRenderLoop active = renderLoop;
        if (prepared && active != null) {
            // Re-acquires focus this session gave up when it went to the
            // background, or lost permanently to another app while it was
            // there.
            audioFocus.request();
            prepareAudioResume();
            synchronized (this) {
                long now = SystemClock.elapsedRealtime();
                if (activeStartedMillis == 0L) activeStartedMillis = now;
                activeFrameTickMillis = now;
            }
            active.resume();
        }
    }

    @Override public void pause(PauseReason reason) {
        resumeRequested = false;
        releasePhoneStylus();
        synchronized (this) { activeFrameTickMillis = 0L; }
        finishActiveInterval();
        ExperimentalGlesRenderLoop active = renderLoop;
        if (prepared && active != null) active.pause();
        AudioTrack audio = audioTrack;
        if (audio != null) try { audio.pause(); } catch (IllegalStateException ignored) {}
        // Kept across a Lucent-menu pause: this is still the foreground game.
        // Given back when Android backgrounds it, which is the point another
        // app expects to be able to take it.
        if (reason == PauseReason.ANDROID_BACKGROUND) audioFocus.abandon();
        if (reason == PauseReason.ANDROID_BACKGROUND && prepared && active != null &&
                !stopping.get() && backgroundCaptureRequested.compareAndSet(false, true)) {
            try {
                // Submit capture before InWindowGameHost can enqueue detach.
                // Only immutable captured bytes cross to the disk worker.
                Future<ExperimentalGlesRenderLoop.PausedState> capture =
                        active.pauseAndCaptureState(
                                QuickResumePolicy.allowsRuntimeRestore(entry.id));
                long capturedActiveMillis = currentActivePlayMillis();
                lifecycle.execute(() -> commitBackgroundCapture(capture, capturedActiveMillis));
            } catch (RuntimeException failure) {
                Log.w(TAG, "Background checkpoint could not be queued engine=" +
                        entry.id + " marker=save-failure", failure);
            }
        }
    }

    private void silenceForAudioFocusLoss() {
        // Nothing here attenuates the track: EmuFusion produces no sound at all
        // while another app owns the output, and presentAudio drops the PCM the
        // core has already produced so nothing queues up behind a paused track.
        AudioTrack audio = audioTrack;
        if (audio != null) try { audio.pause(); } catch (IllegalStateException ignored) {}
    }

    private void resumeAfterAudioFocusGain() {
        if (resumeRequested) prepareAudioResume();
    }

    private void prepareAudioResume() {
        AudioTrack audio = audioTrack;
        if (audio == null || !audioStartedOnce) return;
        // Wake can deliver one PCM block before a longer producer stall.
        // Refill the existing startup-sized buffer, retaining paused samples
        // and FIFO order. Do not flush, insert silence, or permanently enlarge
        // steady-state latency. presentAudio starts only when this track fills.
        try {
            if (audio.getPlayState() == AudioTrack.PLAYSTATE_PLAYING) return;
            if (Build.VERSION.SDK_INT >= 24) {
                int frames = startupAudioBufferBytes(audio.getSampleRate()) / 4;
                if (frames > 0) audio.setBufferSizeInFrames(frames);
            }
            steadyAudioBufferApplied = false;
            audioStartedAtMillis = 0L;
        } catch (IllegalStateException ignored) {
            // Teardown may release the track after this callback reads it.
            // Preserve resume's previous non-throwing lifecycle behavior.
        }
    }

    @Override public void quiesceForExit() {
        resumeRequested = false;
        synchronized (this) { activeFrameTickMillis = 0L; }
        finishActiveInterval();
        ExperimentalGlesRenderLoop active = renderLoop;
        if (prepared && active != null) active.pauseAndWait();
        AudioTrack audio = audioTrack;
        if (audio != null) try { audio.pause(); } catch (IllegalStateException ignored) {}
        Log.i(TAG, "Render loop quiesced before library reveal engine=" + entry.id +
                " system=" + (request == null ? "" : request.systemId));
    }

    @Override public boolean quiesceForPresentationRecovery() {
        resumeRequested = false;
        synchronized (this) { activeFrameTickMillis = 0L; }
        finishActiveInterval();
        AudioTrack audio = audioTrack;
        if (audio != null) try { audio.pause(); } catch (IllegalStateException ignored) {}
        ExperimentalGlesRenderLoop active = renderLoop;
        if (!prepared || active == null || stopping.get() || released.get()) return false;
        active.pauseAndDetachForPresentationRecovery();
        surface = null;
        return true;
    }

    /**
     * Power-cycles the loaded content through libretro's retro_reset.
     *
     * There is still no unload/load pair on this boundary, so there is no
     * reload to fall back on: either the native reset lands or the caller is
     * told nothing happened. The render loop marshals the call onto the
     * render-owning thread and waits for it, which is what lets this return an
     * honest result — every other core entry point (attach, run/present,
     * detach, close) belongs to that one thread, and retro_reset is no
     * different.
     *
     * Battery save RAM is left alone. retro_reset is the console's reset
     * button and does not disturb the core's SRAM; writing the last persisted
     * copy back over it would roll play backwards.
     */
    @Override public boolean reset() {
        ExperimentalGlesRenderLoop active = renderLoop;
        String systemId = request == null ? "" : request.systemId;
        if (!prepared || active == null || stopping.get() || released.get()) {
            Log.w(TAG, "Reset unavailable on the hardware session engine=" +
                    entry.id + " system=" + systemId +
                    " marker=reset-unavailable");
            return false;
        }
        try {
            active.reset();
        } catch (Throwable failure) {
            Log.w(TAG, "Reset rejected engine=" + entry.id +
                    " system=" + systemId + " marker=reset-failure", failure);
            return false;
        }
        flushAudioAfterRestore();
        Log.i(TAG, "Reset applied engine=" + entry.id +
                " system=" + systemId + " marker=reset");
        return true;
    }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        ExperimentalGlesRenderLoop active = renderLoop;
        if (!prepared || active == null || inputRouter == null || event == null ||
                (event.getAction() != KeyEvent.ACTION_DOWN &&
                 event.getAction() != KeyEvent.ACTION_UP)) return false;
        if (event.getAction() == KeyEvent.ACTION_DOWN &&
                event.getRepeatCount() != 0) return true;
        GamepadDescriptor pad = device(event.getDeviceId());
        if (pad == null) { refreshDevices(); pad = device(event.getDeviceId()); }
        if (pad == null) return false;
        try {
            InputSignal signal = InputSignal.key(event.getKeyCode());
            CanonicalControl control = inputRouter.resolve(pad, signal);
            int button = canonicalButton(control);
            if (button < 0) return false;
            boolean pressed = event.getAction() == KeyEvent.ACTION_DOWN;
            joypad.apply(signal, button, pressed, joypadSink);
            if (wiiIrEnabled && control == CanonicalControl.SOUTH) {
                WiiIrPointer.State pointer = wiiIrPointer.setPressed(pressed);
                active.setPointer(0, pointer.x, pointer.y, pointer.pressed);
            }
            Log.i(TAG, "Physical input dispatched engine=" + entry.id +
                    " key=" + event.getKeyCode() + " control=" + control +
                    " button=" + button + " pressed=" + pressed);
            return true;
        } catch (Exception ignored) { return false; }
    }

    @Override public boolean dispatchGenericMotionEvent(MotionEvent event) {
        ExperimentalGlesRenderLoop active = renderLoop;
        InputDevice inputDevice = event == null ? null : event.getDevice();
        if (!prepared || active == null || event.getAction() != MotionEvent.ACTION_MOVE ||
                inputRouter == null || inputDevice == null ||
                inputDevice.getMotionRange(MotionEvent.AXIS_X,
                        event.getSource()) == null ||
                inputDevice.getMotionRange(MotionEvent.AXIS_Y, event.getSource()) == null)
            return false;
        GamepadDescriptor pad = device(event.getDeviceId());
        if (pad == null) { refreshDevices(); pad = device(event.getDeviceId()); }
        if (pad == null) return false;
        active.setAnalogAxis(0, 0, 0, normalizeAxis(event, MotionEvent.AXIS_X));
        active.setAnalogAxis(0, 0, 1, normalizeAxis(event, MotionEvent.AXIS_Y));
        int rightX = inputDevice.getMotionRange(MotionEvent.AXIS_Z, event.getSource()) != null
                ? MotionEvent.AXIS_Z : MotionEvent.AXIS_RX;
        int rightY = inputDevice.getMotionRange(MotionEvent.AXIS_RZ, event.getSource()) != null
                ? MotionEvent.AXIS_RZ : MotionEvent.AXIS_RY;
        boolean hasRightX = inputDevice.getMotionRange(rightX, event.getSource()) != null;
        boolean hasRightY = inputDevice.getMotionRange(rightY, event.getSource()) != null;
        float normalizedRightX = hasRightX ? normalizeAxis(event, rightX) : 0f;
        float normalizedRightY = hasRightY ? normalizeAxis(event, rightY) : 0f;
        if (hasRightX) active.setAnalogAxis(0, 1, 0, normalizedRightX);
        if (hasRightY) active.setAnalogAxis(0, 1, 1, normalizedRightY);
        if (wiiIrEnabled && (hasRightX || hasRightY)) {
            // Pointer and analog are deliberately parallel: pointer-backed IR
            // consumes this absolute cursor while analog index 1 remains live
            // for Dolphin's Wiimote tilt controls.
            WiiIrPointer.State pointer =
                    wiiIrPointer.move(normalizedRightX, normalizedRightY);
            active.setPointer(0, pointer.x, pointer.y, pointer.pressed);
        }
        boolean consumed = true;
        for (int axis : pad.axes) {
            float value = event.getAxisValue(axis);
            consumed |= dispatchAxis(pad, axis, -1, value <= -AXIS_PRESS);
            consumed |= dispatchAxis(pad, axis, 1, value >= AXIS_PRESS);
        }
        return consumed;
    }

    @Override public boolean openControls() {
        if (!(context instanceof Activity) || inputRouter == null) return false;
        GamepadDescriptor pad = inputRouter.activeDevice();
        Activity activity = (Activity) context;
        if (pad == null) {
            activity.runOnUiThread(() -> new AlertDialog.Builder(context)
                    .setTitle("Controls")
                    .setMessage("No physical controller is connected. EmuFusion will use touch controls when available.")
                    .setPositiveButton("Done", null).show());
        } else {
            activity.runOnUiThread(() -> showControlsMenu(pad));
        }
        return true;
    }

    @Override public boolean openRestoreHistory() {
        if (!(context instanceof Activity) || vault == null || identity == null) return false;
        List<StateSnapshot> history = restorableHistory();
        if (history.isEmpty()) return false;
        String[] labels = new String[history.size()];
        DateFormat formatter = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT);
        for (int index = 0; index < history.size(); index++) {
            StateSnapshot snapshot = history.get(index);
            labels[index] = formatter.format(new Date(snapshot.metadata.createdAtMillis)) +
                    "  •  " + formatPlayTime(snapshot.metadata.activePlayMillis);
        }
        ((Activity) context).runOnUiThread(() -> new AlertDialog.Builder(context)
                .setTitle("Restore earlier point")
                .setItems(labels, (dialog, which) -> restore(history.get(which)))
                .setNegativeButton("Cancel", null).show());
        return true;
    }

    @Override public boolean shouldShowOnScreenControls() {
        return inputRouter != null && inputRouter.shouldShowOnScreenControls();
    }
    @Override public int virtualAnalogStickCount() {
        return request == null ? 0 : SystemControlLayouts.analogStickCount(request.systemId);
    }
    @Override public boolean dispatchVirtualAnalog(int stick, float x, float y) {
        ExperimentalGlesRenderLoop active = renderLoop;
        if (!prepared || active == null || stopping.get() || stick < 0 ||
                stick >= virtualAnalogStickCount() || !Float.isFinite(x) || !Float.isFinite(y) ||
                (!shouldShowOnScreenControls() && (x != 0f || y != 0f))) return false;
        active.setAnalogAxis(0, stick, 0, Math.max(-1f, Math.min(1f, x)));
        active.setAnalogAxis(0, stick, 1, Math.max(-1f, Math.min(1f, y)));
        if (wiiIrEnabled && stick == 1) {
            WiiIrPointer.State pointer = wiiIrPointer.move(x, y);
            active.setPointer(0, pointer.x, pointer.y, pointer.pressed);
        }
        return true;
    }
    @Override public boolean dispatchVirtualControl(CanonicalControl control, boolean pressed) {
        int button = canonicalButton(control);
        ExperimentalGlesRenderLoop active = renderLoop;
        if (!prepared || active == null || button < 0 ||
                (pressed && !shouldShowOnScreenControls())) return false;
        joypad.apply(control, button, pressed, joypadSink);
        if (wiiIrEnabled && control == CanonicalControl.SOUTH) {
            WiiIrPointer.State pointer = wiiIrPointer.setPressed(pressed);
            active.setPointer(0, pointer.x, pointer.y, pointer.pressed);
        }
        Log.i(TAG, "Virtual input dispatched engine=" + entry.id +
                " control=" + control + " button=" + button + " pressed=" + pressed);
        return true;
    }

    @Override public void stop(StopReason reason, Completion completion) {
        if (completion == null) throw new IllegalArgumentException("completion required");
        releasePhoneStylus();
        boolean alreadyComplete;
        synchronized (stopLock) {
            alreadyComplete = stopCompleted;
            if (!alreadyComplete) {
                stopCompletions.add(completion);
                if (reason == StopReason.ACTIVITY_DESTROYED) destroyStopRequested = true;
                if (!stopping.compareAndSet(false, true)) return;
            }
        }
        if (alreadyComplete) {
            completion.complete();
            return;
        }
        resumeRequested = false;
        finishActiveInterval();
        lifecycle.execute(() -> {
            try {
                ExperimentalGlesRenderLoop active = renderLoop;
                if (active != null) active.pauseAndWait();
                Throwable saveFailure = saveQuickResume(true);
                boolean rejected;
                synchronized (stopLock) {
                    rejected = !QuickResumePolicy.mayCompleteStop(
                            !destroyStopRequested, saveFailure == null);
                    if (rejected) {
                        stopCompletions.clear();
                        stopping.set(false);
                    }
                }
                if (rejected) {
                    Listener callback = listener;
                    // The rejection channel keeps gameplay retained and lets
                    // the host reset its exit latch; onSessionError would show
                    // the fatal overlay over a still-playable game.
                    if (callback != null) {
                        try {
                            callback.onSessionStopRejected(
                                    "EmuFusion could not protect Quick Resume. The game is still open; " +
                                            "return only if you accept losing this session.", saveFailure);
                        } catch (Throwable callbackFailure) {
                            Log.e(TAG, "Stop rejection callback failed; retaining game", callbackFailure);
                        }
                    }
                    return;
                }
                detachSecondaryBeforeBlank(active);
                releaseAudio();
            } catch (Throwable failure) {
                // Even a save/pause/audio error still needs an actual native
                // close acknowledgement. A timeout is not permission to let
                // Qt or a new emulator destroy shared process resources.
                Log.e(TAG, "Stop teardown failed engine=" + entry.id +
                        " marker=save-failure", failure);
                try { releaseAudio(); } catch (Throwable ignored) {}
            }
            closeForStop(renderLoop);
        });
    }

    private void closeForStop(ExperimentalGlesRenderLoop closing) {
        if (closing == null) {
            completeStop(null);
            return;
        }
        try {
            closing.closeWhenComplete(() -> completeStop(closing));
        } catch (Throwable failure) {
            Log.e(TAG, "Native close not acknowledged; retaining stop engine=" + entry.id,
                    failure);
        }
    }

    private void completeStop(ExperimentalGlesRenderLoop closing) {
        List<Completion> callbacks;
        synchronized (stopLock) {
            if (stopCompleted) return;
            if (renderLoop == closing) renderLoop = null;
            prepared = false;
            stopCompleted = true;
            callbacks = new ArrayList<>(stopCompletions);
            stopCompletions.clear();
        }
        for (Completion callback : callbacks) {
            try { callback.complete(); }
            catch (Throwable failure) { Log.e(TAG, "Stop completion callback failed", failure); }
        }
    }

    @Override public void release() {
        releaseWhenComplete(() -> {});
    }

    /** Async release whose acknowledgement includes actual native teardown. */
    public void releaseWhenComplete(Completion completion) {
        if (completion == null) throw new IllegalArgumentException("completion required");
        releasePhoneStylus();
        boolean alreadyComplete;
        synchronized (releaseLock) {
            alreadyComplete = releaseCompleted;
            if (!alreadyComplete) {
                releaseCompletions.add(completion);
                if (!released.compareAndSet(false, true)) return;
            }
        }
        if (alreadyComplete) {
            completion.complete();
            return;
        }
        resumeRequested = false;
        // Before any teardown that can block or throw: focus held past the end
        // of a session mutes every other app.
        try { audioFocus.abandon(); }
        catch (Throwable failure) { Log.e(TAG, "Release audio focus failed", failure); }
        finishActiveInterval();
        lifecycle.execute(() -> {
            try {
                saveQuickResume(false);
                detachSecondaryBeforeBlank(renderLoop);
                releaseAudio();
            } catch (Throwable failure) {
                Log.e(TAG, "Release cleanup failed; still awaiting native close", failure);
                try { releaseAudio(); } catch (Throwable ignored) {}
            }
            ExperimentalGlesRenderLoop closing = renderLoop;
            if (closing == null) completeRelease(null);
            else {
                try { closing.closeWhenComplete(() -> completeRelease(closing)); }
                catch (Throwable failure) {
                    Log.e(TAG, "Native release not acknowledged; retaining session", failure);
                }
            }
        });
        lifecycle.shutdown();
    }

    private void completeRelease(ExperimentalGlesRenderLoop closing) {
        List<Completion> callbacks;
        synchronized (releaseLock) {
            if (releaseCompleted) return;
            if (renderLoop == closing) renderLoop = null;
            prepared = false;
            releaseCompleted = true;
            callbacks = new ArrayList<>(releaseCompletions);
            releaseCompletions.clear();
        }
        for (Completion callback : callbacks) {
            try { callback.complete(); }
            catch (Throwable failure) { Log.e(TAG, "Release completion callback failed", failure); }
        }
    }

    private static void loopClose(ExperimentalGlesRenderLoop loop) {
        if (loop != null) try { loop.close(); }
        catch (Throwable failure) { Log.e(TAG, "Render close has not completed", failure); }
    }

    private void releaseSecondaryDisplay() {
        if (!secondaryDisplayRequested) return;
        secondaryDisplayRequested = false;
        secondarySurface = null;
        SecondaryGameplaySurfaceRouter.release(appContext, this);
    }

    private void detachSecondaryBeforeBlank(ExperimentalGlesRenderLoop active) {
        if (!secondaryDisplayRequested) return;
        if (active != null) {
            try {
                active.detachSecondarySurfaceAndWait();
            } catch (Throwable failure) {
                Log.w(TAG, "Lower-display swapchain detach failed before blank", failure);
            }
        }
        releaseSecondaryDisplay();
    }

    private static boolean isThreeDsSystem(String systemId) {
        return "3ds".equalsIgnoreCase(systemId) ||
                "n3ds".equalsIgnoreCase(systemId);
    }

    private void handleReady(Listener callback) {
        ExperimentalGlesRenderLoop active = renderLoop;
        if (active == null) {
            callback.onSessionError("The experimental renderer was unavailable.", null);
            return;
        }
        if (stopping.get() || released.get()) {
            loopClose(active);
            return;
        }
        prepared = true;
        try {
            // The render loop's factory has just loaded the game, and loading
            // puts port 0 back to a plain RetroPad. Wii and GameCube run on
            // this hardware path, so a system whose controller is something
            // else must say so before the first frame: Dolphin only attaches
            // the Wii Nunchuk for RETRO_DEVICE_WIIMOTE_NC, and titles that
            // require it (Super Mario Galaxy 2) accept no input without it.
            int portDevice = LibretroJoypadLayout.portDeviceFor(request.systemId);
            if (portDevice != LibretroJoypadLayout.RETRO_DEVICE_JOYPAD) {
                active.setControllerPortDevice(0, portDevice);
                Log.i(TAG, "Controller port device engine=" + entry.id +
                        " system=" + request.systemId +
                        " device=0x" + Integer.toHexString(portDevice));
            }
            if (wiiIrEnabled) {
                WiiIrPointer.State pointer = wiiIrPointer.state();
                active.setPointer(0, pointer.x, pointer.y, pointer.pressed);
            }
            restoreSaveRam(active);
            applyStoredCheats(active);
            double sampleRate = active.avInfo().sampleRate;
            audioTrack = createAudioTrack(sampleRate);
            if (audioTrack == null)
                throw new IllegalStateException("Android could not initialize stereo PCM output");
            audioQueue = new PcmAudioQueue(audioQueueCapacitySamples(sampleRate));
            EngineAudioLog.logResolvedStream(appContext, TAG, entry.id, audioTrack);
            // Focus is taken as soon as this session owns an output, not when
            // the first sample is written; the teardown paths give it back.
            audioFocus.request();
            // Fill the actual streaming buffer before the first play(). A
            // A half-full start can underrun while a heavy core warms its JIT.
            audioPrimeSamplesTarget = startupAudioBufferBytes(sampleRate) / 2;
        } catch (Throwable failure) {
            // Record the original error before native teardown, which may itself fail.
            Log.e(TAG, "Engine preparation failed engine=" + entry.id, failure);
            loopClose(active);
            prepared = false;
            // A session that never started must not keep the focus its aborted
            // preparation took, or every other app stays ducked.
            audioFocus.abandon();
            callback.onSessionError("EmuFusion could not initialize engine audio or saves.", failure);
            return;
        }
        Surface current = surface;
        Log.i(TAG, "Engine ready engine=" + entry.id + " surfaceValid=" +
                (current != null && current.isValid()));
        if (current != null && current.isValid()) {
            active.attachSurface(current);
        }
        if (resumeRequested) {
            synchronized (this) {
                long now = SystemClock.elapsedRealtime();
                if (activeStartedMillis == 0L) activeStartedMillis = now;
                activeFrameTickMillis = now;
            }
            active.resume();
        }
        notifyRestoreAvailability();
        callback.onSessionReady();
    }

    /** Exact AV clock used by the native hardware producer's PTS stamp. */
    @Override public double declaredVideoHz() { return declaredVideoHz; }

    @Override public boolean setPacedVideoHz(double hz) {
        ExperimentalGlesRenderLoop active = renderLoop;
        return active != null && active.setPacedVideoHz(hz);
    }

    @Override public double pacedVideoHz() {
        ExperimentalGlesRenderLoop active = renderLoop;
        return active == null ? 0.0 : active.pacedVideoHz();
    }

    @Override public double achievedCoreHz() {
        ExperimentalGlesRenderLoop active = renderLoop;
        return active == null ? 0.0 : active.achievedCoreHz();
    }

    @Override public double sustainedFrameWorkCapacityHz() {
        ExperimentalGlesRenderLoop active = renderLoop;
        return active == null ? 0.0 : active.sustainedFrameWorkCapacityHz();
    }

    /**
     * Vulkan has a separate producer path and cannot claim the GLES stamp.
     * A filtered Mupen stream also cannot claim that Java receives every
     * stamped AV tick: its missing carrier ordinals are the exact duplicate
     * intervals the core-side source-boundary policy intentionally removed.
     * The retained buffers keep their immutable PTS and are measured directly
     * as 20/30/60 (or another proven cadence) by the source authority.
     */
    boolean usesStampedProducerTimeline() {
        // Both hardware runtimes stamp presented frames on the ideal paced
        // lattice: GLES through eglPresentationTimeANDROID, Vulkan through
        // VK_GOOGLE_display_timing (2026-09-01, PS2 run ps2-b30 showed
        // real-time Vulkan stamps with 1.6 percent RMS jitter and no clock).
        return ("gles-libretro".equals(entry.runtime) ||
                "vulkan-libretro".equals(entry.runtime)) &&
                !filteredSourceTimeline;
    }

    private static boolean supportsLiveCheats(String engineId) {
        // These exact cores implement retro_cheat_reset/set. ARMSX2 and Azahar
        // currently export no-op stubs, so advertising their databases would
        // create a dishonest toggle. Flycast's own retro_cheat_set was such a
        // stub too until engines/patches/flycast-libretro-cheat-support.patch
        // wired it to the core's existing (non-LIBRETRO-gated) CheatManager.
        return "dolphin".equals(engineId) || "ppsspp".equals(engineId) ||
                "mupen64plus-next".equals(engineId) || "flycast".equals(engineId);
    }

    private void prepareCheats(GameLaunchRequest launch, String contentName,
                               String contentIdentity) {
        if (!supportsLiveCheats(entry.id)) return;
        CheatSelection selection = CheatControl.selectionForGame(appContext,
                launch.systemId, launch.gameTitle, contentName, contentIdentity);
        if (selection.available().isEmpty()) return;
        synchronized (cheatLock) {
            cheats = selection;
            cheatGameKey = CheatDatabase.key(launch.systemId, launch.gameTitle);
        }
    }

    private void applyStoredCheats(ExperimentalGlesRenderLoop active) {
        java.util.List<String> codes;
        synchronized (cheatLock) {
            if (cheats == null) return;
            codes = cheats.enabledCodes();
        }
        active.applyCheats(codes);
        Log.i(TAG, "Cheats applied live engine=" + entry.id + " count=" + codes.size());
    }

    @Override public java.util.List<Cheat> availableCheats() {
        synchronized (cheatLock) {
            return cheats == null ? java.util.Collections.<Cheat>emptyList()
                    : cheats.available();
        }
    }

    @Override public java.util.Set<String> enabledCheatIds() {
        synchronized (cheatLock) {
            return cheats == null ? java.util.Collections.<String>emptySet()
                    : cheats.enabledIds();
        }
    }

    @Override public boolean setCheatEnabled(String cheatId, boolean enabled) {
        if (!prepared || stopping.get() || released.get() || renderLoop == null) return false;
        final java.util.List<String> codes;
        final java.util.Set<String> ids;
        final String gameKey;
        synchronized (cheatLock) {
            if (cheats == null || !offers(cheats, cheatId)) return false;
            cheats.setEnabled(cheatId, enabled);
            codes = cheats.enabledCodes();
            ids = cheats.enabledIds();
            gameKey = cheatGameKey;
        }
        try {
            lifecycle.execute(() -> {
                ExperimentalGlesRenderLoop active = renderLoop;
                if (active == null || stopping.get() || released.get()) return;
                try {
                    active.applyCheats(codes);
                    CheatControl.store(appContext).save(gameKey, ids);
                    Log.i(TAG, "Cheat toggled live engine=" + entry.id +
                            " id=" + cheatId + " enabled=" + enabled);
                } catch (Throwable failure) {
                    Log.w(TAG, "Live cheat toggle failed engine=" + entry.id, failure);
                }
            });
            return true;
        } catch (java.util.concurrent.RejectedExecutionException rejected) {
            return false;
        }
    }

    private static boolean offers(CheatSelection selection, String cheatId) {
        if (cheatId == null) return false;
        for (Cheat cheat : selection.available()) if (cheat.id.equals(cheatId)) return true;
        return false;
    }

    private static String discGameIdentity(String systemId, File game) {
        if (!("gamecube".equalsIgnoreCase(systemId) || "gc".equalsIgnoreCase(systemId) ||
                "wii".equalsIgnoreCase(systemId)) || game == null) return "";
        try (java.io.RandomAccessFile input = new java.io.RandomAccessFile(game, "r")) {
            if (input.length() < 8) return "";
            byte[] header = new byte[8];
            input.readFully(header);
            String id = new String(header, 0, 6, java.nio.charset.StandardCharsets.US_ASCII);
            if (!id.matches("[A-Z0-9]{6}")) return "";
            int revision = header[7] & 0xff;
            return id + "R" + revision;
        } catch (Exception ignored) {
            return "";
        }
    }

    private void restoreQuickResume(ExperimentalGlesRenderLoop active) {
        byte[] state = pendingQuickResume;
        if (state == null || !quickResumeApplied.compareAndSet(false, true)) return;
        try {
            applyRuntimeState(active, state);
            flushAudioAfterRestore();
            pendingQuickResume = null;
            Log.i(TAG, "Restored Quick Resume engine=" + entry.id +
                    " commit=" + entry.sourceCommit);
        } catch (Throwable rejected) {
            // The core may already have mutated before rejecting a restore or
            // renderer migration. Preserve the snapshot and let the render
            // listener stop/report the failure; no cold boot happened here.
            pendingQuickResume = null;
            throw new IllegalStateException(
                    "Quick Resume failed; the saved checkpoint has been preserved", rejected);
        }
    }

    private void applyRuntimeState(ExperimentalGlesRenderLoop active, byte[] state) {
        // Both Quick Resume and history restore need this migration: otherwise
        // Dolphin can show its stale cyan/blank pre-snapshot attachment and
        // PPSSPP can publish black frames. Keep the same direct/FG-owned Surface;
        // serialize the restore and recreation together on its render owner.
        boolean migrateRenderer = "ppsspp".equals(entry.id) || "dolphin".equals(entry.id);
        active.unserialize(state, migrateRenderer);
        if (migrateRenderer)
            Log.i(TAG, "Recreated renderer after state restore engine=" + entry.id);
    }

    /** Returns the failure so explicit exits cannot falsely claim a protected save. */
    private Throwable saveQuickResume(boolean requireCommit) {
        try {
            ExperimentalGlesRenderLoop active = renderLoop;
            if (!prepared || active == null || vault == null || identity == null) {
                return requireCommit
                        ? new IllegalStateException("engine state vault is not ready") : null;
            }
            persistSaveRam(active);
            if (!QuickResumePolicy.allowsRuntimeRestore(entry.id)) {
                // Persist the title's ordinary memory-card/SRAM data, but do
                // not overwrite the last immutable state with another state
                // this build deliberately cannot restore safely.
                Log.i(TAG, "Skipped unqualified runtime-state checkpoint engine=" +
                        entry.id + " marker=state-restore-quarantined");
                return null;
            }
            byte[] state = active.serialize();
            commitQuickResume(state, currentActivePlayMillis(), requireCommit);
            return null;
        } catch (Throwable failure) {
            // A failed state must not replace the last verified snapshot or
            // strand the user while stopping qualification content. The
            // stable marker keeps the swallowed failure greppable by the
            // runtime evidence verifiers.
            Log.w(TAG, "Quick Resume was not updated for " + entry.id +
                    " marker=save-failure", failure);
            return failure;
        }
    }

    private void commitBackgroundCapture(
            Future<ExperimentalGlesRenderLoop.PausedState> capture,
            long capturedActiveMillis) {
        try {
            ExperimentalGlesRenderLoop.PausedState snapshot = capture.get(10, TimeUnit.SECONDS);
            if (snapshot == null) {
                Log.i(TAG, "Background checkpoint skipped without a live context engine=" +
                        entry.id + " marker=save-failure");
                return;
            }
            if (vault == null || identity == null) return;
            persistSaveRam(snapshot.saveRam);
            if (snapshot.stateFailure != null) throw snapshot.stateFailure;
            if (snapshot.state == null) return; // Runtime restore remains quarantined.
            commitQuickResume(snapshot.state, capturedActiveMillis, false);
        } catch (Throwable failure) {
            if (failure instanceof InterruptedException) Thread.currentThread().interrupt();
            Log.w(TAG, "Background Quick Resume was not updated for " + entry.id +
                    " marker=save-failure", failure);
        }
    }

    private void commitQuickResume(byte[] state, long capturedActiveMillis,
                                  boolean requireCommit) throws Exception {
        /* Loading the previous snapshot duplicates both states in the
         * Java heap. Dolphin states can exceed 140 MiB, so that recovery
         * convenience would OOM after a successful new serialization and
         * correctly prevent held-Stop from returning. The quick-save
         * publication is already atomic; retain the older snapshot on
         * disk and avoid an in-memory recovery copy for large cores. */
        if (QuickResumePolicy.shouldCopyPreviousToRecovery(state.length)) {
            StateLoadResult previous = vault.loadQuickResume(identity);
            if (previous.status == StateLoadResult.Status.OK)
                vault.saveRecovery(identity, previous.state, null,
                        previous.snapshot.metadata.activePlayMillis);
        } else {
            Log.i(TAG, "Skipped in-memory recovery copy for large state engine=" +
                    entry.id + " bytes=" + state.length);
        }
        vault.saveQuickResume(identity, state, null, capturedActiveMillis);
        notifyRestoreAvailability();
        if (requireCommit)
            Log.i(TAG, "Committed Quick Resume before stop engine=" + entry.id +
                    " commit=" + entry.sourceCommit);
        // Canonical commit marker shared with the Phase 1 session; every
        // acceptance harness matches this exact engine/system phrasing.
        Log.i(TAG, "Quick Resume committed engine=" + entry.id +
                " system=" + request.systemId);
    }

    private void recordActiveProgress(ExperimentalGlesRenderLoop active) {
        if (!resumeRequested || checkpointScheduler == null || active == null) return;
        long elapsed;
        synchronized (this) {
            long now = SystemClock.elapsedRealtime();
            elapsed = activeFrameTickMillis == 0L ? 0L
                    : Math.max(0L, now - activeFrameTickMillis);
            activeFrameTickMillis = now;
        }
        if (checkpointScheduler.advanceActivePlay(elapsed) > 0)
            saveAutomatic();
    }

    private void saveAutomatic() {
        if (!checkpointPending.compareAndSet(false, true)) return;
        try {
            lifecycle.execute(() -> {
                try {
                    ExperimentalGlesRenderLoop active = renderLoop;
                    if (!prepared || active == null || vault == null || identity == null) return;
                    persistSaveRam(active);
                    if (!QuickResumePolicy.allowsRuntimeRestore(entry.id)) return;
                    vault.saveAutomatic(identity, active.serialize(), null,
                            checkpointScheduler == null ? currentActivePlayMillis()
                                    : checkpointScheduler.totalActiveMillis());
                    notifyRestoreAvailability();
                } catch (Throwable failure) {
                    Log.w(TAG, "Automatic checkpoint failed for " + entry.id, failure);
                } finally {
                    checkpointPending.set(false);
                }
            });
        } catch (java.util.concurrent.RejectedExecutionException rejected) {
            checkpointPending.set(false);
        }
    }

    private List<StateSnapshot> restorableHistory() {
        List<StateSnapshot> history = new ArrayList<>();
        if (vault == null || identity == null ||
                !QuickResumePolicy.allowsRuntimeRestore(entry.id)) return history;
        for (StateSnapshot snapshot : vault.list(identity))
            if (snapshot.metadata.kind != SnapshotKind.QUICK_RESUME)
                history.add(snapshot);
        return history;
    }

    private void notifyRestoreAvailability() {
        Listener callback = listener;
        if (callback != null)
            callback.onRestoreAvailabilityChanged(!restorableHistory().isEmpty());
    }

    private void restore(StateSnapshot snapshot) {
        lifecycle.execute(() -> {
            try {
                if (!QuickResumePolicy.allowsRuntimeRestore(entry.id))
                    throw new IllegalStateException(
                            entry.id + " runtime-state restore is not renderer-qualified");
                ExperimentalGlesRenderLoop active = renderLoop;
                if (!prepared || active == null || vault == null || identity == null) return;
                // Preserve the point being left so a timeline restore is reversible.
                vault.saveRecovery(identity, active.serialize(), null,
                        currentActivePlayMillis());
                StateLoadResult loaded = vault.loadSnapshot(identity, snapshot);
                if (loaded.status != StateLoadResult.Status.OK)
                    throw new IllegalStateException("snapshot failed validation: " + loaded.detail);
                applyRuntimeState(active, loaded.state);
                flushAudioAfterRestore();
                notifyRestoreAvailability();
            } catch (Throwable failure) {
                Listener callback = listener;
                if (callback != null) callback.onSessionError(
                        "EmuFusion could not restore that earlier point.", failure);
            }
        });
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

    private boolean dispatchAxis(GamepadDescriptor pad, int axis, int direction,
                                 boolean pressed) {
        try {
            InputSignal signal = InputSignal.axis(axis, direction);
            int button = canonicalButton(inputRouter.resolve(pad, signal));
            ExperimentalGlesRenderLoop active = renderLoop;
            if (button < 0 || active == null) return false;
            joypad.apply(signal, button, pressed, joypadSink);
            return true;
        } catch (Exception ignored) { return false; }
    }

    private void showControlsMenu(GamepadDescriptor pad) {
        String systemId = request == null ? "system" : request.systemId;
        String[] actions = {
                "Remap for " + systemId,
                "Remap for this game",
                "Reset " + systemId + " mapping",
                "Reset this game mapping"
        };
        new AlertDialog.Builder(context).setTitle(pad.name)
                .setItems(actions, (dialog, which) -> {
                    if (which < 2) showControlPicker(pad, which == 1);
                    else try { inputRouter.resetRemap(pad, which == 3); }
                    catch (Exception error) { showControlError(); }
                }).setNegativeButton("Done", null).show();
    }

    private void showControlPicker(GamepadDescriptor pad, boolean gameOnly) {
        final CanonicalControl[] controls = {
                CanonicalControl.DPAD_UP, CanonicalControl.DPAD_DOWN,
                CanonicalControl.DPAD_LEFT, CanonicalControl.DPAD_RIGHT,
                CanonicalControl.SOUTH, CanonicalControl.EAST,
                CanonicalControl.WEST, CanonicalControl.NORTH,
                CanonicalControl.L1, CanonicalControl.R1,
                CanonicalControl.L2, CanonicalControl.R2,
                CanonicalControl.START, CanonicalControl.SELECT
        };
        String[] labels = new String[controls.length];
        for (int index = 0; index < controls.length; index++)
            labels[index] = SystemControlLayouts.controlLabel(
                    request == null ? null : request.systemId, controls[index]);
        new AlertDialog.Builder(context).setTitle("Choose a control")
                .setItems(labels, (dialog, which) ->
                        captureControl(pad, controls[which], gameOnly))
                .setNegativeButton("Cancel", null).show();
    }

    private void captureControl(GamepadDescriptor pad, CanonicalControl control,
                                boolean gameOnly) {
        AlertDialog capture = new AlertDialog.Builder(context)
                .setTitle("Press a button for " + SystemControlLayouts.controlLabel(
                        request == null ? null : request.systemId, control))
                .setMessage("The next controller button becomes this control.")
                .setNegativeButton("Cancel", null).create();
        capture.setOnKeyListener((dialog, keyCode, event) -> {
            if (event.getAction() != KeyEvent.ACTION_DOWN || event.getRepeatCount() != 0)
                return true;
            try {
                EnumMap<CanonicalControl, InputSignal> mapping =
                        new EnumMap<>(CanonicalControl.class);
                mapping.putAll(gameOnly ? inputRouter.effectiveMapping(pad)
                        : inputRouter.effectiveSystemMapping(pad));
                mapping.put(control, InputSignal.key(keyCode));
                inputRouter.saveRemap(pad, gameOnly, mapping);
                dialog.dismiss();
            } catch (Exception error) {
                dialog.dismiss();
                showControlError();
            }
            return true;
        });
        capture.show();
    }

    private void showControlError() {
        new AlertDialog.Builder(context).setTitle("Controls")
                .setMessage("EmuFusion could not save this mapping.")
                .setPositiveButton("OK", null).show();
    }

    private void restoreSaveRam(ExperimentalGlesRenderLoop active) throws Exception {
        byte[] saved = DurableBlobStore.read(saveRamFile, MAX_SAVE_RAM_BYTES);
        if (saved != null) active.writeSaveRam(saved);
    }

    private void persistSaveRam(ExperimentalGlesRenderLoop active) throws Exception {
        persistSaveRam(active.readSaveRam());
    }

    private void persistSaveRam(byte[] value) throws Exception {
        if (value != null && value.length > 0)
            DurableBlobStore.write(saveRamFile, value, MAX_SAVE_RAM_BYTES);
    }

    private synchronized void finishActiveInterval() {
        if (activeStartedMillis == 0L) return;
        activePlayMillis += Math.max(0L,
                SystemClock.elapsedRealtime() - activeStartedMillis);
        activeStartedMillis = 0L;
    }

    private synchronized long currentActivePlayMillis() {
        if (activeStartedMillis == 0L) return activePlayMillis;
        return activePlayMillis + Math.max(0L,
                SystemClock.elapsedRealtime() - activeStartedMillis);
    }

    private void presentAudio(short[] samples) {
        AudioTrack audio = audioTrack;
        PcmAudioQueue queue = audioQueue;
        if (samples != null && samples.length > 0)
            receivedAudioFrames += samples.length / 2L;
        if (audio == null || queue == null) return;
        if (audioFocus.isSuppressed()) {
            // Another app owns the output. Drop what the core produced rather
            // than queueing it behind the paused track: the buffer would fill,
            // every later write would return 0, and the pending block would
            // pin the core's audio queue until focus came back.
            queue.clear();
            return;
        }
        if (samples != null && samples.length > 0) {
            int rejected = queue.offer(samples);
            if (rejected > 0) {
                droppedAudioFrames += rejected / 2L;
                if (!audioDropLogged) {
                    audioDropLogged = true;
                    Log.e(TAG, "Phase 2 PCM FIFO overflow engine=" + entry.id +
                            " droppedFrames=" + (rejected / 2) +
                            " totalDroppedFrames=" + droppedAudioFrames +
                            " marker=audio-pcm-drop");
                }
            }
        }
        boolean trackFilled = false;
        for (int attempt = 0; attempt < 8; attempt++) {
            synchronized (queue) {
                short[] head = queue.head();
                if (head == null) break;
                int offset = queue.headOffset();
                int requested = head.length - offset;
                try {
                    int written = Build.VERSION.SDK_INT >= 23
                            ? audio.write(head, offset, requested,
                                    AudioTrack.WRITE_NON_BLOCKING)
                            : audio.write(head, offset, requested);
                    if (written < 0) throw new IllegalStateException(
                            "AudioTrack write failed with code " + written);
                    if (written == 0) {
                        trackFilled = true;
                        break;
                    }
                    queue.consume(written);
                    writtenAudioFrames += written / 2L;
                    if (!audioStartedOnce) primedAudioSamples += written;
                } catch (Throwable failure) {
                    Log.e(TAG, "Phase 2 audio output failed engine=" + entry.id, failure);
                    if (audioFailureReported.compareAndSet(false, true)) {
                        Listener callback = listener;
                        if (callback != null) callback.onSessionError(
                                "EmuFusion lost audio output for this game.", failure);
                    }
                    return;
                }
            }
        }
        // Non-blocking backpressure proves the paused track is full, including
        // its retained pre-pause PCM. Counting only newly written samples
        // would wait forever for more space. The unwritten FIFO tail remains
        // intact and drains after play(). Initial startup keeps its usual prime.
        boolean canStart = audioStartedOnce
                ? trackFilled
                : primedAudioSamples >= audioPrimeSamplesTarget;
        if (resumeRequested && !audioFocus.isSuppressed() && canStart &&
                audio.getPlayState() != AudioTrack.PLAYSTATE_PLAYING) {
            audio.play();
            if (!audioStartedOnce) {
                audioStartedOnce = true;
                audioStartedAtMillis = SystemClock.elapsedRealtime();
                Log.i(TAG, "Audio playback started engine=" + entry.id +
                        " primedSamples=" + primedAudioSamples);
            } else {
                audioStartedAtMillis = SystemClock.elapsedRealtime();
                Log.i(TAG, "Audio playback resumed after buffer refill engine=" + entry.id);
            }
        }
        applySteadyAudioBuffer(audio);
    }

    private void applySteadyAudioBuffer(AudioTrack audio) {
        if (Build.VERSION.SDK_INT < 24 || !audioStartedOnce ||
                audio.getPlayState() != AudioTrack.PLAYSTATE_PLAYING ||
                steadyAudioBufferApplied ||
                SystemClock.elapsedRealtime() - audioStartedAtMillis < 5_000L) return;
        int frames = steadyAudioBufferBytes(audio.getSampleRate()) / 4;
        if (frames > 0 && audio.setBufferSizeInFrames(frames) > 0)
            steadyAudioBufferApplied = true;
    }

    private void flushAudioAfterRestore() {
        PcmAudioQueue queue = audioQueue;
        if (queue != null) queue.clear();
        primedAudioSamples = 0;
        audioStartedOnce = false;
        audioStartedAtMillis = 0L;
        audioFailureReported.set(false);
        steadyAudioBufferApplied = false;
        AudioTrack audio = audioTrack;
        if (audio == null) return;
        try {
            audio.pause();
            audio.flush();
            // applySteadyAudioBuffer() shrinks the streaming track after the
            // warm-up period, and pause()/flush() preserves that smaller
            // capacity.  A reset or state restore must prime against the
            // original startup target again.  Without restoring the startup
            // capacity first, the paused track fills below
            // audioPrimeSamplesTarget, play() can never be called, and every
            // subsequent core block overflows the Java PCM FIFO.  The
            // software libretro route enforces the same invariant.
            if (Build.VERSION.SDK_INT >= 24) {
                int startupFrames = startupAudioBufferBytes(
                        audio.getSampleRate()) / 4;
                if (startupFrames > 0)
                    audio.setBufferSizeInFrames(startupFrames);
            }
            // Playback restarts only after fresh post-restore PCM is primed.
        } catch (Throwable ignored) {}
    }

    @SuppressWarnings("deprecation")
    private AudioTrack createAudioTrack(double sampleRate) {
        int rate = (int) Math.round(sampleRate);
        if (rate < 8_000 || rate > 192_000) return null;
        int bufferBytes = startupAudioBufferBytes(sampleRate);
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
            AppVolumeController.registerTrack(appContext, track);
            return track;
        }
        track.release();
        return null;
    }

    private int startupAudioBufferBytes(double sampleRate) {
        int rate = (int) Math.round(sampleRate);
        if (rate < 8_000 || rate > 192_000) return 0;
        int minimum = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_STEREO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) return 0;
        // Play's EE JIT exhibits isolated >200 ms compilation stalls during
        // game/menu transitions on the Thor. Allocate and fully prime a 500
        // ms queue for Play so those stalls do not disable AudioTrack. Other
        // Phase 2 engines retain the proven 200 ms startup queue.
        int targetDivisor = isPs2Engine() ? 2 : 5;
        return Math.max(minimum, rate / targetDivisor * 4);
    }

    private int steadyAudioBufferBytes(double sampleRate) {
        int rate = (int) Math.round(sampleRate);
        if (rate < 8_000 || rate > 192_000) return 0;
        int minimum = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_STEREO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) return 0;
        // PS2 EE JIT can briefly stop producing PCM while compiling a new
        // block, so that route retains the full startup cushion. PPSSPP was
        // previously shrunk to 50 ms, but repeated Thor runs gained underruns
        // after roughly 55 seconds despite exact 60 Hz video cadence. A 100 ms
        // PPSSPP target protects that device-level scheduling tail without
        // imposing the PS2 route's much larger latency on it. Other Phase 2
        // engines retain the proven 50 ms target.
        int targetDivisor = isPs2Engine() ? 2 :
                ("ppsspp".equals(entry.id) ? 10 : 20);
        return Math.max(minimum, rate / targetDivisor * 4);
    }

    private boolean isPs2Engine() {
        // "play" is the legacy PS2 route; armsx2 is the current built-in
        // route and has the same long EE/JIT stalls this cushion was created
        // for.  Keying only on the retired id silently shrank armsx2 to the
        // generic 50 ms steady buffer and caused recurring Thor underruns.
        return "play".equals(entry.id) || "armsx2".equals(entry.id);
    }

    private int audioQueueCapacitySamples(double sampleRate) {
        int startupSamples = startupAudioBufferBytes(sampleRate) / 2;
        return Math.max(8_192, startupSamples * 3);
    }

    private void recordFrameHealth() {
        long now = SystemClock.elapsedRealtime();
        if (frameSampleStartedAtMillis == 0L) frameSampleStartedAtMillis = now;
        presentedFrames++;
        if (presentedFrames % 300L != 0L) return;
        long elapsed = Math.max(1L, now - frameSampleStartedAtMillis);
        float fps = presentedFrames * 1_000f / elapsed;
        AudioTrack audio = audioTrack;
        int underruns = Build.VERSION.SDK_INT >= 24 && audio != null
                ? audio.getUnderrunCount() : -1;
        // The playback head only advances when the mixer consumes PCM, so it
        // separates "samples written to a stalled track" from audible output.
        int audioHead = 0;
        if (audio != null)
            try { audioHead = audio.getPlaybackHeadPosition(); }
            catch (IllegalStateException ignored) {}
        Log.i(TAG, "Health engine=" + entry.id + " fps=" +
                String.format(Locale.US, "%.2f", fps) + " frames=" + presentedFrames +
                " audioUnderruns=" + underruns + " audioReceived=" +
                receivedAudioFrames + " audioWritten=" + writtenAudioFrames +
                " audioDropped=" + droppedAudioFrames +
                " audioRate=" + (audio == null ? 0 : audio.getSampleRate()) +
                " audioStarted=" + audioStartedOnce + " audioHead=" + audioHead);
        if (!audioSilenceWarned && (audio == null || !audioStartedOnce || audioHead == 0)) {
            audioSilenceWarned = true;
            Log.w(TAG, "Audio silent after health window engine=" + entry.id +
                    " trackPresent=" + (audio != null) +
                    " started=" + audioStartedOnce +
                    " primed=" + primedAudioSamples +
                    " primeTarget=" + audioPrimeSamplesTarget +
                    " head=" + audioHead);
        }
    }

    private void releaseAudio() {
        PcmAudioQueue queue = audioQueue;
        audioQueue = null;
        if (queue != null) queue.clear();
        primedAudioSamples = 0;
        audioPrimeSamplesTarget = 0;
        audioStartedOnce = false;
        audioStartedAtMillis = 0L;
        steadyAudioBufferApplied = false;
        audioSilenceWarned = false;
        presentedFrames = 0L;
        frameSampleStartedAtMillis = 0L;
        receivedAudioFrames = 0L;
        writtenAudioFrames = 0L;
        AudioTrack audio = audioTrack;
        audioTrack = null;
        if (audio == null) return;
        try { audio.stop(); } catch (IllegalStateException ignored) {}
        AppVolumeController.unregisterTrack(audio);
        audio.release();
    }

    private static File resolveGameFile(Uri uri) throws Exception {
        if (uri == null) throw new IllegalArgumentException("PSP URI is missing");
        String raw = "file".equals(uri.getScheme()) ? uri.getPath() :
                uri.getQueryParameter("path");
        if (raw == null || raw.trim().isEmpty())
            throw new IllegalArgumentException("PSP URI does not expose a local file");
        File file = new File(raw).getCanonicalFile();
        String path = file.getPath();
        if (!(path.startsWith("/storage/") || path.startsWith("/mnt/media_rw/")) ||
                !file.isFile())
            throw new IllegalArgumentException("PSP game is outside approved Android storage");
        return file;
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        InputStream input = new FileInputStream(file);
        try {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) digest.update(buffer, 0, count);
        } finally { input.close(); }
        StringBuilder result = new StringBuilder(64);
        for (byte value : digest.digest())
            result.append(String.format(Locale.US, "%02x", value & 0xff));
        return result.toString();
    }

    private static int retroButton(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_BUTTON_A: return 0;
            case KeyEvent.KEYCODE_BUTTON_X: return 1;
            case KeyEvent.KEYCODE_BUTTON_SELECT: return 2;
            case KeyEvent.KEYCODE_BUTTON_START: return 3;
            case KeyEvent.KEYCODE_DPAD_UP: return 4;
            case KeyEvent.KEYCODE_DPAD_DOWN: return 5;
            case KeyEvent.KEYCODE_DPAD_LEFT: return 6;
            case KeyEvent.KEYCODE_DPAD_RIGHT: return 7;
            case KeyEvent.KEYCODE_BUTTON_B: return 8;
            case KeyEvent.KEYCODE_BUTTON_Y: return 9;
            case KeyEvent.KEYCODE_BUTTON_L1: return 10;
            case KeyEvent.KEYCODE_BUTTON_R1: return 11;
            case KeyEvent.KEYCODE_BUTTON_L2: return 12;
            case KeyEvent.KEYCODE_BUTTON_R2: return 13;
            case KeyEvent.KEYCODE_BUTTON_THUMBL: return 14;
            case KeyEvent.KEYCODE_BUTTON_THUMBR: return 15;
            default: return -1;
        }
    }

    private int canonicalButton(CanonicalControl control) {
        return LibretroJoypadLayout.idFor(request.systemId, control);
    }

    private static boolean isWiiSystem(String systemId) {
        if (systemId == null) return false;
        String system = systemId.toLowerCase(Locale.US)
                .replaceAll("[^a-z0-9]", "");
        return "wii".equals(system) || "nintendowii".equals(system);
    }

    private static float normalizeAxis(MotionEvent event, int axis) {
        float value = event.getAxisValue(axis);
        float magnitude = Math.abs(value);
        if (magnitude <= AXIS_DEAD_ZONE) return 0f;
        return Math.copySign(Math.min(1f,
                (magnitude - AXIS_DEAD_ZONE) / (1f - AXIS_DEAD_ZONE)), value);
    }

    private static void voidDimensions(int width, int height) {
        if (width < 0 || height < 0)
            throw new IllegalArgumentException("surface dimensions cannot be negative");
    }

    private static String formatPlayTime(long millis) {
        long minutes = Math.max(0L, millis) / 60_000L;
        return minutes < 60 ? minutes + " min"
                : (minutes / 60) + "h " + (minutes % 60) + "m";
    }
}
