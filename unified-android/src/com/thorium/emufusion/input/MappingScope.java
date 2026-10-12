package com.thorium.emufusion.input;

/** A game ID may be empty for a system-wide remap. */
public final class MappingScope {
    public final String systemId;
    public final String gameId;

    public MappingScope(String systemId, String gameId) {
        if (systemId == null || systemId.trim().isEmpty())
            throw new IllegalArgumentException("systemId is required");
        this.systemId = systemId.trim();
        this.gameId = gameId == null ? "" : gameId.trim();
    }

    public boolean isGameSpecific() { return !gameId.isEmpty(); }
}
