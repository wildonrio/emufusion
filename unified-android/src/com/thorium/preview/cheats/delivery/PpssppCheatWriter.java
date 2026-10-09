package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * PPSSPP's CWCheat file: {@code <memstick>/PSP/Cheats/<DISCID>.ini}.
 *
 * <p>The libretro build mounts the frontend's save directory as the memory
 * stick, so the file lives in EmuFusion's per-game save directory. Every
 * row is written, {@code _C1} for enabled and {@code _C0} for disabled, in
 * the {@code _L 0xADDR 0xVALUE} form the engine parses. The core keeps the
 * codes running only while {@code ppsspp_cheats} is enabled, and its own
 * live path rewrites this same file, which is why the ownership rule here
 * is {@link OwnedFiles.Ownership#CREATED} rather than exact.
 */
public final class PpssppCheatWriter implements BootCheatWriter {

    @Override public List<File> write(BootCheatRequest request) throws IOException {
        List<File> touched = new ArrayList<>();
        String discId = discId(request);
        if (discId.isEmpty() || request.gameSaveDirectory == null) return touched;
        File file = new File(request.gameSaveDirectory, "PSP/Cheats/" + discId + ".ini");
        if (request.cheats.isEmpty()) {
            if (OwnedFiles.remove(file, OwnedFiles.Ownership.CREATED)) touched.add(file);
            return touched;
        }
        if (OwnedFiles.write(file, render(request, discId), OwnedFiles.Ownership.CREATED))
            touched.add(file);
        return touched;
    }

    static String discId(BootCheatRequest request) {
        for (String key : new String[] {"discId", "serial", "gameId"}) {
            String value = CheatCodeText.serialCompact(request.identity(key));
            if (!value.isEmpty()) return value;
        }
        return CheatCodeText.serialCompact(request.contentStem);
    }

    static String render(BootCheatRequest request, String discId) {
        StringBuilder out = new StringBuilder();
        out.append("_S ").append(discId).append('\n');
        if (!request.gameTitle.isEmpty())
            out.append("_G ").append(CheatCodeText.singleLine(request.gameTitle, 96)).append('\n');
        Set<String> used = new HashSet<>();
        for (DeliveryCheat row : request.cheats) {
            List<String> body = body(row);
            if (body == null) continue;
            String name = CheatCodeText.uniqueName(CheatCodeText.safeName(row.cheat.name, 96), used);
            out.append(request.isEnabled(row) ? "_C1 " : "_C0 ").append(name).append('\n');
            for (String line : body) out.append(line).append('\n');
        }
        return out.toString();
    }

    /** "_L 0xAAAAAAAA 0xVVVVVVVV" lines, or null when a line is not a CWCheat pair. */
    static List<String> body(DeliveryCheat row) {
        List<String> lines = CheatCodeText.lines(row.cheat.code);
        if (lines.isEmpty()) return null;
        List<String> body = new ArrayList<>();
        for (String raw : lines) {
            String line = raw.trim();
            if (line.startsWith("_L") || line.startsWith("_l")) line = line.substring(2).trim();
            if (line.startsWith("_C") || line.startsWith("_S") || line.startsWith("_G")) continue;
            String pair = CheatCodeText.hexPair(line);
            if (pair == null) return null;
            body.add("_L 0x" + pair.substring(0, 8) + " 0x" + pair.substring(9));
        }
        return body.isEmpty() ? null : body;
    }
}
