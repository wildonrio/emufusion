package com.thorium.preview.cheats.sources;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Synthetic headers and a hand-built ISO9660 image; never a real ROM. */
public final class CheatGameIdentityTest {
    public static void main(String[] args) throws Exception {
        n64();
        nds();
        gcWii();
        threeDs();
        paramSfo();
        systemCnf();
        pcsx2Crc();
        isoImages();
        ps3Folder();
        wiiU();
        dreamcast();
        names();
        System.out.println("CheatGameIdentityTest passed");
    }

    private static void n64() {
        byte[] z64 = new byte[0x40];
        z64[0] = (byte) 0x80; z64[1] = 0x37; z64[2] = 0x12; z64[3] = 0x40;
        put32be(z64, 0x10, 0x5C3F3A1BL); put32be(z64, 0x14, 0x53C2B9FAL); z64[0x3E] = 'E';
        Map<String, String> id = CheatGameIdentity.n64Header(z64);
        check("5C3F3A1B-53C2B9FA-C:45".equals(id.get("n64Key")), "n64 z64 key: " + id);
        byte[] v64 = new byte[0x40];
        for (int i = 0; i < 0x40; i += 2) { v64[i] = z64[i + 1]; v64[i + 1] = z64[i]; }
        check("5C3F3A1B-53C2B9FA-C:45".equals(CheatGameIdentity.n64Header(v64).get("n64Key")), "n64 v64 byte swap");
        byte[] n64 = new byte[0x40];
        for (int i = 0; i < 0x40; i += 4) { n64[i] = z64[i + 3]; n64[i + 1] = z64[i + 2]; n64[i + 2] = z64[i + 1]; n64[i + 3] = z64[i]; }
        check("5C3F3A1B-53C2B9FA-C:45".equals(CheatGameIdentity.n64Header(n64).get("n64Key")), "n64 little-endian");
        check(CheatGameIdentity.n64Header(new byte[0x40]).isEmpty(), "n64 garbage rejected");
    }

    private static void nds() {
        byte[] header = new byte[0x200];
        System.arraycopy("MARIO KART".getBytes(StandardCharsets.US_ASCII), 0, header, 0, 10);
        System.arraycopy("AMCE".getBytes(StandardCharsets.US_ASCII), 0, header, 0x0C, 4);
        header[0x15E] = 0x34; header[0x15F] = 0x12;
        Map<String, String> id = CheatGameIdentity.ndsHeader(header);
        check("AMCE".equals(id.get("gameCode")) && "1234".equals(id.get("headerCrc16")), "nds: " + id);
        check(id.get("headerCrc32").length() == 8, "nds crc32 present");
    }

    private static void gcWii() {
        byte[] header = new byte[0x60];
        System.arraycopy("RMCE01".getBytes(StandardCharsets.US_ASCII), 0, header, 0, 6);
        header[7] = 1;
        put32be(header, 0x18, 0x5D1C9EA3L);
        Map<String, String> id = CheatGameIdentity.gcWiiHeader(header);
        check("RMCE01".equals(id.get("gameId")) && "RMCE01R1".equals(id.get("discIdentity")) && "wii".equals(id.get("discType")),
                "gc/wii raw: " + id);
        byte[] rvz = new byte[0x58 + 0x80];
        System.arraycopy("RVZ\1".getBytes(StandardCharsets.US_ASCII), 0, rvz, 0, 4);
        System.arraycopy(header, 0, rvz, 0x58, 0x60);
        Map<String, String> compressed = CheatGameIdentity.rvzHeader(rvz);
        check("RMCE01".equals(compressed.get("gameId")) && "rvz".equals(compressed.get("container")), "rvz: " + compressed);
    }

    private static void threeDs() {
        byte[] ncsd = new byte[0x200];
        System.arraycopy("NCSD".getBytes(StandardCharsets.US_ASCII), 0, ncsd, 0x100, 4);
        put64le(ncsd, 0x108, 0x0004000000030100L);
        check("0004000000030100".equals(CheatGameIdentity.ncsdHeader(ncsd).get("titleId")), "ncsd title id");

        // CIA: header 0x2020, cert chain 0x0A00, ticket 0x0350, TMD with RSA-2048 SHA256 signature.
        int certSize = 0x0A00, ticketSize = 0x0350, tmdSize = 0xB34;
        int tmdOffset = 0x2040 + certSize + align(ticketSize);
        byte[] cia = new byte[tmdOffset + tmdSize];
        put32le(cia, 0x00, 0x2020); put32le(cia, 0x08, certSize); put32le(cia, 0x0C, ticketSize); put32le(cia, 0x10, tmdSize);
        put32be(cia, tmdOffset, 0x00010004L);
        int header = align(tmdOffset + 4 + 0x100);
        put64be(cia, header + 0x4C, 0x00040000000AAAAAL);
        Map<String, String> id = CheatGameIdentity.ciaHeader(cia);
        check("00040000000AAAAA".equals(id.get("titleId")), "cia title id: " + id);
    }

    private static void paramSfo() {
        byte[] sfo = buildSfo(pairs("DISC_ID", "ULUS10041", "TITLE", "God of War", "APP_VER", "01.00"));
        Map<String, String> fields = CheatGameIdentity.paramSfo(sfo);
        check("ULUS10041".equals(fields.get("DISC_ID")) && "God of War".equals(fields.get("TITLE")), "sfo: " + fields);
        check(CheatGameIdentity.paramSfo(new byte[] {1, 2, 3}).isEmpty(), "sfo garbage");
    }

    private static void systemCnf() {
        Map<String, String> cnf = CheatGameIdentity.systemCnf("BOOT2 = cdrom0:\\SLUS_209.46;1\r\nVER = 1.00\r\nVMODE = NTSC\r\n");
        check("SLUS-20946".equals(cnf.get("serial")) && "SLUS_209.46".equals(cnf.get("elf")), "system.cnf ps2: " + cnf);
        Map<String, String> psx = CheatGameIdentity.systemCnf("BOOT = cdrom:\\SLUS_005.83;1\nTCB = 4\n");
        check("SLUS-00583".equals(psx.get("serial")), "system.cnf psx: " + psx);
    }

    private static void pcsx2Crc() {
        byte[] elf = new byte[12];
        put32le(elf, 0, 0x11111111L); put32le(elf, 4, 0x22222222L); put32le(elf, 8, 0x0F0F0F0FL);
        check("3C3C3C3C".equals(CheatGameIdentity.pcsx2ElfCrc(elf)), "pcsx2 crc xor-fold: " + CheatGameIdentity.pcsx2ElfCrc(elf));
    }

    private static void isoImages() throws IOException {
        File dir = Files.createTempDirectory("lucent-identity").toFile();
        Map<String, byte[]> files = new LinkedHashMap<>();
        files.put("SYSTEM.CNF", "BOOT2 = cdrom0:\\SLUS_209.46;1\n".getBytes(StandardCharsets.US_ASCII));
        byte[] elf = new byte[4096];
        for (int i = 0; i < elf.length; i++) elf[i] = (byte) (i * 7);
        files.put("SLUS_209.46", elf);
        files.put("PSP_GAME/PARAM.SFO", buildSfo(pairs("DISC_ID", "ULUS10041", "TITLE", "God of War")));

        File iso = new File(dir, "game.iso");
        writeImage(iso, files, 2048, 0);
        Map<String, String> ps2 = CheatGameIdentity.identify("ps2", iso, "Shadow (USA).iso");
        check("SLUS-20946".equals(ps2.get("serial")), "iso ps2 serial: " + ps2);
        check(CheatGameIdentity.pcsx2ElfCrc(elf).equals(ps2.get("crc")), "iso ps2 crc: " + ps2);
        check("game".equals(ps2.get("stem")) && "Shadow (USA)".equals(ps2.get("originalStem")), "stems: " + ps2);

        Map<String, String> psp = CheatGameIdentity.identify("psp", iso, null);
        check("ULUS-10041".equals(psp.get("serial")) && "ULUS10041".equals(psp.get("discId")), "iso psp: " + psp);

        File bin = new File(dir, "game.bin");
        writeImage(bin, files, 2352, 24);
        File cue = new File(dir, "game.cue");
        write(cue, "FILE \"game.bin\" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n".getBytes(StandardCharsets.US_ASCII));
        Map<String, String> psx = CheatGameIdentity.identify("psx", cue, "");
        check("SLUS-20946".equals(psx.get("serial")), "cue/bin mode2 serial: " + psx);
        Map<String, String> rawBin = CheatGameIdentity.identify("psx", bin, "");
        check("SLUS-20946".equals(rawBin.get("serial")), "bare bin layout autodetect: " + rawBin);

        File chd = new File(dir, "Gran Turismo (USA) [SCUS-94194].chd");
        write(chd, new byte[64]);
        Map<String, String> fallback = CheatGameIdentity.identify("psx", chd, "");
        check("SCUS-94194".equals(fallback.get("serial")), "chd falls back to serial in name: " + fallback);
    }

    private static void ps3Folder() throws IOException {
        File dir = Files.createTempDirectory("lucent-ps3").toFile();
        File root = new File(dir, "Demons Souls [BLUS30443]");
        File usrdir = new File(new File(root, "PS3_GAME"), "USRDIR");
        usrdir.mkdirs();
        File eboot = new File(usrdir, "EBOOT.BIN");
        write(eboot, new byte[16]);
        write(new File(new File(root, "PS3_GAME"), "PARAM.SFO"),
                buildSfo(pairs("TITLE_ID", "BLUS30443", "APP_VER", "01.01", "TITLE", "Demon's Souls")));
        Map<String, String> id = CheatGameIdentity.identify("ps3", eboot, "");
        check("BLUS30443".equals(id.get("titleId")) && "01.01".equals(id.get("appVersion"))
                && "BLUS30443".equals(id.get("serial")), "ps3 folder: " + id);
    }

    private static void wiiU() throws IOException {
        File dir = Files.createTempDirectory("lucent-wiiu").toFile();
        File code = new File(dir, "code"); code.mkdirs();
        File meta = new File(dir, "meta"); meta.mkdirs();
        File rpx = new File(code, "U-King.rpx");
        write(rpx, new byte[8]);
        write(new File(meta, "meta.xml"), ("<?xml version=\"1.0\"?><menu type=\"complex\">"
                + "<title_id type=\"hexBinary\" length=\"8\">00050000101c9400</title_id>"
                + "<longname_en type=\"string\">The Legend of Zelda\nBreath of the Wild</longname_en></menu>")
                .getBytes(StandardCharsets.UTF_8));
        Map<String, String> id = CheatGameIdentity.identify("wiiu", rpx, "");
        check("00050000101C9400".equals(id.get("titleId")), "wiiu meta.xml: " + id);
    }

    private static void dreamcast() throws IOException {
        File dir = Files.createTempDirectory("lucent-dc").toFile();
        byte[] sector = new byte[2352];
        byte[] ip = new byte[0x100];
        System.arraycopy("SEGA SEGAKATANA ".getBytes(StandardCharsets.US_ASCII), 0, ip, 0, 16);
        System.arraycopy("T-8101N   ".getBytes(StandardCharsets.US_ASCII), 0, ip, 0x40, 10);
        System.arraycopy("SONIC ADVENTURE".getBytes(StandardCharsets.US_ASCII), 0, ip, 0x80, 15);
        System.arraycopy(ip, 0, sector, 16, ip.length);
        File track = new File(dir, "track03.bin");
        write(track, sector);
        File gdi = new File(dir, "Sonic Adventure.gdi");
        write(gdi, "3\n1 0 4 2352 track01.bin 0\n2 600 0 2352 track02.raw 0\n3 45000 4 2352 track03.bin 0\n".getBytes(StandardCharsets.US_ASCII));
        Map<String, String> id = CheatGameIdentity.identify("dreamcast", gdi, "");
        check("T-8101N".equals(id.get("productId")) && "SONIC ADVENTURE".equals(id.get("internalTitle")), "gdi ip.bin: " + id);
    }

    private static void names() throws IOException {
        File dir = Files.createTempDirectory("lucent-names").toFile();
        File nsp = new File(dir, "Game [0100ABCDEF123456][v0].nsp");
        write(nsp, new byte[4]);
        Map<String, String> sw = CheatGameIdentity.identify("switch", nsp, "");
        check("0100ABCDEF123456".equals(sw.get("titleId")), "switch title id from name: " + sw);
        File zip = new File(dir, "MSLUG3.zip");
        write(zip, new byte[4]);
        check("mslug3".equals(CheatGameIdentity.identify("arcade", zip, "").get("romset")), "arcade romset");
        check(CheatGameIdentity.sameTitle("Super Mario Bros. (USA)", "super-mario-bros"), "title normalisation");
        check(CheatGameIdentity.identify("nes", null, null).isEmpty() || true, "null rom never throws");
    }

    // ---- fixtures -----------------------------------------------------------

    private static Map<String, String> pairs(String... values) {
        Map<String, String> map = new LinkedHashMap<>();
        for (int i = 0; i + 1 < values.length; i += 2) map.put(values[i], values[i + 1]);
        return map;
    }

    /** A PARAM.SFO with UTF-8 string entries. */
    static byte[] buildSfo(Map<String, String> fields) {
        List<byte[]> keys = new ArrayList<>();
        List<byte[]> data = new ArrayList<>();
        for (Map.Entry<String, String> entry : fields.entrySet()) {
            keys.add((entry.getKey() + "\0").getBytes(StandardCharsets.US_ASCII));
            byte[] value = (entry.getValue() + "\0").getBytes(StandardCharsets.UTF_8);
            byte[] padded = new byte[(value.length + 3) & ~3];
            System.arraycopy(value, 0, padded, 0, value.length);
            data.add(padded);
        }
        int count = keys.size();
        int keyTable = 0x14 + count * 16;
        int keyBytes = 0;
        for (byte[] key : keys) keyBytes += key.length;
        int dataTable = (keyTable + keyBytes + 3) & ~3;
        int dataBytes = 0;
        for (byte[] value : data) dataBytes += value.length;
        byte[] sfo = new byte[dataTable + dataBytes];
        sfo[1] = 'P'; sfo[2] = 'S'; sfo[3] = 'F';
        put32le(sfo, 4, 0x0101); put32le(sfo, 8, keyTable); put32le(sfo, 12, dataTable); put32le(sfo, 16, count);
        int keyOffset = 0, dataOffset = 0;
        for (int i = 0; i < count; i++) {
            int entry = 0x14 + i * 16;
            sfo[entry] = (byte) keyOffset; sfo[entry + 1] = (byte) (keyOffset >> 8);
            sfo[entry + 2] = 0x04; sfo[entry + 3] = 0x02;
            put32le(sfo, entry + 4, data.get(i).length); put32le(sfo, entry + 8, data.get(i).length);
            put32le(sfo, entry + 12, dataOffset);
            System.arraycopy(keys.get(i), 0, sfo, keyTable + keyOffset, keys.get(i).length);
            System.arraycopy(data.get(i), 0, sfo, dataTable + dataOffset, data.get(i).length);
            keyOffset += keys.get(i).length;
            dataOffset += data.get(i).length;
        }
        return sfo;
    }

    /** A tiny ISO9660 image: PVD at sector 16, root directory, one level of subdirectories. */
    static void writeImage(File target, Map<String, byte[]> files, int sectorSize, int dataOffset) throws IOException {
        // layout: 16 system sectors, PVD at 16, root dir at 18, subdirs from 19, files after.
        Map<String, Map<String, byte[]>> subdirs = new LinkedHashMap<>();
        Map<String, byte[]> rootFiles = new LinkedHashMap<>();
        for (Map.Entry<String, byte[]> entry : files.entrySet()) {
            int slash = entry.getKey().indexOf('/');
            if (slash < 0) rootFiles.put(entry.getKey(), entry.getValue());
            else {
                String dirName = entry.getKey().substring(0, slash);
                Map<String, byte[]> sub = subdirs.get(dirName);
                if (sub == null) { sub = new LinkedHashMap<>(); subdirs.put(dirName, sub); }
                sub.put(entry.getKey().substring(slash + 1), entry.getValue());
            }
        }
        int nextSector = 19 + subdirs.size();
        Map<String, int[]> extents = new LinkedHashMap<>(); // path -> {sector, length}
        for (Map.Entry<String, byte[]> entry : rootFiles.entrySet()) {
            extents.put(entry.getKey(), new int[] {nextSector, entry.getValue().length});
            nextSector += Math.max(1, (entry.getValue().length + 2047) / 2048);
        }
        int subIndex = 0;
        Map<String, Integer> dirSectors = new LinkedHashMap<>();
        for (Map.Entry<String, Map<String, byte[]>> dir : subdirs.entrySet()) {
            dirSectors.put(dir.getKey(), 19 + subIndex++);
            for (Map.Entry<String, byte[]> entry : dir.getValue().entrySet()) {
                extents.put(dir.getKey() + "/" + entry.getKey(), new int[] {nextSector, entry.getValue().length});
                nextSector += Math.max(1, (entry.getValue().length + 2047) / 2048);
            }
        }
        byte[][] sectors = new byte[nextSector][];
        for (int i = 0; i < nextSector; i++) sectors[i] = new byte[2048];
        byte[] pvd = sectors[16];
        pvd[0] = 1; System.arraycopy("CD001".getBytes(StandardCharsets.US_ASCII), 0, pvd, 1, 5);
        byte[] rootRecord = record(18, 2048, true, "\0");
        System.arraycopy(rootRecord, 0, pvd, 156, rootRecord.length);
        byte[] root = sectors[18];
        int at = 0;
        for (Map.Entry<String, byte[]> entry : rootFiles.entrySet()) {
            int[] extent = extents.get(entry.getKey());
            byte[] rec = record(extent[0], extent[1], false, entry.getKey() + ";1");
            System.arraycopy(rec, 0, root, at, rec.length); at += rec.length;
        }
        for (Map.Entry<String, Integer> dir : dirSectors.entrySet()) {
            byte[] rec = record(dir.getValue(), 2048, true, dir.getKey());
            System.arraycopy(rec, 0, root, at, rec.length); at += rec.length;
            byte[] sub = sectors[dir.getValue()];
            int subAt = 0;
            for (Map.Entry<String, byte[]> entry : subdirs.get(dir.getKey()).entrySet()) {
                int[] extent = extents.get(dir.getKey() + "/" + entry.getKey());
                byte[] fileRecord = record(extent[0], extent[1], false, entry.getKey() + ";1");
                System.arraycopy(fileRecord, 0, sub, subAt, fileRecord.length); subAt += fileRecord.length;
            }
        }
        for (Map.Entry<String, byte[]> entry : files.entrySet()) {
            int[] extent = extents.get(entry.getKey());
            byte[] data = entry.getValue();
            for (int i = 0; i < data.length; i += 2048)
                System.arraycopy(data, i, sectors[extent[0] + i / 2048], 0, Math.min(2048, data.length - i));
        }
        try (FileOutputStream out = new FileOutputStream(target)) {
            for (byte[] sector : sectors) {
                byte[] raw = new byte[sectorSize];
                System.arraycopy(sector, 0, raw, dataOffset, 2048);
                out.write(raw);
            }
        }
    }

    private static byte[] record(int extent, int length, boolean directory, String name) {
        byte[] nameBytes = name.getBytes(StandardCharsets.US_ASCII);
        int size = 33 + nameBytes.length;
        if (size % 2 == 1) size++;
        byte[] rec = new byte[size];
        rec[0] = (byte) size;
        put32le(rec, 2, extent); put32be(rec, 6, extent);
        put32le(rec, 10, length); put32be(rec, 14, length);
        rec[25] = (byte) (directory ? 2 : 0);
        rec[32] = (byte) nameBytes.length;
        System.arraycopy(nameBytes, 0, rec, 33, nameBytes.length);
        return rec;
    }

    private static void write(File file, byte[] data) throws IOException {
        file.getParentFile().mkdirs();
        try (FileOutputStream out = new FileOutputStream(file)) { out.write(data); }
    }

    private static int align(int value) { return (value + 0x3F) & ~0x3F; }

    static void put32le(byte[] d, int at, long v) {
        d[at] = (byte) v; d[at + 1] = (byte) (v >> 8); d[at + 2] = (byte) (v >> 16); d[at + 3] = (byte) (v >> 24);
    }

    static void put32be(byte[] d, int at, long v) {
        d[at] = (byte) (v >> 24); d[at + 1] = (byte) (v >> 16); d[at + 2] = (byte) (v >> 8); d[at + 3] = (byte) v;
    }

    static void put64le(byte[] d, int at, long v) {
        for (int i = 0; i < 8; i++) d[at + i] = (byte) (v >> (8 * i));
    }

    static void put64be(byte[] d, int at, long v) {
        for (int i = 0; i < 8; i++) d[at + i] = (byte) (v >> (8 * (7 - i)));
    }

    static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
