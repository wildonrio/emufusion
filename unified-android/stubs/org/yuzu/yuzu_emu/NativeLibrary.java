package org.yuzu.yuzu_emu;

import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * The Java half of Eden's JNI contract.
 *
 * <p>Eden's {@code JNI_OnLoad} (common/android/id_cache.cpp) caches this class
 * and nine static methods before it returns. Lucent opens the adapter with
 * dlopen and supplies the process JavaVM itself, so that lookup runs against
 * Lucent's own dex: without these declarations {@code FindClass} raises
 * ClassNotFoundException, {@code JNI_OnLoad} leaves it pending, and ART aborts
 * the process. Every signature here is copied from the cache site and must
 * match it exactly.
 *
 * <p>Lucent owns the session lifecycle, the surface and the audio track, so the
 * callbacks Eden's own Activity would service are recorded and dropped. The
 * three filesystem helpers are real, because Eden calls them while it walks
 * content.
 */
public final class NativeLibrary {
    private static final String TAG = "LucentEdenBridge";

    private NativeLibrary() {}

    /** Eden asking its Activity to finish. Lucent retires the session instead. */
    public static void exitEmulationActivity(int resultCode) {
        Log.i(TAG, "eden requested exit resultCode=" + resultCode);
    }

    public static void onEmulationStarted() {
        Log.i(TAG, "eden reported emulation started");
    }

    public static void onEmulationStopped(int stopCode) {
        Log.i(TAG, "eden reported emulation stopped code=" + stopCode);
    }

    public static void onProgramChanged(int programIndex) {
        Log.i(TAG, "eden reported program change index=" + programIndex);
    }

    /** Netplay is not surfaced by Lucent; the messages are still logged. */
    public static void addNetPlayMessage(int type, String message) {
        Log.i(TAG, "eden netplay message type=" + type + " message=" + message);
    }

    public static void clearChat() {
        Log.i(TAG, "eden cleared netplay chat");
    }

    public static boolean exists(String path) {
        if (path == null || path.isEmpty()) return false;
        return new File(path).exists();
    }

    /** Eden expects the extension without its dot, or an empty string. */
    public static String getFileExtension(String path) {
        if (path == null) return "";
        int separator = path.lastIndexOf('/');
        String name = separator < 0 ? path : path.substring(separator + 1);
        int dot = name.lastIndexOf('.');
        return dot <= 0 || dot == name.length() - 1 ? "" : name.substring(dot + 1);
    }

    /**
     * Eden copies firmware and key material into its own tree through this. It
     * is a real copy: returning a bare false here would surface later as an
     * unexplained decryption failure rather than a copy failure.
     */
    public static boolean copyFileToStorage(String source, String destination) {
        if (source == null || destination == null) return false;
        File target = new File(destination);
        File parent = target.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            Log.w(TAG, "cannot create destination directory for " + destination);
            return false;
        }
        InputStream in = null;
        OutputStream out = null;
        try {
            in = new FileInputStream(source);
            out = new FileOutputStream(target);
            byte[] buffer = new byte[65536];
            int read;
            while ((read = in.read(buffer)) > 0) out.write(buffer, 0, read);
            return true;
        } catch (Exception failure) {
            Log.w(TAG, "copyFileToStorage failed " + source + " -> " + destination, failure);
            return false;
        } finally {
            closeQuietly(in);
            closeQuietly(out);
        }
    }

    private static void closeQuietly(java.io.Closeable stream) {
        if (stream == null) return;
        try { stream.close(); } catch (Exception ignored) {}
    }

    // ---------------------------------------------------------------------
    // Common::FS::Android::RegisterCallbacks binds the six methods below at
    // load time and aborts if any is missing. Eden routes real filesystem work
    // through them, so these are implemented rather than stubbed: Lucent hands
    // the engine ordinary absolute paths, which java.io.File answers directly.
    // ---------------------------------------------------------------------

    /** Eden expects the parent path, or an empty string at the root. */
    public static String getParentDirectory(String path) {
        if (path == null || path.isEmpty()) return "";
        String parent = new File(path).getParent();
        return parent == null ? "" : parent;
    }

    public static String getFilename(String path) {
        if (path == null) return "";
        return new File(path).getName();
    }

    /** Bytes, or 0 when the path does not resolve. Eden treats 0 as absent. */
    public static long getSize(String path) {
        if (path == null || path.isEmpty()) return 0L;
        File file = new File(path);
        return file.isFile() ? file.length() : 0L;
    }

    public static boolean isDirectory(String path) {
        if (path == null || path.isEmpty()) return false;
        return new File(path).isDirectory();
    }

    /**
     * Storage Access Framework hook. Eden only reaches this for a
     * {@code content://} URI (see Common::FS::Android::IsContentUri) and Lucent
     * always supplies ordinary filesystem paths, so it is never expected to
     * fire. Returning -1 is the documented "could not open" answer; a static
     * method has no Context with which to resolve a URI anyway.
     */
    public static int openContentUri(String uri, String openMode) {
        Log.w(TAG, "eden asked to open a content URI Lucent does not provide: " + uri);
        return -1;
    }

    /** Bound by Common::Android::WebBrowser::InitJNI. Lucent owns browsing. */
    public static void openExternalUrl(String url) {
        Log.i(TAG, "eden requested an external URL, ignored by Lucent: " + url);
    }
}
