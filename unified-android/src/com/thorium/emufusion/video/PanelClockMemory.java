package com.thorium.emufusion.video;

import java.util.concurrent.ConcurrentHashMap;

/**
 * Measured physical refresh rates per display mode, kept across generators and
 * (with a {@link Store}) across launches. A panel's oscillator is fixed for a
 * mode, so a value measured to a few ppm once lets the next session's clock
 * start from it instead of waiting a full measurement window again. Values
 * are only accepted within the same sub-one-percent bound the clocks use.
 */
public final class PanelClockMemory {
    /** Durable backing, supplied by the app (SharedPreferences). */
    public interface Store {
        double get(String key);
        void put(String key, double hz);
    }

    private static final double MAX_RELATIVE_DEVIATION = 0.0075;
    private static final ConcurrentHashMap<String, Double> VALUES = new ConcurrentHashMap<>();
    private static volatile Store store;

    private PanelClockMemory() {}

    public static void setStore(Store value) { store = value; }

    static String key(int displayId, double nominalHz) {
        return displayId + "@" + Math.round(nominalHz * 1000.0);
    }

    /** The remembered rate for this mode, or 0. */
    public static double lookup(int displayId, double nominalHz) {
        if (!(nominalHz > 0.0)) return 0.0;
        String key = key(displayId, nominalHz);
        Double cached = VALUES.get(key);
        double hz = cached != null ? cached : 0.0;
        Store backing = store;
        if (hz == 0.0 && backing != null) {
            try { hz = backing.get(key); } catch (RuntimeException ignored) { hz = 0.0; }
        }
        return plausible(hz, nominalHz) ? hz : 0.0;
    }

    /** Remembers a full-baseline measurement for this mode. */
    public static void remember(int displayId, double nominalHz, double measuredHz) {
        if (!plausible(measuredHz, nominalHz)) return;
        String key = key(displayId, nominalHz);
        Double previous = VALUES.put(key, measuredHz);
        Store backing = store;
        if (backing != null && (previous == null || Math.abs(previous / measuredHz - 1.0) > 1.0e-5)) {
            try { backing.put(key, measuredHz); } catch (RuntimeException ignored) {}
        }
    }

    static boolean plausible(double hz, double nominalHz) {
        return Double.isFinite(hz) && hz > 0.0 && nominalHz > 0.0 &&
                Math.abs(hz / nominalHz - 1.0) <= MAX_RELATIVE_DEVIATION;
    }

    /** Test hook. */
    static void clearForTest() { VALUES.clear(); store = null; }
}
