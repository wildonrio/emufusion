package com.thorium.preview.cheats.delivery;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/**
 * DISC_ID ("ULUS10391") of a PSP game, read from its PARAM.SFO: inside an
 * ISO9660 image at /PSP_GAME/PARAM.SFO, or in an EBOOT.PBP header.
 *
 * <p>PPSSPP names its cheat file after this id. The libretro core's live
 * {@code retro_cheat_set} corrupts that file (it rewrites the "_S" header as
 * a "_C" entry, so the CwCheat parser fails on line 2), so EmuFusion writes
 * the file itself before boot and needs the id to do so.
 */
public final class PspDiscId {
    private static final int SECTOR = 2048;
    private static final int MAX_SFO_BYTES = 64 * 1024;

    private PspDiscId() {}

    /** The id, or "" when the file is not a readable ISO/PBP. */
    public static String of(File game) {
        if (game == null || !game.isFile()) return "";
        String name = game.getName().toLowerCase(Locale.US);
        try (RandomAccessFile input = new RandomAccessFile(game, "r")) {
            if (name.endsWith(".pbp")) return discId(pbpSfo(input));
            if (name.endsWith(".iso")) return discId(isoSfo(input));
        } catch (IOException | RuntimeException unreadable) {
            return "";
        }
        return "";
    }

    private static byte[] pbpSfo(RandomAccessFile input) throws IOException {
        byte[] header = new byte[16];
        input.readFully(header);
        if (header[0] != 0 || header[1] != 'P' || header[2] != 'B' || header[3] != 'P') return null;
        long start = u32(header, 8), end = u32(header, 12);
        if (end <= start || end - start > MAX_SFO_BYTES) return null;
        byte[] sfo = new byte[(int) (end - start)];
        input.seek(start);
        input.readFully(sfo);
        return sfo;
    }

    private static byte[] isoSfo(RandomAccessFile input) throws IOException {
        byte[] pvd = sector(input, 16);
        if (pvd[0] != 1 || pvd[1] != 'C' || pvd[2] != 'D' || pvd[3] != '0') return null;
        long rootLba = u32(pvd, 156 + 2), rootSize = u32(pvd, 156 + 10);
        long[] gameDir = find(input, rootLba, rootSize, "PSP_GAME", true);
        if (gameDir == null) return null;
        long[] sfo = find(input, gameDir[0], gameDir[1], "PARAM.SFO", false);
        if (sfo == null || sfo[1] <= 0 || sfo[1] > MAX_SFO_BYTES) return null;
        byte[] data = new byte[(int) sfo[1]];
        input.seek(sfo[0] * SECTOR);
        input.readFully(data);
        return data;
    }

    /** {lba, size} of a directory entry, matching "NAME" or "NAME;1". */
    private static long[] find(RandomAccessFile input, long lba, long size, String wanted,
                               boolean directory) throws IOException {
        if (size <= 0 || size > 1024L * SECTOR) return null;
        long sectors = (size + SECTOR - 1) / SECTOR;
        for (long s = 0; s < sectors; s++) {
            byte[] data = sector(input, lba + s);
            int offset = 0;
            while (offset < SECTOR) {
                int length = data[offset] & 0xff;
                if (length == 0) break;
                if (offset + 33 > SECTOR || offset + length > SECTOR) break;
                int nameLength = data[offset + 32] & 0xff;
                if (offset + 33 + nameLength > SECTOR) break;
                String name = new String(data, offset + 33, nameLength, StandardCharsets.US_ASCII);
                int semicolon = name.indexOf(';');
                if (semicolon >= 0) name = name.substring(0, semicolon);
                boolean isDirectory = (data[offset + 25] & 0x02) != 0;
                if (name.equalsIgnoreCase(wanted) && isDirectory == directory)
                    return new long[] {u32(data, offset + 2), u32(data, offset + 10)};
                offset += length;
            }
        }
        return null;
    }

    private static byte[] sector(RandomAccessFile input, long lba) throws IOException {
        byte[] data = new byte[SECTOR];
        input.seek(lba * SECTOR);
        input.readFully(data);
        return data;
    }

    /** DISC_ID from a PARAM.SFO, compacted ("ULUS-10391" -> "ULUS10391"). */
    static String discId(byte[] sfo) {
        if (sfo == null || sfo.length < 20) return "";
        if (sfo[0] != 0 || sfo[1] != 'P' || sfo[2] != 'S' || sfo[3] != 'F') return "";
        long keys = u32(sfo, 8), values = u32(sfo, 12), count = u32(sfo, 16);
        for (int i = 0; i < count && 20 + i * 16 + 16 <= sfo.length; i++) {
            int entry = 20 + i * 16;
            int keyStart = (int) keys + ((sfo[entry] & 0xff) | (sfo[entry + 1] & 0xff) << 8);
            int keyEnd = keyStart;
            while (keyEnd < sfo.length && sfo[keyEnd] != 0) keyEnd++;
            if (keyStart >= sfo.length) continue;
            String key = new String(sfo, keyStart, keyEnd - keyStart, StandardCharsets.US_ASCII);
            if (!"DISC_ID".equals(key)) continue;
            int length = (int) u32(sfo, entry + 4);
            int start = (int) values + (int) u32(sfo, entry + 12);
            int end = start;
            while (end < start + length && end < sfo.length && sfo[end] != 0) end++;
            String id = new String(sfo, start, Math.max(0, end - start), StandardCharsets.US_ASCII)
                    .replace("-", "").trim().toUpperCase(Locale.US);
            return id.matches("[A-Z]{4}[0-9]{5}") ? id : "";
        }
        return "";
    }

    private static long u32(byte[] data, int offset) {
        return (data[offset] & 0xffL) | (data[offset + 1] & 0xffL) << 8 |
                (data[offset + 2] & 0xffL) << 16 | (data[offset + 3] & 0xffL) << 24;
    }
}
