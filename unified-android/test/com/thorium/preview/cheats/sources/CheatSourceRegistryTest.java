package com.thorium.preview.cheats.sources;

import java.util.List;

/**
 * Regression proof for the LIBRETRO row's {@code systems} coverage list.
 *
 * <p>{@link CheatArchive}'s {@code SYSTEM_FOLDERS} map (in the
 * {@code com.thorium.preview.cheats} package) declares folder mappings for
 * "sg1000" and "msx", but {@link CheatSourceSlicer#libretro} — the only
 * caller that reaches {@code CheatArchive.forGame} — is only ever invoked
 * for a system once {@link CheatSourceRegistry#forSystem} has already
 * selected the LIBRETRO source for it via {@link CheatSource#covers}. If a
 * canonical id is missing from the LIBRETRO row's systems string here, its
 * SYSTEM_FOLDERS entry is unreachable dead code: {@code forSystem} never
 * returns LIBRETRO for that system, so the downloader never asks the
 * archive about it. This test pins both ids into the selection path.</p>
 */
public final class CheatSourceRegistryTest {
    public static void main(String[] args) {
        check(covers("sg1000"), "sg1000 must be covered by " + CheatSourceRegistry.LIBRETRO);
        check(covers("msx"), "msx must be covered by " + CheatSourceRegistry.LIBRETRO);
        check(covers("gba"), "gba must remain covered by " + CheatSourceRegistry.LIBRETRO);
        check(!covers("ps3"), "ps3 must not be covered by " + CheatSourceRegistry.LIBRETRO);
        System.out.println("CheatSourceRegistryTest passed");
    }

    private static boolean covers(String canonicalSystem) {
        for (CheatSource source : CheatSourceRegistry.forSystem(canonicalSystem)) {
            if (CheatSourceRegistry.LIBRETRO.equals(source.id)) return true;
        }
        return false;
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
