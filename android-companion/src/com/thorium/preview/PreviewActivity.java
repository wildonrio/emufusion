package com.thorium.preview;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.PixelFormat;
import android.graphics.SurfaceTexture;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Bundle;
import android.os.Build;
import android.os.SystemClock;
import android.provider.Settings;
import android.view.GestureDetector;
import android.view.Display;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.SurfaceControl;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.TextureView;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.TextView;

import com.thorium.lucent.cheats.CheatPanelSnapshot;
import com.thorium.preview.cheats.CheatPanelView;
import com.thorium.preview.game.FrameGenerationRenderer;
import com.thorium.preview.game.FrameGenerationRendererFactory;
import com.thorium.preview.game.FrameGenerationSettings;
import com.thorium.preview.game.SurfaceOwnershipException;
import com.thorium.lucent.video.FrameGenerationBackendPolicy;
import com.thorium.lucent.video.DualScreenLayout;

import org.json.JSONObject;

import java.io.File;
import android.util.Log;

public final class PreviewActivity extends Activity
        implements SecondaryCheatPanelRouter.Panel,
        SecondaryGameplaySurfaceRouter.Host {
    private static volatile boolean running;
    private static volatile boolean resumed;
    private static final PreviewWindowState windowState = new PreviewWindowState();
    // True only while a dual-screen (DS/3DS/Wii U) session is rendering into
    // this Activity's SurfaceView. Anything that would take the lower display
    // — the in-app browser above all — has to yield while this is set.
    private static volatile boolean gameplaySurfaceActive;
    private static volatile PreviewActivity visibleInstance;
    private FrameLayout root;
    private ImageView artwork;
    private TextView titleView;
    private TextView scoreView;
    private TextView eyebrow;
    private TextView launchButton;
    private View blackout;
    private SurfaceView gameplaySurface;
    private Surface gameplayEngineSurface;
    private FrameGenerationRenderer gameplayFrameGenerator;
    private long gameplayGeneratorGeneration;
    // A failed retirement cannot authorize reuse of this game's holder on a
    // subsequent surfaceChanged callback. Only a new routed game may retry.
    private long gameplayQuarantinedGeneration = -1L;
    /** Owner mode frozen for this lower-display Surface generation. */
    private FrameGenerationSettings.Mode gameplayFrameGenerationMode =
            FrameGenerationSettings.Mode.OFF;
    private boolean gameplayClockwiseQuarterTurn;
    private int gameplayTouchDiagnosticCount;
    private CheatPanelView cheatPanel;
    private long gameplayGeneration;
    private PlayerSlot[] slots;
    // The primary-display reject path finishes before any of the setup below
    // runs, so onDestroy must know whether this instance ever registered its
    // receiver or claimed the static visibility flags.
    private boolean receiverRegistered;
    private boolean ownsVisibilityFlags;
    private int activeSlot = -1;
    private boolean soundEnabled;
    private float appVolumeGain = 1f;
    private final AppVolumeController.Listener appVolumeListener = gain -> {
        appVolumeGain = gain;
        applyPlayerVolumes();
    };
    // A "browser break": every decoder is held paused and silent while
    // EmuFusion's browser is open, then started again where it stopped.
    private boolean playersPaused;
    private long selectionGeneration;
    private long currentSequence;
    private boolean advanceOnCompletion;
    private GestureDetector gestures;
    private static final long CROSSFADE_MS = 85L;
    private volatile long lastLowerVisualChangeMs;
    private volatile String renderedVideoSource = "";
    private volatile int renderedVideoPositionMs;
    private volatile boolean renderedVideoAdvancing;

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (PreviewService.ACTION_CLOSE.equals(intent.getAction())) {
                stopPlayers();
                finishAndRemoveTask();
            } else if (PreviewService.ACTION_HIDE.equals(intent.getAction())) {
                // Keep this non-focusable activity resident on display 4.
                // A dual-screen emulator can cover it with its own lower-screen
                // activity; moving this task globally disrupts display 0 on the
                // Thor and sends Pegasus behind the launcher.
                blankScreen();
            } else if (PreviewService.ACTION_BLANK.equals(intent.getAction())) {
                blankScreen();
            } else if (PreviewService.ACTION_AUDIO.equals(intent.getAction())) {
                applySoundEnabled(intent.getBooleanExtra(
                        PreviewService.EXTRA_SOUND_ENABLED, false));
            } else if (PreviewService.ACTION_PAUSE.equals(intent.getAction())) {
                pausePlayers();
            } else if (PreviewService.ACTION_RESUME.equals(intent.getAction())) {
                resumePlayers();
            } else if (PreviewService.ACTION_UPDATE.equals(intent.getAction())) {
                showSelection(
                        intent.getStringExtra(PreviewService.EXTRA_VIDEO),
                        intent.getStringExtra(PreviewService.EXTRA_ART),
                        intent.getStringExtra(PreviewService.EXTRA_TITLE),
                        intent.getStringExtra(PreviewService.EXTRA_SYSTEM),
                        intent.getStringExtra(PreviewService.EXTRA_SCORE),
                        intent.getStringExtra(PreviewService.EXTRA_PRELOAD_PREV),
                        intent.getStringExtra(PreviewService.EXTRA_PRELOAD_NEXT),
                        intent.getStringExtra(PreviewService.EXTRA_PRELOAD_AUX),
                        intent.getLongExtra(PreviewService.EXTRA_SEQUENCE, 0L),
                        intent.getBooleanExtra(PreviewService.EXTRA_ADVANCE, false));
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // This Activity is only EmuFusion's private Thor lower-display surface.
        // Fail closed if a malformed internal launch ever lands it on the
        // primary display; gameplay and the library both belong to the one
        // MainActivity window there.
        Display display = getWindowManager().getDefaultDisplay();
        if (display == null || display.getDisplayId() == Display.DEFAULT_DISPLAY) {
            Log.e("LucentPreview", "Rejected PreviewActivity on primary display");
            finishAndRemoveTask();
            return;
        }
        running = true;
        visibleInstance = this;
        lastLowerVisualChangeMs = SystemClock.elapsedRealtime();
        ownsVisibilityFlags = true;
        windowState.created(this);
        // Preview audio is STREAM_MUSIC (MediaPlayer's USAGE_MEDIA attributes
        // below), the same stream the engines play on. Bind the hardware volume
        // keys to it here as well as in LucentApplication so this Activity can
        // never present a window whose keys drive an unrelated stream.
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        soundEnabled = getSharedPreferences("preview", MODE_PRIVATE)
                .getBoolean(PreviewService.EXTRA_SOUND_ENABLED, false);
        // A browser break outlives this Activity: the service records it, so a
        // lower display rebuilt mid-break comes back still and silent instead
        // of playing a movie underneath the browser.
        playersPaused = getSharedPreferences("preview", MODE_PRIVATE)
                .getBoolean(PreviewService.EXTRA_BROWSER_ACTIVE, false);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        // The lower-screen movie must never steal controller focus from
        // Pegasus on the upper display. This also stops a GamePad touch down
        // here from pulling focus across displays, because Android only moves
        // focus to a tapped window that can receive keys.
        //
        // On its own the flag is not enough, and is in fact half of the trap:
        // it guarantees this display has no focused window while the Activity
        // still gives it a focused *app*, which is the combination Android
        // reads as "top-focused display" with nothing to dispatch to. See
        // PrimaryDisplayFocusGuard, which is what actually keeps display 0 on
        // top; the two belong together.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE);
        buildUi();
        AppVolumeController.registerListener(this, appVolumeListener);
        hideSystemUi();
        // LucentApplication starts the process-wide foreground service before
        // any Activity. This visible secondary Activity only needs to deliver
        // a normal start; issuing a second foreground-service request creates
        // an independent Android deadline during process-death restoration.
        startService(new Intent(this, PreviewService.class));
        registerReceiver(receiver, new IntentFilter(PreviewService.ACTION_UPDATE));
        registerReceiver(receiver, new IntentFilter(PreviewService.ACTION_HIDE));
        registerReceiver(receiver, new IntentFilter(PreviewService.ACTION_BLANK));
        registerReceiver(receiver, new IntentFilter(PreviewService.ACTION_AUDIO));
        registerReceiver(receiver, new IntentFilter(PreviewService.ACTION_CLOSE));
        registerReceiver(receiver, new IntentFilter(PreviewService.ACTION_PAUSE));
        registerReceiver(receiver, new IntentFilter(PreviewService.ACTION_RESUME));
        receiverRegistered = true;

        gestures = new GestureDetector(this, new GestureDetector.SimpleOnGestureListener() {
            @Override
            public boolean onDown(MotionEvent event) {
                return true;
            }

            @Override
            public boolean onDoubleTap(MotionEvent event) {
                startService(new Intent(PreviewActivity.this, PreviewService.class)
                        .setAction(PreviewService.ACTION_SUSPEND));
                stopPlayers();
                // Do not move this task globally: the Thor's displays share a
                // task group, and doing so can also send Pegasus behind the
                // primary launcher. Preview placement can be switched to TOP
                // from Pegasus settings when Android is wanted below.
                return true;
            }
        });
        root.setOnTouchListener((view, event) -> gestures.onTouchEvent(event));

        if (SecondaryGameplaySurfaceRouter.ACTION_SECONDARY_GAMEPLAY.equals(
                getIntent().getAction())) {
            showGameplaySurface(getIntent().getLongExtra(
                    SecondaryGameplaySurfaceRouter.EXTRA_GENERATION, 0L));
        } else if (SecondaryCheatPanelRouter.ACTION_SECONDARY_CHEATS.equals(
                getIntent().getAction())) {
            attachCheatPanel(getIntent().getLongExtra(
                    SecondaryCheatPanelRouter.EXTRA_GENERATION, 0L));
        } else if (PreviewService.ACTION_BLANK.equals(getIntent().getAction())) {
            blankScreen();
        } else {
            SharedPreferences preferences = getSharedPreferences("preview", MODE_PRIVATE);
            showSelection(
                    value(getIntent(), preferences, PreviewService.EXTRA_VIDEO),
                    value(getIntent(), preferences, PreviewService.EXTRA_ART),
                    value(getIntent(), preferences, PreviewService.EXTRA_TITLE),
                    value(getIntent(), preferences, PreviewService.EXTRA_SYSTEM),
                    value(getIntent(), preferences, PreviewService.EXTRA_SCORE),
                    value(getIntent(), preferences, PreviewService.EXTRA_PRELOAD_PREV),
                    value(getIntent(), preferences, PreviewService.EXTRA_PRELOAD_NEXT),
                    value(getIntent(), preferences, PreviewService.EXTRA_PRELOAD_AUX),
                    longValue(getIntent(), preferences, PreviewService.EXTRA_SEQUENCE),
                    booleanValue(getIntent(), preferences, PreviewService.EXTRA_ADVANCE));
        }
    }

    private static String value(Intent intent, SharedPreferences preferences, String key) {
        String value = intent.getStringExtra(key);
        return value == null ? preferences.getString(key, "") : value;
    }

    private static long longValue(Intent intent, SharedPreferences preferences, String key) {
        return intent.hasExtra(key) ? intent.getLongExtra(key, 0L)
                : preferences.getLong(key, 0L);
    }

    private static boolean booleanValue(Intent intent, SharedPreferences preferences, String key) {
        return intent.hasExtra(key) ? intent.getBooleanExtra(key, false)
                : preferences.getBoolean(key, false);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        // A redelivery to an already-resumed singleTop Activity skips onResume,
        // but the Activity start that carried it still moved this display to
        // the top of the display order, so top focus has to be handed back here
        // too.
        if (ownsVisibilityFlags) yieldTopFocusToPrimaryDisplay();
        if (SecondaryGameplaySurfaceRouter.ACTION_SECONDARY_GAMEPLAY.equals(
                intent.getAction())) {
            showGameplaySurface(intent.getLongExtra(
                    SecondaryGameplaySurfaceRouter.EXTRA_GENERATION, 0L));
            return;
        }
        if (SecondaryCheatPanelRouter.ACTION_SECONDARY_CHEATS.equals(
                intent.getAction())) {
            attachCheatPanel(intent.getLongExtra(
                    SecondaryCheatPanelRouter.EXTRA_GENERATION, 0L));
            return;
        }
        if (PreviewService.ACTION_BLANK.equals(intent.getAction())) {
            blankScreen();
            return;
        }
        showSelection(
                safe(intent.getStringExtra(PreviewService.EXTRA_VIDEO)),
                safe(intent.getStringExtra(PreviewService.EXTRA_ART)),
                safe(intent.getStringExtra(PreviewService.EXTRA_TITLE)),
                safe(intent.getStringExtra(PreviewService.EXTRA_SYSTEM)),
                safe(intent.getStringExtra(PreviewService.EXTRA_SCORE)),
                safe(intent.getStringExtra(PreviewService.EXTRA_PRELOAD_PREV)),
                safe(intent.getStringExtra(PreviewService.EXTRA_PRELOAD_NEXT)),
                safe(intent.getStringExtra(PreviewService.EXTRA_PRELOAD_AUX)),
                intent.getLongExtra(PreviewService.EXTRA_SEQUENCE, 0L),
                intent.getBooleanExtra(PreviewService.EXTRA_ADVANCE, false));
    }

    private void buildUi() {
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(6, 8, 12));
        setContentView(root);

        GradientDrawable gradient = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                new int[]{Color.rgb(17, 23, 34), Color.rgb(5, 7, 11)});
        root.setBackground(gradient);

        artwork = new ImageView(this);
        artwork.setScaleType(ImageView.ScaleType.CENTER_CROP);
        artwork.setColorFilter(Color.argb(110, 0, 0, 0));
        root.addView(artwork, fill());

        slots = new PlayerSlot[]{
                new PlayerSlot(), new PlayerSlot(), new PlayerSlot(), new PlayerSlot()};
        root.addView(slots[0].view, fill());
        root.addView(slots[1].view, fill());
        root.addView(slots[2].view, fill());
        root.addView(slots[3].view, fill());

        eyebrow = new TextView(this);
        eyebrow.setText("");
        eyebrow.setTextColor(Color.WHITE);
        eyebrow.setTextSize(13);
        eyebrow.setLetterSpacing(0.16f);
        eyebrow.setPadding(dp(24), dp(18), dp(24), 0);
        root.addView(eyebrow, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, dp(58)));

        titleView = new TextView(this);
        titleView.setTextColor(Color.WHITE);
        titleView.setTextSize(22);
        titleView.setMaxLines(2);
        titleView.setGravity(android.view.Gravity.BOTTOM);
        titleView.setShadowLayer(10, 0, 2, Color.BLACK);
        titleView.setPadding(dp(24), 0, dp(210), dp(4));
        FrameLayout.LayoutParams titleParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, dp(96));
        titleParams.gravity = android.view.Gravity.BOTTOM;
        titleParams.bottomMargin = dp(38);
        root.addView(titleView, titleParams);

        scoreView = new TextView(this);
        scoreView.setTextColor(Color.WHITE);
        scoreView.setTextSize(14);
        scoreView.setSingleLine(true);
        scoreView.setLetterSpacing(0.07f);
        scoreView.setShadowLayer(9, 0, 2, Color.BLACK);
        scoreView.setPadding(dp(24), 0, dp(210), dp(18));
        scoreView.setGravity(android.view.Gravity.BOTTOM);
        FrameLayout.LayoutParams scoreParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, dp(50));
        scoreParams.gravity = android.view.Gravity.BOTTOM;
        root.addView(scoreView, scoreParams);

        launchButton = new TextView(this);
        launchButton.setText("PLAY NOW");
        launchButton.setTextColor(Color.WHITE);
        launchButton.setTextSize(14);
        launchButton.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        launchButton.setLetterSpacing(0.10f);
        launchButton.setGravity(android.view.Gravity.CENTER);
        launchButton.setClickable(true);
        launchButton.setFocusable(false);
        launchButton.setContentDescription("Play the previewed game now");
        GradientDrawable launchBackground = new GradientDrawable();
        launchBackground.setColor(Color.argb(138, 8, 12, 19));
        launchBackground.setStroke(dp(1), Color.argb(185, 255, 255, 255));
        launchBackground.setCornerRadius(dp(18));
        launchButton.setBackground(launchBackground);
        launchButton.setOnClickListener(view -> requestLaunch());
        FrameLayout.LayoutParams launchParams = new FrameLayout.LayoutParams(
                dp(164), dp(48));
        launchParams.gravity = android.view.Gravity.BOTTOM | android.view.Gravity.RIGHT;
        launchParams.rightMargin = dp(24);
        launchParams.bottomMargin = dp(18);
        root.addView(launchButton, launchParams);

        // An OLED-black surface replaces the preview while a single-screen
        // game is running. Keeping it in this task avoids exposing a launcher
        // or stale artwork on the lower display.
        blackout = new View(this);
        blackout.setBackgroundColor(Color.BLACK);
        blackout.setVisibility(View.GONE);
        root.addView(blackout, fill());

        // Added last so it covers the blackout a running game leaves behind:
        // this panel is only ever shown while a game owns the upper display,
        // which is exactly when the blackout is up.
        cheatPanel = new CheatPanelView(this);
        cheatPanel.setVisibility(View.GONE);
        cheatPanel.setListener(new CheatPanelView.Listener() {
            @Override public void onCheatRowTapped(int index) {
                SecondaryCheatPanelRouter.toggled(index);
            }

            @Override public void onCloseTapped() {
                SecondaryCheatPanelRouter.closedFromPanel();
            }
        });
        root.addView(cheatPanel, fill());
    }

    private FrameLayout.LayoutParams fill() {
        return new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void showSelection(String video, String art, String title,
                               String system, String score,
                               String preloadPrev, String preloadNext, String preloadAux,
                               long sequence, boolean advance) {
        // A dual-screen game owns this display until it hands it back. A
        // preview selection arriving mid-session — the Pegasus heartbeat
        // resurrecting playback, the 750 ms watchdog, a late ACTION_UPDATE —
        // must not evict its Surface, or the engine goes on rendering a lower
        // screen nobody can see for the rest of the session. The selection is
        // already persisted, so the session's own teardown (ACTION_BLANK from
        // SecondaryGameplaySurfaceRouter.release) shows it a moment later.
        if (gameplaySurface != null) return;
        // Same rule for the cheat panel, for the same reason and one more: the
        // panel is opaque, so a selection arriving underneath it would start a
        // preview movie nobody can see while its audio plays over the game.
        if (cheatPanel != null && cheatPanel.getVisibility() == View.VISIBLE) return;
        leaveGameplaySurface(true);
        final long generation = ++selectionGeneration;
        video = safe(video);
        art = safe(art);
        title = safe(title);
        system = safe(system);
        score = safe(score);
        currentSequence = sequence;
        advanceOnCompletion = advance;
        preloadPrev = safe(preloadPrev);
        preloadNext = safe(preloadNext);
        preloadAux = safe(preloadAux);
        renderedVideoSource = video;
        renderedVideoPositionMs = 0;
        renderedVideoAdvancing = false;
        lastLowerVisualChangeMs = SystemClock.elapsedRealtime();
        eyebrow.setText(system);
        titleView.setText(title);
        scoreView.setText(score);
        launchButton.setText("PLAY NOW");
        launchButton.setEnabled(sequence > 0L && !title.isEmpty());
        launchButton.setAlpha(launchButton.isEnabled() ? 1f : 0f);
        launchButton.setVisibility(launchButton.isEnabled() ? View.VISIBLE : View.GONE);
        loadArtwork(art);

        final int outgoingIndex = activeSlot;
        // Keep the outgoing decoded frame alive until the replacement has
        // actually rendered. Releasing it here exposed the window background
        // for roughly half a second on a cold decoder.
        releaseUnwanted(video, preloadPrev, preloadNext, preloadAux, outgoingIndex);
        int incomingIndex = ensureSlot(video);
        ensurePreload(preloadPrev, incomingIndex, outgoingIndex);
        ensurePreload(preloadNext, incomingIndex, outgoingIndex);
        ensurePreload(preloadAux, incomingIndex, outgoingIndex);

        if (video.isEmpty() || incomingIndex < 0) {
            renderedVideoSource = "";
            activeSlot = -1;
            applyPlayerVolumes();
            for (PlayerSlot slot : slots) slot.view.setAlpha(0f);
            artwork.animate().alpha(1f).setDuration(120).start();
            blackout.setVisibility(View.GONE);
            return;
        }

        artwork.animate().cancel();
        blackout.setVisibility(View.GONE);
        final PlayerSlot incoming = slots[incomingIndex];
        incoming.setLooping(!advanceOnCompletion);
        final String selectedVideo = video;
        final String selectedPrevious = preloadPrev;
        final String selectedNext = preloadNext;
        final String selectedAuxiliary = preloadAux;
        activeSlot = incomingIndex;
        final PlayerSlot outgoing = outgoingIndex >= 0 && outgoingIndex < slots.length
                && outgoingIndex != incomingIndex ? slots[outgoingIndex] : null;
        if (outgoing != null) outgoing.setLooping(true);
        // A warm neighbor is already advancing while transparent. A cold
        // selection keeps either the outgoing movie or its artwork visible;
        // normal browsing never reveals the black launch-time cover.
        if (outgoing == null && !incoming.firstFrameRendered) artwork.setAlpha(1f);
        incoming.activate(() -> {
            if (generation != selectionGeneration) return;
            incoming.view.animate().cancel();
            incoming.view.setVisibility(View.VISIBLE);
            raiseVideoBelowChrome(incoming.view);
            if (outgoing != null) {
                outgoing.view.animate().cancel();
                outgoing.view.animate().alpha(0f).setDuration(CROSSFADE_MS).start();
            }
            incoming.view.animate().alpha(1f).setDuration(CROSSFADE_MS).start();
            artwork.animate().alpha(0f).setDuration(CROSSFADE_MS).start();
            activeSlot = incomingIndex;
            applyPlayerVolumes();
            blackout.setVisibility(View.GONE);
            root.postDelayed(() -> {
                if (generation != selectionGeneration) return;
                releaseUnwanted(selectedVideo, selectedPrevious, selectedNext,
                        selectedAuxiliary, incomingIndex);
                // If the outgoing hold temporarily consumed the fourth decoder,
                // fill the auxiliary warm slot as soon as the crossfade ends.
                ensurePreload(selectedAuxiliary, incomingIndex, -1);
            }, CROSSFADE_MS + 8L);
        });
    }

    private void raiseVideoBelowChrome(TextureView view) {
        view.bringToFront();
        eyebrow.bringToFront();
        titleView.bringToFront();
        scoreView.bringToFront();
        launchButton.bringToFront();
        blackout.bringToFront();
    }

    private void requestLaunch() {
        final long sequence = currentSequence;
        if (sequence <= 0L || !launchButton.isEnabled()) return;
        launchButton.setEnabled(false);
        launchButton.setText("LAUNCHING…");
        startService(new Intent(this, PreviewService.class)
                .setAction(PreviewService.ACTION_LAUNCH)
                .putExtra(PreviewService.EXTRA_SEQUENCE, sequence));
        launchButton.postDelayed(() -> {
            if (currentSequence != sequence || blackout.getVisibility() == View.VISIBLE)
                return;
            launchButton.setText("PLAY NOW");
            launchButton.setEnabled(true);
        }, 1200L);
    }

    private boolean wanted(String source, String current, String previous,
                           String next, String auxiliary) {
        return !source.isEmpty() && (source.equals(current) || source.equals(previous)
                || source.equals(next) || source.equals(auxiliary));
    }

    private void releaseUnwanted(String current, String previous,
                                 String next, String auxiliary, int protectedIndex) {
        for (int i = 0; i < slots.length; ++i) {
            PlayerSlot slot = slots[i];
            if (i == protectedIndex) continue;
            if (!slot.source.isEmpty()
                    && !wanted(slot.source, current, previous, next, auxiliary)) {
                slot.release();
            }
        }
    }

    private int ensureSlot(String source) {
        source = safe(source);
        if (source.isEmpty()) return -1;
        for (int i = 0; i < slots.length; ++i) {
            if (source.equals(slots[i].source)) return i;
        }
        for (int i = 0; i < slots.length; ++i) {
            if (slots[i].source.isEmpty()) {
                slots[i].prepare(source);
                return i;
            }
        }
        int replacement = activeSlot == 0 ? 1 : 0;
        slots[replacement].prepare(source);
        return replacement;
    }

    private int ensurePreload(String source, int protectedA, int protectedB) {
        source = safe(source);
        if (source.isEmpty()) return -1;
        for (int i = 0; i < slots.length; ++i) {
            if (source.equals(slots[i].source)) return i;
        }
        for (int i = 0; i < slots.length; ++i) {
            if (i != protectedA && i != protectedB && slots[i].source.isEmpty()) {
                slots[i].prepare(source);
                return i;
            }
        }
        // Never evict the current or outgoing picture merely to warm an
        // auxiliary candidate. The next request will free a stale slot.
        return -1;
    }

    private void loadArtwork(String source) {
        String path = localPath(source);
        if (!path.isEmpty() && new File(path).isFile()) {
            artwork.setImageURI(Uri.fromFile(new File(path)));
        } else {
            artwork.setImageDrawable(null);
        }
        artwork.setAlpha(1f);
    }

    private void stopPlayers() {
        // The reject path skips buildUi, so the slots may never exist.
        if (slots == null) return;
        for (PlayerSlot slot : slots) slot.release();
        activeSlot = -1;
        renderedVideoSource = "";
        renderedVideoPositionMs = 0;
        renderedVideoAdvancing = false;
        lastLowerVisualChangeMs = SystemClock.elapsedRealtime();
    }

    private void applySoundEnabled(boolean enabled) {
        soundEnabled = enabled;
        applyPlayerVolumes();
    }

    /** Holds every decoder where it stands for a browser break.
     *
     * Pausing rather than releasing is deliberate. release() would drop the
     * decoded frame and leave the window background exposed, and returning
     * from the browser would then need a cold prepareAsync behind that black
     * window. A paused MediaPlayer keeps its last frame on screen and resumes
     * with a single start(), so the break is silent and still rather than
     * blank, and the return is immediate. */
    private void pausePlayers() {
        if (playersPaused) return;
        playersPaused = true;
        renderedVideoAdvancing = false;
        // Mute first: a decoder that pause() refuses (an unprepared warm
        // neighbour, say) must still not be audible under the browser.
        applyPlayerVolumes();
        if (slots == null) return;
        for (PlayerSlot slot : slots) slot.pause();
    }

    private void resumePlayers() {
        if (!playersPaused) return;
        playersPaused = false;
        if (slots != null)
            for (PlayerSlot slot : slots) slot.resume();
        applyPlayerVolumes();
    }

    private void applyPlayerVolumes() {
        if (slots == null) return;
        for (int index = 0; index < slots.length; ++index) {
            MediaPlayer player = slots[index].player;
            if (player == null) continue;
            float volume = soundEnabled && !playersPaused && index == activeSlot
                    ? appVolumeGain : 0f;
            try {
                player.setVolume(volume, volume);
            } catch (RuntimeException ignored) {
            }
        }
    }

    /**
     * Takes the cheat panel: this Activity draws it, the game host owns it.
     *
     * <p>The registration is what closes the gap between the launch and the
     * first frame — the router replays the snapshot it was given at request
     * time, so the panel never appears blank while it waits to be told what to
     * show.
     */
    private void attachCheatPanel(long generation) {
        if (cheatPanel == null) return;
        // The lower display is blank during single-screen gameplay, which is
        // when this opens; the movie views underneath are already stopped.
        ++selectionGeneration;
        stopPlayers();
        blackout.setVisibility(View.VISIBLE);
        SecondaryCheatPanelRouter.attach(generation, this);
    }

    @Override public void showCheatPanel(CheatPanelSnapshot snapshot) {
        runOnUiThread(() -> {
            if (cheatPanel == null) return;
            cheatPanel.render(snapshot);
            cheatPanel.setVisibility(View.VISIBLE);
            cheatPanel.bringToFront();
        });
    }

    @Override public void hideCheatPanel() {
        runOnUiThread(() -> {
            if (cheatPanel == null) return;
            cheatPanel.setVisibility(View.GONE);
            // Back to the black the game left here. The library restores the
            // real preview when it comes back, via its own ACTION_UPDATE.
            blackout.setVisibility(View.VISIBLE);
            blackout.bringToFront();
        });
    }

    private void blankScreen() {
        // Starting an in-window game and hiding the ordinary preview are two
        // independently posted operations.  For a dual-screen system the
        // gameplay request can win that race and install its Surface before
        // the older preview HIDE/BLANK broadcast reaches this Activity.  Do
        // not let that stale preview command tear down the current lower
        // screen.  SecondaryGameplaySurfaceRouter.release() invalidates the
        // generation before sending its own BLANK, so real game teardown
        // still follows the normal path below.
        if (gameplaySurface != null &&
                SecondaryGameplaySurfaceRouter.isCurrent(gameplayGeneration)) {
            Log.i("LucentPreview", "Ignoring preview blank while gameplay owns generation=" +
                    gameplayGeneration);
            return;
        }
        leaveGameplaySurface(false);
        if (cheatPanel != null) cheatPanel.setVisibility(View.GONE);
        ++selectionGeneration;
        stopPlayers();
        artwork.setImageDrawable(null);
        titleView.setText("");
        eyebrow.setText("");
        currentSequence = 0L;
        advanceOnCompletion = false;
        launchButton.setVisibility(View.GONE);
        blackout.setVisibility(View.VISIBLE);
        blackout.bringToFront();
    }

    private void showGameplaySurface(long generation) {
        if (generation <= 0L ||
                !SecondaryGameplaySurfaceRouter.isCurrent(generation)) {
            blankScreen();
            return;
        }
        leaveGameplaySurface(false);
        ++selectionGeneration;
        stopPlayers();
        artwork.setVisibility(View.GONE);
        eyebrow.setVisibility(View.GONE);
        titleView.setVisibility(View.GONE);
        scoreView.setVisibility(View.GONE);
        launchButton.setVisibility(View.GONE);
        blackout.setVisibility(View.GONE);
        gameplayGeneration = generation;
        // FG is primary-only until secondary retirement/recovery is qualified.
        // A failed lower generator otherwise freezes touch-screen content even
        // after the primary recovers to Direct. Preserve the native lower path
        // and leave the owner's primary FG selection unchanged.
        gameplayFrameGenerationMode = FrameGenerationSettings.Mode.OFF;
        final long surfaceGeneration = generation;
        gameplaySurfaceActive = true;
        gameplayClockwiseQuarterTurn =
                SecondaryGameplaySurfaceRouter.isClockwiseQuarterTurn(generation);
        Log.i("LucentPreview", "showGameplaySurface generation=" + generation +
                " displayId=" + (getDisplay() == null ? -1 : getDisplay().getDisplayId()) +
                " clockwiseQuarterTurn=" + gameplayClockwiseQuarterTurn);
        if (gameplayClockwiseQuarterTurn) {
            showClockwiseGameplaySurface();
            return;
        }
        gameplaySurface = new SurfaceView(this);
        // DisplayFrameGenerator deliberately selects an 8-bit RGBA EGLConfig.
        // SurfaceView otherwise defaults to the Thor's RGB565 buffer format on
        // display 4.  That mismatch still permits successful swaps and a live
        // SurfaceFlinger cadence while the hardware composer scans out black,
        // which is precisely what the DS qualification evidence recorded.
        // Fix the BufferQueue format before attachment/surface creation so the
        // EGL producer and the physical lower-display consumer agree.
        gameplaySurface.getHolder().setFormat(PixelFormat.RGBA_8888);
        // Compose this Surface ABOVE the window, and give it no View background.
        //
        // Both halves are load-bearing, and either one alone renders a
        // perfectly good frame invisible. setZOrderMediaOverlay(true) puts the
        // Surface at sublayer -1 — above other media Surfaces but *below* this
        // Activity's window — so the window has to keep a transparent hole
        // punched wherever the SurfaceView sits. Giving a View a background
        // clears PFLAG_SKIP_DRAW, which moves that hole punch out of
        // dispatchDraw() and into draw(); draw() punches the hole and then
        // calls View.draw(), which immediately repaints the very same
        // rectangle with the background. The window ends up opaque black
        // directly over the Surface.
        //
        // That is exactly what the Thor showed: SurfaceFlinger had the
        // 1240x1080 RGB_565 gameplay layer present, opaque and composited on
        // display 4 underneath a full-screen window layer, melonDS reported
        // its 256x192 bottom crop drawn with drawFrame returning true, and the
        // physical lower screen read a uniform #000000 — not even the root
        // gradient, which proves the hole was punched and then refilled.
        // setZOrderOnTop lifts the Surface above the window altogether, so no
        // hole is needed and no sibling view — the root gradient, the
        // blackout, the artwork, a preview TextureView — can cover it again.
        gameplaySurface.setZOrderOnTop(true);
        gameplaySurface.setFocusable(false);
        gameplaySurface.setFocusableInTouchMode(false);
        gameplaySurface.getHolder().addCallback(new SurfaceHolder.Callback() {
            @Override public void surfaceCreated(SurfaceHolder holder) {
                if (surfaceGeneration != gameplayGeneration ||
                        gameplayQuarantinedGeneration == surfaceGeneration) return;
                ensureGameplayGenerator(holder.getSurface(),
                        gameplaySurface.getWidth(), gameplaySurface.getHeight());
                Log.i("LucentPreview", "gameplay surfaceCreated generation=" + surfaceGeneration +
                        " size=" + gameplaySurface.getWidth() + "x" + gameplaySurface.getHeight() +
                        " valid=" + holder.getSurface().isValid() + " -> surfaceAvailable");
                SecondaryGameplaySurfaceRouter.surfaceAvailable(surfaceGeneration,
                        gameplayEngineSurface, gameplaySurface.getWidth(),
                        gameplaySurface.getHeight());
            }

            @Override public void surfaceChanged(
                    SurfaceHolder holder, int format, int width, int height) {
                if (surfaceGeneration != gameplayGeneration ||
                        gameplayQuarantinedGeneration == surfaceGeneration) return;
                if (gameplayFrameGenerator == null)
                    ensureGameplayGenerator(holder.getSurface(), width, height);
                else gameplayFrameGenerator.resize(width, height, width, height,
                        displayRefreshRate());
                Log.i("LucentPreview", "gameplay surfaceChanged generation=" + surfaceGeneration +
                        " size=" + width + "x" + height +
                        " valid=" + holder.getSurface().isValid() + " -> surfaceAvailable");
                SecondaryGameplaySurfaceRouter.surfaceAvailable(surfaceGeneration,
                        gameplayEngineSurface, width, height);
            }

            @Override public void surfaceDestroyed(SurfaceHolder holder) {
                // Synchronous and bounded: the Surface dies when this
                // callback returns, so the engine must detach first.
                Log.i("LucentPreview", "gameplay surfaceDestroyed generation=" + surfaceGeneration);
                SecondaryGameplaySurfaceRouter.surfaceDestroyed(surfaceGeneration);
                releaseGameplayGenerator(surfaceGeneration);
            }
        });
        gameplaySurface.setOnTouchListener((view, event) -> {
            int width = Math.max(1, view.getWidth());
            int height = Math.max(1, view.getHeight());
            int action = event.getActionMasked();
            boolean pressed = action != MotionEvent.ACTION_UP &&
                    action != MotionEvent.ACTION_CANCEL;
            float normalizedX = event.getX() / width;
            float normalizedY = event.getY() / height;
            if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_UP)
                Log.i("LucentPreview", "Secondary gameplay touch view=" + width +
                        "x" + height + " normalized=" + normalizedX + "," +
                        normalizedY + " pressed=" + pressed);
            SecondaryGameplaySurfaceRouter.touch(surfaceGeneration,
                    normalizedX, normalizedY, pressed);
            return true;
        });
        root.addView(gameplaySurface, fill());
        gameplaySurface.bringToFront();
    }

    private void showClockwiseGameplaySurface() {
        final long surfaceGeneration = gameplayGeneration;
        /*
         * SurfaceView.setRotation() only transforms the View hierarchy on the
         * Thor; the independently composed SurfaceControl buffer remains
         * sideways.  Give SurfaceFlinger a portrait producer buffer and apply
         * BUFFER_TRANSFORM_ROTATE_90 to that buffer itself.  The layer remains
         * a normal full-display landscape View, so its transformed 1240x1080
         * buffer covers display 4 exactly.
         */
        gameplaySurface = new SurfaceView(this);
        gameplaySurface.getHolder().setFormat(PixelFormat.RGBA_8888);
        Display display = getDisplay();
        int panelWidth = display == null ? Math.max(1, root.getWidth()) :
                display.getMode().getPhysicalWidth();
        int panelHeight = display == null ? Math.max(1, root.getHeight()) :
                display.getMode().getPhysicalHeight();
        // The Thor reports display 4's physical mode as 1080x1240 (the panel
        // is mounted portrait and Android rotates it to a 1240x1080 logical
        // landscape display), so swapping "width" and "height" produced the
        // landscape 1240x1080 buffer the harness rejected (n3ds-b50b,
        // 2026-09-02).  The producer buffer must be portrait whichever way
        // the mode is reported: shorter edge wide, longer edge tall.
        int portraitWidth = Math.min(panelWidth, panelHeight);
        int portraitHeight = Math.max(panelWidth, panelHeight);
        gameplaySurface.getHolder().setFixedSize(portraitWidth, portraitHeight);
        gameplaySurface.setZOrderOnTop(true);
        gameplaySurface.setFocusable(false);
        gameplaySurface.setFocusableInTouchMode(false);
        final SurfaceView surfaceOwner = gameplaySurface;
        gameplaySurface.getHolder().addCallback(new SurfaceHolder.Callback() {
            @Override public void surfaceCreated(SurfaceHolder holder) {
                if (surfaceGeneration != gameplayGeneration ||
                        gameplayQuarantinedGeneration == surfaceGeneration) return;
                if (Build.VERSION.SDK_INT >= 29) {
                    // SurfaceView applies its own geometry transaction after
                    // surfaceCreated. Queue ours behind it; applying here is
                    // deterministically overwritten on Thor's Android 13.
                    postClockwiseSurfaceTransform(surfaceOwner, surfaceGeneration);
                }
                int width = Math.max(1, holder.getSurfaceFrame().width());
                int height = Math.max(1, holder.getSurfaceFrame().height());
                ensureGameplayGenerator(holder.getSurface(), width, height);
                Log.i("LucentPreview", "clockwise gameplay surfaceCreated generation=" +
                        surfaceGeneration + " buffer=" + width + "x" + height);
                SecondaryGameplaySurfaceRouter.surfaceAvailable(surfaceGeneration,
                        gameplayEngineSurface, width, height);
            }

            @Override public void surfaceChanged(
                    SurfaceHolder holder, int format, int width, int height) {
                if (surfaceGeneration != gameplayGeneration ||
                        gameplayQuarantinedGeneration == surfaceGeneration) return;
                if (gameplayFrameGenerator == null)
                    ensureGameplayGenerator(holder.getSurface(), width, height);
                else gameplayFrameGenerator.resize(width, height, width, height,
                        displayRefreshRate());
                SecondaryGameplaySurfaceRouter.surfaceAvailable(surfaceGeneration,
                        gameplayEngineSurface, width, height);
            }

            @Override public void surfaceDestroyed(SurfaceHolder holder) {
                SecondaryGameplaySurfaceRouter.surfaceDestroyed(surfaceGeneration);
                releaseGameplayGenerator(surfaceGeneration);
            }
        });
        gameplaySurface.setOnTouchListener((view, event) -> {
            int width = Math.max(1, view.getWidth());
            int height = Math.max(1, view.getHeight());
            // The visible 4:3 image is contained in the logical landscape
            // display, independently of the portrait producer buffer. Exclude
            // its bars before mapping into Azahar's SideScreen touch region.
            DualScreenLayout.TouchPoint point = DualScreenLayout.threeDsTouchPoint(
                    event.getX(), event.getY(), width, height);
            int action = event.getActionMasked();
            boolean pressed = point.inside && action != MotionEvent.ACTION_UP &&
                    action != MotionEvent.ACTION_CANCEL;
            if (gameplayTouchDiagnosticCount < 12 &&
                    (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_UP ||
                            action == MotionEvent.ACTION_CANCEL)) {
                gameplayTouchDiagnosticCount++;
                Log.i("LucentPreview", "3DS touch action=" + action + " view=" +
                        width + "x" + height + " raw=" + event.getX() + "," + event.getY() +
                        " normalized=" + point.x + "," + point.y + " pressed=" + pressed);
            }
            SecondaryGameplaySurfaceRouter.touch(surfaceGeneration,
                    point.x, point.y, pressed);
            return true;
        });
        FrameLayout.LayoutParams params = fill();
        params.gravity = Gravity.CENTER;
        root.addView(gameplaySurface, params);
        gameplaySurface.bringToFront();
    }

    private void postClockwiseSurfaceTransform(SurfaceView owner, long generation) {
        owner.post(() -> {
            // Sleep/recreation can retire this View before its posted geometry
            // transaction runs. Never dereference the mutable current holder,
            // nor apply an old transaction to a replacement from the same game.
            if (gameplaySurface != owner || gameplayGeneration != generation ||
                    gameplayQuarantinedGeneration == generation ||
                    !SecondaryGameplaySurfaceRouter.isCurrent(generation) ||
                    !owner.isAttachedToWindow()) return;
            SurfaceControl control = owner.getSurfaceControl();
            if (control == null || !control.isValid()) return;
            try (SurfaceControl.Transaction transaction = new SurfaceControl.Transaction()) {
                transaction.setBufferTransform(control,
                        SurfaceControl.BUFFER_TRANSFORM_ROTATE_90).apply();
            }
        });
    }

    private void ensureGameplayGenerator(Surface output, int width, int height) {
        ensureGameplayGenerator(output, width, height, width, height);
    }

    private void ensureGameplayGenerator(Surface output, int inputWidth, int inputHeight,
                                         int outputWidth, int outputHeight) {
        if (gameplayQuarantinedGeneration == gameplayGeneration) return;
        // SurfaceView normally reports surfaceChanged immediately after
        // surfaceCreated with the same dimensions. Replacing the generator in
        // that second callback releases gameplayEngineSurface after the first
        // callback has already handed it to the engine. The Wii U session then
        // waits for a lower target which we ourselves destroyed. Preserve one
        // producer surface for one holder generation; surfaceChanged resizes
        // the existing generator through the branch above.
        if (gameplayFrameGenerator != null || gameplayEngineSurface != null) return;
        FrameGenerationBackendPolicy.Selection selection =
                FrameGenerationSettings.selectBackendForSession(
                        this, gameplayFrameGenerationMode);
        if (selection.backend == FrameGenerationBackendPolicy.Backend.DIRECT) {
            Log.i("LucentPreview",
                    "Lower display uses Direct; frame generation is primary-only");
            gameplayEngineSurface = output;
            gameplayGeneratorGeneration = gameplayGeneration;
            return;
        }
        try {
            // The secondary generator must carry the SAME dense/variant
            // switches as the primary: the one-switch constructor hardwires
            // the dense pyramid off, so the lower screen could never emit
            // schema-39 evidence and dual-screen qualification had no
            // secondary records (physically hit on DS/melonDS runs,
            // 2026-08-15/16).
            gameplayFrameGenerator = FrameGenerationRendererFactory.create(selection, output,
                    inputWidth, inputHeight, outputWidth, outputHeight,
                    displayRefreshRate(), "secondary", displayId(),
                    this::qualificationProofEnabled,
                    this::densePyramidEnabled,
                    this::denseV27ReducedAnalysisEnabled,
                    this::denseV28ReducedAnalysisEnabled);
            gameplayEngineSurface = gameplayFrameGenerator.inputSurface();
            gameplayGeneratorGeneration = gameplayGeneration;
            bindGameplayRuntimeErrorListener(gameplayFrameGenerator, gameplayGeneration);
        } catch (RuntimeException failure) {
            FrameGenerationRenderer partial = gameplayFrameGenerator;
            gameplayFrameGenerator = null;
            if (partial != null) {
                try { partial.close(); }
                catch (RuntimeException cleanupFailure) {
                    failure.addSuppressed(new SurfaceOwnershipException(
                            "Lower-screen generator did not release its output", cleanupFailure));
                }
            }
            if (SurfaceOwnershipException.isUnsafe(failure)) {
                quarantineGameplayGenerator(gameplayGeneration, failure);
                return;
            }
            Log.e("LucentPreview",
                    "Lower-screen frame generation unavailable; using direct presentation",
                    failure);
            gameplayEngineSurface = output;
            gameplayGeneratorGeneration = gameplayGeneration;
        }
    }

    private void quarantineGameplayGenerator(long failedGeneration, Throwable failure) {
        boolean firstFailure = gameplayQuarantinedGeneration != failedGeneration;
        gameplayQuarantinedGeneration = failedGeneration;
        gameplayFrameGenerator = null;
        gameplayEngineSurface = null;
        gameplayGeneratorGeneration = failedGeneration;
        Log.e("LucentPreview", "Lower-screen output ownership is unresolved; no Surface handoff" +
                " generation=" + failedGeneration, failure);
        if (firstFailure)
            SecondaryGameplaySurfaceRouter.surfaceFailed(failedGeneration, failure);
    }

    private void bindGameplayRuntimeErrorListener(FrameGenerationRenderer renderer,
                                                  long ownerGeneration) {
        renderer.setRuntimeErrorListener((message, cause) -> runOnUiThread(() -> {
            if (renderer != gameplayFrameGenerator || ownerGeneration != gameplayGeneration ||
                    ownerGeneration != gameplayGeneratorGeneration ||
                    gameplayQuarantinedGeneration == ownerGeneration) return;
            gameplayQuarantinedGeneration = ownerGeneration;
            // Preserve the renderer reference until the existing generation-
            // checked retirement path drains it. Never reuse this output as Direct.
            Log.e("LucentPreview", "Lower-screen runtime display failed generation=" +
                    ownerGeneration, cause);
            SecondaryGameplaySurfaceRouter.surfaceFailed(ownerGeneration, cause);
        }));
    }

    private void releaseGameplayGenerator(long ownerGeneration) {
        if (ownerGeneration != gameplayGeneratorGeneration) {
            Log.i("LucentPreview", "Ignoring stale gameplay surface destruction candidate=" +
                    ownerGeneration + " owner=" + gameplayGeneratorGeneration);
            return;
        }
        releaseGameplayGenerator();
    }

    private void releaseGameplayGenerator() {
        long retiringGeneration = gameplayGeneratorGeneration;
        FrameGenerationRenderer generator = gameplayFrameGenerator;
        gameplayFrameGenerator = null;
        gameplayEngineSurface = null;
        if (generator != null) {
            try { generator.close(); }
            catch (RuntimeException failure) {
                quarantineGameplayGenerator(retiringGeneration, new SurfaceOwnershipException(
                        "Lower-screen generator retirement failed", failure));
                return;
            }
        }
        gameplayGeneratorGeneration = 0L;
    }

    private float displayRefreshRate() {
        Display display = getDisplay();
        return display == null ? 60f : display.getRefreshRate();
    }

    private int displayId() {
        Display display = getDisplay();
        return display == null ? Display.DEFAULT_DISPLAY : display.getDisplayId();
    }

    /** Shell-only qualification instrumentation; never a user-facing option. */
    private boolean qualificationProofEnabled() {
        try {
            return Settings.Global.getInt(getContentResolver(),
                    "emufusion_framegen_proof", 0) == 1;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private boolean densePyramidEnabled() {
        if (!qualificationProofEnabled()) return false;
        return rawDensePyramidRequested();
    }

    /** Raw shell preselection used only before the generator allocates resources. */
    private boolean rawDensePyramidRequested() {
        try {
            return Settings.Global.getInt(getContentResolver(),
                    "emufusion_framegen_dense_pyramid", 0) == 1;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    /** Pre-launch-only v27 qualification arm; default and v26 stay unchanged. */
    private boolean denseV27ReducedAnalysisEnabled() {
        if (!rawDensePyramidRequested()) return false;
        try {
            return Settings.Global.getInt(getContentResolver(),
                    "emufusion_framegen_dense_v27_192", 0) == 1;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    /** Pre-launch-only v28 qualification arm; default/v26/v27 stay unchanged. */
    private boolean denseV28ReducedAnalysisEnabled() {
        if (!rawDensePyramidRequested()) return false;
        try {
            return Settings.Global.getInt(getContentResolver(),
                    "emufusion_framegen_dense_v28_160", 0) == 1;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private void leaveGameplaySurface(boolean restorePreviewViews) {
        boolean heldGameplaySurface = false;
        SurfaceView existing = gameplaySurface;
        if (existing != null) {
            // The router notification is synchronous and bounded: the
            // engine's lower swapchain detaches (or abandons within its UI
            // bound) before removeView tears the Surface down underneath it.
            SecondaryGameplaySurfaceRouter.surfaceDestroyed(gameplayGeneration);
            root.removeView(existing);
            gameplaySurface = null;
            gameplayClockwiseQuarterTurn = false;
            heldGameplaySurface = true;
        }
        // Only an instance that actually held either gameplay surface clears
        // the flag. The primary-display reject path also reaches onDestroy,
        // and clearing it from there would tell the browser that a live
        // dual-screen session had ended.
        if (heldGameplaySurface) gameplaySurfaceActive = false;
        gameplayGeneration = 0L;
        if (restorePreviewViews) {
            artwork.setVisibility(View.VISIBLE);
            eyebrow.setVisibility(View.VISIBLE);
            titleView.setVisibility(View.VISIBLE);
            scoreView.setVisibility(View.VISIBLE);
        }
    }

    private static String safe(String value) {
        return value == null ? "" : value;
    }

    private static String localPath(String source) {
        if (source == null || source.isEmpty()) return "";
        if (source.startsWith("file:")) return Uri.parse(source).getPath();
        return source;
    }

    private void hideSystemUi() {
        getWindow().setDecorFitsSystemWindows(false);
        WindowInsetsController controller = getWindow().getInsetsController();
        if (controller != null) {
            controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
            controller.setSystemBarsBehavior(
                    WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
        }
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_FULLSCREEN |
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY |
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN |
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION |
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    @Override
    protected void onStart() {
        super.onStart();
        if (ownsVisibilityFlags) windowState.started(this);
    }

    @Override
    protected void onStop() {
        if (ownsVisibilityFlags) windowState.stopped(this);
        super.onStop();
    }

    @Override
    protected void onResume() {
        super.onResume();
        resumed = true;
        hideSystemUi();
        if (!ownsVisibilityFlags) return;
        // Only a resumed instance is worth handing a lower-display window to
        // in-process; anything else has to go through a real Activity start.
        SecondaryGameplaySurfaceRouter.attachHost(this);
        SecondaryCheatPanelRouter.attachPanel(this);
        yieldTopFocusToPrimaryDisplay();
    }

    @Override
    protected void onPause() {
        resumed = false;
        SecondaryGameplaySurfaceRouter.detachHost(this);
        // Keep router handoff limited to resumed instances. Pause alone does
        // not mean this window disappeared: yielding focus to display 0 also
        // pauses it on the Thor. Only onStop retires preview window presence.
        SecondaryCheatPanelRouter.detach(this);
        super.onPause();
    }

    /**
     * Gives the top-focused display back to the frontend.
     *
     * <p>Reaching onResume/onNewIntent means Android has already finished
     * putting this display on top of the display order — the move happens
     * inside the Activity start, before the resume is scheduled — so this is
     * correctly ordered after it rather than racing it. The delayed second
     * attempt covers a launch that is still settling (a cold start bringing up
     * both displays at once), and re-checks {@code resumed} first so it cannot
     * pull focus away from the in-app browser, which legitimately takes the
     * lower display and pauses this Activity while it is open.
     */
    private void yieldTopFocusToPrimaryDisplay() {
        PrimaryDisplayFocusGuard.restorePrimaryTopFocus(this);
        if (root == null) return;
        root.removeCallbacks(deferredFocusYield);
        root.postDelayed(deferredFocusYield, 400L);
    }

    private final Runnable deferredFocusYield = new Runnable() {
        @Override
        public void run() {
            if (!resumed || isFinishing()) return;
            PrimaryDisplayFocusGuard.restorePrimaryTopFocus(PreviewActivity.this);
        }
    };

    /**
     * Takes a dual-screen game's lower surface without an Activity start.
     *
     * <p>Called from the engine's lifecycle thread, so the view work is posted.
     */
    @Override public void showSecondaryGameplaySurface(long generation) {
        runOnUiThread(() -> {
            // A queued handoff can outlive its game. Resume of an existing
            // host must also leave its current holder/producer intact; Android
            // recreates that holder itself after ordinary surface loss.
            if (!SecondaryGameplaySurfaceRouter.isCurrent(generation)) return;
            if (gameplaySurface != null && gameplayGeneration == generation) return;
            showGameplaySurface(generation);
        });
    }

    @Override
    protected void onDestroy() {
        // A rejected primary-display instance never claimed the static flags;
        // clearing them here would blind the watchdog to the real secondary
        // instance and make it relaunch playback it never lost.
        if (ownsVisibilityFlags) {
            windowState.destroyed(this);
            if (visibleInstance == this) {
                running = false;
                resumed = false;
                gameplaySurfaceActive = false;
                visibleInstance = null;
            }
        }
        // The routers keep static references to this instance; a destroyed
        // Activity left registered would swallow the next panel's frames, or
        // be handed a gameplay surface it can no longer draw.
        SecondaryCheatPanelRouter.detach(this);
        SecondaryGameplaySurfaceRouter.detachHost(this);
        AppVolumeController.unregisterListener(appVolumeListener);
        if (root != null) root.removeCallbacks(deferredFocusYield);
        try {
            if (receiverRegistered) unregisterReceiver(receiver);
        } finally {
            // Media teardown must run even if unregistering throws; leaked
            // MediaPlayers keep decoder hardware allocated across restarts.
            leaveGameplaySurface(false);
            stopPlayers();
        }
        super.onDestroy();
    }

    private final class PlayerSlot implements TextureView.SurfaceTextureListener {
        final TextureView view = new TextureView(PreviewActivity.this);
        MediaPlayer player;
        String source = "";
        String pendingSource;
        Runnable ready;
        boolean prepared;
        boolean firstFrameRendered;
        boolean looping = true;

        PlayerSlot() {
            view.setSurfaceTextureListener(this);
            view.setAlpha(0f);
            // Keep the TextureView attached and laid out even while transparent.
            // An INVISIBLE TextureView never acquires a SurfaceTexture on this
            // device, so MediaPlayer preparation could never begin.
            view.setVisibility(View.VISIBLE);
        }

        void prepare(String source) {
            source = safe(source);
            if (!source.isEmpty() && source.equals(this.source)) return;
            release();
            this.source = source;
            pendingSource = source;
            view.setVisibility(View.VISIBLE);
            if (view.isAvailable()) open();
        }

        void activate(Runnable onReady) {
            ready = onReady;
            if (firstFrameRendered && ready != null) {
                Runnable callback = ready;
                ready = null;
                callback.run();
            }
        }

        void setLooping(boolean looping) {
            this.looping = looping;
            if (player == null) return;
            try {
                player.setLooping(looping);
            } catch (RuntimeException ignored) {
            }
        }

        /** Suspends decoding without releasing the decoder, so the rendered
         * frame stays on the lower display for the whole break. */
        void pause() {
            if (player == null || !prepared) return;
            try {
                player.pause();
            } catch (RuntimeException ignored) {
            }
        }

        void resume() {
            if (player == null || !prepared) return;
            try {
                player.start();
            } catch (RuntimeException ignored) {
            }
        }

        private void open() {
            if (pendingSource == null || pendingSource.isEmpty() || !view.isAvailable()) return;
            try {
                final String source = pendingSource;
                final String path = localPath(source);
                File file = new File(path);
                Log.i("ThorPreview", "Preparing video path=" + path
                        + " exists=" + file.isFile() + " bytes=" + file.length());
                player = new MediaPlayer();
                // State the stream instead of inheriting it. USAGE_MEDIA maps
                // to STREAM_MUSIC, which is what the engines' AudioTracks and
                // EmuFusion's menu sounds use, so one hardware volume control
                // governs every sound the app makes.
                player.setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MOVIE)
                        .build());
                player.setSurface(new Surface(view.getSurfaceTexture()));
                player.setLooping(looping);
                // Warm neighbors begin silently. Only the slot that has
                // rendered and been promoted by showSelection becomes audible.
                player.setVolume(0f, 0f);
                // MediaPlayer keeps ownership of a path data source for its whole
                // lifetime. This avoids device-specific failures caused by an FD
                // being closed before the asynchronous prepare has consumed it.
                player.setDataSource(path);
                player.setOnPreparedListener(mediaPlayer -> {
                    Log.i("ThorPreview", "Prepared video path=" + path
                            + " size=" + mediaPlayer.getVideoWidth() + "x"
                            + mediaPlayer.getVideoHeight()
                            + " durationMs=" + mediaPlayer.getDuration());
                    applyCrop(mediaPlayer.getVideoWidth(), mediaPlayer.getVideoHeight());
                    prepared = true;
                    // A decoder that finishes preparing mid-break must not
                    // undo the break; resumePlayers() starts it afterwards.
                    if (!playersPaused) mediaPlayer.start();
                });
                // Game selections hard-loop here even on vendor players that
                // emit completion despite looping. System-level previews report
                // the boundary to Pegasus so it can select a different game.
                player.setOnCompletionListener(mediaPlayer -> {
                    if (activeSlot >= 0 && slots[activeSlot] == PlayerSlot.this &&
                            advanceOnCompletion && currentSequence > 0L) {
                        startService(new Intent(PreviewActivity.this, PreviewService.class)
                                .setAction(PreviewService.ACTION_COMPLETED)
                                .putExtra(PreviewService.EXTRA_SEQUENCE, currentSequence));
                        return;
                    }
                    try {
                        mediaPlayer.seekTo(0);
                        mediaPlayer.start();
                    } catch (Exception error) {
                        Log.w("ThorPreview", "Unable to restart looping preview " + path, error);
                    }
                });
                player.setOnInfoListener((mediaPlayer, what, extra) -> {
                    if (what == MediaPlayer.MEDIA_INFO_VIDEO_RENDERING_START) {
                        firstFrameRendered = true;
                        if (ready != null) {
                            Runnable firstFrame = ready;
                            ready = null;
                            firstFrame.run();
                        }
                    }
                    return false;
                });
                player.setOnErrorListener((mediaPlayer, what, extra) -> {
                    Log.e("ThorPreview", "MediaPlayer error path=" + path
                            + " what=" + what + " extra=" + extra);
                    release();
                    if (activeSlot >= 0 && slots[activeSlot] == this) {
                        artwork.animate().alpha(1f).setDuration(120).start();
                        blackout.setVisibility(View.GONE);
                    }
                    return true;
                });
                player.prepareAsync();
            } catch (Exception error) {
                Log.e("ThorPreview", "Unable to prepare " + pendingSource, error);
                release();
                if (activeSlot >= 0 && slots[activeSlot] == this) {
                    artwork.setAlpha(1f);
                    blackout.setVisibility(View.GONE);
                }
            }
        }

        private void applyCrop(int videoWidth, int videoHeight) {
            int width = view.getWidth();
            int height = view.getHeight();
            if (width <= 0 || height <= 0 || videoWidth <= 0 || videoHeight <= 0) return;
            float viewAspect = width / (float) height;
            float videoAspect = videoWidth / (float) videoHeight;
            float scaleX = 1f;
            float scaleY = 1f;
            if (videoAspect > viewAspect) scaleX = videoAspect / viewAspect;
            else scaleY = viewAspect / videoAspect;
            Matrix matrix = new Matrix();
            matrix.setScale(scaleX, scaleY, width / 2f, height / 2f);
            view.setTransform(matrix);
        }

        void release() {
            source = "";
            pendingSource = null;
            ready = null;
            prepared = false;
            firstFrameRendered = false;
            looping = true;
            if (player != null) {
                try {
                    player.stop();
                } catch (RuntimeException ignored) {
                }
                player.release();
                player = null;
            }
            view.animate().cancel();
            view.setAlpha(0f);
            view.setVisibility(View.VISIBLE);
        }

        @Override
        public void onSurfaceTextureAvailable(SurfaceTexture surface, int width, int height) {
            open();
        }

        @Override
        public void onSurfaceTextureSizeChanged(SurfaceTexture surface, int width, int height) {
            if (player != null) applyCrop(player.getVideoWidth(), player.getVideoHeight());
        }

        @Override
        public boolean onSurfaceTextureDestroyed(SurfaceTexture surface) {
            release();
            return true;
        }

        @Override
        public void onSurfaceTextureUpdated(SurfaceTexture surface) {
            if (activeSlot < 0 || activeSlot >= slots.length || slots[activeSlot] != this ||
                    player == null || !prepared || playersPaused) return;
            lastLowerVisualChangeMs = SystemClock.elapsedRealtime();
            renderedVideoSource = source;
            renderedVideoAdvancing = true;
            try {
                renderedVideoPositionMs = player.getCurrentPosition();
            } catch (RuntimeException ignored) {
            }
        }
    }

    /** Read-only lower-display evidence used by the QML screensaver timer. */
    static JSONObject screensaverStatus() {
        JSONObject result = new JSONObject();
        long now = SystemClock.elapsedRealtime();
        PreviewActivity activity = visibleInstance;
        try {
            result.put("available", activity != null && running && resumed);
            result.put("capturedAtEpochMs", System.currentTimeMillis());
            if (activity == null) {
                result.put("video", "");
                result.put("positionMs", 0);
                result.put("videoAdvancing", false);
                result.put("visualIdleMs", 0);
                return result;
            }
            long idle = Math.max(0L, now - activity.lastLowerVisualChangeMs);
            boolean advancing = activity.renderedVideoAdvancing && idle < 1500L;
            result.put("video", activity.renderedVideoSource);
            result.put("positionMs", Math.max(0, activity.renderedVideoPositionMs));
            result.put("videoAdvancing", advancing);
            result.put("visualIdleMs", idle);
        } catch (Exception ignored) {
        }
        return result;
    }

    static boolean isRunning() {
        return running;
    }

    static boolean isVisible() {
        return windowState.isVisible();
    }

    /** True while a dual-screen game owns this Activity's lower-display
     * Surface. The in-app browser reads it to stay off that display. */
    static boolean isGameplaySurfaceActive() {
        return running && gameplaySurfaceActive;
    }
}
