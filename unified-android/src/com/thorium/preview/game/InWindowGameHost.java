package com.thorium.preview.game;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

import com.thorium.lucent.metadata.EngineSystemIdResolver;
import com.thorium.preview.MenuSoundPlayer;
import com.thorium.preview.PreviewService;

/**
 * Owns in-process emulation inside Lucent's existing Qt MainActivity window.
 *
 * This deliberately is not an Activity. The library, gameplay surface, pause
 * UI, save lifecycle, and return transition therefore share one Android
 * ActivityRecord, task, application window, and process.
 */
public final class InWindowGameHost
        implements GameSurface.Listener, EngineSession.Listener {
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
    private static final int COLOR_ACCENT = Color.rgb(151, 119, 255);
    private static final java.util.regex.Pattern QUALIFICATION_SESSION =
            java.util.regex.Pattern.compile("qa-[0-9a-f]{32}");

    private static InWindowGameHost active;
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

    private final Activity activity;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final AtomicBoolean exitStarted = new AtomicBoolean(false);
    private final GameLaunchRequest request;
    private final ViewGroup content;
    private final List<View> libraryViews = new ArrayList<>();
    private final List<Integer> libraryVisibility = new ArrayList<>();
    private final List<Button> pauseButtons = new ArrayList<>();
    private EngineSession session;
    private FrameLayout root;
    private GameSurface gameSurface;
    private TouchControlsView touchControls;
    private FrameLayout pauseOverlay;
    private TextView status;
    private Button restoreButton;
    private boolean prepared;
    private boolean resumed = true;
    private boolean menuVisible;
    private boolean stopPressed;
    private boolean stopHoldTriggered;
    private boolean startPressed;
    // Start reaches the game immediately when it is pressed on its own, so the
    // combo has to be able to take that press back. Both facts are needed:
    // whether the game currently sees Start down, and the event that put it
    // there (a synthetic release must carry the same device to be routed).
    private boolean startDeliveredToGame;
    private KeyEvent startDownEvent;
    private boolean comboConsumedSelect;
    private boolean comboConsumedStart;
    private boolean fatalErrorVisible;
    private volatile boolean libraryReturned;
    private volatile EngineSession retiringSession;
    private int pauseSelection;
    private long stopGeneration;
    private long resetGeneration;

    private InWindowGameHost(Activity activity, GameLaunchRequest request,
            ViewGroup content) {
        this.activity = activity;
        this.request = request;
        this.content = content;
    }

    /** Consumes a Lucent game intent and overlays gameplay in this Activity. */
    public static synchronized boolean handleIntent(Activity activity, Intent source) {
        if (activity == null || source == null ||
                !ACTION_LAUNCH.equals(source.getAction())) return false;
        GameLaunchRequest request = requestFrom(activity, source);
        if (request == null) {
            Log.e(TAG, "Rejected incomplete or unsafe in-window launch");
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
        // Normal menu launches arrive through InProcessGameLaunchCommand. Legacy or
        // diagnostic direct intents can still reach onNewIntent/onStart. Keep
        // the action intact while gameplay is active so Android process
        // recreation can restore it, and deduplicate by launch identity.
        if (previous != null && previous.sameRequest(request)) return true;
        if (previous != null) previous.replaceWith(request);
        else {
            active = new InWindowGameHost(activity, request, (ViewGroup) contentView);
            active.attach();
        }
        return true;
    }

    public static synchronized boolean dispatchKeyEvent(Activity activity, KeyEvent event) {
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
        else if (active.menuVisible) active.hidePauseMenu();
        else active.showPauseMenu();
        return true;
    }

    public static synchronized void onResume(Activity activity) {
        if (active == null || active.activity != activity) return;
        active.resumed = true;
        // The Qt library stays lifecycle-warm behind the in-window overlay.
        // Explicitly pausing/resuming Qt rebuilds QML and exposes Pegasus's
        // progress splash during return, destroying exact navigation state.
        // Its Android view remains VISIBLE underneath Lucent's opaque gameplay
        // root. INVISIBLE destroys/recreates Qt's Android SurfaceView on this
        // Thor firmware and exposes the progress splash on return.
        active.enterImmersiveMode();
        if (active.prepared && !active.menuVisible && !active.fatalErrorVisible &&
                active.session != null)
            active.session.resume();
    }

    public static synchronized void onPause(Activity activity) {
        if (active == null || active.activity != activity) return;
        active.resumed = false;
        if (active.prepared && active.session != null)
            active.session.pause(EngineSession.PauseReason.ANDROID_BACKGROUND);
    }

    public static synchronized void onDestroy(Activity activity) {
        if (active == null || active.activity != activity) return;
        InWindowGameHost ending = active;
        active = null;
        ending.destroyNow();
    }

    public static synchronized boolean isActive(Activity activity) {
        return active != null && active.activity == activity;
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
        // engine_id merely because it targets Lucent: the signed catalog must
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
            // A QA namespace is honored only when this exact engine exists in
            // the fail-closed Phase 2 qualification catalog packaged in this
            // APK. Production/Phase 1 launches cannot partition state by
            // injecting this extra.
            if (Phase2QualificationCatalog.byId(activity, engine) == null ||
                    !QUALIFICATION_SESSION.matcher(candidate).matches()) return null;
            qualificationSession = candidate;
        } else if (!clean(source.getStringExtra("qualification_session")).isEmpty()) {
            // Never silently accept a namespace without the explicit QA
            // marker: reject it instead of altering production state routing.
            return null;
        }
        GameLaunchRequest request = new GameLaunchRequest(engine, system, gameId,
                title, uri, SessionReturnState.from(source), qualificationSession);
        return request.isValid() ? request : null;
    }

    private void attach() {
        activity.startService(new Intent(activity, PreviewService.class)
                .setAction(PreviewService.ACTION_GAMEPLAY));
        for (int index = 0; index < content.getChildCount(); index++) {
            View child = content.getChildAt(index);
            libraryViews.add(child);
            libraryVisibility.add(child.getVisibility());
            // Keep the Qt SurfaceView attached, visible, and lifecycle-warm.
            // The opaque gameplay root added below owns presentation/input;
            // this avoids Surface recreation without another Activity/window.
        }
        buildUi();
        content.addView(root, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        root.bringToFront();
        enterImmersiveMode();
        session = EngineSessionRegistry.create(activity, request);
        gameSurface.setListener(this);
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

    private void replaceWith(GameLaunchRequest next) {
        if (exitStarted.get()) return;
        exitStarted.set(true);
        EngineSession ending = session;
        session = null;
        if (ending != null) {
            try {
                // Pause the render owner while the outgoing game's surface is
                // still valid, exactly as exitToLibrary does; the stop below
                // then serializes against a quiesced renderer.
                ending.quiesceForExit();
            } catch (RuntimeException failure) {
                Log.w(TAG, "Switch-time render quiescence failed", failure);
            }
        }
        EngineSession.Completion switchGame = () -> {
            // release() joins engine threads for seconds; keep it off the UI
            // thread and let the retirement executor own native teardown.
            if (ending != null) RETIREMENT_RELEASES.execute(ending::release);
            activity.runOnUiThread(() -> {
                detachViews();
                synchronized (InWindowGameHost.class) {
                    active = new InWindowGameHost(activity, next, content);
                    active.attach();
                }
            });
        };
        if (ending == null) switchGame.complete();
        else ending.stop(EngineSession.StopReason.EXIT_TO_LUCENT, switchGame);
    }

    private void buildUi() {
        root = new FrameLayout(activity);
        root.setBackgroundColor(Color.BLACK);
        root.setFocusable(true);
        root.setFocusableInTouchMode(true);
        // Gameplay owns every touch that is not handled by an on-screen control
        // child (the phone/tablet fallback). Consuming here stops a stray tap
        // from reaching Qt's Activity-level touch dispatch behind the game,
        // which was navigating the library ("tapping skips to a new game").
        root.setClickable(true);
        root.setOnTouchListener((view, event) -> true);
        gameSurface = new GameSurface(activity);
        root.addView(gameSurface, match());
        touchControls = new TouchControlsView(activity);
        touchControls.setVisibility(View.GONE);
        touchControls.setListener((control, pressed) -> {
            if (session != null) session.dispatchVirtualControl(control, pressed);
        });
        root.addView(touchControls, match());
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
        root.requestFocus();
    }

    private FrameLayout.LayoutParams match() {
        return new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT);
    }

    private FrameLayout createPauseOverlay() {
        FrameLayout overlay = new FrameLayout(activity);
        overlay.setBackgroundColor(Color.argb(178, 0, 0, 0));
        overlay.setClickable(true);
        LinearLayout panel = new LinearLayout(activity);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(34), dp(28), dp(34), dp(30));
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
        panel.addView(title, rowParams(dp(54)));
        Button resumeButton = menuButton("Resume");
        resumeButton.setOnClickListener(view -> hidePauseMenu());
        panel.addView(resumeButton, rowParams(dp(58)));
        pauseButtons.add(resumeButton);
        Button controls = menuButton("Controls");
        controls.setOnClickListener(view -> {
            if (session == null || !session.openControls())
                explainUnavailable("Control remapping is unavailable for this core.");
        });
        panel.addView(controls, rowParams(dp(58)));
        pauseButtons.add(controls);
        restoreButton = menuButton("Restore earlier point");
        restoreButton.setEnabled(false);
        restoreButton.setAlpha(0.45f);
        restoreButton.setOnClickListener(view -> {
            if (session == null || !session.openRestoreHistory())
                explainUnavailable("No earlier restore points are available yet.");
        });
        panel.addView(restoreButton, rowParams(dp(58)));
        pauseButtons.add(restoreButton);
        Button exit = menuButton("Exit to Lucent");
        exit.setTextColor(Color.rgb(255, 151, 151));
        exit.setOnClickListener(view -> exitToLibrary("pause-menu-exit"));
        panel.addView(exit, rowParams(dp(58)));
        pauseButtons.add(exit);
        overlay.addView(panel, new FrameLayout.LayoutParams(dp(420),
                FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        return overlay;
    }

    private Button menuButton(String label) {
        Button button = new Button(activity);
        button.setFocusable(true);
        button.setFocusableInTouchMode(true);
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

    private LinearLayout.LayoutParams rowParams(int height) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, height);
        params.topMargin = dp(8);
        return params;
    }

    private boolean handleKeyEvent(KeyEvent event) {
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
                if (menuVisible) hidePauseMenu(); else showPauseMenu();
            }
            return true;
        }
        if (code == KeyEvent.KEYCODE_BUTTON_SELECT ||
                code == KeyEvent.KEYCODE_MEDIA_STOP) return handleStopButton(event);
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
        // Only reached during live gameplay: while the pause menu is up Start
        // keeps its existing swallowed-by-the-menu behaviour above.
        if (code == KeyEvent.KEYCODE_BUTTON_START) return handleStartButton(event);
        return session != null && session.dispatchKeyEvent(event);
    }

    private boolean handleMotionEvent(MotionEvent event) {
        return !menuVisible && session != null &&
                session.dispatchGenericMotionEvent(event);
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
                armResetCombo();
                return true;
            }
            startDeliveredToGame = true;
            return deliverToSession(event);
        }
        if (event.getAction() == KeyEvent.ACTION_UP) {
            startPressed = false;
            ++resetGeneration;
            if (comboConsumedStart) {
                comboConsumedStart = false;
                startDeliveredToGame = false;
                startDownEvent = null;
                return true;
            }
            startDownEvent = null;
            if (startDeliveredToGame) {
                startDeliveredToGame = false;
                return deliverToSession(event);
            }
            // Held next to Select but released before the combo completed: the
            // game never saw the press, so deliver it now as a normal tap.
            latchTapToSession(event);
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
        startDownEvent = null;
        comboConsumedSelect = false;
        comboConsumedStart = false;
    }

    private void showPauseMenu() {
        if (pauseOverlay == null || menuVisible || exitStarted.get()) return;
        // The menu owns the buttons from here, and their releases are consumed
        // by the menu handler above rather than reaching the combo.
        cancelResetCombo();
        menuVisible = true;
        if (prepared && session != null)
            session.pause(EngineSession.PauseReason.LUCENT_MENU);
        pauseOverlay.setVisibility(View.VISIBLE);
        pauseSelection = 0;
        focusPauseSelection();
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

    private void hidePauseMenu() {
        if (!menuVisible) return;
        menuVisible = false;
        pauseOverlay.setVisibility(View.GONE);
        gameSurface.requestFocus();
        enterImmersiveMode();
        if (prepared && resumed && session != null) session.resume();
        Log.i(TAG, "Pause menu hidden engine=" + request.engineId +
                " system=" + request.systemId);
    }

    private void exitToLibrary(String reason) {
        if (!exitStarted.compareAndSet(false, true)) return;
        final long returnStartedUptimeMs = android.os.SystemClock.uptimeMillis();
        Log.i(TAG, "Exit to Lucent invoked engine=" + request.engineId +
                " system=" + request.systemId + " reason=" + clean(reason),
                new Throwable("Lucent exit origin"));
        EngineSession ending = session;
        if (ending != null) {
            try {
                // This bounded render-thread barrier completes while the game
                // TextureView and native window are still valid. The warm Qt
                // library can then be revealed with no abandoned-buffer swap.
                ending.quiesceForExit();
            } catch (RuntimeException failure) {
                Log.w(TAG, "Exit render quiescence failed; retaining gameplay " +
                        "surface through checkpoint", failure);
            }
        }
        session = null;
        retiringSession = ending;
        if (ending != null) RETIRING_SESSIONS.add(ending);

        // Return the existing Qt library immediately. Keep the quiesced game
        // root attached underneath it until the engine's lifecycle executor
        // serializes, atomically commits, and detaches native EGL. This keeps
        // Android's Surface valid without exposing a game or save interstitial.
        returnToLibraryUi(returnStartedUptimeMs);
        if (ending != null) {
            try {
                ending.stop(EngineSession.StopReason.EXIT_TO_LUCENT,
                        () -> finishRetiringSession(ending, null));
            } catch (RuntimeException failure) {
                finishRetiringSession(ending, failure);
            }
        } else {
            detachViews();
        }
    }

    private void returnToLibraryUi(long returnStartedUptimeMs) {
        libraryReturned = true;
        // The ACTION_LAUNCH intent is retained only while gameplay is active
        // so Android can restore an interrupted session. Once the user exits,
        // clear it before exposing the library; process recreation must not
        // silently relaunch the game they already closed.
        activity.setIntent(new Intent(Intent.ACTION_MAIN)
                .setClassName(activity,
                        "org.pegasus_frontend.android.MainActivity")
                .addCategory(Intent.CATEGORY_LAUNCHER));
        revealLibraryOverRetiringSurface();
        synchronized (InWindowGameHost.class) {
            if (active == this) active = null;
        }
        activity.startService(new Intent(activity, PreviewService.class)
                .setAction(PreviewService.ACTION_LIBRARY));
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
        RETIRING_SESSIONS.remove(ending);
        // Some stop-failure callbacks are delivered through the Activity's UI
        // listener. Native teardown and thread joins must never execute there.
        RETIREMENT_RELEASES.execute(ending::release);
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

    private void destroyNow() {
        ++stopGeneration;
        EngineSession ending = session;
        session = null;
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
            RETIREMENT_RELEASES.execute(ending::release);
        }
        detachViews();
    }

    private void detachViewsAfterDestroyStop(EngineSession ending) {
        // The final Quick Resume serializes against the quiesced but still
        // attached game root. Detach only after stop's completion fires; the
        // bounded fallback keeps a completion that never arrives from leaking
        // the destroyed Activity's view tree.
        final AtomicBoolean viewsDetached = new AtomicBoolean(false);
        final Runnable detachOnce = () -> {
            if (viewsDetached.compareAndSet(false, true)) detachViews();
        };
        mainHandler.postDelayed(detachOnce, DESTROY_DETACH_FALLBACK_MS);
        try {
            ending.stop(EngineSession.StopReason.ACTIVITY_DESTROYED, () -> {
                RETIREMENT_RELEASES.execute(ending::release);
                mainHandler.post(detachOnce);
            });
        } catch (RuntimeException failure) {
            Log.w(TAG, "Destroy-time stop failed", failure);
            RETIREMENT_RELEASES.execute(ending::release);
            mainHandler.post(detachOnce);
        }
    }

    private void detachViews() {
        if (root != null && root.getParent() == content) content.removeView(root);
        root = null;
        for (int index = 0; index < libraryViews.size(); index++) {
            View child = libraryViews.get(index);
            if (child.getParent() == content)
                child.setVisibility(libraryVisibility.get(index));
        }
        libraryViews.clear();
        libraryVisibility.clear();
    }

    private void revealLibraryOverRetiringSurface() {
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
        if (session != null) session.attachSurface(surface, width, height);
    }

    @Override public void onSurfaceSizeChanged(int width, int height) {
        if (session != null) session.resizeSurface(width, height);
    }

    @Override public void onSurfaceDestroyed() {
        EngineSession current = session;
        if (current == null) return;
        // TextureView releases the Surface the moment this callback returns.
        // A GLES session detaches on its own render thread, so wait for its
        // bounded synchronous detach; a queued swap on the dead surface is
        // the historical EGL_BAD_SURFACE 0x300d route.
        if (current instanceof PpssppGlesEngineSession)
            ((PpssppGlesEngineSession) current).detachSurfaceAndWait();
        else current.detachSurface();
    }

    @Override public void onSessionReady() {
        activity.runOnUiThread(() -> {
            prepared = true;
            if (status != null) status.setVisibility(View.GONE);
            if (touchControls != null && session != null)
                touchControls.setVisibility(session.shouldShowOnScreenControls()
                        ? View.VISIBLE : View.GONE);
            if (resumed && !menuVisible && session != null) session.resume();
        });
    }

    @Override public void onSessionError(String message, Throwable cause) {
        Log.e(TAG, "Engine session error engine=" + request.engineId +
                " system=" + request.systemId + " message=" + clean(message),
                cause == null ? new IllegalStateException("No engine cause supplied") : cause);
        activity.runOnUiThread(() -> {
            if (libraryReturned) {
                finishRetiringSession(retiringSession, cause == null
                        ? new IllegalStateException(message) : cause);
                return;
            }
            showFatalError(message);
        });
    }

    @Override public void onSessionStopRejected(String message, Throwable cause) {
        activity.runOnUiThread(() -> {
            if (libraryReturned) {
                finishRetiringSession(retiringSession, cause == null
                        ? new IllegalStateException(message) : cause);
                return;
            }
            Log.w(TAG, "Exit save rejected; gameplay retained", cause);
            exitStarted.set(false);
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
        });
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
        // Keep failures inside the existing application window; Android
        // dialogs are separate Window objects and violate Lucent's one-window
        // gameplay contract.
        if (status == null) {
            exitToLibrary("fatal-status-unavailable");
            return;
        }
        fatalErrorVisible = true;
        status.setText("Unable to start game\n\n" +
                (clean(message).isEmpty() ?
                        "Lucent could not start this game." : message) +
                "\n\nTap or press Back to return to Lucent");
        status.setBackgroundColor(Color.argb(225, 8, 8, 12));
        status.setVisibility(View.VISIBLE);
        status.bringToFront();
        status.setClickable(true);
        status.setOnClickListener(view -> exitToLibrary("fatal-screen-tap"));
    }

    private void explainUnavailable(String message) {
        if (status == null) return;
        status.setText(message + "\n\nTap to return to the pause menu");
        status.setBackgroundColor(Color.argb(220, 8, 8, 12));
        status.setVisibility(View.VISIBLE);
        status.bringToFront();
        status.setClickable(true);
        status.setOnClickListener(view -> {
            status.setClickable(false);
            status.setVisibility(View.GONE);
            pauseOverlay.bringToFront();
        });
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
        String name = file.getName();
        int dot = name.lastIndexOf('.');
        return dot > 0 ? name.substring(0, dot) : name;
    }
}
