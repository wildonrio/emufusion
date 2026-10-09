package com.thorium.lucent.netplay;

import android.content.Context;
import android.os.Environment;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;

import java.io.File;

/**
 * On-device proof that a remote player's input actually reaches a
 * running core on a non-local port, entirely without any networking --
 * see the design plan's testing strategy section 7(b). This exists to be
 * run once per libretro-family engine while that port-routing code is
 * new, not as a permanent feature; it can only ever fire when a specific
 * marker file has been placed by hand (e.g. {@code adb shell touch
 * /sdcard/lucent-netplay-synthetic-test}), which nothing in the normal
 * UI or launch flow ever does.
 *
 * <p>First taps Start on port 1 once (many co-op titles, e.g. Contra,
 * require player 2 to press Start to join before their character even
 * exists on screen), then toggles retro joypad "Right" (id 7) on port 1
 * twice a second -- a movement key rather than Start/Select for the
 * ongoing proof, so a real two-controller title shows player 2 visibly
 * walking back and forth on screen instead of a pause menu flickering
 * open and closed.
 */
public final class NetplaySyntheticInputTester {
    private static final String TAG = "LucentNetplaySynthTest";
    private static final String MARKER_FILE = "lucent-netplay-synthetic-test";
    private static final int RETRO_DEVICE_ID_JOYPAD_START = 3;
    private static final int RETRO_DEVICE_ID_JOYPAD_RIGHT = 7;
    private static final long JOIN_TAP_MS = 150L;
    private static final long JOIN_SETTLE_MS = 1_500L;
    private static final long TOGGLE_INTERVAL_MS = 500L;

    private NetplaySyntheticInputTester() {}

    public static boolean isRequested(Context context) {
        File marker = new File(Environment.getExternalStorageDirectory(), MARKER_FILE);
        return marker.exists();
    }

    /** Starts the join-then-toggle sequence; returns the HandlerThread so the caller can stop() it on teardown. */
    public static HandlerThread start(RemoteJoypadSink sink) {
        Log.w(TAG, "SYNTHETIC NETPLAY INPUT TEST ACTIVE -- port 1 will tap Start once to join, " +
                "then toggle Right every " + TOGGLE_INTERVAL_MS +
                "ms. This must never run outside manual verification.");
        HandlerThread thread = new HandlerThread("lucent-netplay-synth-test");
        thread.start();
        Handler handler = new Handler(thread.getLooper());

        sink.applyRemoteJoypadButton(1, RETRO_DEVICE_ID_JOYPAD_START, true);
        handler.postDelayed(() ->
                sink.applyRemoteJoypadButton(1, RETRO_DEVICE_ID_JOYPAD_START, false), JOIN_TAP_MS);

        Runnable[] toggle = new Runnable[1];
        boolean[] pressed = {false};
        toggle[0] = () -> {
            pressed[0] = !pressed[0];
            sink.applyRemoteJoypadButton(1, RETRO_DEVICE_ID_JOYPAD_RIGHT, pressed[0]);
            handler.postDelayed(toggle[0], TOGGLE_INTERVAL_MS);
        };
        handler.postDelayed(toggle[0], JOIN_SETTLE_MS);
        return thread;
    }
}
