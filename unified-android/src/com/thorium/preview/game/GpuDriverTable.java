package com.thorium.preview.game;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Which adrenotools driver package suits a GPU: the pure half of
 * {@link GpuDriverProvisioner}, host-tested without an Android Context.
 */
final class GpuDriverTable {
    /** One pinned adrenotools package (meta.json plus the driver library). */
    static final class DriverPackage {
        final String id;
        final int minAdreno;
        final int maxAdreno;
        final String url;
        final long bytes;
        final String sha256;
        final String library;
        /** Qualcomm driver major version ("V@0842"), 0 for Mesa Turnip. */
        final int qualcommVersion;

        DriverPackage(String id, int minAdreno, int maxAdreno, String url, long bytes,
                      String sha256, String library, int qualcommVersion) {
            this.id = id;
            this.minAdreno = minAdreno;
            this.maxAdreno = maxAdreno;
            this.url = url;
            this.bytes = bytes;
            this.sha256 = sha256;
            this.library = library;
            this.qualcommVersion = qualcommVersion;
        }
    }

    /**
     * Eden's own recommendation per Adreno range (DriverFetcherFragment
     * driverMap, unchanged on upstream master as of October 2026). Eden names
     * "GameHub Adreno 8xx" without a version; 842.8 is that repository's
     * newest. The Axx range ("KIMCHI Latest") is a moving target, not a pin.
     */
    static final DriverPackage[] PACKAGES = {
            new DriverPackage("turnip-mrpurple-eol-24.3.4", 600, 639,
                    "https://github.com/MrPurple666/purple-turnip/releases/download/"
                            + "vturnip_mrpurple-EOL-24.3.4.adpkg/turnip_mrpurple-EOL-24.3.4.adpkg.zip",
                    2095320L, "75851eecca564946ed23e20a321a1f3ab1112697d7e0ea045e585990ded9c293",
                    "vulkan.purple.so", 0),
            new DriverPackage("turnip-mrpurple-t19", 640, 699,
                    "https://github.com/MrPurple666/purple-turnip/releases/download/"
                            + "vturnip_mrpurple-T19-toasted.adpkg/turnip_mrpurple-T19-toasted.adpkg.zip",
                    2424925L, "0963287dfccb08f60f9bcb6810d58a507f9a48a8dbb15aaf3de223595cf3bcb1",
                    "vulkan.purple.so", 0),
            new DriverPackage("turnip-kimchi-25.2.0-r5", 700, 710,
                    "https://github.com/K11MCH1/AdrenoToolsDrivers/releases/download/"
                            + "v25.2.0-rc.05/turnip_v25.2.0_R5_auto.zip",
                    3201634L, "ed170aabc3c771d8688fd5e1d5e49a84f53b64671bf075f2b2cb127575f01556",
                    "vulkan.ad07xx.so", 0),
            new DriverPackage("turnip-mrpurple-t23", 711, 799,
                    "https://github.com/MrPurple666/purple-turnip/releases/download/"
                            + "vturnip_mrpurple_T23-toasted.adpkg/turnip_mrpurple_T23-toasted.adpkg.zip",
                    3558070L, "5d290bc1421af9fbe30ca35afa9e28bb27f03daf3648203afe83a34e56620b82",
                    "vulkan.purple.so", 0),
            new DriverPackage("qualcomm-gamehub-842.8", 800, 899,
                    "https://github.com/crueter/GameHub-8Elite-Drivers/releases/download/"
                            + "842.8/adreno-driver-842.8.zip",
                    13235821L, "b63567c51651043ab0afa55758261d7540364eb123e046b6afe9efed17ad2a57",
                    "vulkan.adreno.so", 842),
    };

    private static final Pattern ADRENO = Pattern.compile("Adreno(?:\\s*\\(TM\\))?\\s+(A?)(\\d+)");
    private static final Pattern QUALCOMM_VERSION = Pattern.compile("V@0*(\\d+)");

    /** Adreno model number, or 0 for a non-Adreno or an Axx-series renderer. */
    static int adrenoModel(String glRenderer) {
        if (glRenderer == null) return 0;
        Matcher m = ADRENO.matcher(glRenderer);
        if (!m.find() || !m.group(1).isEmpty()) return 0;
        try { return Integer.parseInt(m.group(2)); }
        catch (NumberFormatException e) { return 0; }
    }

    /** Stock Qualcomm driver major version from GL_VERSION, or 0 when absent. */
    static int qualcommVersion(String glVersion) {
        if (glVersion == null) return 0;
        Matcher m = QUALCOMM_VERSION.matcher(glVersion);
        if (!m.find()) return 0;
        try { return Integer.parseInt(m.group(1)); }
        catch (NumberFormatException e) { return 0; }
    }

    /** The package for this GPU, or null to keep the system driver. */
    static DriverPackage choose(String glRenderer, String glVersion) {
        int model = adrenoModel(glRenderer);
        if (model == 0) return null;
        for (DriverPackage candidate : PACKAGES) {
            if (model < candidate.minAdreno || model > candidate.maxAdreno) continue;
            int stock = qualcommVersion(glVersion);
            if (candidate.qualcommVersion > 0 && stock >= candidate.qualcommVersion) return null;
            return candidate;
        }
        return null;
    }

    private GpuDriverTable() {}
}
