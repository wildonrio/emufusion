package com.thorium.lucent.emulators;

/**
 * Held-Stop teardown policy for in-process native adapters.
 *
 * <p>aPS3e's RPCS3 {@code Emu.Kill}/join path aborts the whole process
 * (Scudo invalid chunk on thread {@code Emulation Join}, Thor ps3-13).
 * Library return already completed; destroying the host after that
 * replaces Lucent with the Android launcher.
 */
public final class NativeAdapterStopPolicy {
    private NativeAdapterStopPolicy() {}

    public static boolean reportsQuickResume(String engineId,
                                             boolean adapterQuickResume) {
        return adapterQuickResume && !isAps3e(engineId);
    }

    public static boolean destroyNativeHostOnStop(String engineId) {
        return !isAps3e(engineId);
    }

    private static boolean isAps3e(String engineId) {
        return "aps3e".equals(engineId);
    }
}
