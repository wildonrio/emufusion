package com.thorium.preview;

import android.content.Context;
import android.media.AudioManager;
import android.media.AudioDeviceInfo;
import android.media.AudioTrack;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.KeyEvent;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.WeakHashMap;

/**
 * Makes the Android STREAM_MUSIC index authoritative for every EmuFusion sink.
 *
 * <p>The AYN Thor firmware updates the visible stream index for a quick rocker
 * tap but can leave a newly-created game/preview track at unity mixer gain for
 * minutes. Holding the rocker appears to work only because repeated platform
 * events eventually refresh that route. We therefore consume each physical
 * down/up pair before Qt, adjust STREAM_MUSIC exactly once on ACTION_DOWN, and
 * mirror the platform volume curve into EmuFusion's own active sinks on this
 * affected device. Other Android devices retain normal platform-only gain.
 */
public final class AppVolumeController {
    public interface Listener { void onAppVolumeChanged(float gain); }

    private static final String TAG = "EmuFusionVolume";
    private static final Object LOCK = new Object();
    private static final WeakHashMap<AudioTrack, Boolean> TRACKS = new WeakHashMap<>();
    private static final List<WeakReference<Listener>> LISTENERS = new ArrayList<>();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private AppVolumeController() {}

    /** Handles both a tap and every long-press repeat; ACTION_UP is consumed. */
    public static boolean handleKeyEvent(Context context, KeyEvent event) {
        if (context == null || event == null || !isVolumeKey(event.getKeyCode())) return false;
        if (event.getAction() == KeyEvent.ACTION_DOWN) {
            AudioManager manager = manager(context);
            if (manager != null) {
                int direction = event.getKeyCode() == KeyEvent.KEYCODE_VOLUME_UP
                        ? AudioManager.ADJUST_RAISE
                        : event.getKeyCode() == KeyEvent.KEYCODE_VOLUME_DOWN
                        ? AudioManager.ADJUST_LOWER : AudioManager.ADJUST_TOGGLE_MUTE;
                manager.adjustStreamVolume(AudioManager.STREAM_MUSIC, direction,
                        AudioManager.FLAG_SHOW_UI);
                apply(context);
                // Vendor AudioService publishes the new curve asynchronously.
                MAIN.postDelayed(() -> apply(context.getApplicationContext()), 32L);
            }
        }
        return true;
    }

    public static void registerTrack(Context context, AudioTrack track) {
        if (track == null) return;
        synchronized (LOCK) { TRACKS.put(track, Boolean.TRUE); }
        setTrackGain(track, gain(context));
    }

    public static void unregisterTrack(AudioTrack track) {
        if (track == null) return;
        synchronized (LOCK) { TRACKS.remove(track); }
    }

    public static void registerListener(Context context, Listener listener) {
        if (listener == null) return;
        synchronized (LOCK) {
            pruneListeners();
            LISTENERS.add(new WeakReference<>(listener));
        }
        listener.onAppVolumeChanged(gain(context));
    }

    public static void unregisterListener(Listener listener) {
        synchronized (LOCK) {
            Iterator<WeakReference<Listener>> iterator = LISTENERS.iterator();
            while (iterator.hasNext()) {
                Listener value = iterator.next().get();
                if (value == null || value == listener) iterator.remove();
            }
        }
    }

    /** Local gain is only needed on the proven vendor mixer defect. */
    public static float gain(Context context) {
        if (!needsLocalGain()) return 1f;
        AudioManager manager = manager(context);
        if (manager == null) return 1f;
        int minimum = Build.VERSION.SDK_INT >= 28
                ? manager.getStreamMinVolume(AudioManager.STREAM_MUSIC) : 0;
        int current = manager.getStreamVolume(AudioManager.STREAM_MUSIC);
        if (manager.isStreamMute(AudioManager.STREAM_MUSIC) || current <= minimum) return 0f;
        int maximum = Math.max(minimum + 1,
                manager.getStreamMaxVolume(AudioManager.STREAM_MUSIC));
        if (Build.VERSION.SDK_INT >= 28) {
            float db = manager.getStreamVolumeDb(AudioManager.STREAM_MUSIC, current,
                    outputDeviceType(manager));
            if (Float.isFinite(db)) return clamp((float) Math.pow(10.0, db / 20.0));
        }
        return clamp((current - minimum) / (float) (maximum - minimum));
    }

    public static void apply(Context context) {
        float value = gain(context);
        List<AudioTrack> tracks;
        List<Listener> listeners = new ArrayList<>();
        synchronized (LOCK) {
            tracks = new ArrayList<>(TRACKS.keySet());
            Iterator<WeakReference<Listener>> iterator = LISTENERS.iterator();
            while (iterator.hasNext()) {
                Listener listener = iterator.next().get();
                if (listener == null) iterator.remove();
                else listeners.add(listener);
            }
        }
        // Never call an Android audio object or an application listener while
        // holding LOCK. MenuSoundPlayer and PreviewActivity each protect their
        // own sink collections; calling them under the controller monitor
        // creates an AppVolumeController -> sink lock order that can deadlock
        // against first-use registration's sink -> AppVolumeController order.
        for (AudioTrack track : tracks)
            if (track != null) setTrackGain(track, value);
        for (Listener listener : listeners)
            listener.onAppVolumeChanged(value);
        Log.i(TAG, "Applied STREAM_MUSIC gain index=" + streamIndex(context) +
                " gain=" + value + " localFallback=" + needsLocalGain());
    }

    private static boolean isVolumeKey(int keyCode) {
        return keyCode == KeyEvent.KEYCODE_VOLUME_UP ||
                keyCode == KeyEvent.KEYCODE_VOLUME_DOWN ||
                keyCode == KeyEvent.KEYCODE_VOLUME_MUTE;
    }

    private static AudioManager manager(Context context) {
        Object service = context.getSystemService(Context.AUDIO_SERVICE);
        return service instanceof AudioManager ? (AudioManager) service : null;
    }

    private static int streamIndex(Context context) {
        AudioManager value = manager(context);
        return value == null ? -1 : value.getStreamVolume(AudioManager.STREAM_MUSIC);
    }

    private static int outputDeviceType(AudioManager manager) {
        try {
            AudioDeviceInfo[] devices = manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS);
            for (AudioDeviceInfo device : devices)
                if (device != null && device.isSink()) return device.getType();
        } catch (RuntimeException ignored) {}
        return AudioDeviceInfo.TYPE_BUILTIN_SPEAKER;
    }

    private static boolean needsLocalGain() {
        return "AYN".equalsIgnoreCase(Build.MANUFACTURER) ||
                (Build.MODEL != null && Build.MODEL.toLowerCase().contains("ayn thor"));
    }

    private static void setTrackGain(AudioTrack track, float gain) {
        try { track.setVolume(gain); }
        catch (IllegalStateException ignored) {}
    }

    private static void pruneListeners() {
        Iterator<WeakReference<Listener>> iterator = LISTENERS.iterator();
        while (iterator.hasNext()) if (iterator.next().get() == null) iterator.remove();
    }

    private static float clamp(float value) {
        return Math.max(0f, Math.min(1f, value));
    }
}
