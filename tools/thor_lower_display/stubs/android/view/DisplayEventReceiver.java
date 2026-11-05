package android.view;

import android.os.Looper;

/**
 * Compile-time stub of the framework's hidden class, for javac only; it is left out of
 * the dex so the device's real class is used.
 */
public abstract class DisplayEventReceiver {
    public DisplayEventReceiver(Looper looper) {
        throw new RuntimeException("Stub!");
    }

    public void onHotplug(long timestampNanos, long physicalDisplayId, boolean connected) {
        throw new RuntimeException("Stub!");
    }
}
