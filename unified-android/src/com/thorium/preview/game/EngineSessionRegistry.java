package com.thorium.preview.game;

import android.content.Context;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Process-local registry populated by approved engine modules at startup. */
public final class EngineSessionRegistry {
    public interface Factory {
        EngineSession create(Context context, GameLaunchRequest request);
    }

    private static final Map<String, Factory> FACTORIES = new ConcurrentHashMap<>();

    private EngineSessionRegistry() {}

    public static void register(String engineId, Factory factory) {
        String normalized = normalize(engineId);
        if (normalized.isEmpty() || factory == null)
            throw new IllegalArgumentException("engineId and factory are required");
        FACTORIES.put(normalized, factory);
    }

    public static void unregister(String engineId) {
        FACTORIES.remove(normalize(engineId));
    }

    public static EngineSession create(Context context, GameLaunchRequest request) {
        Factory factory = FACTORIES.get(normalize(request.engineId));
        return factory == null ? new UnavailableEngineSession(request.engineId)
                : factory.create(context, request);
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(java.util.Locale.US);
    }

    private static final class UnavailableEngineSession implements EngineSession {
        private final String engineId;

        UnavailableEngineSession(String engineId) { this.engineId = engineId; }

        @Override public void prepare(GameLaunchRequest request, Listener listener) {
            listener.onSessionError("Engine is not installed in this EmuFusion build: "
                    + engineId, null);
        }
        @Override public void attachSurface(android.view.Surface surface, int width, int height) {}
        @Override public void resizeSurface(int width, int height) {}
        @Override public void detachSurface() {}
        @Override public void resume() {}
        @Override public void pause(PauseReason reason) {}
        @Override public void quiesceForExit() {}
        @Override public boolean openControls() { return false; }
        @Override public boolean openRestoreHistory() { return false; }
        @Override public boolean dispatchKeyEvent(android.view.KeyEvent event) { return false; }
        @Override public boolean dispatchGenericMotionEvent(android.view.MotionEvent event) { return false; }
        @Override public boolean shouldShowOnScreenControls() { return false; }
        @Override public boolean dispatchVirtualControl(
                com.thorium.lucent.input.CanonicalControl control, boolean pressed) { return false; }
        @Override public void stop(StopReason reason, Completion completion) {
            completion.complete();
        }
        @Override public void release() {}
    }
}
