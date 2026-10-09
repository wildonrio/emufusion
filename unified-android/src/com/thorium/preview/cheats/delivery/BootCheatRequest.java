package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Everything a {@link BootCheatWriter} needs, as plain data.
 *
 * <p>No Context, no session: the writers are proven on the host against
 * temporary directories, and the Android layer ({@code CheatLaunchHooks})
 * does nothing but fill this in.
 */
public final class BootCheatRequest {
    public final String engineId;
    public final String systemId;
    public final String gameTitle;
    /** The content file name without directory or extension. */
    public final String contentStem;
    /** {@code engine-system/<engineId>}: what the core sees as its system directory. */
    public final File engineRoot;
    /** The per-game save directory the core sees, or null when the engine has none. */
    public final File gameSaveDirectory;
    /** serial, crc, gameId, titleId, buildIds, productId, discId, appVersion, ... */
    public final Map<String, String> identity;
    public final List<DeliveryCheat> cheats;
    public final Set<String> enabledIds;

    public BootCheatRequest(String engineId, String systemId, String gameTitle,
                            String contentStem, File engineRoot, File gameSaveDirectory,
                            Map<String, String> identity, List<DeliveryCheat> cheats,
                            Set<String> enabledIds) {
        if (engineRoot == null) throw new IllegalArgumentException("engine root required");
        this.engineId = clean(engineId);
        this.systemId = clean(systemId);
        this.gameTitle = clean(gameTitle);
        this.contentStem = clean(contentStem);
        this.engineRoot = engineRoot;
        this.gameSaveDirectory = gameSaveDirectory;
        Map<String, String> copy = new LinkedHashMap<>();
        if (identity != null) {
            for (Map.Entry<String, String> entry : identity.entrySet()) {
                if (entry.getKey() == null || entry.getValue() == null) continue;
                String value = entry.getValue().trim();
                if (!value.isEmpty()) copy.put(entry.getKey().trim(), value);
            }
        }
        this.identity = Collections.unmodifiableMap(copy);
        this.cheats = Collections.unmodifiableList(
                cheats == null ? new ArrayList<DeliveryCheat>() : new ArrayList<>(cheats));
        this.enabledIds = Collections.unmodifiableSet(
                enabledIds == null ? new LinkedHashSet<String>() : new LinkedHashSet<>(enabledIds));
    }

    public String identity(String key) {
        String value = identity.get(key);
        return value == null ? "" : value;
    }

    public boolean isEnabled(DeliveryCheat cheat) {
        return cheat != null && enabledIds.contains(cheat.cheat.id);
    }

    /** Rows switched on, in catalogue order. */
    public List<DeliveryCheat> enabled() {
        List<DeliveryCheat> rows = new ArrayList<>();
        for (DeliveryCheat cheat : cheats) if (isEnabled(cheat)) rows.add(cheat);
        return rows;
    }

    public BootCheatRequest withEnabledIds(Set<String> ids) {
        return new BootCheatRequest(engineId, systemId, gameTitle, contentStem, engineRoot,
                gameSaveDirectory, identity, cheats, ids);
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
