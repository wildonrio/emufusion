package com.thorium.preview.game;

/** Covers which driver package each GPU receives ({@link GpuDriverTable}). */
public final class GpuDriverTableTest {
    public static void main(String[] args) {
        parsing();
        choices();
        qualcommNeverDowngrades();
        pins();
        System.out.println("GpuDriverTableTest passed");
    }

    private static void parsing() {
        expectEquals(740, GpuDriverTable.adrenoModel("Adreno (TM) 740"));
        expectEquals(830, GpuDriverTable.adrenoModel("Adreno (TM) 830"));
        expectEquals(650, GpuDriverTable.adrenoModel("Adreno 650"));
        // Axx parts (e.g. AYANEO Pocket S2) have no pinned recommendation.
        expectEquals(0, GpuDriverTable.adrenoModel("Adreno (TM) A32"));
        expectEquals(0, GpuDriverTable.adrenoModel("Mali-G720-Immortalis MC12"));
        expectEquals(0, GpuDriverTable.adrenoModel(""));
        expectEquals(0, GpuDriverTable.adrenoModel(null));
        expectEquals(676, GpuDriverTable.qualcommVersion(
                "OpenGL ES 3.2 V@0676.53 (GIT@69e13475cb, I1df7ad3aa9, 1703680572) (Date:12/27/23)"));
        expectEquals(842, GpuDriverTable.qualcommVersion("OpenGL ES 3.2 V@0842.8"));
        expectEquals(0, GpuDriverTable.qualcommVersion("OpenGL ES 3.2 v1.r48p0"));
        expectEquals(0, GpuDriverTable.qualcommVersion(null));
    }

    private static void choices() {
        String stock = "OpenGL ES 3.2 V@0676.53";
        // The Thor (QCS8550).
        expectEquals("turnip-mrpurple-t23", id("Adreno (TM) 740", stock));
        expectEquals("turnip-mrpurple-t23", id("Adreno (TM) 750", stock));
        expectEquals("turnip-mrpurple-t23", id("Adreno (TM) 730", stock));
        expectEquals("turnip-kimchi-25.2.0-r5", id("Adreno (TM) 710", stock));
        expectEquals("turnip-mrpurple-t19", id("Adreno (TM) 660", stock));
        expectEquals("turnip-mrpurple-t19", id("Adreno (TM) 650", stock));
        expectEquals("turnip-mrpurple-eol-24.3.4", id("Adreno (TM) 619", stock));
        expectEquals("qualcomm-gamehub-842.8", id("Adreno (TM) 830", stock));
        expectEquals(null, id("Adreno (TM) 540", stock));
        expectEquals(null, id("Adreno (TM) 950", stock));
        expectEquals(null, id("Mali-G715", "OpenGL ES 3.2 v1.r44p1"));
        expectEquals(null, id("Adreno (TM) A32", stock));
    }

    private static void qualcommNeverDowngrades() {
        expectEquals("qualcomm-gamehub-842.8", id("Adreno (TM) 830", "OpenGL ES 3.2 V@0800.51"));
        expectEquals(null, id("Adreno (TM) 830", "OpenGL ES 3.2 V@0842.8"));
        expectEquals(null, id("Adreno (TM) 840", "OpenGL ES 3.2 V@0910.2"));
        // Turnip is not a version of the Qualcomm driver: no such guard.
        expectEquals("turnip-mrpurple-t23", id("Adreno (TM) 740", "OpenGL ES 3.2 V@0910.2"));
    }

    private static void pins() {
        for (GpuDriverTable.DriverPackage p : GpuDriverTable.PACKAGES) {
            expect(p.url.startsWith("https://github.com/"), p.id + " url");
            expect(p.sha256.matches("[0-9a-f]{64}"), p.id + " sha256");
            expect(p.bytes > 0 && p.bytes < 64L * 1024 * 1024, p.id + " size");
            expect(p.library.endsWith(".so") && !p.library.contains("/"), p.id + " library");
        }
    }

    private static String id(String renderer, String version) {
        GpuDriverTable.DriverPackage p = GpuDriverTable.choose(renderer, version);
        return p == null ? null : p.id;
    }

    private static void expect(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void expectEquals(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual))
            throw new AssertionError("expected " + expected + " but was " + actual);
    }
}
