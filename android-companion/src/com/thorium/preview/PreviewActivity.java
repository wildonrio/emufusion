package com.thorium.preview;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.SurfaceTexture;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Bundle;
import android.view.GestureDetector;
import android.view.Display;
import android.view.MotionEvent;
import android.view.Surface;
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

import java.io.File;
import android.util.Log;

public final class PreviewActivity extends Activity {
    private static volatile boolean running;
    private static volatile boolean resumed;
    // True only while a dual-screen (DS/3DS/Wii U) session is rendering into
    // this Activity's SurfaceView. Anything that would take the lower display
    // — the in-app browser above all — has to yield while this is set.
    private static volatile boolean gameplaySurfaceActive;
    private FrameLayout root;
    private ImageView artwork;
    private TextView titleView;
    private TextView scoreView;
    private TextView eyebrow;
    private TextView launchButton;
    private View blackout;
    private SurfaceView gameplaySurface;
    private long gameplayGeneration;
    private PlayerSlot[] slots;
    // The primary-display reject path finishes before any of the setup below
    // runs, so onDestroy must know whether this instance ever registered its
    // receiver or claimed the static visibility flags.
    private boolean receiverRegistered;
    private boolean ownsVisibilityFlags;
    private int activeSlot = -1;
    private boolean soundEnabled;
    // A "browser break": every decoder is held paused and silent while
    // Lucent's browser is open, then started again where it stopped.
    private boolean playersPaused;
    private long selectionGeneration;
    private long currentSequence;
    private boolean advanceOnCompletion;
    private GestureDetector gestures;
    private static final long CROSSFADE_MS = 85L;

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
        // This Activity is only Lucent's private Thor lower-display surface.
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
        ownsVisibilityFlags = true;
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
        // Pegasus on the upper display.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE);
        buildUi();
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
        if (SecondaryGameplaySurfaceRouter.ACTION_SECONDARY_GAMEPLAY.equals(
                intent.getAction())) {
            showGameplaySurface(intent.getLongExtra(
                    SecondaryGameplaySurfaceRouter.EXTRA_GENERATION, 0L));
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
            float volume = soundEnabled && !playersPaused && index == activeSlot ? 1f : 0f;
            try {
                player.setVolume(volume, volume);
            } catch (RuntimeException ignored) {
            }
        }
    }

    private void blankScreen() {
        leaveGameplaySurface(false);
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
        gameplaySurfaceActive = true;
        Log.i("LucentPreview", "showGameplaySurface generation=" + generation +
                " displayId=" + (getDisplay() == null ? -1 : getDisplay().getDisplayId()));
        gameplaySurface = new SurfaceView(this);
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
                Log.i("LucentPreview", "gameplay surfaceCreated generation=" + gameplayGeneration +
                        " size=" + gameplaySurface.getWidth() + "x" + gameplaySurface.getHeight() +
                        " valid=" + holder.getSurface().isValid() + " -> surfaceAvailable");
                SecondaryGameplaySurfaceRouter.surfaceAvailable(gameplayGeneration,
                        holder.getSurface(), gameplaySurface.getWidth(),
                        gameplaySurface.getHeight());
            }

            @Override public void surfaceChanged(
                    SurfaceHolder holder, int format, int width, int height) {
                Log.i("LucentPreview", "gameplay surfaceChanged generation=" + gameplayGeneration +
                        " size=" + width + "x" + height +
                        " valid=" + holder.getSurface().isValid() + " -> surfaceAvailable");
                SecondaryGameplaySurfaceRouter.surfaceAvailable(gameplayGeneration,
                        holder.getSurface(), width, height);
            }

            @Override public void surfaceDestroyed(SurfaceHolder holder) {
                // Synchronous and bounded: the Surface dies when this
                // callback returns, so the engine must detach first.
                Log.i("LucentPreview", "gameplay surfaceDestroyed generation=" + gameplayGeneration);
                SecondaryGameplaySurfaceRouter.surfaceDestroyed(gameplayGeneration);
            }
        });
        gameplaySurface.setOnTouchListener((view, event) -> {
            int width = Math.max(1, view.getWidth());
            int height = Math.max(1, view.getHeight());
            int action = event.getActionMasked();
            boolean pressed = action != MotionEvent.ACTION_UP &&
                    action != MotionEvent.ACTION_CANCEL;
            SecondaryGameplaySurfaceRouter.touch(gameplayGeneration,
                    event.getX() / width, event.getY() / height, pressed);
            return true;
        });
        root.addView(gameplaySurface, fill());
        gameplaySurface.bringToFront();
    }

    private void leaveGameplaySurface(boolean restorePreviewViews) {
        SurfaceView existing = gameplaySurface;
        if (existing != null) {
            // The router notification is synchronous and bounded: the
            // engine's lower swapchain detaches (or abandons within its UI
            // bound) before removeView tears the Surface down underneath it.
            SecondaryGameplaySurfaceRouter.surfaceDestroyed(gameplayGeneration);
            root.removeView(existing);
            gameplaySurface = null;
            // Only an instance that actually held the Surface clears the flag.
            // The primary-display reject path also reaches onDestroy, and
            // clearing it from there would tell the browser that a live
            // dual-screen session had ended.
            gameplaySurfaceActive = false;
        }
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
    protected void onResume() {
        super.onResume();
        resumed = true;
        hideSystemUi();
    }

    @Override
    protected void onPause() {
        resumed = false;
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        // A rejected primary-display instance never claimed the static flags;
        // clearing them here would blind the watchdog to the real secondary
        // instance and make it relaunch playback it never lost.
        if (ownsVisibilityFlags) {
            running = false;
            resumed = false;
            gameplaySurfaceActive = false;
        }
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
                // Lucent's menu sounds use, so one hardware volume control
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
        }
    }

    static boolean isRunning() {
        return running;
    }

    static boolean isVisible() {
        return running && resumed;
    }

    /** True while a dual-screen game owns this Activity's lower-display
     * Surface. The in-app browser reads it to stay off that display. */
    static boolean isGameplaySurfaceActive() {
        return running && gameplaySurfaceActive;
    }
}
