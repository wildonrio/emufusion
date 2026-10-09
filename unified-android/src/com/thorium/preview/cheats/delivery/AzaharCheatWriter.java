package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Azahar's Gateway cheat file: {@code <user dir>/cheats/<TITLEID>.txt}.
 *
 * <p>The libretro build sets its user directory to {@code <save dir>/Azahar/}
 * (citra_libretro/core_settings.cpp), so the file lives under EmuFusion's
 * per-game save directory. A cheat is on when its block carries the
 * {@code *citra_enabled} marker line the loader looks for; only enabled rows
 * are written, so the file is exactly the active set.
 */
public final class AzaharCheatWriter implements BootCheatWriter {
    static final String ENABLED_MARKER = "*citra_enabled";

    @Override public List<File> write(BootCheatRequest request) throws IOException {
        List<File> touched = new ArrayList<>();
        String titleId = titleId(request);
        if (titleId.isEmpty() || request.gameSaveDirectory == null) return touched;
        File file = new File(request.gameSaveDirectory, "Azahar/cheats/" + titleId + ".txt");
        String text = render(request);
        if (text == null) {
            if (OwnedFiles.remove(file, OwnedFiles.Ownership.CREATED)) touched.add(file);
            return touched;
        }
        if (OwnedFiles.write(file, text, OwnedFiles.Ownership.CREATED)) touched.add(file);
        return touched;
    }

    static String titleId(BootCheatRequest request) {
        String id = CheatCodeText.titleId16(request.identity("titleId"));
        return id.isEmpty() ? CheatCodeText.titleId16(request.contentStem) : id;
    }

    static String render(BootCheatRequest request) {
        StringBuilder out = new StringBuilder();
        Set<String> used = new HashSet<>();
        int written = 0;
        for (DeliveryCheat row : request.enabled()) {
            List<String> body = body(row);
            if (body == null) continue;
            String name = CheatCodeText.uniqueName(CheatCodeText.safeName(row.cheat.name, 96), used);
            out.append('[').append(name).append("]\n");
            out.append(ENABLED_MARKER).append('\n');
            for (String line : body) out.append(line).append('\n');
            out.append('\n');
            written++;
        }
        return written == 0 ? null : out.toString();
    }

    static List<String> body(DeliveryCheat row) {
        List<String> body = new ArrayList<>();
        for (String line : CheatCodeText.lines(row.cheat.code)) {
            String pair = CheatCodeText.hexPair(line);
            if (pair == null) return null;
            body.add(pair);
        }
        return body.isEmpty() ? null : body;
    }
}
