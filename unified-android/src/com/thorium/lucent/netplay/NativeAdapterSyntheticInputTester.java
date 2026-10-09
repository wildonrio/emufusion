package com.thorium.lucent.netplay;

import android.content.Context;
import android.os.Environment;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;

import java.io.File;

/**
 * The Phase 3 native-adapter (Eden/Cemu) analogue of
 * {@link NetplaySyntheticInputTester} -- on-device proof that a second
 * controller_index actually reaches a running Eden/Cemu session on a
 * non-local index, entirely without any networking. Gated behind its own,
 * separate marker file so it can be triggered independently of the
 * libretro-family tester.
 *
 * <p>Taps LUCENT_PAD_START (ordinal 12) on controller_index 1 once (many
 * local-co-op titles require a second player to press Start/+ to join
 * before their character exists), then toggles LUCENT_PAD_DPAD_RIGHT
 * (ordinal 11) on controller_index 1 twice a second -- a movement control
 * rather than Start, so a real two-controller title shows player 2
 * visibly moving on screen for the ongoing proof.
 */
public final class NativeAdapterSyntheticInputTester {
    private static final String TAG = "LucentNativeAdapterSynthTest";
    private static final String MARKER_FILE = "lucent-native-adapter-synthetic-test";
    private static final int LUCENT_PAD_START = 12;
    private static final int LUCENT_PAD_DPAD_RIGHT = 11;
    private static final int REMOTE_CONTROLLER_INDEX = 1;
    private static final long JOIN_TAP_MS = 150L;
    private static final long JOIN_SETTLE_MS = 1_500L;
    private static final long TOGGLE_INTERVAL_MS = 500L;

    private NativeAdapterSyntheticInputTester() {}

    public static boolean isRequested(Context context) {
        File marker = new File(Environment.getExternalStorageDirectory(), MARKER_FILE);
        return marker.exists();
    }

    /** Starts the join-then-toggle sequence; returns the HandlerThread so the caller can stop() it on teardown. */
    public static HandlerThread start(NativeControlSink sink) {
        Log.w(TAG, "SYNTHETIC NATIVE-ADAPTER INPUT TEST ACTIVE -- controller_index 1 will tap " +
                "Start once to join, then toggle Right every " + TOGGLE_INTERVAL_MS +
                "ms. This must never run outside manual verification.");
        HandlerThread thread = new HandlerThread("lucent-native-adapter-synth-test");
        thread.start();
        Handler handler = new Handler(thread.getLooper());

        sink.applyRemoteControl(REMOTE_CONTROLLER_INDEX, LUCENT_PAD_START, 1f);
        handler.postDelayed(() ->
                sink.applyRemoteControl(REMOTE_CONTROLLER_INDEX, LUCENT_PAD_START, 0f), JOIN_TAP_MS);

        Runnable[] toggle = new Runnable[1];
        boolean[] pressed = {false};
        toggle[0] = () -> {
            pressed[0] = !pressed[0];
            sink.applyRemoteControl(REMOTE_CONTROLLER_INDEX, LUCENT_PAD_DPAD_RIGHT, pressed[0] ? 1f : 0f);
            handler.postDelayed(toggle[0], TOGGLE_INTERVAL_MS);
        };
        handler.postDelayed(toggle[0], JOIN_SETTLE_MS);
        return thread;
    }
}
