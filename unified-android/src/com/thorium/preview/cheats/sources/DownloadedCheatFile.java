package com.thorium.preview.cheats.sources;

import android.content.Context;

import com.thorium.lucent.cheats.Cheat;

import java.io.File;
import java.io.IOException;
import java.util.List;
import java.util.Map;

/**
 * Where the update step leaves each game's downloaded cheats, and how the
 * runtime reads them back.
 *
 * <p>Path: {@code files/cheats/downloaded/<canonicalSystem>/<normalised stem>.json}.
 * The stem is normalised with {@link CheatDatabase#normalise} because that is
 * the key both the running engine and the library use to find a game, so a
 * file written from the ROM's file name resolves for a launch that only knows
 * the ROM path. The Android-free logic lives in {@link DownloadedCheatCodec};
 * this class only binds it to the app's files directory.
 */
public final class DownloadedCheatFile {
    public static final String DIRECTORY = "downloaded";

    private DownloadedCheatFile() {}

    public static File directory(Context context) {
        return new File(new File(context.getApplicationContext().getFilesDir(), "cheats"), DIRECTORY);
    }

    public static File pathFor(Context context, String canonicalSystem, String titleOrStem) {
        return pathFor(directory(context), canonicalSystem, titleOrStem);
    }

    /** The same derivation without a {@link Context}; host tests and the codec share it. */
    public static File pathFor(File downloadedDirectory, String canonicalSystem, String titleOrStem) {
        return DownloadedCheatCodec.pathFor(downloadedDirectory, canonicalSystem, titleOrStem);
    }

    /** Empty on absence or corruption; descriptions carry provenance and delivery. */
    public static List<Cheat> read(File file) { return DownloadedCheatCodec.read(file); }

    public static List<DownloadedCheat> readDetailed(File file) {
        return DownloadedCheatCodec.readDetailed(file);
    }

    /** For example serial, crc, gameId, titleId, buildIds (comma-separated), productId. */
    public static Map<String, String> readIdentity(File file) {
        return DownloadedCheatCodec.readIdentity(file);
    }

    /** Atomic: the document lands whole or not at all. */
    public static void write(File file, DownloadedCheatDocument document) throws IOException {
        DownloadedCheatCodec.write(file, document);
    }
}
