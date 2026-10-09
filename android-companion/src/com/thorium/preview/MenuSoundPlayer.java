package com.thorium.preview;

import android.content.Context;
import android.content.SharedPreferences;
import android.media.AudioAttributes;
import android.media.SoundPool;
import android.os.SystemClock;
import android.util.Log;
import android.view.KeyEvent;

import java.util.EnumMap;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;

/**
 * EmuFusion's menu blips: four very short, quiet cues for library navigation.
 *
 * SoundPool rather than MediaPlayer because these have to fire on the same key
 * press the user is making, and it keeps the decoded samples resident instead
 * of re-preparing a decoder each time.
 *
 * The attributes are USAGE_MEDIA, which resolves to STREAM_MUSIC: the same
 * stream the engines' AudioTracks and the preview MediaPlayer use, and the one
 * LucentApplication binds the hardware volume keys to. Nothing here may
 * introduce a second stream, or the volume keys would once again control only
 * part of what the user can hear.
 *
 * Gameplay exclusion is the caller's job and is deliberately not a flag in this
 * class: InWindowGameHost only reaches these cues when no session is active, so
 * a running game can never be talked over by launcher sounds.
 */
public final class MenuSoundPlayer {
    public enum Cue { MOVE, CONFIRM, BACK, ERROR }

    public static final String PREFS = "preview";
    public static final String PREF_ENABLED = "lucent_sfx_enabled";
    /** Sound Effects ships on; the setting exists to turn it off. */
    public static final boolean DEFAULT_ENABLED = true;

    private static final String TAG = "LucentMenuSfx";
    // One cue per ~45 ms. Held D-pad repeats stay audible as distinct ticks
    // while a burst of simultaneous events cannot pile into a chord.
    private static final long MIN_INTERVAL_MILLIS = 45L;
    // A cue requested while its sample is still decoding is worth honouring
    // for about this long; beyond it the press is stale and silence is right.
    private static final long PENDING_CUE_MILLIS = 400L;
    private static final int MAX_STREAMS = 3;
    private static final int RECENT_STREAM_LIMIT = 16;

    private static final Object LOCK = new Object();
    private static SoundPool pool;
    private static final Map<Cue, Integer> SAMPLE_IDS = new EnumMap<>(Cue.class);
    private static final Map<Cue, Boolean> SAMPLE_READY = new EnumMap<>(Cue.class);
    // SoundPool has no playback-complete callback. Keep a small bounded set of
    // recent stream IDs: setVolume is harmless after a stream has completed,
    // while retaining the IDs guarantees that a cue already in flight is
    // silenced on the same quick volume tap as every AudioTrack/MediaPlayer.
    private static final Deque<Integer> RECENT_STREAM_IDS = new ArrayDeque<>();
    private static final AppVolumeController.Listener VOLUME_LISTENER =
            MenuSoundPlayer::applyActiveStreamGain;
    private static boolean volumeListenerRegistered;
    private static Cue pendingCue;
    private static long pendingCueAtMillis;
    private static long lastPlayedAtMillis;
    private static Boolean enabledCache;

    private MenuSoundPlayer() {}

    /** Resource basename in res/raw, which build.sh copies from this module. */
    static String assetName(Cue cue) {
        return "lucent_sfx_" + cue.name().toLowerCase(java.util.Locale.US);
    }

    /** Maps a control-plane name onto a cue, or null when it is not one. */
    public static Cue cueByName(String name) {
        if (name == null) return null;
        String value = name.trim().toLowerCase(java.util.Locale.US);
        if ("move".equals(value)) return Cue.MOVE;
        if ("confirm".equals(value)) return Cue.CONFIRM;
        if ("back".equals(value)) return Cue.BACK;
        if ("error".equals(value)) return Cue.ERROR;
        return null;
    }

    /**
     * Maps a hardware key onto a navigation cue, or null when the key is not
     * navigation. The denial blip has no key: nothing the user presses is
     * itself an error, so it is raised by whatever refuses the action.
     */
    public static Cue cueForKey(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_UP:
            case KeyEvent.KEYCODE_DPAD_DOWN:
            case KeyEvent.KEYCODE_DPAD_LEFT:
            case KeyEvent.KEYCODE_DPAD_RIGHT:
            case KeyEvent.KEYCODE_BUTTON_L1:
            case KeyEvent.KEYCODE_BUTTON_R1:
                return Cue.MOVE;
            case KeyEvent.KEYCODE_BUTTON_A:
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_NUMPAD_ENTER:
                return Cue.CONFIRM;
            case KeyEvent.KEYCODE_BUTTON_B:
            case KeyEvent.KEYCODE_BACK:
            case KeyEvent.KEYCODE_ESCAPE:
                return Cue.BACK;
            default:
                return null;
        }
    }

    public static boolean isEnabled(Context context) {
        Boolean cached = enabledCache;
        if (cached != null) return cached;
        if (context == null) return DEFAULT_ENABLED;
        boolean enabled = context.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getBoolean(PREF_ENABLED, DEFAULT_ENABLED);
        enabledCache = enabled;
        return enabled;
    }

    public static void setEnabled(Context context, boolean enabled) {
        enabledCache = enabled;
        if (context == null) return;
        SharedPreferences preferences = context.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        preferences.edit().putBoolean(PREF_ENABLED, enabled).apply();
        if (enabled) warmUp(context);
        else release();
    }

    /** Plays a cue for a key press, or does nothing when it is not navigation. */
    public static void playForKey(Context context, KeyEvent event) {
        if (event == null || event.getAction() != KeyEvent.ACTION_DOWN) return;
        Cue cue = cueForKey(event.getKeyCode());
        if (cue != null) play(context, cue);
    }

    public static void play(Context context, Cue cue) {
        if (cue == null || context == null || !isEnabled(context)) return;
        long now = SystemClock.elapsedRealtime();
        synchronized (LOCK) {
            if (now - lastPlayedAtMillis < MIN_INTERVAL_MILLIS) return;
            if (pool == null && !openPool(context)) return;
            Integer sampleId = SAMPLE_IDS.get(cue);
            if (sampleId == null) return;
            if (!Boolean.TRUE.equals(SAMPLE_READY.get(cue))) {
                // First press of a cold process: honour it once the decoder
                // catches up rather than swallowing the very first sound.
                pendingCue = cue;
                pendingCueAtMillis = now;
                return;
            }
            lastPlayedAtMillis = now;
            float gain = AppVolumeController.gain(context);
            playLocked(pool, sampleId, gain);
        }
    }

    /** Decodes the samples ahead of the first press. Safe to call repeatedly. */
    public static void warmUp(Context context) {
        if (context == null || !isEnabled(context)) return;
        synchronized (LOCK) {
            if (pool == null) openPool(context);
        }
    }

    public static void release() {
        synchronized (LOCK) {
            if (pool != null) pool.release();
            pool = null;
            SAMPLE_IDS.clear();
            SAMPLE_READY.clear();
            RECENT_STREAM_IDS.clear();
            pendingCue = null;
        }
    }

    private static boolean openPool(Context context) {
        Context app = context.getApplicationContext();
        SoundPool created;
        try {
            created = new SoundPool.Builder()
                    .setMaxStreams(MAX_STREAMS)
                    .setAudioAttributes(new AudioAttributes.Builder()
                            // USAGE_MEDIA is what puts these on STREAM_MUSIC.
                            .setUsage(AudioAttributes.USAGE_MEDIA)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                            .build())
                    .build();
        } catch (Throwable unavailable) {
            Log.w(TAG, "Menu sounds unavailable on this device", unavailable);
            return false;
        }
        created.setOnLoadCompleteListener((soundPool, sampleId, status) -> {
            synchronized (LOCK) {
                if (soundPool != pool || status != 0) return;
                Cue loaded = null;
                for (Map.Entry<Cue, Integer> entry : SAMPLE_IDS.entrySet())
                    if (entry.getValue() == sampleId) loaded = entry.getKey();
                if (loaded == null) return;
                SAMPLE_READY.put(loaded, Boolean.TRUE);
                long now = SystemClock.elapsedRealtime();
                if (pendingCue == loaded &&
                        now - pendingCueAtMillis <= PENDING_CUE_MILLIS) {
                    pendingCue = null;
                    lastPlayedAtMillis = now;
                    float gain = AppVolumeController.gain(app);
                    playLocked(soundPool, sampleId, gain);
                }
            }
        });
        int loadedCount = 0;
        for (Cue cue : Cue.values()) {
            int resource = app.getResources().getIdentifier(
                    assetName(cue), "raw", app.getPackageName());
            if (resource == 0) continue;
            int sampleId = created.load(app, resource, 1);
            if (sampleId == 0) continue;
            SAMPLE_IDS.put(cue, sampleId);
            SAMPLE_READY.put(cue, Boolean.FALSE);
            loadedCount++;
        }
        if (loadedCount == 0) {
            Log.w(TAG, "No menu sound assets are packaged in this build");
            created.release();
            return false;
        }
        pool = created;
        if (!volumeListenerRegistered) {
            // The listener is a process-lifetime singleton and captures no
            // Context, so keeping it registered cannot leak an Activity.
            volumeListenerRegistered = true;
            AppVolumeController.registerListener(app, VOLUME_LISTENER);
        }
        return true;
    }

    private static void playLocked(SoundPool soundPool, int sampleId, float gain) {
        int streamId = soundPool.play(sampleId, gain, gain, 1, 0, 1.0f);
        if (streamId == 0) return;
        RECENT_STREAM_IDS.addLast(streamId);
        while (RECENT_STREAM_IDS.size() > RECENT_STREAM_LIMIT)
            RECENT_STREAM_IDS.removeFirst();
        Log.i(TAG, "SoundPool sink started stream=" + streamId + " gain=" + gain);
    }

    private static void applyActiveStreamGain(float gain) {
        synchronized (LOCK) {
            SoundPool soundPool = pool;
            if (soundPool == null) return;
            for (Integer streamId : RECENT_STREAM_IDS) {
                if (streamId != null && streamId != 0) {
                    soundPool.setVolume(streamId, gain, gain);
                    Log.i(TAG, "SoundPool sink gain stream=" + streamId +
                            " gain=" + gain);
                }
            }
            Log.i(TAG, "SoundPool active sinks gain=" + gain +
                    " trackedStreams=" + RECENT_STREAM_IDS.size());
        }
    }
}
