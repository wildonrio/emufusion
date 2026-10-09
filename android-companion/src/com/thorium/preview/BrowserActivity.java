package com.thorium.preview;

import android.app.Activity;
import android.app.ActivityOptions;
import android.app.DownloadManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.util.Log;
import android.view.Display;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.URLUtil;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.net.URI;
import java.net.URLEncoder;
import java.util.concurrent.atomic.AtomicInteger;

/** A small browser that remains inside EmuFusion and routes ordinary web
 * downloads through Android's DownloadManager into the public Downloads
 * directory. It deliberately retains WebView's default TLS validation.
 *
 * On a dual-screen Thor this window belongs on the physical lower display,
 * the same surface the preview player uses: it is a companion window, never
 * a second library. It runs in its own task so it stacks above the resident
 * PreviewActivity instead of replacing it, which keeps EmuFusion — not Android's
 * launcher — in ownership of that display for the whole browsing session. */
public final class BrowserActivity extends Activity {
    public static final String EXTRA_URL = "com.thorium.preview.BROWSER_URL";
    /** Returned by {@link #open} when Android refused the window entirely. */
    static final int LAUNCH_FAILED = Integer.MIN_VALUE;
    private static final String HOME = "https://www.google.com/";
    private static final String PREFS = "lucent_browser";
    private static final String LAST_URL = "last_url";
    private static final String TAG = "LucentBrowser";
    private static final int BAR_COLOR = Color.rgb(11, 14, 20);
    private static final int FIELD_COLOR = Color.rgb(27, 32, 42);
    // 43821 belongs to PreviewService and 43822 to the secondary gameplay
    // router; a distinct request code keeps the three PendingIntents from
    // overwriting one another under FLAG_UPDATE_CURRENT.
    private static final int PENDING_INTENT_REQUEST = 43823;
    /** Downloads handed to Android's DownloadManager during this process.
     * The system service owns every transfer from enqueue onward, so this is
     * evidence for the teardown log, never a handle used to cancel one. */
    private static final AtomicInteger HANDED_OFF_DOWNLOADS = new AtomicInteger();

    private WebView webView;
    private EditText address;
    private TextView progress;

    /** Opens EmuFusion's browser on the display it belongs to and returns that
     * display id, or {@link #LAUNCH_FAILED}. Callable from the service, which
     * is why it carries the same background-activity-start handling as the
     * preview and secondary-gameplay launches. */
    static int open(Context context, String requestedUrl) {
        if (context == null) return LAUNCH_FAILED;
        Intent browser = new Intent(context, BrowserActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                        | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
                .putExtra(EXTRA_URL, requestedUrl == null ? "" : requestedUrl);
        int displayId = targetDisplayId(context);
        boolean overlays = Settings.canDrawOverlays(context);
        try {
            if (displayId < 0) {
                // Single-screen devices — and the dual-screen-gameplay
                // exception — keep the historical primary-display launch.
                context.startActivity(browser);
                Log.i(TAG, "open displayId=" + Display.DEFAULT_DISPLAY +
                        " path=startActivity(default)");
                return Display.DEFAULT_DISPLAY;
            }
            ActivityOptions options = ActivityOptions.makeBasic();
            options.setLaunchDisplayId(displayId);
            if (Build.VERSION.SDK_INT >= 34) {
                options.setPendingIntentCreatorBackgroundActivityStartMode(
                        ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED);
                options.setPendingIntentBackgroundActivityStartMode(
                        ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOWED);
            }
            // The user-granted overlay capability is Android's own exemption
            // for a background service to show a window; without it, a
            // creator-and-sender opted-in PendingIntent is the supported route.
            if (overlays) {
                context.startActivity(browser, options.toBundle());
            } else {
                PendingIntent pending = PendingIntent.getActivity(
                        context, PENDING_INTENT_REQUEST, browser,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE,
                        options.toBundle());
                pending.send(context, 0, null, null, null, null, options.toBundle());
            }
            Log.i(TAG, "open displayId=" + displayId + " path=" +
                    (overlays ? "startActivity(canDrawOverlays)" : "PendingIntent") +
                    " (SDK=" + Build.VERSION.SDK_INT + ")");
            return displayId;
        } catch (PendingIntent.CanceledException | RuntimeException failure) {
            Log.e(TAG, "Unable to open the Lucent browser on display " + displayId, failure);
            return LAUNCH_FAILED;
        }
    }

    /** The lower display whenever the device has one, otherwise -1 for the
     * main display. */
    static int targetDisplayId(Context context) {
        int secondary = context == null ? -1 : BootReceiver.secondaryDisplayId(context);
        if (secondary < 0) {
            Log.i(TAG, "targetDisplayId=main reason=no-secondary-display");
            return -1;
        }
        if (PreviewActivity.isGameplaySurfaceActive()) {
            // A DS/3DS/Wii U session renders its lower screen through
            // PreviewActivity's SurfaceView on that very display. Launching
            // over it would stop that Activity and tear the gameplay Surface
            // down mid-frame, so the browser yields and opens on the main
            // display instead.
            Log.i(TAG, "targetDisplayId=main reason=dual-screen-gameplay-owns-display-"
                    + secondary);
            return -1;
        }
        Log.i(TAG, "targetDisplayId=" + secondary + " reason=secondary-display-present");
        return secondary;
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        // Web audio plays on STREAM_MUSIC, the same stream as previews and
        // gameplay. Keep the hardware keys on it here too, so leaving the
        // browser never returns the user to a differently-adjusted volume.
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        getWindow().setStatusBarColor(BAR_COLOR);
        getWindow().setNavigationBarColor(BAR_COLOR);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.BLACK);

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(10), dp(7), dp(10), dp(7));
        bar.setBackgroundColor(BAR_COLOR);

        bar.addView(button("CLOSE", view -> finish()), buttonParams(dp(78)));
        bar.addView(button("‹", view -> {
            if (webView.canGoBack()) webView.goBack(); else finish();
        }), buttonParams(dp(48)));
        bar.addView(button("›", view -> {
            if (webView.canGoForward()) webView.goForward();
        }), buttonParams(dp(48)));
        bar.addView(button("↻", view -> webView.reload()), buttonParams(dp(48)));

        address = new EditText(this);
        address.setSingleLine(true);
        address.setTextColor(Color.WHITE);
        address.setHintTextColor(Color.rgb(135, 145, 163));
        address.setHint("Search or enter address");
        address.setTextSize(16);
        address.setPadding(dp(14), 0, dp(14), 0);
        address.setBackgroundColor(FIELD_COLOR);
        address.setImeOptions(EditorInfo.IME_ACTION_GO);
        address.setOnEditorActionListener((view, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_GO ||
                    (event != null && event.getKeyCode() == KeyEvent.KEYCODE_ENTER)) {
                navigate(address.getText().toString());
                return true;
            }
            return false;
        });
        LinearLayout.LayoutParams addressParams = new LinearLayout.LayoutParams(
                0, dp(46), 1f);
        addressParams.setMargins(dp(8), 0, dp(8), 0);
        bar.addView(address, addressParams);
        bar.addView(button("GO", view -> navigate(address.getText().toString())),
                buttonParams(dp(54)));

        progress = new TextView(this);
        progress.setTextColor(Color.WHITE);
        progress.setTextSize(12);
        progress.setGravity(Gravity.CENTER);
        progress.setBackgroundColor(Color.rgb(22, 27, 36));
        progress.setVisibility(View.GONE);

        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setSupportMultipleWindows(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);

        webView.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view,
                                                               WebResourceRequest request) {
                return openUrl(request.getUrl());
            }

            @SuppressWarnings("deprecation")
            @Override public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return openUrl(Uri.parse(url));
            }

            @Override public void onPageFinished(WebView view, String url) {
                address.setText(url);
                rememberUrl(url);
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView view, int value) {
                if (value >= 100) {
                    progress.setVisibility(View.GONE);
                } else {
                    progress.setVisibility(View.VISIBLE);
                    progress.setText("LOADING  " + value + "%");
                }
            }

            @Override public void onReceivedTitle(WebView view, String title) {
                if (view.getUrl() != null) address.setText(view.getUrl());
            }
        });
        webView.setDownloadListener(new BrowserDownloadListener());

        root.addView(bar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(60)));
        root.addView(progress, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(22)));
        root.addView(webView, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);

        if (state == null || webView.restoreState(state) == null)
            webView.loadUrl(initialUrl(getIntent()));
        Log.i(TAG, "Browser created on displayId=" +
                (getDisplay() == null ? -1 : getDisplay().getDisplayId()));
    }

    @Override protected void onStart() {
        super.onStart();
        // PreviewService already armed the break when it opened this window.
        // Re-asserting here covers a start it did not initiate — a relaunch
        // after a configuration or display change, or a restored task.
        notifyPreviewService(PreviewService.ACTION_BROWSER_OPENED);
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        String requested = initialUrl(intent);
        if (!HOME.equals(requested)) webView.loadUrl(requested);
    }

    private String initialUrl(Intent intent) {
        String requested = intent == null ? null : intent.getStringExtra(EXTRA_URL);
        if (requested != null && !requested.trim().isEmpty()) return requested.trim();
        return getSharedPreferences(PREFS, MODE_PRIVATE).getString(LAST_URL, HOME);
    }

    private void rememberUrl(String url) {
        if (url == null || url.trim().isEmpty() || "about:blank".equals(url)) return;
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(LAST_URL, url).apply();
    }

    private TextView button(String text, View.OnClickListener action) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(Color.WHITE);
        view.setTextSize(text.length() > 2 ? 12 : 27);
        view.setGravity(Gravity.CENTER);
        view.setBackgroundColor(Color.TRANSPARENT);
        view.setOnClickListener(action);
        view.setFocusable(true);
        return view;
    }

    private LinearLayout.LayoutParams buttonParams(int width) {
        return new LinearLayout.LayoutParams(width, dp(46));
    }

    private void navigate(String requested) {
        String value = requested == null ? "" : requested.trim();
        if (value.isEmpty()) return;
        if (!value.matches("(?i)^[a-z][a-z0-9+.-]*://.*")) {
            if (value.contains(".") && !value.contains(" ")) value = "https://" + value;
            else {
                try {
                    value = "https://www.google.com/search?q=" +
                            URLEncoder.encode(value, "UTF-8");
                } catch (Exception ignored) {
                    value = HOME;
                }
            }
        }
        webView.loadUrl(value);
        address.clearFocus();
    }

    private boolean openUrl(Uri uri) {
        String scheme = uri.getScheme();
        if ("http".equalsIgnoreCase(scheme) || "https".equalsIgnoreCase(scheme))
            return false;
        // Keep EmuFusion's browser in the same package. Downloads are handled by
        // BrowserDownloadListener; arbitrary deep links must not switch into
        // another application or create a second app/task identity.
        Toast.makeText(this, "Only web links and downloads open inside EmuFusion",
                Toast.LENGTH_SHORT).show();
        return true;
    }

    private final class BrowserDownloadListener implements DownloadListener {
        @Override public void onDownloadStart(String url, String userAgent,
                                               String contentDisposition,
                                               String mimeType, long contentLength) {
            try {
                Uri downloadUri = Uri.parse(url);
                String scheme = downloadUri.getScheme();
                if (!"http".equalsIgnoreCase(scheme) && !"https".equalsIgnoreCase(scheme))
                    throw new IllegalArgumentException("Unsupported download scheme: " + scheme);
                String fileName = uniqueDownloadName(
                        sanitizeFileName(URLUtil.guessFileName(url, contentDisposition, mimeType)));
                DownloadManager.Request request = new DownloadManager.Request(downloadUri);
                request.setMimeType(mimeType);
                String effectiveUserAgent = userAgent == null || userAgent.isEmpty() ?
                        webView.getSettings().getUserAgentString() : userAgent;
                request.addRequestHeader("User-Agent", effectiveUserAgent);
                String referer = webView == null ? null : webView.getUrl();
                // DownloadManager replays these headers verbatim across
                // redirects, so a session cookie is only safe to attach while
                // the download stays on the page's own host.
                String cookie = CookieManager.getInstance().getCookie(url);
                if (cookie != null && !cookie.isEmpty() && sameHost(url, referer))
                    request.addRequestHeader("Cookie", cookie);
                if (referer != null && !referer.isEmpty())
                    request.addRequestHeader("Referer", referer);
                request.addRequestHeader("Accept", "*/*");
                request.addRequestHeader("Accept-Language", "en-US,en;q=0.9");
                request.setTitle(fileName);
                request.setDescription("Downloaded from EmuFusion Browser");
                request.setAllowedOverMetered(true);
                request.setAllowedOverRoaming(true);
                request.setNotificationVisibility(
                        DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS,
                        fileName);
                DownloadManager manager = (DownloadManager)
                        getSystemService(Context.DOWNLOAD_SERVICE);
                if (manager == null) throw new IllegalStateException("DownloadManager unavailable");
                // enqueue() transfers ownership to the system's
                // android.providers.downloads process. Nothing in EmuFusion may
                // call manager.remove(id) afterwards: the transfer has to
                // outlive this Activity, this display, and this process.
                long downloadId = manager.enqueue(request);
                HANDED_OFF_DOWNLOADS.incrementAndGet();
                // Download URLs regularly carry signed query tokens; keep them
                // out of the log.
                Log.i(TAG, "Queued background download " + downloadId +
                        " host=" + downloadUri.getHost() + " file=" + fileName);
                Toast.makeText(BrowserActivity.this,
                        "Background download started: " + fileName, Toast.LENGTH_LONG).show();
            } catch (Exception error) {
                Log.e(TAG, "Download could not be started from host "
                        + (url == null ? "?" : Uri.parse(url).getHost()), error);
                Toast.makeText(BrowserActivity.this,
                        "Download failed to start: " + error.getMessage(), Toast.LENGTH_LONG).show();
            }
        }
    }

    private static boolean sameHost(String downloadUrl, String pageUrl) {
        try {
            String downloadHost = new URI(downloadUrl).getHost();
            String pageHost = pageUrl == null ? null : new URI(pageUrl).getHost();
            return downloadHost != null && pageHost != null &&
                    downloadHost.equalsIgnoreCase(pageHost);
        } catch (Exception ignored) {
            return false;
        }
    }

    private String sanitizeFileName(String requestedName) {
        String cleaned = requestedName == null ? "download" :
                requestedName.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_").trim();
        return cleaned.isEmpty() ? "download" : cleaned;
    }

    private String uniqueDownloadName(String requestedName) {
        File directory = Environment.getExternalStoragePublicDirectory(
                Environment.DIRECTORY_DOWNLOADS);
        if (!directory.exists()) directory.mkdirs();
        if (!new File(directory, requestedName).exists()) return requestedName;

        int dot = requestedName.lastIndexOf('.');
        String stem = dot > 0 ? requestedName.substring(0, dot) : requestedName;
        String extension = dot > 0 ? requestedName.substring(dot) : "";
        for (int suffix = 2; suffix < 10000; suffix++) {
            String candidate = stem + " (" + suffix + ")" + extension;
            if (!new File(directory, candidate).exists()) return candidate;
        }
        return System.currentTimeMillis() + "-" + requestedName;
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        // BrowserActivity owns a separate focusable window (and, on a Thor,
        // can own the lower display), so MainActivity's pre-Qt key hook cannot
        // see volume presses delivered here. Route the complete DOWN/UP pair
        // through the same controller: ACTION_DOWN adjusts STREAM_MUSIC once
        // and reconciles every app-owned sink, while ACTION_UP is consumed
        // without a second adjustment.
        if (AppVolumeController.handleKeyEvent(this, event)) return true;
        return super.dispatchKeyEvent(event);
    }

    @Override protected void onPause() {
        if (webView != null) rememberUrl(webView.getUrl());
        super.onPause();
    }

    @Override protected void onSaveInstanceState(Bundle state) {
        if (webView != null) webView.saveState(state);
        super.onSaveInstanceState(state);
    }

    @Override protected void onDestroy() {
        if (webView != null) {
            // stopLoading() only abandons the page this WebView is rendering.
            // Downloads left this Activity at enqueue() time and are owned by
            // the system DownloadManager, so tearing the window down — whether
            // the user pressed CLOSE or Android relaunched us on another
            // display — cannot interrupt one.
            webView.stopLoading();
            webView.setDownloadListener(null);
            webView.destroy();
            webView = null;
        }
        // A configuration- or display-driven relaunch is not a close: onStart
        // re-arms the break, and resuming previews in between would flash the
        // lower display back to a movie for a frame.
        if (!isChangingConfigurations())
            notifyPreviewService(PreviewService.ACTION_BROWSER_CLOSED);
        Log.i(TAG, "Browser destroyed; " + HANDED_OFF_DOWNLOADS.get() +
                " download(s) handed to DownloadManager keep running in the background");
        super.onDestroy();
    }

    private void notifyPreviewService(String action) {
        // A package-scoped broadcast to the already-running service, not
        // startService: onDestroy can run once this process has left the
        // foreground, where a background service start would be refused.
        try {
            sendBroadcast(new Intent(action).setPackage(getPackageName()));
        } catch (RuntimeException error) {
            Log.w(TAG, "Unable to tell the preview service about " + action, error);
        }
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
