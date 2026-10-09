package org.yuzu.yuzu_emu.model;

/**
 * Eden's game record. Lucent never reads one — its own library owns metadata —
 * but Eden's JNI cache resolves the constructor and all six fields at load
 * time, so the shape has to exist exactly as declared in
 * common/android/id_cache.cpp.
 */
public final class Game {
    public String title;
    public String path;
    public String programId;
    public String developer;
    public String version;
    public boolean isHomebrew;

    public Game(String title, String path, String programId, String developer,
                String version, boolean isHomebrew) {
        this.title = title;
        this.path = path;
        this.programId = programId;
        this.developer = developer;
        this.version = version;
        this.isHomebrew = isHomebrew;
    }
}
