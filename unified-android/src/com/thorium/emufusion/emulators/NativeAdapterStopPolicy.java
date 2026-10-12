package com.thorium.emufusion.emulators;

/**
 * Held-Stop teardown policy for in-process native adapters.
 *
 * <p>aPS3e's RPCS3 {@code Emu.Kill}/join path aborts the whole process
 * (Scudo invalid chunk on thread {@code Emulation Join}, Thor ps3-13).
 * Library return already completed; destroying the host after that
 * replaces Lucent with the Android launcher.
 *
 * <p>Eden (Switch) runs its guest natively (NCE), and Eden's teardown is not
 * safe in this long-lived process: on the Thor it crashed in an NVDEC thread
 * while nvdrv closed and in a kernel assert while AM terminated the title.
 * Its flush_save pauses the guest and flushes every buffered save file, then
 * the host is retained and the process replaced after that acknowledged
 * stop -- like aPS3e, but never on a timer.
 */
public final class NativeAdapterStopPolicy {
    private NativeAdapterStopPolicy() {}

    public static boolean reportsQuickResume(String engineId,
                                             boolean adapterQuickResume) {
        return adapterQuickResume && !isAps3e(engineId);
    }

    public static boolean destroyNativeHostOnStop(String engineId) {
        return !retainsHostForProcessExit(engineId);
    }

    /** Engines whose next guest needs a fresh process, even after normal Stop. */
    public static boolean requiresCleanFrontendRestart(String engineId) {
        // Thor Off-to-Off Metroid relaunch hangs on both a034e602 and b321bab2
        // despite acknowledged native close. Switch flushes its saves, keeps
        // its native owner, and renews the process before admitting another
        // guest.
        return isAps3e(engineId) || "eden".equals(engineId);
    }

    /**
     * Only aPS3e may be replaced on a timer. Eden also retains its host, but
     * its restart still waits for the acknowledged save flush and release.
     */
    public static boolean allowsForcedFrontendRestart(String engineId) {
        return isAps3e(engineId);
    }

    /** aPS3e and Eden intentionally retain native resources for process exit. */
    private static boolean retainsHostForProcessExit(String engineId) {
        return isAps3e(engineId) || "eden".equals(engineId);
    }

    private static boolean isAps3e(String engineId) {
        return "aps3e".equals(engineId);
    }
}
