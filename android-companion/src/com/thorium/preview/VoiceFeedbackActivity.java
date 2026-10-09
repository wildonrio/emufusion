package com.thorium.preview;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;

import java.lang.ref.WeakReference;
import java.util.ArrayList;

/** Transparent permission and SpeechRecognizer owner for the QML feedback UI. */
public final class VoiceFeedbackActivity extends Activity implements RecognitionListener {
    private static final int MICROPHONE_REQUEST = 614;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static WeakReference<VoiceFeedbackActivity> active = new WeakReference<>(null);

    private SpeechRecognizer recognizer;
    private boolean onDeviceRecognizer;
    private boolean finished;
    private final Runnable timeout = () -> finishWithError(
            "Voice recording timed out. Tap Redo to try again.");

    static boolean open(Context context) {
        if (!VoiceFeedbackManager.appIsVisible(context)) {
            VoiceFeedbackManager.error("EmuFusion must be visible to start recording.");
            return false;
        }
        try {
            context.startActivity(new Intent(context, VoiceFeedbackActivity.class)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            return true;
        } catch (RuntimeException failure) {
            VoiceFeedbackManager.error("Android could not open voice recording.");
            return false;
        }
    }

    static void cancelActive() {
        VoiceFeedbackActivity activity = active.get();
        if (activity != null) MAIN.post(activity::cancelAndFinish);
        else VoiceFeedbackManager.cancelled();
    }

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        active = new WeakReference<>(this);
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED) {
            beginRecognition();
        } else {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},
                    MICROPHONE_REQUEST);
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode,
                                                     String[] permissions,
                                                     int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != MICROPHONE_REQUEST) return;
        if (grantResults.length > 0 &&
                grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            beginRecognition();
        } else {
            finishWithError("Microphone permission is required to record voice feedback.");
        }
    }

    private void beginRecognition() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            finishWithError("No Android speech-recognition service is available.");
            return;
        }
        try {
            onDeviceRecognizer = android.os.Build.VERSION.SDK_INT >= 31 &&
                    SpeechRecognizer.isOnDeviceRecognitionAvailable(this);
            recognizer = onDeviceRecognizer ?
                    SpeechRecognizer.createOnDeviceSpeechRecognizer(this) :
                    SpeechRecognizer.createSpeechRecognizer(this);
            recognizer.setRecognitionListener(this);
            Intent request = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                            RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                    .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
                    .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
                    .putExtra(RecognizerIntent.EXTRA_PROMPT, "Describe the bug or feature request");
            VoiceFeedbackManager.listening();
            MAIN.postDelayed(timeout, 45_000L);
            recognizer.startListening(request);
        } catch (RuntimeException failure) {
            finishWithError("Speech recognition could not start. Tap Redo to try again.");
        }
    }

    @Override public void onPartialResults(Bundle partialResults) {
        String text = firstResult(partialResults);
        if (!text.isEmpty()) VoiceFeedbackManager.partial(text);
    }

    @Override public void onResults(Bundle results) {
        String text = firstResult(results);
        finished = true;
        MAIN.removeCallbacks(timeout);
        VoiceFeedbackManager.complete(text);
        finish();
    }

    @Override public void onError(int error) {
        String message;
        switch (error) {
            case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS:
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) ==
                        PackageManager.PERMISSION_GRANTED) {
                    message = "Android's built-in transcription rejected microphone " +
                            "access. Check microphone permission, then tap Redo.";
                } else {
                    message = "Microphone permission is required to record voice feedback.";
                }
                break;
            case SpeechRecognizer.ERROR_NETWORK:
            case SpeechRecognizer.ERROR_NETWORK_TIMEOUT:
                message = "Speech recognition could not reach its service. Check the network and tap Redo.";
                break;
            case SpeechRecognizer.ERROR_NO_MATCH:
            case SpeechRecognizer.ERROR_SPEECH_TIMEOUT:
                message = "No speech was recognized. Tap Redo and try again.";
                break;
            default:
                message = "Speech recognition stopped (error " + error + "). Tap Redo to try again.";
        }
        finishWithError(message);
    }

    private static String firstResult(Bundle results) {
        if (results == null) return "";
        ArrayList<String> values = results.getStringArrayList(
                SpeechRecognizer.RESULTS_RECOGNITION);
        return values == null || values.isEmpty() || values.get(0) == null ?
                "" : values.get(0);
    }

    private void finishWithError(String message) {
        if (finished) return;
        finished = true;
        MAIN.removeCallbacks(timeout);
        VoiceFeedbackManager.error(message);
        finish();
    }

    private void cancelAndFinish() {
        if (finished) return;
        finished = true;
        MAIN.removeCallbacks(timeout);
        VoiceFeedbackManager.cancelled();
        if (recognizer != null) {
            try { recognizer.cancel(); } catch (RuntimeException ignored) {}
        }
        finish();
    }

    @Override protected void onDestroy() {
        MAIN.removeCallbacks(timeout);
        if (recognizer != null) {
            try { recognizer.destroy(); } catch (RuntimeException ignored) {}
            recognizer = null;
        }
        if (active.get() == this) active.clear();
        super.onDestroy();
    }

    @Override public void onReadyForSpeech(Bundle params) {}
    @Override public void onBeginningOfSpeech() {}
    @Override public void onRmsChanged(float rmsdB) {}
    @Override public void onBufferReceived(byte[] buffer) {}
    @Override public void onEndOfSpeech() {}
    @Override public void onEvent(int eventType, Bundle params) {}
}
