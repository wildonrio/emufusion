package android.util;

/** Host-JVM compile-only stand-in; never packaged in the Android APK. */
public final class Log {
    public static int i(String tag, String msg) { return 0; }
    public static int w(String tag, String msg) { return 0; }
    public static int w(String tag, String msg, Throwable error) { return 0; }
    public static int e(String tag, String msg) { return 0; }
}
