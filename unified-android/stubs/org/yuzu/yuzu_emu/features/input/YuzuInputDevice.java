package org.yuzu.yuzu_emu.features.input;

/**
 * Eden's view of one controller. Its JNI cache resolves these seven instance
 * methods at load time, so the interface has to exist with these exact
 * signatures. Lucent supplies no implementation: input is delivered through
 * Lucent's own InputRouter and set_control on the adapter ABI, and the
 * vibration path is the reason the adapter needed a JavaVM in the first place.
 */
public interface YuzuInputDevice {
    String getName();

    String getGUID();

    int getPort();

    boolean getSupportsVibration();

    void vibrate(float intensity);

    boolean[] hasKeys(int[] keys);

    Integer[] getAxes();
}
