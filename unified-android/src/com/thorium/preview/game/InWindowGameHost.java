package com.thorium.preview.game;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.media.AudioManager;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.PowerManager;
import android.os.SystemClock;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.Display;
import android.view.KeyEvent;
import android.view.MotionEvent;
import com.thorium.lucent.input.CanonicalControl;
import android.view.Surface;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatPanelModel;
import com.thorium.lucent.cheats.CheatPanelSnapshot;
import com.thorium.lucent.emulators.NativeAdapterStopPolicy;
import com.thorium.lucent.metadata.EngineSystemIdResolver;
import com.thorium.lucent.timing.DisplaySyncPolicy;
import com.thorium.preview.MenuSoundPlayer;
import com.thorium.preview.AppVolumeController;
import com.thorium.preview.BootVideoOverlay;
import com.thorium.preview.FrontendRestartActivity;
import com.thorium.preview.PreviewService;
import com.thorium.preview.PrivateDiagnostics;
import com.thorium.preview.PrivateDiagnosticsSession;
import com.thorium.preview.SecondaryCheatPanelRouter;

/**
 * Owns in-process emulation inside EmuFusion's existing Qt MainActivity window.
 *
 * This deliberately is not an Activity. The library, gameplay surface, pause
 * UI, save lifecycle, and return transition therefore share one Android
 * ActivityRecord, task, application window, and process.
 */
public final class InWindowGameHost
        implements GameSurface.Listener, EngineSession.Listener,
        SecondaryCheatPanelRouter.Controller {
    public static final String ACTION_LAUNCH =
            "com.thorium.preview.LAUNCH_INTERNAL_GAME";
    private static final String TAG = "LucentInWindow";
    private static final String AUTHORITY = "com.thorium.preview.roms";
    private static final long STOP_HOLD_MS = 1000L;
    // Select+Start held together resets the running game. Three seconds is far
    // enough past the 1 s Stop hold and past any Start press a game asks for
    // that it cannot be reached by accident.
    private static final long RESET_COMBO_HOLD_MS = 2000L;
    // About three 60 fps frame periods: long enough that every core's next
    // input poll observes the synthesized Select press, short enough to feel
    // like a tap.
    private static final long TAP_SELECT_HOLD_MS = 48L;
    // Destroy-time bound on how long the quiesced game views may await a stop
    // completion that never fires. The Activity is already being destroyed; a
    // wedged engine must not leak its view tree indefinitely.
    private static final long DESTROY_DETACH_FALLBACK_MS = 4000L;
    // Exit-time bound for a core that never returned from the frame it was
    // running when Exit was chosen (quiesce failed). Its checkpoint cannot run
    // and the retained gameplay Surface keeps covering the library, so the
    // process is replaced through the restart bridge after this wait. Normal
    // exits, including Dolphin's ~100 MB state, commit well inside it.
    private static final long WEDGED_EXIT_RESTART_MS = 15_000L;
    private static final int COLOR_ACCENT = Color.rgb(151, 119, 255);
    private static final java.util.regex.Pattern QUALIFICATION_SESSION =
            java.util.regex.Pattern.compile("qa-[0-9a-f]{32}");

    private static InWindowGameHost active;
    private static final String RECREATION_STATE = "lucent.inWindow.recreation.v1";
    private static final WeakHashMap<Activity, RecreationState> RECREATIONS =
            new WeakHashMap<>();
    private static int destroyedSessionsRetiring;
    private static boolean qtTerminalShutdownRequested;
    private static Runnable pendingQtTerminalShutdown;
    private static Activity qtTerminalShutdownOwner;
    private static boolean qtTerminalExecutionStarted;
    private static boolean qtTerminalProcessExitStarted;

    /**
     * The Qt delegate supplies its own terminal action after Android destruction.
     * Do not terminate Qt while an engine can still be committing or releasing.
     * This process remains closed to new Qt/game owners until it actually exits.
     */
    public static boolean requestQtTerminalShutdown(Activity owner, Runnable terminal) {
        if (!isMainQtActivity(owner)) return false;
        if (terminal == null) throw new IllegalArgumentException("Missing Qt terminal action");
        synchronized (InWindowGameHost.class) {
            if (qtTerminalShutdownRequested) return true;
            qtTerminalShutdownRequested = true;
            qtTerminalShutdownOwner = owner;
            pendingQtTerminalShutdown = terminal;
            Log.i(TAG, "Qt terminal shutdown deferred active=" + (active != null) +
                    " normal=" + RETIRING_SESSIONS.size() +
                    " destroyed=" + destroyedSessionsRetiring);
        }
        dispatchQtTerminalShutdownIfReady();
        return true;
    }

    /** Also checked before a replacement MainActivity may initialize Qt. */
    public static synchronized boolean isQtTerminalShutdownPending() {
        return qtTerminalShutdownRequested;
    }

    /** A replacement Main must not forward lifecycle calls to the retiring delegate. */
    public static synchronized boolean shouldSkipQtDelegate(Activity activity) {
        return qtTerminalShutdownRequested && activity != qtTerminalShutdownOwner &&
                isMainQtActivity(activity);
    }

    private static boolean isMainQtActivity(Activity activity) {
        return activity != null && "org.pegasus_frontend.android.MainActivity".equals(
                activity.getClass().getName());
    }

    private static void dispatchQtTerminalShutdownIfReady() {
        final Runnable terminal;
        synchronized (InWindowGameHost.class) {
            if (pendingQtTerminalShutdown == null || active != null ||
                    destroyedSessionsRetiring != 0 || !RETIRING_SESSIONS.isEmpty()) return;
            terminal = pendingQtTerminalShutdown;
            pendingQtTerminalShutdown = null;
        }
        // Always enqueue: even an already-idle process must first return from
        // Android onDestroy. Neither Qt nor its thread join runs under our lock.
        new Handler(Looper.getMainLooper()).post(() -> {
            synchronized (InWindowGameHost.class) {
                if (!qtTerminalShutdownRequested || active != null ||
                        destroyedSessionsRetiring != 0 || !RETIRING_SESSIONS.isEmpty()) {
                    Log.e(TAG, "Qt terminal callback found pending native work; retaining process", null);
                    return;
                }
                try {
                    // The pinned Qt Android plugin otherwise calls libc exit
                    // from startQtApplication before Java's thread join returns.
                    // Keep Qt's ordinary cleanup, but let our acknowledged
                    // terminal endpoint retire whole preloaded emulator DSOs.
                    android.system.Os.setenv("QT_ANDROID_NO_EXIT_CALL", "1", true);
                } catch (Exception failure) {
                    Log.e(TAG, "Cannot disable unsafe Qt native exit; retaining process", failure);
                    return;
                }
                qtTerminalExecutionStarted = true;
            }
            Log.i(TAG, "Tracked retirements drained; executing deferred Qt terminal shutdown");
            terminal.run();
        });
    }

    /** Called only by the captured Qt delegate after its original terminal cleanup/join. */
    public static boolean finishQtTerminalProcess(Activity owner, Thread qtThread) {
        synchronized (InWindowGameHost.class) {
            if (!qtTerminalShutdownRequested || owner != qtTerminalShutdownOwner ||
                    !isMainQtActivity(owner)) return false;
            // Consume managed failures too: falling through to System.exit
            // would run the same unsafe process-global emulator destructors.
            if (!qtTerminalExecutionStarted || pendingQtTerminalShutdown != null ||
                    active != null || destroyedSessionsRetiring != 0 ||
                    !RETIRING_SESSIONS.isEmpty()) {
                Log.e(TAG, "Managed Qt terminal endpoint is not quiescent; retaining process", null);
                return true;
            }
            // QtThread.exit() catches InterruptedException from join(). Check
            // its captured backing thread rather than treating return as proof
            // that Qt's native main and frontend cleanup actually finished.
            if (qtThread == null || qtThread.isAlive()) {
                Log.e(TAG, "Managed Qt terminal thread has not completed; retaining process", null);
                return true;
            }
            if (qtTerminalProcessExitStarted) return true;
            qtTerminalProcessExitStarted = true;
        }
        Log.i(TAG, "Qt terminal thread completed; terminating retired Main process " +
                "without process-global emulator destructors");
        android.os.Process.killProcess(android.os.Process.myPid());
        return true;
    }

    private static final class RecreationState {
        Intent pending;
        String originalIntent;
        boolean suppressStart;
        boolean resumed;
    }

    /** Android owns this small request record; no last-game preference or state bytes. */
    public static synchronized void onCreate(Activity activity, Bundle savedState) {
        RecreationState state = new RecreationState();
        Intent incoming = activity.getIntent();
        state.originalIntent = launchIntentIdentity(incoming);
        RECREATIONS.put(activity, state);
        if (savedState == null) return;
        // An explicit inactive record also suppresses an old task's launch intent.
        state.suppressStart = true;
        try {
            if (!savedState.containsKey(RECREATION_STATE)) {
                state.suppressStart = false;
                return;
            }
            Bundle record = savedState.getBundle(RECREATION_STATE);
            if (record == null) return;
            String original = record.getString("originalIntent", "");
            Intent pending = record.getParcelable("request");
            if (pending != null && ACTION_LAUNCH.equals(pending.getAction()))
                state.pending = new Intent(pending);
            // A genuinely new initial game request wins over an older saved game.
            // The original task intent, including after normal Exit, does not.
            if (incoming != null && ACTION_LAUNCH.equals(incoming.getAction()) &&
                    !state.originalIntent.equals(original)) {
                state.pending = new Intent(incoming);
            } else {
                state.originalIntent = original;
            }
        } catch (RuntimeException malformed) {
            state.pending = null;
            Log.w(TAG, "Discarded invalid activity recreation request", malformed);
        }
    }

    public static synchronized void onSaveInstanceState(Activity activity, Bundle out) {
        if (out == null) return;
        RecreationState state = RECREATIONS.get(activity);
        Bundle record = new Bundle();
        Intent original = activity.getIntent();
        record.putString("originalIntent", state != null ? state.originalIntent :
                launchIntentIdentity(original));
        Intent pending = state == null ? null : state.pending;
        if (active != null && active.activity == activity) {
            pending = !active.exitStarted.get() && !active.libraryReturned &&
                    !active.fatalErrorVisible ? recreationIntent(active.request) : null;
        }
        if (pending != null) record.putParcelable("request", new Intent(pending));
        // Always write the inactive marker too; never replay a closed game's task intent.
        out.putBundle(RECREATION_STATE, record);
    }

    public static synchronized void onStart(Activity activity) {
        RecreationState state = RECREATIONS.get(activity);
        if (state == null || !state.suppressStart) handleIntent(activity, activity.getIntent());
    }

    private static String launchIntentIdentity(Intent intent) {
        if (intent == null) return "";
        StringBuilder identity = new StringBuilder(clean(intent.getAction()));
        // Ignore task flags/categories, which Android may change during recreation.
        for (String key : new String[] { "path", "engine_id", "system_id", "system",
                "game_id", "qualification_session" }) {
            String value = clean(intent.getStringExtra(key));
            identity.append('|').append(value.length()).append(':').append(value);
        }
        return identity.append('|').append(
                intent.getBooleanExtra("qualification_only", false)).toString();
    }

    private static Intent recreationIntent(GameLaunchRequest request) {
        Intent intent = new Intent(ACTION_LAUNCH)
                .putExtra("path", request.contentUri.getQueryParameter("path"))
                .putExtra("engine_id", request.engineId)
                .putExtra("system_id", request.systemId)
                .putExtra("game_id", request.gameId)
                .putExtra("title", request.gameTitle);
        if (!request.qualificationSession.isEmpty()) {
            intent.putExtra("qualification_only", true);
            intent.putExtra("qualification_session", request.qualificationSession);
        }
        request.returnState.putInto(intent);
        return intent;
    }

    private static synchronized void clearPendingRecreation(Activity activity) {
        RecreationState state = RECREATIONS.get(activity);
        if (state != null) {
            state.pending = null;
            state.suppressStart = true;
        }
    }

    private static void restorePendingRecreation(Activity activity) {
        RecreationState state = RECREATIONS.get(activity);
        if (state == null || state.pending == null || !state.resumed ||
                activity.isFinishing() || activity.isDestroyed() || active != null ||
                destroyedSessionsRetiring != 0 || !RETIRING_SESSIONS.isEmpty() ||
                qtTerminalShutdownRequested ||
                cleanFrontendRestartPending || importFrontendRestartPending) return;
        try {
            PowerManager power = (PowerManager) activity.getSystemService(Context.POWER_SERVICE);
            if (power == null || !power.isInteractive()) return;
        } catch (RuntimeException unavailable) {
            return;
        }
        Intent pending = state.pending;
        state.pending = null; // Consume before validation/attachment, including failure.
        Log.i(TAG, "Restoring active game from Android activity saved state");
        handleIntent(activity, pending);
    }

    private static synchronized void restorePendingRecreations() {
        for (Activity activity : new ArrayList<>(RECREATIONS.keySet()))
            restorePendingRecreation(activity);
    }
    /**
     * Sessions that are committing an exit checkpoint after the library has
     * already been restored.  The strong process-local ownership prevents a
     * session (and its native core) from being collected while its serialized
     * state is being atomically published.  Android process death remains
     * safe: the state vault never replaces the last verified snapshot until
     * the new file and metadata have both committed.
     */
    private static final Set<EngineSession> RETIRING_SESSIONS =
            Collections.synchronizedSet(Collections.newSetFromMap(
                    new IdentityHashMap<EngineSession, Boolean>()));
    private static final ExecutorService RETIREMENT_RELEASES =
            Executors.newSingleThreadExecutor(runnable -> {
                Thread thread = new Thread(runnable, "LucentEngineRetirement");
                thread.setDaemon(true);
                return thread;
            });
    /** Blocks a second launch while the aPS3e process-lifetime owner retires. */
    private static boolean cleanFrontendRestartPending;
    private static Intent pendingCleanFrontendLaunch;
    /** Import reload has reserved this process; do not start a new guest in it. */
    private static boolean importFrontendRestartPending;

    private final Activity activity;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final AtomicBoolean exitStarted = new AtomicBoolean(false);
    private final GameLaunchRequest request;
    private final ViewGroup content;
    private final List<View> libraryViews = new ArrayList<>();
    private final List<Integer> libraryVisibility = new ArrayList<>();
    private final List<Button> pauseButtons = new ArrayList<>();
    private Button primaryScreenButton;
    private final List<Button> cheatButtons = new ArrayList<>();
    /** Global index represented by cheatButtons[0]; huge databases are paged. */
    private int cheatRowsFirstIndex = -1;
    /** One selection, drawn either in this window or on the lower display. */
    private final CheatPanelModel cheatModel = new CheatPanelModel();
    private EngineSession session;
    private FrameLayout root;
    /** Real SurfaceFlinger gameplay layer; see {@link #buildUi()}. */
    private View gameSurface;
    /**
     * Opaque black held over a {@link GameSurfaceView} until the engine's first
     * frame. That layer punches a transparent hole through this window, and
     * before the engine publishes a buffer the hole shows the still-attached Qt
     * library rather than the neutral black a launch should look like. Null on
     * the TextureView route, which never punches anything.
     */
    private View launchCurtain;
    /** Delayed-only feedback; fast launches reach a frame before it appears. */
    private ProgressBar launchSpinner;
    private final Runnable revealLaunchSpinner = () -> {
        if (launchCurtain != null && launchSpinner != null)
            launchSpinner.setVisibility(View.VISIBLE);
    };
    private TouchControlsView touchControls;
    private FrameLayout pauseOverlay;
    private FrameLayout cheatOverlay;
    /**
     * Built lazily -- only the first time the pause menu's "Multiplayer" row
     * is pressed -- unlike pauseOverlay/cheatOverlay above, which every
     * launch needs. Most sessions never touch multiplayer at all
     * (MultiplayerConfig.isConfigured is false by default), so there is no
     * reason to pay for a status-polling overlay on every single launch.
     * Once built it stays attached to {@link #root} for the rest of this
     * session so its countdown chip can keep ticking, and stay visible,
     * for as long as the game runs -- not only while this menu is open.
     */
    private MultiplayerOverlay multiplayerOverlay;
    private LinearLayout cheatRows;
    private TextView cheatDetail;
    private TextView status;
    /** Owner-visible frame-generation badge: source, target, delivered, backend. */
    private TextView frameRateBadge;
    private Button restoreButton;
    private Button cheatsButton;
    private boolean prepared;
    private boolean presentationRecoveryAttempted;
    private boolean presentationRecoveryPending;
    private boolean ownerRequestedDirect;
    /** Loading alone must not pin a stalled launch on an OLED indefinitely. */
    private boolean gameplayPresented;
    private boolean resumed = true;
    /**
     * True only while the current gameplay Surface belongs to this visible
     * Activity generation.  A Surface can continue to report isValid() after
     * Android has abandoned its BufferQueue during lid sleep, so validity alone
     * must never authorize an engine resume.
     */
    private boolean surfaceAvailable;
    private boolean menuVisible;
    private boolean cheatsVisible;
    /** True while the cheats are on the Thor's lower display instead of here. */
    private boolean cheatsOnSecondDisplay;
    /** Remembers whether closing the cheats should land back on the pause menu. */
    private boolean cheatsFromPauseMenu;
    /** L1 was spent opening or closing the cheats; its release is not the game's. */
    private boolean cheatChordArmed;
    private boolean stopPressed;
    private boolean stopHoldTriggered;
    private boolean startPressed;
    // Start reaches the game immediately when it is pressed on its own, so the
    // combo has to be able to take that press back. Both facts are needed:
    // whether the game currently sees Start down, and the event that put it
    // there (a synthetic release must carry the same device to be routed).
    private boolean startDeliveredToGame;
    /** A real Start-down was withheld because Select was already held. */
    private boolean startWithheldForCombo;
    private KeyEvent startDownEvent;
    private boolean comboConsumedSelect;
    private boolean comboConsumedStart;
    private boolean fatalErrorVisible;
    private final PrivateDiagnosticsSession privateDiagnostics;
    private volatile boolean libraryReturned;
    private volatile EngineSession retiringSession;
    private EngineSession switchingSession;
    private AtomicBoolean switchingStopCompleted;
    private EngineSession.Completion switchingCompletion;
    private final AtomicBoolean cleanFrontendRestartStarted = new AtomicBoolean(false);
    private int pauseSelection;
    private long stopGeneration;
    private long resetGeneration;

    private InWindowGameHost(Activity activity, GameLaunchRequest request,
            ViewGroup content) {
        this.activity = activity;
        this.request = request;
        this.content = content;
        privateDiagnostics = PrivateDiagnostics.session(activity, request.systemId);
    }

    /** Consumes a EmuFusion game intent and overlays gameplay in this Activity. */
    public static synchronized boolean handleIntent(Activity activity, Intent source) {
        if (activity == null || source == null ||
                !ACTION_LAUNCH.equals(source.getAction())) return false;
        clearPendingRecreation(activity);
        if (qtTerminalShutdownRequested) {
            Log.w(TAG, "Ignored launch while Qt terminal shutdown is pending");
            return true;
        }
        GameLaunchRequest request = requestFrom(activity, source);
        if (request == null) {
            Log.e(TAG, "Rejected incomplete or unsafe in-window launch");
            return true;
        }
        if (cleanFrontendRestartPending || importFrontendRestartPending) {
            if (cleanFrontendRestartPending)
                pendingCleanFrontendLaunch = recreationIntent(request);
            Log.w(TAG, "Ignored launch while clean frontend restart is pending");
            return true;
        }
        // Own the Activity's decor, not android.R.id.content. The latter is
        // inset to 1920x1025 on the Thor even after bars are hidden, which
        // gives hardware cores a clipped/non-native render target. The decor
        // remains the same single Android Window but exposes the full
        // 1920x1080 top display.
        View contentView = activity.getWindow().getDecorView();
        if (!(contentView instanceof ViewGroup)) {
            Log.e(TAG, "Lucent content root is not a ViewGroup");
            return true;
        }
        InWindowGameHost previous = active;
        // A prior Activity's asynchronous teardown must finish before its
        // successor starts another core, even when the launch identity matches.
        if ((previous != null && previous.activity != activity) ||
                destroyedSessionsRetiring != 0 || !RETIRING_SESSIONS.isEmpty()) {
            RecreationState state = RECREATIONS.get(activity);
            if (state != null) state.pending = recreationIntent(request);
            return true;
        }
        if (previous != null && previous.sameRequest(request)) return true;
        if (previous != null) previous.replaceWith(request);
        else {
            active = new InWindowGameHost(activity, request, (ViewGroup) contentView);
            active.attach();
        }
        return true;
    }

    /**
     * Keys the platform owns and a game must never swallow.
     *
     * <p>A session consumes any key that resolves to a control on a device it
     * recognises as a gamepad, and on handhelds the volume rocker often
     * enumerates through exactly such a device. The reported symptom was
     * precise: tapping volume did nothing while press-and-hold worked, because
     * the discrete press was being consumed and only the platform's long-press
     * repeat path still reached AudioManager. These are checked before any
     * resolution runs, so no remap, device quirk or engine can capture them.
     */
    /**
     * Applies a hardware volume press to STREAM_MUSIC and reports that the key
     * was ours to consume.
     *
     * <p>Everything audible in this process plays on STREAM_MUSIC -- engine
     * output, preview video and menu sounds alike -- so one stream is the whole
     * answer. The adjustment runs on ACTION_DOWN including auto-repeats, so a
     * tap moves one step and a held button ramps at the platform's own repeat
     * rate. ACTION_UP is consumed silently so nothing downstream sees a
     * half-delivered key.
     */

    private static boolean isPlatformOwnedKey(KeyEvent event) {
        switch (event.getKeyCode()) {
            case KeyEvent.KEYCODE_VOLUME_UP:
            case KeyEvent.KEYCODE_VOLUME_DOWN:
            case KeyEvent.KEYCODE_VOLUME_MUTE:
            case KeyEvent.KEYCODE_POWER:
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
            case KeyEvent.KEYCODE_MEDIA_PLAY:
            case KeyEvent.KEYCODE_MEDIA_PAUSE:
            case KeyEvent.KEYCODE_MEDIA_NEXT:
            case KeyEvent.KEYCODE_MEDIA_PREVIOUS:
            case KeyEvent.KEYCODE_HEADSETHOOK:
                return true;
            default:
                return false;
        }
    }

    public static synchronized boolean dispatchKeyEvent(Activity activity, KeyEvent event) {
        // Qt does not propagate an unaccepted QML volume event back into
        // Activity's platform default path on this device. Handle it before Qt
        // and mirror the resulting STREAM_MUSIC curve to active Thor sinks.
        // Both DOWN and UP are consumed; exactly one adjustment occurs per
        // DOWN, including the platform's normal long-press repeat events.
        if (AppVolumeController.handleKeyEvent(activity, event)) return true;
        if (event != null && isPlatformOwnedKey(event)) return false;
        if (active != null)
            return active.activity == activity && active.handleKeyEvent(event);
        // No session exists at all, so the press belongs to the library UI.
        // This is the one place every hardware key in the app passes through
        // (MainActivity.dispatchKeyEvent is patched to call it first), which
        // makes it the only hook that can sound menu navigation with no chance
        // of sounding over a running game. The event is not consumed: Qt still
        // receives it and performs the navigation.
        MenuSoundPlayer.playForKey(activity, event);
        return false;
    }

    public static synchronized boolean dispatchGenericMotionEvent(
            Activity activity, MotionEvent event) {
        return active != null && active.activity == activity &&
                active.handleMotionEvent(event);
    }

    public static synchronized boolean onBackPressed(Activity activity) {
        if (active == null || active.activity != activity) return false;
        if (active.fatalErrorVisible) active.exitToLibrary("fatal-back-callback");
        else if (active.cheatsVisible) active.hideCheatsPanel();
        else if (active.menuVisible) active.hidePauseMenu();
        else active.showPauseMenu();
        return true;
    }

    public static synchronized void onResume(Activity activity) {
        RecreationState state = RECREATIONS.get(activity);
        if (state != null) state.resumed = true;
        restorePendingRecreation(activity);
        if (active == null || active.activity != activity) return;
        active.resumed = true;
        // The Qt library stays lifecycle-warm behind the in-window overlay.
        // Explicitly pausing/resuming Qt rebuilds QML and exposes Pegasus's
        // progress splash during return, destroying exact navigation state.
        // Its Android view remains VISIBLE underneath EmuFusion's opaque gameplay
        // root. INVISIBLE destroys/recreates Qt's Android SurfaceView on this
        // Thor firmware and exposes the progress splash on return.
        active.enterImmersiveMode();
        // We deliberately hid only the gameplay layer on background entry.
        // SurfaceView creates a fresh queue asynchronously after visibility is
        // restored. TextureView is different: on this Thor it can retain the
        // same available SurfaceTexture across screen-off and therefore emits
        // no second availability callback. Re-registering the listener is the
        // common, idempotent handshake: GameSurface immediately returns its
        // retained valid Surface, while GameSurfaceView waits for surfaceChanged.
        if (active.gameSurface != null) {
            active.gameSurface.setVisibility(View.VISIBLE);
            active.attachSurfaceListener();
        }
        if (active.prepared && !active.menuVisible && !active.fatalErrorVisible &&
                active.session != null && active.surfaceAvailable)
            active.session.resume();
        active.updateGameplayScreenOn();
    }

    public static synchronized void onPause(Activity activity) {
        RecreationState state = RECREATIONS.get(activity);
        if (state != null) state.resumed = false;
        if (active == null || active.activity != activity) return;
        active.resumed = false;
        if (active.touchControls != null) active.touchControls.releaseTouches();
        active.updateGameplayScreenOn();
        EngineSession current = active.session;
        if (active.prepared && current != null) {
            current.pause(EngineSession.PauseReason.ANDROID_BACKGROUND);
            // Stop every render owner before Android can abandon its queue.
            // Native/Vulkan sessions need a bounded barrier; the remaining
            // engines detach synchronously by assignment.
            active.detachCurrentSurface(current);
        }
        active.surfaceAvailable = false;
        // Force Android to retire the gameplay Surface while the app is in the
        // background.  This guarantees a new callback/queue on lid-open rather
        // than trusting Surface.isValid() on an abandoned BLAST queue.
        if (active.gameSurface != null)
            active.gameSurface.setVisibility(View.INVISIBLE);
    }

    public static synchronized void onDestroy(Activity activity) {
        RECREATIONS.remove(activity);
        if (active == null || active.activity != activity) return;
        InWindowGameHost ending = active;
        active = null;
        if (ending.session != null) destroyedSessionsRetiring++;
        ending.destroyNow();
        dispatchQtTerminalShutdownIfReady();
    }

    public static synchronized boolean isActive(Activity activity) {
        return active != null && active.activity == activity;
    }

    /** Atomic with handleIntent: library visibility does not imply save completion. */
    public static synchronized boolean tryBeginImportFrontendRestart() {
        if (active != null || !RETIRING_SESSIONS.isEmpty() || destroyedSessionsRetiring != 0 ||
                qtTerminalShutdownRequested ||
                cleanFrontendRestartPending || importFrontendRestartPending) return false;
        importFrontendRestartPending = true;
        return true;
    }

    /** Only used when the bridge could not be started; the current process stays usable. */
    public static synchronized void cancelImportFrontendRestart() {
        importFrontendRestartPending = false;
    }

    // Confine ROMs to real public storage volumes and reject app-private or
    // system paths. Retro handhelds keep their library on a removable SD card
    // mounted at /storage/<VOLUME>/ (e.g. /storage/6B6F-F576/...), so those
    // volumes must be allowed alongside internal storage and the raw mount.
    private static boolean isAllowedRomRoot(String canonical) {
        if (canonical == null) return false;
        if (canonical.startsWith("/storage/emulated/") ||
                canonical.startsWith("/storage/self/primary/") ||
                canonical.startsWith("/mnt/media_rw/")) return true;
        // A removable volume label is /storage/<id>/... where <id> is not the
        // internal "emulated"/"self" namespace (FAT/exFAT looks like 6B6F-F576;
        // ext volumes use a longer UUID). Require a non-empty first segment and
        // at least one path element beneath it.
        if (!canonical.startsWith("/storage/")) return false;
        String rest = canonical.substring("/storage/".length());
        int slash = rest.indexOf('/');
        if (slash <= 0 || slash == rest.length() - 1) return false;
        String volume = rest.substring(0, slash);
        return !volume.equals("emulated") && !volume.equals("self") &&
                !volume.contains("..");
    }

    private static GameLaunchRequest requestFrom(Activity activity, Intent source) {
        String path = clean(source.getStringExtra("path"));
        String system = clean(source.getStringExtra("system_id"));
        if (system.isEmpty()) system = clean(source.getStringExtra("system"));
        // Library metadata may carry a frontend alias ("gc", "n3ds", "ds")
        // rather than the engine-facing canonical id. Resolve it here so an
        // alias never fails closed as an unpackaged engine route.
        if (!system.isEmpty())
            system = EngineSystemIdResolver.canonical(system);
        String engine = clean(source.getStringExtra("engine_id"));
        if (engine.isEmpty() && !system.isEmpty()) {
            InternalEngineCatalog.Entry entry =
                    InternalEngineCatalog.availableForSystem(activity, system);
            if (entry != null) engine = entry.id;
            else engine = Phase2QualificationCatalog.libraryEngineIdForSystem(
                    activity, system);
        }
        if (path.isEmpty() || engine.isEmpty() || system.isEmpty()) return null;
        // External metadata survives APK replacement. Never trust its stale
        // engine_id merely because it targets EmuFusion: the signed catalog must
        // resolve that exact id/system to a core physically present in this
        // installed APK (including artifact hash verification). This prevents
        // a menu A press from entering an unavailable-engine fatal overlay.
        InternalEngineCatalog.Entry phaseOne =
                InternalEngineCatalog.byId(activity, engine);
        Phase2QualificationCatalog.Entry phaseTwo =
                Phase2QualificationCatalog.byId(activity, engine);
        boolean qualificationOnly = source.getBooleanExtra("qualification_only", false);
        boolean approvedPhaseOne = phaseOne != null && phaseOne.supports(system);
        boolean approvedPhaseTwo = phaseTwo != null && phaseTwo.supports(system) &&
                (qualificationOnly || engine.equals(
                        Phase2QualificationCatalog.libraryEngineIdForSystem(
                                activity, system)));
        // Phase 3 in-process native adapters are gated by their own catalog,
        // which applies the same fail-closed rule: the adapter must be bundled
        // in this APK and hash-match its signed manifest before it resolves.
        NativeAdapterCatalog.Entry phaseThree =
                NativeAdapterCatalog.byId(activity, engine);
        boolean approvedPhaseThree = phaseThree != null && phaseThree.supports(system) &&
                engine.equals(NativeAdapterCatalog.libraryEngineIdForSystem(
                        activity, system));
        if (!approvedPhaseOne && !approvedPhaseTwo && !approvedPhaseThree) {
            Log.e(TAG, "Rejected stale/unpackaged engine route engine=" + engine +
                    " system=" + system);
            return null;
        }
        File file;
        try {
            file = new File(path).getCanonicalFile();
        } catch (IOException error) {
            return null;
        }
        String canonical = file.getPath();
        if (!file.isFile() || !isAllowedRomRoot(canonical)) return null;
        Uri uri = new Uri.Builder().scheme("content").authority(AUTHORITY)
                .appendPath("rom").appendPath(file.getName())
                .appendQueryParameter("path", canonical).build();
        String gameId = clean(source.getStringExtra("game_id"));
        if (gameId.isEmpty()) gameId = canonical;
        String title = clean(source.getStringExtra("title"));
        if (title.isEmpty()) title = title(file);
        String qualificationSession = "";
        if (qualificationOnly) {
            String candidate = clean(source.getStringExtra("qualification_session"));
            // Save isolation is independent of frame generation: normal Off
            // gameplay must be testable without touching player saves. Honor
            // a namespace only for an explicitly marked QA launch of an
            // approved core. Ordinary launches still reject this extra.
            boolean phaseTwoNamespace = phaseTwo != null && phaseTwo.supports(system);
            boolean phaseOneNamespace = approvedPhaseOne;
            // Audited native routes separate guest system trees and wrapper
            // snapshots. Eden additionally pins one storage root per process.
            boolean nativeNamespace = approvedPhaseThree &&
                    com.thorium.lucent.emulators.NativeQualificationStorage.supports(engine, system);
            if ((!phaseTwoNamespace && !phaseOneNamespace && !nativeNamespace) ||
                    !QUALIFICATION_SESSION.matcher(candidate).matches()) return null;
            qualificationSession = candidate;
        } else if (!clean(source.getStringExtra("qualification_session")).isEmpty()) {
            // Never silently accept a namespace without the explicit QA
            // marker: reject it instead of altering production state routing.
            return null;
        }
        FrameGenerationSettings.Mode launchMode =
                FrameGenerationSettings.mode(activity);
        GameLaunchRequest request = new GameLaunchRequest(engine, system, gameId,
                title, uri, SessionReturnState.from(source), qualificationSession,
                launchMode);
        return request.isValid() ? request : null;
    }

    /**
     * Tells the companion service what the window is now showing.
     *
     * <p>Never lets that kill the app. Android 12+ refuses a service start when
     * it considers the uid idle, and it does so with an unchecked exception:
     * the ACTION_GAMEPLAY start in attach() was killing the process outright
     * the moment a game launched, and the ACTION_LIBRARY start could do the
     * same on the way back. Both are advisory -- the companion only uses them
     * to blank the lower display and to release preview state -- so a refusal
     * must degrade to a stale lower display, never to a dead game.
     */
    private void tellCompanion(String action) {
        try {
            activity.startService(new Intent(activity, PreviewService.class)
                    .setAction(action));
        } catch (IllegalStateException refused) {
            Log.w(TAG, "Companion not told about " + action + ": " +
                    refused.getMessage());
        }
    }

    private void attach() {
        tellCompanion(PreviewService.ACTION_GAMEPLAY);
        for (int index = 0; index < content.getChildCount(); index++) {
            View child = content.getChildAt(index);
            libraryViews.add(child);
            libraryVisibility.add(child.getVisibility());
            // Keep the Qt SurfaceView attached, visible, and lifecycle-warm.
            // The opaque gameplay Surface covers it without rebuilding QML.
        }
        // Created before the views: which kind of video surface this game gets
        // is a property of its engine, and EngineSessionRegistry.create is a
        // map lookup plus a constructor -- it neither loads content nor touches
        // the adapter.
        session = EngineSessionRegistry.create(activity, request);
        buildUi();
        content.addView(root, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        root.bringToFront();
        enterImmersiveMode();
        attachSurfaceListener();
        session.prepare(request, this);
        Log.i(TAG, "In-window route accepted engine=" + request.engineId +
                " system=" + request.systemId + " activity=" +
                activity.getClass().getName());
    }

    private boolean sameRequest(GameLaunchRequest other) {
        return request.engineId.equals(other.engineId) &&
                request.systemId.equals(other.systemId) &&
                request.gameId.equals(other.gameId) &&
                request.contentUri.equals(other.contentUri) &&
                request.qualificationSession.equals(other.qualificationSession);
    }

    /** Un-publishes a torn-down session from ActiveEngineSessionRegistry, if it was the published one. */
    private static void clearActiveNetplaySession(EngineSession ending) {
        if (ending instanceof com.thorium.lucent.netplay.NetplayCapableSession ||
                ending instanceof com.thorium.lucent.netplay.NativeAdapterCapableSession) {
            com.thorium.lucent.netplay.ActiveEngineSessionRegistry.clearIfCurrent(ending);
        }
    }

    private void replaceWith(GameLaunchRequest next) {
        if (exitStarted.get()) return;
        exitStarted.set(true);
        updateGameplayScreenOn();
        // The incoming game brings its own cheats; the outgoing one's list must
        // leave the lower display before it does.
        hideCheatsPanel();
        EngineSession ending = session;
        session = null;
        switchingSession = ending;
        clearActiveNetplaySession(ending);
        if (ending != null) {
            RETIRING_SESSIONS.add(ending);
            try {
                // Pause the render owner while the outgoing game's surface is
                // still valid, exactly as exitToLibrary does; the stop below
                // then serializes against a quiesced renderer.
                ending.quiesceForExit();
            } catch (RuntimeException failure) {
                Log.w(TAG, "Switch-time render quiescence failed", failure);
            }
        }
        AtomicBoolean switchCompleted = new AtomicBoolean(false);
        switchingStopCompleted = switchCompleted;
        EngineSession.Completion switchGame = () -> {
            if (!switchCompleted.compareAndSet(false, true)) return;
            Runnable released = () -> {
                if (ending != null) RETIRING_SESSIONS.remove(ending);
                activity.runOnUiThread(() -> {
                    detachViews();
                    synchronized (InWindowGameHost.class) {
                        switchingSession = null;
                        switchingCompletion = null;
                        if (qtTerminalShutdownRequested || active != this ||
                                activity.isFinishing() || activity.isDestroyed()) return;
                        // A fresh launch received while release was pending wins.
                        RecreationState state = RECREATIONS.get(activity);
                        Intent launch = state != null && state.pending != null
                                ? state.pending : recreationIntent(next);
                        active = null;
                        if (requiresCleanFrontendRestart()) {
                            cleanFrontendRestartPending = true;
                            beginCleanFrontendRestart(launch);
                        } else handleIntent(activity, launch);
                    }
                });
                mainHandler.post(InWindowGameHost::restorePendingRecreations);
                dispatchQtTerminalShutdownIfReady();
            };
            if (ending == null) released.run();
            else releaseSessionWhenComplete(ending, released);
        };
        switchingCompletion = switchGame;
        if (ending == null) switchGame.complete();
        else runAfterPresentationRecovery(() ->
                ending.stop(EngineSession.StopReason.EXIT_TO_LUCENT, switchGame));
    }

    private void buildUi() {
        requestNativePanelMode();
        root = new FrameLayout(activity);
        root.setBackgroundColor(Color.BLACK);
        root.setFocusable(true);
        root.setFocusableInTouchMode(true);
        // This full-window focus target is not a button. Android's default
        // keyboard highlight otherwise tints the entire game after menu input.
        root.setDefaultFocusHighlightEnabled(false);
        // Gameplay owns every touch that is not handled by an on-screen control
        // child (the phone/tablet fallback). Consuming here stops a stray tap
        // from reaching Qt's Activity-level touch dispatch behind the game,
        // which was navigating the library ("tapping skips to a new game").
        root.setClickable(true);
        root.setOnTouchListener((view, event) -> {
            if (prepared && !menuVisible && !fatalErrorVisible && !exitStarted.get() &&
                    session != null)
                session.onPrimaryTouch(event, view.getWidth(), view.getHeight());
            return true;
        });
        // Never pre-shape a game Surface from a system-wide guess. The running
        // engine owns its current title/video-mode aspect; libretro routes fit
        // the submitted frame internally and native adapters receive the full
        // physical Surface so EmuFusion cannot force or crop their viewport.
        boolean nativeAdapter = session instanceof NativeAdapterEngineSession;
        boolean strictOff = request.frameGenerationMode ==
                FrameGenerationSettings.Mode.OFF;
        if (strictOff) {
            // OFF still hands the engine the exact display Surface and creates
            // no frame-generation renderer. Use an independently latched
            // SurfaceView for that direct Surface: the legacy TextureView
            // route made every hardware-canvas post dirty/recompose the Qt
            // window and produced recurring 33 ms gameplay holds despite a
            // measured 60.00 Hz core. A dedicated layer removes HWUI/Qt from
            // the presentation clock without inserting any intermediary.
            GameSurfaceView layer = new GameSurfaceView(
                    activity, request.frameGenerationMode);
            // Software libretro already letterboxes inside its direct Canvas
            // using PresentationGeometry. Give it an opaque full-window
            // Surface so the continuously warm Qt Surface below is completely
            // occluded; shrinking the Surface itself left two live Qt strips
            // composited at 60 Hz and physical traces showed missed scans.
            layer.setDisplayAspect(0f);
            double authoritativeHz = authoritativeVideoHz(request.systemId);
            layer.setAuthoritativeSourceHz(authoritativeHz);
            layer.setDirectPresentationHz(directSurfaceCadenceHz(authoritativeHz));
            gameSurface = layer;
            Log.i(TAG, "Strict Off: direct isolated SurfaceView path engine=" +
                    request.engineId + " system=" + request.systemId);
        } else {
            // Native adapters and enabled alpha modes use this isolated
            // SurfaceFlinger layer as well.
            GameSurfaceView layer = new GameSurfaceView(
                    activity, request.frameGenerationMode);
            layer.setDisplayAspect(0f);
            double authoritativeHz = authoritativeVideoHz(request.systemId);
            layer.setAuthoritativeSourceHz(authoritativeHz);
            layer.setDirectPresentationHz(directSurfaceCadenceHz(authoritativeHz));
            gameSurface = layer;
        }
        FrameLayout.LayoutParams videoParams = match();
        videoParams.gravity = Gravity.CENTER;
        root.addView(gameSurface, videoParams);
        // Cover the still-attached library until the exact gameplay surface has
        // posted a frame. This is deliberately created for both TextureView and
        // SurfaceView routes: the transition is immediate and never exposes a
        // frozen menu. Fast launches remove it before the delayed spinner is
        // ever visible.
        launchCurtain = new View(activity);
        launchCurtain.setBackgroundColor(Color.BLACK);
        root.addView(launchCurtain, match());
        launchSpinner = new ProgressBar(activity);
        launchSpinner.setIndeterminate(true);
        launchSpinner.setVisibility(View.GONE);
        FrameLayout.LayoutParams spinnerParams = new FrameLayout.LayoutParams(
                dp(46), dp(46), Gravity.CENTER);
        root.addView(launchSpinner, spinnerParams);
        mainHandler.postDelayed(revealLaunchSpinner, 500L);
        if (gameSurface instanceof GameSurfaceView) {
            ((GameSurfaceView) gameSurface)
                    .setFirstSubmittedFrameListener(this::dismissLaunchCurtain);
        }
        if (gameSurface instanceof GameSurfaceView) {
            // A requested generator can fail its startup proof and hand the
            // engine the direct Surface instead. The renderer callback cannot
            // fire in that case, so use the engine's first actual presentation
            // as a direct-only backup. Without this, the game runs normally
            // behind a loading curtain forever after LSFG fails open.
            GameSurfaceView layer = (GameSurfaceView) gameSurface;
            session.setFirstFrameCallback(() -> {
                if (layer.usesDirectPresentation()) dismissLaunchCurtain();
            });
        } else if (nativeAdapter || strictOff) {
            session.setFirstFrameCallback(this::dismissLaunchCurtain);
            // Cemu publishes no FPS hook, so the presentation boundary is the
            // generator's first consumed producer buffer. Eden also keeps its
            // engine-speed proof, but neither adapter may expose an empty
            // Surface on a timer and turn a slow, healthy boot into black UI.
        } else if (gameSurface instanceof GameSurface) {
            ((GameSurface) gameSurface)
                    .setFirstSubmittedFrameListener(this::dismissLaunchCurtain);
        }
        // Presentation telemetry feeds OLED protection AND the owner's corner
        // badge. The badge is the product's only visible confirmation that
        // frame generation is actually running: source rate, selected target,
        // physically delivered rate, and the backend that produced it. It is
        // deliberately honest — it reports the delivered rate the timing
        // authority measured, never the aspirational target (owner directive
        // 2026-09-01: "the corner should show the normal frame rate and the
        // generated frame rate; that is my indication that it is on").
        FrameGenerationRenderer.StatsListener frameRateListener =
                (source, target, actual, qualified) ->
                mainHandler.post(() -> {
                    observeReportedOutput(actual);
                    // Delivery/GPU load must never downclock the guest. Near-native
                    // display synchronization is owned by each engine session.
                    updateFrameRateBadge(source, target, actual, qualified);
                });
        if (gameSurface instanceof GameSurfaceView)
            ((GameSurfaceView) gameSurface).setFrameRateListener(frameRateListener);
        else if (gameSurface instanceof GameSurface)
            ((GameSurface) gameSurface).setFrameRateListener(frameRateListener);
        touchControls = new TouchControlsView(activity);
        touchControls.setSystem(request.systemId);
        touchControls.setVisibility(View.GONE);
        touchControls.setListener(new TouchControlsView.Listener() {
            @Override public void onControl(CanonicalControl control, boolean pressed) {
                if (session != null && (!pressed || (prepared && resumed && !menuVisible &&
                        !fatalErrorVisible && !exitStarted.get())))
                    session.dispatchVirtualControl(control, pressed);
            }
            @Override public void onAnalog(int stick, float x, float y) {
                if (session != null && ((x == 0f && y == 0f) ||
                        (prepared && resumed && !menuVisible && !fatalErrorVisible &&
                         !exitStarted.get()))) session.dispatchVirtualAnalog(stick, x, y);
            }
        });
        root.addView(touchControls, match());
        frameRateBadge = new TextView(activity);
        frameRateBadge.setTextColor(Color.argb(0xE6, 0xFF, 0xFF, 0xFF));
        frameRateBadge.setBackgroundColor(Color.argb(0x80, 0x00, 0x00, 0x00));
        frameRateBadge.setTextSize(12f);
        frameRateBadge.setPadding(dp(8), dp(3), dp(8), dp(3));
        frameRateBadge.setVisibility(View.GONE);
        FrameLayout.LayoutParams badgeParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT,
                FrameLayout.LayoutParams.WRAP_CONTENT);
        badgeParams.gravity = Gravity.TOP | Gravity.LEFT;
        badgeParams.leftMargin = dp(10);
        badgeParams.topMargin = dp(8);
        root.addView(frameRateBadge, badgeParams);
        status = new TextView(activity);
        status.setTextColor(Color.WHITE);
        status.setTextSize(17f);
        status.setGravity(Gravity.CENTER);
        // A cold core may need a few frames before presenting its first
        // surface. Keep that transition visually neutral; never put a
        // "Preparing game" interstitial over the same-window launch.
        status.setVisibility(View.GONE);
        root.addView(status, match());
        pauseOverlay = createPauseOverlay();
        pauseOverlay.setVisibility(View.GONE);
        root.addView(pauseOverlay, match());
        // Added after the pause overlay so it sits above it: the cheats panel
        // is opened from that menu and returns to it, and the menu underneath
        // must stay put rather than be rebuilt on the way back.
        cheatOverlay = createCheatOverlay();
        cheatOverlay.setVisibility(View.GONE);
        root.addView(cheatOverlay, match());
        root.requestFocus();
    }

    /** Requests the exact native panel mode required by this launch. */
    private void requestNativePanelMode() {
        float refreshHz = 120.0f;
        if (request.frameGenerationMode == FrameGenerationSettings.Mode.OFF)
            refreshHz = DisplaySyncPolicy.directPanelRefreshHz(
                    authoritativeVideoHz(request.systemId));
        requestNativePanelMode(refreshHz);
    }

    /**
     * A Surface vote alone is insufficient on the Thor: the window mode id is
     * the app-scoped hardware request.  This changes no emulator clock and
     * creates no presentation intermediary.
     */
    private void requestNativePanelMode(float refreshHz) {
        Display display = activity.getDisplay();
        if (display == null) return;
        int selectedModeId = 0;
        for (Display.Mode mode : display.getSupportedModes()) {
            if (Math.abs(mode.getRefreshRate() - refreshHz) <= 0.25f) {
                selectedModeId = mode.getModeId();
                break;
            }
        }
        if (selectedModeId == 0) {
            Log.w(TAG, "No native " + refreshHz +
                    " Hz display mode is available display=" + display.getDisplayId());
            return;
        }
        WindowManager.LayoutParams attributes = activity.getWindow().getAttributes();
        attributes.preferredDisplayModeId = selectedModeId;
        attributes.preferredRefreshRate = refreshHz;
        activity.getWindow().setAttributes(attributes);
        Log.i(TAG, "Requested native gameplay panel mode display=" +
                display.getDisplayId() + " modeId=" + selectedModeId +
                " refreshHz=" + refreshHz);
    }

    /**
     * The window owns the physical 120 Hz mode; the direct Surface separately
     * declares the source clock so SurfaceFlinger can repeat each buffer on an
     * exact integer scan lattice. Unknown/non-uniform clocks retain a 120 Hz
     * default vote until the engine reports its real rate.
     */
    private static float directSurfaceCadenceHz(double declaredHz) {
        double synchronizedHz = DisplaySyncPolicy.synchronizedSourceHz(declaredHz);
        if (synchronizedHz >= 20.0 && synchronizedHz <= 120.0 &&
                DisplaySyncPolicy.isUniformOnThor(synchronizedHz))
            return (float) synchronizedHz;
        return 120.0f;
    }

    private FrameLayout.LayoutParams match() {
        return new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT);
    }

    /**
     * Fixed-clock legacy consoles advance one scan frame per core callback.
     * Their video clock—not whether two adjacent frames happen to contain the
     * same pixels—is authoritative. Variable-performance 3D systems remain
     * adaptive so a slow game never receives a fictional 60/120 badge.
     */
    static double authoritativeVideoHz(String systemId) {
        if (systemId == null) return 0.0;
        switch (systemId.trim().toLowerCase(Locale.US)) {
            case "nes":
            case "snes":
            case "gb":
            case "gbc":
            case "gba":
            case "mastersystem":
            case "gamegear":
            case "megadrive":
            case "sega32x":
            case "segacd":
            case "sg1000":
            case "pcengine":
            case "ngp":
            case "wonderswancolor":
            case "atari2600":
            case "atari5200":
            case "atari7800":
            case "atari800":
            case "colecovision":
            case "intellivision":
            case "odyssey2":
            case "virtualboy":
                return 60.0;
            default:
                return 0.0;
        }
    }

    /** Hands the live video surface its listener, whichever kind it is. */
    private void attachSurfaceListener() {
        if (gameSurface instanceof GameSurfaceView)
            ((GameSurfaceView) gameSurface).setListener(this);
        else if (gameSurface instanceof GameSurface)
            ((GameSurface) gameSurface).setListener(this);
    }

    /** Called off the render owner the first time the guest is advancing. */
    private void dismissLaunchCurtain() {
        mainHandler.post(() -> {
            mainHandler.removeCallbacks(revealLaunchSpinner);
            View curtain = launchCurtain;
            launchCurtain = null;
            View spinner = launchSpinner;
            launchSpinner = null;
            if (curtain == null) return;
            // A cold deep launch can present before the Qt library reports
            // ready. Its decor-level boot video otherwise covers a running
            // game until that unrelated signal (or the 20 s failsafe).
            BootVideoOverlay.finish();
            gameplayPresented = true;
            updateGameplayScreenOn();
            if (curtain.getParent() == root) root.removeView(curtain);
            if (spinner != null && spinner.getParent() == root) root.removeView(spinner);
            Log.i(TAG, "Gameplay layer presenting; launch curtain removed engine=" +
                    request.engineId + " system=" + request.systemId);
        });
    }

    private FrameLayout createPauseOverlay() {
        FrameLayout overlay = new FrameLayout(activity);
        overlay.setBackgroundColor(Color.argb(178, 0, 0, 0));
        overlay.setClickable(true);
        LinearLayout panel = new LinearLayout(activity);
        panel.setOrientation(LinearLayout.VERTICAL);
        // Fit every row on short landscape screens -- a 720px phone, and the
        // Thor's 1080px panel at 2.3x -- instead of pushing Exit below the
        // fold. Rows shrink only as far as needed; the scroller stays as the
        // fallback for anything still taller.
        int rows = "cemu".equals(request.engineId) ? 7 : 6;
        int available = activity.getResources().getDisplayMetrics().heightPixels - dp(32);
        boolean compact = dp(28 + 30) + dp(54 + 8) + rows * dp(58 + 8) > available;
        int gap = compact ? dp(6) : dp(8);
        int titleHeight = compact ? dp(40) : dp(54);
        int padTop = compact ? dp(16) : dp(28);
        int padBottom = compact ? dp(16) : dp(30);
        int rowHeight = dp(58);
        if (compact) rowHeight = Math.max(dp(40), Math.min(dp(58),
                (available - padTop - padBottom - titleHeight - gap) / rows - gap));
        float rowText = rowHeight < dp(48) ? 15f : 17f;
        panel.setPadding(dp(34), padTop, dp(34), padBottom);
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(24, 24, 29));
        background.setCornerRadius(dp(20));
        background.setStroke(dp(1), Color.argb(100, 255, 255, 255));
        panel.setBackground(background);
        TextView title = new TextView(activity);
        title.setText(request.gameTitle.isEmpty() ? "Paused" : request.gameTitle);
        title.setTextColor(Color.WHITE);
        title.setTextSize(24f);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        // Long names ("ICO(TM) and Shadow of the Colossus(TM) Collection") must
        // not wrap under the first button: shrink to one line, then ellipsize.
        title.setMaxLines(1);
        title.setEllipsize(android.text.TextUtils.TruncateAt.END);
        if (android.os.Build.VERSION.SDK_INT >= 26)
            title.setAutoSizeTextTypeUniformWithConfiguration(
                    15, 24, 1, android.util.TypedValue.COMPLEX_UNIT_SP);
        panel.addView(title, pauseRowParams(titleHeight, gap));
        Button resumeButton = menuButton("Resume");
        resumeButton.setOnClickListener(view -> hidePauseMenu());
        resumeButton.setTextSize(rowText);
        panel.addView(resumeButton, pauseRowParams(rowHeight, gap));
        pauseButtons.add(resumeButton);
        if ("cemu".equals(request.engineId)) {
            primaryScreenButton = menuButton("Switch to GamePad");
            primaryScreenButton.setEnabled(false);
            primaryScreenButton.setOnClickListener(view -> {
                if (session != null && session.switchPrimaryScreen()) hidePauseMenu();
            });
            primaryScreenButton.setTextSize(rowText);
        panel.addView(primaryScreenButton, pauseRowParams(rowHeight, gap));
            pauseButtons.add(primaryScreenButton);
        }
        Button controls = menuButton("Controls");
        controls.setOnClickListener(view -> {
            if (session == null || !session.openControls())
                explainUnavailable("Control remapping is unavailable for this core.");
        });
        controls.setTextSize(rowText);
        panel.addView(controls, pauseRowParams(rowHeight, gap));
        pauseButtons.add(controls);
        // Disabled until the engine reports what this game actually has. The
        // menu can be opened before the core finishes loading, and an entry
        // that opens an empty list is worse than one that is visibly not
        // offered yet; movePauseSelection already steps over disabled rows.
        cheatsButton = menuButton("Cheats");
        cheatsButton.setEnabled(false);
        cheatsButton.setAlpha(0.45f);
        cheatsButton.setOnClickListener(view -> showCheatsPanel());
        cheatsButton.setTextSize(rowText);
        panel.addView(cheatsButton, pauseRowParams(rowHeight, gap));
        pauseButtons.add(cheatsButton);
        restoreButton = menuButton("Restore earlier point");
        restoreButton.setEnabled(false);
        restoreButton.setAlpha(0.45f);
        restoreButton.setOnClickListener(view -> {
            if (session == null || !session.openRestoreHistory())
                explainUnavailable("No earlier restore points are available yet.");
        });
        restoreButton.setTextSize(rowText);
        panel.addView(restoreButton, pauseRowParams(rowHeight, gap));
        pauseButtons.add(restoreButton);
        Button multiplayer = menuButton("Multiplayer (Alpha)");
        multiplayer.setOnClickListener(view -> toggleMultiplayerOverlay());
        multiplayer.setTextSize(rowText);
        panel.addView(multiplayer, pauseRowParams(rowHeight, gap));
        pauseButtons.add(multiplayer);
        Button exit = menuButton("Exit to EmuFusion");
        exit.setTextColor(Color.rgb(255, 151, 151));
        exit.setOnClickListener(view -> exitToLibrary("pause-menu-exit"));
        exit.setTextSize(rowText);
        panel.addView(exit, pauseRowParams(rowHeight, gap));
        pauseButtons.add(exit);
        // A landscape phone can be shorter than the six menu rows. Keep Exit
        // reachable by touch and controller focus rather than clipping it
        // below the window (which is not apparent on the taller Thor panel).
        ScrollView scroller = new ScrollView(activity);
        scroller.setFillViewport(false);
        scroller.addView(panel, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        int availableWidth = activity.getResources().getDisplayMetrics().widthPixels - dp(32);
        FrameLayout.LayoutParams menuParams = new FrameLayout.LayoutParams(
                Math.min(dp(420), Math.max(dp(1), availableWidth)),
                ViewGroup.LayoutParams.MATCH_PARENT, Gravity.CENTER);
        menuParams.setMargins(dp(16), dp(16), dp(16), dp(16));
        overlay.addView(scroller, menuParams);
        return overlay;
    }

    /**
     * Lazily builds the multiplayer invite/schedule overlay and toggles it.
     *
     * <p>Built only on first press, unlike {@link #createPauseOverlay} and
     * {@link #createCheatOverlay} -- see {@link #multiplayerOverlay}'s own
     * field doc for why. The first press shows whatever its own immediate
     * poll finds (the pause menu is already open at this point, so that poll
     * is within {@link MultiplayerOverlay}'s pause-gated polling rule); every
     * press after that is a manual show/hide through
     * {@link MultiplayerOverlay#toggleUserHidden}.
     */
    private void toggleMultiplayerOverlay() {
        boolean firstTime = multiplayerOverlay == null;
        if (firstTime) {
            multiplayerOverlay = new MultiplayerOverlay(activity, request);
            root.addView(multiplayerOverlay, match());
        }
        multiplayerOverlay.bringToFront();
        if (firstTime) multiplayerOverlay.setPauseMenuOpen(true);
        else multiplayerOverlay.toggleUserHidden();
    }

    /**
     * The cheats sheet: one toggle row per cheat, plus a line of detail for
     * whichever row is selected.
     *
     * <p>The rows are filled in when the sheet is opened rather than here,
     * because nothing is known about the game's cheats until its core has
     * loaded the content.
     */
    private FrameLayout createCheatOverlay() {
        FrameLayout overlay = new FrameLayout(activity);
        overlay.setBackgroundColor(Color.argb(214, 0, 0, 0));
        overlay.setClickable(true);
        LinearLayout panel = new LinearLayout(activity);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(34), dp(26), dp(34), dp(24));
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(24, 24, 29));
        background.setCornerRadius(dp(20));
        background.setStroke(dp(1), Color.argb(100, 255, 255, 255));
        panel.setBackground(background);
        TextView title = new TextView(activity);
        title.setText("Cheats");
        title.setTextColor(Color.WHITE);
        title.setTextSize(24f);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        panel.addView(title, rowParams(dp(46)));
        cheatRows = new LinearLayout(activity);
        cheatRows.setOrientation(LinearLayout.VERTICAL);
        // A catalogue entry may carry more cheats than fit the panel. Scrolling
        // keeps the last row reachable; requestFocus on the selected button is
        // what brings it into view as the D-pad walks down.
        ScrollView scroller = new ScrollView(activity);
        scroller.setFillViewport(true);
        scroller.addView(cheatRows, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        LinearLayout.LayoutParams scrollParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f);
        scrollParams.topMargin = dp(6);
        panel.addView(scroller, scrollParams);
        cheatDetail = new TextView(activity);
        cheatDetail.setTextColor(Color.argb(190, 255, 255, 255));
        cheatDetail.setTextSize(14f);
        panel.addView(cheatDetail, rowParams(LinearLayout.LayoutParams.WRAP_CONTENT));
        TextView hint = new TextView(activity);
        hint.setText("A toggles  •  B or Back closes  •  " +
                "Select + L1 opens this from the game");
        hint.setTextColor(Color.argb(140, 255, 255, 255));
        hint.setTextSize(13f);
        panel.addView(hint, rowParams(LinearLayout.LayoutParams.WRAP_CONTENT));
        overlay.addView(panel, new FrameLayout.LayoutParams(dp(500), dp(430),
                Gravity.CENTER));
        return overlay;
    }

    private Button menuButton(String label) {
        Button button = new Button(activity);
        button.setFocusable(true);
        // Keep D-pad focus, but let an unfocused button activate on its first
        // touch. Touch-mode focus consumed that tap without invoking Controls.
        button.setFocusableInTouchMode(false);
        button.setAllCaps(false);
        button.setText(label);
        button.setTextSize(17f);
        button.setTextColor(Color.WHITE);
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(38, 38, 45));
        background.setCornerRadius(dp(11));
        background.setStroke(dp(1), Color.argb(90, 255, 255, 255));
        button.setBackground(background);
        button.setOnFocusChangeListener((view, focused) -> {
            GradientDrawable state = new GradientDrawable();
            state.setColor(focused ? COLOR_ACCENT : Color.rgb(38, 38, 45));
            state.setCornerRadius(dp(11));
            state.setStroke(dp(1), focused ? Color.WHITE :
                    Color.argb(90, 255, 255, 255));
            view.setBackground(state);
        });
        return button;
    }

    private LinearLayout.LayoutParams pauseRowParams(int height, int gap) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, height);
        params.topMargin = gap;
        return params;
    }

    private LinearLayout.LayoutParams rowParams(int height) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, height);
        params.topMargin = dp(8);
        return params;
    }

    private boolean handleKeyEvent(KeyEvent event) {
        // Any physical input is the user returning; the OLED guard must be
        // gone before the event reaches the game.
        clearOledGuard();
        int code = event.getKeyCode();
        if (fatalErrorVisible) {
            // The physical A-up that launched the game can arrive after an
            // asynchronous prepare failure. It must never dismiss the error
            // before QA/the user can see the real engine exception. Fatal
            // state exits only through Back/Menu or an intentional touch.
            if (event.getAction() == KeyEvent.ACTION_UP &&
                    (code == KeyEvent.KEYCODE_BACK ||
                     code == KeyEvent.KEYCODE_MENU)) {
                exitToLibrary("fatal-back-key");
            }
            return true;
        }
        if (code == KeyEvent.KEYCODE_BACK || code == KeyEvent.KEYCODE_MENU) {
            if (event.getAction() == KeyEvent.ACTION_UP) {
                // Back steps out one sheet at a time, so leaving the cheats
                // list does not also dismiss the menu it was opened from.
                if (cheatsVisible) hideCheatsPanel();
                else if (menuVisible) hidePauseMenu();
                else showPauseMenu();
            }
            return true;
        }
        if (code == KeyEvent.KEYCODE_BUTTON_SELECT ||
                code == KeyEvent.KEYCODE_MEDIA_STOP) return handleStopButton(event);
        // Ahead of the sheet handlers below, because the same chord that opens
        // the cheats has to be able to close them again.
        if (code == KeyEvent.KEYCODE_BUTTON_L1) return handleCheatsChord(event);
        if (cheatsVisible) {
            if (event.getAction() != KeyEvent.ACTION_UP) return true;
            if (code == KeyEvent.KEYCODE_DPAD_UP) moveCheatSelection(-1);
            else if (code == KeyEvent.KEYCODE_DPAD_DOWN) moveCheatSelection(1);
            else if (code == KeyEvent.KEYCODE_BUTTON_B) hideCheatsPanel();
            // A game with nothing to show must not trap the pad: on an empty
            // panel the confirm button closes it rather than toggling nothing.
            else if (code == KeyEvent.KEYCODE_ENTER ||
                    code == KeyEvent.KEYCODE_DPAD_CENTER ||
                    code == KeyEvent.KEYCODE_BUTTON_A) {
                if (cheatModel.isEmpty()) hideCheatsPanel();
                else toggleCheat(cheatModel.selectedIndex());
            }
            return true;
        }
        if (menuVisible) {
            if (event.getAction() != KeyEvent.ACTION_UP) return true;
            if (code == KeyEvent.KEYCODE_DPAD_UP) {
                movePauseSelection(-1);
                return true;
            }
            if (code == KeyEvent.KEYCODE_DPAD_DOWN) {
                movePauseSelection(1);
                return true;
            }
            if (code == KeyEvent.KEYCODE_ENTER ||
                    code == KeyEvent.KEYCODE_DPAD_CENTER ||
                    code == KeyEvent.KEYCODE_BUTTON_A) {
                if (!pauseButtons.isEmpty())
                    pauseButtons.get(pauseSelection).performClick();
                return true;
            }
            return true;
        }
        // A gamepad button is level-triggered inside every engine: the first
        // DOWN latches it and the matching UP releases it.  Android may emit
        // DOWN auto-repeats while the user keeps a button held.  Forwarding
        // those redundant edges performs input routing (and, on some vendor
        // builds, verbose logging) roughly every 50 ms on the UI thread.  Keep
        // the already-latched state and consume repeats before any engine work.
        if (event.getAction() == KeyEvent.ACTION_DOWN &&
                event.getRepeatCount() != 0) return true;
        // Only reached during live gameplay: while the pause menu is up Start
        // keeps its existing swallowed-by-the-menu behaviour above.
        if (code == KeyEvent.KEYCODE_BUTTON_START) return handleStartButton(event);
        return session != null && session.dispatchKeyEvent(event);
    }

    private boolean handleMotionEvent(MotionEvent event) {
        clearOledGuard();
        return !menuVisible && session != null &&
                session.dispatchGenericMotionEvent(event);
    }

    /**
     * In-game OLED protection with the semantics the screensaver cannot have:
     * the theme's QML screensaver renders BENEATH the gameplay view (starting
     * it under a live game is exactly the phantom 120 Hz video layer QA hit),
     * so the HOST owns burn-in protection while a game runs. A truly static
     * game screen — zero committed presentation output, meaning the source
     * stopped producing unique frames — for two continuous minutes fades in a
     * pure-black guard (zero OLED emission, stronger protection than any
     * moving video). Any input or the first new frame removes it instantly.
     */
    private static final long OLED_GUARD_STATIC_MS = 120_000L;
    private static final long GAMEPLAY_REASSERT_MS = 60_000L;
    private View oledGuard;
    private long oledStaticOutputSinceMs;
    private long lastGameplayReassertMs;

    /** The request belongs to this attached gameplay view, never the Qt window. */
    private boolean shouldKeepGameplayScreenOn() {
        return root != null && session != null && prepared && gameplayPresented &&
                resumed && surfaceAvailable && !menuVisible && !fatalErrorVisible &&
                !exitStarted.get() && !libraryReturned && oledGuard == null;
    }

    private void updateGameplayScreenOn() {
        // Surface callbacks can arrive from a renderer; view flags are UI-owned.
        if (Looper.myLooper() != Looper.getMainLooper()) {
            mainHandler.post(this::updateGameplayScreenOn);
            return;
        }
        if (root == null) return;
        boolean keepOn = shouldKeepGameplayScreenOn();
        if (root.getKeepScreenOn() == keepOn) return;
        // View-scoped KEEP_SCREEN_ON prevents idle timeout, not explicit power
        // or lid sleep. Removing this view cannot leak the request to the library.
        root.setKeepScreenOn(keepOn);
        Log.i(TAG, "Gameplay idle-sleep prevention=" + keepOn +
                " engine=" + request.engineId + " system=" + request.systemId);
    }

    /**
     * Renders the corner badge from the timing authority's committed report.
     *
     * <p>{@code S} is the sustained measured source rate, {@code T} the
     * selected panel-divisor target, {@code A} the physically delivered rate.
     * The generated rate is only claimed once cadence is qualified; until then
     * the badge shows the direct rate so a struggling backend is never
     * dressed up as smooth. Off sessions never create a renderer, so the badge
     * stays hidden there without any extra state.</p>
     */

    private void updateFrameRateBadge(double source, double target,
                                      double actual, boolean qualified) {
        TextView badge = frameRateBadge;
        if (badge != null && (ownerRequestedDirect || presentationRecoveryAttempted)) {
            badge.setVisibility(View.GONE);
            return; // queued stats from the retired generator are no longer live
        }
        if (badge == null || request == null ||
                request.frameGenerationMode == FrameGenerationSettings.Mode.OFF)
            return;
        String backend = gameSurface instanceof GameSurfaceView ?
                ((GameSurfaceView) gameSurface).activeFrameGenerationBackend() :
                "Built-in";
        boolean generating = qualified && target > source + 0.5;
        String text = generating
                ? String.format(Locale.US, "%.0f → %.0f  ·  %.1f fps  ·  %s",
                        source, target, actual, backend)
                : String.format(Locale.US, "%.0f fps  ·  direct  ·  %s",
                        source, backend);
        badge.setText(text);
        badge.setVisibility(source > 0.0 ? View.VISIBLE : View.GONE);
    }

    private void observeReportedOutput(double output) {
        long now = android.os.SystemClock.elapsedRealtime();
        // A companion service restarted mid-session (crash, low-memory kill)
        // reboots with gameplayActive=false, which let the frontend's
        // screensaver start beneath a live game (runs switch32/33,
        // 2026-08-16). Reasserting once a minute heals any restart within
        // one minute.
        if (now - lastGameplayReassertMs >= GAMEPLAY_REASSERT_MS) {
            lastGameplayReassertMs = now;
            tellCompanion(PreviewService.ACTION_GAMEPLAY);
        }
        if (output > 0.0) {
            oledStaticOutputSinceMs = 0L;
            clearOledGuard();
            return;
        }
        if (oledStaticOutputSinceMs == 0L) {
            oledStaticOutputSinceMs = now;
        } else if (oledGuard == null &&
                now - oledStaticOutputSinceMs >= OLED_GUARD_STATIC_MS) {
            View guard = new View(activity);
            guard.setBackgroundColor(Color.BLACK);
            guard.setAlpha(0f);
            guard.setOnTouchListener((view, touch) -> {
                clearOledGuard();
                return true;
            });
            root.addView(guard, match());
            guard.animate().alpha(1f).setDuration(1200L).start();
            oledGuard = guard;
            updateGameplayScreenOn();
            Log.i(TAG, "OLED guard shown after static screen ms=" +
                    (now - oledStaticOutputSinceMs));
        }
    }

    private void clearOledGuard() {
        View guard = oledGuard;
        oledGuard = null;
        oledStaticOutputSinceMs = 0L;
        if (guard != null && root != null) {
            root.removeView(guard);
            updateGameplayScreenOn();
            Log.i(TAG, "OLED guard cleared");
        }
    }

    private boolean handleStopButton(KeyEvent event) {
        if (event.getAction() == KeyEvent.ACTION_DOWN) {
            if (event.getRepeatCount() != 0) return true;
            stopPressed = true;
            stopHoldTriggered = false;
            if (startPressed) {
                // Start is already held, so this is the reset combo rather than
                // a Stop hold. Retiring the exit generation is what stops the
                // 1 s hold from exiting to the library one third of the way
                // through the 3 s combo.
                ++stopGeneration;
                releaseLeakedStartPress();
                armResetCombo();
                return true;
            }
            final long generation = ++stopGeneration;
            mainHandler.postDelayed(() -> {
                if (stopPressed && generation == stopGeneration) {
                    stopHoldTriggered = true;
                    stopPressed = false;
                    exitToLibrary("thor-stop-hold");
                }
            }, STOP_HOLD_MS);
            return true;
        }
        if (event.getAction() == KeyEvent.ACTION_UP) {
            stopPressed = false;
            ++stopGeneration;
            // Releasing either half retires any combo still counting down.
            ++resetGeneration;
            if (comboConsumedSelect) {
                // The reset already spent this press. Replaying it as a tap
                // would land Select on the game that just restarted.
                comboConsumedSelect = false;
                stopHoldTriggered = false;
                return true;
            }
            if (!stopHoldTriggered) latchTapToSession(event);
            stopHoldTriggered = false;
        }
        return true;
    }

    /**
     * Select + L1 opens and closes the cheats while the game keeps running.
     *
     * <p>Select is already EmuFusion's modifier — held alone it is Stop, held
     * with Start it is Reset — so the cheats join that family rather than
     * claiming a button of their own. Every free button on the Thor is a button
     * some console shipped with, and a bare binding would collide with a game
     * the day someone loaded the right cartridge.
     *
     * <p>Both countdowns are retired the moment the chord lands: without that,
     * the 1 s Stop hold would exit to the library one screen into browsing the
     * cheat list, and a Start still held from a half-finished reset would fire
     * two seconds later. L1 itself is withheld from the game, because a chord
     * the user meant as a menu must not also press a shoulder button in it.
     */
    private boolean handleCheatsChord(KeyEvent event) {
        boolean sheetOpen = menuVisible || cheatsVisible;
        if (event.getAction() == KeyEvent.ACTION_DOWN) {
            if (stopPressed && event.getRepeatCount() == 0) {
                ++stopGeneration;
                ++resetGeneration;
                comboConsumedSelect = true;
                stopHoldTriggered = false;
                cheatChordArmed = true;
                if (cheatsVisible) hideCheatsPanel();
                else showCheatsPanel();
                return true;
            }
            // An auto-repeat of the press the chord already spent.
            if (cheatChordArmed && event.getRepeatCount() != 0) return true;
            // A fresh press with Select released ends the chord. Clearing here
            // as well as on the release is what stops a release lost to a
            // focus change from swallowing L1 for the rest of the session.
            cheatChordArmed = false;
            return sheetOpen || deliverToSession(event);
        }
        if (event.getAction() == KeyEvent.ACTION_UP && cheatChordArmed) {
            cheatChordArmed = false;
            return true;
        }
        return sheetOpen || deliverToSession(event);
    }

    /**
     * Start behaves exactly as it always has until Select joins it.
     *
     * A press that begins while Select is already held is withheld from the
     * game, because it is a candidate for the reset combo; if the combo never
     * completes, the release replays it as a tap so the game still sees the
     * button. A press that begins on its own goes straight through and keeps
     * its hold semantics, and arming the combo afterwards takes it back with a
     * synthetic release so no Start bit is left stuck across a reset.
     */
    private boolean handleStartButton(KeyEvent event) {
        if (event.getAction() == KeyEvent.ACTION_DOWN) {
            if (event.getRepeatCount() != 0)
                return !startDeliveredToGame || deliverToSession(event);
            startPressed = true;
            startDownEvent = event;
            if (stopPressed) {
                // Select is held: withhold Start and replace the pending Stop
                // hold with the reset countdown.
                ++stopGeneration;
                startDeliveredToGame = false;
                startWithheldForCombo = true;
                armResetCombo();
                return true;
            }
            startWithheldForCombo = false;
            startDeliveredToGame = true;
            return deliverToSession(event);
        }
        if (event.getAction() == KeyEvent.ACTION_UP) {
            startPressed = false;
            ++resetGeneration;
            if (comboConsumedStart) {
                comboConsumedStart = false;
                startDeliveredToGame = false;
                startWithheldForCombo = false;
                startDownEvent = null;
                return true;
            }
            startDownEvent = null;
            if (startDeliveredToGame) {
                startDeliveredToGame = false;
                startWithheldForCombo = false;
                return deliverToSession(event);
            }
            // Held next to Select but released before the combo completed: the
            // game never saw the press, so deliver it now as a normal tap.
            if (startWithheldForCombo) latchTapToSession(event);
            // A standalone ACTION_UP has no press ownership. This occurs when
            // device QA neutralizes an already-released controller and must
            // never be promoted into a synthetic Start tap (TWINE opens its
            // watch/pause screen on Start).
            startWithheldForCombo = false;
        }
        return true;
    }

    private boolean deliverToSession(KeyEvent event) {
        return session != null && session.dispatchKeyEvent(event);
    }

    /**
     * Replays a withheld press as a tap the core can actually observe.
     *
     * Cores read buttons by polling once per retro_run, so a zero-width
     * down/up pair between two polls is invisible. Latch the synthesized press
     * across a few frame periods instead, so at least one poll sees it.
     */
    private void latchTapToSession(KeyEvent release) {
        final EngineSession target = session;
        if (target == null) return;
        final KeyEvent up = release;
        long now = release.getEventTime();
        target.dispatchKeyEvent(new KeyEvent(now, now, KeyEvent.ACTION_DOWN,
                release.getKeyCode(), 0, release.getMetaState(), release.getDeviceId(),
                release.getScanCode(), release.getFlags(), release.getSource()));
        mainHandler.postDelayed(() -> {
            // If the session changed meanwhile, drop the release: the old
            // session is retiring and a new host starts with a clean joypad
            // mask.
            if (session == target) target.dispatchKeyEvent(up);
        }, TAP_SELECT_HOLD_MS);
    }

    /**
     * Takes back a Start press the game already received. Without this, arming
     * the combo after Start went down alone would leave the joypad's Start bit
     * asserted for three seconds and across the reset itself.
     */
    private void releaseLeakedStartPress() {
        if (!startDeliveredToGame) return;
        startDeliveredToGame = false;
        EngineSession target = session;
        KeyEvent down = startDownEvent;
        if (target == null || down == null) return;
        long now = down.getEventTime();
        target.dispatchKeyEvent(new KeyEvent(down.getDownTime(), now, KeyEvent.ACTION_UP,
                down.getKeyCode(), 0, down.getMetaState(), down.getDeviceId(),
                down.getScanCode(), down.getFlags(), down.getSource()));
    }

    /**
     * Starts (or restarts) the 3 s countdown. Modelled on the Stop hold: the
     * generation counter is bumped by every release and by every re-arm, so a
     * stale callback can never fire after the buttons were let go.
     */
    private void armResetCombo() {
        final long generation = ++resetGeneration;
        mainHandler.postDelayed(() -> {
            if (generation != resetGeneration || !stopPressed || !startPressed ||
                    menuVisible || fatalErrorVisible || exitStarted.get()) return;
            fireResetCombo();
        }, RESET_COMBO_HOLD_MS);
    }

    private void fireResetCombo() {
        // Both presses belong to the combo now; neither may reach the game.
        comboConsumedSelect = true;
        comboConsumedStart = true;
        stopHoldTriggered = false;
        releaseLeakedStartPress();
        final EngineSession target = session;
        if (target == null) return;
        // reset() takes the engine's own lock and, on hardware sessions, waits
        // on the render thread. Running it here would block the UI thread for
        // as long as the core takes to power-cycle, which looked exactly like
        // the game freezing instead of resetting. Hand it to the retirement
        // executor so the combo returns immediately.
        RETIREMENT_RELEASES.execute(() -> {
            boolean applied = false;
            try {
                applied = target.reset();
            } catch (Throwable failure) {
                Log.w(TAG, "Reset combo failed engine=" + request.engineId +
                        " marker=reset-combo-failure", failure);
            }
            Log.i(TAG, "Reset combo fired engine=" + request.engineId +
                    " system=" + request.systemId + " applied=" + applied +
                    " marker=reset-combo");
        });
    }

    private void cancelResetCombo() {
        ++resetGeneration;
        releaseLeakedStartPress();
        startPressed = false;
        startWithheldForCombo = false;
        startDownEvent = null;
        comboConsumedSelect = false;
        comboConsumedStart = false;
    }

    private void showPauseMenu() {
        if (pauseOverlay == null || menuVisible || exitStarted.get()) return;
        // The menu owns the buttons from here, and their releases are consumed
        // by the menu handler above rather than reaching the combo.
        cancelResetCombo();
        if (touchControls != null) touchControls.releaseTouches();
        menuVisible = true;
        updateGameplayScreenOn();
        if (prepared && session != null)
            session.pause(EngineSession.PauseReason.LUCENT_MENU);
        if (primaryScreenButton != null) {
            boolean available = session != null && session.canSwitchPrimaryScreen();
            primaryScreenButton.setVisibility(available ? View.VISIBLE : View.GONE);
            primaryScreenButton.setEnabled(available);
            primaryScreenButton.setText(session != null && session.isGamepadOnPrimary()
                    ? "Switch to TV" : "Switch to GamePad");
        }
        pauseOverlay.setVisibility(View.VISIBLE);
        pauseSelection = 0;
        focusPauseSelection();
        // Already built only if "Multiplayer" has been pressed before this
        // pause -- see MultiplayerOverlay's pause-gated polling rule.
        if (multiplayerOverlay != null) multiplayerOverlay.setPauseMenuOpen(true);
        Log.i(TAG, "Pause menu shown engine=" + request.engineId +
                " system=" + request.systemId);
    }

    private void movePauseSelection(int direction) {
        if (pauseButtons.isEmpty()) return;
        int next = pauseSelection;
        do {
            next = (next + direction + pauseButtons.size()) % pauseButtons.size();
        } while (!pauseButtons.get(next).isEnabled() && next != pauseSelection);
        pauseSelection = next;
        focusPauseSelection();
    }

    private void focusPauseSelection() {
        if (!pauseButtons.isEmpty()) pauseButtons.get(pauseSelection).requestFocus();
    }

    /**
     * Opens the cheats, below the game where there is a screen for them.
     *
     * <p>The Thor's lower display is preferred over this window's own sheet
     * because that is the whole point of the feature: the game stays visible
     * and running while a cheat is switched, so its effect can be seen as it
     * happens. The in-window sheet is the fallback for a single-screen device
     * and for a DS/3DS/Wii U session, which is already using the lower display
     * as half of the console.
     *
     * <p>The list is rebuilt from the session on every open. A cheat's state
     * can have changed since the sheet was last closed -- from the library
     * before this launch, or from a toggle earlier in this session -- and a
     * stale row would show the wrong switch position.
     */
    private void showCheatsPanel() {
        if (cheatOverlay == null || session == null) return;
        cheatModel.load(request.gameTitle, session.availableCheats(),
                session.enabledCheatIds());
        cheatsFromPauseMenu = menuVisible;
        cheatsVisible = true;
        cheatsOnSecondDisplay = SecondaryCheatPanelRouter.request(
                activity, this, cheatModel.snapshot());
        if (!cheatsOnSecondDisplay) {
            buildCheatRows();
            cheatOverlay.setVisibility(View.VISIBLE);
            cheatOverlay.bringToFront();
            focusCheatSelection();
        }
        Log.i(TAG, "Cheats panel shown engine=" + request.engineId +
                " system=" + request.systemId + " count=" + cheatModel.size() +
                " lowerDisplay=" + cheatsOnSecondDisplay);
    }

    private void hideCheatsPanel() {
        if (!cheatsVisible) return;
        cheatsVisible = false;
        if (cheatsOnSecondDisplay) {
            cheatsOnSecondDisplay = false;
            SecondaryCheatPanelRouter.release(activity, this);
        }
        if (cheatOverlay != null) cheatOverlay.setVisibility(View.GONE);
        if (cheatsFromPauseMenu && menuVisible) {
            if (pauseOverlay != null) pauseOverlay.bringToFront();
            focusPauseSelection();
        } else if (!menuVisible && gameSurface != null) {
            // Opened live, over a game that never stopped: hand the pad back
            // without going anywhere near the pause menu's pause/resume.
            gameSurface.requestFocus();
        }
        cheatsFromPauseMenu = false;
    }

    private void buildCheatRows() {
        cheatRows.removeAllViews();
        cheatButtons.clear();
        CheatPanelSnapshot snapshot = cheatModel.snapshot();
        cheatRowsFirstIndex = snapshot.firstIndex;
        for (int index = 0; index < snapshot.rows.size(); index++) {
            final int globalRow = snapshot.firstIndex + index;
            Button button = menuButton(snapshot.rows.get(index).label());
            button.setOnClickListener(view -> toggleCheat(globalRow));
            cheatRows.addView(button, rowParams(dp(54)));
            cheatButtons.add(button);
        }
        if (!cheatModel.isEmpty()) return;
        // A game with no cheats still has to say so. Answering the chord with
        // nothing on screen reads as a dead button, and the user's next move is
        // to press it again.
        TextView nothing = new TextView(activity);
        nothing.setText(cheatModel.snapshot().message);
        nothing.setTextColor(Color.argb(200, 255, 255, 255));
        nothing.setTextSize(16f);
        nothing.setGravity(Gravity.CENTER);
        cheatRows.addView(nothing, rowParams(dp(80)));
    }

    /**
     * Applies a toggle to the running game.
     *
     * <p>The row is redrawn from the session rather than from what was asked
     * for, so a change the engine refused cannot leave a switch showing a
     * position the core is not in.
     */
    private void toggleCheat(int index) {
        Cheat cheat = cheatModel.cheatAt(index);
        if (session == null || cheat == null) return;
        cheatModel.select(index);
        if (!session.setCheatEnabled(cheat.id, !session.enabledCheatIds().contains(cheat.id))) {
            explainUnavailable("EmuFusion could not change cheats for this game.");
            return;
        }
        cheatModel.setEnabledIds(session.enabledCheatIds());
        refreshCheatUi();
    }

    /** Redraws whichever screen is currently showing the cheats. */
    private void refreshCheatUi() {
        CheatPanelSnapshot snapshot = cheatModel.snapshot();
        if (cheatsOnSecondDisplay) {
            SecondaryCheatPanelRouter.publish(this, snapshot);
            return;
        }
        if (cheatRowsFirstIndex != snapshot.firstIndex ||
                cheatButtons.size() != snapshot.rows.size()) {
            buildCheatRows();
            focusCheatSelection();
            return;
        }
        for (int index = 0; index < cheatButtons.size(); index++) {
            cheatButtons.get(index).setText(snapshot.rows.get(index).label());
        }
        focusCheatSelection();
    }

    private void moveCheatSelection(int direction) {
        if (cheatModel.isEmpty()) return;
        cheatModel.moveSelection(direction);
        refreshCheatUi();
    }

    private void focusCheatSelection() {
        // Cleared for an empty game, whose explanation is already the whole
        // list; repeating it underneath would read as two different messages.
        if (cheatDetail != null) cheatDetail.setText(
                cheatModel.isEmpty() ? "" : cheatModel.snapshot().detail());
        int selected = cheatModel.selectedIndex() - cheatRowsFirstIndex;
        if (cheatButtons.isEmpty() || selected < 0 || selected >= cheatButtons.size()) return;
        // Focus doubles as the scroll request: a row below the fold is brought
        // into view by the ScrollView when it takes focus.
        cheatButtons.get(selected).requestFocus();
    }

    /**
     * A row was touched on the lower display.
     *
     * <p>Arrives from the router on the lower display's own Activity, and is
     * bounced onto this window's UI thread before it reaches the session: the
     * pad handlers next to it all run there, and a toggle racing them would
     * read the enabled set while the other half was rewriting it.
     */
    @Override public void onSecondaryCheatToggled(int index) {
        activity.runOnUiThread(() -> {
            if (!cheatsVisible || !cheatsOnSecondDisplay) return;
            if (cheatModel.isEmpty()) hideCheatsPanel();
            else toggleCheat(index);
        });
    }

    @Override public void onSecondaryCheatPanelClosed() {
        activity.runOnUiThread(this::hideCheatsPanel);
    }

    private void hidePauseMenu() {
        if (!menuVisible) return;
        hideCheatsPanel();
        menuVisible = false;
        // Stops the status poll, not the countdown chip's own local tick --
        // see MultiplayerOverlay's pause-gated polling rule.
        if (multiplayerOverlay != null) multiplayerOverlay.setPauseMenuOpen(false);
        pauseOverlay.setVisibility(View.GONE);
        gameSurface.requestFocus();
        enterImmersiveMode();
        if (prepared && resumed && session != null) session.resume();
        updateGameplayScreenOn();
        Log.i(TAG, "Pause menu hidden engine=" + request.engineId +
                " system=" + request.systemId);
    }

    private void exitToLibrary(String reason) {
        if (!exitStarted.compareAndSet(false, true)) return;
        updateGameplayScreenOn();
        // Before anything else: the lower display must not be left holding a
        // cheat list for a game that no longer exists.
        hideCheatsPanel();
        final long returnStartedUptimeMs = android.os.SystemClock.uptimeMillis();
        Log.i(TAG, "Exit to Lucent invoked engine=" + request.engineId +
                " system=" + request.systemId + " reason=" + clean(reason),
                new Throwable("Lucent exit origin"));
        EngineSession ending = session;
        boolean renderQuiesced = ending == null;
        if (ending != null) {
            try {
                // This bounded render-thread barrier completes while the game
                // TextureView and native window are still valid. The warm Qt
                // library can then be revealed with no abandoned-buffer swap.
                ending.quiesceForExit();
                renderQuiesced = true;
            } catch (RuntimeException failure) {
                Log.w(TAG, "Exit render quiescence failed; retaining gameplay " +
                        "surface through checkpoint", failure);
            }
        }
        session = null;
        clearActiveNetplaySession(ending);
        retiringSession = ending;
        if (ending != null) RETIRING_SESSIONS.add(ending);

        // Return the existing Qt library immediately. A successful synchronous
        // quiesce proves there can be no later swap, so the SurfaceView can be
        // removed before serialization and the separately composed gameplay
        // layer cannot cover the library for the duration of the save. If the
        // bounded barrier failed, retain the Surface as the fail-closed path.
        returnToLibraryUi(returnStartedUptimeMs, renderQuiesced);
        if (ending != null && !renderQuiesced)
            mainHandler.postDelayed(() -> restartFrontendIfExitWedged(ending),
                    WEDGED_EXIT_RESTART_MS);
        if (ending != null) {
            try {
                Runnable stop = () -> {
                    try {
                        ending.stop(EngineSession.StopReason.EXIT_TO_LUCENT,
                                () -> finishRetiringSession(ending, null));
                    } catch (RuntimeException failure) {
                        finishRetiringSession(ending, failure);
                    }
                };
                // A recovery worker can still own native image references.
                // Return the library now, but order core stop after retirement.
                runAfterPresentationRecovery(stop);
            } catch (RuntimeException failure) {
                finishRetiringSession(ending, failure);
            }
        } else {
            detachViews();
        }
    }

    private void returnToLibraryUi(long returnStartedUptimeMs,
                                   boolean renderQuiesced) {
        libraryReturned = true;
        privateDiagnostics.close();
        clearPendingRecreation(activity);
        if (requiresCleanFrontendRestart()) {
            synchronized (InWindowGameHost.class) {
                cleanFrontendRestartPending = true;
            }
            // Stop normally gets here quickly after its durable-save flush. A
            // wedged adapter may not keep RPCS3 alive indefinitely: the black
            // bridge is the bounded fail-safe and kills this process owner.
            if (NativeAdapterStopPolicy.allowsForcedFrontendRestart(request.engineId))
                mainHandler.postDelayed(this::beginCleanFrontendRestart, 4000L);
        }
        // Clear the local launch intent too. The saved-instance-state inactive
        // marker is authoritative if Android recreates the original task intent.
        activity.setIntent(new Intent(Intent.ACTION_MAIN)
                .setClassName(activity,
                        "org.pegasus_frontend.android.MainActivity")
                .addCategory(Intent.CATEGORY_LAUNCHER));
        if (renderQuiesced) {
            detachViews();
            Log.i(TAG, "Library revealed after quiesced game surface detached engine=" +
                    request.engineId + " system=" + request.systemId);
        } else {
            revealLibraryOverRetiringSurface();
        }
        synchronized (InWindowGameHost.class) {
            if (active == this) active = null;
        }
        tellCompanion(PreviewService.ACTION_LIBRARY);
        long latencyMs = Math.max(0L,
                android.os.SystemClock.uptimeMillis() - returnStartedUptimeMs);
        Log.i(TAG, "Returned to Lucent immediately in same window engine=" +
                request.engineId + " system=" + request.systemId +
                " latencyMs=" + latencyMs);
    }

    private synchronized void finishRetiringSession(
            EngineSession ending, Throwable failure) {
        if (ending == null || retiringSession != ending) return;
        retiringSession = null;
        // Some stop-failure callbacks are delivered through the Activity's UI
        // listener. Native teardown and thread joins must never execute there.
        releaseSessionWhenComplete(ending, () -> {
            RETIRING_SESSIONS.remove(ending);
            mainHandler.post(() -> {
                if (requiresCleanFrontendRestart()) beginCleanFrontendRestart();
                else restorePendingRecreations();
            });
            dispatchQtTerminalShutdownIfReady();
        });
        mainHandler.post(() -> {
            detachViews();
            Log.i(TAG, "Retired game surface removed after checkpoint engine=" +
                    request.engineId + " system=" + request.systemId);
        });
        if (failure == null) {
            Log.i(TAG, "Exit checkpoint finished after library return engine=" +
                    request.engineId + " system=" + request.systemId);
        } else {
            Log.w(TAG, "Exit checkpoint failed after library return; retaining " +
                    "the previous verified Quick Resume", failure);
        }
    }

    /**
     * The retiring session is still waiting on a core frame that never
     * returned, so neither its checkpoint nor its Surface retirement can
     * finish. Replace this process through the restart bridge; nothing can be
     * saved from the wedged core, and the previous verified Quick Resume stays.
     */
    private void restartFrontendIfExitWedged(EngineSession ending) {
        synchronized (this) {
            if (retiringSession != ending) return;
        }
        if (qtTerminalShutdownRequested || activity.isFinishing() || activity.isDestroyed() ||
                !cleanFrontendRestartStarted.compareAndSet(false, true)) return;
        Log.w(TAG, "Exit checkpoint still blocked by a running core frame; restarting " +
                "frontend engine=" + request.engineId + " system=" + request.systemId +
                " marker=wedged-exit-clean-process-boundary");
        try {
            activity.startActivity(FrontendRestartActivity.createIntent(activity));
        } catch (RuntimeException failure) {
            Log.e(TAG, "Unable to start restart bridge for wedged exit; terminating " +
                    "retained frontend", failure);
            android.os.Process.killProcess(android.os.Process.myPid());
        }
    }

    private boolean requiresCleanFrontendRestart() {
        return NativeAdapterStopPolicy.requiresCleanFrontendRestart(request.engineId);
    }

    /**
     * Keep engines built in while renewing the frontend for adapters whose
     * subsequent sessions cannot reuse the process. Switch waits for actual
     * save/stop/release acknowledgement; only aPS3e keeps its timed fallback.
     */
    private void beginCleanFrontendRestart() {
        beginCleanFrontendRestart(pendingCleanFrontendLaunch);
    }

    private void beginCleanFrontendRestart(Intent nextLaunch) {
        if (!requiresCleanFrontendRestart() ||
                qtTerminalShutdownRequested || activity.isFinishing() || activity.isDestroyed() ||
                !cleanFrontendRestartStarted.compareAndSet(false, true)) return;
        try {
            activity.startActivity(FrontendRestartActivity.createIntent(activity, nextLaunch));
            Log.i(TAG, "Started clean frontend restart after built-in session engine=" +
                    request.engineId + ("aps3e".equals(request.engineId)
                            ? " marker=aps3e-clean-process-boundary"
                            : " marker=native-clean-process-boundary"));
        } catch (RuntimeException failure) {
            Log.e(TAG, "Unable to start native clean-process bridge; terminating " +
                    "unsafe retained frontend", failure);
            android.os.Process.killProcess(android.os.Process.myPid());
        }
    }

    private void destroyNow() {
        ++stopGeneration;
        resumed = false;
        updateGameplayScreenOn();
        // The router holds this host statically; a destroyed one left
        // registered would keep the lower display's panel pointing at it.
        SecondaryCheatPanelRouter.release(activity, this);
        cheatsVisible = false;
        cheatsOnSecondDisplay = false;
        EngineSession ending = session;
        session = null;
        clearActiveNetplaySession(ending);
        if (ending == null && switchingCompletion != null) switchingCompletion.complete();
        if (ending != null) {
            try {
                // Same bounded barrier as exitToLibrary: the render owner must
                // pause while the game TextureView is still valid, or a queued
                // swap lands on an abandoned BufferQueue (EGL_BAD_SURFACE
                // 0x300d) and the final Quick Resume commit can fail.
                ending.quiesceForExit();
            } catch (RuntimeException failure) {
                Log.w(TAG, "Destroy-time render quiescence failed", failure);
            }
            // Release joins engine threads; it must never run on the UI
            // thread that Android is tearing the Activity down on.
            if (!exitStarted.get()) {
                detachViewsAfterDestroyStop(ending);
                return;
            }
            releaseDestroyedSession(ending);
        }
        detachViews();
    }

    private void detachViewsAfterDestroyStop(EngineSession ending) {
        // The final Quick Resume serializes against the quiesced but still
        // attached game root. Detach only after stop's completion fires; the
        // bounded fallback keeps a completion that never arrives from leaking
        // the destroyed Activity's view tree.
        final AtomicBoolean viewsDetached = new AtomicBoolean(false);
        final AtomicBoolean releaseStarted = new AtomicBoolean(false);
        final Runnable releaseOnce = () -> {
            if (releaseStarted.compareAndSet(false, true)) releaseDestroyedSession(ending);
        };
        final Runnable detachOnce = () -> {
            if (viewsDetached.compareAndSet(false, true)) detachViews();
        };
        mainHandler.postDelayed(detachOnce, DESTROY_DETACH_FALLBACK_MS);
        runAfterPresentationRecovery(() -> {
            try {
                ending.stop(EngineSession.StopReason.ACTIVITY_DESTROYED, () -> {
                    releaseOnce.run();
                    mainHandler.post(detachOnce);
                });
            } catch (RuntimeException failure) {
                Log.w(TAG, "Destroy-time stop failed", failure);
                releaseOnce.run();
                mainHandler.post(detachOnce);
            }
        });
    }

    private void runAfterPresentationRecovery(Runnable action) {
        if (presentationRecoveryPending) RETIREMENT_RELEASES.execute(action);
        else action.run();
    }

    private void releaseDestroyedSession(EngineSession ending) {
        releaseSessionWhenComplete(ending, () -> {
            synchronized (InWindowGameHost.class) {
                destroyedSessionsRetiring--;
            }
            mainHandler.post(InWindowGameHost::restorePendingRecreations);
            dispatchQtTerminalShutdownIfReady();
        });
    }

    private void releaseSessionWhenComplete(EngineSession ending, Runnable completion) {
        AtomicBoolean acknowledged = new AtomicBoolean(false);
        EngineSession.Completion once = () -> {
            if (acknowledged.compareAndSet(false, true)) completion.run();
        };
        RETIREMENT_RELEASES.execute(() -> {
            try {
                if (ending instanceof PpssppGlesEngineSession) {
                    ((PpssppGlesEngineSession) ending).releaseWhenComplete(once);
                } else if (ending instanceof LibretroEngineSession) {
                    ((LibretroEngineSession) ending).releaseWhenComplete(once);
                } else if (ending instanceof NativeAdapterEngineSession) {
                    ((NativeAdapterEngineSession) ending).releaseWhenComplete(once);
                } else {
                    // Synchronous sessions retain their release-return contract.
                    ending.release();
                    once.complete();
                }
            } catch (RuntimeException failure) {
                Log.e(TAG, "Engine release not acknowledged; retaining retirement gate", failure);
            }
        });
    }

    private void detachViews() {
        mainHandler.removeCallbacks(revealLaunchSpinner);
        if (root != null) root.setKeepScreenOn(false);
        if (multiplayerOverlay != null) {
            multiplayerOverlay.destroy();
            multiplayerOverlay = null;
        }
        if (root != null && root.getParent() == content) content.removeView(root);
        root = null;
        launchCurtain = null;
        launchSpinner = null;
        for (int index = 0; index < libraryViews.size(); index++) {
            View child = libraryViews.get(index);
            if (child.getParent() == content)
                child.setVisibility(libraryVisibility.get(index));
        }
        libraryViews.clear();
        libraryVisibility.clear();
    }

    private void revealLibraryOverRetiringSurface() {
        // Fail-closed fallback used only when the synchronous render barrier
        // could not establish that removing the Surface is safe.
        for (int index = 0; index < libraryViews.size(); index++) {
            View child = libraryViews.get(index);
            if (child.getParent() == content) {
                child.setVisibility(libraryVisibility.get(index));
                child.bringToFront();
            }
        }
        Log.i(TAG, "Library revealed over quiesced game surface engine=" +
                request.engineId + " system=" + request.systemId);
    }

    @Override public void onSurfaceAvailable(Surface surface, int width, int height) {
        EngineSession current = session;
        if (current == null) return;
        current.attachSurface(surface, width, height);
        surfaceAvailable = surface != null && surface.isValid();
        applyOwnerRequestedDirect();
        updateGameplayScreenOn();
        if (surfaceAvailable && prepared && resumed && !menuVisible &&
                !fatalErrorVisible)
            current.resume();
    }

    @Override public void onSurfaceSizeChanged(int width, int height) {
        if (session != null) session.resizeSurface(width, height);
    }

    @Override public void onSurfaceDestroyed() {
        EngineSession current = session;
        surfaceAvailable = false;
        updateGameplayScreenOn();
        if (current == null) return;
        // A TextureView releases the Surface, and a SurfaceView disconnects it,
        // the moment this callback returns. Sessions that own a render thread
        // therefore detach synchronously within a short bound; a queued swap on
        // the dead surface is the historical EGL_BAD_SURFACE 0x300d route.
        detachCurrentSurface(current);
    }

    @Override public void onSurfaceStartupError(String message, Throwable cause) {
        activity.runOnUiThread(() -> {
            // Cancellation cleanup may complete after Exit, replacement or
            // Activity destruction. It must not reopen UI for the old game.
            if (libraryReturned || fatalErrorVisible || exitStarted.get() ||
                    activity.isFinishing() || activity.isDestroyed()) return;
            surfaceAvailable = false;
            updateGameplayScreenOn();
            // This is a launch failure, not a first-frame notification. Stop
            // the launch indicators and use the existing error/return UI
            // without claiming any frame was presented.
            mainHandler.removeCallbacks(revealLaunchSpinner);
            if (launchSpinner != null) launchSpinner.setVisibility(View.GONE);
            Log.e(TAG, "Gameplay display startup failed", cause);
            showFatalError(message);
        });
    }

    @Override public void retireSurfaceRenderer(FrameGenerationRenderer renderer,
            GameSurface.RetirementCompletion completion) {
        final EngineSession producer = session != null ? session : retiringSession;
        surfaceAvailable = false;
        updateGameplayScreenOn();
        presentationRecoveryPending = true;
        RETIREMENT_RELEASES.execute(() -> {
            Throwable problem = null;
            try {
                if (producer == null || !producer.quiesceForSurfaceRetirement())
                    throw new IllegalStateException("Producer did not acknowledge surface retirement");
                renderer.close();
            } catch (Throwable failure) { problem = failure; }
            final Throwable failure = problem;
            mainHandler.post(() -> {
                presentationRecoveryPending = false;
                Log.i(TAG, "Published generator retirement engine=" + request.engineId +
                        " acknowledged=" + (failure == null));
                completion.complete(failure);
            });
        });
    }

    @Override public void onSurfaceRuntimeError(String message, Throwable cause) {
        activity.runOnUiThread(() -> {
            if (libraryReturned || fatalErrorVisible || exitStarted.get()) return;
            if (presentationRecoveryPending) return;
            if (tryStartRuntimeDirectRecovery(message, cause)) return;
            prepared = false;
            surfaceAvailable = false;
            updateGameplayScreenOn();
            // UI dispatch, never the failed renderer owner. Pause through the
            // session's existing command queue; retirement waits for normal exit.
            EngineSession failedSession = session;
            if (failedSession != null) {
                try { failedSession.pause(EngineSession.PauseReason.ANDROID_BACKGROUND); }
                catch (RuntimeException pauseFailure) {
                    Log.e(TAG, "Could not pause after display failure", pauseFailure);
                }
            }
            Log.e(TAG, "Runtime gameplay display stopped", cause);
            showFatalError(message, true);
        });
    }

    /** Called after saving Off; UI dispatch never blocks the settings transaction. */
    public static void requestFrameGenerationOff() {
        // setMode holds the settings lock. Never acquire the host lock until
        // dispatch: launch paths can read settings while holding the host lock.
        new Handler(Looper.getMainLooper()).post(() -> {
            final InWindowGameHost target;
            synchronized (InWindowGameHost.class) { target = active; }
            if (target == null) return;
            target.ownerRequestedDirect = true;
            target.applyOwnerRequestedDirect();
        });
    }

    private void applyOwnerRequestedDirect() {
        if (!ownerRequestedDirect || session == null ||
                libraryReturned || fatalErrorVisible || exitStarted.get() ||
                presentationRecoveryPending || presentationRecoveryAttempted ||
                !(gameSurface instanceof GameSurfaceView)) return;
        GameSurfaceView layer = (GameSurfaceView) gameSurface;
        if (frameRateBadge != null) frameRateBadge.setVisibility(View.GONE);
        layer.requestOwnerDirect();
        if (!prepared) return;
        FrameGenerationRenderer renderer = layer.beginOwnerDirectRecovery();
        if (renderer != null)
            startRuntimeDirectRecovery(layer, renderer,
                    "Unable to turn frame generation off safely", null);
    }

    private boolean tryStartRuntimeDirectRecovery(String message, Throwable cause) {
        if (presentationRecoveryAttempted || !prepared || session == null ||
                !(gameSurface instanceof GameSurfaceView)) return false;
        final GameSurfaceView layer = (GameSurfaceView) gameSurface;
        final FrameGenerationRenderer renderer = layer.beginRuntimeDirectRecovery();
        if (renderer == null) return false; // e.g. lower-panel or engine error
        return startRuntimeDirectRecovery(layer, renderer, message, cause);
    }

    private boolean startRuntimeDirectRecovery(final GameSurfaceView layer,
            final FrameGenerationRenderer renderer, String message, Throwable cause) {
        final EngineSession recovering = session;
        presentationRecoveryAttempted = true;
        presentationRecoveryPending = true;
        if (frameRateBadge != null) frameRateBadge.setVisibility(View.GONE);
        prepared = false;
        surfaceAvailable = false;
        updateGameplayScreenOn();
        Log.w(TAG, "Retiring frame generation to Direct", cause);
        // This same queue orders later core release after generator retirement.
        // Neither the emulator barrier nor LSFG's bounded close runs on the UI.
        RETIREMENT_RELEASES.execute(() -> {
            Throwable problem = null;
            try {
                if (!recovering.quiesceForPresentationRecovery())
                    throw new IllegalStateException("Producer did not acknowledge display recovery");
                renderer.close();
            } catch (Throwable failure) { problem = failure; }
            final Throwable failure = problem;
            mainHandler.post(() -> {
                presentationRecoveryPending = false;
                boolean current = session == recovering && gameSurface == layer &&
                        !libraryReturned && !fatalErrorVisible && !exitStarted.get();
                if (failure == null && current) prepared = true;
                try {
                    if (!layer.finishRuntimeDirectRecovery(renderer, failure == null, current) &&
                            failure == null)
                        throw new IllegalStateException("Display recovery owner changed before commit");
                } catch (RuntimeException rebindFailure) {
                    prepared = false;
                    onSurfaceRuntimeError(message, rebindFailure);
                    return;
                }
                if (!current) return;
                if (failure != null) {
                    onSurfaceRuntimeError(message, failure);
                    return;
                }
                updateGameplayScreenOn();
                Log.i(TAG, "Frame generation retired; continuing game in Direct " +
                        "engine=" + request.engineId + " system=" + request.systemId);
                Toast.makeText(activity, "Frame generation stopped; continuing without it.",
                        Toast.LENGTH_LONG).show();
            });
        });
        return true;
    }

    private void detachCurrentSurface(EngineSession current) {
        if (current instanceof PpssppGlesEngineSession)
            ((PpssppGlesEngineSession) current).detachSurfaceAndWait();
        else if (current instanceof NativeAdapterEngineSession)
            ((NativeAdapterEngineSession) current).detachSurfaceAndWait();
        else current.detachSurface();
    }

    @Override public void onSessionReady() {
        activity.runOnUiThread(() -> {
            if (fatalErrorVisible) return;
            privateDiagnostics.ready();
            double declaredVideoHz = 0.0;
            if (session instanceof LibretroEngineSession)
                declaredVideoHz = ((LibretroEngineSession) session).declaredVideoHz();
            else if (session instanceof PpssppGlesEngineSession)
                declaredVideoHz = ((PpssppGlesEngineSession) session).declaredVideoHz();
            // Do not select a native adapter's panel mode from its nominal
            // declaration alone. The bb76 Thor experiment selected 60 Hz but
            // increased presentation misses; whole-clock synchronization and
            // physical pacing must be qualified before enabling that path.
            if (declaredVideoHz > 1.0 && declaredVideoHz < 1000.0) {
                float directPanelHz = directSurfaceCadenceHz(declaredVideoHz);
                if (request.frameGenerationMode == FrameGenerationSettings.Mode.OFF)
                    requestNativePanelMode(
                            DisplaySyncPolicy.directPanelRefreshHz(declaredVideoHz));
                if (gameSurface instanceof GameSurface)
                    ((GameSurface) gameSurface).setDirectPresentationHz(directPanelHz);
                else if (gameSurface instanceof GameSurfaceView)
                    ((GameSurfaceView) gameSurface).setDirectPresentationHz(directPanelHz);
            }
            if (gameSurface instanceof GameSurfaceView &&
                    session instanceof LibretroEngineSession &&
                    authoritativeVideoHz(request.systemId) > 0.0) {
                ((GameSurfaceView) gameSurface).setAuthoritativeSourceHz(
                        ((LibretroEngineSession) session).effectiveVideoHz());
            }
            if (gameSurface instanceof GameSurfaceView &&
                    session instanceof NativeAdapterEngineSession) {
                // A native adapter class, declared 60-Hz clock, Vulkan present
                // count or quantized submission timestamp is not image-linked
                // source authority. The session publishes an optional explicit
                // capability after start; missing hooks (including aPS3e and
                // old Eden/Cemu binaries) remain unknown.
                double timelineHz = ((NativeAdapterEngineSession) session)
                        .authoritativeProducerTimelineHz();
                ((GameSurfaceView) gameSurface).setSlotLatticeProducer(timelineHz > 0.0);
                ((GameSurfaceView) gameSurface).setProducerTimelineHz(timelineHz);
            }
            if (gameSurface instanceof GameSurfaceView &&
                    session instanceof PpssppGlesEngineSession) {
                PpssppGlesEngineSession hardware =
                        (PpssppGlesEngineSession) session;
                // Hardware cores are stamped on the clock they are paced at
                // (declared x synchronized multiplier), so the trusted
                // producer timeline is the synchronized clock, not the
                // declared one: a 59.94-declared timeline against 60.00
                // stamps failed the per-tick continuity test on multi-tick
                // gaps and silently reset the presentation epoch every
                // second (GameCube run gc-b18).
                ((GameSurfaceView) gameSurface).setProducerTimelineHz(
                        hardware.usesStampedProducerTimeline() ?
                                DisplaySyncPolicy.synchronizedSourceHz(
                                        hardware.declaredVideoHz()) : 0.0);
            }
            // Publishes the live session for MultiplayerManager (a different
            // source tree entirely, android-companion, compiled into the same
            // APK) to find and attach a netplay relay to once a match goes
            // active -- see ActiveEngineSessionRegistry's own doc comment. A
            // session implementing neither capable-session interface simply
            // never gets published.
            if (session instanceof com.thorium.lucent.netplay.NetplayCapableSession ||
                    session instanceof com.thorium.lucent.netplay.NativeAdapterCapableSession) {
                com.thorium.lucent.netplay.ActiveEngineSessionRegistry.set(session);
            }
            // Manual netplay port-routing verification only: fires only when
            // a marker file has been placed by hand (adb shell touch
            // /sdcard/lucent-netplay-synthetic-test), which nothing in the
            // normal UI or launch flow ever does. See
            // NetplaySyntheticInputTester's class doc for the full rationale.
            if (com.thorium.lucent.netplay.NetplaySyntheticInputTester.isRequested(activity)) {
                if (session instanceof LibretroEngineSession) {
                    LibretroEngineSession target = (LibretroEngineSession) session;
                    com.thorium.lucent.netplay.NetplaySyntheticInputTester.start(
                            target::applyRemoteJoypadButton);
                } else if (session instanceof PpssppGlesEngineSession) {
                    PpssppGlesEngineSession target = (PpssppGlesEngineSession) session;
                    com.thorium.lucent.netplay.NetplaySyntheticInputTester.start(
                            target::applyRemoteJoypadButton);
                }
            }
            // Same manual-only verification, for the native-adapter (Eden/Cemu)
            // family -- its own separate marker file, since it drives a
            // different sink type (NativeControlSink, not RemoteJoypadSink).
            if (com.thorium.lucent.netplay.NativeAdapterSyntheticInputTester.isRequested(activity)
                    && session instanceof com.thorium.lucent.netplay.NativeAdapterCapableSession) {
                com.thorium.lucent.netplay.NativeAdapterCapableSession target =
                        (com.thorium.lucent.netplay.NativeAdapterCapableSession) session;
                com.thorium.lucent.netplay.NativeAdapterSyntheticInputTester.start(
                        target::applyRemoteControl);
            }
            prepared = true;
            applyOwnerRequestedDirect();
            updateGameplayScreenOn();
            if (status != null) status.setVisibility(View.GONE);
            if (touchControls != null && session != null) {
                touchControls.setAnalogStickCount(session.virtualAnalogStickCount());
                touchControls.setVisibility(session.shouldShowOnScreenControls()
                        ? View.VISIBLE : View.GONE);
            }
            // The catalogue is only consulted once the core has loaded the
            // content, so this is the first moment the menu can say whether
            // this game has cheats at all.
            if (cheatsButton != null && session != null) {
                boolean offered = !session.availableCheats().isEmpty();
                cheatsButton.setEnabled(offered);
                cheatsButton.setAlpha(offered ? 1f : 0.45f);
            }
            if (prepared && resumed && surfaceAvailable && !menuVisible && session != null)
                session.resume();
        });
    }

    @Override public void onSessionError(String message, Throwable cause) {
        if (cause instanceof com.thorium.lucent.video.RuntimePresentationFailure.Failure) {
            onSurfaceRuntimeError(cause.getMessage(), cause);
            return;
        }
        privateDiagnostics.failed(cause instanceof OutOfMemoryError);
        Log.e(TAG, "Engine session error engine=" + request.engineId +
                " system=" + request.systemId + " message=" + clean(message),
                cause == null ? new IllegalStateException("No engine cause supplied") : cause);
        activity.runOnUiThread(() -> {
            if (libraryReturned) {
                finishRetiringSession(retiringSession, cause == null
                        ? new IllegalStateException(message) : cause);
                return;
            }
            // This session was launched internally. A prerequisite failure is
            // not permission to hand its ROM to another app, even if the route
            // preference changed while this load was in flight. External games
            // are launched only through the explicitly selected library route.
            showFatalError(message);
        });
    }

    @Override public void onSessionStopRejected(String message, Throwable cause) {
        activity.runOnUiThread(() -> {
            if (libraryReturned) {
                // The library is deliberately revealed before the checkpoint
                // commits. A late failure therefore cannot reuse this host's
                // detached status sheet, but it must still be visible. Toast is
                // already an application-wide, nonblocking message channel in
                // EmuFusion and does not reopen gameplay or replace the warm Qt
                // window the user has already returned to.
                String notice = clean(message);
                if (notice.isEmpty()) notice = "EmuFusion could not save your current " +
                        "position. Your previous Quick Resume is still available.";
                Toast.makeText(activity.getApplicationContext(), notice,
                        Toast.LENGTH_LONG).show();
                Log.w(TAG, "Background exit checkpoint failure shown in library " +
                        "engine=" + request.engineId + " system=" + request.systemId +
                        " marker=exit-save-failure-visible", cause);
                finishRetiringSession(retiringSession, cause == null
                        ? new IllegalStateException(message) : cause);
                return;
            }
            if (switchingSession != null && !restoreRejectedSwitchSession()) {
                // A destroyed owner cannot resurrect a rejected switch. Its
                // retirement remains held until the release acknowledgement.
                if (switchingCompletion != null) switchingCompletion.complete();
                return;
            }
            Log.w(TAG, "Exit save rejected; gameplay retained", cause);
            exitStarted.set(false);
            hideCheatsPanel();
            menuVisible = false;
            if (pauseOverlay != null) pauseOverlay.setVisibility(View.GONE);
            if (status != null) {
                status.setClickable(false);
                status.setOnClickListener(null);
                status.setText(message);
                status.setBackgroundColor(Color.argb(190, 8, 8, 12));
                status.setVisibility(View.VISIBLE);
                status.bringToFront();
                mainHandler.postDelayed(() -> {
                    if (!exitStarted.get() && !fatalErrorVisible && status != null)
                        status.setVisibility(View.GONE);
                }, 3500L);
            }
            if (prepared && resumed && surfaceAvailable && session != null) session.resume();
            updateGameplayScreenOn();
        });
    }

    private boolean restoreRejectedSwitchSession() {
        synchronized (InWindowGameHost.class) {
            if (switchingSession == null || switchingStopCompleted == null ||
                    active != this || qtTerminalShutdownRequested ||
                    activity.isFinishing() || activity.isDestroyed() ||
                    !switchingStopCompleted.compareAndSet(false, true)) return false;
            session = switchingSession;
            switchingSession = null;
            switchingCompletion = null;
            // The live host owns the retained native session again; this is
            // cancellation of a switch, not an acknowledgement of release.
            RETIRING_SESSIONS.remove(session);
            if (session instanceof com.thorium.lucent.netplay.NetplayCapableSession ||
                    session instanceof com.thorium.lucent.netplay.NativeAdapterCapableSession) {
                com.thorium.lucent.netplay.ActiveEngineSessionRegistry.set(session);
            }
            return true;
        }
    }

    @Override public void onRestoreAvailabilityChanged(boolean available) {
        activity.runOnUiThread(() -> {
            if (restoreButton != null) {
                restoreButton.setEnabled(available);
                restoreButton.setAlpha(available ? 1f : 0.45f);
            }
        });
    }

    private void showFatalError(String message) {
        showFatalError(message, false);
    }

    private void showFatalError(String message, boolean runtimeFailure) {
        // No message, stack, path, title, or exception object crosses this boundary.
        privateDiagnostics.failed(false);
        clearPendingRecreation(activity);
        // A failed cold launch must expose its error, not wait behind the
        // library's boot video for a first game frame that can never arrive.
        BootVideoOverlay.finish();
        // Keep failures inside the existing application window; Android
        // dialogs are separate Window objects and violate EmuFusion's one-window
        // gameplay contract.
        mainHandler.removeCallbacks(revealLaunchSpinner);
        View failedCurtain = launchCurtain;
        launchCurtain = null;
        View failedSpinner = launchSpinner;
        launchSpinner = null;
        if (failedCurtain != null && failedCurtain.getParent() == root)
            root.removeView(failedCurtain);
        if (failedSpinner != null && failedSpinner.getParent() == root)
            root.removeView(failedSpinner);
        // No first-frame callback or success log: failure, including a lower
        // display startup error, terminates the launch indicators explicitly.
        if (status == null) {
            exitToLibrary("fatal-status-unavailable");
            return;
        }
        fatalErrorVisible = true;
        updateGameplayScreenOn();
        status.setText((runtimeFailure ? "Game display stopped\n\n" : "Unable to start game\n\n") +
                (clean(message).isEmpty() ?
                        "EmuFusion could not start this game." : message) +
                "\n\nTap or press Back to return to EmuFusion");
        status.setBackgroundColor(Color.argb(225, 8, 8, 12));
        status.setVisibility(View.VISIBLE);
        status.bringToFront();
        status.setClickable(true);
        status.setOnClickListener(view -> exitToLibrary("fatal-screen-tap"));
    }

    private void explainUnavailable(String message) {
        if (status == null) return;
        // Returns to whichever sheet asked, so an explanation raised from the
        // cheats list does not drop the user back at the pause menu.
        final View sheet = cheatsOnSecondDisplay ? null
                : (cheatsVisible ? cheatOverlay : pauseOverlay);
        // Raised over a running game there is no menu to send anyone back to,
        // and the top screen may be the one the user is not touching. Say so,
        // and take it down on a timer as well as on a tap.
        final boolean overGameplay = sheet == null;
        status.setText(message + (overGameplay ? ""
                : "\n\nTap to return to the pause menu"));
        status.setBackgroundColor(Color.argb(overGameplay ? 170 : 220, 8, 8, 12));
        status.setVisibility(View.VISIBLE);
        status.bringToFront();
        status.setClickable(true);
        status.setOnClickListener(view -> {
            status.setClickable(false);
            status.setVisibility(View.GONE);
            if (sheet != null) sheet.bringToFront();
        });
        if (!overGameplay) return;
        mainHandler.postDelayed(() -> {
            if (!fatalErrorVisible && status != null && status.isClickable()) {
                status.setClickable(false);
                status.setVisibility(View.GONE);
            }
        }, 3000L);
    }

    private void enterImmersiveMode() {
        View decor = activity.getWindow().getDecorView();
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            activity.getWindow().setDecorFitsSystemWindows(false);
            android.view.WindowInsetsController controller =
                    decor.getWindowInsetsController();
            if (controller != null) controller.hide(
                    WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
        } else {
            decor.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN |
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY |
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN |
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION |
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }

    private int dp(int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }

    private static String title(File file) {
        return GameTitles.forFile(file);
    }
}
