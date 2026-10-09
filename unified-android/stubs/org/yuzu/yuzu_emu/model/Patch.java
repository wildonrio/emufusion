package org.yuzu.yuzu_emu.model;

/**
 * Eden's title-patch record. Lucent ships no patch UI, but the constructor and
 * all six cached fields are resolved at load time and must match
 * common/android/id_cache.cpp exactly.
 */
public final class Patch {
    public boolean enabled;
    public String name;
    public String version;
    public int type;
    public String programId;
    public String titleId;

    public Patch(boolean enabled, String name, String version, int type,
                 String programId, String titleId, long size, int kind) {
        this.enabled = enabled;
        this.name = name;
        this.version = version;
        this.type = type;
        this.programId = programId;
        this.titleId = titleId;
    }
}
