package android.util;
/** Host-test-only Android log sink. */
public final class Log {
    public static String last;
    public static int w(String tag,String message){last=message;return 0;}
}
