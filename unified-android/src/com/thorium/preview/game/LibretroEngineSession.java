package com.thorium.preview.game;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.net.Uri;
import android.os.Build;
import android.os.SystemClock;
import android.util.Log;
import android.view.KeyEvent;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.Surface;

import com.thorium.lucent.input.CanonicalControl;
import com.thorium.lucent.audio.PcmAudioQueue;
import com.thorium.lucent.audio.PcmSignalTelemetry;
import com.thorium.lucent.input.DeviceCatalog;
import com.thorium.lucent.input.FileRemapStore;
import com.thorium.lucent.input.GamepadDescriptor;
import com.thorium.lucent.input.InputRouter;
import com.thorium.lucent.input.InputSignal;
import com.thorium.lucent.input.JoypadPressLedger;
import com.thorium.lucent.input.LibretroJoypadLayout;
import com.thorium.lucent.input.SystemControlLayouts;
import com.thorium.lucent.input.android.AndroidDeviceScanner;
import com.thorium.lucent.input.android.AndroidGamingDeviceDetector;
import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.lucent.cheats.CheatSelection;
import com.thorium.preview.cheats.CheatControl;
import com.thorium.lucent.state.CheckpointScheduler;
import com.thorium.lucent.state.DurableBlobStore;
import com.thorium.lucent.state.StateIdentity;
import com.thorium.lucent.state.StateLoadResult;
import com.thorium.lucent.state.StateSnapshot;
import com.thorium.lucent.state.StateVault;
import com.thorium.lucent.state.StateVaultWorker;
import com.thorium.lucent.timing.AbsoluteFramePacer;
import com.thorium.lucent.timing.DisplaySyncPolicy;
import com.thorium.lucent.timing.DirectVideoTelemetry;
import com.thorium.preview.AppVolumeController;
import com.thorium.lucent.timing.LatestValueMailbox;
import com.thorium.lucent.video.DualScreenLayout;
import com.thorium.lucent.video.PresentationGeometry;
import com.thorium.preview.LibretroHost;
import com.thorium.preview.SecondaryGameplaySurfaceRouter;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.security.MessageDigest;
import java.text.DateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/** One release-qualified libretro core behind EmuFusion's engine-neutral shell. */
public final class LibretroEngineSession implements EngineSession,
        SecondaryGameplaySurfaceRouter.Listener,
        com.thorium.lucent.netplay.NetplayCapableSession {
    private static final String TAG = "LucentEngine";
    private static final long FRAME_NS = 1_000_000_000L / 60L;
    private static final float AXIS_PRESS = 0.55f;
    private static final int MAX_VIDEO_DIMENSION = 8192;
    private static final long MAX_VIDEO_PIXELS = 16L * 1024L * 1024L;
    private static final int MAX_SAVE_RAM_BYTES = 64 * 1024 * 1024;
    private static final long QUALIFICATION_WARMUP_FRAMES = 120L;
    private static final long QUALIFICATION_MEASURED_FRAMES = 300L;

    private final Context context;
    private final Context appContext;
    private final LibretroEngineSpec entry;
    private final ExecutorService lifecycle = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "lucent-engine-lifecycle");
        thread.setDaemon(true);
        return thread;
    });
    private final AtomicBoolean stopping = new AtomicBoolean(false);
    private final AtomicBoolean released = new AtomicBoolean(false);
    private final Object runLock = new Object();
    /** Serializes a Surface handoff with the independent Canvas/FG producer. */
    private final java.util.concurrent.locks.ReentrantLock presentationLock =
            new java.util.concurrent.locks.ReentrantLock();
    private final Object lifecycleSubmissionLock = new Object();
    // A request is not an acknowledgement: all callers wait for the same
    // completed save/release instead of advancing a second retirement early.
    private final List<Completion> stopCompletions = new ArrayList<>();
    private final List<Completion> releaseCompletions = new ArrayList<>();
    private boolean stopCompleted;
    private boolean releaseCompleted;
    private boolean destroyStopRequested;
    // The selection is written on the lifecycle thread at load and on the UI
    // thread by the pause menu, and read by both, so it gets its own monitor
    // rather than riding on one that a native call already holds.
    private final Object cheatLock = new Object();
    private final AtomicLong cheatApplySequence = new AtomicLong();
    private final LatestValueMailbox<LibretroHost.VideoFrame> videoMailbox =
            new LatestValueMailbox<>();

    private volatile Listener listener;
    private volatile LibretroHost host;
    // The hat, the left stick and any BTN_DPAD_* keys all mean "the D-pad" on a
    // D-pad-only console, so several sources can assert one libretro ID. The
    // ledger ORs them; writing each source straight through made the last
    // writer win and a centred stick cleared a physically held hat direction.
    // Declared after host: an initializer cannot forward-reference a field.
    private final JoypadPressLedger joypad = new JoypadPressLedger();
    /**
     * Null unless a netplay match is active for this session; broadcasts
     * local port-0 button transitions to every connected peer and applies
     * theirs back onto their assigned ports. See NetplayInputRelay's own
     * doc comment for the full contract. Declared before joypadSink for
     * the same forward-reference reason as host/joypad above -- javac
     * rejects joypadSink's lambda body reading this field's simple name
     * otherwise, even though the lambda only runs later.
     */
    private volatile com.thorium.lucent.netplay.NetplayInputRelay netplayRelay;
    private final JoypadPressLedger.Sink joypadSink = (retroId, pressed) -> {
        // Log the aggregate libretro boundary, not only Android key events.
        // This also catches remaps, axis alternatives and virtual controls,
        // which is required to diagnose a core-visible Start press without
        // guessing which Android input path supplied it.
        if (retroId == 3) {
            Log.i(TAG, "Joypad aggregate Start transition pressed=" + pressed);
        }
        LibretroHost active = host;
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
     * The netplay integration point: applies one remote player's input to
     * a non-local port. The native host already supports up to 8
     * controllers (lucent_libretro_host.c's MAX_PORTS), unused by
     * anything else in this class, which only ever drives port 0 for the
     * player physically holding this device. Safe to call from any
     * thread -- LibretroHost's setters only record the state --
     * ordinarily called from a NetplaySession's WebRTC DataChannel
     * callback thread, deliberately never routed through the UI/frame
     * thread first (see NetplaySession.DataListener's own doc comment on
     * why that hop is avoided).
     */
    public void applyRemoteJoypadButton(int port, int retroId, boolean pressed) {
        if (port < 1 || port > 7)
            throw new IllegalArgumentException("remote port must be 1..7; port 0 is local input");
        LibretroHost active = host;
        if (active != null) active.setJoypadButton(port, retroId, pressed);
    }

    public void applyRemoteAnalogAxis(int port, int retroAnalogIndex, int retroAnalogId,
                                       float normalizedValue) {
        if (port < 1 || port > 7)
            throw new IllegalArgumentException("remote port must be 1..7; port 0 is local input");
        LibretroHost active = host;
        if (active != null) active.setAnalogAxis(port, retroAnalogIndex, retroAnalogId, normalizedValue);
    }

    /** {@link com.thorium.lucent.netplay.NetplayCapableSession}: the same serialize() Quick Resume already uses. */
    public byte[] currentSerializedStateForDesync() {
        LibretroHost active = host;
        if (active == null) return null;
        try {
            byte[] state = active.serialize();
            return state != null && state.length > 0 ? state : null;
        } catch (Throwable ignored) {
            return null;
        }
    }

    private volatile boolean running;
    private volatile boolean prepared;
    private volatile Thread frameThread;
    private volatile Thread renderThread;
    private volatile DirectDisplayVsync directDisplayVsync;
    private volatile double displayAudioClockHz;
    private long displayAudioClockUpdatedNs;
    private boolean displayClockWasActive;
    private boolean physicalFgClockApplied;
    private FrameGenerationRenderer physicalFgClockOwner;
    private double physicalFgClockDeclaration;
    private volatile Runnable firstFrameCallback;
    private volatile GameLaunchRequest request;
    private volatile Surface surface;
    private volatile long directSurfaceEpoch;
    private volatile long directSecondarySurfaceEpoch;
    /** The core's reported display aspect, or 0 when it reported none. */
    private volatile float displayAspect;
    private volatile int surfaceWidth;
    private volatile int surfaceHeight;
    private volatile Surface secondarySurface;
    private volatile int secondarySurfaceWidth;
    private volatile int secondarySurfaceHeight;
    private volatile boolean secondaryGameplayRequested;
    // Preserve native DS panel identity by default: top above, touch below.
    // Explicit per-game swaps still win; do not infer screen identity from
    // which panel happens to contain gameplay in a particular title.
    private static final boolean DEFAULT_DS_TOUCH_ON_PRIMARY = false;
    private volatile boolean dsTouchOnPrimary = DEFAULT_DS_TOUCH_ON_PRIMARY;
    private String dsLayoutPreferenceKey = "";
    private final Object dsTouchLock = new Object();
    private int primaryStylusPointerId = -1;
    private StateVault vault;
    // Bounded image observations only: unchanged pixels cannot establish a
    // failed restore or authorize discarding progress/resetting the game.
    private volatile boolean quickResumeLivenessWatch;
    private int dualCropDiagCountdown;
    private long quickResumeLastCropSignature = Long.MIN_VALUE;
    private int quickResumeFrozenRepeats;
    private int quickResumeChangesSeen;
    private StateVaultWorker vaultWorker;
    private StateIdentity identity;
    private CheckpointScheduler checkpointScheduler;
    private InputRouter inputRouter;
    private List<GamepadDescriptor> devices = new ArrayList<>();
    private long activeTickMillis;
    private volatile long framePeriodNs = FRAME_NS;
    private volatile double declaredVideoHz;
    private volatile double synchronizedCoreHz;
    private volatile double pacedCoreHz;
    // Frame-work headroom ring: worst core work time per completed second.
    private static final int WORK_RING_SECONDS = 15;
    private final long[] workWorstNsRing = new long[WORK_RING_SECONDS];
    private int workRingFilled;
    private int workRingIndex;
    private long workSecondStartNs;
    private long workSecondWorstNs;
    private int workSecondFrames;
    private volatile double achievedCoreHzSnapshot;
    private volatile double frameWorkCapacityHzSnapshot;
    private int lastVideoSequence = -1;
    private boolean frameEvidenceLogged;
    private boolean lowerDrawEvidenceLogged;
    private boolean directHardwareCanvasFallbackLogged;
    private DirectHardwareCanvas primaryDirectCanvas;
    private DirectHardwareCanvas secondaryDirectCanvas;
    private boolean timestampedDirectCanvasUnavailable;
    private boolean primaryRecoverySurfaceCanvas;
    private Bitmap frameBitmap;
    private int[] frameColors;
    private int[] dsPhoneColors;
    private final Rect primarySourceRect = new Rect();
    private final Rect secondarySourceRect = new Rect();
    private final RectF frameDestinationRect = new RectF();
    private final Paint filteredFramePaint = new Paint(
            Paint.DITHER_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final Paint nearestFramePaint = new Paint(Paint.DITHER_FLAG);
    // Written on the lifecycle thread during prepare and read on the frame
    // thread. Thread.start() already publishes them, but volatile keeps any
    // future writer (audio recovery, restore) safe without re-auditing.
    private volatile AudioTrack audioTrack;
    /**
     * The focus this session holds while it plays. Declared final and built in
     * the constructor so no teardown path can reach a null one and leak focus.
     */
    private final EngineAudioFocus audioFocus;
    /**
     * PCM drained from the core but not yet accepted by AudioTrack. Keeping a
     * bounded FIFO is essential: a partial non-blocking write must not stop us
     * draining later core output, and no overflow may disappear without an
     * exact counter and QA marker.
     */
    private volatile PcmAudioQueue audioQueue;
    /** Signal-only evidence at the native-drain boundary, before AudioTrack. */
    private volatile PcmSignalTelemetry audioSignalTelemetry;
    private final Object audioTelemetryLock = new Object();
    private int primedAudioSamples;
    private volatile int audioPrimeSamplesTarget;
    private volatile boolean audioStartedOnce;
    private boolean audioSilenceWarned;
    private long audioStartedAtMillis;
    private boolean steadyAudioBufferApplied;
    private File saveRamFile;
    /** Null until the loaded game turns out to have cheats. Guarded by cheatLock. */
    private CheatSelection cheats;
    private String cheatGameKey = "";
    private long qualificationFrameCount;
    private long qualificationStartedNanos;
    private long qualificationAudioSamplesWritten;
    private long qualificationAudioSamplesAtWindowStart;
    // Core cadence is not display cadence. These counters prove how many
    // source frames entered the bounded handoff and how many direct Canvas
    // posts actually succeeded on the presentation thread.
    private final DirectVideoTelemetry directVideoTelemetry =
            new DirectVideoTelemetry();
    private long audioProducedSamples;
    private long audioDroppedSamples;
    private long audioFocusDroppedSamples;
    private long audioPartialWrites;
    private long audioZeroWrites;
    private long audioWriteErrors;
    private long audioNativeDrainBoundHits;
    private long qualificationAudioProducedAtWindowStart;
    private long qualificationAudioDroppedAtWindowStart;
    private long qualificationAudioFocusDroppedAtWindowStart;
    private long qualificationAudioPartialWritesAtWindowStart;
    private long qualificationAudioZeroWritesAtWindowStart;
    private long qualificationAudioWriteErrorsAtWindowStart;
    private long qualificationAudioNativeDrainBoundHitsAtWindowStart;
    private int qualificationAudioUnderrunsAtWindowStart = -1;
    private boolean audioDropLogged;
    private boolean audioWriteFailureLogged;
    private boolean audioNativeDrainBoundLogged;
    private boolean qualificationInputLogged;

    public LibretroEngineSession(Context context, InternalEngineCatalog.Entry entry) {
        this(context, LibretroEngineSpec.phaseOne(entry));
    }

    LibretroEngineSession(Context context, LibretroEngineSpec entry) {
        if (context == null || entry == null)
            throw new IllegalArgumentException("context and engine entry are required");
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

    @Override public void prepare(GameLaunchRequest launch, Listener callback) {
        if (launch == null || callback == null) throw new IllegalArgumentException("launch required");
        listener = callback;
        request = launch;
        lifecycle.execute(() -> {
            try {
                if (!entry.id.equals(launch.engineId) || !entry.supports(launch.systemId))
                    throw new IllegalStateException("Engine is not approved for " + launch.systemId);
                if (!entry.isInstalled(appContext))
                    throw new IllegalStateException("Approved core is not present in this build");

                File game = resolveGameFile(launch.contentUri);
                // Content identity, rather than its current storage path, owns
                // saves, remaps, and restore history. Moving a ROM between
                // internal storage and an SD card must not orphan progress.
                String romSha = GameContentIdentityCache.sha256(appContext, game);
                if (isDualScreenSystem(launch.systemId)) {
                    dsLayoutPreferenceKey = launch.qualificationSession.isEmpty() ? romSha :
                            "qa:" + launch.qualificationSession + ":" + romSha;
                    dsTouchOnPrimary = appContext.getSharedPreferences(
                            "ds-screen-order-v1", Context.MODE_PRIVATE)
                            .getBoolean(dsLayoutPreferenceKey, DEFAULT_DS_TOUCH_ON_PRIMARY);
                    Log.i(TAG, "DS screen order touchOnPrimary=" + dsTouchOnPrimary);
                }
                LibretroEngineSpec.SystemInstallation runtime =
                        entry.installRuntime(appContext, launch.systemId);
                File system = runtime.directory;
                String saveRoot = !launch.qualificationSession.isEmpty() ?
                        "engine-saves-qa/" + launch.qualificationSession :
                        "engine-saves";
                if (!launch.qualificationSession.isEmpty())
                    Log.i(TAG, "Isolated qualification runtime state engine=" +
                            entry.id + " namespace=" + launch.qualificationSession);
                File saves = new File(appContext.getFilesDir(),
                        saveRoot + "/" + storageKey(romSha));
                if (!saves.isDirectory() && !saves.mkdirs())
                    throw new IllegalStateException("Cannot create game save directory");
                String firmware = "firmware:none".equals(runtime.firmwareIdentity)
                        ? firmwareFingerprint(system, entry.firmwareRequired,
                                entry.acceptedFirmwareHashes) : runtime.firmwareIdentity;
                boolean widescreenEnhancements =
                        WidescreenSettings.isEnabled(appContext);
                LibretroHost opened = new LibretroHost(entry.coreFile,
                        entry.coreFile.getParentFile(), system, saves,
                        widescreenEnhancements);
                Log.i(TAG, "Built-in widescreen profile engine=" + entry.id +
                        " enabled=" + widescreenEnhancements);
                try {
                    opened.loadGame(game);
                    // Loading resets port 0 to a plain RetroPad. Systems whose
                    // controller is something else must say so now: Dolphin
                    // only attaches the Wii Nunchuk for RETRO_DEVICE_WIIMOTE_NC,
                    // and titles that require it (Super Mario Galaxy 2) accept
                    // no input at all until the extension is present.
                    int portDevice =
                            LibretroJoypadLayout.portDeviceFor(launch.systemId);
                    if (portDevice != LibretroJoypadLayout.RETRO_DEVICE_JOYPAD) {
                        opened.setControllerPortDevice(0, portDevice);
                        Log.i(TAG, "Controller port device engine=" + entry.id +
                                " system=" + launch.systemId +
                                " device=0x" + Integer.toHexString(portDevice));
                    }
                    saveRamFile = new File(saves, "save-ram.bin");
                    restoreSaveRam(opened, saveRamFile);
                    applyStoredCheats(opened, launch, game.getName());
                    LibretroHost.AvInfo av = opened.avInfo();
                    // Console pixels are rarely square. The SNES draws 256x239
                    // but displayed it at 4:3, so scaling by the raw pixel
                    // dimensions renders it far too narrow and leaves unused
                    // screen on a 16:9 panel. Cores report their true display
                    // aspect in retro_game_geometry, which is what the picture
                    // must be fitted to; a core that reports nothing usable
                    // falls back to the pixel dimensions, which is the old
                    // behaviour and correct for the square-pixel systems.
                    displayAspect = av.aspectRatio > 0.1f && av.aspectRatio < 10f
                            ? av.aspectRatio : 0f;
                    double synchronizedVideoHz =
                            DisplaySyncPolicy.synchronizedSourceHz(av.framesPerSecond);
                    if (synchronizedVideoHz > 1.0 && synchronizedVideoHz < 1000.0)
                        framePeriodNs = Math.max(1L,
                                Math.round(1_000_000_000.0 / synchronizedVideoHz));
                    declaredVideoHz = av.framesPerSecond;
                    synchronizedCoreHz = synchronizedVideoHz;
                    pacedCoreHz = 0.0;
                    publishLowerSourceCadence();
                    opened.setSynchronizedVideoRate(
                            av.framesPerSecond, synchronizedVideoHz);
                    Log.i(TAG, String.format(Locale.ROOT,
                            "Display-synchronized core clock engine=%s system=%s " +
                            "declaredHz=%.6f synchronizedHz=%.6f panelHz=%.0f " +
                            "uniform=%s",
                            entry.id, launch.systemId, av.framesPerSecond,
                            synchronizedVideoHz,
                            DisplaySyncPolicy.panelRefreshHz(synchronizedVideoHz),
                            DisplaySyncPolicy.isUniformOnThor(synchronizedVideoHz)));
                    audioTrack = createAudioTrack(av.sampleRate);
                    audioPrimeSamplesTarget = startupAudioBufferBytes(av.sampleRate) / 2;
                    audioQueue = new PcmAudioQueue(audioQueueCapacitySamples(av.sampleRate));
                    int audioSampleRate = (int) Math.round(av.sampleRate);
                    audioSignalTelemetry = audioSampleRate >= 8_000 && audioSampleRate <= 192_000
                            ? new PcmSignalTelemetry(audioSampleRate) : null;
                    if (audioTrack == null)
                        // A dead track must be loud in the log: every later
                        // write silently no-ops and the game plays mute.
                        Log.w(TAG, "Audio track unavailable engine=" + entry.id +
                                " rate=" + av.sampleRate);
                    else
                        Log.i(TAG, "Audio track ready engine=" + entry.id +
                                " rate=" + (int) Math.round(av.sampleRate) +
                                " primeTargetSamples=" + audioPrimeSamplesTarget);
                    EngineAudioLog.logResolvedStream(appContext, TAG, entry.id,
                            audioTrack);
                    // Focus is taken as soon as this session owns an output,
                    // not when the first sample is written: everything after
                    // this point can fail, and the teardown paths below all
                    // give it back.
                    audioFocus.request();
                    long previousActive = 0L;
                    if (!"scummvm".equals(entry.id)) {
                        String engineIdentity = entry.sourceCommit + ":sha256:" +
                                entry.coreArtifactSha256;
                        if (!launch.qualificationSession.isEmpty())
                            engineIdentity += ":qa:" + launch.qualificationSession;
                        identity = new StateIdentity(romSha, romSha, entry.id,
                                engineIdentity,
                                "serialize-v" + entry.stateCompatibilityVersion,
                                firmware);
                        vault = StateVault.shared(new File(appContext.getFilesDir(), "state-vault"));
                        vaultWorker = new StateVaultWorker(vault);
                        StateLoadResult quick = vault.loadQuickResume(identity);
                        if (quick.status == StateLoadResult.Status.OK) {
                            try {
                                opened.unserialize(quick.state);
                                previousActive = quick.snapshot.metadata.activePlayMillis;
                                quickResumeLivenessWatch = true;
                                Log.i(TAG, "Quick Resume restored engine=" + entry.id +
                                        " system=" + launch.systemId);
                            } catch (Throwable rejectedState) {
                                // A core can reject a state even after EmuFusion validates its
                                // identity and checksum. Boot normally and retain it for
                                // recovery instead of making the game unlaunchable.
                                Log.w(TAG, "Engine rejected a matching Quick Resume; " +
                                        "booting normally engine=" + entry.id +
                                        " system=" + launch.systemId, rejectedState);
                            }
                        }
                        checkpointScheduler = new CheckpointScheduler(
                                CheckpointScheduler.DEFAULT_INTERVAL_MILLIS, previousActive);
                    }
                    inputRouter = new InputRouter(DeviceCatalog.standard(),
                            new FileRemapStore(new File(appContext.getFilesDir(),
                                    "controls/remaps.properties")),
                            AndroidGamingDeviceDetector.isKnownGamingHandheld());
                    inputRouter.setGame(launch.systemId, romSha);
                    refreshDevices();
                    qualificationFrameCount = 0L;
                    qualificationStartedNanos = 0L;
                    qualificationAudioSamplesWritten = 0L;
                    qualificationAudioSamplesAtWindowStart = 0L;
                    resetAudioTelemetry();
                    qualificationInputLogged = false;
                    host = opened;
                    secondaryGameplayRequested = isDualScreenSystem(launch.systemId) &&
                            SecondaryGameplaySurfaceRouter.request(
                                    appContext, launch.systemId, this);
                    prepared = true;
                    startRenderThread();
                    startFrameThread();
                    notifyRestoreAvailability();
                    callback.onSessionReady();
                } catch (Throwable failure) {
                    // Even a ready/restore callback can fail after the frame
                    // and render workers were started. Retain the host for
                    // queued, acknowledged teardown instead of closing it
                    // here underneath those workers.
                    host = opened;
                    throw failure;
                }
            } catch (Throwable failure) {
                // A session that never started must not keep the focus its
                // aborted preparation took, or every other app stays ducked.
                try { audioFocus.abandon(); }
                catch (Throwable cleanupFailure) {
                    Log.e(TAG, "Failed preparation audio focus release", cleanupFailure);
                }
                try { releaseWhenComplete(() -> {}); }
                catch (Throwable cleanupFailure) {
                    Log.e(TAG, "Failed preparation release not acknowledged", cleanupFailure);
                }
                Log.e(TAG, "Unable to prepare " + launch.engineId + " for "
                        + launch.systemId, failure);
                callback.onSessionError(failure instanceof PcEngineCdFirmware.SetupException
                        ? failure.getMessage() : "EmuFusion could not start " +
                        (launch.gameTitle.isEmpty() ? "this game" : launch.gameTitle) + ".", failure);
            }
        });
    }

    /** Exact video clock reported by retro_get_system_av_info after load. */
    @Override public double declaredVideoHz() { return declaredVideoHz; }

    @Override public double pacedVideoHz() { return pacedCoreHz; }
    /** Actual scheduled guest clock, distinct from the original core declaration. */
    public double effectiveVideoHz() {
        return pacedCoreHz > 0.0 ? pacedCoreHz : synchronizedCoreHz;
    }
    @Override public double achievedCoreHz() { return achievedCoreHzSnapshot; }
    @Override public double sustainedFrameWorkCapacityHz() {
        return frameWorkCapacityHzSnapshot;
    }

    @Override public boolean setPacedVideoHz(double hz) {
        LibretroHost active = host;
        double synchronizedHz = synchronizedCoreHz;
        double declaredHz = declaredVideoHz;
        if (active == null || !(synchronizedHz > 1.0) || !(declaredHz > 1.0))
            return false;
        // Only a bounded trim of the declared guest clock is allowed. Reject
        // unsafe/invalid requests without changing the current clock; only
        // an explicit zero restores the existing synchronized clock.
        double target = hz;
        if (hz != 0.0 && !DisplaySyncPolicy.permitsCoreClockCorrection(declaredHz, hz))
            return false;
        if (Math.abs(target - pacedCoreHz) < 1.0e-4) return true;
        double clock = target > 0.0 ? target : synchronizedHz;
        try {
            // Same mechanism the display synchronization already uses: the
            // Java pacer owns the core clock and the native audio resampler
            // follows the declared-to-clock ratio.  The synchronized clock
            // itself is computed once at open and is never modified here.
            active.setSynchronizedVideoRate(declaredHz, clock);
        } catch (RuntimeException failure) {
            Log.w(TAG, "Tier pacing rejected engine=" + entry.id +
                    " clock=" + clock, failure);
            return false;
        }
        pacedCoreHz = target;
        displayAudioClockHz = 0;
        publishPrimarySourceCadence();
        publishLowerSourceCadence();
        framePeriodNs = Math.max(1L, Math.round(1_000_000_000.0 / clock));
        Log.i(TAG, String.format(Locale.ROOT,
                "Tier pacing engine=%s declaredHz=%.6f synchronizedHz=%.6f " +
                "pacedHz=%.3f coreClockHz=%.6f",
                entry.id, declaredHz, synchronizedHz, target, clock));
        return true;
    }

    /** Frame-thread only: folds one core frame's work time into the ring. */
    private void recordFrameWork(long startNs, long endNs) {
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

    @Override public void attachSurface(Surface surface, int width, int height) {
        ++directSurfaceEpoch;
        this.surface = surface;
        surfaceWidth = width;
        surfaceHeight = height;
    }

    @Override public void resizeSurface(int width, int height) {
        surfaceWidth = width;
        surfaceHeight = height;
    }
    @Override public void detachSurface() {
        surface = null;
        retireDetachedCanvas(false);
    }

    private void retireDetachedCanvas(boolean secondary) {
        long started = System.nanoTime();
        boolean locked = false;
        try {
            // Stop new draws first, then let an in-flight draw leave the owner.
            // syncAndDraw may leave work on HWUI's RenderThread after returning;
            // destroying its context retires that work before SurfaceView tears
            // down the queue. The view, not this renderer, owns the Surface.
            locked = presentationLock.tryLock(250L, TimeUnit.MILLISECONDS);
            if (!locked) {
                Log.w(TAG, "Software canvas detach lock timed out engine=" + entry.id +
                        " secondary=" + secondary);
                return;
            }
            DirectHardwareCanvas canvas = secondary ? secondaryDirectCanvas : primaryDirectCanvas;
            if (canvas != null) canvas.close();
            Log.i(TAG, "Software canvas retired engine=" + entry.id +
                    " secondary=" + secondary +
                    " elapsedUs=" + (System.nanoTime() - started) / 1000L);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            Log.w(TAG, "Software canvas detach interrupted engine=" + entry.id, interrupted);
        } catch (Throwable failure) {
            Log.w(TAG, "Software canvas detach failed engine=" + entry.id, failure);
        } finally {
            if (locked) presentationLock.unlock();
        }
    }

    @Override public void onSecondarySurfaceAvailable(
            Surface next, int width, int height) {
        ++directSecondarySurfaceEpoch;
        secondarySurface = next;
        secondarySurfaceWidth = width;
        secondarySurfaceHeight = height;
        Log.i(TAG, "LucentLowerScreen secondary surface available engine=" + entry.id +
                " system=" + (request == null ? "?" : request.systemId) +
                " valid=" + (next != null && next.isValid()) +
                " size=" + width + "x" + height +
                " secondaryGameplayRequested=" + secondaryGameplayRequested);
        publishLowerSourceCadence();
    }

    /**
     * The lower-panel generator never received the core's cadence (only the
     * upper GameSurfaceView called setAuthoritativeSourceHz), so a static
     * touch-screen crop could sit at presents=0 until a unique endpoint
     * survived an epoch resync (DS lower-display map, 2026-09-03).  Give it
     * the paced or synchronized core clock whenever either changes; the
     * Canvas/direct path draws every frame already and needs nothing.
     */
    private void publishPrimarySourceCadence() {
        GameLaunchRequest launch = request;
        if (launch == null ||
                InWindowGameHost.authoritativeVideoHz(launch.systemId) <= 0.0) return;
        FrameGenerationRenderer generator = FrameGenerationRendererRegistry.find(surface);
        double hz = effectiveVideoHz();
        if (generator != null && hz > 0.0) generator.setAuthoritativeSourceHz(hz);
    }

    private void publishLowerSourceCadence() {
        Surface lower = secondarySurface;
        if (lower == null) return;
        FrameGenerationRenderer generator = FrameGenerationRendererRegistry.find(lower);
        if (generator == null) return;
        double hz = pacedCoreHz > 0.0 ? pacedCoreHz : synchronizedCoreHz;
        if (hz > 0.0) generator.setAuthoritativeSourceHz(hz);
    }

    @Override public void onSecondarySurfaceDestroyed() {
        Log.i(TAG, "LucentLowerScreen secondary surface destroyed engine=" + entry.id +
                " system=" + (request == null ? "?" : request.systemId) +
                " secondaryGameplayRequested=" + secondaryGameplayRequested);
        secondarySurface = null;
        secondarySurfaceWidth = 0;
        secondarySurfaceHeight = 0;
        lowerDrawEvidenceLogged = false;
        retireDetachedCanvas(true);
    }

    @Override public void onSecondarySurfaceError(Throwable failure) {
        secondarySurface = null;
        secondarySurfaceWidth = secondarySurfaceHeight = 0;
        Listener callback = listener;
        if (callback != null) callback.onSessionError(
                "The lower-screen renderer could not release the display. Close and reopen this game.",
                failure);
    }

    @Override public void onSecondaryTouch(
            float normalizedX, float normalizedY, boolean pressed) {
        int width = secondarySurfaceWidth;
        int height = secondarySurfaceHeight;
        dispatchDsPanelTouch(false, normalizedX * width, normalizedY * height,
                width, height, pressed);
    }

    /** Gameplay owns these events even when this panel shows the non-touch screen. */
    @Override public void onPrimaryTouch(MotionEvent event, int width, int height) {
        synchronized (dsTouchLock) {
            int action = event.getActionMasked();
            if (action == MotionEvent.ACTION_DOWN)
                primaryStylusPointerId = event.getPointerId(0);
            if (action == MotionEvent.ACTION_CANCEL || action == MotionEvent.ACTION_UP ||
                    (action == MotionEvent.ACTION_POINTER_UP &&
                     event.getPointerId(event.getActionIndex()) == primaryStylusPointerId)) {
                dispatchDsPanelTouch(true, 0f, 0f, width, height, false);
                primaryStylusPointerId = -1;
            } else if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_MOVE) {
                int index = event.findPointerIndex(primaryStylusPointerId);
                if (index >= 0) dispatchDsPanelTouch(true, event.getX(index), event.getY(index),
                        width, height, true);
            }
        }
    }

    private void dispatchDsPanelTouch(boolean primary, float x, float y,
                                      int width, int height, boolean pressed) {
        synchronized (dsTouchLock) {
            LibretroHost active = host;
            if (!prepared || active == null || request == null ||
                    !isDualScreenSystem(request.systemId) || stopping.get() || released.get()) return;
            boolean splitScreens = hasSecondaryDsSurface();
            if (splitScreens ? !DualScreenLayout.dsPanelIsTouch(primary, dsTouchOnPrimary)
                    : !primary) return;
            // The native touch screen remains the LOWER half of the composite,
            // regardless of which physical panel is displaying it. Remove that
            // panel's 4:3 bars before mapping; outside drags release the stylus.
            DualScreenLayout.TouchPoint point = splitScreens
                    ? DualScreenLayout.dsTouchPoint(x, y, width, height)
                    : DualScreenLayout.dsSideBySideTouchPoint(x, y, width, height);
            active.setPointer(0, DualScreenLayout.pointerCoordinate(point.x),
                    DualScreenLayout.lowerScreenPointerY(point.y),
                    running && pressed && point.inside);
        }
    }

    private void releaseDsTouch() {
        synchronized (dsTouchLock) {
            primaryStylusPointerId = -1;
            LibretroHost active = host;
            if (active != null && request != null && isDualScreenSystem(request.systemId))
                active.setPointer(0, (short) 0, (short) 0, false);
        }
    }

    private boolean hasSecondaryDsSurface() {
        Surface lower = secondarySurface;
        return secondaryGameplayRequested && lower != null && lower.isValid();
    }

    @Override public void resume() {
        if (!prepared || stopping.get() || released.get()) return;
        LibretroHost active = host;
        if (active != null) active.resume();
        // Re-acquires focus this session gave up when it went to the
        // background, or lost permanently to another app while it was there.
        audioFocus.request();
        prepareAudioResume();
        synchronized (runLock) {
            activeTickMillis = SystemClock.elapsedRealtime();
            running = true;
            runLock.notifyAll();
        }
    }

    @Override public void pause(PauseReason reason) {
        synchronized (runLock) { running = false; }
        releaseDsTouch();
        DirectDisplayVsync clock = directDisplayVsync;
        if (clock != null) clock.suspend();
        LibretroHost active = host;
        if (active != null) active.pause();
        AudioTrack audio = audioTrack;
        if (audio != null) try { audio.pause(); }
        catch (Throwable failure) { recordAudioWriteError("pause", failure); }
        // Kept across a Lucent-menu pause: this is still the foreground game.
        // Given back when Android backgrounds it, which is the point another
        // app expects to be able to take it.
        if (reason == PauseReason.ANDROID_BACKGROUND) audioFocus.abandon();
        if (reason == PauseReason.ANDROID_BACKGROUND && prepared && !stopping.get())
            saveQuickResume(false, null);
    }

    private void silenceForAudioFocusLoss() {
        // Nothing here attenuates the track: EmuFusion produces no sound at all
        // while another app owns the output, and presentAudio drops the PCM the
        // core has already produced so nothing queues up behind a paused track.
        AudioTrack audio = audioTrack;
        if (audio != null) try { audio.pause(); }
        catch (Throwable failure) { recordAudioWriteError("focus-pause", failure); }
        PcmAudioQueue queue = audioQueue;
        if (queue != null) recordFocusDroppedSamples(queue.clear());
    }

    private void resumeAfterAudioFocusGain() {
        // Only if the session was actually running. Focus can come back while
        // the game sits paused in the Lucent menu, and restarting the track
        // there would play over a menu the player is still reading.
        if (running) prepareAudioResume();
    }

    private void prepareAudioResume() {
        AudioTrack audio = audioTrack;
        if (audio == null || !audioStartedOnce) return;
        try {
            if (audio.getPlayState() == AudioTrack.PLAYSTATE_PLAYING) return;
            // Keep the paused PCM. Refill the existing startup capacity before
            // restarting the sink; display/core wake-up can outlast the small
            // steady buffer. presentAudio starts playback only after a full
            // nonblocking write reports no remaining room.
            if (Build.VERSION.SDK_INT >= 24)
                audio.setBufferSizeInFrames(startupAudioBufferBytes(audio.getSampleRate()) / 4);
            steadyAudioBufferApplied = false;
            audioStartedAtMillis = 0L;
        } catch (Throwable failure) {
            recordAudioWriteError("resume-buffer-resize", failure);
        }
    }

    @Override public void quiesceForExit() {
        // Pausing only records the request in LibretroHost, so wait (bounded)
        // for any frame already in progress to leave the core. The
        // independent Canvas/FG submitter must also finish before its Surface
        // is detached. Pausing closes the render gate; this bounded barrier
        // drains a draw that had already passed it. On failure, the host keeps
        // the Surface attached through checkpoint/release instead of racing it.
        pause(PauseReason.LUCENT_MENU);
        try {
            LibretroHost active = host;
            if (active != null && !active.awaitFrameBoundary(250L))
                throw new IllegalStateException("Core frame still running at exit");
            if (!presentationLock.tryLock(250L, TimeUnit.MILLISECONDS))
                throw new IllegalStateException("Software renderer still owns the exit Surface");
            try {
                closeDirectCanvases();
            } finally { presentationLock.unlock(); }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Interrupted while awaiting software render exit", interrupted);
        }
    }

    @Override public boolean quiesceForPresentationRecovery() {
        if (!prepared || stopping.get() || released.get()) return false;
        pause(PauseReason.LUCENT_MENU);
        try {
            if (!presentationLock.tryLock(250L, java.util.concurrent.TimeUnit.MILLISECONDS))
                return false;
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return false;
        }
        try {
            surface = null;
            closeDirectCanvases();
            // Thor's custom HardwareRenderer can report successful draws but
            // post black after an EGL FG producer relinquishes this Surface.
            // The same recovered crop renders through Surface hardware Canvas.
            // Limit this compatibility fallback to the recovered primary; fresh
            // Off sessions and the lower panel retain source-vsync submission.
            primaryRecoverySurfaceCanvas = true;
            return true;
        } finally { presentationLock.unlock(); }
    }

    @Override public boolean openControls() {
        if (!(context instanceof Activity) || inputRouter == null) return false;
        if (secondaryGameplayRequested) {
            ((Activity) context).runOnUiThread(() -> new AlertDialog.Builder(context)
                    .setTitle("Controls")
                    .setItems(new String[] { "Button mapping", "DS screen order" }, (dialog, which) -> {
                        if (which == 0) openButtonControls();
                        else showDsScreenOrder();
                    })
                    .setNegativeButton("Done", null).show());
            return true;
        }
        return openButtonControls();
    }

    private boolean openButtonControls() {
        GamepadDescriptor pad = inputRouter.activeDevice();
        if (pad == null) {
            ((Activity) context).runOnUiThread(() -> new AlertDialog.Builder(context)
                    .setTitle("Controls")
                    .setMessage("No physical controller is connected. EmuFusion will use touch controls when available.")
                    .setPositiveButton("Done", null).show());
            return true;
        }
        ((Activity) context).runOnUiThread(() -> showControlsMenu(pad));
        return true;
    }

    private void showDsScreenOrder() {
        android.content.SharedPreferences settings = appContext.getSharedPreferences(
                "ds-screen-order-v1", Context.MODE_PRIVATE);
        boolean selected = settings.getBoolean(dsLayoutPreferenceKey, DEFAULT_DS_TOUCH_ON_PRIMARY);
        new AlertDialog.Builder(context)
                .setTitle("DS touch screen — this game")
                .setSingleChoiceItems(new String[] { "Bottom panel (original order)", "Top panel" },
                        selected ? 1 : 0, (dialog, which) -> {
                            if (!prepared || running || stopping.get() || released.get()) return;
                            boolean next = which == 1;
                            settings.edit().putBoolean(dsLayoutPreferenceKey, next).apply();
                            dialog.dismiss();
                            if (request.frameGenerationMode == FrameGenerationSettings.Mode.OFF) {
                                synchronized (dsTouchLock) {
                                    releaseDsTouch();
                                    dsTouchOnPrimary = next;
                                }
                                Log.i(TAG, "DS screen order changed touchOnPrimary=" + next);
                            } else {
                                // Fresh renderers on relaunch cannot form a pair across
                                // unrelated top/touch images retained by a live generator.
                                new AlertDialog.Builder(context).setTitle("Screen order saved")
                                        .setMessage("With frame generation enabled, the new order applies the next time you open this game.")
                                        .setPositiveButton("OK", null).show();
                            }
                        })
                .setNegativeButton("Cancel", null).show();
    }

    @Override public boolean openRestoreHistory() {
        if (!(context instanceof Activity) || vault == null || identity == null) return false;
        final List<StateSnapshot> history = restorableHistory();
        if (history.isEmpty()) return false;
        final String[] labels = new String[history.size()];
        DateFormat formatter = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT);
        for (int i = 0; i < history.size(); i++) {
            StateSnapshot snapshot = history.get(i);
            labels[i] = formatter.format(new Date(snapshot.metadata.createdAtMillis)) +
                    "  •  " + formatPlayTime(snapshot.metadata.activePlayMillis);
        }
        ((Activity) context).runOnUiThread(() -> new AlertDialog.Builder(context)
                .setTitle("Restore earlier point")
                .setItems(labels, (dialog, which) -> restore(history.get(which)))
                .setNegativeButton("Cancel", null)
                .show());
        return true;
    }

    /**
     * Power-cycles the loaded content in place through libretro's own
     * retro_reset, now that the native host exposes it.
     *
     * Battery save RAM is written out first but deliberately not written back:
     * retro_reset is the console's reset button, and a console reset leaves
     * the cartridge's battery memory exactly as the game left it. Pushing the
     * last persisted copy back over the core's live SRAM would silently roll
     * play back to whenever that copy was taken. The persist before the reset
     * is only insurance — the on-disk battery file stays current if the
     * process dies before the next checkpoint.
     *
     * The call holds the host monitor. LibretroHost's own methods are
     * synchronized on that same object, so a frame already in flight completes
     * before the reset and no frame observes a half-reset core.
     *
     * If the core has no usable retro_reset the old unload/reload power cycle
     * still runs, rather than leaving the game wedged. That path does destroy
     * core memory, so it keeps the save-RAM restore and the port-device
     * reattach that loading a game requires.
     */
    @Override public boolean reset() {
        GameLaunchRequest launch = request;
        LibretroHost active = host;
        if (!prepared || launch == null || active == null ||
                stopping.get() || released.get()) return false;
        synchronized (lifecycleSubmissionLock) {
            if (released.get() || lifecycle.isShutdown()) return false;
            try {
                lifecycle.execute(() -> {
                    LibretroHost open = host;
                    if (open == null || stopping.get() || released.get()) return;
                    try {
                        synchronized (open) {
                            persistSaveRam(open);
                            open.reset();
                        }
                        flushAudioAfterRestore();
                        Log.i(TAG, "Reset applied engine=" + entry.id +
                                " system=" + launch.systemId + " marker=reset");
                    } catch (Throwable failure) {
                        Log.w(TAG, "Native reset rejected; reloading content " +
                                "engine=" + entry.id + " system=" +
                                launch.systemId, failure);
                        reloadAsReset(open, launch, failure);
                    }
                });
            } catch (java.util.concurrent.RejectedExecutionException rejected) {
                return false;
            }
        }
        return true;
    }

    /** Unload/reload power cycle used only when retro_reset is unavailable. */
    private void reloadAsReset(LibretroHost open, GameLaunchRequest launch,
                               Throwable resetFailure) {
        try {
            File game = resolveGameFile(launch.contentUri);
            synchronized (open) {
                // A core carrying EmuFusion's exit-persistence extension may
                // refuse the unload; it then throws and the game keeps
                // running untouched.
                persistSaveRam(open);
                open.unloadGame();
                open.loadGame(game);
                // Loading put port 0 back to a plain RetroPad, so a system
                // with a different controller has to reattach it or the
                // reset game takes no input.
                int portDevice = LibretroJoypadLayout
                        .portDeviceFor(launch.systemId);
                if (portDevice != LibretroJoypadLayout.RETRO_DEVICE_JOYPAD)
                    open.setControllerPortDevice(0, portDevice);
                // Unloading destroyed the core's SRAM, so unlike the
                // retro_reset path this one must put it back.
                if (saveRamFile != null) restoreSaveRam(open, saveRamFile);
            }
            flushAudioAfterRestore();
            Log.i(TAG, "Reset applied engine=" + entry.id +
                    " system=" + launch.systemId + " marker=reset");
        } catch (Throwable failure) {
            Log.w(TAG, "Reset rejected engine=" + entry.id +
                    " system=" + launch.systemId +
                    " nativeReset=" + (resetFailure == null ? "none" :
                            String.valueOf(resetFailure.getMessage())) +
                    " marker=reset-failure", failure);
        }
    }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if (!prepared || inputRouter == null || event == null ||
                (event.getAction() != KeyEvent.ACTION_DOWN &&
                 event.getAction() != KeyEvent.ACTION_UP)) return false;
        if (event.getAction() == KeyEvent.ACTION_DOWN &&
                event.getRepeatCount() != 0) return true;
        GamepadDescriptor device = device(event.getDeviceId());
        if (device == null) {
            refreshDevices();
            device = device(event.getDeviceId());
        }
        if (device == null) return false;
        try {
            InputSignal signal = InputSignal.key(event.getKeyCode());
            CanonicalControl control = inputRouter.resolve(device, signal);
            int retroId = joypadId(control);
            LibretroHost active = host;
            if (retroId < 0 || active == null) return false;
            if (control == CanonicalControl.START) {
                Log.i(TAG, "Controller Start edge engine=" + entry.id +
                        " system=" + request.systemId +
                        " action=" + event.getAction() +
                        " repeat=" + event.getRepeatCount() +
                        " deviceId=" + event.getDeviceId());
            }
            joypad.apply(signal, retroId,
                    event.getAction() != KeyEvent.ACTION_UP, joypadSink);
            if (!qualificationInputLogged && event.getAction() == KeyEvent.ACTION_DOWN) {
                qualificationInputLogged = true;
                restartQualificationPacingWindow();
                Log.i(TAG, "Input consumed engine=" + entry.id +
                        " system=" + request.systemId + " control=" + control.name());
            }
            return true;
        } catch (Exception ignored) { return false; }
    }

    @Override public boolean dispatchGenericMotionEvent(MotionEvent event) {
        if (!prepared || inputRouter == null || event == null ||
                event.getAction() != MotionEvent.ACTION_MOVE) return false;
        GamepadDescriptor device = device(event.getDeviceId());
        if (device == null) {
            refreshDevices();
            device = device(event.getDeviceId());
        }
        if (device == null) return false;
        boolean consumed = false;
        LibretroHost active = host;
        if (active != null) {
            consumed |= dispatchAnalogStick(event, active, MotionEvent.AXIS_X,
                    MotionEvent.AXIS_Y, 0);
            // Android gamepads normally report the right stick as Z/RZ. RX/RY
            // is the established fallback; do not send both because an idle
            // duplicate pair would overwrite the active pair with zero.
            if (device.axes.contains(MotionEvent.AXIS_Z) &&
                    device.axes.contains(MotionEvent.AXIS_RZ)) {
                consumed |= dispatchAnalogStick(event, active, MotionEvent.AXIS_Z,
                        MotionEvent.AXIS_RZ, 1);
            } else {
                consumed |= dispatchAnalogStick(event, active, MotionEvent.AXIS_RX,
                        MotionEvent.AXIS_RY, 1);
            }
        }
        for (int axis : device.axes) {
            float value = event.getAxisValue(axis);
            consumed |= dispatchAxis(device, axis, -1, value <= -AXIS_PRESS);
            consumed |= dispatchAxis(device, axis, 1, value >= AXIS_PRESS);
        }
        return consumed;
    }

    private boolean dispatchAnalogStick(MotionEvent event, LibretroHost active,
                                        int xAxis, int yAxis, int retroIndex) {
        InputDevice inputDevice = event.getDevice();
        if (inputDevice == null ||
                inputDevice.getMotionRange(xAxis, event.getSource()) == null ||
                inputDevice.getMotionRange(yAxis, event.getSource()) == null) return false;
        active.setAnalogAxis(0, retroIndex, 0, normalizedAxis(event, xAxis));
        active.setAnalogAxis(0, retroIndex, 1, normalizedAxis(event, yAxis));
        return true;
    }

    private static float normalizedAxis(MotionEvent event, int axis) {
        float value = event.getAxisValue(axis);
        InputDevice device = event.getDevice();
        InputDevice.MotionRange range = device == null ? null
                : device.getMotionRange(axis, event.getSource());
        float flat = range == null ? 0.08f : Math.max(0f, range.getFlat());
        float magnitude = Math.abs(value);
        if (magnitude <= flat) return 0f;
        float extent = range == null ? 1f
                : value < 0f ? Math.abs(range.getMin()) : Math.abs(range.getMax());
        float normalized = (magnitude - flat) / Math.max(0.0001f, extent - flat);
        normalized = Math.max(0f, Math.min(1f, normalized));
        return Math.copySign(normalized, value);
    }

    @Override public boolean shouldShowOnScreenControls() {
        return inputRouter != null && inputRouter.shouldShowOnScreenControls();
    }

    @Override public boolean dispatchVirtualControl(CanonicalControl control, boolean pressed) {
        LibretroHost active = host;
        int id = joypadId(control);
        if (!prepared || active == null || id < 0 ||
                (pressed && !shouldShowOnScreenControls())) return false;
        joypad.apply(control, id, pressed, joypadSink);
        return true;
    }

    @Override public void stop(StopReason reason, Completion completion) {
        if (completion == null) throw new IllegalArgumentException("completion required");
        synchronized (lifecycleSubmissionLock) {
            if (released.get()) {
                releaseWhenComplete(completion);
                return;
            }
            if (stopCompleted) {
                completion.complete();
                return;
            }
            stopCompletions.add(completion);
            if (reason == StopReason.ACTIVITY_DESTROYED) destroyStopRequested = true;
            if (!stopping.compareAndSet(false, true)) return;
            synchronized (runLock) { running = false; }
            LibretroHost active = host;
            if (active != null) active.pause();
            if ("scummvm".equals(entry.id)) {
                saveScummvmExit(this::completeStop);
                return;
            }
            saveQuickResume(true, this::completeStop);
        }
    }

    private void completeStop() {
        List<Completion> callbacks;
        synchronized (lifecycleSubmissionLock) {
            if (stopCompleted) return;
            stopCompleted = true;
            callbacks = new ArrayList<>(stopCompletions);
            stopCompletions.clear();
        }
        for (Completion callback : callbacks) {
            try { callback.complete(); }
            catch (Throwable failure) { Log.e(TAG, "Stop completion callback failed", failure); }
        }
    }

    private void saveScummvmExit(Completion completion) {
        synchronized (lifecycleSubmissionLock) {
            if (released.get() || lifecycle.isShutdown()) return;
            try {
                lifecycle.execute(() -> {
                    try {
                        LibretroHost active = host;
                        if (active == null)
                            throw new IllegalStateException("ScummVM host is unavailable");
                        active.unloadGame();
                        prepared = false;
                        completion.complete();
                    } catch (Throwable failure) {
                        rejectScummvmStop(failure);
                    }
                });
            } catch (java.util.concurrent.RejectedExecutionException rejected) {
                rejectScummvmStop(rejected);
            }
        }
    }

    private void rejectScummvmStop(Throwable failure) {
        synchronized (lifecycleSubmissionLock) {
            if (destroyStopRequested || released.get()) {
                // A destroyed Activity cannot retain playable ownership. Let
                // its release run, but do not misreport the unsuccessful save.
                Log.w(TAG, "ScummVM destroy-time save failed marker=save-failure", failure);
                completeStop();
                return;
            }
            stopCompletions.clear();
            stopping.set(false);
            LibretroHost active = host;
            if (active != null) try { active.resume(); }
            catch (Throwable ignored) {}
            synchronized (runLock) {
                running = true;
                runLock.notifyAll();
            }
        }
        Listener callback = listener;
        if (callback != null) callback.onSessionStopRejected(
                "ScummVM could not save at this point. The game is still running; " +
                        "try held-Stop again after returning to gameplay.", failure);
    }

    @Override public void release() {
        releaseWhenComplete(() -> {});
    }

    /** Acknowledges only after every owned worker and the native host finish. */
    public void releaseWhenComplete(Completion completion) {
        if (completion == null) throw new IllegalArgumentException("completion required");
        synchronized (lifecycleSubmissionLock) {
            if (releaseCompleted) {
                completion.complete();
                return;
            }
            releaseCompletions.add(completion);
            if (!released.compareAndSet(false, true)) return;
            synchronized (runLock) {
                running = false;
                runLock.notifyAll();
            }
            // Queue behind preparation and every accepted serialization task.
            // Preparation may still create its threads, vault or host; sampling
            // those owners before reaching this queue barrier misses them.
            lifecycle.execute(this::completeRelease);
            lifecycle.shutdown();
        }
        try { audioFocus.abandon(); }
        catch (Throwable failure) { Log.e(TAG, "Release audio focus failed", failure); }
    }

    private void completeRelease() {
        boolean interrupted = false;
        try {
            prepared = false;
            // Also abandon after an in-flight prepare, which may have acquired
            // focus after releaseWhenComplete made its early best-effort call.
            try { audioFocus.abandon(); }
            catch (Throwable failure) { Log.e(TAG, "Release audio focus failed", failure); }
            Thread frames = frameThread;
            Thread renderer = renderThread;
            DirectDisplayVsync clock = directDisplayVsync;
            if (clock != null) clock.close();
            directDisplayVsync = null;
            if (frames != null) frames.interrupt();
            if (renderer != null) renderer.interrupt();
            videoMailbox.close(LibretroHost.VideoFrame::release);
            interrupted |= joinReleaseThread(frames);
            interrupted |= joinReleaseThread(renderer);
            closeDirectCanvases();
            SecondaryGameplaySurfaceRouter.release(appContext, this);
            secondaryGameplayRequested = false;
            secondarySurface = null;
            StateVaultWorker worker = vaultWorker;
            if (worker != null) {
                worker.close();
                boolean warned = false;
                for (;;) {
                    try {
                        if (worker.awaitTermination(10L, TimeUnit.SECONDS)) break;
                        if (!warned) {
                            Log.w(TAG, "Still awaiting queued save writes before release");
                            warned = true;
                        }
                    } catch (InterruptedException waitInterrupted) {
                        interrupted = true;
                    }
                }
            }
            AudioTrack audio = audioTrack;
            audioTrack = null;
            if (audio != null) {
                try { audio.stop(); } catch (IllegalStateException ignored) {}
                AppVolumeController.unregisterTrack(audio);
                audio.release();
            }
            LibretroHost active = host;
            if (active != null) active.close();
            host = null;
            List<Completion> callbacks;
            synchronized (lifecycleSubmissionLock) {
                releaseCompleted = true;
                callbacks = new ArrayList<>(releaseCompletions);
                releaseCompletions.clear();
            }
            Log.i(TAG, "Software libretro release acknowledged after worker/native close engine=" + entry.id);
            for (Completion callback : callbacks) {
                try { callback.complete(); }
                catch (Throwable failure) { Log.e(TAG, "Release completion callback failed", failure); }
            }
        } catch (Throwable failure) {
            // Retain the host and callbacks on failure: the frontend must not
            // terminate Qt or launch another emulator over unclosed ownership.
            Log.e(TAG, "Software libretro release not acknowledged", failure);
        } finally {
            if (interrupted) Thread.currentThread().interrupt();
        }
    }

    private static boolean joinReleaseThread(Thread owner) {
        if (owner == null) return false;
        if (owner == Thread.currentThread())
            throw new IllegalStateException("Cannot acknowledge own live worker");
        boolean interrupted = false;
        while (owner.isAlive()) {
            try { owner.join(); }
            catch (InterruptedException waitInterrupted) { interrupted = true; }
        }
        return interrupted;
    }

    private void startFrameThread() {
        try { directDisplayVsync = new DirectDisplayVsync(context); }
        catch (RuntimeException unavailable) {
            Log.w(TAG, "Display tick source unavailable; retaining absolute core clock", unavailable);
        }
        Thread thread = new Thread(() -> {
            AbsoluteFramePacer pacer = new AbsoluteFramePacer(framePeriodNs);
            boolean resetPacer = true;
            int slowFrameEvidenceCount = 0;
            while (!released.get()) {
                synchronized (runLock) {
                    while (!running && !released.get()) {
                        resetPacer = true;
                        DirectDisplayVsync clock = directDisplayVsync;
                        if (clock != null) clock.suspend();
                        try { runLock.wait(); }
                        catch (InterruptedException interrupted) {
                            if (released.get()) return;
                        }
                    }
                }
                if (released.get()) return;
                updatePhysicalFgClock();
                if (pacer.periodNanos() != framePeriodNs) {
                    // A small oscillator trim changes future spacing, not the
                    // timestamp already scheduled. Reanchoring to thread wake
                    // time injected an unrelated PTS jump on every refinement.
                    if (physicalFgClockApplied && !resetPacer && Math.abs((double) framePeriodNs /
                            pacer.periodNanos() - 1.0) <= 0.0005) {
                        pacer = pacer.withPeriodPreservingDeadline(framePeriodNs);
                    } else {
                        pacer = new AbsoluteFramePacer(framePeriodNs);
                        resetPacer = true;
                    }
                }
                if (resetPacer) {
                    pacer.reset(System.nanoTime());
                    resetPacer = false;
                }
                DirectDisplayVsync displayClock = directDisplayVsync;
                long displayDueNs = 0;
                if (displayClock != null) {
                    Surface currentSurface = surface;
                    boolean direct = running && currentSurface != null &&
                            currentSurface.isValid() && netplayRelay == null &&
                            FrameGenerationRendererRegistry.find(currentSurface) == null;
                    displayClock.configure(declaredVideoHz,
                            1_000_000_000.0 / framePeriodNs, direct);
                    try { displayDueNs = displayClock.awaitDueTimeNs(); }
                    catch (InterruptedException interrupted) {
                        if (released.get()) return;
                    }
                }
                if (!running || released.get()) continue;
                LibretroHost.VideoFrame newest = null;
                long evidenceDueNs = displayDueNs != 0 ? displayDueNs : pacer.deadlineNanos();
                long evidenceStartNs = System.nanoTime();
                long evidenceCoreStartNs = 0L, evidenceCoreEndNs = 0L;
                long evidenceVideoEndNs = 0L, evidenceAudioEndNs = 0L;
                long evidenceCheckpointStartNs = 0L;
                try {
                    LibretroHost active = host;
                    if (active != null) {
                        updateDisplayAudioClock(active, displayClock, displayDueNs != 0);
                        // The frame about to run is due at the pacer's current
                        // absolute deadline; that exact lattice instant is its
                        // producer timestamp (see VideoFrame.producerTimestampNs).
                        long scheduledNs = displayDueNs != 0
                                ? displayDueNs : pacer.deadlineNanos();
                        long workStartNs = System.nanoTime();
                        evidenceCoreStartNs = workStartNs;
                        active.runFrame();
                        evidenceCoreEndNs = System.nanoTime();
                        recordFrameWork(workStartNs, evidenceCoreEndNs);
                        // Canvas submission and bitmap conversion can take several
                        // milliseconds on handheld displays. Keep them entirely off
                        // the emulation/audio clock. If rendering falls behind, skip
                        // an obsolete visual frame instead of slowing the game.
                        newest = active.latestVideoFrame();
                        if (newest != null) newest.producerTimestampNs = scheduledNs;
                        evidenceVideoEndNs = System.nanoTime();
                        // Drain on every core frame, even while AudioTrack still
                        // owns a partial prior block. Otherwise the native ring
                        // can overwrite its oldest samples without Java ever
                        // observing or reporting the loss.
                        drainAndPresentAudio(active);
                        evidenceAudioEndNs = System.nanoTime();
                        recordQualificationPacing();
                    }
                    evidenceCheckpointStartNs = System.nanoTime();
                    long now = SystemClock.elapsedRealtime();
                    long elapsed = activeTickMillis == 0L ? 0L : Math.max(0L, now - activeTickMillis);
                    activeTickMillis = now;
                    if (checkpointScheduler != null &&
                            checkpointScheduler.advanceActivePlay(elapsed) > 0)
                        saveAutomatic();
                } catch (Throwable failure) {
                    running = false;
                    Listener callback = listener;
                    if (callback != null) callback.onSessionError(
                            "The internal engine stopped unexpectedly.", failure);
                }
                if (displayDueNs != 0) pacer.reset(System.nanoTime());
                long evidenceEndNs = System.nanoTime();
                long pacingDelay = pacer.delayAfterFrame(evidenceEndNs);
                boolean coalescing = displayDueNs != 0
                        ? displayClock.coalescingCatchUpPresentation()
                        : pacer.coalescingCatchUpPresentation();
                directVideoTelemetry.recordSourceDecision(newest != null, coalescing,
                        displayDueNs != 0 && !coalescing && displayClock.hasNewerDueFrame());
                if (newest != null && !coalescing) {
                    // The mailbox reports replacement in the same monitor that
                    // performs the write. The former isEmpty()+offer pair raced
                    // the render consumer and made telemetry contradict itself.
                    LatestValueMailbox.OfferResult result =
                            videoMailbox.offerLatest(
                                    newest, LibretroHost.VideoFrame::release);
                    if (result != LatestValueMailbox.OfferResult.REJECTED) {
                        directVideoTelemetry.recordMailboxOffer(
                                result == LatestValueMailbox.OfferResult.REPLACED);
                    } else newest.release();
                } else if (newest != null) newest.release();
                // Failure-only, bounded evidence. Stage durations are wall time:
                // descheduling inside a stage is not proof of expensive CPU work.
                // Emit after mailbox publication, never before the frame's work.
                if (slowFrameEvidenceCount < 16 && evidenceCoreEndNs > 0L &&
                        evidenceEndNs - evidenceDueNs >= 2L * framePeriodNs) {
                    ++slowFrameEvidenceCount;
                    Log.w(TAG, "Frame loop lateness engine=" + entry.id +
                            " dueNs=" + evidenceDueNs + " startNs=" + evidenceStartNs +
                            " coreStartNs=" + evidenceCoreStartNs +
                            " coreEndNs=" + evidenceCoreEndNs +
                            " videoEndNs=" + evidenceVideoEndNs +
                            " audioEndNs=" + evidenceAudioEndNs +
                            " checkpointStartNs=" + evidenceCheckpointStartNs +
                            " endNs=" + evidenceEndNs + " periodNs=" + framePeriodNs +
                            " coalesced=" + coalescing + " displayClock=" + (displayDueNs != 0));
                }
                if (displayDueNs == 0) sleepUntilNextFrame(pacingDelay);
            }
        }, "lucent-libretro-frames");
        thread.setDaemon(true);
        frameThread = thread;
        thread.start();
    }

    private void updatePhysicalFgClock() {
        FrameGenerationRenderer renderer = netplayRelay == null
                ? FrameGenerationRendererRegistry.find(surface) : null;
        double target = renderer == null ? 0.0 : DisplaySyncPolicy.physicalSourceHz(
                declaredVideoHz, renderer.physicalPanelHz());
        if (target > 0.0) {
            if (setPacedVideoHz(target)) {
                physicalFgClockApplied = true;
                physicalFgClockOwner = renderer;
                physicalFgClockDeclaration = declaredVideoHz;
            }
        } else if (physicalFgClockApplied &&
                (renderer == null || renderer != physicalFgClockOwner ||
                        Double.compare(declaredVideoHz, physicalFgClockDeclaration) != 0) &&
                setPacedVideoHz(0.0)) {
            physicalFgClockApplied = false;
            physicalFgClockOwner = null;
            physicalFgClockDeclaration = 0.0;
        }
        // Zero from the same renderer means its short-lived measurement is
        // unavailable, not that the panel oscillator became exactly 60 Hz.
        // Restoring nominal here during priming resets the endpoint epoch and
        // destroys the very physical-clock evidence needed to finish priming.
        // A fresh valid measurement still adjusts the clock above; replacing
        // the renderer, disabling its route, or changing the core declaration
        // releases this retained trim instead of inheriting it into a session.
    }

    private void updateDisplayAudioClock(LibretroHost active,
            DirectDisplayVsync clock, boolean displayDriven) {
        double nominalHz = 1_000_000_000.0 / framePeriodNs;
        double measuredHz = displayDriven ? clock.measuredSourceHz() : nominalHz;
        long now = System.nanoTime();
        boolean changedPath = displayClockWasActive != displayDriven;
        if (displayAudioClockHz == 0) displayAudioClockHz = nominalHz;
        if (DisplaySyncPolicy.permitsCoreClockCorrection(declaredVideoHz, measuredHz) &&
                (changedPath || now - displayAudioClockUpdatedNs >= 2_000_000_000L) &&
                Math.abs(measuredHz - displayAudioClockHz) > 0.001) {
            active.setSynchronizedVideoRate(declaredVideoHz, measuredHz);
            displayAudioClockHz = measuredHz;
            displayAudioClockUpdatedNs = now;
        }
        if (changedPath) {
            Log.i(TAG, "Direct display tick clock active=" + displayDriven +
                    " engine=" + entry.id + " measuredHz=" + measuredHz +
                    " audioClockHz=" + displayAudioClockHz);
            displayClockWasActive = displayDriven;
        }
    }

    private void startRenderThread() {
        Thread thread = new Thread(() -> {
            while (!released.get()) {
                try {
                    LibretroHost.VideoFrame frame = videoMailbox.take();
                    if (frame == null) return;
                    try {
                        presentVideoWithSurfaceLock(frame);
                    } finally {
                        frame.release();
                    }
                } catch (InterruptedException interrupted) {
                    if (released.get()) return;
                } catch (Throwable ignored) {
                    directVideoTelemetry.recordPresentation(false);
                    // A lost or replaced Surface may drop one visual frame. The
                    // core and audio clocks continue and the next frame retries.
                }
            }
        }, "lucent-libretro-render");
        thread.setDaemon(true);
        renderThread = thread;
        thread.start();
    }

    private static void sleepUntilNextFrame(long remainingNanos) {
        long deadline = System.nanoTime() + remainingNanos;
        while (remainingNanos > 0L) {
            try {
                Thread.sleep(remainingNanos / 1_000_000L,
                        (int) (remainingNanos % 1_000_000L));
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                return;
            }
            remainingNanos = deadline - System.nanoTime();
        }
    }

    private synchronized void restartQualificationPacingWindow() {
        qualificationFrameCount = 0L;
        qualificationStartedNanos = 0L;
        qualificationAudioSamplesAtWindowStart = qualificationAudioSamplesWritten;
        captureDirectVideoTelemetryBaseline();
        captureAudioTelemetryBaseline();
        PcmSignalTelemetry signal = audioSignalTelemetry;
        if (signal != null) signal.resetWindow();
    }

    private synchronized void recordQualificationPacing() {
        long now = System.nanoTime();
        ++qualificationFrameCount;
        if (qualificationFrameCount == QUALIFICATION_WARMUP_FRAMES) {
            qualificationStartedNanos = now;
            qualificationAudioSamplesAtWindowStart = qualificationAudioSamplesWritten;
            captureDirectVideoTelemetryBaseline();
            captureAudioTelemetryBaseline();
            PcmSignalTelemetry signal = audioSignalTelemetry;
            if (signal != null) signal.resetWindow();
            return;
        }
        if (qualificationFrameCount <
                QUALIFICATION_WARMUP_FRAMES + QUALIFICATION_MEASURED_FRAMES) return;
        long elapsed = Math.max(1L, now - qualificationStartedNanos);
        double measuredFps = QUALIFICATION_MEASURED_FRAMES *
                1_000_000_000.0 / elapsed;
        double targetFps = 1_000_000_000.0 / framePeriodNs;
        long measuredAudioFrames = Math.max(0L,
                qualificationAudioSamplesWritten - qualificationAudioSamplesAtWindowStart) / 2L;
        // The playback head only advances when the mixer consumes PCM, so it
        // separates "samples written to a stalled track" from audible output.
        // Frames-written alone has already produced a false audio PASS.
        int audioHead = 0;
        AudioTrack audio = audioTrack;
        if (audio != null)
            try { audioHead = audio.getPlaybackHeadPosition(); }
            catch (IllegalStateException ignored) {}
        AudioTelemetry telemetry = measuredAudioTelemetry();
        DirectVideoTelemetry.Snapshot videoTelemetry =
                directVideoTelemetry.snapshotAndReset();
        long mailboxOffers = videoTelemetry.mailboxOffers;
        long mailboxBusyDrops = videoTelemetry.mailboxBusyDrops;
        long presentAttempts = videoTelemetry.presentAttempts;
        long presentSuccesses = videoTelemetry.presentSuccesses;
        long presentFailures = videoTelemetry.presentFailures;
        LibretroHost activeHost = host;
        long videoBufferAllocations = activeHost == null ? 0L :
                activeHost.videoBufferAllocationCount();
        long videoPoolExhaustions = activeHost == null ? 0L :
                activeHost.videoPoolExhaustionCount();
        PcmAudioQueue queue = audioQueue;
        long queuedFrames = queue == null ? 0L : queue.queuedSamples() / 2L;
        Log.i(TAG, String.format(Locale.ROOT,
                "Runtime telemetry engine=%s system=%s frames=%d elapsedMs=%d " +
                "measuredFps=%.3f targetFps=%.3f audioFrames=%d audioStarted=%s " +
                "audioHead=%d audioProducedFrames=%d audioWrittenFrames=%d " +
                "audioDroppedFrames=%d audioFocusDroppedFrames=%d audioQueuedFrames=%d " +
                "audioPartialWrites=%d audioZeroWrites=%d audioWriteErrors=%d " +
                "audioNativeDrainBoundHits=%d audioUnderruns=%d " +
                "directMailboxOffers=%d directMailboxBusyDrops=%d " +
                "directPresentAttempts=%d directPresentSuccesses=%d " +
                "directPresentFailures=%d directPresentFps=%.3f " +
                "videoBufferAllocations=%d videoPoolExhaustions=%d " +
                "sourceNoVideo=%d sourceCoalesced=%d sourceBriefOverruns=%d",
                entry.id, request.systemId, QUALIFICATION_MEASURED_FRAMES,
                elapsed / 1_000_000L, measuredFps, targetFps,
                measuredAudioFrames, audioStartedOnce, audioHead,
                telemetry.producedSamples / 2L, measuredAudioFrames,
                telemetry.droppedSamples / 2L, telemetry.focusDroppedSamples / 2L,
                queuedFrames, telemetry.partialWrites, telemetry.zeroWrites,
                telemetry.writeErrors, telemetry.nativeDrainBoundHits,
                telemetry.underruns, mailboxOffers, mailboxBusyDrops,
                presentAttempts, presentSuccesses, presentFailures,
                presentSuccesses * 1_000_000_000.0 / elapsed,
                videoBufferAllocations, videoPoolExhaustions,
                videoTelemetry.sourceNoVideo, videoTelemetry.sourceCoalesced,
                videoTelemetry.sourceBriefOverruns));
        logPcmSignalTelemetry();
        if (!audioSilenceWarned && (!audioStartedOnce || audioHead == 0)) {
            audioSilenceWarned = true;
            Log.w(TAG, "Audio silent after measurement window engine=" + entry.id +
                    " trackPresent=" + (audio != null) +
                    " started=" + audioStartedOnce +
                    " primed=" + primedAudioSamples +
                    " primeTarget=" + audioPrimeSamplesTarget +
                    " head=" + audioHead);
        }
        // Keep emitting non-overlapping rolling windows. The physical gate may
        // reject a transiently interrupted first sample and require a later
        // sustained window without hiding persistently slow emulation.
        qualificationFrameCount = QUALIFICATION_WARMUP_FRAMES;
        qualificationStartedNanos = now;
        qualificationAudioSamplesAtWindowStart = qualificationAudioSamplesWritten;
        // snapshotAndReset() above atomically opened the next video window.
        // Resetting again here would erase a render completion that raced the
        // intervening log/audio work.
        captureAudioTelemetryBaseline();
    }

    private void captureDirectVideoTelemetryBaseline() {
        directVideoTelemetry.resetWindow();
    }

    private void logPcmSignalTelemetry() {
        PcmSignalTelemetry signal = audioSignalTelemetry;
        if (signal == null) {
            Log.w(TAG, "PCM signal telemetry unavailable engine=" + entry.id +
                    " system=" + request.systemId +
                    " boundary=pre-AudioTrack audibilityProven=false " +
                    "marker=audio-pcm-signal-unavailable");
            return;
        }
        PcmSignalTelemetry.Snapshot window = signal.snapshotWindowAndReset();
        PcmSignalTelemetry.Snapshot total = signal.snapshotCumulative();
        Log.i(TAG, String.format(Locale.ROOT,
                "PCM signal telemetry engine=%s system=%s " +
                "audioSignalBoundary=pre-AudioTrack audioSignalAudibilityProven=false " +
                "audioSignalSampleRateHz=%d " +
                "audioSignalWindowFrames=%d audioSignalWindowSamples=%d " +
                "audioSignalWindowFrequencyResolutionHz=%.6f " +
                "audioSignalWindowOverflow=%s " +
                "audioSignalWindowLeftMin=%d audioSignalWindowLeftMax=%d " +
                "audioSignalWindowLeftPeak=%d audioSignalWindowLeftRms=%.3f " +
                "audioSignalWindowLeftToneHz=%.3f audioSignalWindowLeftCrossings=%d " +
                "audioSignalWindowRightMin=%d audioSignalWindowRightMax=%d " +
                "audioSignalWindowRightPeak=%d audioSignalWindowRightRms=%.3f " +
                "audioSignalWindowRightToneHz=%.3f audioSignalWindowRightCrossings=%d " +
                "audioSignalTotalFrames=%d audioSignalTotalSamples=%d " +
                "audioSignalTotalFrequencyResolutionHz=%.6f " +
                "audioSignalTotalOverflow=%s " +
                "audioSignalTotalLeftMin=%d audioSignalTotalLeftMax=%d " +
                "audioSignalTotalLeftPeak=%d audioSignalTotalLeftRms=%.3f " +
                "audioSignalTotalLeftToneHz=%.3f audioSignalTotalLeftCrossings=%d " +
                "audioSignalTotalRightMin=%d audioSignalTotalRightMax=%d " +
                "audioSignalTotalRightPeak=%d audioSignalTotalRightRms=%.3f " +
                "audioSignalTotalRightToneHz=%.3f audioSignalTotalRightCrossings=%d " +
                "marker=audio-pcm-signal",
                entry.id, request.systemId, window.sampleRate,
                window.frames, window.interleavedSamples, window.frequencyResolutionHz,
                window.overflowed,
                window.left.min, window.left.max, window.left.peak, window.left.rms,
                window.left.toneHz, window.left.positiveCrossings,
                window.right.min, window.right.max, window.right.peak, window.right.rms,
                window.right.toneHz, window.right.positiveCrossings,
                total.frames, total.interleavedSamples, total.frequencyResolutionHz,
                total.overflowed,
                total.left.min, total.left.max, total.left.peak, total.left.rms,
                total.left.toneHz, total.left.positiveCrossings,
                total.right.min, total.right.max, total.right.peak, total.right.rms,
                total.right.toneHz, total.right.positiveCrossings));
    }

    private void saveAutomatic() {
        try {
            LibretroHost active = host;
            if (active == null || vaultWorker == null || identity == null) return;
            persistSaveRam(active);
            byte[] state = active.serialize();
            Future<StateSnapshot> write = vaultWorker.saveAutomatic(identity, state, null,
                    checkpointScheduler.totalActiveMillis());
            notifyWhenCommitted(write);
        } catch (Throwable ignored) {
            // A failed background checkpoint never interrupts gameplay. Quick
            // Resume will retry on background/exit and retains the last good state.
        }
    }

    private void saveQuickResume(boolean waitForCommit, Completion completion) {
        synchronized (lifecycleSubmissionLock) {
            if (released.get() || lifecycle.isShutdown()) {
                if (waitForCommit) reportQuickResumeSaveFailure(
                        new IllegalStateException("Quick Resume owner is unavailable"));
                if (completion != null) completion.complete();
                return;
            }
            try {
                lifecycle.execute(() -> {
                    try {
                        LibretroHost active = host;
                        if (active != null && vaultWorker != null && identity != null) {
                            persistSaveRam(active);
                            byte[] state = active.serialize();
                            Future<StateSnapshot> write = vaultWorker.saveQuickResume(identity, state, null,
                                    checkpointScheduler == null ? 0L : checkpointScheduler.totalActiveMillis());
                            if (waitForCommit) {
                                write.get();
                                Log.i(TAG, "Quick Resume committed engine=" + entry.id +
                                        " system=" + request.systemId);
                            }
                            notifyRestoreAvailability();
                        }
                    } catch (Throwable failure) {
                        if (waitForCommit) reportQuickResumeSaveFailure(failure);
                    } finally {
                        if (completion != null) completion.complete();
                    }
                });
            } catch (java.util.concurrent.RejectedExecutionException rejected) {
                if (waitForCommit) reportQuickResumeSaveFailure(rejected);
                if (completion != null) completion.complete();
            }
        }
    }

    private void reportQuickResumeSaveFailure(Throwable failure) {
        // Never strand the user in a game when a core cannot serialize; the
        // previous verified Quick Resume remains untouched. A swallowed exit
        // failure is unacceptable: runtime acceptance greps for this marker,
        // and the listener surfaces it after the warm library returns.
        Log.w(TAG, "Exit save failed engine=" + entry.id +
                " system=" + (request == null ? "?" : request.systemId) +
                " marker=save-failure", failure);
        Listener callback = listener;
        if (callback != null) callback.onSessionStopRejected(
                "EmuFusion could not save your current position. " +
                "Your previous Quick Resume is still available.", failure);
    }

    private void restore(StateSnapshot snapshot) {
        lifecycle.execute(() -> {
            StateLoadResult loaded = vault.loadSnapshot(identity, snapshot);
            if (loaded.status != StateLoadResult.Status.OK) return;
            LibretroHost active = host;
            if (active != null) {
                active.unserialize(loaded.state);
                flushAudioAfterRestore();
            }
        });
    }

    private void notifyWhenCommitted(final Future<StateSnapshot> write) {
        try {
            lifecycle.execute(() -> {
                try {
                    write.get();
                    notifyRestoreAvailability();
                } catch (Throwable ignored) {}
            });
        } catch (java.util.concurrent.RejectedExecutionException ignored) {}
    }

    private List<StateSnapshot> restorableHistory() {
        List<StateSnapshot> all = vault.list(identity);
        List<StateSnapshot> history = new ArrayList<>();
        for (StateSnapshot snapshot : all)
            if (snapshot.metadata.kind != com.thorium.lucent.state.SnapshotKind.QUICK_RESUME)
                history.add(snapshot);
        return history;
    }

    private void notifyRestoreAvailability() {
        Listener callback = listener;
        if (callback != null && vault != null && identity != null)
            callback.onRestoreAvailabilityChanged(!restorableHistory().isEmpty());
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

    private boolean dispatchAxis(GamepadDescriptor device, int axis, int direction, boolean pressed) {
        try {
            InputSignal signal = InputSignal.axis(axis, direction);
            CanonicalControl control = inputRouter.resolve(device, signal);
            int id = joypadId(control);
            LibretroHost active = host;
            if (id < 0 || active == null) return false;
            joypad.apply(signal, id, pressed, joypadSink);
            return true;
        } catch (Exception ignored) { return false; }
    }

    private void showControlsMenu(GamepadDescriptor pad) {
        String[] actions = {
                "Remap for " + request.systemId,
                "Remap for this game",
                "Reset " + request.systemId + " mapping",
                "Reset this game mapping"
        };
        new AlertDialog.Builder(context)
                .setTitle(pad.name)
                .setItems(actions, (dialog, which) -> {
                    if (which == 0 || which == 1) showControlPicker(pad, which == 1);
                    else try {
                        inputRouter.resetRemap(pad, which == 3);
                    } catch (Exception error) { showControlError(error); }
                })
                .setNegativeButton("Done", null)
                .show();
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
        for (int i = 0; i < controls.length; i++)
            labels[i] = SystemControlLayouts.controlLabel(request.systemId, controls[i]);
        new AlertDialog.Builder(context)
                .setTitle("Choose a control")
                .setItems(labels, (dialog, which) -> captureControl(pad, controls[which], gameOnly))
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void captureControl(GamepadDescriptor pad, CanonicalControl control, boolean gameOnly) {
        AlertDialog capture = new AlertDialog.Builder(context)
                .setTitle("Press a button for " + SystemControlLayouts.controlLabel(
                        request.systemId, control))
                .setMessage("The next controller button becomes this control.")
                .setNegativeButton("Cancel", null)
                .create();
        capture.setOnKeyListener((dialog, keyCode, event) -> {
            if (event.getAction() != KeyEvent.ACTION_DOWN || event.getRepeatCount() != 0)
                return true;
            try {
                java.util.EnumMap<CanonicalControl, InputSignal> mapping =
                        new java.util.EnumMap<>(CanonicalControl.class);
                mapping.putAll(gameOnly ? inputRouter.effectiveMapping(pad) :
                        inputRouter.effectiveSystemMapping(pad));
                mapping.put(control, InputSignal.key(keyCode));
                inputRouter.saveRemap(pad, gameOnly, mapping);
                dialog.dismiss();
            } catch (Exception error) {
                dialog.dismiss();
                showControlError(error);
            }
            return true;
        });
        capture.show();
    }

    private void showControlError(Throwable error) {
        new AlertDialog.Builder(context).setTitle("Controls")
                .setMessage("EmuFusion could not save this mapping.")
                .setPositiveButton("OK", null).show();
    }

    private void presentVideoWithSurfaceLock(LibretroHost.VideoFrame frame) {
        presentationLock.lock();
        try {
            // A mailbox item may have been taken before pause/Exit. Check
            // inside the ownership lock so a queued renderer cannot revive
            // presentation after quiesce has acknowledged Surface retirement.
            if (running && !released.get()) presentVideo(frame);
        }
        finally { presentationLock.unlock(); }
    }

    private void presentVideo(LibretroHost.VideoFrame frame) {
        Surface target = surface;
        if (frame == null || target == null || !target.isValid() ||
                frame.sequence == lastVideoSequence) return;
        int bytesPerPixel = frame.pixelFormat == 1 ? 4 : 2;
        long pixelCountLong = (long) frame.width * (long) frame.height;
        long minimumPitch = (long) frame.width * bytesPerPixel;
        long requiredBytes = (long) frame.pitch * (long) frame.height;
        if (frame.pixelFormat < 0 || frame.pixelFormat > 2 ||
                frame.width < 1 || frame.height < 1 ||
                frame.width > MAX_VIDEO_DIMENSION || frame.height > MAX_VIDEO_DIMENSION ||
                pixelCountLong > MAX_VIDEO_PIXELS || frame.pitch < minimumPitch ||
                requiredBytes < 1 || requiredBytes != frame.byteSize ||
                frame.pixels.length < requiredBytes) return;
        lastVideoSequence = frame.sequence;
        int pixelCount = (int) pixelCountLong;
        if (frameColors == null || frameColors.length != pixelCount)
            frameColors = new int[pixelCount];
        decodePixels(frame, frameColors);
        boolean dualScreen = request != null && isDualScreenSystem(request.systemId);
        boolean splitScreens = dualScreen && hasSecondaryDsSurface();
        boolean phoneDs = dualScreen && !splitScreens && (frame.height & 1) == 0;
        int[] presentationColors = frameColors;
        int presentationWidth = frame.width;
        int presentationHeight = frame.height;
        if (phoneDs) {
            if (dsPhoneColors == null || dsPhoneColors.length != pixelCount)
                dsPhoneColors = new int[pixelCount];
            DualScreenLayout.dsSideBySide(frameColors, dsPhoneColors, frame.width, frame.height);
            presentationColors = dsPhoneColors;
            presentationWidth = frame.width * 2;
            presentationHeight = frame.height / 2;
        }
        primarySourceRect.set(0, 0, presentationWidth, presentationHeight);
        Rect primarySource = primarySourceRect;
        Rect secondarySource = null;
        if (splitScreens && frame.height >= 2 && (frame.height & 1) == 0) {
            // melonDS keeps native TopBottom order. A saved per-game choice
            // only changes destinations, not row origin, aspect or core layout.
            // Snapshot once so both physical panels use the same order.
            boolean touchOnPrimary = dsTouchOnPrimary;
            int primaryTop = DualScreenLayout.dsScreenTop(frame.height, true, touchOnPrimary);
            int secondaryTop = DualScreenLayout.dsScreenTop(frame.height, false, touchOnPrimary);
            primarySourceRect.set(0, primaryTop, frame.width, primaryTop + frame.height / 2);
            secondarySourceRect.set(0, secondaryTop, frame.width, secondaryTop + frame.height / 2);
            secondarySource = secondarySourceRect;
        }
        // A crop is half the picture, so the aspect the core reported for the
        // whole frame does not describe it. Withhold the engine's number for
        // the crops and let the hardware table (a DS screen is 4:3) answer.
        float sourceAspect = phoneDs ? 8f / 3f : dualScreen ? 0f : displayAspect;
        String systemId = request == null ? "" : request.systemId;
        float primaryAspect = PresentationGeometry.resolveAspect(systemId, sourceAspect,
                primarySource.width(), primarySource.height());
        FrameGenerationRenderer primaryGenerator =
                FrameGenerationRendererRegistry.find(target);
        Surface lower = secondarySurface;
        FrameGenerationRenderer lowerGenerator =
                FrameGenerationRendererRegistry.find(lower);
        // A direct producer must relinquish the surface before an FG owner
        // receives it. Normal mode changes recreate the session/surfaces.
        if (primaryGenerator != null && primaryDirectCanvas != null)
            primaryDirectCanvas.close();
        if (lowerGenerator != null && secondaryDirectCanvas != null)
            secondaryDirectCanvas.close();
        // Canvas consumes the decoded libretro rows. The generator reverses
        // rows inside each immutable crop snapshot; both paths therefore use
        // the same corrected physical-screen selection above.
        boolean needsBitmap = primaryGenerator == null ||
                (secondarySource != null && lower != null && lower.isValid() &&
                        lowerGenerator == null);
        if (needsBitmap) {
            if (frameBitmap == null || frameBitmap.getWidth() != presentationWidth ||
                    frameBitmap.getHeight() != presentationHeight) {
                if (frameBitmap != null) frameBitmap.recycle();
                frameBitmap = Bitmap.createBitmap(
                        presentationWidth, presentationHeight, Bitmap.Config.ARGB_8888);
            }
            frameBitmap.setPixels(presentationColors, 0, presentationWidth,
                    0, 0, presentationWidth, presentationHeight);
        }
        boolean presented = primaryGenerator != null
                ? primaryGenerator.submitSoftwareFrame(presentationColors,
                        presentationWidth, presentationHeight,
                        primarySource.left, primarySource.top,
                        primarySource.right, primarySource.bottom, primaryAspect,
                        frame.producerTimestampNs)
                : drawFrame(target, surfaceWidth, surfaceHeight,
                        primarySource, sourceAspect, false, frame.producerTimestampNs);
        if (secondarySource != null && lower != null && lower.isValid()) {
            // Observe restored source crops briefly to help distinguish core
            // output from presentation failures. Static menus, dark scenes
            // and different images with equal sampled sums are all valid.
            // These observations must never reset the core or discard its
            // resume reference. Real input/engine failure requires separate
            // evidence; the ordinary user-requested reset remains available.
            if (quickResumeLivenessWatch && --dualCropDiagCountdown <= 0) {
                dualCropDiagCountdown = 120;
                long topSum = 0, bottomSum = 0;
                int samples = 0;
                for (int y = 0; y < frame.height / 2; y += 16) {
                    int rowTop = y * frame.width;
                    int rowBottom = (y + frame.height / 2) * frame.width;
                    for (int x = 0; x < frame.width; x += 16) {
                        topSum += frameColors[rowTop + x] & 0xff;
                        bottomSum += frameColors[rowBottom + x] & 0xff;
                        ++samples;
                    }
                }
                Log.i(TAG, "DS crop blue-channel samples=" + samples +
                        " topMean=" + (samples == 0 ? 0 : topSum / samples) +
                        " bottomMean=" + (samples == 0 ? 0 :
                                bottomSum / samples) +
                        " resumeWatch=" + quickResumeLivenessWatch);
                if (quickResumeLivenessWatch) {
                    // End diagnostic work after repeated equal samples or at
                    // most 30 observations; neither outcome proves health.
                    long signature = topSum * 1_000_003L + bottomSum;
                    if (signature != quickResumeLastCropSignature) {
                        quickResumeLastCropSignature = signature;
                        quickResumeFrozenRepeats = 0;
                    } else if (++quickResumeFrozenRepeats >= 6) {
                        quickResumeLivenessWatch = false;
                        Log.w(TAG, "Quick Resume image samples unchanged;" +
                                " retaining running game and saved state" +
                                " engine=" + entry.id);
                    }
                    if (quickResumeLivenessWatch &&
                            ++quickResumeChangesSeen >= 30) {
                        quickResumeLivenessWatch = false;
                        Log.i(TAG, "Quick Resume image observation complete" +
                                " engine=" + entry.id);
                    }
                }
            }
            float lowerAspect = PresentationGeometry.resolveAspect(systemId, sourceAspect,
                    secondarySource.width(), secondarySource.height());
            boolean lowerPresented = lowerGenerator != null
                    ? lowerGenerator.submitSoftwareFrame(frameColors,
                            frame.width, frame.height,
                            secondarySource.left, secondarySource.top,
                            secondarySource.right, secondarySource.bottom, lowerAspect,
                            frame.producerTimestampNs)
                    : drawFrame(lower, secondarySurfaceWidth,
                            secondarySurfaceHeight, secondarySource, sourceAspect, true,
                            frame.producerTimestampNs);
            if (!lowerDrawEvidenceLogged) {
                lowerDrawEvidenceLogged = true;
                Log.i(TAG, "LucentLowerScreen bottom crop drawn engine=" + entry.id +
                        " system=" + request.systemId +
                        " secondarySurfaceNotNull=" + true +
                        " isValid=" + lower.isValid() +
                        " secondarySurfaceSize=" + secondarySurfaceWidth + "x" +
                        secondarySurfaceHeight +
                        " crop=" + secondarySource.width() + "x" + secondarySource.height() +
                        " drawFrameReturned=" + lowerPresented);
            }
        } else if (splitScreens && !lowerDrawEvidenceLogged) {
            lowerDrawEvidenceLogged = true;
            String reason = secondarySource == null ? "secondarySource-null(frameHeightNotEvenPair)"
                    : lower == null ? "secondarySurface-null(never-attached)"
                    : "secondarySurface-invalid";
            Log.i(TAG, "LucentLowerScreen bottom crop SKIPPED engine=" + entry.id +
                    " system=" + request.systemId +
                    " reason=" + reason +
                    " secondarySurfaceNotNull=" + (lower != null) +
                    " isValid=" + (lower != null && lower.isValid()) +
                    " secondarySurfaceSize=" + secondarySurfaceWidth + "x" +
                    secondarySurfaceHeight +
                    " frameSize=" + frame.width + "x" + frame.height +
                    " secondaryGameplayRequested=" + secondaryGameplayRequested);
        }
        if (presented && !frameEvidenceLogged) {
            int nonblack = 0;
            for (int color : frameColors) if ((color & 0x00ffffff) != 0) ++nonblack;
            if (nonblack > 0) {
                frameEvidenceLogged = true;
                // The resolved geometry is logged with the first visible frame
                // so a stretched picture can be diagnosed from a log alone:
                // "aspect" is what the picture was fitted to, "coreAspect" is
                // what the core claimed, and "destination" is where it landed.
                PresentationGeometry.Rectangle box = PresentationGeometry.fitFrame(
                        surfaceWidth, surfaceHeight, request.systemId, sourceAspect,
                        primarySource.width(), primarySource.height());
                Log.i(TAG, "Core frame presented engine=" + entry.id +
                        " system=" + request.systemId + " sequence=" + frame.sequence +
                        " size=" + frame.width + "x" + frame.height +
                        " nonblack=" + nonblack +
                        " surface=" + surfaceWidth + "x" + surfaceHeight +
                        " coreAspect=" + displayAspect +
                        " aspect=" + PresentationGeometry.resolveAspect(
                                request.systemId, sourceAspect,
                                primarySource.width(), primarySource.height()) +
                        " destination=" + box.left + "," + box.top + " " +
                        box.width() + "x" + box.height());
            }
        }
        directVideoTelemetry.recordPresentation(presented);
        if (presented) {
            Runnable callback = firstFrameCallback;
            firstFrameCallback = null;
            if (callback != null) try { callback.run(); }
            catch (Throwable ignored) {}
        }
    }

    @Override public void setFirstFrameCallback(Runnable callback) {
        firstFrameCallback = callback;
    }

    private boolean drawFrame(Surface target, int requestedWidth, int requestedHeight,
                              Rect source, float engineAspect,
                              boolean preserveWholePicture, long sourceVsyncNs) {
        Canvas canvas = null;
        DirectHardwareCanvas timestampedCanvas = null;
        boolean presented = false;
        try {
            if (useTimestampedDirectCanvas(preserveWholePicture) &&
                    Build.VERSION.SDK_INT >= 29 && !timestampedDirectCanvasUnavailable &&
                    requestedWidth > 0 && requestedHeight > 0) {
                try {
                    if (preserveWholePicture) {
                        if (secondaryDirectCanvas == null) secondaryDirectCanvas =
                                new DirectHardwareCanvas("EmuFusion direct lower");
                        timestampedCanvas = secondaryDirectCanvas;
                    } else {
                        if (primaryDirectCanvas == null) primaryDirectCanvas =
                                new DirectHardwareCanvas("EmuFusion direct top");
                        timestampedCanvas = primaryDirectCanvas;
                    }
                    canvas = timestampedCanvas.begin(target, requestedWidth, requestedHeight,
                            preserveWholePicture ? directSecondarySurfaceEpoch : directSurfaceEpoch);
                } catch (Throwable unavailable) {
                    closeDirectCanvases();
                    timestampedCanvas = null;
                    timestampedDirectCanvasUnavailable = true;
                    Log.w(TAG, "Timestamped direct canvas unavailable; using Surface canvas",
                            unavailable);
                }
            }
            // lockCanvas() is a CPU raster target. Scaling a 256x224 console
            // frame over the Thor's 1440x1080 gameplay surface there measured
            // only 42-45 successful posts/s while the core held 60.09 fps.
            // Hardware Canvas keeps the exact direct Surface and original frame
            // semantics but moves the full-panel filtered blit to the GPU.
            if (canvas == null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                try {
                    canvas = target.lockHardwareCanvas();
                } catch (Throwable unavailable) {
                    if (!directHardwareCanvasFallbackLogged) {
                        directHardwareCanvasFallbackLogged = true;
                        Log.w(TAG, "Hardware Canvas unavailable; falling back to CPU direct blit",
                                unavailable);
                    }
                    canvas = target.lockCanvas(null);
                }
            } else if (canvas == null) canvas = target.lockCanvas(null);
            canvas.drawColor(android.graphics.Color.BLACK);
            int width = requestedWidth > 0 ? requestedWidth : canvas.getWidth();
            int height = requestedHeight > 0 ? requestedHeight : canvas.getHeight();
            // One rule, shared with every other engine path: keep the real
            // display aspect and grow until the picture is flush with the top
            // and bottom edges, pillarboxing the sides. Never the frame's own
            // pixel dimensions when the system's hardware aspect is known --
            // a Mega Drive frame is 320x224 but the console drew it 4:3, and
            // scaling by 320/224 is precisely the "stretched wider than it is
            // tall" fault. The surface dimensions are whatever was measured at
            // runtime; nothing here assumes a particular panel size.
            String systemId = request == null ? "" : request.systemId;
            PresentationGeometry.Rectangle box = preserveWholePicture
                    ? PresentationGeometry.fitFrameInside(
                            width, height, systemId, engineAspect,
                            source.width(), source.height())
                    : PresentationGeometry.fitFrame(
                            width, height, systemId, engineAspect,
                            source.width(), source.height());
            // Only a whole-number scale of the source pixels can be blitted
            // without resampling; anything else needs filtering to avoid
            // shimmering on movement.
            boolean integerScale = source.width() > 0 && source.height() > 0 &&
                    box.width() % source.width() == 0 &&
                    box.height() % source.height() == 0;
            frameDestinationRect.set(box.left, box.top, box.right, box.bottom);
            canvas.drawBitmap(frameBitmap, source, frameDestinationRect,
                    integerScale ? nearestFramePaint : filteredFramePaint);
            presented = true;
        } catch (Throwable ignored) {
        } finally {
            if (canvas != null) try {
                if (timestampedCanvas != null)
                    presented = timestampedCanvas.post(sourceVsyncNs) && presented;
                else target.unlockCanvasAndPost(canvas);
            }
            catch (Throwable ignored) { presented = false; }
        }
        return presented;
    }

    private boolean useTimestampedDirectCanvas(boolean secondary) {
        return secondary || !primaryRecoverySurfaceCanvas;
    }

    private void closeDirectCanvases() {
        presentationLock.lock();
        try {
            if (primaryDirectCanvas != null) primaryDirectCanvas.close();
            if (secondaryDirectCanvas != null) secondaryDirectCanvas.close();
        } finally { presentationLock.unlock(); }
    }

    private static boolean isDualScreenSystem(String systemId) {
        if (systemId == null) return false;
        String normalized = systemId.trim().toLowerCase(Locale.US);
        return "nds".equals(normalized) || "ds".equals(normalized);
    }

    private static void decodePixels(LibretroHost.VideoFrame frame, int[] output) {
        byte[] bytes = frame.pixels;
        int bytesPerPixel = frame.pixelFormat == 1 ? 4 : 2;
        for (int y = 0; y < frame.height; y++) {
            int source = y * frame.pitch;
            int target = y * frame.width;
            for (int x = 0; x < frame.width; x++, source += bytesPerPixel) {
                int red, green, blue;
                if (frame.pixelFormat == 1) { // RETRO_PIXEL_FORMAT_XRGB8888, little endian
                    blue = bytes[source] & 0xff;
                    green = bytes[source + 1] & 0xff;
                    red = bytes[source + 2] & 0xff;
                } else {
                    int value = (bytes[source] & 0xff) | ((bytes[source + 1] & 0xff) << 8);
                    if (frame.pixelFormat == 2) { // RGB565
                        red = ((value >> 11) & 31) * 255 / 31;
                        green = ((value >> 5) & 63) * 255 / 63;
                        blue = (value & 31) * 255 / 31;
                    } else { // 0RGB1555
                        red = ((value >> 10) & 31) * 255 / 31;
                        green = ((value >> 5) & 31) * 255 / 31;
                        blue = (value & 31) * 255 / 31;
                    }
                }
                output[target + x] = 0xff000000 | (red << 16) | (green << 8) | blue;
            }
        }
    }

    private void presentAudio(short[] samples) {
        AudioTrack audio = audioTrack;
        PcmAudioQueue queue = audioQueue;
        if (samples != null && samples.length > 0) {
            // This is deliberately before every AudioTrack/focus/queue branch.
            // It proves what PCM crossed out of the core, never speaker output.
            PcmSignalTelemetry signal = audioSignalTelemetry;
            if (signal != null) {
                try { signal.accept(samples); }
                catch (IllegalArgumentException malformed) {
                    recordAudioWriteError("signal-telemetry-malformed-pcm", malformed);
                }
            }
            recordProducedSamples(samples.length);
        }
        if (audio == null || queue == null) {
            if (samples != null) recordDroppedSamples(samples.length,
                    "track-or-queue-unavailable");
            return;
        }
        if (audioFocus.isSuppressed()) {
            // Another app owns the output. Drop what the core produced rather
            // than queueing it behind the paused track: the buffer would fill,
            // every later write would return 0, and stale sound would play when
            // focus came back. This intentional loss has its own counter and is
            // never confused with a sink overflow in QA.
            int discarded = queue.clear();
            if (samples != null) discarded += samples.length;
            recordFocusDroppedSamples(discarded);
            return;
        }
        if (samples != null && samples.length > 0) {
            int rejected = queue.offer(samples);
            if (rejected > 0) recordDroppedSamples(rejected, "java-queue-full");
        }

        // One core frame can produce several small callback blocks. Drain a
        // bounded number per iteration so a recovered sink catches up without
        // letting audio writes monopolize the emulation clock.
        boolean trackFilled = false;
        for (int attempt = 0; attempt < 8; attempt++) {
            // Focus callbacks may clear the FIFO from another thread. Hold
            // its monitor from head lookup through consume so an accepted
            // AudioTrack write can never race a clear and corrupt accounting.
            synchronized (queue) {
                short[] head = queue.head();
                if (head == null) break;
                int offset = queue.headOffset();
                int requested = head.length - offset;
                final int written;
                try {
                    written = Build.VERSION.SDK_INT >= 23
                            ? audio.write(head, offset, requested, AudioTrack.WRITE_NON_BLOCKING)
                            : audio.write(head, offset, requested);
                } catch (Throwable failure) {
                    recordAudioWriteError("exception", failure);
                    break;
                }
                if (written > 0) {
                    queue.consume(written);
                    qualificationAudioSamplesWritten += written;
                    if (!audioStartedOnce) primedAudioSamples += written;
                    if (written < requested) {
                        synchronized (audioTelemetryLock) { ++audioPartialWrites; }
                        break;
                    }
                } else if (written == 0) {
                    synchronized (audioTelemetryLock) { ++audioZeroWrites; }
                    trackFilled = true;
                    break;
                } else {
                    recordAudioWriteError("code=" + written, null);
                    break;
                }
            }
        }
        synchronized (runLock) {
            try {
                boolean canStart = audioStartedOnce ? trackFilled
                        : primedAudioSamples >= audioPrimeSamplesTarget;
                // Serialize with pause's running=false so late PCM cannot
                // restart audio after the lifecycle gate has closed.
                if (running && !stopping.get() && !released.get() &&
                        !audioFocus.isSuppressed() && canStart &&
                        audio.getPlayState() != AudioTrack.PLAYSTATE_PLAYING) {
                    boolean resumed = audioStartedOnce;
                    audio.play();
                    audioStartedOnce = true;
                    audioStartedAtMillis = SystemClock.elapsedRealtime();
                    Log.i(TAG, "Audio playback " + (resumed ? "resumed" : "started") +
                            " engine=" + entry.id + " primedSamples=" + primedAudioSamples);
                }
            } catch (Throwable failure) {
                recordAudioWriteError("play-exception", failure);
            }
        }
        try {
            applySteadyAudioBuffer(audio);
        } catch (Throwable failure) {
            recordAudioWriteError("buffer-resize-exception", failure);
        }
    }

    private void drainAndPresentAudio(LibretroHost active) {
        // 4,096 stereo frames exceed one 192 kHz core frame at 40/50/60 Hz.
        // Continue while a full block comes back so a burst accumulated during
        // a brief sink stall is removed from the native ring in the same
        // emulation iteration rather than being silently overwritten there.
        final int maxFrames = 4_096;
        for (int attempt = 0; attempt < 8; attempt++) {
            short[] samples = active.drainAudio(maxFrames);
            presentAudio(samples);
            if (samples == null || samples.length < maxFrames * 2) return;
        }
        // Reaching the bound means the native producer is outrunning Java by
        // more than 32,768 frames. We cannot inspect the native ring depth from
        // this ABI, so fail visibly rather than claiming complete accounting.
        boolean shouldLog;
        synchronized (audioTelemetryLock) {
            ++audioNativeDrainBoundHits;
            shouldLog = !audioNativeDrainBoundLogged;
            audioNativeDrainBoundLogged = true;
        }
        if (shouldLog) {
            Log.e(TAG, "Native audio drain remained saturated engine=" + entry.id +
                    " system=" + (request == null ? "?" : request.systemId) +
                    " marker=audio-native-drain-bound");
        }
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

    private static int audioQueueCapacitySamples(double sampleRate) {
        int startupSamples = startupAudioBufferBytes(sampleRate) / 2;
        // Three startup buffers are roughly 600 ms. That absorbs a transient
        // partial write but remains bounded tightly enough that a dead sink is
        // reported as loss instead of producing seconds of delayed sound.
        return Math.max(8_192, startupSamples * 3);
    }

    private void resetAudioTelemetry() {
        synchronized (audioTelemetryLock) {
            audioProducedSamples = 0L;
            audioDroppedSamples = 0L;
            audioFocusDroppedSamples = 0L;
            audioPartialWrites = 0L;
            audioZeroWrites = 0L;
            audioWriteErrors = 0L;
            audioNativeDrainBoundHits = 0L;
            qualificationAudioProducedAtWindowStart = 0L;
            qualificationAudioDroppedAtWindowStart = 0L;
            qualificationAudioFocusDroppedAtWindowStart = 0L;
            qualificationAudioPartialWritesAtWindowStart = 0L;
            qualificationAudioZeroWritesAtWindowStart = 0L;
            qualificationAudioWriteErrorsAtWindowStart = 0L;
            qualificationAudioNativeDrainBoundHitsAtWindowStart = 0L;
            audioDropLogged = false;
            audioWriteFailureLogged = false;
            audioNativeDrainBoundLogged = false;
        }
        PcmSignalTelemetry signal = audioSignalTelemetry;
        if (signal != null) signal.resetAll();
        qualificationAudioUnderrunsAtWindowStart = currentAudioUnderruns();
    }

    private void recordProducedSamples(int samples) {
        if (samples <= 0) return;
        synchronized (audioTelemetryLock) { audioProducedSamples += samples; }
    }

    private void recordFocusDroppedSamples(int samples) {
        if (samples <= 0) return;
        synchronized (audioTelemetryLock) { audioFocusDroppedSamples += samples; }
    }

    private void recordDroppedSamples(int samples, String reason) {
        if (samples <= 0) return;
        boolean shouldLog;
        synchronized (audioTelemetryLock) {
            audioDroppedSamples += samples;
            shouldLog = !audioDropLogged;
            audioDropLogged = true;
        }
        if (shouldLog) Log.e(TAG, "Audio PCM dropped engine=" + entry.id +
                " system=" + (request == null ? "?" : request.systemId) +
                " samples=" + samples + " reason=" + reason +
                " marker=audio-pcm-drop");
    }

    private void recordAudioWriteError(String operation, Throwable failure) {
        boolean shouldLog;
        synchronized (audioTelemetryLock) {
            ++audioWriteErrors;
            shouldLog = !audioWriteFailureLogged;
            audioWriteFailureLogged = true;
        }
        String message = "Audio sink failure engine=" + entry.id +
                " system=" + (request == null ? "?" : request.systemId) +
                " operation=" + operation + " marker=audio-write-failure";
        if (shouldLog) Log.e(TAG, message, failure);
    }

    private void captureAudioTelemetryBaseline() {
        synchronized (audioTelemetryLock) {
            qualificationAudioProducedAtWindowStart = audioProducedSamples;
            qualificationAudioDroppedAtWindowStart = audioDroppedSamples;
            qualificationAudioFocusDroppedAtWindowStart = audioFocusDroppedSamples;
            qualificationAudioPartialWritesAtWindowStart = audioPartialWrites;
            qualificationAudioZeroWritesAtWindowStart = audioZeroWrites;
            qualificationAudioWriteErrorsAtWindowStart = audioWriteErrors;
            qualificationAudioNativeDrainBoundHitsAtWindowStart = audioNativeDrainBoundHits;
        }
        qualificationAudioUnderrunsAtWindowStart = currentAudioUnderruns();
    }

    private AudioTelemetry measuredAudioTelemetry() {
        // Query first: a platform exception is itself a sink error and must be
        // included in this window rather than incremented after its snapshot.
        int currentUnderruns = currentAudioUnderruns();
        long produced;
        long dropped;
        long focusDropped;
        long partial;
        long zero;
        long errors;
        long drainBounds;
        synchronized (audioTelemetryLock) {
            produced = Math.max(0L,
                    audioProducedSamples - qualificationAudioProducedAtWindowStart);
            dropped = Math.max(0L,
                    audioDroppedSamples - qualificationAudioDroppedAtWindowStart);
            focusDropped = Math.max(0L,
                    audioFocusDroppedSamples - qualificationAudioFocusDroppedAtWindowStart);
            partial = Math.max(0L,
                    audioPartialWrites - qualificationAudioPartialWritesAtWindowStart);
            zero = Math.max(0L,
                    audioZeroWrites - qualificationAudioZeroWritesAtWindowStart);
            errors = Math.max(0L,
                    audioWriteErrors - qualificationAudioWriteErrorsAtWindowStart);
            drainBounds = Math.max(0L, audioNativeDrainBoundHits -
                    qualificationAudioNativeDrainBoundHitsAtWindowStart);
        }
        int underruns = currentUnderruns < 0 || qualificationAudioUnderrunsAtWindowStart < 0
                ? -1 : Math.max(0, currentUnderruns - qualificationAudioUnderrunsAtWindowStart);
        return new AudioTelemetry(produced, dropped, focusDropped, partial, zero,
                errors, drainBounds, underruns);
    }

    private int currentAudioUnderruns() {
        AudioTrack audio = audioTrack;
        if (audio == null || Build.VERSION.SDK_INT < 24) return -1;
        try { return audio.getUnderrunCount(); }
        catch (Throwable failure) {
            recordAudioWriteError("underrun-query", failure);
            return -1;
        }
    }

    private static final class AudioTelemetry {
        final long producedSamples;
        final long droppedSamples;
        final long focusDroppedSamples;
        final long partialWrites;
        final long zeroWrites;
        final long writeErrors;
        final long nativeDrainBoundHits;
        final int underruns;

        AudioTelemetry(long producedSamples, long droppedSamples,
                long focusDroppedSamples, long partialWrites, long zeroWrites,
                long writeErrors, long nativeDrainBoundHits, int underruns) {
            this.producedSamples = producedSamples;
            this.droppedSamples = droppedSamples;
            this.focusDroppedSamples = focusDroppedSamples;
            this.partialWrites = partialWrites;
            this.zeroWrites = zeroWrites;
            this.writeErrors = writeErrors;
            this.nativeDrainBoundHits = nativeDrainBoundHits;
            this.underruns = underruns;
        }
    }

    private void flushAudioAfterRestore() {
        PcmAudioQueue queue = audioQueue;
        if (queue != null) queue.clear();
        primedAudioSamples = 0;
        audioStartedOnce = false;
        audioStartedAtMillis = 0L;
        steadyAudioBufferApplied = false;
        AudioTrack audio = audioTrack;
        if (audio == null) return;
        try {
            audio.pause();
            audio.flush();
            // Playback restarts only after fresh post-restore PCM is primed --
            // and priming has to be able to REACH its target. After five
            // seconds applySteadyAudioBuffer shrinks the track to the smaller
            // low-latency buffer, and that survives pause/flush. Leaving it
            // shrunk meant primedAudioSamples could never reach the startup
            // prime target, so play() was never called again and the game ran
            // on in silence until the session was torn down and rebuilt. That
            // is exactly the "reset killed the sound until I exited and
            // re-entered" symptom. Restore the startup size to match the
            // startup target we are about to prime against.
            if (Build.VERSION.SDK_INT >= 24) {
                int startupFrames = startupAudioBufferBytes(audio.getSampleRate()) / 4;
                if (startupFrames > 0) audio.setBufferSizeInFrames(startupFrames);
            }
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

    private static int startupAudioBufferBytes(double sampleRate) {
        int rate = (int) Math.round(sampleRate);
        if (rate < 8_000 || rate > 192_000) return 0;
        int minimum = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_STEREO,
                AudioFormat.ENCODING_PCM_16BIT);
        return minimum <= 0 ? 0 : Math.max(minimum, rate / 5 * 4);
    }

    private static int steadyAudioBufferBytes(double sampleRate) {
        int rate = (int) Math.round(sampleRate);
        if (rate < 8_000 || rate > 192_000) return 0;
        int minimum = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_STEREO,
                AudioFormat.ENCODING_PCM_16BIT);
        return minimum <= 0 ? 0 : Math.max(minimum, rate / 20 * 4);
    }

    private void persistSaveRam(LibretroHost active) throws Exception {
        byte[] bytes = active.readSaveRam();
        if (bytes == null || saveRamFile == null) return;
        DurableBlobStore.write(saveRamFile, bytes, MAX_SAVE_RAM_BYTES);
    }

    /**
     * Applies whichever cheats the user left switched on for this game.
     *
     * <p>Runs after the content is loaded, because libretro cheats address core
     * memory that does not exist until then, and after the save RAM restore so
     * a cheat writes over the restored state rather than the other way round.
     *
     * <p>Never fatal: a game must still start when its cheats cannot be read.
     *
     * <p>The selection is kept afterwards even when nothing is switched on,
     * because it is also what the in-game menu lists and toggles; loading the
     * catalogue again from the pause menu would re-read the database on the UI
     * thread for an answer this session already has.
     */
    private void applyStoredCheats(LibretroHost active, GameLaunchRequest launch,
                                   String contentName) {
        long attempt = 0L;
        try {
            if (!supportsLiveCheats(entry.id)) return;
            CheatSelection selection = CheatControl.selectionForGame(appContext,
                    launch.systemId, launch.gameTitle, contentName);
            java.util.List<Cheat> available = selection.available();
            if (available.isEmpty()) return;
            String gameKey = CheatDatabase.key(launch.systemId, launch.gameTitle);
            synchronized (cheatLock) {
                cheats = selection;
                cheatGameKey = gameKey;
            }
            java.util.List<String> codes = selection.enabledCodes();
            if (codes.isEmpty()) return;
            attempt = cheatApplySequence.incrementAndGet();
            Log.i(TAG, "Cheat apply attempted engine=" + entry.id +
                    " system=" + launch.systemId + " attempt=" + attempt +
                    " source=stored count=" + codes.size() +
                    " marker=cheat-apply-attempt");
            active.applyCheats(codes);
            Log.i(TAG, "Cheats applied engine=" + entry.id + " system=" + launch.systemId +
                    " attempt=" + attempt + " count=" + codes.size() +
                    " callbackReturned=true acknowledged=false " +
                    "effectProofRequired=true marker=cheat-apply-returned");
        } catch (Throwable failure) {
            Log.w(TAG, "Cheats were not applied engine=" + entry.id +
                    " system=" + launch.systemId +
                    (attempt == 0L ? "" : " attempt=" + attempt) +
                    " source=stored selectionRetained=true effectProofRequired=true" +
                    " marker=cheat-apply-failure", failure);
        }
    }

    private static boolean supportsLiveCheats(String engineId) {
        // Source-audited implementations only. Several libretro cores export
        // the ABI as an empty compatibility stub; listing their database rows
        // would make the switch move while doing nothing in the game.
        return "mesen".equals(engineId) || "mesen-s".equals(engineId) ||
                "sameboy".equals(engineId) || "mgba".equals(engineId) ||
                "gearsystem".equals(engineId) || "swanstation".equals(engineId) ||
                "melonds-ds".equals(engineId) || "fuse".equals(engineId) ||
                "virtualjaguar".equals(engineId);
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

    /**
     * Toggles one cheat on the running core.
     *
     * <p>The selection changes here and now so the menu row it came from can
     * redraw from the session's own state, while the two slow halves -- taking
     * the host monitor, which waits out any frame already inside the core, and
     * the store's fsync -- run on the lifecycle thread. Doing either inline
     * would stall the UI thread on native work for a button press.
     *
     * <p>libretro has no "remove one cheat" call, so every toggle re-applies
     * the whole enabled set; {@link CheatSelection#enabledCodes()} keeps that
     * set in authored order so overlapping codes land the same way each time.
     */
    @Override public boolean setCheatEnabled(String cheatId, boolean enabled) {
        LibretroHost active = host;
        if (!prepared || active == null || stopping.get() || released.get()) return false;
        final java.util.List<String> codes;
        final java.util.Set<String> enabledIds;
        final String gameKey;
        synchronized (cheatLock) {
            if (cheats == null || !offers(cheats, cheatId)) return false;
            cheats.setEnabled(cheatId, enabled);
            codes = cheats.enabledCodes();
            enabledIds = cheats.enabledIds();
            gameKey = cheatGameKey;
        }
        synchronized (lifecycleSubmissionLock) {
            if (released.get() || lifecycle.isShutdown()) {
                synchronized (cheatLock) {
                    // This path proves the owner task never ran, so restoring
                    // the prior menu state is accurate rather than speculative.
                    if (cheats != null) cheats.setEnabled(cheatId, !enabled);
                }
                Log.w(TAG, "Cheat apply owner unavailable engine=" + entry.id +
                        " system=" + request.systemId + " id=" + cheatId +
                        " stage=pre-submit selectionRetained=false " +
                        "marker=cheat-apply-failure");
                return false;
            }
            final long attempt = cheatApplySequence.incrementAndGet();
            Log.i(TAG, "Cheat apply attempted engine=" + entry.id +
                    " system=" + request.systemId + " attempt=" + attempt +
                    " source=live id=" + cheatId + " enabled=" + enabled +
                    " active=" + codes.size() + " marker=cheat-apply-attempt");
            try {
                lifecycle.execute(() -> {
                    LibretroHost open = host;
                    if (open == null || stopping.get() || released.get()) {
                        // The selection may already have been observed by the
                        // UI, but this asynchronous state transition cannot
                        // prove that rolling it back is still current.
                        Log.w(TAG, "Cheat apply session unavailable engine=" + entry.id +
                                " system=" + request.systemId + " attempt=" + attempt +
                                " id=" + cheatId + " stage=session-unavailable " +
                                "selectionRetained=true effectProofRequired=true " +
                                "marker=cheat-apply-failure");
                        return;
                    }
                    boolean callbackReturned = false;
                    try {
                        synchronized (open) { open.applyCheats(codes); }
                        callbackReturned = true;
                        CheatControl.store(appContext).save(gameKey, enabledIds);
                        // retro_cheat_set is a void ABI. Returning proves the
                        // exact core callback did not throw or crash, not that
                        // this ROM revision changed as the code author intended.
                        Log.i(TAG, "Cheat apply returned engine=" + entry.id +
                                " system=" + request.systemId + " attempt=" + attempt +
                                " id=" + cheatId + " enabled=" + enabled +
                                " active=" + codes.size() +
                                " callbackReturned=true persisted=true " +
                                "acknowledged=false effectProofRequired=true " +
                                "marker=cheat-apply-returned");
                    } catch (Throwable failure) {
                        Log.w(TAG, "Cheat toggle rejected engine=" + entry.id +
                                " system=" + request.systemId + " attempt=" + attempt +
                                " id=" + cheatId + " stage=" +
                                (callbackReturned ? "persistence" : "core-callback") +
                                " selectionRetained=true effectProofRequired=true " +
                                "marker=cheat-apply-failure", failure);
                    }
                });
            } catch (java.util.concurrent.RejectedExecutionException rejected) {
                synchronized (cheatLock) {
                    // The owner rejected the task before any native callback
                    // could run, so this is the one failure for which rollback
                    // is certain rather than an inference from libretro's void
                    // ABI.
                    if (cheats != null) cheats.setEnabled(cheatId, !enabled);
                }
                Log.w(TAG, "Cheat apply queue rejected engine=" + entry.id +
                        " system=" + request.systemId + " attempt=" + attempt +
                        " id=" + cheatId + " selectionRetained=false " +
                        "marker=cheat-apply-failure", rejected);
                return false;
            }
        }
        return true;
    }

    private static boolean offers(CheatSelection selection, String cheatId) {
        if (cheatId == null || cheatId.isEmpty()) return false;
        for (Cheat cheat : selection.available())
            if (cheat.id.equals(cheatId)) return true;
        return false;
    }

    private void restoreSaveRam(LibretroHost active, File file) throws Exception {
        byte[] value = DurableBlobStore.read(file, MAX_SAVE_RAM_BYTES);
        if (value == null) return;
        // Some cores (notably mGBA) do not expose the cartridge's final save
        // memory type/size until emulation has begun. A stale early size must
        // never make a valid game unlaunchable or discard the saved bytes.
        // Prime only as many undisplayed frames as needed, then restore before
        // Quick Resume or the visible frame loop can start.
        for (int attempt = 0; attempt < 4; attempt++) {
            byte[] current = active.readSaveRam();
            if (current != null && current.length == value.length) {
                active.writeSaveRam(value);
                return;
            }
            // mGBA exposes an erased 128 KiB frontend buffer while the GBA
            // cartridge type is still AUTODETECT. Its first retro_run copies
            // that buffer into the core's deferred save loader. Install the
            // complete known-size save before that first frame, preserving an
            // erased tail; waiting for the final size can boot without progress.
            // This is a pinned mGBA contract, not generic cross-core padding.
            if (attempt == 0 && "mgba".equals(entry.id) && current != null &&
                    current.length == 128 * 1024 &&
                    (value.length == 512 || value.length == 8 * 1024 ||
                     value.length == 32 * 1024 || value.length == 64 * 1024)) {
                java.util.Arrays.fill(current, (byte) 0xff);
                System.arraycopy(value, 0, current, 0, value.length);
                active.writeSaveRam(current);
                Log.i(TAG, "Restored mGBA cartridge save before deferred setup storedBytes=" +
                        value.length + " bufferBytes=" + current.length);
                return;
            }
            active.runFrame();
        }
        Log.w(TAG, "Retaining save RAM for a future compatible core size; " +
                "storedBytes=" + value.length);
    }

    private int joypadId(CanonicalControl control) {
        return LibretroJoypadLayout.idFor(request.systemId, control);
    }

    private static File resolveGameFile(Uri uri) throws Exception {
        if (uri == null) throw new IllegalArgumentException("ROM URI is missing");
        String raw = "file".equals(uri.getScheme()) ? uri.getPath() : uri.getQueryParameter("path");
        if (raw == null || raw.trim().isEmpty())
            throw new IllegalArgumentException("ROM URI does not expose a local file");
        File file = new File(raw).getCanonicalFile();
        String path = file.getPath();
        if (!(path.startsWith("/storage/") || path.startsWith("/mnt/media_rw/")) || !file.isFile())
            throw new IllegalArgumentException("ROM is outside approved Android storage");
        return file;
    }

    private static String firmwareFingerprint(File directory, boolean required,
            List<String> acceptedHashes) throws Exception {
        File[] files = directory.listFiles(file -> file.isFile());
        if (acceptedHashes == null || acceptedHashes.isEmpty()) {
            if (required) throw new IllegalStateException(
                    "This engine has no audited firmware identities");
            return "firmware:none";
        }
        if (files == null || files.length == 0) {
            if (required) throw new IllegalStateException("This engine requires user-supplied firmware");
            return "firmware:none";
        }
        java.util.Arrays.sort(files, (left, right) -> left.getName().compareTo(right.getName()));
        MessageDigest identityDigest = MessageDigest.getInstance("SHA-256");
        int accepted = 0;
        for (File file : files) {
            String hash = sha256(file);
            if (!acceptedHashes.contains(hash)) continue;
            accepted++;
            identityDigest.update(file.getName().getBytes("UTF-8"));
            identityDigest.update(hash.getBytes("US-ASCII"));
        }
        if (required && accepted == 0)
            throw new IllegalStateException("Required firmware did not match an audited identity");
        return accepted == 0 ? "firmware:none" : "firmware:" + hex(identityDigest.digest());
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        InputStream input = new FileInputStream(file);
        try {
            byte[] buffer = new byte[64 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0) if (count > 0)
                digest.update(buffer, 0, count);
        } finally { input.close(); }
        return hex(digest.digest());
    }

    private static String storageKey(String value) throws Exception {
        return hex(MessageDigest.getInstance("SHA-256").digest(
                value.getBytes("UTF-8"))).substring(0, 32);
    }

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) result.append(String.format(Locale.US, "%02x", value & 0xff));
        return result.toString();
    }

    private static String formatPlayTime(long millis) {
        long minutes = Math.max(0L, millis) / 60_000L;
        return minutes < 60 ? minutes + " min" : (minutes / 60) + "h " + (minutes % 60) + "m";
    }
}
