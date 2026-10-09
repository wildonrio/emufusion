package com.thorium.lucent.emulators;

/**
 * How an external emulator expects to be handed a ROM.
 *
 * These are the same three mechanisms EmulatorCatalog builds launch recipes
 * for, restated here without any Android dependency so custom-entry validation
 * is host-testable. EmulatorCatalog keeps its own copies as the constants the
 * recipe builder switches on; the values are identical and
 * test_external_emulator_routing.py asserts they stay that way, because a
 * silent divergence would make a valid custom entry unlaunchable.
 */
public final class ExternalEmulatorDelivery {
    /** {@code --es <key> "{file.path}"} — the emulator reads a plain path. */
    public static final String FILE_PATH = "file-path";
    /** {@code -a VIEW -d file://{file.path}} — the emulator opens a file. */
    public static final String ACTION_VIEW = "action-view";
    /** Via EmuFusion's trampoline, for scoped-storage emulators. */
    public static final String CONTENT_URI = "content-uri";

    private ExternalEmulatorDelivery() {}

    public static boolean known(String value) {
        return FILE_PATH.equals(value) || ACTION_VIEW.equals(value)
                || CONTENT_URI.equals(value);
    }

    /**
     * A short phrase for the picker. Written for someone who has never heard of
     * an Intent extra, because that is who is configuring a custom emulator.
     */
    public static String describe(String value) {
        if (FILE_PATH.equals(value)) return "Sends the game's file path";
        if (ACTION_VIEW.equals(value)) return "Asks the app to open the game file";
        if (CONTENT_URI.equals(value)) return "Shares the game through a temporary link";
        return "";
    }
}
