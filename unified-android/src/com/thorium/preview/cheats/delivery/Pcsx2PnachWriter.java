package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * ARMSX2 (PCSX2) cheats: {@code <system>/pcsx2/cheats/<SERIAL>_<CRC>.pnach}.
 *
 * <p>PCSX2 globs {@code <serial>_*.pnach} for cheats, so one file per known
 * CRC is written and, when no CRC is known, {@code <serial>_00000000.pnach}
 * (the name PCSX2's own editor falls back to). Only enabled rows are
 * written, unlabelled, so they apply whenever {@code armsx2_cheats} is on
 * without a per-game enabled list. Files EmuFusion wrote for CRCs that are
 * no longer relevant are removed.
 */
public final class Pcsx2PnachWriter implements BootCheatWriter {
    private static final Pattern CRC = Pattern.compile("^[0-9A-Fa-f]{8}$");
    // Type names per the pinned ARMSX2/PCSX2 source's patch_data_type enum
    // (pcsx2/Patch.h): byte/short/word/double/extended/beshort/beword/
    // bedouble/bytes. "leshort"/"leword"/"ledouble" are not real PCSX2 types
    // (LookupEnumName has nothing to match them against) and must not be
    // accepted here, or the cheat line silently no-ops at boot.
    private static final Pattern PNACH_LINE = Pattern.compile(
            "^(?:d?patch=[0-9],(?:EE|IOP),[0-9A-Fa-f]{1,8},(?:byte|short|word|double|extended|"
            + "beshort|beword|bedouble|bytes),[0-9A-Fa-f]{1,32}"
            + "|gsaspectratio=[0-9:. ]+|gsinterlacemode=[0-9]+)$");

    @Override public List<File> write(BootCheatRequest request) throws IOException {
        List<File> touched = new ArrayList<>();
        String serial = serial(request);
        List<String> crcs = crcs(request);
        File directory = new File(request.engineRoot, "pcsx2/cheats");
        Set<String> targets = new LinkedHashSet<>();
        if (!serial.isEmpty()) {
            if (crcs.isEmpty()) targets.add(serial + "_00000000.pnach");
            for (String crc : crcs) targets.add(serial + "_" + crc + ".pnach");
        } else {
            for (String crc : crcs) targets.add(crc + ".pnach");
        }
        if (targets.isEmpty()) return touched;
        String text = render(request);
        boolean any = text != null;
        // Retire the variants EmuFusion wrote earlier that no longer apply.
        File[] existing = directory.listFiles();
        if (existing != null) {
            for (File file : existing) {
                String name = file.getName();
                boolean ours = !serial.isEmpty() ? name.startsWith(serial + "_") && name.endsWith(".pnach")
                        : targets.contains(name);
                if (!ours || (any && targets.contains(name))) continue;
                if (OwnedFiles.remove(file, OwnedFiles.Ownership.EXACT)) touched.add(file);
            }
        }
        if (!any) return touched;
        for (String name : targets) {
            File file = new File(directory, name);
            if (!OwnedFiles.inside(request.engineRoot, file)) continue;
            if (OwnedFiles.write(file, text, OwnedFiles.Ownership.EXACT)) touched.add(file);
        }
        return touched;
    }

    static String serial(BootCheatRequest request) {
        String serial = CheatCodeText.serialWithHyphen(request.identity("serial"));
        return serial.isEmpty() ? CheatCodeText.serialWithHyphen(request.contentStem) : serial;
    }

    static List<String> crcs(BootCheatRequest request) {
        List<String> crcs = new ArrayList<>();
        for (String value : CheatCodeText.csv(request.identity("crc"))) {
            String crc = value.toUpperCase(Locale.US);
            if (crc.startsWith("0X")) crc = crc.substring(2);
            while (crc.length() < 8) crc = "0" + crc;
            if (CRC.matcher(crc).matches() && !crcs.contains(crc)) crcs.add(crc);
        }
        return crcs;
    }

    /** The pnach text, or null when nothing enabled survives validation. */
    static String render(BootCheatRequest request) {
        StringBuilder out = new StringBuilder();
        out.append("// Written by EmuFusion cheat delivery. Regenerated before every launch; ")
                .append("change the selection in EmuFusion.\n");
        if (!request.gameTitle.isEmpty())
            out.append("gametitle=").append(CheatCodeText.singleLine(request.gameTitle, 120)).append('\n');
        int written = 0;
        for (DeliveryCheat row : request.enabled()) {
            List<String> body = body(row);
            if (body == null) continue;
            out.append("// ").append(CheatCodeText.singleLine(row.cheat.name, 120));
            if (!row.source.isEmpty()) out.append(" (").append(CheatCodeText.singleLine(row.source, 60)).append(')');
            out.append('\n');
            for (String line : body) out.append(line).append('\n');
            written++;
        }
        return written == 0 ? null : out.toString();
    }

    static List<String> body(DeliveryCheat row) {
        List<String> body = new ArrayList<>();
        for (String raw : CheatCodeText.lines(row.cheat.code)) {
            String trimmed = raw.trim();
            if (trimmed.startsWith("//") || trimmed.startsWith("#")) continue;
            // PCSX2 itself strips a trailing "// ..." end-of-line comment
            // (Patch.cpp) and pcsx2_patches ships plenty of lines that carry
            // one (e.g. "... 4481f000 // 00000000"); do the same before the
            // whole-line match, or every such line is silently dropped.
            int comment = trimmed.indexOf("//");
            if (comment >= 0) trimmed = trimmed.substring(0, comment);
            String line = trimmed.replaceAll("\\s+", "");
            if (line.isEmpty()) continue;
            if (!PNACH_LINE.matcher(line).matches()) return null;
            body.add(line);
        }
        return body.isEmpty() ? null : body;
    }
}
