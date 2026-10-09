package com.thorium.preview.game;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.concurrent.atomic.AtomicBoolean;

/** Full-screen EmuFusion shell used by every in-process emulation engine. */
public final class LucentGameActivity extends Activity
        implements GameSurface.Listener, EngineSession.Listener {
    private static final String TAG = "LucentGame";
    private static final long STOP_HOLD_MS = 1000L;
    // About three 60 fps frame periods: long enough that every core's next
    // input poll observes the synthesized Select press, short enough to feel
    // like a tap.
    private static final long TAP_SELECT_HOLD_MS = 48L;
    private static final int COLOR_ACCENT = Color.rgb(151, 119, 255);

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final AtomicBoolean exitStarted = new AtomicBoolean(false);
    private GameLaunchRequest request;
    private EngineSession session;
    private GameSurface gameSurface;
    private TouchControlsView touchControls;
    private FrameLayout pauseOverlay;
    private TextView status;
    private Button restoreButton;
    private boolean prepared;
    private boolean surfaceStartupFailed;
    private boolean activityResumed;
    private boolean menuVisible;
    private boolean stopPressed;
    private boolean stopHoldTriggered;
    private long stopGeneration;

    public static Intent createIntent(Context context, GameLaunchRequest request) {
        Intent intent = new Intent(context, LucentGameActivity.class)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        return request.putInto(intent);
    }

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN,
                WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        enterImmersiveMode();

        request = GameLaunchRequest.from(getIntent());
        if (!request.isValid()) {
            showFatalError("EmuFusion received an incomplete game launch request.", null);
            return;
        }
        SessionReturnRouter.remember(this, request.returnState);
        buildUi();
        session = EngineSessionRegistry.create(this, request);
        gameSurface.setListener(this);
        session.prepare(request, this);
    }

    @Override protected void onResume() {
        super.onResume();
        activityResumed = true;
        enterImmersiveMode();
        if (prepared && !menuVisible && session != null) session.resume();
    }

    @Override protected void onPause() {
        activityResumed = false;
        if (prepared && session != null)
            session.pause(EngineSession.PauseReason.ANDROID_BACKGROUND);
        super.onPause();
    }

    @Override protected void onDestroy() {
        ++stopGeneration;
        if (session != null) {
            EngineSession endingSession = session;
            session = null;
            if (!exitStarted.get()) {
                // Preserve the asynchronous stop boundary: a future StateVault
                // implementation must be allowed to finish its atomic state
                // write before native resources are released.
                endingSession.stop(EngineSession.StopReason.ACTIVITY_DESTROYED,
                        endingSession::release);
            } else {
                endingSession.release();
            }
        }
        super.onDestroy();
    }

    @Override public void onBackPressed() {
        if (menuVisible) hidePauseMenu();
        else showPauseMenu();
    }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        int code = event.getKeyCode();
        if (code == KeyEvent.KEYCODE_BACK || code == KeyEvent.KEYCODE_MENU) {
            if (event.getAction() == KeyEvent.ACTION_UP) onBackPressed();
            return true;
        }
        if (code == KeyEvent.KEYCODE_BUTTON_SELECT || code == KeyEvent.KEYCODE_MEDIA_STOP)
            return handleStopButton(event);
        if (menuVisible) return super.dispatchKeyEvent(event);
        return session != null && session.dispatchKeyEvent(event)
                || super.dispatchKeyEvent(event);
    }

    @Override public boolean dispatchGenericMotionEvent(MotionEvent event) {
        if (!menuVisible && session != null && session.dispatchGenericMotionEvent(event))
            return true;
        return super.dispatchGenericMotionEvent(event);
    }

    @Override public void onSurfaceAvailable(Surface surface, int width, int height) {
        if (session != null) session.attachSurface(surface, width, height);
    }

    @Override public void onSurfaceSizeChanged(int width, int height) {
        if (session != null) session.resizeSurface(width, height);
    }

    @Override public void onSurfaceDestroyed() {
        if (session != null) session.detachSurface();
    }

    @Override public void onSurfaceStartupError(String message, Throwable cause) {
        surfaceStartupFailed = true;
        prepared = false;
        onSessionError(message, cause);
    }

    @Override public void onSurfaceRuntimeError(String message, Throwable cause) {
        runOnUiThread(() -> {
            if (surfaceStartupFailed || isFinishing() || exitStarted.get()) return;
            surfaceStartupFailed = true;
            prepared = false;
            if (session != null) {
                try { session.pause(EngineSession.PauseReason.ANDROID_BACKGROUND); }
                catch (RuntimeException pauseFailure) {
                    Log.e(TAG, "Could not pause after display failure", pauseFailure);
                }
            }
            showFatalError(message, cause);
        });
    }

    @Override public void onSessionReady() {
        runOnUiThread(() -> {
            if (surfaceStartupFailed) return;
            prepared = true;
            status.setVisibility(View.GONE);
            if (touchControls != null && session != null)
                touchControls.setVisibility(session.shouldShowOnScreenControls()
                        ? View.VISIBLE : View.GONE);
            if (activityResumed && !menuVisible && session != null) session.resume();
        });
    }

    @Override public void onSessionError(String message, Throwable cause) {
        if (cause instanceof com.thorium.lucent.video.RuntimePresentationFailure.Failure) {
            onSurfaceRuntimeError(cause.getMessage(), cause);
            return;
        }
        runOnUiThread(() -> showFatalError(message, cause));
    }

    @Override public void onSessionStopRejected(String message, Throwable cause) {
        runOnUiThread(() -> {
            Log.w(TAG, "Exit save rejected; gameplay retained", cause);
            exitStarted.set(false);
            menuVisible = false;
            if (pauseOverlay != null) pauseOverlay.setVisibility(View.GONE);
            if (status != null) {
                status.setText(message);
                status.setVisibility(View.VISIBLE);
                status.bringToFront();
                mainHandler.postDelayed(() -> {
                    if (!exitStarted.get() && status != null)
                        status.setVisibility(View.GONE);
                }, 3500L);
            }
        });
    }

    @Override public void onRestoreAvailabilityChanged(boolean available) {
        runOnUiThread(() -> {
            if (restoreButton != null) {
                restoreButton.setEnabled(available);
                restoreButton.setAlpha(available ? 1f : 0.45f);
            }
        });
    }

    private void buildUi() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        gameSurface = new GameSurface(this, request.frameGenerationMode);
        // The running engine, not a system-wide frontend guess, owns aspect.
        gameSurface.setDisplayAspect(0f);
        FrameLayout.LayoutParams videoParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT);
        videoParams.gravity = Gravity.CENTER;
        root.addView(gameSurface, videoParams);

        touchControls = new TouchControlsView(this);
        touchControls.setVisibility(View.GONE);
        touchControls.setListener((control, pressed) -> {
            if (session != null) session.dispatchVirtualControl(control, pressed);
        });
        root.addView(touchControls, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        status = new TextView(this);
        status.setText("Preparing " + (request.gameTitle.isEmpty() ? "game" : request.gameTitle));
        status.setTextColor(Color.WHITE);
        status.setTextSize(17f);
        status.setGravity(Gravity.CENTER);
        root.addView(status, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        pauseOverlay = createPauseOverlay();
        pauseOverlay.setVisibility(View.GONE);
        root.addView(pauseOverlay, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);
    }

    private FrameLayout createPauseOverlay() {
        FrameLayout overlay = new FrameLayout(this);
        overlay.setBackgroundColor(Color.argb(178, 0, 0, 0));
        overlay.setClickable(true);

        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(34), dp(28), dp(34), dp(30));
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(24, 24, 29));
        background.setCornerRadius(dp(20));
        background.setStroke(dp(1), Color.argb(100, 255, 255, 255));
        panel.setBackground(background);

        TextView title = new TextView(this);
        title.setText(request.gameTitle.isEmpty() ? "Paused" : request.gameTitle);
        title.setTextColor(Color.WHITE);
        title.setTextSize(24f);
        title.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        panel.addView(title, rowParams(dp(54)));

        Button resume = menuButton("Resume");
        resume.setOnClickListener(view -> hidePauseMenu());
        panel.addView(resume, rowParams(dp(58)));

        Button controls = menuButton("Controls");
        controls.setOnClickListener(view -> {
            if (session == null || !session.openControls())
                explainUnavailable("Control remapping will be supplied by InputRouter.");
        });
        panel.addView(controls, rowParams(dp(58)));

        restoreButton = menuButton("Restore earlier point");
        restoreButton.setEnabled(false);
        restoreButton.setAlpha(0.45f);
        restoreButton.setOnClickListener(view -> {
            if (session == null || !session.openRestoreHistory())
                explainUnavailable("No earlier restore points are available yet.");
        });
        panel.addView(restoreButton, rowParams(dp(58)));

        Button exit = menuButton("Exit to EmuFusion");
        exit.setTextColor(Color.rgb(255, 151, 151));
        exit.setOnClickListener(view -> exitToEmuFusion());
        panel.addView(exit, rowParams(dp(58)));

        FrameLayout.LayoutParams panelParams = new FrameLayout.LayoutParams(
                dp(420), FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER);
        overlay.addView(panel, panelParams);
        return overlay;
    }

    private Button menuButton(String label) {
        Button button = new Button(this);
        // Game launchers frequently enter this Activity in Android touch mode
        // even when the next input comes from a controller/ADB key event. Keep
        // menu actions focusable in both modes so Resume is deterministic on
        // the first ENTER press after opening the overlay.
        button.setFocusable(true);
        button.setFocusableInTouchMode(true);
        button.setAllCaps(false);
        button.setText(label);
        button.setTextSize(17f);
        button.setTextColor(Color.WHITE);
        button.setGravity(Gravity.CENTER);
        button.setFocusable(true);
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(38, 38, 45));
        background.setCornerRadius(dp(11));
        background.setStroke(dp(1), Color.argb(90, 255, 255, 255));
        button.setBackground(background);
        button.setOnFocusChangeListener((view, focused) -> {
            GradientDrawable state = new GradientDrawable();
            state.setColor(focused ? COLOR_ACCENT : Color.rgb(38, 38, 45));
            state.setCornerRadius(dp(11));
            state.setStroke(dp(1), focused ? Color.WHITE : Color.argb(90, 255, 255, 255));
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

    private void showPauseMenu() {
        if (pauseOverlay == null || menuVisible || exitStarted.get()) return;
        menuVisible = true;
        if (prepared && session != null) session.pause(EngineSession.PauseReason.LUCENT_MENU);
        pauseOverlay.setVisibility(View.VISIBLE);
        pauseOverlay.getChildAt(0).requestFocus();
        // Focus the first actual button rather than the panel container.
        View panel = pauseOverlay.getChildAt(0);
        if (panel instanceof LinearLayout && ((LinearLayout) panel).getChildCount() > 1)
            ((LinearLayout) panel).getChildAt(1).requestFocus();
        Log.i(TAG, "Pause menu shown engine=" + request.engineId +
                " system=" + request.systemId);
    }

    private void hidePauseMenu() {
        if (!menuVisible) return;
        menuVisible = false;
        pauseOverlay.setVisibility(View.GONE);
        gameSurface.requestFocus();
        enterImmersiveMode();
        if (prepared && activityResumed && session != null) session.resume();
        Log.i(TAG, "Pause menu hidden engine=" + request.engineId +
                " system=" + request.systemId);
    }

    private boolean handleStopButton(KeyEvent event) {
        if (event.getAction() == KeyEvent.ACTION_DOWN) {
            if (event.getRepeatCount() != 0) return true;
            stopPressed = true;
            stopHoldTriggered = false;
            final long generation = ++stopGeneration;
            mainHandler.postDelayed(() -> {
                if (stopPressed && generation == stopGeneration) {
                    stopHoldTriggered = true;
                    stopPressed = false;
                    exitToEmuFusion();
                }
            }, STOP_HOLD_MS);
            return true;
        }
        if (event.getAction() == KeyEvent.ACTION_UP) {
            stopPressed = false;
            ++stopGeneration;
            if (!stopHoldTriggered && session != null) {
                // Cores observe buttons by polling once per retro_run; a
                // zero-width down/up pair between two polls is invisible.
                // Latch the synthesized Select press across a few frame
                // periods so at least one poll sees it.
                final EngineSession target = session;
                final KeyEvent up = event;
                long now = event.getEventTime();
                target.dispatchKeyEvent(new KeyEvent(now, now, KeyEvent.ACTION_DOWN,
                        event.getKeyCode(), 0, event.getMetaState(), event.getDeviceId(),
                        event.getScanCode(), event.getFlags(), event.getSource()));
                mainHandler.postDelayed(() -> {
                    // If the session changed meanwhile, drop the release: the
                    // old session is retiring and a new host starts with a
                    // clean joypad mask.
                    if (session == target) target.dispatchKeyEvent(up);
                }, TAP_SELECT_HOLD_MS);
            }
            stopHoldTriggered = false;
            return true;
        }
        return true;
    }

    private void exitToEmuFusion() {
        if (!exitStarted.compareAndSet(false, true)) return;
        Log.i(TAG, "Exit to Lucent invoked engine=" + request.engineId +
                " system=" + request.systemId);
        menuVisible = false;
        if (pauseOverlay != null) pauseOverlay.setVisibility(View.VISIBLE);
        if (status != null) {
            status.setText("Saving and returning to EmuFusion…");
            status.setVisibility(View.VISIBLE);
            status.bringToFront();
        }
        if (session == null) {
            SessionReturnRouter.finishToEmuFusion(this, request.returnState);
            return;
        }
        session.stop(EngineSession.StopReason.EXIT_TO_LUCENT,
                () -> runOnUiThread(() ->
                        SessionReturnRouter.finishToEmuFusion(this, request.returnState)));
    }

    private void showFatalError(String message, Throwable cause) {
        String detail = message == null || message.trim().isEmpty()
                ? "EmuFusion could not start this game." : message;
        new AlertDialog.Builder(this)
                .setTitle(cause instanceof com.thorium.lucent.video.RuntimePresentationFailure.Failure
                        ? "Game display stopped" : "Unable to start game")
                .setMessage(detail)
                .setCancelable(false)
                .setPositiveButton("Return to EmuFusion", (dialog, which) -> {
                    SessionReturnState state = request == null
                            ? SessionReturnState.EMPTY : request.returnState;
                    SessionReturnRouter.finishToEmuFusion(this, state);
                })
                .show();
    }

    private void explainUnavailable(String message) {
        new AlertDialog.Builder(this)
                .setMessage(message)
                .setPositiveButton("OK", null)
                .show();
    }

    private void enterImmersiveMode() {
        // PhoneWindow.getInsetsController() dereferences its decor view.  The
        // first call happens before setContentView(), so explicitly create the
        // decor and query the controller from the View instead.  A controller
        // may still be unavailable until attachment; onResume retries it.
        View decor = getWindow().getDecorView();
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            android.view.WindowInsetsController controller =
                    decor.getWindowInsetsController();
            if (controller != null) {
                controller.hide(
                        WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
            }
        } else {
            decor.setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
        }
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
