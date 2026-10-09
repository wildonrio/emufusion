package com.thorium.preview;

/** Runs against the production formatter, without Android, network, or real user data. */
public final class FeedbackDiagnosticsTest {
    public static void main(String[] args) {
        String normal = FeedbackDiagnostics.markdown("3.2.16", 90, "Nintendo Switch");
        assert normal.equals("- EmuFusion: 3.2.16 (version code 90)\n- Emulated system: switch\n");
        String[] systems = {"switch", "wiiu", "ps3", "wii", "gamecube", "ps2", "psp",
                "dreamcast", "3ds", "psx", "nds", "n64", "snes", "nes", "gb", "gbc",
                "gba", "megadrive", "gamegear", "pcenginecd"};
        for (String system : systems) assert FeedbackDiagnostics.systemCode(system).equals(system);
        String[] untrusted = {null, "", "guest@example.invalid", "/storage/roms/private-name.iso",
                "Nintendo Switch\n- Account: secret", "device-serial-123", "3.2.16-owner-name",
                "192.0.2.1", "SNES personal collection", "\\u0000", "3.2.16\n", "9999999.1"};
        for (String value : untrusted) {
            assert FeedbackDiagnostics.systemCode(value).equals("unknown");
            // An IPv4-shaped string can also be a valid four-part app version.
            // This formatter receives PackageInfo.versionName, never a network address.
            if ("192.0.2.1".equals(value)) continue;
            assert FeedbackDiagnostics.markdown(value, Long.MAX_VALUE, value).equals(
                    "- EmuFusion: unknown (version code -1)\n- Emulated system: unknown\n");
        }
        assert FeedbackDiagnostics.markdown("3.2.16", -10, "PS2").contains("version code -1");
        assert FeedbackDiagnostics.systemCode("  GAME BOY ADVANCE  ").equals("gba");
        java.util.Random random = new java.util.Random(31);
        for (int i = 0; i < 2000; i++) {
            String value = "PRIVATE_" + Long.toHexString(random.nextLong());
            String result = FeedbackDiagnostics.markdown(value, 90, value);
            assert !result.contains(value);
            assert result.equals("- EmuFusion: unknown (version code 90)\n- Emulated system: unknown\n");
        }
    }
}
