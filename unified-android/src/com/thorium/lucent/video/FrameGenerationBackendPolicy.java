package com.thorium.lucent.video;

/**
 * Pure selection policy for one immutable frame-generation session.
 *
 * <p>EmuFusion owns timing regardless of the selected renderer. A backend is
 * never selected from file/package presence: the caller must provide one
 * already-completed assessment covering legal use, ABI/API compatibility,
 * capabilities, initialization/output self-test, and deadline performance.
 */
public final class FrameGenerationBackendPolicy {
    public enum Backend {
        LSFG("LSFG"),
        BUILT_IN("Built-in (Alpha)"),
        DIRECT("Direct");

        private final String label;
        Backend(String label) { this.label = label; }
        public String label() { return label; }
    }

    public static final class Assessment {
        public final boolean legallyUsable;
        public final boolean abiCompatible;
        public final boolean capabilitiesReady;
        public final boolean selfTestPassed;
        public final boolean deadlineQualified;
        public final String reason;

        public Assessment(boolean legallyUsable, boolean abiCompatible,
                          boolean capabilitiesReady, boolean selfTestPassed,
                          boolean deadlineQualified, String reason) {
            this.legallyUsable = legallyUsable;
            this.abiCompatible = abiCompatible;
            this.capabilitiesReady = capabilitiesReady;
            this.selfTestPassed = selfTestPassed;
            this.deadlineQualified = deadlineQualified;
            this.reason = reason == null ? "" : reason;
        }

        public static Assessment ready() {
            return new Assessment(true, true, true, true, true, "ready");
        }

        public static Assessment unavailable(String reason) {
            return new Assessment(false, false, false, false, false, reason);
        }

        public boolean usable() {
            return legallyUsable && abiCompatible && capabilitiesReady &&
                    selfTestPassed && deadlineQualified;
        }
    }

    public static final class Selection {
        public final Backend backend;
        public final Assessment lsfg;
        public final Assessment builtIn;

        private Selection(Backend backend, Assessment lsfg,
                          Assessment builtIn) {
            this.backend = backend;
            this.lsfg = lsfg;
            this.builtIn = builtIn;
        }
    }

    private FrameGenerationBackendPolicy() {}

    /** Selects exactly once; callers retain the returned value for the session. */
    public static Selection select(boolean enabled, Assessment lsfg,
                                   Assessment builtIn) {
        Assessment safeLsfg = lsfg == null ?
                Assessment.unavailable("missing LSFG assessment") : lsfg;
        Assessment safeBuiltIn = builtIn == null ?
                Assessment.unavailable("missing built-in assessment") : builtIn;
        Backend selected = !enabled ? Backend.DIRECT :
                (safeLsfg.usable() ? Backend.LSFG :
                        (safeBuiltIn.usable() ? Backend.BUILT_IN : Backend.DIRECT));
        return new Selection(selected, safeLsfg, safeBuiltIn);
    }
}
