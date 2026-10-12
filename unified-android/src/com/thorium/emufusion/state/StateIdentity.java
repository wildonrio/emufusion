package com.thorium.emufusion.state;

import java.nio.charset.StandardCharsets;
import java.util.Objects;

/** Everything that must still match before an emulator state may be restored. */
public final class StateIdentity {
    public final String gameId;
    public final String romSha256;
    public final String engineId;
    public final String engineVersion;
    public final String stateVersion;
    public final String firmwareFingerprint;

    public StateIdentity(String gameId, String romSha256, String engineId,
            String engineVersion, String stateVersion, String firmwareFingerprint) {
        this.gameId = required("gameId", gameId);
        this.romSha256 = required("romSha256", romSha256).toLowerCase();
        this.engineId = required("engineId", engineId);
        this.engineVersion = required("engineVersion", engineVersion);
        this.stateVersion = required("stateVersion", stateVersion);
        this.firmwareFingerprint = firmwareFingerprint == null ? "" : firmwareFingerprint;
    }

    /** Filesystem-safe stable directory name; the display title never becomes a path. */
    public String storageKey() {
        String completeIdentity = gameId + '\n' + romSha256 + '\n' + engineId + '\n' +
                engineVersion + '\n' + stateVersion + '\n' + firmwareFingerprint;
        return Digests.sha256(completeIdentity.getBytes(StandardCharsets.UTF_8)).substring(0, 32);
    }

    public boolean matches(StateIdentity other) {
        return other != null && gameId.equals(other.gameId) &&
                romSha256.equalsIgnoreCase(other.romSha256) && engineId.equals(other.engineId) &&
                engineVersion.equals(other.engineVersion) && stateVersion.equals(other.stateVersion) &&
                firmwareFingerprint.equals(other.firmwareFingerprint);
    }

    private static String required(String name, String value) {
        if (value == null || value.trim().isEmpty())
            throw new IllegalArgumentException(name + " is required");
        return value.trim();
    }

    @Override public boolean equals(Object value) {
        if (!(value instanceof StateIdentity)) return false;
        return matches((StateIdentity) value);
    }

    @Override public int hashCode() {
        return Objects.hash(gameId, romSha256, engineId, engineVersion, stateVersion,
                firmwareFingerprint);
    }
}
