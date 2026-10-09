package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/**
 * Flycast cheat file: {@code <system>/dc/cheats/<stem>.cht} in the
 * key/value form flycast's own CheatManager saves and loads.
 *
 * <p>Codes are the 16-hex CodeBreaker/Xploder pairs the Dreamcast catalogue
 * carries: the top byte selects an 8-, 16- or 32-bit write, the low 24 bits
 * are the RAM offset. Other code types have no flycast equivalent and skip
 * the row. Every row is written with its enable flag so the file mirrors
 * the selection.
 */
public final class FlycastCheatWriter implements BootCheatWriter {

    @Override public List<File> write(BootCheatRequest request) throws IOException {
        List<File> touched = new ArrayList<>();
        String stem = OwnedFiles.safeName(request.contentStem);
        if (stem.isEmpty()) return touched;
        File file = new File(request.engineRoot, "dc/cheats/" + stem + ".cht");
        if (!OwnedFiles.inside(request.engineRoot, file)) return touched;
        String text = render(request);
        if (text == null) {
            if (OwnedFiles.remove(file, OwnedFiles.Ownership.EXACT)) touched.add(file);
            return touched;
        }
        if (OwnedFiles.write(file, text, OwnedFiles.Ownership.EXACT)) touched.add(file);
        return touched;
    }

    static final class Poke {
        final long address; final long value; final int searchSize;
        Poke(long address, long value, int searchSize) {
            this.address = address; this.value = value; this.searchSize = searchSize;
        }
    }

    static String render(BootCheatRequest request) {
        StringBuilder out = new StringBuilder();
        int index = 0;
        for (DeliveryCheat row : request.cheats) {
            List<Poke> pokes = pokes(row);
            if (pokes == null) continue;
            boolean enabled = request.isEnabled(row);
            String name = CheatCodeText.safeName(row.cheat.name, 96);
            for (int p = 0; p < pokes.size(); p++) {
                Poke poke = pokes.get(p);
                String prefix = "cheat" + index + "_";
                out.append(prefix).append("desc = ").append(name)
                        .append(pokes.size() > 1 ? " (" + (p + 1) + "/" + pokes.size() + ")" : "").append('\n');
                out.append(prefix).append("address = ").append(poke.address).append('\n');
                out.append(prefix).append("address_bit_position = 0\n");
                out.append(prefix).append("big_endian = false\n");
                out.append(prefix).append("cheat_type = 1\n");
                out.append(prefix).append("code = \n");
                out.append(prefix).append("dest_address = 0\n");
                out.append(prefix).append("enable = ").append(enabled ? "true" : "false").append('\n');
                out.append(prefix).append("handler = 1\n");
                out.append(prefix).append("memory_search_size = ").append(poke.searchSize).append('\n');
                out.append(prefix).append("value = ").append(poke.value).append('\n');
                out.append(prefix).append("repeat_count = 1\n");
                out.append(prefix).append("repeat_add_to_value = 0\n");
                out.append(prefix).append("repeat_add_to_address = 0\n");
                index++;
            }
        }
        if (index == 0) return null;
        out.append("cheats = ").append(index).append('\n');
        return out.toString();
    }

    /** Constant writes for each pair, or null when a line is not a supported code. */
    static List<Poke> pokes(DeliveryCheat row) {
        List<Poke> pokes = new ArrayList<>();
        for (String line : CheatCodeText.lines(row.cheat.code)) {
            String pair = CheatCodeText.hexPair(line);
            if (pair == null) return null;
            long word = Long.parseLong(pair.substring(0, 8), 16);
            long value = Long.parseLong(pair.substring(9), 16);
            int type = (int) ((word >>> 24) & 0xff);
            int searchSize;
            switch (type) {
                case 0x00: searchSize = 0; value &= 0xffL; break;
                case 0x01: searchSize = 1; value &= 0xffffL; break;
                case 0x02: searchSize = 2; break;
                default: return null;
            }
            pokes.add(new Poke(word & 0x00ffffffL, value, searchSize));
        }
        return pokes.isEmpty() ? null : pokes;
    }
}
