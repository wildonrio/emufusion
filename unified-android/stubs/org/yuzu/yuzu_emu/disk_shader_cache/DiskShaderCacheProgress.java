package org.yuzu.yuzu_emu.disk_shader_cache;

import android.util.Log;

/**
 * Shader-cache build progress. Eden's JNI cache resolves this class, its nested
 * {@code LoadCallbackStage}, and the static {@code loadProgress} callback at
 * load time, so all three must exist before the adapter is opened.
 *
 * <p>Eden calls loadProgress while it compiles a title's shaders. Lucent has no
 * progress UI for it yet, so the callback logs; a title with a cold cache will
 * still stutter through its first minutes, and that shows up here rather than
 * silently.
 */
public final class DiskShaderCacheProgress {
    private static final String TAG = "LucentEdenBridge";

    private DiskShaderCacheProgress() {}

    public static void loadProgress(int stage, int progress, int maximum) {
        Log.i(TAG, "eden shader cache stage=" + stage + " progress=" + progress
                + "/" + maximum);
    }

    /**
     * Resolved by name as {@code DiskShaderCacheProgress$LoadCallbackStage}.
     * Eden only caches the class reference during JNI_OnLoad, so the members
     * are not part of the load-time contract.
     */
    public static final class LoadCallbackStage {
        private LoadCallbackStage() {}
    }
}
