package com.thorium.preview;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.SurfaceTexture;
import android.media.MediaPlayer;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.Surface;
import android.view.TextureView;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/**
 * EmuFusion's only startup screen.
 *
 * <p>It exists in Java, above Qt's own surface, because the frontend draws a
 * grey progress-bar splash of its own before any theme QML is loaded. A QML
 * boot screen cannot cover that -- it only appears once the theme is up, so the
 * user sees the frontend's splash and then ours. Owning the screen from
 * Activity.onStart is the only place that replaces it rather than following it.
 *
 * <p>It is also deliberately reluctant to appear. A loading screen exists to
 * fill a wait; if the library is already warm and ready in a few hundred
 * milliseconds there is no wait to fill, and flashing a video makes startup
 * feel slower than showing nothing. So the video is only mounted once the app
 * has been busy for {@link #SHOW_AFTER_MS}, and a ready signal before that
 * cancels it outright.
 */
public final class BootVideoOverlay {

    private static final String TAG = "EmuFusionBoot";
    /** Broadcast by PreviewService when the theme reports its library ready. */
    public static final String ACTION_FRONTEND_READY =
            "com.thorium.preview.FRONTEND_READY";
    private static final String ASSET = "boot/loading.mp4";
    private static final String ASSET_SHA256 = "boot/loading.sha256";
    /**
     * Nothing is shown before this. Chosen to sit above the duration of a warm
     * start, so a fast launch shows no video at all, and below the point where
     * a blank screen starts to read as a hang.
     */
    private static final long SHOW_AFTER_MS = 400L;
    /** Never strand the user behind the video if a ready signal never arrives. */
    private static final long FAILSAFE_MS = 20_000L;

    private static final Handler HANDLER = new Handler(Looper.getMainLooper());

    private static Activity host;
    private static FrameLayout overlay;
    private static MediaPlayer player;
    private static BroadcastReceiver readyReceiver;
    private static boolean finished;
    private static Runnable mountTask;
    private static Runnable failsafeTask;

    private BootVideoOverlay() {}

    /** Called from MainActivity.onStart, before the frontend has drawn. */
    public static synchronized void begin(Activity activity) {
        if (activity == null || host != null || finished) return;
        host = activity;
        readyReceiver = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                finish();
            }
        };
        try {
            // Not exported: only this app's own PreviewService sends it.
            activity.registerReceiver(readyReceiver,
                    new IntentFilter(ACTION_FRONTEND_READY),
                    Context.RECEIVER_NOT_EXPORTED);
        } catch (RuntimeException unsupported) {
            try {
                activity.registerReceiver(readyReceiver,
                        new IntentFilter(ACTION_FRONTEND_READY));
            } catch (RuntimeException ignored) {
                // Without the signal the failsafe below still clears it.
            }
        }
        mountTask = new Runnable() {
            @Override public void run() { mount(); }
        };
        failsafeTask = new Runnable() {
            @Override public void run() {
                Log.w(TAG, "Ready signal never arrived; clearing boot screen");
                finish();
            }
        };
        HANDLER.postDelayed(mountTask, SHOW_AFTER_MS);
        HANDLER.postDelayed(failsafeTask, FAILSAFE_MS);
    }

    /** Idempotent: the ready broadcast and the failsafe can both fire. */
    public static synchronized void finish() {
        finished = true;
        if (mountTask != null) { HANDLER.removeCallbacks(mountTask); mountTask = null; }
        if (failsafeTask != null) { HANDLER.removeCallbacks(failsafeTask); failsafeTask = null; }
        if (host != null && readyReceiver != null) {
            try { host.unregisterReceiver(readyReceiver); } catch (RuntimeException ignored) {}
        }
        readyReceiver = null;
        final FrameLayout showing = overlay;
        final MediaPlayer playing = player;
        overlay = null;
        player = null;
        host = null;
        if (showing == null) {
            releaseQuietly(playing);
            return;
        }
        // Fade rather than cut: the frontend behind is already drawn, and a
        // hard swap reads as a flicker.
        showing.animate().alpha(0f).setDuration(260).withEndAction(new Runnable() {
            @Override public void run() {
                ViewGroup parent = (ViewGroup) showing.getParent();
                if (parent != null) parent.removeView(showing);
                releaseQuietly(playing);
            }
        }).start();
    }

    private static synchronized void mount() {
        mountTask = null;
        if (finished || host == null) return;
        File video = extractedVideo(host);
        if (video == null) return;
        View decor = host.getWindow().getDecorView();
        if (!(decor instanceof ViewGroup)) return;

        FrameLayout container = new FrameLayout(host);
        container.setBackgroundColor(Color.BLACK);
        TextureView surface = new TextureView(host);
        // The fitted texture may leave bars; let the black container show
        // through instead of promising opaque pixels across the whole view.
        surface.setOpaque(false);
        container.addView(surface, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT, Gravity.CENTER));
        // A TextureView, not a VideoView: VideoView is SurfaceView-backed and
        // would fight the frontend's own SurfaceView for z-order. A TextureView
        // composites as an ordinary view and reliably draws above it.
        surface.setSurfaceTextureListener(new TextureView.SurfaceTextureListener() {
            @Override public void onSurfaceTextureAvailable(SurfaceTexture texture,
                                                            int width, int height) {
                start(surface, new Surface(texture), video);
            }
            @Override public void onSurfaceTextureSizeChanged(SurfaceTexture t, int w, int h) {
                MediaPlayer playing = player;
                if (playing != null)
                    fitVideo(surface, playing.getVideoWidth(), playing.getVideoHeight());
            }
            @Override public boolean onSurfaceTextureDestroyed(SurfaceTexture t) { return true; }
            @Override public void onSurfaceTextureUpdated(SurfaceTexture t) {}
        });
        ((ViewGroup) decor).addView(container, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        container.bringToFront();
        overlay = container;
    }

    private static synchronized void start(TextureView view, Surface target, File video) {
        if (finished) { target.release(); return; }
        try {
            MediaPlayer created = new MediaPlayer();
            created.setDataSource(video.getPath());
            created.setSurface(target);
            created.setLooping(true);
            created.setVolume(0f, 0f);
            created.setOnVideoSizeChangedListener(new MediaPlayer.OnVideoSizeChangedListener() {
                @Override public void onVideoSizeChanged(MediaPlayer ready, int width, int height) {
                    fitVideo(view, width, height);
                }
            });
            created.setOnPreparedListener(new MediaPlayer.OnPreparedListener() {
                @Override public void onPrepared(MediaPlayer ready) {
                    fitVideo(view, ready.getVideoWidth(), ready.getVideoHeight());
                    ready.start();
                }
            });
            created.prepareAsync();
            player = created;
        } catch (IOException | RuntimeException failure) {
            // A boot screen that cannot play must not block startup.
            Log.w(TAG, "Boot video unavailable", failure);
        }
    }

    /** Undo TextureView's default stretch, fitting the entire video without crop. */
    private static void fitVideo(TextureView view, int videoWidth, int videoHeight) {
        int width = view.getWidth();
        int height = view.getHeight();
        if (width <= 0 || height <= 0 || videoWidth <= 0 || videoHeight <= 0) return;
        float scale = Math.min((float) width / videoWidth, (float) height / videoHeight);
        Matrix transform = new Matrix();
        // TextureView initially maps the decoded buffer to the whole view.
        // These factors undo that nonuniform mapping around the view center.
        transform.setScale(videoWidth * scale / width, videoHeight * scale / height,
                width / 2f, height / 2f);
        view.setTransform(transform);
    }

    /**
     * MediaPlayer needs a real file, and an asset is only openable by descriptor
     * when it was stored uncompressed, which is not something to depend on. The
     * copy happens once and is reused on every later launch.
     */
    private static File extractedVideo(Context context) {
        String identity = assetIdentity(context);
        if (identity == null) return null;
        File target = new File(context.getFilesDir(),
                "boot-loading-" + identity.substring(0, 16) + ".mp4");
        if (target.isFile() && target.length() > 0) return target;
        File partial = new File(target.getPath() + ".partial");
        try (InputStream input = context.getAssets().open(ASSET);
             OutputStream output = new FileOutputStream(partial)) {
            byte[] chunk = new byte[16384];
            int read;
            while ((read = input.read(chunk)) > 0) output.write(chunk, 0, read);
        } catch (IOException missing) {
            partial.delete();
            Log.w(TAG, "No bundled boot video", missing);
            return null;
        }
        // Rename last so a half-written file can never be played on the next
        // launch: this runs during startup, which is exactly when a process is
        // most likely to be killed part way through.
        if (!partial.renameTo(target)) {
            partial.delete();
            return null;
        }
        return target;
    }

    /**
     * Bind the extracted file name to the exact packaged video. APK replacement
     * can keep app-private files, so the former fixed boot-loading.mp4 path
     * continued playing an older video after an update. A content-addressed
     * name makes a changed root loading.mp4 take effect on the first launch of
     * the new APK without deleting unrelated app data.
     */
    private static String assetIdentity(Context context) {
        try (InputStream input = context.getAssets().open(ASSET_SHA256)) {
            byte[] value = new byte[64];
            int offset = 0;
            while (offset < value.length) {
                int count = input.read(value, offset, value.length - offset);
                if (count < 0) break;
                offset += count;
            }
            String hash = new String(value, 0, offset, StandardCharsets.US_ASCII)
                    .trim().toLowerCase(java.util.Locale.US);
            return hash.matches("[0-9a-f]{64}") ? hash : null;
        } catch (IOException missing) {
            Log.w(TAG, "No bundled boot video identity", missing);
            return null;
        }
    }

    private static void releaseQuietly(MediaPlayer target) {
        if (target == null) return;
        try { target.stop(); } catch (RuntimeException ignored) {}
        try { target.release(); } catch (RuntimeException ignored) {}
    }
}
