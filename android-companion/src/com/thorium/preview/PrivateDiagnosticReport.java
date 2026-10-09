package com.thorium.preview;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** A closed vocabulary, not a log-redaction pipeline. No arbitrary text is serialized. */
public final class PrivateDiagnosticReport {
    private static final Set<String> SYSTEMS = new HashSet<>(Arrays.asList(
            "switch", "wiiu", "ps3", "wii", "gamecube", "ps2", "psp", "dreamcast",
            "3ds", "psx", "nds", "n64", "snes", "nes", "gb", "gbc", "gba",
            "megadrive", "gamegear", "pcenginecd"));
    public final int build;
    public final String system, event, bucket;

    private PrivateDiagnosticReport(int build, String system, String event, String bucket) {
        this.build = build;
        this.system = system;
        this.event = event;
        this.bucket = bucket;
    }

    public static PrivateDiagnosticReport create(int build, String system, String event, String bucket) {
        if (build <= 0 || !SYSTEMS.contains(system) || event == null || bucket == null) return null;
        boolean valid;
        switch (event) {
            case "engine_ready": valid = bucket.equals("ok"); break;
            case "launch_failed": case "runtime_failed":
                valid = Arrays.asList("missing_firmware", "unsupported_gpu", "invalid_content",
                        "out_of_memory", "unknown").contains(bucket); break;
            case "unexpected_exit":
                valid = Arrays.asList("java", "native", "anr", "out_of_memory",
                        "process_death", "unknown").contains(bucket); break;
            case "audio_starvation": case "frame_deadline_miss":
                valid = Arrays.asList("1_9", "10_99", "100_plus").contains(bucket); break;
            default: valid = false;
        }
        return valid ? new PrivateDiagnosticReport(build, system, event, bucket) : null;
    }

    static PrivateDiagnosticReport fromKey(String key) {
        if (key == null || key.length() > 100) return null;
        String[] parts = key.split("\\|", -1);
        if (parts.length != 4 || !parts[0].matches("[1-9][0-9]{0,9}")) return null;
        try { return create(Integer.parseInt(parts[0]), parts[1], parts[2], parts[3]); }
        catch (NumberFormatException ignored) { return null; }
    }

    String key() { return build + "|" + system + "|" + event + "|" + bucket; }

    public byte[] body() {
        // All strings came from exact allowlists above; no untrusted escaping channel.
        return ("{\"schema\":1,\"build\":" + build + ",\"system\":\"" + system +
                "\",\"event\":\"" + event + "\",\"bucket\":\"" + bucket + "\"}")
                .getBytes(StandardCharsets.UTF_8);
    }
}
