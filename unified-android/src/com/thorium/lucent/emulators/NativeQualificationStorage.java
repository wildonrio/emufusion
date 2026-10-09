package com.thorium.lucent.emulators;

/** Storage-isolation admission for the native engines whose paths were audited. */
public final class NativeQualificationStorage {
    private static final EdenProcessRoot EDEN_ROOT = new EdenProcessRoot();

    private NativeQualificationStorage() {}

    public static boolean supports(String engine, String system) {
        return ("aps3e".equals(engine) && "ps3".equals(system))
                || ("eden".equals(engine) && "switch".equals(system));
    }

    public static void claimProcessRoot(String engine, String session) {
        if ("eden".equals(engine)) EDEN_ROOT.claim(session);
    }

    // Eden's Core::System owns a ProfileManager for the whole process, whereas
    // SetAppDirectory changes its global NAND paths at each load. Crossing roots
    // in that process would mix a cached user's identity with another NAND.
    // Do not reset this on title exit, failure or switching to another engine.
    static final class EdenProcessRoot {
        private String claimed;

        synchronized void claim(String session) {
            String next = session == null ? "" : session;
            if (!next.isEmpty() && !next.matches("qa-[0-9a-f]{32}"))
                throw new IllegalArgumentException("Invalid native qualification session");
            if (claimed != null && !claimed.equals(next))
                throw new IllegalStateException(
                        "Restart EmuFusion before switching between Switch test profiles or normal saves");
            claimed = next;
        }
    }
}
