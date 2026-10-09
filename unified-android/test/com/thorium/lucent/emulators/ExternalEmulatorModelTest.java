package com.thorium.lucent.emulators;

import com.thorium.lucent.TestSupport;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Host coverage for the Settings route picker's platform-neutral core: what a
 * custom emulator entry is allowed to be, and how the per-system directory
 * behaves when the packaged file disagrees with itself.
 */
public final class ExternalEmulatorModelTest {
    private static final String OWN = "com.thorium.preview";

    public static void main(String[] args) {
        customAcceptsAWellFormedEntry();
        customResolvesRelativeActivities();
        customRejectsMalformedInput();
        customRefusesShellMetacharacters();
        customReportsEveryProblemAtOnce();
        deliveryVocabularyIsStable();
        directoryKeepsCatalogOrder();
        directoryDropsUnusableRows();
        directoryReportsUnsupportedSystems();
        System.out.println("ExternalEmulatorModelTest passed");
    }

    private static void customAcceptsAWellFormedEntry() {
        CustomEmulatorSpec spec = CustomEmulatorSpec.parse(
                "com.example.emulator", "com.example.emulator.EmulationActivity",
                ExternalEmulatorDelivery.FILE_PATH, "bootPath", OWN);
        TestSupport.truth(spec.valid(), "a complete entry validates");
        TestSupport.equal("com.example.emulator.EmulationActivity", spec.component(),
                "a fully qualified activity is kept as written");
        TestSupport.equal("", spec.firstMessage(), "a valid entry has no message");
    }

    private static void customResolvesRelativeActivities() {
        CustomEmulatorSpec leadingDot = CustomEmulatorSpec.parse(
                "com.example.emulator", ".EmulationActivity",
                ExternalEmulatorDelivery.ACTION_VIEW, "", OWN);
        TestSupport.truth(leadingDot.valid(), "a leading-dot activity validates");
        TestSupport.equal("com.example.emulator.EmulationActivity",
                leadingDot.component(), "leading dot resolves against the package");

        CustomEmulatorSpec bare = CustomEmulatorSpec.parse(
                "com.example.emulator", "EmulationActivity",
                ExternalEmulatorDelivery.ACTION_VIEW, "", OWN);
        TestSupport.equal("com.example.emulator.EmulationActivity", bare.component(),
                "a bare class name resolves against the package");

        // ACTION_VIEW carries the ROM as intent data, so no extra key is asked
        // for and none is required.
        TestSupport.truth(bare.valid(), "action-view needs no ROM key");
    }

    private static void customRejectsMalformedInput() {
        TestSupport.truth(!CustomEmulatorSpec.parse("", ".Main",
                ExternalEmulatorDelivery.ACTION_VIEW, "", OWN).valid(),
                "an empty package is rejected");
        TestSupport.truth(!CustomEmulatorSpec.parse("emulator", ".Main",
                ExternalEmulatorDelivery.ACTION_VIEW, "", OWN).valid(),
                "a package with no dot is rejected");
        TestSupport.truth(!CustomEmulatorSpec.parse("com.example.emulator", "",
                ExternalEmulatorDelivery.ACTION_VIEW, "", OWN).valid(),
                "an empty activity is rejected");
        TestSupport.truth(!CustomEmulatorSpec.parse("com.example.emulator", ".Main",
                "carrier-pigeon", "", OWN).valid(),
                "an unknown delivery is rejected");
        TestSupport.truth(!CustomEmulatorSpec.parse("com.example.emulator", ".Main",
                ExternalEmulatorDelivery.FILE_PATH, "", OWN).valid(),
                "file-path delivery without a ROM key is rejected");

        // Pointing a system at EmuFusion would make every launch re-enter the
        // frontend, so it is refused by name rather than left to loop.
        CustomEmulatorSpec self = CustomEmulatorSpec.parse(OWN, ".Main",
                ExternalEmulatorDelivery.ACTION_VIEW, "", OWN);
        TestSupport.truth(!self.valid(), "EmuFusion's own package is rejected");
        TestSupport.truth(self.firstMessage().contains("EmuFusion"),
                "and the refusal says so in words");

        // An invalid entry must never yield something launchable.
        TestSupport.equal("", self.component(),
                "a rejected entry produces no component");
    }

    private static void customRefusesShellMetacharacters() {
        // These values are interpolated into the am start command Pegasus runs,
        // so the validator is the boundary that keeps a settings field from
        // becoming argument injection.
        String[] hostile = {
                "com.example.emu;rm -rf /", "com.example.emu rm", "com.example.emu\"",
                "com.example.$(id)", "com.example.emu|cat", "com.example.emu&&id",
                "com.example.emu\nrm",
        };
        for (String value : hostile)
            TestSupport.truth(!CustomEmulatorSpec.parse(value, ".Main",
                    ExternalEmulatorDelivery.ACTION_VIEW, "", OWN).valid(),
                    "package rejected: " + value);
        for (String value : hostile)
            TestSupport.truth(!CustomEmulatorSpec.parse("com.example.emu", value,
                    ExternalEmulatorDelivery.ACTION_VIEW, "", OWN).valid(),
                    "activity rejected: " + value);
        for (String value : new String[] {"boot path", "boot\"path", "boot;path",
                                          "boot$path", "-boot"})
            TestSupport.truth(!CustomEmulatorSpec.parse("com.example.emu", ".Main",
                    ExternalEmulatorDelivery.FILE_PATH, value, OWN).valid(),
                    "ROM key rejected: " + value);
    }

    private static void customReportsEveryProblemAtOnce() {
        // The guided setup lists everything wrong in one pass; making the user
        // fix one field at a time is the experience this replaces.
        CustomEmulatorSpec spec = CustomEmulatorSpec.parse(
                "nodots", "not a class", ExternalEmulatorDelivery.FILE_PATH, "", OWN);
        TestSupport.equal(3, spec.problems().size(),
                "package, activity and ROM key are all reported");
        List<String> fields = new ArrayList<>();
        for (CustomEmulatorSpec.Problem problem : spec.problems()) {
            fields.add(problem.field());
            TestSupport.truth(problem.message().length() > 20,
                    "every problem explains itself: " + problem.field());
        }
        TestSupport.truth(fields.contains("package") && fields.contains("activity")
                && fields.contains("romExtraKey"), "each problem names its field");
    }

    private static void deliveryVocabularyIsStable() {
        // EmulatorCatalog aliases these exact strings; a rename here without one
        // there would make a valid custom entry unlaunchable.
        TestSupport.equal("file-path", ExternalEmulatorDelivery.FILE_PATH, "file-path id");
        TestSupport.equal("action-view", ExternalEmulatorDelivery.ACTION_VIEW,
                "action-view id");
        TestSupport.equal("content-uri", ExternalEmulatorDelivery.CONTENT_URI,
                "content-uri id");
        TestSupport.truth(!ExternalEmulatorDelivery.known("unsupported"),
                "the catalog's unsupported marker is not a delivery");
        TestSupport.truth(!ExternalEmulatorDelivery.describe(
                ExternalEmulatorDelivery.FILE_PATH).isEmpty(),
                "every delivery has wording for the picker");
    }

    private static ExternalEmulator app(String id, String name, String... packages) {
        return new ExternalEmulator(id, name, Arrays.asList(packages),
                ExternalEmulator.INSTALL_PLAY,
                "https://play.google.com/store/apps/details?id=" + packages[0], false);
    }

    private static ExternalEmulatorDirectory directory() {
        Map<String, ExternalEmulator> emulators = new LinkedHashMap<>();
        emulators.put("duckstation", app("duckstation", "DuckStation",
                "com.github.stenzek.duckstation"));
        emulators.put("epsxe", app("epsxe", "ePSXe", "com.epsxe.ePSXe"));
        emulators.put("retroarch", app("retroarch", "RetroArch",
                "com.retroarch.aarch64", "com.retroarch"));
        Map<String, List<String[]>> systems = new LinkedHashMap<>();
        systems.put("psx", Arrays.asList(
                new String[] {"duckstation", "duckstation"},
                new String[] {"epsxe", "epsxe"},
                new String[] {"retroarch-psx", "retroarch"},
                new String[] {"ghost-emulator", "ghost-emulator"}));
        Map<String, String> unsupported = new LinkedHashMap<>();
        unsupported.put("xbox", "Xemu has no Android port.");
        return ExternalEmulatorDirectory.of(emulators, systems, unsupported);
    }

    private static void directoryKeepsCatalogOrder() {
        ExternalEmulatorDirectory directory = directory();
        List<ExternalEmulatorDirectory.Choice> psx = directory.forSystem("psx");
        TestSupport.equal(3, psx.size(), "the unknown emulator is not offered");
        TestSupport.equal("duckstation", psx.get(0).optionId(), "first option is first");
        TestSupport.equal("epsxe", psx.get(1).optionId(), "order is preserved");

        // One app, many per-system options: the option id is what gets stored,
        // the app is what the user recognises and installs.
        ExternalEmulatorDirectory.Choice retroarch = psx.get(2);
        TestSupport.equal("retroarch-psx", retroarch.optionId(),
                "the catalog option id is kept for binding");
        TestSupport.equal("RetroArch", retroarch.emulator().name(),
                "and the app supplies the name shown");
        TestSupport.equal("com.retroarch.aarch64",
                retroarch.emulator().primaryPackage(),
                "the install target is the app's first package");

        TestSupport.truth(directory.choice("psx", "epsxe") != null,
                "a listed option is findable by id");
        TestSupport.truth(directory.choice("psx", "nothing-here") == null,
                "an unlisted option is not");
    }

    private static void directoryDropsUnusableRows() {
        Map<String, ExternalEmulator> emulators = new LinkedHashMap<>();
        // Incomplete rows must never reach the picker as blank buttons.
        emulators.put("nameless", new ExternalEmulator("nameless", "",
                Arrays.asList("com.example.a"), ExternalEmulator.INSTALL_PLAY,
                "https://example.invalid", false));
        emulators.put("packageless", new ExternalEmulator("packageless", "No Package",
                new ArrayList<String>(), ExternalEmulator.INSTALL_PLAY,
                "https://example.invalid", false));
        Map<String, List<String[]>> systems = new LinkedHashMap<>();
        systems.put("psx", Arrays.asList(new String[] {"nameless", "nameless"},
                new String[] {"packageless", "packageless"}));
        ExternalEmulatorDirectory directory =
                ExternalEmulatorDirectory.of(emulators, systems, null);
        TestSupport.truth(directory.forSystem("psx").isEmpty(),
                "incomplete rows are dropped");
        // A system left with nothing has no entry at all, so the caller falls
        // back to EmulatorCatalog rather than showing an empty list.
        TestSupport.truth(directory.isEmpty(), "and the system is then unlisted");

        TestSupport.truth(ExternalEmulatorDirectory.empty()
                .forSystem("psx").isEmpty(), "an empty directory offers nothing");
        TestSupport.equal("", ExternalEmulatorDirectory.empty()
                .unsupportedReason("xbox"), "and claims nothing about a system");
    }

    private static void directoryReportsUnsupportedSystems() {
        ExternalEmulatorDirectory directory = directory();
        TestSupport.equal("Xemu has no Android port.",
                directory.unsupportedReason("xbox"),
                "an optionless system explains itself");
        TestSupport.equal("", directory.unsupportedReason("psx"),
                "a served system has no such reason");
        // Lookups are case- and whitespace-insensitive so a folder name read
        // from disk lands on the same row as a canonical id.
        TestSupport.equal("Xemu has no Android port.",
                directory.unsupportedReason("  XBOX "),
                "system lookup normalizes");
    }
}
