package com.thorium.preview.game;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.preview.PreviewService;
import com.thorium.preview.multiplayer.DeviceIdentity;
import com.thorium.preview.multiplayer.MultiplayerManager;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.UnsupportedEncodingException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Small, non-blocking overlay that surfaces multiplayer invites and
 * scheduled-match countdowns while a game is running inside
 * {@link InWindowGameHost}.
 *
 * <p>Modeled on the "custom Java view drawn straight over Qt's surface, added
 * via {@code root.addView(...)} and {@code bringToFront()}" technique used by
 * {@code LegalNoticeOverlay} and {@code BootVideoOverlay} -- NOT on their
 * full-screen dimmed-scrim look. Those two own the whole window while they are
 * up; this one must never take a single pixel of gameplay input, because the
 * whole point of it is to be visible while a game keeps running underneath.
 * It never calls {@code setClickable(true)} on itself, and its only clickable
 * children are the small "Play Now" / dismiss controls on the invite banner.
 *
 * <h3>The pause-gated polling rule</h3>
 * <p>There is no push path from {@code MultiplayerManager} to this overlay
 * yet (a real, known gap -- see the class doc on
 * {@code PreviewService.getMultiplayerManager()} and on
 * {@code MultiplayerManager} itself), so the only way this overlay learns
 * about a new invite or schedule is by polling
 * {@code GET /multiplayer/status} on the companion's localhost port.
 *
 * <p>This codebase has already been burned once by exactly this shape of
 * mistake: {@code theme.qml}'s {@code importPollTimer} wedged Qt's network
 * thread by polling the companion server during live gameplay, and is now
 * hard-gated {@code running: !root.gameplayActive}. This overlay applies the
 * same rule the same way: the status poll only ever runs while
 * {@link #setPauseMenuOpen} has most recently been told the pause menu is
 * open (i.e. the engine is itself paused, not actively rendering), and it
 * stops for good the moment a match goes active -- once a match exists there
 * is nothing left worth polling for. See {@link #setPauseMenuOpen} and
 * {@link #pollOnce}.
 *
 * <p>The unavoidable consequence: an invite that arrives while the player is
 * mid-game and never opens the pause menu will not surface until they do (or
 * until they next open it for an unrelated reason). That is a real UX gap,
 * accepted for this pass rather than building a push mechanism or a
 * gameplay-safe polling scheme that does not exist yet anywhere else in this
 * codebase.
 *
 * <p>What is NOT gated on the pause menu is the countdown chip's own tick:
 * once a {@code match.scheduled} payload has been fetched, the remaining time
 * is recomputed locally from its {@code scheduledAt} timestamp on a plain
 * {@link Handler#postDelayed} loop, with no backend call per tick, so the
 * chip keeps counting down correctly through live gameplay after the pause
 * menu that discovered it has been closed again.
 */
final class MultiplayerOverlay extends FrameLayout {
    private static final String TAG = "LucentMultiplayerOverlay";

    /** A few seconds, per the session's own guidance for a paused-only poll. */
    private static final long POLL_INTERVAL_MS = 4000L;
    private static final long TICK_INTERVAL_MS = 1000L;
    private static final String STATUS_PATH = "/multiplayer/status";
    private static final String RESPOND_PATH = "/multiplayer/invite/respond";

    private static final ExecutorService NETWORK = Executors.newSingleThreadExecutor(
            runnable -> {
                Thread thread = new Thread(runnable, "LucentMultiplayerOverlayHttp");
                thread.setDaemon(true);
                return thread;
            });

    private final Activity activity;
    private final GameLaunchRequest request;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    /**
     * Best-effort local stand-in for the multiplayer backend's own
     * {@code gameKey}. The API contract this overlay was built against
     * specifies gameKey only as an opaque wire string -- it does not say how
     * a client computes one for "the game currently running" -- and the
     * companion endpoints / QML panel pieces of this feature were built by
     * two other agents this overlay never saw the code of. {@link
     * CheatDatabase#key} (system + normalised title) is reused here because
     * it is this codebase's one existing convention for "the same game
     * across two different local copies/devices" (its own doc explains why:
     * regional/revision variants share a title but not a content hash).
     * If the other two pieces settled on a different gameKey formula, the
     * "already running the right game" comparison below will simply always
     * miss and every Play Now will fall into the safe no-op branch --
     * confirm this against the companion endpoints' actual gameKey source
     * before shipping.
     */
    private final String localGameKey;

    private final LinearLayout banner;
    private final TextView bannerText;
    private final TextView chip;

    private boolean pauseMenuOpen;
    private boolean userHidden;
    private boolean matchActive;
    private boolean ticking;

    /** The invite currently rendered in {@link #banner}, or null. */
    private JSONObject shownInvite;
    /** A banner the player dismissed without responding; suppressed until a fresh poll drops it. */
    private String dismissedMatchId = "";

    private long tickingScheduledAtEpochMs = -1L;

    private final Runnable pollTick = this::pollOnce;
    private final Runnable tickTask = this::tick;

    MultiplayerOverlay(Activity activity, GameLaunchRequest request) {
        super(activity);
        this.activity = activity;
        this.request = request;
        this.localGameKey = CheatDatabase.key(request.systemId, request.gameTitle);
        // Passes touches through to the gameplay surface everywhere except
        // the two small children built below.
        setClickable(false);

        float density = activity.getResources().getDisplayMetrics().density;

        banner = new LinearLayout(activity);
        banner.setOrientation(LinearLayout.HORIZONTAL);
        banner.setGravity(Gravity.CENTER_VERTICAL);
        banner.setPadding(dp(density, 16), dp(density, 10), dp(density, 12), dp(density, 10));
        GradientDrawable bannerBackground = new GradientDrawable();
        bannerBackground.setColor(Color.argb(235, 24, 24, 29));
        bannerBackground.setCornerRadius(dp(density, 14));
        bannerBackground.setStroke(dp(density, 1), Color.argb(120, 151, 119, 255));
        banner.setBackground(bannerBackground);
        banner.setVisibility(GONE);

        bannerText = new TextView(activity);
        bannerText.setTextColor(Color.WHITE);
        bannerText.setTextSize(14f);
        bannerText.setMaxWidth(dp(density, 260));
        LinearLayout.LayoutParams textParams = new LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        banner.addView(bannerText, textParams);

        Button playNow = new Button(activity);
        playNow.setAllCaps(false);
        playNow.setText("Play Now");
        playNow.setTextColor(Color.WHITE);
        playNow.setTextSize(13f);
        GradientDrawable playBackground = new GradientDrawable();
        playBackground.setColor(Color.rgb(151, 119, 255));
        playBackground.setCornerRadius(dp(density, 9));
        playNow.setBackground(playBackground);
        playNow.setPadding(dp(density, 14), dp(density, 4), dp(density, 14), dp(density, 4));
        playNow.setMinWidth(0);
        playNow.setMinimumWidth(0);
        playNow.setOnClickListener(view -> onPlayNowTapped());
        LinearLayout.LayoutParams playParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        playParams.leftMargin = dp(density, 10);
        banner.addView(playNow, playParams);

        TextView dismiss = new TextView(activity);
        dismiss.setText("✕");
        dismiss.setTextColor(Color.argb(200, 255, 255, 255));
        dismiss.setTextSize(16f);
        dismiss.setPadding(dp(density, 14), 0, 0, 0);
        dismiss.setOnClickListener(view -> dismissBanner());
        banner.addView(dismiss);

        FrameLayout.LayoutParams bannerParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.TOP | Gravity.CENTER_HORIZONTAL);
        bannerParams.topMargin = dp(density, 24);
        addView(banner, bannerParams);

        chip = new TextView(activity);
        chip.setTextColor(Color.WHITE);
        chip.setTextSize(12f);
        chip.setPadding(dp(density, 10), dp(density, 5), dp(density, 10), dp(density, 5));
        GradientDrawable chipBackground = new GradientDrawable();
        chipBackground.setColor(Color.argb(210, 24, 24, 29));
        chipBackground.setCornerRadius(dp(density, 11));
        chipBackground.setStroke(dp(density, 1), Color.argb(90, 255, 255, 255));
        chip.setBackground(chipBackground);
        chip.setVisibility(GONE);
        FrameLayout.LayoutParams chipParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.TOP | Gravity.RIGHT);
        chipParams.topMargin = dp(density, 14);
        chipParams.rightMargin = dp(density, 14);
        addView(chip, chipParams);
    }

    private static int dp(float density, int value) {
        return Math.round(value * density);
    }

    // ---- Lifecycle hooks called by InWindowGameHost ----

    /**
     * Called from {@code showPauseMenu()}/{@code hidePauseMenu()}. This is
     * the single gate on this overlay ever touching the network -- see the
     * class doc's "pause-gated polling rule".
     */
    void setPauseMenuOpen(boolean open) {
        pauseMenuOpen = open;
        if (open) {
            startTicking();
            pollOnce();
        } else {
            mainHandler.removeCallbacks(pollTick);
            // The chip's own tick keeps running -- it is local arithmetic,
            // not a network call, and is exactly what makes it "persistent"
            // through the gameplay this pause menu is about to resume.
        }
    }

    /**
     * Called from the pause menu's "Multiplayer" row. First tap after
     * construction just shows whatever the initial {@link #setPauseMenuOpen}
     * poll already found; every tap after that is a manual show/hide, since
     * this row is the only remaining way to reach this overlay once the
     * player has hidden it and is not expecting the game itself to reopen it.
     */
    void toggleUserHidden() {
        userHidden = !userHidden;
        if (userHidden) {
            banner.setVisibility(GONE);
            chip.setVisibility(GONE);
            return;
        }
        // This row only exists inside the pause menu, so every call here
        // happens while the game is already paused -- a fresh look is always
        // within the polling rule above.
        pollOnce();
        renderBanner();
        renderChip();
    }

    /** Called from InWindowGameHost.detachViews() when this session ends. */
    void destroy() {
        mainHandler.removeCallbacks(pollTick);
        stopTicking();
    }

    // ---- Status polling (pause-gated; see class doc) ----

    private void pollOnce() {
        if (!pauseMenuOpen || matchActive) return;
        NETWORK.execute(() -> {
            JSONObject status = fetchJson(STATUS_PATH, "");
            mainHandler.post(() -> {
                if (status != null) applyStatus(status);
                // Re-checked after the round trip: the menu may have closed,
                // or a match may have gone active, while this request was in
                // flight.
                if (pauseMenuOpen && !matchActive)
                    mainHandler.postDelayed(pollTick, POLL_INTERVAL_MS);
            });
        });
    }

    private void applyStatus(JSONObject status) {
        boolean active = !status.isNull("activeMatchId")
                && !status.optString("activeMatchId", "").isEmpty();
        matchActive = active;
        if (active) {
            mainHandler.removeCallbacks(pollTick);
            stopTicking();
            shownInvite = null;
            tickingScheduledAtEpochMs = -1L;
            banner.setVisibility(GONE);
            chip.setVisibility(GONE);
            return;
        }

        JSONObject invite = firstRelevantInvite(status.optJSONArray("invites"));
        shownInvite = invite;
        renderBanner();

        JSONObject scheduled = firstSchedule(status.optJSONArray("scheduled"));
        long scheduledAtEpochMs = scheduled == null ? -1L
                : parseRfc3339(scheduled.optString("scheduledAt"));
        tickingScheduledAtEpochMs = scheduledAtEpochMs;
        renderChip();
        if (scheduledAtEpochMs > 0L) startTicking();
        else stopTicking();
    }

    private JSONObject firstRelevantInvite(JSONArray invites) {
        if (invites == null) return null;
        for (int index = 0; index < invites.length(); index++) {
            JSONObject invite = invites.optJSONObject(index);
            if (invite == null) continue;
            String matchId = invite.optString("matchId");
            if (matchId.isEmpty() || matchId.equals(dismissedMatchId)) continue;
            return invite;
        }
        return null;
    }

    private JSONObject firstSchedule(JSONArray scheduled) {
        if (scheduled == null) return null;
        for (int index = 0; index < scheduled.length(); index++) {
            JSONObject entry = scheduled.optJSONObject(index);
            if (entry != null && !entry.optString("matchId").isEmpty()) return entry;
        }
        return null;
    }

    // ---- Rendering ----

    private void renderBanner() {
        if (userHidden || shownInvite == null) {
            banner.setVisibility(GONE);
            return;
        }
        String title = request.gameTitle.isEmpty()
                ? shownInvite.optString("gameKey") : request.gameTitle;
        String who = firstOtherParticipant(shownInvite.optJSONArray("participants"));
        bannerText.setText((who.isEmpty() ? "Someone" : who) + " wants to play " + title);
        banner.setVisibility(VISIBLE);
        banner.bringToFront();
    }

    private void renderChip() {
        if (userHidden || tickingScheduledAtEpochMs <= 0L) {
            chip.setVisibility(GONE);
            return;
        }
        long remainingMs = tickingScheduledAtEpochMs - System.currentTimeMillis();
        if (remainingMs <= 0L) {
            chip.setVisibility(GONE);
            return;
        }
        chip.setText("Match in " + formatCountdown(remainingMs));
        chip.setVisibility(VISIBLE);
    }

    /**
     * The invite payload only ever carries device ids (see
     * {@code InviteAvailable} in backend/internal/protocol/messages.go --
     * there is no inviter nickname field in the contract this overlay was
     * built against), so the banner falls back to a shortened device id
     * rather than a real name. A nicer banner needs either a nickname added
     * to that payload or a roster lookup keyed by device id; flagged here
     * rather than built, per this pass's scope.
     */
    private String firstOtherParticipant(JSONArray participants) {
        if (participants == null) return "";
        String myDeviceId = DeviceIdentity.deviceId(activity);
        for (int index = 0; index < participants.length(); index++) {
            String candidate = participants.optString(index, "");
            if (!candidate.isEmpty() && !candidate.equals(myDeviceId))
                return "Player " + candidate.substring(0, Math.min(8, candidate.length()));
        }
        return "";
    }

    private static String formatCountdown(long remainingMs) {
        long totalSeconds = remainingMs / 1000L;
        long hours = totalSeconds / 3600L;
        long minutes = (totalSeconds % 3600L) / 60L;
        long seconds = totalSeconds % 60L;
        if (hours > 0L) return String.format(Locale.US, "%d:%02d:%02d", hours, minutes, seconds);
        return String.format(Locale.US, "%d:%02d", minutes, seconds);
    }

    private void dismissBanner() {
        if (shownInvite != null) dismissedMatchId = shownInvite.optString("matchId");
        shownInvite = null;
        banner.setVisibility(GONE);
    }

    // ---- Local countdown tick (no network per tick; see class doc) ----

    private void startTicking() {
        if (ticking) return;
        ticking = true;
        mainHandler.post(tickTask);
    }

    private void stopTicking() {
        ticking = false;
        mainHandler.removeCallbacks(tickTask);
    }

    private void tick() {
        if (!ticking) return;
        renderChip();
        if (tickingScheduledAtEpochMs > 0L
                && System.currentTimeMillis() < tickingScheduledAtEpochMs) {
            mainHandler.postDelayed(tickTask, TICK_INTERVAL_MS);
        } else {
            ticking = false;
        }
    }

    // ---- Play Now ----

    private void onPlayNowTapped() {
        JSONObject invite = shownInvite;
        if (invite == null) return;
        String matchId = invite.optString("matchId");
        String inviteGameKey = invite.optString("gameKey");
        List<String> participants = toStringList(invite.optJSONArray("participants"));

        if (!localGameKey.equals(inviteGameKey)) {
            // Real, separate work this session explicitly deferred (see
            // MultiplayerManager.activateMatch's own "known gap" doc):
            // tearing down whatever is currently running and launching the
            // invited game instead. Not attempted here -- log loudly and
            // leave the invite exactly as it was so the player can act on it
            // after switching games themselves.
            Log.w(TAG, "Play Now tapped for gameKey=" + inviteGameKey +
                    " but this session is running gameKey=" + localGameKey +
                    " (system=" + request.systemId + ", title=" + request.gameTitle +
                    "); automatically relaunching into the invited game is not " +
                    "implemented in this pass -- ignoring the tap.");
            Toast.makeText(activity, "That invite is for a different game. Launch it, " +
                    "then accept from its own pause menu.", Toast.LENGTH_LONG).show();
            return;
        }

        banner.setVisibility(GONE);
        NETWORK.execute(() -> {
            fetchJson(RESPOND_PATH, "matchId=" + urlEncode(matchId) + "&accept=1");
            mainHandler.post(() -> {
                MultiplayerManager manager = PreviewService.getMultiplayerManager();
                if (manager == null) {
                    Log.w(TAG, "Play Now: PreviewService has no MultiplayerManager yet " +
                            "(matchId=" + matchId + ")");
                    return;
                }
                // The HTTP call above already told the backend this device
                // accepts; this same-process call is the separate step that
                // actually builds the WebRTC session and attaches it to the
                // running engine (see MultiplayerManager.activateMatch's own
                // doc on why the two are not merged into one).
                manager.activateMatch(matchId, participants);
            });
        });
    }

    private static List<String> toStringList(JSONArray array) {
        List<String> list = new ArrayList<>();
        if (array == null) return list;
        for (int index = 0; index < array.length(); index++) {
            String value = array.optString(index, "");
            if (!value.isEmpty()) list.add(value);
        }
        return list;
    }

    // ---- Companion HTTP (plain HttpURLConnection, matching this codebase's
    // established convention -- no OkHttp; see e.g. UpdateManager) ----

    /** GET the given companion path with an optional query string; null on any failure. */
    private static JSONObject fetchJson(String path, String query) {
        HttpURLConnection connection = null;
        try {
            String url = "http://127.0.0.1:" + PreviewService.PORT + path +
                    (query.isEmpty() ? "" : "?" + query);
            connection = (HttpURLConnection) new URL(url).openConnection();
            connection.setConnectTimeout(2000);
            connection.setReadTimeout(2000);
            connection.setRequestMethod("GET");
            int code = connection.getResponseCode();
            InputStream stream = code >= 200 && code < 300
                    ? connection.getInputStream() : connection.getErrorStream();
            if (stream == null) return null;
            StringBuilder body = new StringBuilder();
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) body.append(line);
            }
            return new JSONObject(body.toString());
        } catch (IOException | JSONException | RuntimeException failure) {
            Log.w(TAG, "Multiplayer companion request failed path=" + path, failure);
            return null;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static String urlEncode(String value) {
        try {
            return URLEncoder.encode(value, "UTF-8");
        } catch (UnsupportedEncodingException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    /**
     * Minimal RFC3339 parser (date, {@code T}, time, optional fractional
     * seconds, then {@code Z} or a {@code +HH:MM}/{@code -HH:MM} offset) --
     * exactly what the backend's {@code scheduledAt} field emits
     * (backend/internal/protocol/messages.go). Written by hand rather than
     * with {@code java.time} because this project's actual minimum supported
     * API level is unclear across its two source trees (android-companion's
     * manifest declares 26, but unified-android also carries a separate
     * "api21-lint" project declaring 21) and {@code java.time.Instant} needs
     * API 26. Returns -1 for anything that fails to parse.
     */
    private static long parseRfc3339(String value) {
        if (value == null || value.isEmpty()) return -1L;
        try {
            int splitIndex = value.indexOf('T');
            if (splitIndex < 0) return -1L;
            String[] dateFields = value.substring(0, splitIndex).split("-");
            if (dateFields.length != 3) return -1L;
            int year = Integer.parseInt(dateFields[0]);
            int month = Integer.parseInt(dateFields[1]);
            int day = Integer.parseInt(dateFields[2]);

            String timePart = value.substring(splitIndex + 1);
            int offsetMinutes = 0;
            char last = timePart.charAt(timePart.length() - 1);
            if (last == 'Z' || last == 'z') {
                timePart = timePart.substring(0, timePart.length() - 1);
            } else {
                int colon = timePart.indexOf(':');
                int signIndex = Math.max(timePart.lastIndexOf('+'), timePart.lastIndexOf('-'));
                if (signIndex > colon) {
                    String offsetText = timePart.substring(signIndex);
                    timePart = timePart.substring(0, signIndex);
                    String[] offsetFields = offsetText.substring(1).split(":");
                    int offsetHours = Integer.parseInt(offsetFields[0]);
                    int offsetMins = offsetFields.length > 1
                            ? Integer.parseInt(offsetFields[1]) : 0;
                    offsetMinutes = (offsetHours * 60 + offsetMins)
                            * (offsetText.charAt(0) == '-' ? -1 : 1);
                }
            }
            int dot = timePart.indexOf('.');
            int millis = 0;
            if (dot >= 0) {
                String fraction = (timePart.substring(dot + 1) + "000").substring(0, 3);
                millis = Integer.parseInt(fraction);
                timePart = timePart.substring(0, dot);
            }
            String[] timeFields = timePart.split(":");
            if (timeFields.length != 3) return -1L;
            int hour = Integer.parseInt(timeFields[0]);
            int minute = Integer.parseInt(timeFields[1]);
            int second = Integer.parseInt(timeFields[2]);

            Calendar calendar = Calendar.getInstance(TimeZone.getTimeZone("UTC"), Locale.US);
            calendar.clear();
            calendar.set(year, month - 1, day, hour, minute, second);
            calendar.set(Calendar.MILLISECOND, millis);
            // "+02:00" means the wall-clock time shown is two hours ahead of
            // UTC, so the true instant is two hours earlier than what was
            // just set as if it were UTC.
            return calendar.getTimeInMillis() - offsetMinutes * 60_000L;
        } catch (RuntimeException malformed) {
            return -1L;
        }
    }
}
