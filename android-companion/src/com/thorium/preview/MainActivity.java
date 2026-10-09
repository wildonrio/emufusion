package com.thorium.preview;

import android.Manifest;
import android.app.Activity;
import android.app.ActivityManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Human-facing setup and status screen. PreviewActivity is display-only. */
public final class MainActivity extends Activity {
    private static final int STORAGE_REQUEST = 41;
    private static final String PEGASUS_PACKAGE = "org.pegasus_frontend.android";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView serviceStatus;
    private TextView themeStatus;
    private TextView permissionStatus;
    private TextView activityStatus;
    private TextView openPegasusButton;
    private TextView repairThemeButton;
    private TextView updateCheckButton;
    private TextView updateInstallButton;
    private TextView grantAccessButton;
    private boolean polling;
    private boolean initialScanRequested;
    private volatile int updateMonitorGeneration;

    private final Runnable poller = new Runnable() {
        @Override public void run() {
            if (!polling) return;
            refreshStatus();
            handler.postDelayed(this, 1500L);
        }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setStatusBarColor(Color.rgb(5, 7, 11));
        getWindow().setNavigationBarColor(Color.rgb(5, 7, 11));
        buildUi();
        startEmuFusionService();
        requestStorageIfNeeded(false);
    }

    @Override protected void onResume() {
        super.onResume();
        polling = true;
        handler.removeCallbacks(poller);
        handler.post(poller);
        if (hasLibraryAccess() && !initialScanRequested) {
            initialScanRequested = true;
            handler.postDelayed(() -> callService("/import/initial",
                    "Automatic library discovery started"), 500L);
        }
        handler.postDelayed(() -> monitorUpdateStatus(false), 700L);
    }

    @Override protected void onPause() {
        polling = false;
        handler.removeCallbacks(poller);
        super.onPause();
    }

    private void buildUi() {
        FrameLayout root = new FrameLayout(this);
        root.setBackground(background(new int[]{Color.rgb(6, 9, 14), Color.rgb(12, 18, 27)}, 0));
        setContentView(root);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        root.addView(scroll, fill());

        LinearLayout stage = new LinearLayout(this);
        stage.setOrientation(LinearLayout.VERTICAL);
        stage.setGravity(Gravity.CENTER_HORIZONTAL);
        stage.setPadding(dp(24), dp(34), dp(24), dp(34));
        scroll.addView(stage, new ScrollView.LayoutParams(
                ScrollView.LayoutParams.MATCH_PARENT, ScrollView.LayoutParams.WRAP_CONTENT));

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        int screen = getResources().getDisplayMetrics().widthPixels;
        int contentWidth = Math.min(screen - dp(48), dp(780));
        stage.addView(content, new LinearLayout.LayoutParams(contentWidth,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        TextView mark = label("EMUFUSION  /  ANDROID COMPANION  /  APP " + appVersionName(),
                12, Color.rgb(113, 230, 176));
        mark.setLetterSpacing(0.18f);
        content.addView(mark, matchWrap(0));

        TextView title = label("EmuFusion", 38, Color.WHITE);
        title.setTypeface(Typeface.create("sans", Typeface.BOLD));
        content.addView(title, matchWrap(dp(8)));

        TextView intro = label("Your library automation, media previews, and EmuFusion theme are managed here.",
                17, Color.rgb(183, 193, 207));
        intro.setLineSpacing(0, 1.18f);
        content.addView(intro, matchWrap(dp(8)));

        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(22), dp(18), dp(22), dp(18));
        card.setBackground(cardBackground());
        LinearLayout.LayoutParams cardParams = matchWrap(dp(28));
        cardParams.bottomMargin = dp(16);
        content.addView(card, cardParams);

        TextView ready = label("SYSTEM STATUS", 12, Color.rgb(113, 230, 176));
        ready.setLetterSpacing(0.15f);
        card.addView(ready, matchWrap(0));
        serviceStatus = label("Starting EmuFusion service…", 18, Color.WHITE);
        serviceStatus.setTypeface(Typeface.DEFAULT_BOLD);
        card.addView(serviceStatus, matchWrap(dp(12)));
        themeStatus = label("Checking theme installation…", 15, Color.rgb(182, 192, 205));
        card.addView(themeStatus, matchWrap(dp(8)));
        permissionStatus = label("Checking library access…", 15, Color.rgb(182, 192, 205));
        card.addView(permissionStatus, matchWrap(dp(6)));

        openPegasusButton = action("OPEN PEGASUS", true, view -> openPegasus());
        content.addView(openPegasusButton, buttonParams(0));
        repairThemeButton = action("INSTALL / REPAIR EMUFUSION THEME", false,
                view -> repairTheme());
        content.addView(repairThemeButton, buttonParams(dp(10)));
        updateCheckButton = action("CHECK FOR UPDATES", false,
                view -> checkForUpdates());
        content.addView(updateCheckButton, buttonParams(dp(10)));
        updateInstallButton = action("INSTALL DOWNLOADED UPDATE", false,
                view -> callService("/update/install", "Opening Android installer"));
        content.addView(updateInstallButton, buttonParams(dp(10)));
        grantAccessButton = action("GRANT LIBRARY ACCESS", false,
                view -> requestStorageIfNeeded(true));
        content.addView(grantAccessButton, buttonParams(dp(10)));

        activityStatus = label("EmuFusion scans the complete device automatically after library access is granted.",
                14, Color.rgb(146, 158, 174));
        activityStatus.setGravity(Gravity.CENTER);
        activityStatus.setLineSpacing(0, 1.15f);
        LinearLayout.LayoutParams activityParams = matchWrap(dp(20));
        activityParams.bottomMargin = dp(16);
        content.addView(activityStatus, activityParams);

        TextView foot = label("The lower-screen player opens automatically only when Pegasus sends a preview. " +
                "Opening EmuFusion itself will always return to this dashboard.",
                13, Color.rgb(105, 118, 135));
        foot.setGravity(Gravity.CENTER);
        foot.setLineSpacing(0, 1.15f);
        content.addView(foot, matchWrap(0));
    }

    private void startEmuFusionService() {
        Intent service = new Intent(this, PreviewService.class);
        // This visible Activity is already a foreground entry point. Reserve
        // startForegroundService for BootReceiver's background-only start.
        startService(service);
    }

    private void repairTheme() {
        activityStatus.setText("Installing the bundled EmuFusion theme…");
        ThemeInstaller.forceInstallBundled(this, () -> runOnUiThread(() -> {
            activityStatus.setText("EmuFusion theme installed. Open Pegasus to use it.");
            refreshStatus();
        }));
    }

    private void openPegasus() {
        Intent launch = getPackageManager().getLaunchIntentForPackage(PEGASUS_PACKAGE);
        if (launch == null) {
            activityStatus.setText("Pegasus Frontend is not installed. Install Pegasus first, then return here.");
            try {
                startActivity(new Intent(Intent.ACTION_VIEW,
                        Uri.parse("https://pegasus-frontend.org/")));
            } catch (RuntimeException ignored) {}
            return;
        }
        // Metadata is parsed when Pegasus starts. Reordering an existing task
        // leaves its stale in-memory library intact, which made a successful
        // scan look empty. Pegasus is backgrounded while this dashboard is
        // visible, so restart only that process and launch a fresh task.
        ActivityManager manager = (ActivityManager)getSystemService(ACTIVITY_SERVICE);
        if (manager != null) manager.killBackgroundProcesses(PEGASUS_PACKAGE);
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        handler.postDelayed(() -> startActivity(launch), 250L);
    }

    private void requestStorageIfNeeded(boolean userInitiated) {
        if (hasLibraryAccess()) {
            if (permissionStatus != null) {
                permissionStatus.setText("✓  Library access granted");
                permissionStatus.setTextColor(Color.rgb(113, 230, 176));
            }
            if (userInitiated) activityStatus.setText("Library access is already granted.");
            return;
        }
        if (!userInitiated) {
            permissionStatus.setText("Library access needs approval");
            return;
        }
        if (Build.VERSION.SDK_INT >= 30) {
            try {
                startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                        Uri.parse("package:" + getPackageName())));
                return;
            } catch (RuntimeException ignored) {
                startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
                return;
            }
        }
        if (Build.VERSION.SDK_INT >= 23) requestPermissions(new String[]{
                Manifest.permission.READ_EXTERNAL_STORAGE,
                Manifest.permission.WRITE_EXTERNAL_STORAGE}, STORAGE_REQUEST);
    }

    private boolean hasLibraryAccess() {
        return ThemeInstaller.hasStorageAccess(this);
    }

    private void refreshStatus() {
        serviceStatus.setText("✓  EmuFusion service active");
        serviceStatus.setTextColor(Color.rgb(113, 230, 176));
        File theme = new File(Environment.getExternalStorageDirectory(),
                "pegasus-frontend/themes/lucent/theme.qml");
        String version = ThemeInstaller.installedVersion();
        boolean installed = theme.isFile();
        themeStatus.setText(installed
                ? "✓  EmuFusion theme installed" +
                        (version.isEmpty() ? "" : "  •  theme " + version) +
                        "  •  companion " + appVersionName()
                : "○  Theme installation pending");
        themeStatus.setTextColor(installed ? Color.rgb(113, 230, 176) : Color.rgb(240, 184, 92));
        setActionState(repairThemeButton, installed ? 1 : 0,
                installed ? "✓  EMUFUSION THEME INSTALLED" : "INSTALL / REPAIR EMUFUSION THEME");
        boolean permitted = hasLibraryAccess();
        permissionStatus.setText(permitted
                ? "✓  Library access granted" : "○  Library access needs approval");
        permissionStatus.setTextColor(permitted ? Color.rgb(113, 230, 176) : Color.rgb(240, 184, 92));
        setActionState(grantAccessButton, permitted ? 1 : 0,
                permitted ? "✓  LIBRARY ACCESS GRANTED" : "GRANT LIBRARY ACCESS");
        android.content.SharedPreferences updateUi = getSharedPreferences("updates-ui", 0);
        String persistedUpdateState = updateUi.getString("state", "");
        long updateAge = System.currentTimeMillis() - updateUi.getLong("updatedAt", 0L);
        boolean staleProgress = ("checking".equals(persistedUpdateState) ||
                "theme".equals(persistedUpdateState) ||
                "software".equals(persistedUpdateState)) && updateAge > 70_000L;
        if (staleProgress) {
            updateUpdateButtons("interrupted", false);
        } else if (!persistedUpdateState.isEmpty()) {
            updateUpdateButtons(persistedUpdateState,
                    updateUi.getBoolean("installReady", false));
        }
        readServiceStatus("/update/status");
    }

    private void callService(String path, String immediate) {
        activityStatus.setText(immediate + "…");
        Thread thread = new Thread(() -> {
            String response = http(path);
            runOnUiThread(() -> activityStatus.setText(message(response, immediate)));
        }, "lucent-dashboard-action");
        thread.setDaemon(true);
        thread.start();
    }

    private void checkForUpdates() {
        setActionState(updateCheckButton, 2, "CHECKING FOR UPDATES…");
        activityStatus.setText("Checking GitHub for updates…");
        Thread request = new Thread(() -> {
            http("/update/check");
            monitorUpdateStatus(true);
        }, "lucent-dashboard-update-request");
        request.setDaemon(true);
        request.start();
    }

    private void monitorUpdateStatus(boolean userInitiated) {
        final int generation = ++updateMonitorGeneration;
        Thread monitor = new Thread(() -> {
            long deadline = System.currentTimeMillis() + 55_000L;
            while (System.currentTimeMillis() < deadline && generation == updateMonitorGeneration) {
                String response = http("/update/status");
                try {
                    JSONObject value = new JSONObject(response);
                    String state = value.optString("state");
                    boolean installReady = value.optBoolean("installReady", false);
                    String statusMessage = value.optString("message", "EmuFusion is ready");
                    runOnUiThread(() -> {
                        updateUpdateButtons(state, installReady);
                        if (!"idle".equals(state)) activityStatus.setText(statusMessage);
                    });
                    if ("complete".equals(state) || "available".equals(state) ||
                            "permission".equals(state) || "error".equals(state)) return;
                } catch (Exception ignored) {}
                try { Thread.sleep(600L); }
                catch (InterruptedException interrupted) { return; }
            }
            if (generation == updateMonitorGeneration && userInitiated) {
                runOnUiThread(() -> {
                    setActionState(updateCheckButton, -1,
                            "UPDATE CHECK TIMED OUT — TAP TO RETRY");
                    activityStatus.setText("Update check timed out; network and library remain safe.");
                });
            }
        }, "lucent-dashboard-update-monitor");
        monitor.setDaemon(true);
        monitor.start();
    }

    private void readServiceStatus(String path) {
        Thread thread = new Thread(() -> {
            String response = http(path);
            if (response.isEmpty()) return;
            String message = message(response, "EmuFusion is ready");
            JSONObject value;
            try {
                value = new JSONObject(response);
            } catch (Exception ignored) { return; }
            String state = value.optString("state");
            boolean installReady = value.optBoolean("installReady", false);
            runOnUiThread(() -> {
                updateUpdateButtons(state, installReady);
                if (!"idle".equals(state)) activityStatus.setText(message);
            });
        }, "lucent-dashboard-status");
        thread.setDaemon(true);
        thread.start();
    }

    private String http(String path) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(
                    "http://127.0.0.1:" + PreviewService.PORT + path).openConnection();
            connection.setConnectTimeout(1200);
            connection.setReadTimeout(2500);
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                    connection.getInputStream(), StandardCharsets.UTF_8))) {
                StringBuilder out = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) out.append(line);
                return out.toString();
            }
        } catch (Exception ignored) {
            return "";
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private String message(String json, String fallback) {
        if (json == null || json.isEmpty()) return fallback;
        try {
            String value = new JSONObject(json).optString("message", fallback);
            return value.isEmpty() ? fallback : value;
        } catch (Exception ignored) { return fallback; }
    }

    private String appVersionName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception ignored) {
            return "unknown";
        }
    }

    private TextView action(String text, boolean primary, View.OnClickListener listener) {
        TextView button = label(text, 14, primary ? Color.rgb(4, 17, 12) : Color.WHITE);
        button.setTypeface(Typeface.DEFAULT_BOLD);
        button.setLetterSpacing(0.10f);
        button.setGravity(Gravity.CENTER);
        button.setClickable(true);
        button.setFocusable(true);
        button.setBackground(buttonBackground(primary));
        button.setOnClickListener(listener);
        return button;
    }

    private void updateUpdateButtons(String state, boolean installReady) {
        if ("idle".equals(state)) {
            setActionState(updateCheckButton, 0, "CHECK FOR UPDATES");
            setActionState(updateInstallButton, installReady ? 2 : 0,
                    installReady ? "UPDATE READY — INSTALL" : "INSTALL DOWNLOADED UPDATE");
        } else if ("checking".equals(state) || "theme".equals(state) || "software".equals(state)) {
            setActionState(updateCheckButton, 2, "CHECKING FOR UPDATES…");
            setActionState(updateInstallButton, installReady ? 2 : 0,
                    installReady ? "UPDATE READY TO INSTALL" : "INSTALL DOWNLOADED UPDATE");
        } else if ("complete".equals(state)) {
            setActionState(updateCheckButton, 1, "✓  UPDATES CHECKED — CURRENT");
            setActionState(updateInstallButton, 1, "✓  NO UPDATE INSTALL NEEDED");
        } else if ("available".equals(state) || "permission".equals(state)) {
            setActionState(updateCheckButton, 1, "✓  UPDATE CHECK COMPLETED");
            setActionState(updateInstallButton, 2, "UPDATE READY — INSTALL");
        } else if ("error".equals(state) || "interrupted".equals(state)) {
            setActionState(updateCheckButton, -1, "UPDATE CHECK FAILED — TAP TO RETRY");
            setActionState(updateInstallButton, 0, "INSTALL DOWNLOADED UPDATE");
        }
    }

    /** state: -1 error, 0 pending, 1 complete, 2 working/action required. */
    private void setActionState(TextView button, int state, String text) {
        if (button == null) return;
        button.setText(text);
        GradientDrawable background = new GradientDrawable();
        background.setCornerRadius(dp(14));
        if (state == 1) {
            background.setColor(Color.rgb(113, 230, 176));
            button.setTextColor(Color.rgb(4, 17, 12));
        } else if (state == 2) {
            background.setColor(Color.rgb(240, 184, 92));
            button.setTextColor(Color.rgb(20, 13, 3));
        } else if (state < 0) {
            background.setColor(Color.rgb(102, 35, 40));
            background.setStroke(dp(1), Color.rgb(238, 112, 121));
            button.setTextColor(Color.WHITE);
        } else {
            background.setColor(Color.rgb(22, 30, 41));
            background.setStroke(dp(1), Color.rgb(55, 69, 86));
            button.setTextColor(Color.WHITE);
        }
        button.setBackground(background);
    }

    private TextView label(String text, float size, int color) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setFontFeatureSettings("kern");
        return view;
    }

    private GradientDrawable background(int[] colors, float radius) {
        GradientDrawable shape = new GradientDrawable(GradientDrawable.Orientation.TL_BR, colors);
        shape.setCornerRadius(dp((int) radius));
        return shape;
    }

    private GradientDrawable cardBackground() {
        GradientDrawable card = background(new int[]{Color.rgb(20, 28, 39),
                Color.rgb(13, 19, 28)}, 18);
        card.setStroke(dp(1), Color.rgb(48, 61, 76));
        return card;
    }

    private GradientDrawable buttonBackground(boolean primary) {
        GradientDrawable button = new GradientDrawable();
        button.setCornerRadius(dp(14));
        if (primary) button.setColor(Color.rgb(113, 230, 176));
        else {
            button.setColor(Color.rgb(22, 30, 41));
            button.setStroke(dp(1), Color.rgb(55, 69, 86));
        }
        return button;
    }

    private LinearLayout.LayoutParams matchWrap(int top) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        params.topMargin = top;
        return params;
    }

    private LinearLayout.LayoutParams buttonParams(int top) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(58));
        params.topMargin = top;
        return params;
    }

    private FrameLayout.LayoutParams fill() {
        return new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
