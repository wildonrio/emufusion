package com.thorium.lucent.state;

/** Memory and exit rules shared by large in-process emulator states. */
public final class QuickResumePolicy {
    public static final int MAX_IN_MEMORY_RECOVERY_COPY_BYTES = 64 * 1024 * 1024;

    private QuickResumePolicy() {}

    /**
     * Whether serialized emulator state may be applied to a running core.
     *
     * <p>ARMSX2 can accept a matching state and continue running at full speed
     * while publishing only black Vulkan frames.  That failure is silent: the
     * core, audio path, and libretro return value all remain healthy, so the
     * host has no trustworthy post-restore success signal.  Keep its existing
     * snapshots on disk for a future, separately qualified migration, but cold
     * boot now and rely on the title's ordinary PS2 memory-card data.
     *
     * <p>Dolphin was quarantined for a different, equally observable reason:
     * restoring its guest state after the first visible frame recreated the EGL
     * surface and reset the renderer a second time, which on the Thor was the
     * startup/return flicker reported for GameCube and Wii. That is now the
     * exact recovery {@code PpssppGlesEngineSession.restoreQuickResume}
     * performs (recreate the generator-owned Surface immediately after
     * unserialize, before any frame presents on the stale pre-snapshot
     * attachment), so Dolphin no longer needs to cold-boot past a matching
     * snapshot -- 2026-09-06.</p>
     */
    public static boolean allowsRuntimeRestore(String engineId) {
        if (engineId == null || engineId.trim().isEmpty())
            throw new IllegalArgumentException("engine id is required");
        return !"armsx2".equals(engineId);
    }

    public static boolean shouldCopyPreviousToRecovery(int newStateBytes) {
        if (newStateBytes < 0) throw new IllegalArgumentException("state size cannot be negative");
        return newStateBytes <= MAX_IN_MEMORY_RECOVERY_COPY_BYTES;
    }

    public static boolean mayCompleteStop(boolean exitToEmuFusion,
                                          boolean commitSucceeded) {
        return !exitToEmuFusion || commitSucceeded;
    }
}
