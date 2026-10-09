package com.thorium.preview.game;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.os.Bundle;
import android.util.Log;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.Window;
import android.view.WindowManager;

import org.json.JSONObject;

/**
 * Shell-launched, qualification-APK-only LSFG transport self-test.
 *
 * <p>This is deliberately not a gameplay or product entry point. It owns one
 * black top-display surface, runs the bounded native opening self-test, emits
 * one machine-readable result, closes every native resource, and exits. The
 * owner-staged shaders remain app-private and are never packaged.</p>
 */
public final class LsfgQualificationSelfTestActivity extends Activity
        implements SurfaceHolder.Callback {
    private static final String TAG = "EmuFusion-LSFG-SelfTest";
    private static final int ENDPOINT_WIDTH = 256;
    private static final int ENDPOINT_HEIGHT = 144;

    private SurfaceView surfaceView;
    private volatile long nativeHandle;
    private boolean started;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN |
                WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        WindowManager.LayoutParams attributes = getWindow().getAttributes();
        // The Surface remains composited for physical-timing evidence while
        // the OLED emits no visible qualification pattern.
        attributes.screenBrightness = 0.0f;
        getWindow().setAttributes(attributes);
        getWindow().getDecorView().setBackgroundColor(Color.BLACK);

        surfaceView = new SurfaceView(this);
        surfaceView.setBackgroundColor(Color.BLACK);
        surfaceView.getHolder().setFormat(PixelFormat.RGBA_8888);
        surfaceView.getHolder().addCallback(this);
        setContentView(surfaceView);
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {
        if (started) return;
        started = true;
        // Run after Surface creation returns so the compositor can publish the
        // window before native creates its owned FIFO swapchain.
        surfaceView.post(() -> {
            Surface surface = holder.getSurface();
            Thread worker = new Thread(
                    () -> runSelfTest(surface), "EmuFusion-LSFG-SelfTest");
            worker.start();
        });
    }

    private void runSelfTest(Surface surface) {
        boolean passed = false;
        String record = "{}";
        try {
            if (surface == null || !surface.isValid())
                throw new IllegalStateException("qualification surface is invalid");
            LsfgQualificationRuntime.Prepared prepared =
                    LsfgQualificationRuntime.open(this);
            nativeHandle = NativeLsfgBridge.open(surface,
                    prepared.shaderDirectory.getAbsolutePath(),
                    ENDPOINT_WIDTH, ENDPOINT_HEIGHT);
            if (nativeHandle == 0L)
                throw new IllegalStateException("LSFG native self-test open failed");
            record = NativeLsfgBridge.capabilities(nativeHandle);
            JSONObject capabilities = new JSONObject(record);
            passed = capabilities.getBoolean("selfTestPassed") &&
                    capabilities.getBoolean("selfTestEndpoint") &&
                    capabilities.getBoolean("selfTestGenerated") &&
                    capabilities.getBoolean("selfTestDeadline") &&
                    capabilities.getBoolean("selfTestPhysicalTiming") &&
                    capabilities.getBoolean("selfTestContent") &&
                    capabilities.getBoolean("selfTestLiveSurfaceControl") &&
                    capabilities.getBoolean("selfTestLiveCadence") &&
                    capabilities.getLong("selfTestLiveCadencePresents") == 240L &&
                    capabilities.getLong("selfTestLiveCadenceGenerated") == 120L &&
                    capabilities.getLong("selfTestLiveCadenceMinIntervalNs") > 0L &&
                    capabilities.getLong("selfTestLiveCadenceMaxIntervalNs") >=
                            capabilities.getLong("selfTestLiveCadenceMinIntervalNs") &&
                    !capabilities.getBoolean("ownedWsiImplemented") &&
                    capabilities.getBoolean("ownedWsiFrozenReference") &&
                    capabilities.getBoolean("surfaceControlPresentation") &&
                    capabilities.getBoolean("surfaceControlDesiredPresentTime") &&
                    capabilities.getBoolean("surfaceControlPhysicalFence") &&
                    capabilities.getBoolean("surfaceControlLiveImplemented") &&
                    capabilities.getBoolean("surfaceControlReleaseFenceReuse") &&
                    capabilities.getLong("selfTestGenerationCompleteNs") <
                            capabilities.getLong("selfTestGenerationDeadlineNs") &&
                    capabilities.getLong("selfTestFirstLatchNs") > 0L &&
                    capabilities.getLong("selfTestFirstActualNs") >=
                            capabilities.getLong("selfTestFirstLatchNs") &&
                    capabilities.getLong("selfTestSecondLatchNs") > 0L &&
                    capabilities.getLong("selfTestSecondActualNs") >=
                            capabilities.getLong("selfTestSecondLatchNs") &&
                    capabilities.getLong("selfTestPhysicalIntervalNs") > 0L &&
                    capabilities.getBoolean("liveResourcesReady") &&
                    capabilities.getBoolean("zeroWaitLivePath") &&
                    !capabilities.getBoolean("liveDeviceWaitIdle") &&
                    !capabilities.getBoolean("liveBlockingFenceWait");
            if (!passed)
                throw new IllegalStateException("LSFG capability record rejected");
            Log.i(TAG, "RESULT PASS capabilities=" + record);
            runOnUiThread(() -> setResult(RESULT_OK));
        } catch (Throwable failure) {
            Log.e(TAG, "RESULT FAIL capabilities=" + record, failure);
            runOnUiThread(() -> setResult(RESULT_CANCELED));
        } finally {
            closeNative();
            // Let logcat flush the terminal result, then remove the black
            // qualification task. The host harness powers the OLED off next.
            surfaceView.postDelayed(this::finishAndRemoveTask, 100L);
        }
    }

    private synchronized void closeNative() {
        long handle = nativeHandle;
        nativeHandle = 0L;
        if (handle != 0L) NativeLsfgBridge.close(handle);
    }

    @Override public void surfaceChanged(
            SurfaceHolder holder, int format, int width, int height) {}

    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        closeNative();
    }

    @Override protected void onDestroy() {
        closeNative();
        super.onDestroy();
    }
}
