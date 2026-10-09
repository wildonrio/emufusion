package com.thorium.preview.cheats.sources;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** One upstream cheat collection the device may fetch on the owner's behalf. */
public final class CheatSource {
    public final String id;
    public final String name;
    /** Bulk archive URL, or a template with {@code <GAMEID>} for per-game sources. */
    public final String url;
    /** A second URL the source needs (Switch build ids, MAME version pointer). */
    public final String auxiliaryUrl;
    public final String license;
    public final String keyedBy;
    public final String format;
    public final List<String> systems;
    /** Copied into the APK or the repository. Always false for device-fetched sources. */
    public final boolean bundled;
    /** Whether EmuFusion may redistribute the data. Always false for device-fetched sources. */
    public final boolean redistribution;
    /** Fetched once per game (URL template) rather than once per source. */
    public final boolean perGame;
    /** Already installed by the update session; nothing is fetched here. */
    public final boolean installedLocally;
    public final boolean enabledByDefault;
    public final long maxBytes;

    CheatSource(String id, String name, String url, String auxiliaryUrl, String license,
                String keyedBy, String format, String systems, boolean perGame,
                boolean installedLocally, long maxBytes) {
        this.id = id;
        this.name = name;
        this.url = url;
        this.auxiliaryUrl = auxiliaryUrl == null ? "" : auxiliaryUrl;
        this.license = license;
        this.keyedBy = keyedBy;
        this.format = format;
        this.systems = Collections.unmodifiableList(Arrays.asList(systems.trim().split("\\s+")));
        this.bundled = false;
        this.redistribution = false;
        this.perGame = perGame;
        this.installedLocally = installedLocally;
        this.enabledByDefault = true;
        this.maxBytes = maxBytes;
    }

    public boolean covers(String canonicalSystem) {
        return canonicalSystem != null && systems.contains(canonicalSystem);
    }

    @Override public String toString() { return "CheatSource{" + id + "}"; }
}
