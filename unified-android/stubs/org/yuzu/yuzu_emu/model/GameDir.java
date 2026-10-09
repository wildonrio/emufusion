package org.yuzu.yuzu_emu.model;

/**
 * Eden's scanned-directory record. Lucent supplies content paths directly, so
 * nothing here is consulted; the constructor exists because Eden's JNI cache
 * resolves it during load.
 */
public final class GameDir {
    public String uriString;
    public boolean deepScan;

    public GameDir(String uriString, boolean deepScan) {
        this.uriString = uriString;
        this.deepScan = deepScan;
    }
}
