package com.thorium.lucent.emulators;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * A user-supplied external emulator, validated well enough to explain itself.
 *
 * Two reasons this is strict rather than a free-text field.
 *
 * First, product: "Custom" has to be a guided setup, so every rejection has to
 * name the field and say what is wrong in words the user can act on. A silent
 * failure here looks identical to a broken emulator.
 *
 * Second, safety: these values are interpolated into the {@code am start …}
 * string that EmulatorCatalog builds and Pegasus executes as a shell command.
 * An unvalidated activity name or extra key is therefore an argument-injection
 * surface, not merely a typo. The patterns below admit only the character set
 * Android itself allows for package names, class names and extra keys, which
 * excludes every quoting, separator and substitution character a shell reacts
 * to. Validation is whitelist-only for exactly that reason.
 *
 * Whether the package is actually installed is deliberately NOT decided here —
 * that needs a PackageManager and belongs to the Android layer. This class
 * answers "is this a well-formed target at all", which is the question that can
 * be answered, and tested, on the host.
 */
public final class CustomEmulatorSpec {

    /** The reserved emulator id a custom target is stored under, per system. */
    public static final String ID = "custom";

    // Android package ids: dot-separated Java identifiers, at least two parts.
    private static final Pattern PACKAGE =
            Pattern.compile("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+");
    // Class names additionally allow '$' for the nested-class form Android
    // components occasionally use.
    private static final Pattern CLASS_SEGMENT =
            Pattern.compile("[A-Za-z][A-Za-z0-9_$]*");
    // Intent string-extra keys, as they appear after --es.
    private static final Pattern EXTRA_KEY =
            Pattern.compile("[A-Za-z][A-Za-z0-9_.]*");

    /** One thing wrong with the entry, addressed to the person fixing it. */
    public static final class Problem {
        private final String field;
        private final String message;

        Problem(String field, String message) {
            this.field = field;
            this.message = message;
        }

        /** "package", "activity", "romExtraKey" or "delivery". */
        public String field() { return field; }

        /** Shown verbatim in the guided setup. */
        public String message() { return message; }
    }

    private final String packageName;
    private final String activity;
    private final String delivery;
    private final String romExtraKey;
    private final List<Problem> problems;

    private CustomEmulatorSpec(String packageName, String activity, String delivery,
                               String romExtraKey, List<Problem> problems) {
        this.packageName = packageName;
        this.activity = activity;
        this.delivery = delivery;
        this.romExtraKey = romExtraKey;
        this.problems = Collections.unmodifiableList(problems);
    }

    /**
     * Validates a custom entry. {@code ownPackage} is EmuFusion's own package
     * id; pointing a system at EmuFusion would make launching a game re-enter
     * the frontend forever, so it is rejected by name rather than left to
     * produce a mystifying loop on the device.
     */
    public static CustomEmulatorSpec parse(String packageName, String activity,
                                           String delivery, String romExtraKey,
                                           String ownPackage) {
        List<Problem> problems = new ArrayList<>();
        String trimmedPackage = trim(packageName);
        String trimmedActivity = trim(activity);
        String normalizedDelivery = trim(delivery).toLowerCase(Locale.US);
        String trimmedKey = trim(romExtraKey);

        if (trimmedPackage.isEmpty()) {
            problems.add(new Problem("package",
                    "Enter the emulator's app ID, for example com.example.emulator."));
        } else if (!PACKAGE.matcher(trimmedPackage).matches()) {
            problems.add(new Problem("package",
                    "\"" + trimmedPackage + "\" is not an Android app ID. It must look " +
                    "like com.example.emulator: letters, digits and underscores " +
                    "separated by dots, with at least one dot."));
        } else if (trimmedPackage.equalsIgnoreCase(trim(ownPackage))) {
            problems.add(new Problem("package",
                    "That is EmuFusion's own app ID. Choose the emulator you want " +
                    "games to open in instead."));
        }

        if (trimmedActivity.isEmpty()) {
            problems.add(new Problem("activity",
                    "Enter the emulator's launch screen, for example " +
                    ".EmulationActivity or com.example.emulator.EmulationActivity."));
        } else if (!validActivity(trimmedActivity)) {
            problems.add(new Problem("activity",
                    "\"" + trimmedActivity + "\" is not an activity name. Use the " +
                    "full class name, or a leading dot for one inside the app ID."));
        }

        if (!ExternalEmulatorDelivery.known(normalizedDelivery)) {
            problems.add(new Problem("delivery",
                    "Choose how this emulator receives a game: a file path, an open " +
                    "action, or a shared-storage link."));
        } else if (ExternalEmulatorDelivery.FILE_PATH.equals(normalizedDelivery)) {
            if (trimmedKey.isEmpty()) {
                problems.add(new Problem("romExtraKey",
                        "This emulator takes the game as a named value, so enter the " +
                        "name it expects, for example bootPath or ROM."));
            } else if (!EXTRA_KEY.matcher(trimmedKey).matches()) {
                problems.add(new Problem("romExtraKey",
                        "\"" + trimmedKey + "\" is not a valid name. Use letters, " +
                        "digits, underscores and dots only, starting with a letter."));
            }
        }

        return new CustomEmulatorSpec(trimmedPackage, trimmedActivity,
                normalizedDelivery, trimmedKey, problems);
    }

    private static boolean validActivity(String value) {
        // A leading dot means "relative to the package", exactly as Android's
        // own manifest shorthand does.
        String body = value.startsWith(".") ? value.substring(1) : value;
        if (body.isEmpty() || body.endsWith(".")) return false;
        for (String segment : body.split("\\.", -1))
            if (!CLASS_SEGMENT.matcher(segment).matches()) return false;
        return true;
    }

    public boolean valid() { return problems.isEmpty(); }

    /** Every problem at once, so the guided setup lists them all in one pass. */
    public List<Problem> problems() { return problems; }

    /** The first problem's message, or "" when the entry is valid. */
    public String firstMessage() {
        return problems.isEmpty() ? "" : problems.get(0).message();
    }

    public String packageName() { return packageName; }
    public String activity() { return activity; }
    public String delivery() { return delivery; }
    public String romExtraKey() { return romExtraKey; }

    /**
     * The activity as EmulatorCatalog needs it: relative names are resolved
     * against the package so the built {@code -n pkg/component} is always
     * unambiguous. Returns "" for an invalid entry so a rejected spec can never
     * be turned into a launch command by accident.
     */
    public String component() {
        if (!valid()) return "";
        if (activity.startsWith(".")) return packageName + activity;
        return activity.indexOf('.') < 0 ? packageName + "." + activity : activity;
    }

    private static String trim(String value) {
        return value == null ? "" : value.trim();
    }
}
