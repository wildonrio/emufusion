package com.thorium.lucent.emulators;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * The per-system, ordered list of external emulators the Settings picker
 * offers, as loaded from engines/external-emulators.json.
 *
 * Two ids per choice because they are genuinely different things: {@code
 * option} is the EmulatorCatalog entry that owns the launch recipe and is what
 * gets persisted, while {@code app} names the emulator application the user
 * recognises and installs. They differ only where one app hosts many systems —
 * RetroArch is option {@code retroarch-psx} but app {@code retroarch} — and
 * collapsing them would either lose the per-system core or list "RetroArch"
 * thirty times as if they were thirty different downloads.
 */
public final class ExternalEmulatorDirectory {

    /** One offered row: which catalog option to bind, and which app it is. */
    public static final class Choice {
        private final String optionId;
        private final ExternalEmulator emulator;

        public Choice(String optionId, ExternalEmulator emulator) {
            this.optionId = optionId == null ? "" : optionId;
            this.emulator = emulator;
        }

        /** The EmulatorCatalog option id persisted by EngineRouteStore. */
        public String optionId() { return optionId; }

        /** The application shown, installed and link-checked. */
        public ExternalEmulator emulator() { return emulator; }
    }

    private final Map<String, List<Choice>> bySystem;
    private final Map<String, String> unsupported;

    private ExternalEmulatorDirectory(Map<String, List<Choice>> bySystem,
                                      Map<String, String> unsupported) {
        this.bySystem = Collections.unmodifiableMap(bySystem);
        this.unsupported = Collections.unmodifiableMap(unsupported);
    }

    /** An empty directory. A missing or damaged asset degrades to this. */
    public static ExternalEmulatorDirectory empty() {
        return new ExternalEmulatorDirectory(
                new LinkedHashMap<String, List<Choice>>(),
                new LinkedHashMap<String, String>());
    }

    /**
     * Builds a directory from already-parsed rows. Choices naming an emulator
     * that is absent or incomplete are dropped rather than shown as a blank
     * row, and a system left with nothing simply has no entry — the caller then
     * falls back to EmulatorCatalog, which can still launch.
     */
    public static ExternalEmulatorDirectory of(
            Map<String, ExternalEmulator> emulators,
            Map<String, List<String[]>> systemChoices,
            Map<String, String> unsupportedReasons) {
        LinkedHashMap<String, List<Choice>> bySystem = new LinkedHashMap<>();
        if (systemChoices != null) {
            for (Map.Entry<String, List<String[]>> entry : systemChoices.entrySet()) {
                String system = normalize(entry.getKey());
                if (system.isEmpty() || entry.getValue() == null) continue;
                List<Choice> choices = new ArrayList<>();
                for (String[] pair : entry.getValue()) {
                    if (pair == null || pair.length == 0) continue;
                    String optionId = normalize(pair[0]);
                    String appId = pair.length > 1 && pair[1] != null && !pair[1].isEmpty()
                            ? normalize(pair[1]) : optionId;
                    ExternalEmulator emulator =
                            emulators == null ? null : emulators.get(appId);
                    if (optionId.isEmpty() || emulator == null || !emulator.usable())
                        continue;
                    choices.add(new Choice(optionId, emulator));
                }
                if (!choices.isEmpty())
                    bySystem.put(system, Collections.unmodifiableList(choices));
            }
        }
        LinkedHashMap<String, String> unsupported = new LinkedHashMap<>();
        if (unsupportedReasons != null) {
            for (Map.Entry<String, String> entry : unsupportedReasons.entrySet()) {
                String system = normalize(entry.getKey());
                String reason = entry.getValue() == null ? "" : entry.getValue().trim();
                if (!system.isEmpty() && !reason.isEmpty())
                    unsupported.put(system, reason);
            }
        }
        return new ExternalEmulatorDirectory(bySystem, unsupported);
    }

    /** Ordered choices for a canonical system; empty when none are listed. */
    public List<Choice> forSystem(String system) {
        List<Choice> choices = bySystem.get(normalize(system));
        return choices == null ? Collections.<Choice>emptyList() : choices;
    }

    /** The recorded choice for a catalog option id, or null. */
    public Choice choice(String system, String optionId) {
        String wanted = normalize(optionId);
        for (Choice choice : forSystem(system))
            if (choice.optionId().equals(wanted)) return choice;
        return null;
    }

    /**
     * Why a system is offered no external emulator at all, or "" when it is
     * either supported or simply unlisted. Shown verbatim in Settings so
     * "External" is never an empty dead end the user has to guess about.
     */
    public String unsupportedReason(String system) {
        String reason = unsupported.get(normalize(system));
        return reason == null ? "" : reason;
    }

    public boolean isEmpty() { return bySystem.isEmpty(); }

    private static String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.US);
    }
}
