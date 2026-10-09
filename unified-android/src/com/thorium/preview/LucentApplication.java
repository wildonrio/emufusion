package com.thorium.preview;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.Application;
import android.content.Intent;
import android.media.AudioManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import com.thorium.preview.game.InternalEngineBootstrap;
import com.thorium.preview.game.FrameGenerationSettings;
import com.thorium.preview.game.InWindowGameHost;

import java.lang.ref.WeakReference;
import java.util.concurrent.atomic.AtomicBoolean;

/** Starts EmuFusion's frontend, in-window engines, and companion features. */
public final class LucentApplication
        extends org.qtproject.qt5.android.bindings.QtApplication {
    // The inherited Qt/JNI class name is retained for binary compatibility;
    // it is EmuFusion's sole foreground MainActivity in this package.
    private static final String LUCENT_ACTIVITY =
            "org.pegasus_frontend.android.MainActivity";
    private static volatile WeakReference<Activity> liveMainActivity =
            new WeakReference<>(null);
    private static final String TAG = "EmuFusionApplication";
    // 400ms x 40 covers roughly sixteen seconds, far longer than the platform
    // takes to publish a resumed activity's uid state, without spinning if the
    // process really was created in the background.
    private static final long SERVICE_RETRY_MS = 400L;
    private static final int SERVICE_RETRY_LIMIT = 40;
    private final AtomicBoolean completingFirstSetup = new AtomicBoolean(false);
    private final AtomicBoolean serviceStarted = new AtomicBoolean(false);
    private final Handler serviceStartHandler = new Handler(Looper.getMainLooper());
    private int serviceStartAttempts;
    private boolean firstSetupRequired;
    private boolean firstSetupRestartReady;
    private boolean initialLibraryScanFinished;
    private int firstSetupFocusAttempts;
    private WeakReference<Activity> resumedFrontend = new WeakReference<>(null);

    @Override
    public void onCreate() {
        super.onCreate();
        // FrontendRestartActivity is a deliberately tiny bridge in a separate
        // process. It must not register/preload engines or start PreviewService:
        // either action can recreate the default process before the bridge has
        // retired the old Qt renderer and launched the new MainActivity.
        if (isFrontendRestartProcess()) {
            Log.i(TAG, "Frontend restart bridge process initialized without app services");
            return;
        }
        // Capture this before PreviewService can install the theme. Otherwise
        // its worker may create the version marker while Qt has already read
        // the old/missing configuration, causing us to skip the needed restart.
        firstSetupRequired = !ThemeInstaller.isFrontendConfigured();
        // Engine registration hash-verifies every bundled core; register()
        // runs that on its own background thread and catalog consumers block
        // until it completes, so onCreate stays off the ANR path.
        InternalEngineBootstrap.register(this);
        // Qualification APKs validate the optional lawful RIFE payload and
        // cold Vulkan/model initialization away from game launch and renderer
        // callbacks. Normal APKs do not contain that class and fail closed.
        if (FrameGenerationSettings.isEnabled(this))
            FrameGenerationSettings.prewarmOptionalBackends(this);
        // Theme extraction can touch thousands of external-storage files and
        // must never delay Application startup. PreviewService installs or
        // updates it on its worker thread; the first-setup lifecycle callback
        // restarts EmuFusion once that initial install is complete.
        startEmuFusionService();
        registerActivityLifecycleCallbacks(new Application.ActivityLifecycleCallbacks() {
            @Override public void onActivityResumed(Activity activity) {
                routeVolumeKeysToMusicStream(activity);
                // A platform slider, headset, or separate browser window can
                // change STREAM_MUSIC while MainActivity is paused. Reconcile
                // every Thor-local sink before resumed media can become
                // audible, so a system index of zero can never return to a
                // stale nonzero AudioTrack/MediaPlayer/SoundPool gain.
                AppVolumeController.apply(activity);
                rememberMainActivity(activity);
                // A resumed Activity is unambiguously foreground, so this is
                // where a start the platform refused during onCreate succeeds.
                // No-op once the service is running.
                startEmuFusionService();
                // If Android sent the owner through its one-time "install
                // unknown apps" permission screen, continue directly into the
                // package installer. The downloaded APK stays app-private;
                // there is never a file-manager step.
                UpdateManager.resumePendingInstall(activity);
                if (LUCENT_ACTIVITY.equals(activity.getClass().getName())) {
                    resumedFrontend = new WeakReference<>(activity);
                    firstSetupFocusAttempts = 0;
                    // Also retries after Android's storage permission screen;
                    // the empty-library fallback never runs our QML heartbeat.
                    if (ThemeInstaller.hasStorageAccess(LucentApplication.this))
                        startService(new Intent(LucentApplication.this, PreviewService.class)
                                .setAction(PreviewService.ACTION_INITIAL_LIBRARY_SCAN));
                    scheduleFirstSetupRestart();
                }
                completeFirstSetupIfNeeded(activity);
            }
            @Override public void onActivityCreated(Activity activity, Bundle state) {
                routeVolumeKeysToMusicStream(activity);
                rememberMainActivity(activity);
                installFirstSetupFocusListener(activity);
            }
            @Override public void onActivityStarted(Activity activity) {
                rememberMainActivity(activity);
            }
            @Override public void onActivityPaused(Activity activity) {
                if (resumedFrontend.get() == activity) {
                    resumedFrontend = new WeakReference<>(null);
                    serviceStartHandler.removeCallbacks(firstSetupRestart);
                }
            }
            @Override public void onActivityStopped(Activity activity) {}
            @Override public void onActivitySaveInstanceState(Activity activity, Bundle state) {}
            @Override public void onActivityDestroyed(Activity activity) {
                Activity remembered = liveMainActivity.get();
                if (remembered == activity) liveMainActivity = new WeakReference<>(null);
            }
        });
    }

    private boolean isFrontendRestartProcess() {
        String expected = getPackageName() + ":frontend_restart";
        if (Build.VERSION.SDK_INT >= 28) {
            String processName = Application.getProcessName();
            if (processName != null) return expected.equals(processName);
        }
        ActivityManager manager = (ActivityManager)getSystemService(ACTIVITY_SERVICE);
        if (manager == null) return false;
        java.util.List<ActivityManager.RunningAppProcessInfo> processes =
                manager.getRunningAppProcesses();
        if (processes == null) return false;
        int myPid = android.os.Process.myPid();
        for (ActivityManager.RunningAppProcessInfo process : processes) {
            if (process != null && process.pid == myPid)
                return expected.equals(process.processName);
        }
        return false;
    }

    /**
     * Points the hardware volume keys at the one stream EmuFusion actually plays
     * on.
     *
     * Everything audible in this process is STREAM_MUSIC: both engine
     * AudioTracks (LibretroEngineSession/PpssppGlesEngineSession
     * createAudioTrack) and the preview MediaPlayer. Without this call Android
     * gives an Activity whose window has no active stream the *default* target
     * — ring/notification volume on most devices — so the keys move a stream
     * nothing plays on while STREAM_MUSIC keeps whatever level it last had.
     * That is the reported "turn it down and it only goes part-way, turn it up
     * and it stays low", and the silent-menus case is simply STREAM_MUSIC
     * having been left at zero.
     *
     * Every Activity in the process is covered here rather than in each
     * onCreate: the callbacks are registered in Application.onCreate, before
     * any Activity of this process exists, so MainActivity (whose Java class is
     * Pegasus's and is only reachable through smali patching), PreviewActivity,
     * BrowserActivity, and RomLaunchActivity all get it with no extra patch.
     * It is applied again on resume so a re-created or restored Activity can
     * never come back with the platform default.
     */
    private static void routeVolumeKeysToMusicStream(Activity activity) {
        if (activity != null) activity.setVolumeControlStream(AudioManager.STREAM_MUSIC);
    }

    /** Returns EmuFusion's existing Qt activity without creating or resuming one. */
    public static Activity currentMainActivity() {
        Activity activity = liveMainActivity.get();
        return activity != null && !activity.isFinishing() && !activity.isDestroyed()
                ? activity : null;
    }

    private static void rememberMainActivity(Activity activity) {
        if (activity != null && LUCENT_ACTIVITY.equals(activity.getClass().getName()))
            liveMainActivity = new WeakReference<>(activity);
    }

    /**
     * Starts the companion service, retrying until the platform accepts it.
     *
     * <p>Android 12+ only. This process IS created to show the foreground
     * MainActivity, but Application.onCreate runs BEFORE that Activity is
     * bound, and the platform still sees the uid as idle with procs:0 in that
     * window whenever the app has been unused long enough to leave the active
     * standby bucket. The start is refused, and the unchecked exception kills
     * the process during startup: EmuFusion simply fails to open.
     *
     * <p>Retrying is required rather than merely swallowing the refusal.
     * Frontend startup depends on this service — it owns the theme install and
     * the control endpoints the theme drives — so a process that survives
     * without it just shows a black screen. onActivityResumed alone is not
     * late enough either: the uid record is still stale when the resume
     * callback runs, so the retry has to outlive that moment.
     *
     * <p>PreviewService enters foreground state at the first line of onCreate
     * and again in onStartCommand, so Android 8+ can use the supported
     * startForegroundService contract without risking its five-second deadline.
     */
    private void startEmuFusionService() {
        if (serviceStarted.get()) return;
        try {
            startCompanionService();
            serviceStarted.set(true);
            serviceStartHandler.removeCallbacks(serviceStartRetry);
        } catch (IllegalStateException backgroundStartRefused) {
            Log.i(TAG, "Companion service start refused, retrying: " +
                    backgroundStartRefused.getMessage());
            serviceStartHandler.removeCallbacks(serviceStartRetry);
            serviceStartHandler.postDelayed(serviceStartRetry, SERVICE_RETRY_MS);
        }
    }

    private final Runnable serviceStartRetry = new Runnable() {
        @Override public void run() {
            if (serviceStarted.get()) return;
            try {
                startCompanionService();
                serviceStarted.set(true);
                Log.i(TAG, "Companion service started after " +
                        serviceStartAttempts + " retries");
            } catch (IllegalStateException stillRefused) {
                if (++serviceStartAttempts < SERVICE_RETRY_LIMIT) {
                    serviceStartHandler.postDelayed(this, SERVICE_RETRY_MS);
                } else {
                    // Give up quietly rather than spin forever: a process that
                    // genuinely is in the background has nothing to show.
                    Log.w(TAG, "Companion service could not be started: " +
                            stillRefused.getMessage());
                }
            }
        }
    };

    private void startCompanionService() {
        Intent service = new Intent(this, PreviewService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            startForegroundService(service);
        else
            startService(service);
    }

    private void completeFirstSetupIfNeeded(Activity activity) {
        if (!LUCENT_ACTIVITY.equals(activity.getClass().getName()) ||
                !ThemeInstaller.hasStorageAccess(this) ||
                (!firstSetupRequired && ThemeInstaller.isFrontendConfigured()) ||
                !completingFirstSetup.compareAndSet(false, true)) return;

        Thread worker = new Thread(() -> {
            boolean ready = ThemeInstaller.installBundledNow(this);
            startEmuFusionService();
            serviceStartHandler.post(() -> {
                if (!ready) {
                    completingFirstSetup.set(false);
                    Log.e(TAG, "First setup failed; frontend restart withheld");
                    Activity owner = resumedFrontend.get();
                    if (owner != null && !owner.isFinishing() && !owner.isDestroyed()) {
                        new android.app.AlertDialog.Builder(owner)
                                .setTitle("EmuFusion setup couldn't finish")
                                .setMessage("Check that storage access is allowed and storage has free space, then retry.")
                                .setPositiveButton("Retry", (dialog, which) -> completeFirstSetupIfNeeded(owner))
                                .setNegativeButton("Close", (dialog, which) -> owner.finish())
                                .show();
                    }
                    return;
                }
                firstSetupRestartReady = true;
                firstSetupFocusAttempts = 0;
                scheduleFirstSetupRestart();
            });
        }, "lucent-first-setup");
        worker.setDaemon(true);
        worker.start();
    }

    void onInitialLibraryScanFinished(boolean changed) {
        serviceStartHandler.post(() -> {
            initialLibraryScanFinished = true;
            firstSetupRestartReady |= changed;
            firstSetupFocusAttempts = 0;
            scheduleFirstSetupRestart();
        });
    }

    /** Publish a completed local rescan without waiting for online media. */
    void onLibraryIndexChanged() {
        serviceStartHandler.post(() -> {
            firstSetupRestartReady = true;
            firstSetupFocusAttempts = 0;
            scheduleFirstSetupRestart();
        });
    }

    private void installFirstSetupFocusListener(Activity activity) {
        if (!LUCENT_ACTIVITY.equals(activity.getClass().getName())) return;
        // A dialog (including our legal notice) may keep focus for longer than
        // the bounded first-setup retry window. Dismissing it does not cause
        // Activity.onResume, so resume-only recovery leaves the old Qt library
        // visible indefinitely. The decor owns this listener for the Activity's
        // lifetime; no global strong Activity reference is retained.
        activity.getWindow().getDecorView().getViewTreeObserver()
                .addOnWindowFocusChangeListener(hasFocus -> {
                    if (hasFocus && resumedFrontend.get() == activity
                            && !activity.isFinishing() && !activity.isDestroyed()) {
                        firstSetupFocusAttempts = 0;
                        scheduleFirstSetupRestart();
                    }
                });
    }

    private void scheduleFirstSetupRestart() {
        serviceStartHandler.removeCallbacks(firstSetupRestart);
        if (initialLibraryScanFinished && firstSetupRestartReady &&
                ThemeInstaller.isFrontendConfigured() && resumedFrontend.get() != null)
            serviceStartHandler.post(firstSetupRestart);
    }

    private final Runnable firstSetupRestart = new Runnable() {
        @Override public void run() {
            Activity owner = resumedFrontend.get();
            if (!firstSetupRestartReady || owner == null || owner.isFinishing()
                    || owner.isDestroyed()) return;
            // Permission dialogs can still own focus when onResume fires.
            // Never recreate MainActivity in the old process: Qt keeps the
            // renderer/Surface for that process's lifetime and goes blank.
            if (!owner.hasWindowFocus() || !InWindowGameHost.tryBeginImportFrontendRestart()) {
                if (++firstSetupFocusAttempts < 150)
                    serviceStartHandler.postDelayed(this, 100L);
                return; // A later resume retries; an active game is never killed.
            }
            try {
                owner.startActivity(FrontendRestartActivity.createIntent(owner));
                firstSetupRestartReady = false;
                Log.i(TAG, "Local library and setup ready; handing off to clean Qt restart");
            } catch (RuntimeException failure) {
                InWindowGameHost.cancelImportFrontendRestart();
                Log.e(TAG, "Unable to start first-setup restart bridge", failure);
                if (++firstSetupFocusAttempts < 150)
                    serviceStartHandler.postDelayed(this, 100L);
            }
        }
    };
}
