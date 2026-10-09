package com.thorium.preview;

import java.util.Locale;

/**
 * Update-availability logic for installed external emulators.
 *
 * Install and update stay a user decision: this class never installs or forces
 * anything. It answers "is a newer release available?" for an emulator EmuFusion
 * knows a release source for (a {@code github} or {@code official-api} option in
 * {@link EmulatorCatalog}), and builds the same non-silent install/update offer
 * that opens the emulator's official source.
 *
 * The network fetch of the latest release tag is intentionally injected as a
 * {@link ReleaseLookup} so this stays pure and host-testable; PreviewService
 * (out of scope for this workstream) owns the actual HTTP call and the settings
 * surface that presents the offer.
 */
final class ExternalEmulatorUpdater {

    /** Resolves the latest published version tag for a release source, or "". */
    interface ReleaseLookup {
        String latestTag(String source, String sourceType);
    }

    /** The outcome of an update check for a single installed emulator. */
    static final class Result {
        final String emulatorId;
        final String installedVersion;
        final String latestVersion;
        final boolean updateAvailable;
        final String offerCommand; // "" when no newer release or no source

        Result(String emulatorId, String installedVersion, String latestVersion,
               boolean updateAvailable, String offerCommand) {
            this.emulatorId = emulatorId;
            this.installedVersion = installedVersion == null ? "" : installedVersion;
            this.latestVersion = latestVersion == null ? "" : latestVersion;
            this.updateAvailable = updateAvailable;
            this.offerCommand = offerCommand == null ? "" : offerCommand;
        }
    }

    private ExternalEmulatorUpdater() {}

    /** Only emulators with a checkable release source can report updates. */
    static boolean hasCheckableSource(EmulatorCatalog.Option option) {
        return option != null && option.supported() &&
                ("github".equals(option.sourceType) ||
                        "official-api".equals(option.sourceType));
    }

    /**
     * Compares two version strings segment by segment. A {@code v} prefix is
     * ignored and each dot/dash separated segment is compared numerically when
     * both sides are numeric, else lexicographically. Missing trailing segments
     * count as zero, so {@code 1.2} == {@code 1.2.0}.
     */
    static boolean isNewer(String installed, String latest) {
        String[] left = segments(installed);
        String[] right = segments(latest);
        int count = Math.max(left.length, right.length);
        for (int index = 0; index < count; index++) {
            String a = index < left.length ? left[index] : "0";
            String b = index < right.length ? right[index] : "0";
            int order = compareSegment(a, b);
            if (order != 0) return order < 0; // latest greater than installed
        }
        return false; // equal versions: nothing newer to offer
    }

    /**
     * Builds an update {@link Result} for an installed emulator option. Returns
     * a "no update" result (never null) when the source is not checkable, the
     * lookup yields nothing, or the installed version is already current.
     */
    static Result checkForUpdate(EmulatorCatalog.Option option,
                                 String installedVersion, ReleaseLookup lookup) {
        if (!hasCheckableSource(option) || lookup == null) {
            return new Result(option == null ? "" : option.id,
                    installedVersion, "", false, "");
        }
        String latest = lookup.latestTag(option.source, option.sourceType);
        if (latest == null) latest = "";
        boolean newer = !latest.isEmpty() && isNewer(installedVersion, latest);
        // The offer reuses the ordinary install source; it is never a silent or
        // forced install.
        String offer = newer ? EmulatorCatalog.installCommand(option) : "";
        return new Result(option.id, installedVersion, latest, newer, offer);
    }

    private static String[] segments(String value) {
        String trimmed = value == null ? "" : value.trim().toLowerCase(Locale.US);
        if (trimmed.startsWith("v")) trimmed = trimmed.substring(1);
        if (trimmed.isEmpty()) return new String[]{"0"};
        return trimmed.split("[.\\-_]");
    }

    private static int compareSegment(String a, String b) {
        Long na = asLong(a);
        Long nb = asLong(b);
        if (na != null && nb != null) return Long.compare(na, nb);
        return a.compareTo(b);
    }

    private static Long asLong(String value) {
        if (value.isEmpty()) return 0L;
        for (int i = 0; i < value.length(); i++)
            if (!Character.isDigit(value.charAt(i))) return null;
        try {
            return Long.parseLong(value);
        } catch (NumberFormatException error) {
            return null;
        }
    }
}
