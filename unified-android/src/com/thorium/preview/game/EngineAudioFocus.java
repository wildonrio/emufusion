package com.thorium.preview.game;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

/**
 * The audio focus an in-process game session holds while it makes sound.
 *
 * <p>EmuFusion requested none until now. That is a correctness bug on its own
 * terms: a game that never asks for focus plays straight over a call, a
 * navigation prompt or another app's music, and is never told to stop. It is
 * also the last structural difference between an EmuFusion track and the stock
 * video player's track, whose STREAM_MUSIC attenuation works correctly on the
 * same output thread and the same speaker while EmuFusion's mixer gain stays
 * pinned. See the engine sessions for the full list of ruled-out causes.
 *
 * <p>Focus is session-scoped: taken when a game starts playing and given back
 * on every teardown path, including the failure ones. An app that keeps focus
 * after its game is gone leaves every other app ducked or silent.
 */
final class EngineAudioFocus {
    /** Marker grepped by runtime acceptance and by future audio reports. */
    static final String MARKER = "audio-focus";

    /** What a session must do when the platform moves focus away and back. */
    interface Listener {
        /** Stop producing sound: something else owns the output now. */
        void onAudioFocusSuppressed();

        /** Focus is back; sound may resume. */
        void onAudioFocusRestored();
    }

    /**
     * The attributes the request carries.
     *
     * <p>Must stay identical to the attributes every engine AudioTrack is
     * built with, or the platform is being asked about a different kind of
     * playback than the one that actually happens. The sessions state theirs
     * inline so the track construction reads on its own; this is the one place
     * that has to be kept in step with them.
     */
    static AudioAttributes gameAttributes() {
        return new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_GAME)
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                .build();
    }

    private final Context appContext;
    private final String tag;
    private final String engineId;
    private final Listener listener;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AudioManager.OnAudioFocusChangeListener changes = this::onFocusChange;
    private final Object lock = new Object();
    /** The granted AudioFocusRequest on API 26+, null below it. */
    private Object granted;
    private boolean held;
    private volatile boolean suppressed;

    EngineAudioFocus(Context context, String tag, String engineId, Listener listener) {
        this.appContext = context == null ? null : context.getApplicationContext();
        this.tag = tag;
        this.engineId = engineId == null ? "" : engineId;
        this.listener = listener;
    }

    /**
     * True while the session must stay silent because another app holds focus.
     *
     * <p>Read on the audio-producing thread, so the session drops the PCM it
     * has already drained rather than queueing it behind a paused track: a
     * backed-up track buffer stalls the engine, and a backed-up guest audio
     * queue freezes the guest outright.
     */
    boolean isSuppressed() {
        return suppressed;
    }

    /**
     * Asks for focus for as long as the game runs. Idempotent, so resume can
     * call it to re-acquire focus after a permanent loss.
     *
     * @return true when the platform granted it
     */
    boolean request() {
        AudioManager manager = manager();
        if (manager == null) return false;
        boolean acquired;
        synchronized (lock) {
            if (held) return true;
            int result;
            if (Build.VERSION.SDK_INT >= 26) {
                AudioFocusRequest built = new AudioFocusRequest.Builder(
                        AudioManager.AUDIOFOCUS_GAIN)
                        .setAudioAttributes(gameAttributes())
                        .setOnAudioFocusChangeListener(changes, main)
                        // The platform ducks this track itself for a short
                        // interruption. EmuFusion must never attenuate its own
                        // output -- the system level is the single authority --
                        // so letting the platform duck is the only correct
                        // answer here, not a convenience.
                        .setWillPauseWhenDucked(false)
                        .setAcceptsDelayedFocusGain(false)
                        .build();
                result = manager.requestAudioFocus(built);
                if (result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED) granted = built;
            } else {
                result = manager.requestAudioFocus(changes,
                        AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN);
            }
            held = result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
            acquired = held;
            // A refusal is not a loss. EmuFusion has always played without
            // focus, so a refused request keeps that behaviour rather than
            // silencing a game the user launched deliberately; only a focus
            // change the platform actually reports suppresses output.
            if (held) suppressed = false;
        }
        Log.i(tag, "Audio focus " + (acquired ? "granted" : "refused") +
                " engine=" + engineId + " marker=" + MARKER);
        return acquired;
    }

    /**
     * Gives focus back. Safe to call more than once and from any teardown
     * path, including one already unwinding a failure.
     */
    void abandon() {
        AudioManager manager = manager();
        boolean released;
        synchronized (lock) {
            Object pending = granted;
            granted = null;
            released = held;
            held = false;
            suppressed = false;
            if (manager == null || (!released && pending == null)) return;
            try {
                if (Build.VERSION.SDK_INT >= 26 && pending instanceof AudioFocusRequest)
                    manager.abandonAudioFocusRequest((AudioFocusRequest) pending);
                else manager.abandonAudioFocus(changes);
            } catch (Throwable ignored) {
                // Teardown must complete even if a vendor AudioManager throws;
                // the process is losing the request either way.
            }
        }
        Log.i(tag, "Audio focus abandoned engine=" + engineId + " marker=" + MARKER);
    }

    private void onFocusChange(int change) {
        boolean silence;
        switch (change) {
            case AudioManager.AUDIOFOCUS_GAIN:
                synchronized (lock) {
                    held = true;
                    suppressed = false;
                }
                silence = false;
                break;
            case AudioManager.AUDIOFOCUS_LOSS:
                // Permanent. The platform has already taken the request away,
                // so there is nothing left to abandon, and asking for it back
                // would be talking over whatever replaced us. Stay silent
                // until the player returns to the game, which re-requests.
                synchronized (lock) {
                    held = false;
                    granted = null;
                    suppressed = true;
                }
                silence = true;
                break;
            case AudioManager.AUDIOFOCUS_LOSS_TRANSIENT:
                synchronized (lock) { suppressed = true; }
                silence = true;
                break;
            case AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK:
                // setWillPauseWhenDucked(false) asked the platform to duck this
                // track for us. Doing it here as well would be app-side gain.
                return;
            default:
                return;
        }
        Log.i(tag, "Audio focus change=" + change + " engine=" + engineId +
                " silenced=" + silence + " marker=" + MARKER);
        Listener callback = listener;
        if (callback == null) return;
        if (silence) callback.onAudioFocusSuppressed();
        else callback.onAudioFocusRestored();
    }

    private AudioManager manager() {
        Object service = appContext == null ? null
                : appContext.getSystemService(Context.AUDIO_SERVICE);
        return service instanceof AudioManager ? (AudioManager) service : null;
    }
}
