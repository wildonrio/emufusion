package com.thorium.preview;

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
    // A browser break. While Lucent's browser window exists, preview playback
    // is suspended: previewActive is false so the watchdog cannot fire,
    // /heartbeat cannot resurrect it, and /play and /transition record the
    // user's newest selection without starting a decoder under the browser.
    private volatile boolean browserActive;
    private volatile boolean resumePreviewAfterBrowser;
    private volatile long lastPegasusHeartbeat;
    private volatile long lastPreviewSequence;
    private volatile long requestedLaunchSequence;
    private volatile long completedPreviewSequence;
    private ImportManager importManager;
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
            if (!PreviewActivity.isVisible()) showLastPlayer();
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
            "/settings/sound", "/settings/sfx", "/sfx", "/game/rename",
            "/game/delete", "/import/scan",
            "/import/initial", "/import/reload", "/maintenance/rescan",
            "/browser/open", "/update/check", "/update/install",
            "/archive/include", "/launch/status"));
    // The port is reachable by every application on the device, so mutating
    // endpoints require a per-boot bearer token — except the ones below,
    // which the FROZEN theme/theme.qml calls without one and which therefore
    // stay open to local processes (residual risk accepted; browser CSRF is
    // still blocked by the Origin/Referer rejection on every mutating path).
    private static final Set<String> THEME_CALLED_ENDPOINTS = new HashSet<>(Arrays.asList(
            "/play", "/heartbeat", "/hide", "/transition", "/blank", "/led",
            "/settings/sound", "/settings/sfx", "/sfx", "/game/rename",
            "/game/delete", "/import/scan",
            "/import/reload", "/maintenance/rescan", "/browser/open",
            "/update/check", "/update/install", "/launch/status"));
    private volatile String controlToken = "";
    private UpdateManager updateManager;
    private LibraryIndexManager libraryIndexManager;
    private ThorLedManager thorLedManager;

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
        libraryIndexManager = new LibraryIndexManager();
        thorLedManager = new ThorLedManager(this);
        // Decode the four menu blips now. SoundPool loads asynchronously, and
        // doing it at process start means the user's very first D-pad press in
        // the library is already audible.
        MenuSoundPlayer.warmUp(this);
        Thread launchMigration = new Thread(() -> {
            int changed = LaunchMetadataRouter.normalize(this);
            if (changed > 0) {
                Log.i("LucentLaunchMetadata",
                        "Migrated " + changed + " collection launch routes");
                // Do not force-restart Pegasus here. On large libraries the
                // frontend may still be creating its first window; clearing
                // that task can leave Android with no focused window and
                // trigger an ANR. New imports already emit the stable route,
                // while a migrated legacy library is picked up by the next
                // normal library/app reload.
            }
        }, "lucent-launch-metadata");
        launchMigration.setDaemon(true);
        launchMigration.start();
        if (ThemeInstaller.hasStorageAccess(this)) {
            ThemeInstaller.installBundledIfNeeded(this, () -> updateManager.checkAsync(false));
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
                "preview", "Lucent", NotificationManager.IMPORTANCE_MIN);
        channel.setDescription("Synchronizes previews, imports games, and checks for updates");
        manager.createNotificationChannel(channel);
        Notification notification = new Notification.Builder(this, "preview")
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentTitle("Lucent")
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
        if (intent != null && ACTION_GAMEPLAY.equals(intent.getAction())) {
            gameplayActive = true;
            placementBlank = false;
            previewActive = false;
            // A game started; closing the browser later must not put a movie
            // back on the lower display underneath it.
            resumePreviewAfterBrowser = false;
            suppressPlayUntil = SystemClock.elapsedRealtime() + 5000L;
            mainHandler.removeCallbacks(pegasusWatchdog);
            // Keep the secondary display owned by Lucent but render it fully
            // black for every single-screen game. Closing this resident lower
            // display surface exposes Android's launcher, which is both a
            // burn-in risk and visually misleading. Emulation itself remains
            // exclusively inside Lucent's MainActivity on display 0.
            if (PreviewActivity.isVisible()) {
                sendBroadcast(new Intent(ACTION_BLANK).setPackage(getPackageName()));
            } else {
                launchPlayerOnSecondary(new Intent(this, PreviewActivity.class)
                        .setAction(ACTION_BLANK)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK |
                                Intent.FLAG_ACTIVITY_REORDER_TO_FRONT));
            }
        } else if (intent != null && ACTION_LIBRARY.equals(intent.getAction())) {
            gameplayActive = false;
            suppressPlayUntil = 0L;
        } else if (intent != null && ACTION_SUSPEND.equals(intent.getAction())) {
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
                // including from Lucent's own BrowserActivity.
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
                if (browserActive) {
                    // The break owns preview state until the browser closes.
                    // Resurrecting playback here would both put a movie back
                    // under the browser and reorder the lower-display task
                    // over it on every heartbeat.
                    respond(writer, "200 OK", "{\"ok\":true,\"browserActive\":true}");
                    return;
                }
                if (placementBlank) {
                    respond(writer, "200 OK", "{\"ok\":true,\"placementBlank\":true}");
                    return;
                }
                if (previewActive) {
                    lastPegasusHeartbeat = now;
                    // The lower launcher can cover a still-running Activity.
                    // Reclaim only the secondary display while Pegasus is
                    // actively heartbeating on the upper display.
                    if (!PreviewActivity.isVisible()) showLastPlayer();
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
                respond(writer, "200 OK", "{\"ok\":true}");
            } else if ("/hide".equals(path)) {
                suppressPlayUntil = SystemClock.elapsedRealtime() + 1500L;
                previewActive = false;
                resumePreviewAfterBrowser = false;
                sendBroadcast(new Intent(ACTION_HIDE).setPackage(getPackageName()));
                respond(writer, "200 OK", "{\"ok\":true}");
            } else if ("/transition".equals(path)) {
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
                if (reload) mainHandler.postDelayed(this::reloadLucentFrontend, 220L);
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
            } else if ("/game/delete".equals(path)) {
                Map<String, String> values = parseQuery(query);
                boolean deleted = importManager.deleteGame(values.getOrDefault("id", ""));
                respond(writer, deleted ? "200 OK" : "404 Not Found",
                        "{\"ok\":" + deleted + ",\"recoverable\":false}");
            } else if ("/update/check".equals(path)) {
                updateManager.checkAsync(true);
                respond(writer, "202 Accepted", updateManager.statusJson());
            } else if ("/update/status".equals(path)) {
                respond(writer, "200 OK", updateManager.statusJson());
            } else if ("/update/install".equals(path)) {
                updateManager.installDownloadedApk();
                respond(writer, "202 Accepted", updateManager.statusJson());
            } else {
                respond(writer, "200 OK", "{\"service\":\"lucent\",\"ok\":true}");
            }
        } catch (Exception ignored) {
        }
    }

    /** Stops preview playback for as long as Lucent's browser is open.
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
     * it — the newest selection playing, or Lucent's own black surface. */
    private synchronized void endBrowserBreak() {
        if (!browserActive) return;
        browserActive = false;
        getSharedPreferences("preview", MODE_PRIVATE).edit()
                .putBoolean(EXTRA_BROWSER_ACTIVE, false).apply();
        // Ordered ahead of the update below: the same receiver takes both, so
        // the decoders are unpaused before a new selection reaches them.
        sendBroadcast(new Intent(ACTION_RESUME).setPackage(getPackageName()));
        boolean resume = resumePreviewAfterBrowser && !gameplayActive && !placementBlank;
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
            // Nothing to resume, but Lucent still owns that display: show its
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

    private void reloadLucentFrontend() {
        placementBlank = true;
        previewActive = false;
        sendBroadcast(new Intent(ACTION_BLANK).setPackage(getPackageName()));
        Intent frontend = new Intent(Intent.ACTION_MAIN)
                .setComponent(new ComponentName(getPackageName(),
                        "org.pegasus_frontend.android.MainActivity"))
                .addCategory(Intent.CATEGORY_LAUNCHER)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        try {
            startActivity(frontend);
        } catch (RuntimeException error) {
            Log.e("LucentImport", "Unable to refresh Lucent after import", error);
        }
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

    /** Places Lucent's private preview/blackout surface on the physical lower display. */
    private void launchPlayerOnSecondary(Intent activity) {
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
