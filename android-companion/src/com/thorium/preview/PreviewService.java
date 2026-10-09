package com.thorium.preview;

import android.app.Activity;
import android.app.ActivityOptions;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.util.Log;

import com.thorium.preview.game.FrameGenerationSettings;
import com.thorium.preview.game.InWindowGameHost;
import com.thorium.preview.game.WidescreenSettings;
import com.thorium.preview.cheats.CheatControl;
import com.thorium.preview.multiplayer.MultiplayerIdentityEndpoint;
import com.thorium.preview.multiplayer.MultiplayerInviteEndpoint;
import com.thorium.preview.multiplayer.MultiplayerRosterEndpoint;
import com.thorium.preview.multiplayer.MultiplayerScheduleEndpoint;
import com.thorium.preview.multiplayer.MultiplayerStatusEndpoint;
import com.thorium.preview.multiplayer.MultiplayerWantEndpoint;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

public final class PreviewService extends Service {
    public static final String ACTION_UPDATE = "com.thorium.preview.UPDATE";
    public static final String ACTION_HIDE = "com.thorium.preview.HIDE";
    public static final String ACTION_BLANK = "com.thorium.preview.BLANK";
    public static final String ACTION_AUDIO = "com.thorium.preview.AUDIO";
    public static final String ACTION_SUSPEND = "com.thorium.preview.SUSPEND";
    public static final String ACTION_GAMEPLAY = "com.thorium.preview.GAMEPLAY";
    public static final String ACTION_LIBRARY = "com.thorium.preview.LIBRARY";
    public static final String ACTION_CLOSE = "com.thorium.preview.CLOSE";
    public static final String ACTION_LAUNCH = "com.thorium.preview.LAUNCH";
    public static final String ACTION_COMPLETED = "com.thorium.preview.COMPLETED";
    /** Broadcast to PreviewActivity: hold every decoder paused and silent. */
    public static final String ACTION_PAUSE = "com.thorium.preview.PAUSE";
    /** Broadcast to PreviewActivity: start the paused decoders again. */
    public static final String ACTION_RESUME = "com.thorium.preview.RESUME";
    /** Broadcast from BrowserActivity when its window appears/disappears. */
    public static final String ACTION_BROWSER_OPENED = "com.thorium.preview.BROWSER_OPENED";
    public static final String ACTION_BROWSER_CLOSED = "com.thorium.preview.BROWSER_CLOSED";
    public static final String EXTRA_VIDEO = "video";
    public static final String EXTRA_ART = "art";
    public static final String EXTRA_TITLE = "title";
    public static final String EXTRA_SYSTEM = "system";
    public static final String EXTRA_SCORE = "score";
    public static final String EXTRA_PRELOAD_PREV = "preload_prev";
    public static final String EXTRA_PRELOAD_NEXT = "preload_next";
    public static final String EXTRA_PRELOAD_AUX = "preload_aux";
    public static final String EXTRA_SOUND_ENABLED = "sound_enabled";
    public static final String EXTRA_SEQUENCE = "sequence";
    public static final String EXTRA_ADVANCE = "advance";
    /** Persisted so a PreviewActivity rebuilt during a browser break knows it
     * must come back paused rather than playing under the browser. */
    public static final String EXTRA_BROWSER_ACTIVE = "browser_active";
    public static final int PORT = 43821;
    private static final String BROWSER_TAG = "LucentBrowser";

    private volatile boolean running;
    private volatile long suppressPlayUntil;
    private volatile boolean previewActive;
    private volatile boolean gameplayActive;
    // Unlike a launch-time hide, TOP preview placement is persistent.  Do not
    // let the normal Pegasus heartbeat resurrect lower-display playback until
    // a subsequent /play request explicitly returns placement to the Thor.
    private volatile boolean placementBlank;
    // A browser break. While EmuFusion's browser window exists, preview playback
    // is suspended: previewActive is false so the watchdog cannot fire,
    // /heartbeat cannot resurrect it, and /play and /transition record the
    // user's newest selection without starting a decoder under the browser.
    private volatile boolean browserActive;
    private volatile boolean resumePreviewAfterBrowser;
    private volatile boolean screensaverActive;
    private volatile long lastPegasusHeartbeat;
    private volatile long lastPreviewSequence;
    private volatile long requestedLaunchSequence;
    private volatile long completedPreviewSequence;
    /** A legacy launch route or bundled theme changed on disk before Pegasus
     * was ready to reload it. The first safe library heartbeat consumes this
     * request, combining simultaneous changes into one clean Qt restart. */
    private final AtomicBoolean launchRouteReloadPending = new AtomicBoolean();
    private boolean importReloadWaitLogged;
    private ImportManager importManager;
    static final String ACTION_INITIAL_LIBRARY_SCAN = "com.thorium.preview.INITIAL_LIBRARY_SCAN";
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final Runnable pegasusWatchdog = new Runnable() {
        @Override
        public void run() {
            if (!previewActive) return;
            // On the Thor, touching a lower-screen launcher can move global
            // application focus away from Pegasus, which pauses Pegasus' QML
            // heartbeat before it has a chance to restore the preview. The
            // service already knows whether playback is logically active, so
            // reclaim a covered display directly. Launch-time blank/hide and
            // top-PIP placement all set previewActive false first.
            if (PrimaryDisplayFocusGuard.isInteractive(PreviewService.this)
                    && !PreviewActivity.isVisible()) {
                if (screensaverActive)
                    showScreensaverBlackout();
                else
                    showLastPlayer();
            }
            // Do not expire solely because global focus moved to display 4;
            // that is the exact failure we are recovering from, and it pauses
            // Qt's heartbeat. Game launch, top-PIP placement, and the user's
            // double-tap dismissal all explicitly clear previewActive.
            mainHandler.postDelayed(this, 750L);
        }
    };
    // BrowserActivity reports its own lifecycle instead of the service merely
    // assuming it: a package-scoped broadcast to this already-running service
    // is delivered even when the browser is torn down after the process has
    // left the foreground, where a background startService would be refused.
    private final android.content.BroadcastReceiver browserReceiver =
            new android.content.BroadcastReceiver() {
        @Override
        public void onReceive(android.content.Context context, Intent intent) {
            if (ACTION_BROWSER_OPENED.equals(intent.getAction())) beginBrowserBreak();
            else if (ACTION_BROWSER_CLOSED.equals(intent.getAction())) endBrowserBreak();
        }
    };
    private boolean browserReceiverRegistered;
    private ServerSocket server;
    // Requests are handled off the accept loop on a small bounded pool so a
    // single stalled client can never wedge the whole localhost control plane.
    // The queue is bounded too: overflow requests are refused at accept time
    // instead of piling up behind a slow endpoint.
    private final ExecutorService httpWorkers = new ThreadPoolExecutor(
            2, 2, 0L, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(16),
            new java.util.concurrent.ThreadFactory() {
                private final AtomicInteger index = new AtomicInteger();
                @Override public Thread newThread(Runnable task) {
                    Thread thread = new Thread(task,
                            "thor-preview-http-" + index.incrementAndGet());
                    thread.setDaemon(true);
                    return thread;
                }
            });

    // Every endpoint that changes state (including /launch/status and
    // /heartbeat, which consume or resurrect preview state when read).
    // Read-only endpoints — /capabilities, /library/index, /import/status,
    // /update/status, /archive/list, /audit/artwork, and the root probe —
    // stay callable without a token.
    private static final Set<String> MUTATING_ENDPOINTS = new HashSet<>(Arrays.asList(
            "/play", "/heartbeat", "/hide", "/transition", "/blank", "/led",
            "/screensaver/play",
            "/settings/sound", "/settings/sfx", "/settings/frame-generation",
            "/settings/widescreen", "/settings/widescreen-hack",
            "/settings/private-diagnostics",
            "/sfx", "/game/rename",
            "/game/delete", "/cheats/set", "/import/scan",
            "/import/initial", "/import/reload", "/maintenance/rescan",
            "/browser/open", "/update/check", "/update/install",
            "/feedback/record", "/feedback/cancel", "/feedback/send",
            "/archive/include", "/launch/status", "/artwork/decide",
            "/route/set", "/route/clear", "/route/link", "/route/custom",
            "/multiplayer/identity", "/multiplayer/roster", "/multiplayer/want",
            "/multiplayer/schedule/submit", "/multiplayer/schedule/cancel",
            "/multiplayer/invite/respond", "/multiplayer/status"));
    // The port is reachable by every application on the device, so mutating
    // endpoints require a per-boot bearer token — except the ones below,
    // which the FROZEN theme/theme.qml calls without one and which therefore
    // stay open to local processes (residual risk accepted; browser CSRF is
    // still blocked by the Origin/Referer rejection on every mutating path).
    private static final Set<String> THEME_CALLED_ENDPOINTS = new HashSet<>(Arrays.asList(
            "/play", "/heartbeat", "/hide", "/transition", "/blank", "/led",
            "/screensaver/play",
            "/settings/sound", "/settings/sfx", "/settings/frame-generation",
            "/settings/widescreen", "/settings/widescreen-hack",
            "/settings/private-diagnostics",
            "/sfx", "/game/rename",
            "/game/delete", "/cheats/set", "/import/scan",
            "/import/reload", "/maintenance/rescan", "/browser/open",
            "/feedback/record", "/feedback/cancel", "/feedback/send",
            "/update/check", "/update/install", "/launch/status",
            // The Settings emulator picker. Token-free for the same reason as
            // every row above it: the theme has no way to read the per-boot
            // token, and these endpoints share the Origin/Referer rejection
            // that blocks page-initiated calls. The residual risk is narrower
            // than it looks — a route may only be pointed at a catalog entry,
            // and /route/custom refuses anything that is not an already
            // installed package with a real exported activity, so a local
            // caller cannot invent a target that does not already exist on the
            // device. See docs/external-emulator-routing.md.
            "/route/set", "/route/clear", "/route/link", "/route/custom",
            // The missing-box-art review. It can delete a ROM, so it is as
            // sensitive as /game/delete above and is open for the same
            // reason: the theme cannot read the per-boot token. It only ever
            // acts on a key the companion itself put in the review queue, so
            // a caller cannot name an arbitrary file.
            "/artwork/decide",
            // The multiplayer panel (QML) and in-game overlay both call these
            // directly, same constraint as every row above: neither can read
            // the per-boot token. All seven are self-contained requests keyed
            // by data the caller already supplies (gameKey/matchId/scheduleId)
            // or, for /multiplayer/status and /multiplayer/roster, read-only.
            "/multiplayer/identity", "/multiplayer/roster", "/multiplayer/want",
            "/multiplayer/schedule/submit", "/multiplayer/schedule/cancel",
            "/multiplayer/invite/respond", "/multiplayer/status"));
    private volatile String controlToken = "";
    private UpdateManager updateManager;
    private LibraryIndexManager libraryIndexManager;
    private ThorLedManager thorLedManager;
    // Static, not instance-scoped: mirrors PreviewActivity's running/resumed
    // fields (see its isVisible()) -- one process, one service instance, and
    // this is how a live-gameplay overlay (InWindowGameHost, a different
    // source tree entirely) reaches it without a bind/IPC round trip, the
    // same way InWindowGameHost already calls startService(...) directly.
    private static volatile com.thorium.preview.multiplayer.MultiplayerManager multiplayerManager;

    public static com.thorium.preview.multiplayer.MultiplayerManager getMultiplayerManager() {
        return multiplayerManager;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        // Android starts a fresh service process during process-death Quick
        // Resume. Enter foreground state before any library migration, theme
        // installation, importer construction, or updater work can consume
        // the platform's five-second deadline.
        ensureForeground();
        ensureControlToken();
        android.content.IntentFilter browserFilter =
                new android.content.IntentFilter(ACTION_BROWSER_OPENED);
        browserFilter.addAction(ACTION_BROWSER_CLOSED);
        registerReceiver(browserReceiver, browserFilter);
        browserReceiverRegistered = true;
        // A break can only be stale here: this is a fresh service instance, so
        // no browser window of ours is open yet.
        getSharedPreferences("preview", MODE_PRIVATE).edit()
                .putBoolean(EXTRA_BROWSER_ACTIVE, false).apply();
        importManager = new ImportManager(this);
        updateManager = new UpdateManager(this);
        updateManager.setGameplayGate(() -> gameplayActive);
        libraryIndexManager = new LibraryIndexManager();
        thorLedManager = new ThorLedManager(this);
        // Alpha multiplayer: a no-op end to end unless the owner has
        // configured a self-hosted backend (MultiplayerConfig.isConfigured),
        // since this backend is self-hosted per deployment, not a
        // Lucent-operated service -- see MultiplayerManager's own doc
        // comment. globalInit() must run before any NetplaySession is ever
        // constructed; doing it here, once, at the same place every other
        // process-wide manager starts, is the simplest way to guarantee that.
        com.thorium.lucent.netplay.NetplaySession.globalInit(this);
        multiplayerManager = new com.thorium.preview.multiplayer.MultiplayerManager(this);
        multiplayerManager.start();
        // Decode the four menu blips now. SoundPool loads asynchronously, and
        // doing it at process start means the user's very first D-pad press in
        // the library is already audible.
        MenuSoundPlayer.warmUp(this);
        Thread launchMigration = new Thread(() -> {
            int changed = LaunchMetadataRouter.normalize(this);
            if (changed > 0) {
                Log.i("LucentLaunchMetadata",
                        "Migrated " + changed + " collection launch routes");
                // The migration runs before Pegasus can safely be restarted.
                // Defer exactly one reload until a heartbeat proves the Qt
                // frontend is alive and the service is not in gameplay,
                // screensaver, or browser-break state.
                launchRouteReloadPending.set(true);
            }
        }, "lucent-launch-metadata");
        launchMigration.setDaemon(true);
        launchMigration.start();
        if (ThemeInstaller.hasStorageAccess(this)) {
            ThemeInstaller.installBundledIfNeeded(
                    this,
                    () -> updateManager.checkAsync(false),
                    () -> launchRouteReloadPending.set(true));
        } else {
            // App updates are independent of ROM/library permission. A first
            // launch must still discover and download a newer GitHub release
            // before the owner has granted broad storage access.
            updateManager.checkAsync(false);
        }
        startServer();
        // Both checks are independent and non-blocking. The importer is
        // fingerprint-throttled, while the updater performs lightweight
        // version checks and only downloads changed artifacts.
        importManager.startInitialScan();
    }

    private void ensureForeground() {
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        NotificationChannel channel = new NotificationChannel(
                "preview", "EmuFusion", NotificationManager.IMPORTANCE_MIN);
        channel.setDescription("Synchronizes previews, imports games, and checks for updates");
        manager.createNotificationChannel(channel);
        Notification notification = new Notification.Builder(this, "preview")
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentTitle("EmuFusion")
                .setContentText("Preview, library import, and updates are active")
                .setOngoing(true)
                .build();
        startForeground(43821, notification);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Every startForegroundService request owns a platform deadline, even
        // when this sticky service already exists. Reassert foreground state
        // before action dispatch so duplicate process-restoration starts can
        // never leave an outstanding deadline behind.
        ensureForeground();
        if (intent != null && ACTION_INITIAL_LIBRARY_SCAN.equals(intent.getAction()))
            importManager.startInitialScan();
        if (intent != null && ACTION_GAMEPLAY.equals(intent.getAction())) {
            PrivateDiagnostics.gameplay(this, true);
            boolean alreadyActive = gameplayActive;
            gameplayActive = true;
            screensaverActive = false;
            placementBlank = false;
            previewActive = false;
            // A game started; closing the browser later must not put a movie
            // back on the lower display underneath it.
            resumePreviewAfterBrowser = false;
            suppressPlayUntil = SystemClock.elapsedRealtime() + 5000L;
            mainHandler.removeCallbacks(pegasusWatchdog);
            // Keep the secondary display owned by EmuFusion but render it fully
            // black for every single-screen game. Closing this resident lower
            // display surface exposes Android's launcher, which is both a
            // burn-in risk and visually misleading. Emulation itself remains
            // exclusively inside EmuFusion's MainActivity on display 0.
            //
            // ONLY on the transition into gameplay: the in-window host also
            // re-asserts ACTION_GAMEPLAY once a minute to heal a restarted
            // companion, and blanking on every re-assert covered the LIVE
            // GamePad view of a dual-screen session a minute into gameplay
            // (run 2026-08-17-wiiu5: "did not render on the Thor lower
            // display"). When gameplay was already active the flags above
            // are refreshed and nothing visual changes.
            if (!alreadyActive) {
                if (PreviewActivity.isVisible()) {
                    sendBroadcast(new Intent(ACTION_BLANK).setPackage(getPackageName()));
                } else {
                    launchPlayerOnSecondary(new Intent(this, PreviewActivity.class)
                            .setAction(ACTION_BLANK)
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                                    Intent.FLAG_ACTIVITY_REORDER_TO_FRONT));
                }
            }
        } else if (intent != null && ACTION_LIBRARY.equals(intent.getAction())) {
            PrivateDiagnostics.gameplay(this, false);
            gameplayActive = false;
            suppressPlayUntil = 0L;
            updateManager.onLibraryVisible();
        } else if (intent != null && ACTION_SUSPEND.equals(intent.getAction())) {
            screensaverActive = false;
            placementBlank = true;
            previewActive = false;
            resumePreviewAfterBrowser = false;
            sendBroadcast(new Intent(ACTION_BLANK).setPackage(getPackageName()));
        } else if (intent != null && ACTION_LAUNCH.equals(intent.getAction())) {
            long sequence = intent.getLongExtra(EXTRA_SEQUENCE, 0L);
            // Accept only the preview that is still visible. A delayed tap can
            // never launch a game the user has already navigated away from.
            if (previewActive && sequence > 0L && sequence == lastPreviewSequence)
                requestedLaunchSequence = sequence;
        } else if (intent != null && ACTION_COMPLETED.equals(intent.getAction())) {
            long sequence = intent.getLongExtra(EXTRA_SEQUENCE, 0L);
            if (previewActive && sequence > 0L && sequence == lastPreviewSequence)
                completedPreviewSequence = sequence;
        }
        startServer();
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private synchronized void startServer() {
        if (running) return;
        running = true;
        Thread thread = new Thread(this::serve, "thor-preview-http");
        thread.setDaemon(true);
        thread.start();
    }

    /** Regenerates the per-boot control-plane token and publishes it to the
     * app-private files directory for in-process callers. */
    private void ensureControlToken() {
        byte[] raw = new byte[32];
        new SecureRandom().nextBytes(raw);
        StringBuilder hex = new StringBuilder(raw.length * 2);
        for (byte value : raw)
            hex.append(String.format(Locale.US, "%02x", value & 0xff));
        controlToken = hex.toString();
        try (java.io.FileOutputStream out = new java.io.FileOutputStream(
                new java.io.File(getFilesDir(), "control-plane-token"))) {
            out.write(controlToken.getBytes(StandardCharsets.UTF_8));
        } catch (Exception error) {
            Log.e("ThorPreview", "Unable to publish control-plane token", error);
        }
    }

    private boolean tokenAuthorized(String headerToken, String queryToken) {
        String expected = controlToken;
        if (expected.isEmpty()) return false;
        for (String provided : new String[] {headerToken, queryToken}) {
            if (provided != null && MessageDigest.isEqual(
                    expected.getBytes(StandardCharsets.UTF_8),
                    provided.getBytes(StandardCharsets.UTF_8)))
                return true;
        }
        return false;
    }

    private void serve() {
        try {
            // SO_REUSEADDR lets a restarted service rebind immediately instead
            // of losing the control port to a lingering TIME_WAIT socket. A
            // few backoff retries cover the race where the previous service
            // instance has not yet closed its listener.
            ServerSocket listener = null;
            for (int attempt = 0; listener == null; attempt++) {
                ServerSocket binding = new ServerSocket();
                try {
                    binding.setReuseAddress(true);
                    binding.bind(new InetSocketAddress(
                            InetAddress.getByName("127.0.0.1"), PORT), 8);
                    listener = binding;
                } catch (java.io.IOException error) {
                    binding.close();
                    if (attempt >= 4 || !running) throw error;
                    Thread.sleep(250L << attempt);
                }
            }
            server = listener;
            while (running) {
                Socket socket = server.accept();
                // A client that connects and then never writes must time out
                // rather than hold a worker forever.
                socket.setSoTimeout(5000);
                try {
                    httpWorkers.execute(() -> handle(socket));
                } catch (RejectedExecutionException overloaded) {
                    try { socket.close(); } catch (Exception ignored) {}
                }
            }
        } catch (Exception ignored) {
            running = false;
        }
    }

    private void handle(Socket socket) {
        try (Socket client = socket;
             BufferedReader reader = new BufferedReader(
                     new InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8));
             BufferedWriter writer = new BufferedWriter(
                     new OutputStreamWriter(client.getOutputStream(), StandardCharsets.UTF_8))) {
            String request = reader.readLine();
            String target = request == null ? "/" : request.split(" ")[1];
            String path = target;
            String query = "";
            int separator = target.indexOf('?');
            if (separator >= 0) {
                path = target.substring(0, separator);
                query = target.substring(separator + 1);
            }
            String origin = null;
            String referer = null;
            String headerToken = null;
            String headerLine;
            while ((headerLine = reader.readLine()) != null && !headerLine.isEmpty()) {
                int colon = headerLine.indexOf(':');
                if (colon <= 0) continue;
                String name = headerLine.substring(0, colon).trim().toLowerCase(Locale.US);
                String value = headerLine.substring(colon + 1).trim();
                if ("origin".equals(name)) origin = value;
                else if ("referer".equals(name)) referer = value;
                else if ("x-lucent-auth".equals(name)) headerToken = value;
            }
            if (MUTATING_ENDPOINTS.contains(path)) {
                // A browser cannot strip Origin/Referer from a cross-origin
                // request, so their mere presence marks page-initiated CSRF —
                // including from EmuFusion's own BrowserActivity.
                if (origin != null || referer != null) {
                    respond(writer, "403 Forbidden",
                            "{\"error\":\"browser-originated request refused\"}");
                    return;
                }
                if (!THEME_CALLED_ENDPOINTS.contains(path) &&
                        !tokenAuthorized(headerToken, parseQuery(query).get("token"))) {
                    respond(writer, "403 Forbidden",
                            "{\"error\":\"missing or invalid control token\"}");
                    return;
                }
            }

            if ("/play".equals(path)) {
                if (gameplayActive || SystemClock.elapsedRealtime() < suppressPlayUntil) {
                    respond(writer, "200 OK", "{\"ok\":true,\"suppressed\":true}");
                    return;
                }
                placementBlank = false;
                screensaverActive = false;
                Map<String, String> values = parseQuery(query);
                long sequence = parseLong(values.get("seq"));
                if (sequence > 0L && sequence <= lastPreviewSequence) {
                    respond(writer, "200 OK", "{\"ok\":true,\"stale\":true}");
                    return;
                }
                if (sequence > 0L) lastPreviewSequence = sequence;
                String video = values.getOrDefault("video", "");
                String art = values.getOrDefault("art", "");
                String title = values.getOrDefault("title", "");
                String system = values.getOrDefault("system", "");
                String score = values.getOrDefault("score", "");
                String preloadPrev = values.getOrDefault("preload_prev", "");
                String preloadNext = values.getOrDefault("preload_next", "");
                String preloadAux = values.getOrDefault("preload_aux", "");
                boolean advance = "1".equals(values.getOrDefault("advance", "0"));
                getSharedPreferences("preview", MODE_PRIVATE).edit()
                        .putString(EXTRA_VIDEO, video)
                        .putString(EXTRA_ART, art)
                        .putString(EXTRA_TITLE, title)
                        .putString(EXTRA_SYSTEM, system)
                        .putString(EXTRA_SCORE, score)
                        .putString(EXTRA_PRELOAD_PREV, preloadPrev)
                        .putString(EXTRA_PRELOAD_NEXT, preloadNext)
                        .putString(EXTRA_PRELOAD_AUX, preloadAux)
                        .putBoolean(EXTRA_ADVANCE, advance)
                        .putLong(EXTRA_SEQUENCE, sequence)
                        .apply();
                if (browserActive) {
                    // Pegasus keeps running on the upper display during a
                    // break, so the user can still move the selection. Keep
                    // the newest one on record — closing the browser resumes
                    // what is selected then, not what was selected on open —
                    // but never start a decoder underneath the browser.
                    resumePreviewAfterBrowser = true;
                    respond(writer, "200 OK", "{\"ok\":true,\"browserActive\":true}");
                    return;
                }
                previewActive = true;
                lastPegasusHeartbeat = SystemClock.elapsedRealtime();
                mainHandler.removeCallbacks(pegasusWatchdog);
                mainHandler.postDelayed(pegasusWatchdog, 750L);
                showPlayer(video, art, title, system, score,
                        preloadPrev, preloadNext, preloadAux, sequence, advance);
                respond(writer, "200 OK", "{\"ok\":true}");
            } else if ("/screensaver/play".equals(path)) {
                Map<String, String> values = parseQuery(query);
                String video = values.getOrDefault("video", "");
                if (video.isEmpty()) {
                    respond(writer, "400 Bad Request", "{\"error\":\"video required\"}");
                    return;
                }
                if (gameplayActive || browserActive ||
                        PreviewActivity.isGameplaySurfaceActive()) {
                    respond(writer, "409 Conflict",
                            "{\"ok\":false,\"suppressed\":true}");
                    return;
                }
                screensaverActive = true;
                placementBlank = false;
                previewActive = true;
                lastPegasusHeartbeat = SystemClock.elapsedRealtime();
                mainHandler.removeCallbacks(pegasusWatchdog);
                mainHandler.postDelayed(pegasusWatchdog, 750L);
                // QML owns the only screensaver video and its metadata on the
                // top panel. Keep EmuFusion's lower-display Activity present,
                // but fully black; sending this for every shuffled item also
                // repairs a lower Activity recreated during the session.
                showScreensaverBlackout();
                respond(writer, "200 OK",
                        "{\"ok\":true,\"lowerDisplayBlack\":true}");
            } else if ("/launch/status".equals(path)) {
                // Reading consumes the request. The localhost response reaches
                // Pegasus before it yields the top display to the emulator,
                // preventing a launch from repeating when Pegasus resumes.
                long sequence = requestedLaunchSequence;
                requestedLaunchSequence = 0L;
                long completed = completedPreviewSequence;
                completedPreviewSequence = 0L;
                respond(writer, "200 OK", "{\"seq\":" + sequence +
                        ",\"completedSeq\":" + completed + "}");
            } else if ("/heartbeat".equals(path)) {
                long now = SystemClock.elapsedRealtime();
                maybeReloadMigratedLaunchRoutes();
                if (browserActive) {
                    // The break owns preview state until the browser closes.
                    // Resurrecting playback here would both put a movie back
                    // under the browser and reorder the lower-display task
                    // over it on every heartbeat.
                    respond(writer, "200 OK", "{\"ok\":true,\"browserActive\":true"
                            + ",\"gameplay\":" + gameplayActive + "}");
                    return;
                }
                if (placementBlank) {
                    respond(writer, "200 OK", "{\"ok\":true,\"placementBlank\":true"
                            + ",\"gameplay\":" + gameplayActive + "}");
                    return;
                }
                if (!PrimaryDisplayFocusGuard.isInteractive(this)) {
                    // A delayed QML heartbeat must not resurrect an Activity
                    // after Sleep. Existing logical preview state survives;
                    // the watchdog or a fresh heartbeat can recover on wake.
                    respond(writer, "200 OK", "{\"ok\":true,\"noninteractive\":true"
                            + ",\"gameplay\":" + gameplayActive + "}");
                    return;
                }
                if (previewActive) {
                    lastPegasusHeartbeat = now;
                    // The lower launcher can cover a still-running Activity.
                    // Reclaim only the secondary display while Pegasus is
                    // actively heartbeating on the upper display.
                    if (!PreviewActivity.isVisible()) {
                        if (screensaverActive) showScreensaverBlackout();
                        else showLastPlayer();
                    }
                } else if (!gameplayActive && now >= suppressPlayUntil) {
                    // Pegasus has become active again after a game, Home, or a
                    // process restart. Restore the last selection without
                    // requiring the user to move to another item first.
                    previewActive = true;
                    lastPegasusHeartbeat = now;
                    mainHandler.removeCallbacks(pegasusWatchdog);
                    mainHandler.postDelayed(pegasusWatchdog, 750L);
                    showLastPlayer();
                }
                // The frontend cannot detect in-window gameplay on its own: the
                // game view is added to the SAME Activity and the Qt window is
                // kept deliberately warm, so Qt.application.state never leaves
                // ApplicationActive. Reporting it here is what lets the theme
                // stand its pollers down while a game owns the screen.
                respond(writer, "200 OK", "{\"ok\":true,\"gameplay\":"
                        + gameplayActive + "}");
            } else if ("/hide".equals(path)) {
                screensaverActive = false;
                suppressPlayUntil = SystemClock.elapsedRealtime() + 1500L;
                previewActive = false;
                resumePreviewAfterBrowser = false;
                sendBroadcast(new Intent(ACTION_HIDE).setPackage(getPackageName()));
                respond(writer, "200 OK", "{\"ok\":true}");
            } else if ("/transition".equals(path)) {
                screensaverActive = false;
                Map<String, String> values = parseQuery(query);
                long sequence = parseLong(values.get("seq"));
                if (sequence > 0L && sequence <= lastPreviewSequence) {
                    respond(writer, "200 OK", "{\"ok\":true,\"stale\":true}");
                    return;
                }
                if (sequence > 0L) lastPreviewSequence = sequence;
                // A navigation transition is not a launch-time blank. Keep
                // the outgoing decoded frame visible until /play reports that
                // the incoming decoder has rendered; PreviewActivity then
                // performs the short crossfade.
                suppressPlayUntil = 0L;
                if (browserActive) {
                    // Navigating the library during a break arms the resume
                    // without ending the break.
                    resumePreviewAfterBrowser = true;
                    respond(writer, "200 OK", "{\"ok\":true,\"browserActive\":true}");
                    return;
                }
                previewActive = true;
                lastPegasusHeartbeat = SystemClock.elapsedRealtime();
                respond(writer, "200 OK", "{\"ok\":true}");
            } else if ("/capabilities".equals(path)) {
                boolean dualScreen = BootReceiver.secondaryDisplayId(this) >= 0;
                boolean soundEnabled = getSharedPreferences("preview", MODE_PRIVATE)
                        .getBoolean(EXTRA_SOUND_ENABLED, false);
                respond(writer, "200 OK", "{\"dualScreen\":" + dualScreen
                        + ",\"previewPlacement\":\""
                        + (dualScreen ? "secondary-display" : "upper-right-pip")
                        + "\",\"soundEnabled\":" + soundEnabled
                        + ",\"soundEffects\":" + MenuSoundPlayer.isEnabled(this)
                        + "}");
            } else if ("/screensaver/status".equals(path)) {
                JSONObject status = PreviewActivity.screensaverStatus();
                status.put("gameplay", gameplayActive);
                status.put("browserActive", browserActive);
                status.put("screensaverActive", screensaverActive);
                status.put("lowerDisplayBlack", screensaverActive);
                respond(writer, "200 OK", status.toString());
            } else if ("/audit/artwork".equals(path)) {
                try {
                    respond(writer, "200 OK", ArtworkAudit.run(new java.io.File(
                            android.os.Environment.getExternalStorageDirectory(),
                            "pegasus-frontend")).toString());
                } catch (Exception error) {
                    Log.e("ArtworkAudit", "Audit failed", error);
                    respond(writer, "500 Internal Server Error",
                            "{\"error\":\"artwork audit failed\"}");
                }
            } else if ("/private-diagnostics/status".equals(path)) {
                respond(writer, "200 OK", PrivateDiagnostics.status(this).toString());
            } else if ("/settings/private-diagnostics".equals(path)) {
                Map<String, String> values = parseQuery(query);
                String requested = values.get("enabled");
                if (!"0".equals(requested) && !"1".equals(requested)) {
                    respond(writer, "400 Bad Request", "{\"error\":\"explicit choice required\"}");
                    return;
                }
                PrivateDiagnostics.setEnabled(this, "1".equals(requested));
                respond(writer, "200 OK", PrivateDiagnostics.status(this).toString());
            } else if ("/settings/sound".equals(path)) {
                Map<String, String> values = parseQuery(query);
                String requested = values.getOrDefault("enabled", "0");
                boolean enabled = !"0".equals(requested)
                        && !"false".equalsIgnoreCase(requested);
                getSharedPreferences("preview", MODE_PRIVATE).edit()
                        .putBoolean(EXTRA_SOUND_ENABLED, enabled)
                        .apply();
                sendBroadcast(new Intent(ACTION_AUDIO)
                        .setPackage(getPackageName())
                        .putExtra(EXTRA_SOUND_ENABLED, enabled));
                respond(writer, "200 OK", "{\"ok\":true,\"soundEnabled\":"
                        + enabled + "}");
            } else if ("/settings/sfx".equals(path)) {
                // Sound Effects defaults on, so an absent parameter means on;
                // only an explicit 0/false turns the menu blips off.
                Map<String, String> values = parseQuery(query);
                String requested = values.getOrDefault("enabled", "1");
                boolean enabled = !"0".equals(requested)
                        && !"false".equalsIgnoreCase(requested);
                MenuSoundPlayer.setEnabled(this, enabled);
                respond(writer, "200 OK", "{\"ok\":true,\"soundEffects\":"
                        + enabled + "}");
            } else if ("/settings/frame-generation".equals(path)) {
                Map<String, String> values = parseQuery(query);
                if (values.containsKey("mode")) {
                    String requested = values.get("mode");
                    FrameGenerationSettings.Mode parsed =
                            FrameGenerationSettings.Mode.parse(requested);
                    String normalized = requested == null ? "" :
                            requested.trim().toLowerCase(Locale.US);
                    if (!parsed.storedValue().equals(normalized)) {
                        respond(writer, "400 Bad Request",
                                "{\"error\":\"mode must be off, built-in-alpha, or lsfg\"}");
                        return;
                    }
                    FrameGenerationSettings.setMode(this, parsed);
                } else if (values.containsKey("enabled")) {
                    // Old themes may still send enabled=false while migrating.
                    // A legacy Boolean must never reactivate experimental code.
                    String requested = values.get("enabled");
                    boolean enabled = !"0".equals(requested)
                            && !"false".equalsIgnoreCase(requested);
                    if (enabled) {
                        respond(writer, "409 Conflict",
                                "{\"error\":\"legacy frame-generation enable is disabled; select an explicit mode\"}");
                        return;
                    }
                    FrameGenerationSettings.setMode(this,
                            FrameGenerationSettings.Mode.OFF);
                }
                FrameGenerationSettings.Mode mode = FrameGenerationSettings.mode(this);
                respond(writer, "200 OK", "{\"ok\":true,\"frameGenerationMode\":\""
                        + mode.storedValue() + "\",\"frameGeneration\":"
                        + (mode != FrameGenerationSettings.Mode.OFF) + "}");
                if (!values.containsKey("enabled") && !values.containsKey("mode")) return;
            } else if ("/settings/widescreen-hack".equals(path)) {
                WidescreenHackEndpoint.Result hack = WidescreenHackEndpoint.handle(this, query);
                respond(writer, hack.status, hack.body);
            } else if ("/multiplayer/identity".equals(path)) {
                MultiplayerIdentityEndpoint.Result identity =
                        MultiplayerIdentityEndpoint.handle(this, query);
                respond(writer, identity.status, identity.body);
            } else if ("/multiplayer/roster".equals(path)) {
                MultiplayerRosterEndpoint.Result roster = MultiplayerRosterEndpoint.handle(this, query);
                respond(writer, roster.status, roster.body);
            } else if ("/multiplayer/want".equals(path)) {
                MultiplayerWantEndpoint.Result want = MultiplayerWantEndpoint.handle(this, query);
                respond(writer, want.status, want.body);
            } else if ("/multiplayer/schedule/submit".equals(path)) {
                MultiplayerScheduleEndpoint.Result scheduleSubmit =
                        MultiplayerScheduleEndpoint.submit(this, query);
                respond(writer, scheduleSubmit.status, scheduleSubmit.body);
            } else if ("/multiplayer/schedule/cancel".equals(path)) {
                MultiplayerScheduleEndpoint.Result scheduleCancel =
                        MultiplayerScheduleEndpoint.cancel(this, query);
                respond(writer, scheduleCancel.status, scheduleCancel.body);
            } else if ("/multiplayer/invite/respond".equals(path)) {
                MultiplayerInviteEndpoint.Result inviteResponse =
                        MultiplayerInviteEndpoint.handle(this, query);
                respond(writer, inviteResponse.status, inviteResponse.body);
            } else if ("/multiplayer/status".equals(path)) {
                MultiplayerStatusEndpoint.Result status = MultiplayerStatusEndpoint.handle(this, query);
                respond(writer, status.status, status.body);
            } else if ("/settings/widescreen".equals(path)) {
                Map<String, String> values = parseQuery(query);
                if (values.containsKey("enabled")) {
                    String requested = values.get("enabled");
                    WidescreenSettings.setEnabled(this,
                            !"0".equals(requested) &&
                            !"false".equalsIgnoreCase(requested));
                }
                respond(writer, "200 OK",
                        "{\"ok\":true,\"widescreenEnhancements\":" +
                        WidescreenSettings.isEnabled(this) + "}");
            } else if ("/sfx".equals(path)) {
                // Lets the theme sound an interaction that is not a plain key
                // press — most importantly the denial blip, which no key of its
                // own can produce. Playing is a no-op while the setting is off.
                MenuSoundPlayer.Cue cue = MenuSoundPlayer.cueByName(
                        parseQuery(query).get("name"));
                if (cue == null) {
                    respond(writer, "400 Bad Request",
                            "{\"error\":\"unknown sound effect\"}");
                    return;
                }
                MenuSoundPlayer.play(this, cue);
                respond(writer, "200 OK", "{\"ok\":true,\"played\":\""
                        + cue.name().toLowerCase(Locale.US) + "\",\"enabled\":"
                        + MenuSoundPlayer.isEnabled(this) + "}");
            } else if ("/led".equals(path)) {
                Map<String, String> values = parseQuery(query);
                boolean enabled = !"0".equals(values.getOrDefault("enabled", "1"));
                String brightnessValue = values.getOrDefault("brightness", "system");
                int brightness = -1;
                if (!"system".equalsIgnoreCase(brightnessValue)) {
                    try {
                        brightness = Integer.parseInt(brightnessValue);
                    } catch (NumberFormatException ignored) {}
                }
                boolean applied = enabled && thorLedManager.setColor(
                        values.getOrDefault("color", ""), brightness);
                respond(writer, "200 OK", "{\"ok\":true,\"available\":" +
                        thorLedManager.available() + ",\"applied\":" + applied +
                        ",\"brightness\":" + thorLedManager.appliedBrightness() +
                        ",\"systemBrightness\":" +
                        thorLedManager.rememberedDeviceBrightness() + "}");
            } else if ("/blank".equals(path)) {
                screensaverActive = false;
                placementBlank = true;
                suppressPlayUntil = SystemClock.elapsedRealtime() + 1500L;
                previewActive = false;
                resumePreviewAfterBrowser = false;
                sendBroadcast(new Intent(ACTION_BLANK).setPackage(getPackageName()));
                respond(writer, "200 OK", "{\"ok\":true}");
            } else if ("/import/scan".equals(path)) {
                importManager.startScan();
                respond(writer, "202 Accepted", importManager.statusJson());
            } else if ("/maintenance/rescan".equals(path)) {
                importManager.startManualScan();
                updateManager.checkAsync(true);
                respond(writer, "202 Accepted", importManager.statusJson());
            } else if ("/feedback/status".equals(path)) {
                respond(writer, "200 OK", VoiceFeedbackManager.status().toString());
            } else if ("/feedback/record".equals(path)) {
                Map<String, String> values = parseQuery(query);
                VoiceFeedbackManager.begin(values.getOrDefault("title", ""),
                        values.getOrDefault("system", ""),
                        values.getOrDefault("page", ""));
                boolean opened = VoiceFeedbackActivity.open(this);
                JSONObject feedback = VoiceFeedbackManager.status().put("ok", opened);
                respond(writer, opened ? "202 Accepted" : "500 Internal Server Error",
                        feedback.toString());
            } else if ("/feedback/cancel".equals(path)) {
                VoiceFeedbackActivity.cancelActive();
                respond(writer, "200 OK", VoiceFeedbackManager.status()
                        .put("ok", true).toString());
            } else if ("/feedback/send".equals(path)) {
                Map<String, String> values = parseQuery(query);
                if (values.containsKey("transcript"))
                    VoiceFeedbackManager.replaceTranscript(values.get("transcript"));
                // The authenticated GitHub review uses the same in-app browser
                // as an ordinary browsing break. Silence preview decoders
                // before its lower-display window appears, and undo the break
                // if GitHub could not be opened.
                beginBrowserBreak();
                JSONObject feedback = VoiceFeedbackManager.openGithubComposer(this);
                if (!feedback.optBoolean("ok", false)) endBrowserBreak();
                respond(writer, feedback.optBoolean("ok", false) ?
                        "202 Accepted" : "409 Conflict", feedback.toString());
            } else if ("/browser/open".equals(path)) {
                String requestedUrl = parseQuery(query).getOrDefault("url", "");
                // Break first: the decoders must be silent and still before
                // the window appears, so no movie is ever heard underneath
                // the browser and the watchdog is already disarmed when the
                // lower-display task loses the front.
                beginBrowserBreak();
                int displayId = BrowserActivity.open(this, requestedUrl);
                boolean opened = displayId != BrowserActivity.LAUNCH_FAILED;
                // A refused window would otherwise leave previews stopped
                // with nothing on screen to close.
                if (!opened) endBrowserBreak();
                respond(writer, opened ? "202 Accepted" : "500 Internal Server Error",
                        "{\"ok\":" + opened + ",\"displayId\":" + displayId + "}");
            } else if ("/import/initial".equals(path)) {
                importManager.startInitialScan();
                respond(writer, "202 Accepted", importManager.statusJson());
            } else if ("/import/status".equals(path)) {
                respond(writer, "200 OK", importManager.statusJson());
            } else if ("/import/reload".equals(path)) {
                boolean reload = importManager.consumeReloadRequest();
                respond(writer, "200 OK", "{\"ok\":" + reload + "}");
                if (reload) mainHandler.postDelayed(this::reloadEmuFusionFrontend, 220L);
            } else if ("/library/index".equals(path)) {
                respond(writer, "200 OK", libraryIndexManager.json());
            } else if ("/archive/list".equals(path)) {
                respond(writer, "200 OK", importManager.archiveJson());
            } else if ("/archive/include".equals(path)) {
                Map<String, String> values = parseQuery(query);
                boolean included = importManager.includeArchived(values.getOrDefault("id", ""));
                respond(writer, included ? "200 OK" : "404 Not Found",
                        "{\"ok\":" + included + "}");
            } else if ("/game/rename".equals(path)) {
                Map<String, String> values = parseQuery(query);
                boolean renamed = importManager.renameGame(
                        values.getOrDefault("id", ""), values.getOrDefault("title", ""));
                respond(writer, renamed ? "200 OK" : "404 Not Found",
                        "{\"ok\":" + renamed + "}");
            } else if ("/artwork/missing".equals(path)) {
                // Read-only: the games whose box art could not be found and
                // that the owner has not answered for yet.
                respond(writer, "200 OK", importManager.artworkReviewJson());
            } else if ("/artwork/decide".equals(path)) {
                Map<String, String> values = parseQuery(query);
                String applied = importManager.decideArtwork(
                        values.getOrDefault("key", ""), values.getOrDefault("choice", ""));
                respond(writer, applied.isEmpty() ? "404 Not Found" : "200 OK",
                        "{\"ok\":" + !applied.isEmpty() + ",\"choice\":\"" + applied + "\"}");
            } else if ("/game/delete".equals(path)) {
                Map<String, String> values = parseQuery(query);
                boolean deleted = importManager.deleteGame(values.getOrDefault("id", ""));
                respond(writer, deleted ? "200 OK" : "404 Not Found",
                        "{\"ok\":" + deleted + ",\"recoverable\":false}");
            } else if ("/cheats/list".equals(path)) {
                // Answered on demand when the user opens a game's options.
                // Deliberately not pushed or polled: a cheat catalogue only
                // changes when the user edits their own file, and the theme
                // has no timer that could notice it any sooner.
                Map<String, String> values = parseQuery(query);
                respond(writer, "200 OK", CheatControl.listJson(this,
                        values.getOrDefault("system", ""),
                        values.getOrDefault("title", "")));
            } else if ("/cheats/set".equals(path)) {
                Map<String, String> values = parseQuery(query);
                String requested = values.getOrDefault("enabled", "0");
                boolean enabled = !"0".equals(requested)
                        && !"false".equalsIgnoreCase(requested);
                // Writes the selection a later launch reads. A game that is
                // already running owns its own copy and is toggled from the
                // in-game menu instead, which is why this path never tries to
                // reach the engine.
                boolean changed = CheatControl.setEnabled(this,
                        values.getOrDefault("system", ""),
                        values.getOrDefault("title", ""),
                        values.getOrDefault("id", ""), enabled);
                respond(writer, changed ? "200 OK" : "404 Not Found",
                        "{\"ok\":" + changed + ",\"enabled\":" + enabled + "}");
            } else if ("/update/check".equals(path)) {
                updateManager.checkAsync(true);
                respond(writer, "202 Accepted", updateManager.statusJson());
            } else if ("/frontend/ready".equals(path)) {
                // The theme reports its library is up. This is what dismisses
                // the Java boot screen, which owns the display from onStart --
                // before any QML exists to report anything itself.
                sendBroadcast(new Intent(
                        com.thorium.preview.BootVideoOverlay.ACTION_FRONTEND_READY)
                        .setPackage(getPackageName()));
                respond(writer, "200 OK", "{\"ok\":true}");
            } else if ("/update/status".equals(path)) {
                respond(writer, "200 OK", updateManager.statusJson());
            } else if ("/update/install".equals(path)) {
                updateManager.installDownloadedApk();
                respond(writer, "202 Accepted", updateManager.statusJson());
            } else if ("/legal/notice".equals(path)) {
                // The Settings copy of the first-launch notice. It is served
                // from LegalNotice rather than duplicated into QML for the same
                // reason the startup overlay reads it: a legal notice that says
                // two different things in two places is worse than one that
                // says nothing. Read-only, and unlike the popup it carries no
                // scroll gate and no checkbox — it is just readable text.
                JSONObject notice = new JSONObject();
                JSONArray paragraphs = new JSONArray();
                for (String paragraph : com.thorium.lucent.legal.LegalNotice.PARAGRAPHS)
                    paragraphs.put(paragraph);
                notice.put("title", com.thorium.lucent.legal.LegalNotice.TITLE);
                notice.put("paragraphs", paragraphs);
                notice.put("body", com.thorium.lucent.legal.LegalNotice.body());
                respond(writer, "200 OK", notice.toString());
            } else if ("/route/systems".equals(path)) {
                respond(writer, "200 OK", RoutePicker.systemsJson(
                        this, importManager.activeSystemFolders()));
            } else if ("/route/options".equals(path)) {
                respond(writer, "200 OK", RoutePicker.optionsJson(
                        this, parseQuery(query).getOrDefault("system", "")));
            } else if ("/route/resolve".equals(path)) {
                respond(writer, "200 OK", RoutePicker.resolveJson(
                        this, parseQuery(query).getOrDefault("system", "")));
            } else if ("/route/set".equals(path)) {
                Map<String, String> values = parseQuery(query);
                JSONObject result = RoutePicker.setRoute(this,
                        values.getOrDefault("system", ""),
                        values.getOrDefault("route", ""),
                        values.getOrDefault("emulator", ""));
                if (result.optBoolean("authorizationRequired", false))
                    result.put("authorizationOpened", openExternalStopAuthorization());
                else applyRouteChange(result);
                respond(writer, "200 OK", result.toString());
            } else if ("/route/clear".equals(path)) {
                JSONObject result = RoutePicker.clearRoute(
                        this, parseQuery(query).getOrDefault("system", ""));
                applyRouteChange(result);
                respond(writer, "200 OK", result.toString());
            } else if ("/route/link".equals(path)) {
                // One tap, two outcomes. Installed: bound to this system.
                // Missing: the install source opens and nothing is recorded, so
                // the user comes back and taps the same row again.
                Map<String, String> values = parseQuery(query);
                JSONObject result = RoutePicker.link(this,
                        values.getOrDefault("system", ""),
                        values.getOrDefault("emulator", ""));
                if (result.optBoolean("linked", false)) applyRouteChange(result);
                else if (result.optBoolean("authorizationRequired", false))
                    result.put("authorizationOpened", openExternalStopAuthorization());
                else if (result.optBoolean("ok", false))
                    result.put("opened", openInstallSource(result.optJSONObject("install")));
                respond(writer, "200 OK", result.toString());
            } else if ("/route/custom".equals(path)) {
                Map<String, String> values = parseQuery(query);
                String system = values.getOrDefault("system", "");
                JSONObject result;
                if ("1".equals(values.getOrDefault("clear", "0"))) {
                    CustomEmulatorStore.clear(this, system);
                    // A cleared custom target must not stay selected, or the
                    // system would resolve external with nothing behind it.
                    EngineRouteStore.clearRoute(this, system);
                    result = new JSONObject().put("ok", true).put("cleared", true);
                    applyRouteChange(result);
                } else {
                    result = CustomEmulatorStore.save(this, system,
                            values.getOrDefault("package", ""),
                            values.getOrDefault("activity", ""),
                            values.getOrDefault("delivery", ""),
                            values.getOrDefault("romExtraKey", ""));
                    // Finishing the guided setup is the act of choosing it;
                    // making the user then pick it from the list again would be
                    // a second step with no decision in it.
                    if (result.optBoolean("ok", false)) {
                        if (!ExternalEmulationSession.stopControlEnabled(this)) {
                            result.put("selected", false);
                            result.put("authorizationRequired", true);
                            result.put("authorizationOpened",
                                    openExternalStopAuthorization());
                        } else {
                            result.put("selected", EngineRouteStore.setRoute(this, system,
                                    EngineRouteStore.EXTERNAL, CustomEmulatorStore.ID));
                            applyRouteChange(result);
                        }
                    }
                }
                respond(writer, "200 OK", result.toString());
            } else {
                respond(writer, "200 OK", "{\"service\":\"lucent\",\"ok\":true}");
            }
        } catch (Exception ignored) {
        }
    }

    /**
     * Makes a route change take effect everywhere.
     *
     * Re-emitting every collection's {@code launch:} line walks the whole
     * library, so it runs off the HTTP worker: with only two workers, doing it
     * inline would let one settings tap stall the control plane the theme is
     * simultaneously polling. The response therefore reports that the change
     * was accepted, not that the rewrite has finished — the import status's
     * existing needsReload flag is what the theme already watches to know the
     * library has caught up.
     */
    private void applyRouteChange(JSONObject result) {
        if (result == null || !result.optBoolean("ok", false)) return;
        try {
            result.put("rewriting", true);
        } catch (Exception ignored) {}
        Thread rewrite = new Thread(() -> importManager.rewriteLaunchRoutes(),
                "lucent-route-rewrite");
        rewrite.setDaemon(true);
        rewrite.start();
    }

    /**
     * Opens where a missing emulator is installed from. Play listings need the
     * Play app itself — a web view cannot install an APK — so the market:// form
     * is tried first and the https page is the fallback for a device with no
     * Play Store, where it opens in EmuFusion's own lower-display browser
     * rather than handing the user off to whatever else is on the device.
     */
    private boolean openInstallSource(JSONObject install) {
        if (install == null) return false;
        String market = install.optString("marketUrl", "");
        if (!market.isEmpty() && startExternalView(market)) return true;
        String url = install.optString("url", "");
        if (url.isEmpty()) return false;
        if (url.startsWith("http://") || url.startsWith("https://")) {
            // Same break as /browser/open: the decoders must be silent and
            // still before the window appears on the lower display.
            beginBrowserBreak();
            if (BrowserActivity.open(this, url) != BrowserActivity.LAUNCH_FAILED)
                return true;
            endBrowserBreak();
            return false;
        }
        return startExternalView(url);
    }

    /**
     * Android intentionally forbids silent AccessibilityService enablement.
     * This is the one-time OS-owned consent screen reached only while the user
     * is setting up an external route, never between selecting and playing a
     * game. Returning to the picker and selecting again completes the link.
     */
    private boolean openExternalStopAuthorization() {
        try {
            startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            return true;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private boolean startExternalView(String uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, android.net.Uri.parse(uri))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            return true;
        } catch (RuntimeException unavailable) {
            Log.i("LucentRoute", "No handler for install source " + uri);
            return false;
        }
    }

    /** Stops preview playback for as long as EmuFusion's browser is open.
     *
     * Three things fight a naive pause and are neutralised here: the 750 ms
     * pegasusWatchdog (disarmed, and previewActive false so a queued run
     * returns immediately), /heartbeat (short-circuits on browserActive), and
     * /play and /transition (record the selection without showing it). */
    private synchronized void beginBrowserBreak() {
        if (browserActive) return;
        browserActive = true;
        resumePreviewAfterBrowser = previewActive;
        previewActive = false;
        mainHandler.removeCallbacks(pegasusWatchdog);
        getSharedPreferences("preview", MODE_PRIVATE).edit()
                .putBoolean(EXTRA_BROWSER_ACTIVE, true).apply();
        sendBroadcast(new Intent(ACTION_PAUSE).setPackage(getPackageName()));
        Log.i(BROWSER_TAG, "browser break started resumeOnClose="
                + resumePreviewAfterBrowser + " gameplayActive=" + gameplayActive);
    }

    /** Ends the break and puts the lower display back the way the user left
     * it — the newest selection playing, or EmuFusion's own black surface. */
    private synchronized void endBrowserBreak() {
        if (!browserActive) return;
        browserActive = false;
        getSharedPreferences("preview", MODE_PRIVATE).edit()
                .putBoolean(EXTRA_BROWSER_ACTIVE, false).apply();
        // Ordered ahead of the update below: the same receiver takes both, so
        // the decoders are unpaused before a new selection reaches them.
        sendBroadcast(new Intent(ACTION_RESUME).setPackage(getPackageName()));
        boolean resume = resumePreviewAfterBrowser && !gameplayActive &&
                !placementBlank && !screensaverActive;
        resumePreviewAfterBrowser = false;
        if (resume) {
            previewActive = true;
            lastPegasusHeartbeat = SystemClock.elapsedRealtime();
            mainHandler.removeCallbacks(pegasusWatchdog);
            mainHandler.postDelayed(pegasusWatchdog, 750L);
            // Doubles as the reorder that brings the lower-display task back
            // above the closing browser task.
            showLastPlayer();
        } else if (!PreviewActivity.isGameplaySurfaceActive()) {
            // Nothing to resume, but EmuFusion still owns that display: show its
            // OLED-black surface rather than let Android's launcher appear as
            // the browser task disappears. A dual-screen game is the one case
            // that already owns the display and must not be touched.
            launchPlayerOnSecondary(new Intent(this, PreviewActivity.class)
                    .setAction(ACTION_BLANK)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                            | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT));
        }
        Log.i(BROWSER_TAG, "browser break ended resumedPreview=" + resume);
    }

    private void reloadEmuFusionFrontend() {
        Activity frontendOwner = LucentApplication.currentMainActivity();
        if (gameplayActive || browserActive || screensaverActive ||
                frontendOwner == null || !frontendOwner.hasWindowFocus()) {
            launchRouteReloadPending.set(true);
            return;
        }
        if (!InWindowGameHost.tryBeginImportFrontendRestart()) {
            // The library appears before the asynchronous checkpoint finishes.
            // Keep this request pending; heartbeat retries after teardown, with
            // no timer that can kill a guest merely because its save is slow.
            launchRouteReloadPending.set(true);
            if (!importReloadWaitLogged) {
                Log.i("LucentImport", "Deferred frontend reload until game retirement completes");
                importReloadWaitLogged = true;
            }
            return;
        }
        importReloadWaitLogged = false;
        placementBlank = true;
        previewActive = false;
        sendBroadcast(new Intent(ACTION_BLANK).setPackage(getPackageName()));
        Intent frontend = new Intent(Intent.ACTION_MAIN)
                .setComponent(new ComponentName(getPackageName(),
                        "org.pegasus_frontend.android.MainActivity"))
                .addCategory(Intent.CATEGORY_LAUNCHER)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        try {
            // Qt 5 owns native renderer state for the lifetime of this process.
            // Clearing/recreating only MainActivity abandons its SurfaceView while
            // QtThread continues dequeuing the old BufferQueue; the replacement
            // window never draws or receives focus and Android reports an ANR.
            // A system AlarmManager relaunch is not sufficient on Android 13:
            // after this process exits the PendingIntent is classified as a
            // background activity start and is dropped. Hand the transition to a
            // tiny Activity in a separate process while our window is still
            // foreground. It remains the focused transition owner while ending
            // this process, then starts a genuinely fresh Qt process.
            Intent restart = new Intent(frontendOwner, FrontendRestartActivity.class)
                    .putExtra(FrontendRestartActivity.EXTRA_OLD_PROCESS_PID,
                            android.os.Process.myPid())
                    .addFlags(Intent.FLAG_ACTIVITY_NO_ANIMATION);
            frontendOwner.startActivity(restart);
            Log.i("LucentImport", "Started clean EmuFusion process reload after import");
        } catch (RuntimeException error) {
            InWindowGameHost.cancelImportFrontendRestart();
            launchRouteReloadPending.set(true);
            Log.e("LucentImport", "Unable to refresh Lucent after import", error);
        }
    }

    /**
     * Consumes a startup metadata or bundled-theme refresh only when the
     * frontend itself has demonstrated liveness. Re-arm on a transiently
     * unsafe state so a game, screensaver, browser break, or unfocused startup
     * window is never interrupted merely to refresh frontend content.
     */
    private void maybeReloadMigratedLaunchRoutes() {
        if (gameplayActive || browserActive || screensaverActive ||
                !launchRouteReloadPending.compareAndSet(true, false)) return;
        mainHandler.postDelayed(() -> {
            Activity owner = LucentApplication.currentMainActivity();
            if (gameplayActive || browserActive || screensaverActive ||
                    owner == null || !owner.hasWindowFocus()) {
                launchRouteReloadPending.set(true);
                return;
            }
            reloadEmuFusionFrontend();
        }, 350L);
    }

    private static long parseLong(String value) {
        if (value == null || value.isEmpty()) return 0L;
        try {
            return Long.parseLong(value);
        } catch (NumberFormatException ignored) {
            return 0L;
        }
    }

    private void showPlayer(String video, String art, String title,
                            String system, String score,
                            String preloadPrev, String preloadNext, String preloadAux,
                            long sequence, boolean advance) {
        Intent update = new Intent(ACTION_UPDATE)
                .setPackage(getPackageName())
                .putExtra(EXTRA_VIDEO, video)
                .putExtra(EXTRA_ART, art)
                .putExtra(EXTRA_TITLE, title)
                .putExtra(EXTRA_SYSTEM, system)
                .putExtra(EXTRA_SCORE, score)
                .putExtra(EXTRA_PRELOAD_PREV, preloadPrev)
                .putExtra(EXTRA_PRELOAD_NEXT, preloadNext)
                .putExtra(EXTRA_PRELOAD_AUX, preloadAux)
                .putExtra(EXTRA_ADVANCE, advance)
                .putExtra(EXTRA_SEQUENCE, sequence);
        if (PreviewActivity.isVisible()) {
            sendBroadcast(update);
            return;
        }

        // A retained Activity can still be hidden behind the secondary
        // launcher. In that state a broadcast updates decoders but leaves the
        // launcher visible, so explicitly reorder the lower-display task.
        // Never use AppTask.moveToFront(): AYN's shared display group can then
        // disturb Pegasus on display 0.
        Intent activity = new Intent(this, PreviewActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
                .putExtra(EXTRA_VIDEO, video)
                .putExtra(EXTRA_ART, art)
                .putExtra(EXTRA_TITLE, title)
                .putExtra(EXTRA_SYSTEM, system)
                .putExtra(EXTRA_SCORE, score)
                .putExtra(EXTRA_PRELOAD_PREV, preloadPrev)
                .putExtra(EXTRA_PRELOAD_NEXT, preloadNext)
                .putExtra(EXTRA_PRELOAD_AUX, preloadAux)
                .putExtra(EXTRA_ADVANCE, advance)
                .putExtra(EXTRA_SEQUENCE, sequence);
        launchPlayerOnSecondary(activity);
    }

    /** Keeps the physical lower panel OLED-black while QML plays the
     * screensaver exclusively on the upper display. This is deliberately not
     * {@link #showPlayer}: no lower decoder, artwork, or title chrome may be
     * resurrected by a watchdog or Activity recreation during screensaver. */
    private void showScreensaverBlackout() {
        Intent blank = new Intent(ACTION_BLANK).setPackage(getPackageName());
        if (PreviewActivity.isVisible()) {
            sendBroadcast(blank);
            return;
        }
        launchPlayerOnSecondary(new Intent(this, PreviewActivity.class)
                .setAction(ACTION_BLANK)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                        | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT));
    }

    /** Places EmuFusion's private preview/blackout surface on the physical lower display. */
    private void launchPlayerOnSecondary(Intent activity) {
        if (!PrimaryDisplayFocusGuard.isInteractive(this)) return;
        // A caller can have observed a stopped window before an intervening
        // onStart. Browser-close blackout also reaches this gateway directly.
        // Update an existing window without re-topping its display.
        if (PreviewActivity.isVisible()) {
            String action = ACTION_BLANK.equals(activity.getAction())
                    ? ACTION_BLANK : ACTION_UPDATE;
            sendBroadcast(new Intent(action).putExtras(activity).setPackage(getPackageName()));
            return;
        }
        ActivityOptions options = ActivityOptions.makeBasic();
        int displayId = BootReceiver.secondaryDisplayId(this);
        // The native companion is exclusively a physical-secondary-display
        // player. Single-screen devices render their preview as a QML PIP in
        // Pegasus instead of opening a full-screen Android activity.
        if (displayId < 0) return;
        options.setLaunchDisplayId(displayId);
        if (Build.VERSION.SDK_INT >= 34) {
            options.setPendingIntentCreatorBackgroundActivityStartMode(
                    ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED);
            options.setPendingIntentBackgroundActivityStartMode(
                    ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED);
        }
        try {
            // The user-granted overlay capability is also Android's explicit
            // exemption for a background service to restore a user-visible
            // activity.  Direct launch is required on Android 13: a
            // self-created PendingIntent can be silently accepted yet leave a
            // different task covering display 4.
            if (Settings.canDrawOverlays(this)) {
                if (!PrimaryDisplayFocusGuard.isInteractive(this)) return;
                startActivity(activity, options.toBundle());
                return;
            }
            // Android blocks a foreground service from directly restoring an
            // activity after it has been sent behind the secondary launcher.
            // A creator-and-sender opted-in PendingIntent is the platform's
            // supported route for this user-visible playback transition.
            PendingIntent pending = PendingIntent.getActivity(
                    this, 43821, activity,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE,
                    options.toBundle());
            if (!PrimaryDisplayFocusGuard.isInteractive(this)) return;
            pending.send(this, 0, null, null, null, null, options.toBundle());
        } catch (PendingIntent.CanceledException | RuntimeException error) {
            Log.e("ThorPreview", "Unable to restore preview activity on display "
                    + displayId, error);
        }
    }

    private void showLastPlayer() {
        android.content.SharedPreferences preferences =
                getSharedPreferences("preview", MODE_PRIVATE);
        showPlayer(
                preferences.getString(EXTRA_VIDEO, ""),
                preferences.getString(EXTRA_ART, ""),
                preferences.getString(EXTRA_TITLE, ""),
                preferences.getString(EXTRA_SYSTEM, ""),
                preferences.getString(EXTRA_SCORE, ""),
                preferences.getString(EXTRA_PRELOAD_PREV, ""),
                preferences.getString(EXTRA_PRELOAD_NEXT, ""),
                preferences.getString(EXTRA_PRELOAD_AUX, ""),
                preferences.getLong(EXTRA_SEQUENCE, 0L),
                preferences.getBoolean(EXTRA_ADVANCE, false));
    }

    private static Map<String, String> parseQuery(String query) throws Exception {
        Map<String, String> values = new HashMap<>();
        if (query.isEmpty()) return values;
        for (String pair : query.split("&")) {
            String[] item = pair.split("=", 2);
            String key = URLDecoder.decode(item[0], "UTF-8");
            String value = item.length > 1 ? URLDecoder.decode(item[1], "UTF-8") : "";
            values.put(key, value);
        }
        return values;
    }

    private static void respond(BufferedWriter writer, String status, String body) throws Exception {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        writer.write("HTTP/1.1 " + status + "\r\n");
        writer.write("Content-Type: application/json\r\n");
        writer.write("Content-Length: " + bytes.length + "\r\n");
        writer.write("Connection: close\r\n\r\n");
        writer.write(body);
        writer.flush();
    }

    @Override
    public void onDestroy() {
        running = false;
        if (importManager != null) importManager.close();
        previewActive = false;
        mainHandler.removeCallbacks(pegasusWatchdog);
        try {
            if (browserReceiverRegistered) unregisterReceiver(browserReceiver);
        } catch (RuntimeException ignored) {
        }
        // Deliberately absent: any DownloadManager teardown. Downloads started
        // from the browser belong to the system download service from enqueue
        // onward and must survive this service, the browser window, and the
        // process itself.
        try {
            if (server != null) server.close();
        } catch (Exception ignored) {
        }
        httpWorkers.shutdownNow();
        super.onDestroy();
    }
}
