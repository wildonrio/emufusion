package com.thorium.lucent.metadata;

import com.thorium.lucent.TestSupport;

public final class MetadataLaunchNormalizerTest {
    public static void main(String[] arguments) {
        restoresMissingLaunchPerCollection();
        replacesAndDeduplicatesCollectionLaunches();
        removesUnsupportedCollectionAndGameRoutes();
        removesStaleGameOverrideWhenInternalRouteWins();
    }

    private static String route(String system) {
        return "psp".equals(system) ? "lucent --system psp" :
                "dreamcast".equals(system) ? "lucent --system dreamcast" : "";
    }

    private static void restoresMissingLaunchPerCollection() {
        String input = "collection: PSP\nshortname: psp\ngame: One\nfile: one.iso\n" +
                "collection: Dreamcast\nshortname: dreamcast\ngame: Two\nfile: two.cdi\n";
        String output = MetadataLaunchNormalizer.rewrite(
                input, MetadataLaunchNormalizerTest::route);
        TestSupport.truth(output.contains(
                "shortname: psp\nlaunch: lucent --system psp\ngame: One"),
                "PSP launch must be restored");
        TestSupport.truth(output.contains(
                "shortname: dreamcast\nlaunch: lucent --system dreamcast\ngame: Two"),
                "Dreamcast launch must be restored");
        TestSupport.equal(2, count(output, "launch: lucent"),
                "each supported collection gets one route");
    }

    private static void replacesAndDeduplicatesCollectionLaunches() {
        String input = "collection: PSP\nshortname: psp\nlaunch: old-one\n" +
                "launch: old-two\ngame: One\nfile: one.iso\n";
        String output = MetadataLaunchNormalizer.rewrite(
                input, MetadataLaunchNormalizerTest::route);
        TestSupport.equal(1, count(output, "launch:"),
                "duplicate collection launches must collapse");
        TestSupport.truth(output.contains("launch: lucent --system psp"),
                "current route must replace stale routes");
        TestSupport.truth(!output.contains("old-one") && !output.contains("old-two"),
                "stale routes must be gone");
    }

    private static void removesUnsupportedCollectionAndGameRoutes() {
        String input = "collection: Saturn\nshortname: saturn\nlaunch: external\n" +
                "game: One\nlaunch: game-specific\nfile: one.chd\n";
        String output = MetadataLaunchNormalizer.rewrite(
                input, MetadataLaunchNormalizerTest::route);
        TestSupport.truth(!output.contains("launch: external"),
                "unsupported collection route must be removed");
        TestSupport.truth(!output.contains("launch: game-specific"),
                "unsupported game-level route must be removed");
    }

    private static void removesStaleGameOverrideWhenInternalRouteWins() {
        String input = "collection: PSP\nshortname: psp\nlaunch: old-external\n" +
                "game: One\nlaunch: standalone-one\nfile: one.iso\n" +
                "game: Two\nlaunch: standalone-two\nfile: two.iso\n";
        String output = MetadataLaunchNormalizer.rewrite(
                input, MetadataLaunchNormalizerTest::route);
        TestSupport.equal(1, count(output, "launch:"),
                "only the authoritative collection route may remain");
        TestSupport.truth(output.contains("launch: lucent --system psp"),
                "internal collection route must win");
        TestSupport.truth(!output.contains("standalone-one") &&
                        !output.contains("standalone-two"),
                "stale per-game external overrides must be gone");
    }

    private static int count(String value, String needle) {
        int total = 0;
        int cursor = 0;
        while ((cursor = value.indexOf(needle, cursor)) >= 0) {
            total++;
            cursor += needle.length();
        }
        return total;
    }
}
