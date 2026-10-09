package com.thorium.preview;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.app.ActivityManager;
import android.os.Build;

import org.json.JSONObject;

import java.net.URLEncoder;
import java.util.List;

/** Process-local, user-reviewed voice-feedback draft.
 *
 * Raw microphone audio is owned by Android's SpeechRecognizer and is never
 * written by EmuFusion. Only recognized text enters this object. GitHub
 * credentials are likewise never stored here: Send opens GitHub's own
 * authenticated issue composer with a bounded, prefilled draft.
 */
final class VoiceFeedbackManager {
    static final String REPOSITORY = "wildonrio/pegasus-lucent";
    private static final int MAX_TRANSCRIPT = 4_000;
    private static final Object LOCK = new Object();

    private static String state = "idle";
    private static String transcript = "";
    private static String message = "Tap the raised-hand icon to record feedback.";
    private static String systemContext = "";
    private static boolean githubComposerOpened;

    private VoiceFeedbackManager() {}

    static void begin(String title, String system, String page) {
        synchronized (LOCK) {
            state = "requesting-permission";
            transcript = "";
            message = "Waiting for microphone permission…";
            // Do not retain the selected game, screen, or capture timestamp.
            systemContext = FeedbackDiagnostics.systemCode(system);
            githubComposerOpened = false;
        }
    }

    static void listening() {
        synchronized (LOCK) {
            state = "listening";
            message = "Listening… Speak naturally, then pause when finished.";
        }
    }

    static void partial(String text) {
        synchronized (LOCK) {
            if (!"listening".equals(state)) return;
            transcript = bounded(text, MAX_TRANSCRIPT);
        }
    }

    static void complete(String text) {
        synchronized (LOCK) {
            transcript = bounded(text, MAX_TRANSCRIPT);
            if (transcript.trim().isEmpty()) {
                state = "error";
                message = "No speech was recognized. Tap Redo and try again.";
            } else {
                state = "ready";
                message = "Review the transcription before sending.";
            }
        }
    }

    /** Replaces recognition output with the exact text reviewed in the UI. */
    static void replaceTranscript(String text) {
        synchronized (LOCK) {
            transcript = bounded(text, MAX_TRANSCRIPT);
            if (transcript.trim().isEmpty()) {
                state = "error";
                message = "Enter or record feedback before sending.";
            } else {
                state = "ready";
                message = "Review the edited transcription before sending.";
            }
        }
    }

    static void error(String explanation) {
        synchronized (LOCK) {
            state = "error";
            message = bounded(explanation, 240);
        }
    }

    static void cancelled() {
        synchronized (LOCK) {
            state = "idle";
            transcript = "";
            message = "Recording cancelled.";
        }
    }

    static boolean ready() {
        synchronized (LOCK) {
            return "ready".equals(state) || "github-review".equals(state);
        }
    }

    static boolean appIsVisible(Context context) {
        ActivityManager manager = (ActivityManager)context.getSystemService(
                Context.ACTIVITY_SERVICE);
        if (manager == null) return false;
        List<ActivityManager.RunningAppProcessInfo> processes =
                manager.getRunningAppProcesses();
        if (processes == null) return false;
        for (ActivityManager.RunningAppProcessInfo process : processes) {
            if (context.getPackageName().equals(process.processName) &&
                    process.importance <= ActivityManager.RunningAppProcessInfo.IMPORTANCE_VISIBLE)
                return true;
        }
        return false;
    }

    static JSONObject status() throws Exception {
        synchronized (LOCK) {
            return new JSONObject()
                    .put("state", state)
                    .put("transcript", transcript)
                    .put("message", message)
                    .put("githubComposerOpened", githubComposerOpened)
                    .put("repository", REPOSITORY)
                    .put("audioStored", false)
                    .put("diagnostics", "App version and emulated system only; no device details or logs")
                    .put("anonymous", false);
        }
    }

    static JSONObject openGithubComposer(Context context) throws Exception {
        if (!appIsVisible(context)) {
            return status().put("ok", false)
                    .put("error", "EmuFusion must be visible to send feedback");
        }
        final String issueUrl;
        synchronized (LOCK) {
            if (!ready() || transcript.trim().isEmpty()) {
                return status().put("ok", false)
                        .put("error", "A reviewed transcription is required");
            }
            issueUrl = issueUrl(context, transcript, systemContext);
        }
        int displayId = BrowserActivity.open(context, issueUrl);
        synchronized (LOCK) {
            if (displayId == BrowserActivity.LAUNCH_FAILED) {
                state = "error";
                message = "GitHub could not be opened. The transcription is still available.";
                return status().put("ok", false).put("error", message);
            }
            state = "github-review";
            githubComposerOpened = true;
            message = "GitHub opened on display " + displayId +
                    ". Sign in if needed, review the issue, then confirm Create.";
            return status().put("ok", true).put("displayId", displayId)
                    .put("requiresGithubConfirmation", true);
        }
    }

    static String issueUrl(Context context, String recognizedText, String system) throws Exception {
        String issueTitle = "[Device feedback] " + firstMeaningfulLine(recognizedText);
        StringBuilder body = new StringBuilder();
        body.append("## Voice feedback\n\n")
                .append(bounded(recognizedText, MAX_TRANSCRIPT).trim())
                .append("\n\n## Automatic diagnostics\n\n")
                .append(environment(context, system))
                .append("\n_No device details, timestamps, game names, paths, or raw logs are attached. " +
                        "The reviewed text above is user-supplied. GitHub issues are not anonymous " +
                        "and are associated with the submitting GitHub account._\n");
        return "https://github.com/" + REPOSITORY + "/issues/new?title=" +
                encode(bounded(issueTitle, 120)) + "&body=" + encode(body.toString());
    }

    private static String environment(Context context, String system) {
        String version = "unknown";
        long code = -1L;
        try {
            PackageInfo info = context.getPackageManager()
                    .getPackageInfo(context.getPackageName(), 0);
            version = info.versionName == null ? "unknown" : info.versionName;
            code = Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
        } catch (Exception ignored) {}
        return FeedbackDiagnostics.markdown(version, code, system);
    }

    private static String firstMeaningfulLine(String value) {
        String normalized = value == null ? "" : value.replace('\n', ' ').trim();
        if (normalized.isEmpty()) return "Voice feedback";
        return bounded(normalized, 88);
    }

    private static String bounded(String value, int maximum) {
        if (value == null) return "";
        String clean = value.replace('\u0000', ' ');
        return clean.length() <= maximum ? clean : clean.substring(0, maximum) + "…";
    }

    private static String encode(String value) throws Exception {
        return URLEncoder.encode(value, "UTF-8").replace("+", "%20");
    }

}
