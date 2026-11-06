package com.thorium.nxnative;

import android.view.Surface;

/** The JNI boundary of the host library (dm/android/jni.c). */
final class NxNative {
    static { System.loadLibrary("dmhost"); }

    private NxNative() {}

    static native void nativeSetEnv(String key, String value);
    static native void nativeStart(Surface surface, String packDir, String dataDir, String language, int width, int height);
    static native void nativePad(long buttons, int lx, int ly, int rx, int ry);
    static native void nativeTouch(int[] ids, float[] xs, float[] ys, int count);
    static native void nativePause(boolean paused);
    static native void nativeQuit();
}
