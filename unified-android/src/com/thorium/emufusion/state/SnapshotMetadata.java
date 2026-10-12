package com.thorium.emufusion.state;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.Properties;

/** Versioned, deliberately small manifest stored beside every immutable state blob. */
public final class SnapshotMetadata {
    static final int FORMAT_VERSION = 1;

    public final String snapshotId;
    public final SnapshotKind kind;
    public final StateIdentity identity;
    public final long createdAtMillis;
    public final long activePlayMillis;
    public final long uncompressedBytes;
    public final String stateSha256;
    public final long stateCrc32;
    public final boolean hasScreenshot;

    SnapshotMetadata(String snapshotId, SnapshotKind kind, StateIdentity identity,
            long createdAtMillis, long activePlayMillis, long uncompressedBytes,
            String stateSha256, long stateCrc32, boolean hasScreenshot) {
        this.snapshotId = snapshotId;
        this.kind = kind;
        this.identity = identity;
        this.createdAtMillis = createdAtMillis;
        this.activePlayMillis = activePlayMillis;
        this.uncompressedBytes = uncompressedBytes;
        this.stateSha256 = stateSha256;
        this.stateCrc32 = stateCrc32;
        this.hasScreenshot = hasScreenshot;
    }

    void write(OutputStream output) throws IOException {
        Properties values = new Properties();
        values.setProperty("format", Integer.toString(FORMAT_VERSION));
        values.setProperty("snapshotId", snapshotId);
        values.setProperty("kind", kind.name());
        values.setProperty("gameId", identity.gameId);
        values.setProperty("romSha256", identity.romSha256);
        values.setProperty("engineId", identity.engineId);
        values.setProperty("engineVersion", identity.engineVersion);
        values.setProperty("stateVersion", identity.stateVersion);
        values.setProperty("firmwareFingerprint", identity.firmwareFingerprint);
        values.setProperty("createdAtMillis", Long.toString(createdAtMillis));
        values.setProperty("activePlayMillis", Long.toString(activePlayMillis));
        values.setProperty("uncompressedBytes", Long.toString(uncompressedBytes));
        values.setProperty("stateSha256", stateSha256);
        values.setProperty("stateCrc32", Long.toString(stateCrc32));
        values.setProperty("hasScreenshot", Boolean.toString(hasScreenshot));
        values.store(output, "Lucent state manifest v" + FORMAT_VERSION);
    }

    static SnapshotMetadata read(InputStream input) throws IOException {
        Properties values = new Properties();
        values.load(input);
        int format = integer(values, "format");
        if (format != FORMAT_VERSION) throw new IOException("Unsupported state format " + format);
        try {
            StateIdentity identity = new StateIdentity(required(values, "gameId"),
                    required(values, "romSha256"), required(values, "engineId"),
                    required(values, "engineVersion"), required(values, "stateVersion"),
                    values.getProperty("firmwareFingerprint", ""));
            return new SnapshotMetadata(required(values, "snapshotId"),
                    SnapshotKind.valueOf(required(values, "kind")), identity,
                    number(values, "createdAtMillis"), number(values, "activePlayMillis"),
                    number(values, "uncompressedBytes"), required(values, "stateSha256"),
                    number(values, "stateCrc32"),
                    Boolean.parseBoolean(values.getProperty("hasScreenshot", "false")));
        } catch (IllegalArgumentException invalid) {
            throw new IOException("Invalid state manifest", invalid);
        }
    }

    private static String required(Properties values, String key) throws IOException {
        String value = values.getProperty(key);
        if (value == null || value.isEmpty()) throw new IOException("Missing " + key);
        return value;
    }

    private static long number(Properties values, String key) throws IOException {
        try { return Long.parseLong(required(values, key)); }
        catch (NumberFormatException invalid) { throw new IOException("Invalid " + key, invalid); }
    }

    private static int integer(Properties values, String key) throws IOException {
        long value = number(values, key);
        if (value > Integer.MAX_VALUE || value < Integer.MIN_VALUE)
            throw new IOException("Invalid " + key);
        return (int) value;
    }
}
