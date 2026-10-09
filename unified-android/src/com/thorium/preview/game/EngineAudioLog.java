package com.thorium.preview.game;

import android.content.Context;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.util.Log;

/**
 * One-shot diagnosis of the stream an engine session actually plays on.
 *
 * A silent game is almost never a dead AudioTrack; it is the hardware volume
 * keys having moved a different stream while the one EmuFusion plays on sits at
 * zero. Recording the resolved stream together with its current and maximum
 * level at session start makes that distinguishable from a logcat capture
 * alone, without asking the user to reproduce anything.
 */
final class EngineAudioLog {
    /** Marker grepped by runtime acceptance and by future desync reports. */
    static final String MARKER = "audio-stream";

    private EngineAudioLog() {}

    static void logResolvedStream(Context context, String tag, String engineId,
            AudioTrack track) {
        if (track == null) return;
        int stream;
        try {
            stream = track.getStreamType();
        } catch (Throwable unavailable) {
            return;
        }
        int volume = -1;
        int maxVolume = -1;
        Object service = context == null ? null
                : context.getSystemService(Context.AUDIO_SERVICE);
        if (service instanceof AudioManager) {
            AudioManager manager = (AudioManager) service;
            try {
                volume = manager.getStreamVolume(stream);
                maxVolume = manager.getStreamMaxVolume(stream);
            } catch (Throwable ignored) {
                // A vendor AudioManager that refuses to report a level must
                // never keep the session from starting.
            }
        }
        Log.i(tag, "Audio stream resolved engine=" + engineId +
                " stream=" + stream +
                " expectedMusicStream=" + AudioManager.STREAM_MUSIC +
                " volume=" + volume + "/" + maxVolume +
                " marker=" + MARKER);
    }
}
