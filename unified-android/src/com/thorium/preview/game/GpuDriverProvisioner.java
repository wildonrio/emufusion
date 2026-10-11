package com.thorium.preview.game;

import android.content.Context;
import android.content.SharedPreferences;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLSurface;
import android.opengl.GLES20;
import android.os.Build;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Per-device Vulkan driver for the embedded Switch runtime.
 *
 * <p>Eden on Adreno runs best on a replacement driver -- Mesa Turnip on the
 * 6xx/7xx series, a newer Qualcomm build on the 8xx series -- loaded through
 * libadrenotools. The standalone app makes every owner pick one by hand. Here
 * the GPU is probed once per OS build, the package Eden's own driver fetcher
 * recommends for that Adreno model is downloaded in the background at startup,
 * and the Switch adapter is handed its directory before its first load in the
 * process. Non-Adreno GPUs (Mali, Immortalis, PowerVR, Xclipse) and models the
 * map leaves unsupported keep the system driver.
 *
 * <p>Every package is pinned by URL, size and SHA-256 and checked again after
 * extraction (meta.json must name the expected library). A Qualcomm package is
 * never applied over a stock Qualcomm driver of the same or newer version.
 * A driver that takes the process down before a first guest frame twice is
 * set aside for that device; the adapter itself falls back to the system
 * driver whenever the custom one fails to open.
 */
public final class GpuDriverProvisioner {
    private static final String TAG = "EmuFusionGpuDriver";
    /** Read by the Eden adapter (engines/patches/eden-lucent-adapter.cpp). */
    static final String ENV_DIR = "EMUFUSION_GPU_DRIVER_DIR";
    static final String ENV_LIBRARY = "EMUFUSION_GPU_DRIVER_LIBRARY";
    static final String PREFS = "gpu-driver";
    static final String MODE_AUTO = "auto";
    static final String MODE_SYSTEM = "system";
    static final int MAX_CRASHES_BEFORE_FIRST_FRAME = 2;
    private static final int CONNECT_TIMEOUT_MS = 15_000;
    private static final int READ_TIMEOUT_MS = 60_000;

    private static final AtomicBoolean PROVISIONING = new AtomicBoolean(false);
    private static final Object LAUNCH_LOCK = new Object();
    /** Driver the adapter received for this process ("" = system); null before the first load. */
    private static String processDriver;

    private GpuDriverProvisioner() {}

    static File root(Context context) {
        return new File(context.getApplicationContext().getFilesDir(), "gpu-drivers");
    }

    static String mode(Context context) {
        return prefs(context).getString("mode", MODE_AUTO);
    }

    static void setMode(Context context, String mode) {
        prefs(context).edit().putString("mode",
                MODE_SYSTEM.equals(mode) ? MODE_SYSTEM : MODE_AUTO).apply();
    }

    /** Starts the background probe and download; returns at once. */
    public static void provisionAsync(Context context) {
        final Context app = context.getApplicationContext();
        if (!PROVISIONING.compareAndSet(false, true)) return;
        Thread worker = new Thread(() -> {
            try { provision(app); }
            catch (Throwable failure) { Log.w(TAG, "Driver provisioning failed", failure); }
            finally { PROVISIONING.set(false); }
        }, "emufusion-gpu-driver");
        worker.setDaemon(true);
        worker.setPriority(Thread.MIN_PRIORITY);
        worker.start();
    }

    static void provision(Context context) throws IOException {
        String[] gpu = gpuIdentity(context);
        GpuDriverTable.DriverPackage chosen = GpuDriverTable.choose(gpu[0], gpu[1]);
        File root = root(context);
        removeOtherPackages(root, chosen);
        if (chosen == null) {
            Log.i(TAG, "System driver kept renderer=" + gpu[0] + " version=" + gpu[1]);
            return;
        }
        if (MODE_SYSTEM.equals(mode(context))) {
            Log.i(TAG, "System driver selected by setting; " + chosen.id + " not downloaded");
            return;
        }
        File dir = new File(root, chosen.id);
        if (isInstalled(dir, chosen)) {
            Log.i(TAG, "Driver ready id=" + chosen.id + " renderer=" + gpu[0]);
            return;
        }
        install(root, chosen);
        Log.i(TAG, "Driver installed id=" + chosen.id + " renderer=" + gpu[0]
                + " stock=" + gpu[1]);
    }

    /**
     * Publishes the driver for the adapter's first load in this process.
     * Only Eden reads it; its driver is resolved once per process, so a later
     * call returns what that first load received.
     */
    static String prepareLaunch(Context context, String engineId) {
        if (!"eden".equals(engineId)) return "";
        synchronized (LAUNCH_LOCK) {
            if (processDriver != null) return processDriver;
            File root = root(context);
            String chosenId = "";
            try {
                String[] gpu = gpuIdentity(context);
                GpuDriverTable.DriverPackage chosen = GpuDriverTable.choose(gpu[0], gpu[1]);
                if (chosen != null && MODE_AUTO.equals(mode(context))) {
                    File dir = new File(root, chosen.id);
                    if (isInstalled(dir, chosen) && !rejected(dir)) {
                        if (!new File(dir, ".proven").isFile()) touch(new File(dir, ".inflight"));
                        String path = dir.getCanonicalPath() + "/";
                        android.system.Os.setenv(ENV_DIR, path, true);
                        android.system.Os.setenv(ENV_LIBRARY, chosen.library, true);
                        chosenId = chosen.id;
                    }
                }
                if (chosenId.isEmpty()) {
                    android.system.Os.unsetenv(ENV_DIR);
                    android.system.Os.unsetenv(ENV_LIBRARY);
                }
            } catch (Throwable failure) {
                Log.w(TAG, "Driver selection failed; using the system driver", failure);
                try {
                    android.system.Os.unsetenv(ENV_DIR);
                    android.system.Os.unsetenv(ENV_LIBRARY);
                } catch (Throwable ignored) {}
                chosenId = "";
            }
            processDriver = chosenId;
            Log.i(TAG, "Switch GPU driver=" + (chosenId.isEmpty() ? "system" : chosenId));
            return chosenId;
        }
    }

    /** The first guest frame proves the driver opened and rendered. */
    static void noteFirstFrame(Context context, String engineId) {
        String driver = currentProcessDriver(engineId);
        if (driver.isEmpty()) return;
        File dir = new File(root(context), driver);
        touch(new File(dir, ".proven"));
        new File(dir, ".inflight").delete();
        new File(dir, ".crashes").delete();
    }

    /** An orderly session end says nothing against the driver. */
    static void noteSessionEnded(Context context, String engineId) {
        String driver = currentProcessDriver(engineId);
        if (!driver.isEmpty()) new File(new File(root(context), driver), ".inflight").delete();
    }

    /** One-line state for /capabilities and logs. */
    public static String describe(Context context) {
        try {
            // Never probe from here: /capabilities is on the theme's startup path.
            String[] gpu = cachedGpuIdentity(context);
            if (gpu == null) return "probing";
            GpuDriverTable.DriverPackage chosen = GpuDriverTable.choose(gpu[0], gpu[1]);
            String state;
            if (chosen == null) state = "system";
            else if (MODE_SYSTEM.equals(mode(context))) state = "system-by-setting";
            else {
                File dir = new File(root(context), chosen.id);
                state = !isInstalled(dir, chosen) ? "pending:" + chosen.id
                        : crashCount(dir, false) >= MAX_CRASHES_BEFORE_FIRST_FRAME
                                && !new File(dir, ".proven").isFile()
                        ? "rejected:" + chosen.id : chosen.id;
            }
            return state + " renderer=" + gpu[0];
        } catch (Throwable failure) {
            return "unknown";
        }
    }

    private static String currentProcessDriver(String engineId) {
        if (!"eden".equals(engineId)) return "";
        synchronized (LAUNCH_LOCK) { return processDriver == null ? "" : processDriver; }
    }

    /** Only called before this process's first load, so any marker is a previous process's. */
    private static boolean rejected(File dir) {
        return crashCount(dir, true) >= MAX_CRASHES_BEFORE_FIRST_FRAME
                && !new File(dir, ".proven").isFile();
    }

    /**
     * A launch marker still present when no load has happened in this process
     * was left by a process that died before the first frame. {@code consume}
     * folds it into the stored count; otherwise it is only counted if this
     * process has not loaded yet (once it has, the marker is its own).
     */
    private static int crashCount(File dir, boolean consume) {
        File inflight = new File(dir, ".inflight");
        File crashes = new File(dir, ".crashes");
        int count = readInt(crashes);
        if (!inflight.isFile()) return count;
        if (!consume) {
            synchronized (LAUNCH_LOCK) { return processDriver == null ? count + 1 : count; }
        }
        count++;
        writeText(crashes, Integer.toString(count));
        inflight.delete();
        Log.w(TAG, "Previous launch with " + dir.getName()
                + " ended before its first frame (" + count + ")");
        return count;
    }

    static boolean isInstalled(File dir, GpuDriverTable.DriverPackage pkg) {
        File verified = new File(dir, ".verified");
        return verified.isFile() && pkg.sha256.equals(readText(verified).trim())
                && new File(dir, pkg.library).isFile();
    }

    private static void install(File root, GpuDriverTable.DriverPackage pkg) throws IOException {
        if (!root.isDirectory() && !root.mkdirs()) throw new IOException("Cannot create " + root);
        File archive = new File(root, pkg.id + ".zip.part");
        File staging = new File(root, pkg.id + ".tmp");
        File target = new File(root, pkg.id);
        deleteTree(staging);
        try {
            download(pkg, archive);
            extract(archive, staging, pkg);
            writeText(new File(staging, ".verified"), pkg.sha256);
            deleteTree(target);
            if (!staging.renameTo(target)) throw new IOException("Cannot publish " + target);
        } finally {
            archive.delete();
            deleteTree(staging);
        }
    }

    private static void download(GpuDriverTable.DriverPackage pkg, File out) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(pkg.url).openConnection();
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
        connection.setInstanceFollowRedirects(true);
        connection.setRequestProperty("User-Agent",
                "EmuFusion-GpuDriver/1.0 (+https://github.com/wildonrio/emufusion)");
        try {
            int status = connection.getResponseCode();
            if (status != 200) throw new IOException("HTTP " + status + " for " + pkg.id);
            MessageDigest digest = sha256();
            long total = 0;
            try (InputStream in = connection.getInputStream();
                 OutputStream file = new FileOutputStream(out)) {
                byte[] buffer = new byte[65536];
                int read;
                while ((read = in.read(buffer)) > 0) {
                    total += read;
                    if (total > pkg.bytes) throw new IOException("Oversized " + pkg.id);
                    digest.update(buffer, 0, read);
                    file.write(buffer, 0, read);
                }
            }
            String actual = hex(digest.digest());
            if (total != pkg.bytes || !pkg.sha256.equals(actual))
                throw new IOException("Hash mismatch for " + pkg.id + " bytes=" + total
                        + " sha256=" + actual);
        } finally {
            connection.disconnect();
        }
    }

    /** Flat archive only: meta.json and shared libraries, no paths. */
    private static void extract(File archive, File staging, GpuDriverTable.DriverPackage pkg) throws IOException {
        if (!staging.mkdirs()) throw new IOException("Cannot create " + staging);
        String meta = null;
        try (ZipInputStream zip = new ZipInputStream(new FileInputStream(archive))) {
            ZipEntry entry;
            byte[] buffer = new byte[65536];
            while ((entry = zip.getNextEntry()) != null) {
                String name = entry.getName();
                if (entry.isDirectory()) continue;
                if (name.contains("/") || name.contains("\\") || name.startsWith("."))
                    throw new IOException("Unexpected entry " + name + " in " + pkg.id);
                boolean isMeta = name.equals("meta.json");
                if (!isMeta && !name.endsWith(".so"))
                    throw new IOException("Unexpected entry " + name + " in " + pkg.id);
                ByteArrayOutputStream metaBytes = isMeta ? new ByteArrayOutputStream() : null;
                try (OutputStream file = new FileOutputStream(new File(staging, name))) {
                    int read;
                    while ((read = zip.read(buffer)) > 0) {
                        file.write(buffer, 0, read);
                        if (metaBytes != null) metaBytes.write(buffer, 0, read);
                    }
                }
                if (metaBytes != null)
                    meta = new String(metaBytes.toByteArray(), StandardCharsets.UTF_8);
            }
        }
        if (meta == null) throw new IOException("No meta.json in " + pkg.id);
        try {
            String library = new org.json.JSONObject(meta).getString("libraryName");
            if (!pkg.library.equals(library))
                throw new IOException("meta.json names " + library + " in " + pkg.id);
        } catch (org.json.JSONException e) {
            throw new IOException("Unreadable meta.json in " + pkg.id, e);
        }
        if (!new File(staging, pkg.library).isFile())
            throw new IOException("Missing " + pkg.library + " in " + pkg.id);
    }

    /** A pin change (or a GPU the map no longer covers) retires the old package. */
    private static void removeOtherPackages(File root, GpuDriverTable.DriverPackage keep) {
        File[] children = root.listFiles();
        if (children == null) return;
        for (File child : children) {
            if (keep != null && child.getName().equals(keep.id)) continue;
            deleteTree(child);
        }
    }

    /** {GL_RENDERER, GL_VERSION}, probed once per OS build. */
    static String[] gpuIdentity(Context context) {
        String[] cached = cachedGpuIdentity(context);
        if (cached != null) return cached;
        String fingerprint = Build.FINGERPRINT == null ? "" : Build.FINGERPRINT;
        SharedPreferences prefs = prefs(context);
        String[] probed = probeGl();
        // A failed probe is retried next time rather than remembered.
        if (probed[0].isEmpty()) return probed;
        prefs.edit().putString("fingerprint", fingerprint)
                .putString("renderer", probed[0]).putString("version", probed[1]).apply();
        return probed;
    }

    private static String[] cachedGpuIdentity(Context context) {
        SharedPreferences prefs = prefs(context);
        String fingerprint = Build.FINGERPRINT == null ? "" : Build.FINGERPRINT;
        if (!fingerprint.equals(prefs.getString("fingerprint", null))) return null;
        return new String[] {prefs.getString("renderer", ""), prefs.getString("version", "")};
    }

    private static String[] probeGl() {
        EGLDisplay display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        if (display == EGL14.EGL_NO_DISPLAY) return new String[] {"", ""};
        int[] version = new int[2];
        if (!EGL14.eglInitialize(display, version, 0, version, 1)) return new String[] {"", ""};
        EGLContext context = EGL14.EGL_NO_CONTEXT;
        EGLSurface surface = EGL14.EGL_NO_SURFACE;
        try {
            int[] attributes = {EGL14.EGL_RENDERABLE_TYPE, EGL14.EGL_OPENGL_ES2_BIT,
                    EGL14.EGL_SURFACE_TYPE, EGL14.EGL_PBUFFER_BIT, EGL14.EGL_NONE};
            EGLConfig[] configs = new EGLConfig[1];
            int[] count = new int[1];
            if (!EGL14.eglChooseConfig(display, attributes, 0, configs, 0, 1, count, 0)
                    || count[0] == 0) return new String[] {"", ""};
            context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT,
                    new int[] {EGL14.EGL_CONTEXT_CLIENT_VERSION, 2, EGL14.EGL_NONE}, 0);
            surface = EGL14.eglCreatePbufferSurface(display, configs[0],
                    new int[] {EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE}, 0);
            if (context == EGL14.EGL_NO_CONTEXT || surface == EGL14.EGL_NO_SURFACE
                    || !EGL14.eglMakeCurrent(display, surface, surface, context))
                return new String[] {"", ""};
            String renderer = GLES20.glGetString(GLES20.GL_RENDERER);
            String glVersion = GLES20.glGetString(GLES20.GL_VERSION);
            return new String[] {renderer == null ? "" : renderer,
                    glVersion == null ? "" : glVersion};
        } finally {
            EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE,
                    EGL14.EGL_NO_CONTEXT);
            if (surface != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display, surface);
            if (context != EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display, context);
            EGL14.eglReleaseThread();
            EGL14.eglTerminate(display);
        }
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static MessageDigest sha256() throws IOException {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IOException(e); }
    }

    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) out.append(String.format(Locale.US, "%02x", b & 0xff));
        return out.toString();
    }

    private static int readInt(File file) {
        try { return Integer.parseInt(readText(file).trim()); }
        catch (NumberFormatException e) { return 0; }
    }

    private static String readText(File file) {
        if (!file.isFile()) return "";
        try (InputStream in = new FileInputStream(file)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[256];
            int read;
            while ((read = in.read(buffer)) > 0) out.write(buffer, 0, read);
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "";
        }
    }

    private static void writeText(File file, String text) {
        try (OutputStream out = new FileOutputStream(file)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            Log.w(TAG, "Cannot write " + file, e);
        }
    }

    private static void touch(File file) {
        writeText(file, Long.toString(System.currentTimeMillis()));
    }

    private static void deleteTree(File file) {
        if (file == null || !file.exists()) return;
        File[] children = file.listFiles();
        if (children != null) for (File child : children) deleteTree(child);
        file.delete();
    }
}
