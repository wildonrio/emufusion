package com.thorium.preview.cheats.sources;

import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.lucent.metadata.EngineSystemIdResolver;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.CRC32;

/**
 * Reads the identifiers cheat databases key on straight from the ROM.
 *
 * <p>Every reader is bounded, tolerant, and pure Java: it returns what it
 * could establish as a string map and never throws. Keys used across sources:
 * {@code serial} (SLUS-20946, ULUS-10041, BLUS30443), {@code crc} (PCSX2's ELF
 * checksum), {@code gameId}/{@code revision}/{@code discIdentity} (GameCube/Wii),
 * {@code n64Key} (CRC1-CRC2-C:CC), {@code gameCode}/{@code headerCrc32} (DS),
 * {@code titleId} (3DS, Switch, Wii U, PS3), {@code appVersion} (PS3),
 * {@code productId} (Dreamcast), {@code romset} (arcade), {@code romCrc32}
 * (whole-file CRC32 for a No-Intro-style cartridge dump), {@code chdRawHash}/
 * {@code chdRawHashAlgo} (a CHD's raw-data hash, for a Redump-style disc
 * dump; see {@link #chdIdentity(File)}), plus {@code stem} and
 * {@code originalStem} for title matching.
 */
public final class CheatGameIdentity {
    static final long MAX_ELF_BYTES = 64L * 1024L * 1024L;
    static final long MAX_ISO_FILE_BYTES = 4L * 1024L * 1024L;
    /** Generous enough for the largest No-Intro cartridge dumps (NDS/N64); bounds a pathological file. */
    static final long MAX_CRC_BYTES = 768L * 1024L * 1024L;
    /** A CHD's fixed header is at most the V5 layout (124 bytes); read a little slack. */
    private static final int CHD_HEADER_READ = 160;
    private static final Pattern SERIAL_IN_NAME = Pattern.compile(
            "(?i)(?:^|[^A-Z0-9])([A-Z]{4})[-_ ]?([0-9]{5})(?:[^A-Z0-9]|$)");
    private static final Pattern SWITCH_TITLE_ID = Pattern.compile("(?i)(?:^|[^0-9A-F])(01[0-9A-F]{14})(?:[^0-9A-F]|$)");
    private static final Pattern SYSTEM_CNF_BOOT = Pattern.compile(
            "(?i)BOOT2?\\s*=\\s*cdrom0?:\\\\?([A-Z0-9_.\\\\]+?)(?:;1)?\\s*$", Pattern.MULTILINE);
    private static final Pattern PS_SERIAL_FILE = Pattern.compile("(?i)([A-Z]{4})_([0-9]{3})\\.([0-9]{2})");
    private static final Pattern WIIU_TITLE_ID = Pattern.compile(
            "(?is)<title_id[^>]*>\\s*([0-9A-F]{16})\\s*</title_id>");

    /**
     * Systems where a single-file cartridge dump's whole-file CRC32 is the
     * No-Intro DAT key (see {@code DiscDatIndex}). Disc-based systems are
     * identified by serial/ISO/CHD-hash instead: a whole-file CRC of a CD
     * image does not correspond to anything in a Redump DAT (which hashes
     * per-track).
     */
    private static final Set<String> CRC_KEYED_SYSTEMS = new HashSet<>(Arrays.asList(
            "nes", "snes", "gb", "gbc", "gba", "megadrive", "mastersystem", "gamegear",
            "sg1000", "atari2600", "atari5200", "atari7800", "atari800", "pcengine",
            "jaguar", "n64", "nds", "msx", "colecovision", "intellivision"));

    /** Systems whose disc image may arrive as a headerless CHD (see {@link #chdIdentity(File)}). */
    private static final Set<String> CHD_IDENTITY_SYSTEMS = new HashSet<>(Arrays.asList(
            "psx", "ps2", "dreamcast", "segacd", "pcenginecd", "saturn", "neogeocd", "3do", "amigacd32"));

    private CheatGameIdentity() {}

    /** Never throws; an empty map means "title matching only". */
    public static Map<String, String> identify(String system, File rom, String originalName) {
        return identify(system, rom, originalName, -1L);
    }

    /**
     * Same as {@link #identify(String, File, String)}, except the whole-file
     * CRC32 read for a cartridge-keyed system -- the one genuinely expensive
     * step here; every other reader is a header read of at most a few KB --
     * respects {@code crcBudgetMillis} the way {@link #crc32(File, long)}
     * does. A caller processing many games under one wall-clock deadline
     * (the round-robin library refresh) passes its remaining budget so a
     * single huge ROM cannot by itself consume the whole batch's time
     * limit; every other caller passes a negative budget for the original
     * unbounded behaviour.
     */
    public static Map<String, String> identify(String system, File rom, String originalName,
                                                long crcBudgetMillis) {
        Map<String, String> identity = new LinkedHashMap<>();
        try {
            String canonical = EngineSystemIdResolver.canonical(system);
            String name = rom == null ? "" : rom.getName();
            identity.put("stem", stem(name));
            String originalStem = stem(originalName == null || originalName.isEmpty() ? name : originalName);
            if (!originalStem.isEmpty() && !originalStem.equals(identity.get("stem")))
                identity.put("originalStem", originalStem);
            String serialFromName = serialInName(name + " " + (originalName == null ? "" : originalName));
            if (rom != null && rom.isFile() || rom != null && rom.isDirectory()) {
                Map<String, String> read = readRom(canonical, rom);
                for (Map.Entry<String, String> entry : read.entrySet())
                    if (entry.getValue() != null && !entry.getValue().isEmpty())
                        identity.put(entry.getKey(), entry.getValue());
            }
            if (!identity.containsKey("serial") && !serialFromName.isEmpty()
                    && isSerialKeyed(canonical))
                identity.put("serial", serialFromName);
            if (rom != null && rom.isFile() && CRC_KEYED_SYSTEMS.contains(canonical)
                    && !identity.containsKey("romCrc32")) {
                String crc = crc32(rom, crcBudgetMillis);
                if (!crc.isEmpty()) identity.put("romCrc32", crc);
            }
            if ("switch".equals(canonical) && !identity.containsKey("titleId")) {
                String titleId = switchTitleId(name + " " + (originalName == null ? "" : originalName)
                        + " " + (rom == null ? "" : rom.getAbsolutePath()));
                if (!titleId.isEmpty()) identity.put("titleId", titleId);
            }
            if (("arcade".equals(canonical) || "neogeo".equals(canonical)) && !identity.containsKey("romset"))
                identity.put("romset", stem(name).toLowerCase(Locale.US));
        } catch (RuntimeException ignored) {
            // Identity is best effort; a miss falls back to title matching.
        }
        return identity;
    }

    private static boolean isSerialKeyed(String canonical) {
        return "psx".equals(canonical) || "ps2".equals(canonical) || "psp".equals(canonical)
                || "ps3".equals(canonical);
    }

    private static Map<String, String> readRom(String canonical, File rom) {
        String lower = rom.getName().toLowerCase(Locale.US);
        try {
            if (lower.endsWith(".chd") && CHD_IDENTITY_SYSTEMS.contains(canonical))
                return chdDiscIdentity(rom);
            switch (canonical) {
                case "n64": return n64Header(head(rom, 0x40));
                case "nds": return ndsHeader(head(rom, 0x200));
                case "gamecube":
                case "wii": return discHeader(rom);
                case "3ds": return threeDs(rom, lower);
                case "psx":
                case "ps2": return playstationDisc(canonical, rom, lower);
                case "psp": return pspDisc(rom, lower);
                case "ps3": return ps3(rom);
                case "wiiu": return wiiU(rom, lower);
                case "dreamcast": return dreamcast(rom, lower);
                default: return Collections.emptyMap();
            }
        } catch (IOException | RuntimeException failed) {
            return Collections.emptyMap();
        }
    }

    /** {@link #chdIdentity(File)}'s output, filtered to the keys worth merging into an identity map. */
    private static Map<String, String> chdDiscIdentity(File rom) {
        Map<String, String> chd = chdIdentity(rom);
        if (chd.isEmpty()) return chd;
        Map<String, String> result = new LinkedHashMap<>();
        for (String key : new String[] {"chdVersion", "chdSha1", "chdRawSha1", "chdMd5",
                "chdRawHash", "chdRawHashAlgo"}) {
            String value = chd.get(key);
            if (value != null && !value.isEmpty()) result.put(key, value);
        }
        return result;
    }

    // ---- Nintendo 64 ---------------------------------------------------

    /** CRC1/CRC2 at 0x10/0x14 and the country byte at 0x3E, any byte order. */
    public static Map<String, String> n64Header(byte[] header) {
        Map<String, String> result = new LinkedHashMap<>();
        if (header == null || header.length < 0x40) return result;
        byte[] big = new byte[0x40];
        System.arraycopy(header, 0, big, 0, 0x40);
        int b0 = big[0] & 0xff, b1 = big[1] & 0xff, b2 = big[2] & 0xff, b3 = big[3] & 0xff;
        if (b0 == 0x37 && b1 == 0x80 && b2 == 0x40 && b3 == 0x12) {
            for (int i = 0; i + 1 < big.length; i += 2) { byte t = big[i]; big[i] = big[i + 1]; big[i + 1] = t; }
            result.put("byteOrder", "v64");
        } else if (b0 == 0x40 && b1 == 0x12 && b2 == 0x37 && b3 == 0x80) {
            for (int i = 0; i + 3 < big.length; i += 4) {
                byte t0 = big[i], t1 = big[i + 1];
                big[i] = big[i + 3]; big[i + 1] = big[i + 2]; big[i + 2] = t1; big[i + 3] = t0;
            }
            result.put("byteOrder", "n64");
        } else if (b0 == 0x80 && b1 == 0x37 && b2 == 0x12 && b3 == 0x40) {
            result.put("byteOrder", "z64");
        } else {
            return result;
        }
        long crc1 = u32be(big, 0x10);
        long crc2 = u32be(big, 0x14);
        int country = big[0x3E] & 0xff;
        result.put("crc1", String.format(Locale.US, "%08X", crc1));
        result.put("crc2", String.format(Locale.US, "%08X", crc2));
        result.put("country", String.format(Locale.US, "%02X", country));
        result.put("n64Key", String.format(Locale.US, "%08X-%08X-C:%02X", crc1, crc2, country));
        String title = ascii(big, 0x20, 20).trim();
        if (!title.isEmpty()) result.put("internalTitle", title);
        return result;
    }

    // ---- Nintendo DS ---------------------------------------------------

    /** Game code at 0x0C, header CRC16 at 0x15E, CRC32 of the first 512 bytes (R4 key). */
    public static Map<String, String> ndsHeader(byte[] header) {
        Map<String, String> result = new LinkedHashMap<>();
        if (header == null || header.length < 0x160) return result;
        String code = ascii(header, 0x0C, 4);
        if (!code.matches("[A-Z0-9#]{4}")) return result;
        result.put("gameCode", code);
        result.put("headerCrc16", String.format(Locale.US, "%04X", u16le(header, 0x15E)));
        java.util.zip.CRC32 crc = new java.util.zip.CRC32();
        crc.update(header, 0, Math.min(512, header.length));
        result.put("headerCrc32", String.format(Locale.US, "%08X", crc.getValue()));
        String title = ascii(header, 0, 12).trim();
        if (!title.isEmpty()) result.put("internalTitle", title);
        return result;
    }

    // ---- GameCube / Wii ------------------------------------------------

    /** Raw disc header: 6-char ID, disc number at 6, revision at 7. */
    public static Map<String, String> gcWiiHeader(byte[] header) {
        Map<String, String> result = new LinkedHashMap<>();
        if (header == null || header.length < 0x20) return result;
        String id = ascii(header, 0, 6);
        if (!id.matches("[A-Z0-9]{6}")) return result;
        boolean wii = u32be(header, 0x18) == 0x5D1C9EA3L;
        boolean gc = u32be(header, 0x1C) == 0xC2339F3DL;
        result.put("gameId", id);
        result.put("revision", String.valueOf(header[7] & 0xff));
        result.put("discIdentity", id + "R" + (header[7] & 0xff));
        result.put("maker", id.substring(4));
        if (wii || gc) result.put("discType", wii ? "wii" : "gamecube");
        if (header.length >= 0x60) {
            String title = ascii(header, 0x20, 0x40).trim();
            if (!title.isEmpty()) result.put("internalTitle", title);
        }
        return result;
    }

    /** RVZ/WIA: header_1 is 0x48 bytes, header_2 opens with four u32 then the raw disc header. */
    public static Map<String, String> rvzHeader(byte[] header) {
        if (header == null || header.length < 0x58 + 0x20) return new LinkedHashMap<>();
        String magic = ascii(header, 0, 3);
        if (!"RVZ".equals(magic) && !"WIA".equals(magic)) return new LinkedHashMap<>();
        byte[] disc = new byte[Math.min(0x80, header.length - 0x58)];
        System.arraycopy(header, 0x58, disc, 0, disc.length);
        Map<String, String> result = gcWiiHeader(disc);
        if (!result.isEmpty()) result.put("container", magic.toLowerCase(Locale.US));
        return result;
    }

    private static Map<String, String> discHeader(File rom) throws IOException {
        byte[] head = head(rom, 0x8000 + 0x80);
        if (head.length < 0x20) return Collections.emptyMap();
        String magic4 = ascii(head, 0, 4);
        if ("RVZ".equals(ascii(head, 0, 3)) || "WIA".equals(ascii(head, 0, 3))) return rvzHeader(head);
        if ("WBFS".equals(magic4) && head.length >= 0x200 + 0x60) {
            byte[] disc = new byte[0x60];
            System.arraycopy(head, 0x200, disc, 0, 0x60);
            Map<String, String> result = gcWiiHeader(disc);
            if (!result.isEmpty()) result.put("container", "wbfs");
            return result;
        }
        if ("CISO".equals(magic4) && head.length >= 0x8000 + 0x60 && head[8] == 1) {
            byte[] disc = new byte[0x60];
            System.arraycopy(head, 0x8000, disc, 0, 0x60);
            Map<String, String> result = gcWiiHeader(disc);
            if (!result.isEmpty()) result.put("container", "ciso");
            return result;
        }
        return gcWiiHeader(head);
    }

    // ---- 3DS ---------------------------------------------------------------

    /** NCSD (.3ds/.cci): "NCSD" at 0x100, media/title id at 0x108 (u64 LE). */
    public static Map<String, String> ncsdHeader(byte[] header) {
        Map<String, String> result = new LinkedHashMap<>();
        if (header == null || header.length < 0x120) return result;
        if ("NCSD".equals(ascii(header, 0x100, 4))) {
            result.put("titleId", hex64le(header, 0x108));
            result.put("container", "ncsd");
        } else if ("NCCH".equals(ascii(header, 0x100, 4))) {
            result.put("titleId", hex64le(header, 0x118));
            result.put("container", "ncch");
        }
        return result;
    }

    /**
     * CIA: header sizes at 0x00 (header), 0x08 (cert chain), 0x0C (ticket),
     * 0x10 (TMD); sections are 64-byte aligned; the TMD's title id sits at
     * 0x4C past its signature block.
     */
    public static Map<String, String> ciaHeader(byte[] head) {
        Map<String, String> result = new LinkedHashMap<>();
        if (head == null || head.length < 0x20) return result;
        long headerSize = u32le(head, 0x00);
        long certSize = u32le(head, 0x08);
        long ticketSize = u32le(head, 0x0C);
        long tmdSize = u32le(head, 0x10);
        if (headerSize != 0x2020 || tmdSize < 0x100 || tmdSize > 1024L * 1024L) return result;
        long tmdOffset = align64(headerSize) + align64(certSize) + align64(ticketSize);
        if (tmdOffset + 0x4 > head.length) return result;
        long signatureType = u32be(head, (int) tmdOffset);
        int signatureSize;
        if (signatureType == 0x00010000L || signatureType == 0x00010003L) signatureSize = 0x200;
        else if (signatureType == 0x00010001L || signatureType == 0x00010004L) signatureSize = 0x100;
        else if (signatureType == 0x00010002L || signatureType == 0x00010005L) signatureSize = 0x3C;
        else return result;
        long headerStart = tmdOffset + 4 + signatureSize;
        headerStart = (headerStart + 0x3F) & ~0x3FL;
        int titleAt = (int) (headerStart + 0x4C);
        if (titleAt + 8 > head.length) return result;
        result.put("titleId", hex64be(head, titleAt));
        result.put("container", "cia");
        return result;
    }

    private static Map<String, String> threeDs(File rom, String lower) throws IOException {
        if (lower.endsWith(".cia")) return ciaHeader(head(rom, 0x4000));
        return ncsdHeader(head(rom, 0x200));
    }

    // ---- PlayStation family --------------------------------------------

    /** All string entries of a PARAM.SFO: DISC_ID, TITLE_ID, APP_VER, TITLE, ... */
    public static Map<String, String> paramSfo(byte[] sfo) {
        Map<String, String> result = new LinkedHashMap<>();
        if (sfo == null || sfo.length < 0x14 || sfo[0] != 0 || sfo[1] != 'P' || sfo[2] != 'S' || sfo[3] != 'F')
            return result;
        long keyTable = u32le(sfo, 0x08);
        long dataTable = u32le(sfo, 0x0C);
        long entries = u32le(sfo, 0x10);
        if (entries > 256) return result;
        for (int i = 0; i < entries; i++) {
            int entry = 0x14 + i * 16;
            if (entry + 16 > sfo.length) break;
            int keyOffset = u16le(sfo, entry);
            int format = u16le(sfo, entry + 2);
            long length = u32le(sfo, entry + 4);
            long dataOffset = u32le(sfo, entry + 12);
            long keyAt = keyTable + keyOffset;
            long dataAt = dataTable + dataOffset;
            if (keyAt >= sfo.length || dataAt >= sfo.length || length > 4096) continue;
            String key = cstring(sfo, (int) keyAt, 64);
            if (key.isEmpty()) continue;
            if (format == 0x0204 || format == 0x0004) {
                result.put(key, cstring(sfo, (int) dataAt, (int) Math.min(length, sfo.length - dataAt)));
            } else if (format == 0x0404 && dataAt + 4 <= sfo.length) {
                result.put(key, String.valueOf(u32le(sfo, (int) dataAt)));
            }
        }
        return result;
    }

    /** {@code BOOT2 = cdrom0:\SLUS_209.46;1} → SLUS-20946 and the ELF path. */
    public static Map<String, String> systemCnf(String text) {
        Map<String, String> result = new LinkedHashMap<>();
        if (text == null) return result;
        Matcher boot = SYSTEM_CNF_BOOT.matcher(text);
        if (!boot.find()) return result;
        String path = boot.group(1).replace("\\", "/");
        result.put("elf", path);
        Matcher serial = PS_SERIAL_FILE.matcher(path);
        if (serial.find())
            result.put("serial", (serial.group(1) + "-" + serial.group(2) + serial.group(3)).toUpperCase(Locale.US));
        return result;
    }

    /** PCSX2's game "CRC": every little-endian 32-bit word of the ELF XOR-folded. */
    public static String pcsx2ElfCrc(byte[] elf) {
        if (elf == null) return "";
        long crc = 0;
        int words = elf.length / 4;
        for (int i = 0; i < words; i++) crc ^= u32le(elf, i * 4);
        return String.format(Locale.US, "%08X", crc);
    }

    private static Map<String, String> playstationDisc(String canonical, File rom, String lower)
            throws IOException {
        Iso9660 iso = openDisc(rom, lower);
        if (iso == null) return Collections.emptyMap();
        try {
            byte[] cnf = iso.readFile("SYSTEM.CNF", 64 * 1024);
            if (cnf == null) return Collections.emptyMap();
            Map<String, String> result = new LinkedHashMap<>(
                    systemCnf(new String(cnf, StandardCharsets.US_ASCII)));
            String elf = result.get("elf");
            if ("ps2".equals(canonical) && elf != null && !elf.isEmpty()) {
                byte[] data = iso.readFile(elf, MAX_ELF_BYTES);
                if (data != null && data.length >= 4) result.put("crc", pcsx2ElfCrc(data));
            }
            return result;
        } finally {
            iso.close();
        }
    }

    private static Map<String, String> pspDisc(File rom, String lower) throws IOException {
        Iso9660 iso = openDisc(rom, lower);
        if (iso == null) return Collections.emptyMap();
        try {
            byte[] sfo = iso.readFile("PSP_GAME/PARAM.SFO", 256 * 1024);
            if (sfo == null) return Collections.emptyMap();
            Map<String, String> fields = paramSfo(sfo);
            Map<String, String> result = new LinkedHashMap<>();
            String discId = fields.get("DISC_ID");
            if (discId != null && !discId.isEmpty()) {
                result.put("discId", discId);
                result.put("serial", CwCheatParser.normaliseSerial(discId));
            }
            String title = fields.get("TITLE");
            if (title != null && !title.isEmpty()) result.put("internalTitle", title);
            return result;
        } finally {
            iso.close();
        }
    }

    private static Map<String, String> ps3(File rom) throws IOException {
        File titleRoot = null;
        if (rom.isDirectory()) titleRoot = rom;
        else if (rom.getParentFile() != null && rom.getParentFile().getParentFile() != null
                && "USRDIR".equalsIgnoreCase(rom.getParentFile().getName()))
            titleRoot = rom.getParentFile().getParentFile();
        if (titleRoot == null) return Collections.emptyMap();
        File sfoFile = new File(titleRoot, "PARAM.SFO");
        if (!sfoFile.isFile()) sfoFile = new File(new File(titleRoot, "PS3_GAME"), "PARAM.SFO");
        if (!sfoFile.isFile() || sfoFile.length() > 256 * 1024) return Collections.emptyMap();
        Map<String, String> fields = paramSfo(head(sfoFile, (int) sfoFile.length()));
        Map<String, String> result = new LinkedHashMap<>();
        String titleId = fields.get("TITLE_ID");
        if (titleId != null && !titleId.isEmpty()) {
            result.put("titleId", titleId.toUpperCase(Locale.US));
            result.put("serial", Rpcs3PatchYamlParser.normaliseSerial(titleId));
        }
        String version = fields.get("APP_VER");
        if (version != null && !version.isEmpty()) result.put("appVersion", version);
        String title = fields.get("TITLE");
        if (title != null && !title.isEmpty()) result.put("internalTitle", title);
        return result;
    }

    // ---- Wii U -------------------------------------------------------------

    public static Map<String, String> wiiUMetaXml(String xml) {
        Map<String, String> result = new LinkedHashMap<>();
        if (xml == null) return result;
        Matcher match = WIIU_TITLE_ID.matcher(xml);
        if (match.find()) result.put("titleId", match.group(1).toUpperCase(Locale.US));
        Matcher name = Pattern.compile("(?is)<longname_en[^>]*>(.*?)</longname_en>").matcher(xml);
        if (name.find()) result.put("internalTitle", name.group(1).replace("\n", " ").trim());
        return result;
    }

    private static Map<String, String> wiiU(File rom, String lower) throws IOException {
        File base = rom.isDirectory() ? rom : rom.getParentFile();
        for (int depth = 0; depth < 3 && base != null; depth++, base = base.getParentFile()) {
            File meta = new File(new File(base, "meta"), "meta.xml");
            if (meta.isFile() && meta.length() <= 1024 * 1024)
                return wiiUMetaXml(new String(head(meta, (int) meta.length()), StandardCharsets.UTF_8));
        }
        return Collections.emptyMap();
    }

    // ---- Dreamcast -----------------------------------------------------------

    /** IP.BIN: "SEGA SEGAKATANA" at 0, product number at 0x40, title at 0x80. */
    public static Map<String, String> ipBin(byte[] sector) {
        Map<String, String> result = new LinkedHashMap<>();
        if (sector == null) return result;
        int base = -1;
        for (int offset : new int[] {0, 16, 24}) {
            if (sector.length >= offset + 0x100 && "SEGA SEGAKATANA".equals(ascii(sector, offset, 15))) {
                base = offset;
                break;
            }
        }
        if (base < 0) return result;
        String product = ascii(sector, base + 0x40, 10).trim();
        if (!product.isEmpty()) result.put("productId", product);
        String title = ascii(sector, base + 0x80, 128).trim();
        if (!title.isEmpty()) result.put("internalTitle", title);
        return result;
    }

    private static Map<String, String> dreamcast(File rom, String lower) throws IOException {
        File data = null;
        if (lower.endsWith(".gdi")) {
            String gdi = new String(head(rom, 64 * 1024), StandardCharsets.US_ASCII);
            for (String line : CodeText.lines(gdi)) {
                String[] parts = line.trim().split("\\s+");
                if (parts.length >= 5 && "3".equals(parts[0])) {
                    String name = line.contains("\"") ? line.substring(line.indexOf('"') + 1,
                            line.lastIndexOf('"')) : parts[4];
                    data = new File(rom.getParentFile(), name);
                    break;
                }
            }
        } else if (lower.endsWith(".cue")) {
            CueSheet cue = CueSheet.parse(rom);
            if (cue != null) data = cue.bin;
        } else if (lower.endsWith(".bin") || lower.endsWith(".iso")) {
            data = rom;
        }
        if (data == null || !data.isFile()) return Collections.emptyMap();
        return ipBin(head(data, 2352 + 0x100));
    }

    // ---- CRC32 / CHD header identity ------------------------------------------

    /**
     * Streaming CRC32 of an arbitrary file, bounded by {@link #MAX_CRC_BYTES}.
     * This is the No-Intro DAT key for single-file cartridge dumps (the DAT's
     * {@code crc} attribute is the CRC32 of the ROM file exactly as
     * distributed); it never loads more than one buffer into memory
     * regardless of file size, so the bound is purely "do not spend forever
     * hashing an unrelated multi-gigabyte file", not a memory limit.
     */
    public static String crc32(File file) {
        return crc32(file, -1L);
    }

    /**
     * Same as {@link #crc32(File)}, but additionally bounded by a wall-clock
     * budget: {@code budgetMillis == 0} skips the hash entirely (no time
     * left to spend on it, a quiet miss exactly like an unreadable file),
     * {@code budgetMillis > 0} aborts the read (also a quiet miss) once
     * that many milliseconds have elapsed, and a negative budget is
     * unbounded -- the original behaviour, and what {@link #crc32(File)}
     * and every direct caller still gets.
     */
    public static String crc32(File file, long budgetMillis) {
        if (budgetMillis == 0) return "";
        if (file == null || !file.isFile()) return "";
        long length = file.length();
        if (length <= 0 || length > MAX_CRC_BYTES) return "";
        long deadlineNanos = budgetMillis > 0 ? System.nanoTime() + budgetMillis * 1_000_000L : -1L;
        CRC32 crc = new CRC32();
        try (InputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[64 * 1024];
            int read;
            while ((read = input.read(buffer)) >= 0) {
                crc.update(buffer, 0, read);
                if (deadlineNanos >= 0 && System.nanoTime() > deadlineNanos) return "";
            }
        } catch (IOException unreadable) {
            return "";
        }
        return String.format(Locale.US, "%08X", crc.getValue());
    }

    /**
     * Header-only identity for a MAME/CHD-format disc image ({@code "MComprHD"}
     * magic), without decompressing a single hunk. Layout verified against
     * MAME's {@code src/lib/util/chd.h} (BSD-3-Clause) header documentation
     * and cross-checked against the field offsets {@code chd_file::parse_v3
     * /v4/v5_header} actually read in {@code src/lib/util/chd.cpp}:
     *
     * <ul>
     * <li>v1/v2: MD5 of the raw data at offset 44 (16 bytes). Both versions
     *     share this layout up to that point; only v2 adds a trailing
     *     {@code seclen} field the identity does not need.</li>
     * <li>v3: SHA1 of the raw data at offset 80 (20 bytes) -- v3 has no
     *     separate metadata blob folded into the disc hash, so this SHA1
     *     already is the raw-data hash. A legacy MD5 remains at offset 44.</li>
     * <li>v4: a combined raw+metadata SHA1 at offset 48, and a separate raw
     *     data-only SHA1 at offset 88 (each 20 bytes).</li>
     * <li>v5: a raw data-only SHA1 at offset 64, and the combined raw+metadata
     *     SHA1 at offset 84 (each 20 bytes).</li>
     * </ul>
     *
     * <p>{@code chdRawHash}/{@code chdRawHashAlgo} name whichever of those is
     * the hash of the original, uncompressed media (MD5 for v1/v2, SHA1
     * otherwise) -- the value a Redump DAT's {@code md5}/{@code sha1} rom
     * attribute can match for a single-track image. A multi-track CD image
     * (separate audio tracks) has no single Redump hash to match against
     * here: Redump lists one hash per track, while a CHD folds every track
     * into one raw hash, so only single-track dumps (most non-audio disc
     * games ripped as one bin/iso, which is the common case for the systems
     * this is wired into) resolve; anything else falls back to title/serial
     * matching, as it already did before this method existed. Versions
     * before 1 or after 5 are unknown formats and report only
     * {@code chdVersion}.
     */
    public static Map<String, String> chdIdentity(byte[] header) {
        Map<String, String> result = new LinkedHashMap<>();
        if (header == null || header.length < 16 || !"MComprHD".equals(ascii(header, 0, 8)))
            return result;
        long declaredLength = u32be(header, 8);
        long version = u32be(header, 12);
        result.put("chdVersion", String.valueOf(version));
        if ((version == 1 || version == 2) && declaredLength >= 76 && header.length >= 60 + 16) {
            putHashIfNonZero(result, "chdMd5", header, 44, 16);
            promoteRawHash(result, "chdMd5", "md5");
        } else if (version == 3 && declaredLength >= 120 && header.length >= 100 + 20) {
            putHashIfNonZero(result, "chdMd5", header, 44, 16);
            putHashIfNonZero(result, "chdSha1", header, 80, 20);
            promoteRawHash(result, "chdSha1", "sha1");
        } else if (version == 4 && declaredLength >= 108 && header.length >= 88 + 20) {
            putHashIfNonZero(result, "chdSha1", header, 48, 20);
            putHashIfNonZero(result, "chdRawSha1", header, 88, 20);
            promoteRawHash(result, "chdRawSha1", "sha1");
        } else if (version == 5 && declaredLength >= 124 && header.length >= 104 + 20) {
            putHashIfNonZero(result, "chdRawSha1", header, 64, 20);
            putHashIfNonZero(result, "chdSha1", header, 84, 20);
            promoteRawHash(result, "chdRawSha1", "sha1");
        }
        // Versions outside 1-5 (or a header too short for the version it
        // claims) are not documented here with confidence; report only the
        // version so a caller can see it was recognised but not decoded.
        return result;
    }

    /** Reads only the fixed header bytes of {@code chd} and delegates to {@link #chdIdentity(byte[])}. */
    public static Map<String, String> chdIdentity(File chd) {
        try {
            return chdIdentity(head(chd, CHD_HEADER_READ));
        } catch (IOException unreadable) {
            return Collections.emptyMap();
        }
    }

    private static void promoteRawHash(Map<String, String> result, String key, String algo) {
        String value = result.get(key);
        if (value != null && !value.isEmpty()) {
            result.put("chdRawHash", value);
            result.put("chdRawHashAlgo", algo);
        }
    }

    private static void putHashIfNonZero(Map<String, String> result, String key, byte[] data,
                                         int offset, int length) {
        if (offset < 0 || offset + length > data.length) return;
        boolean allZero = true;
        for (int i = 0; i < length; i++) if (data[offset + i] != 0) { allZero = false; break; }
        if (allZero) return;
        result.put(key, hexBytes(data, offset, length));
    }

    static String hexBytes(byte[] data, int offset, int length) {
        StringBuilder out = new StringBuilder(length * 2);
        for (int i = 0; i < length; i++) out.append(String.format(Locale.US, "%02X", data[offset + i] & 0xff));
        return out.toString();
    }

    // ---- ISO9660 ---------------------------------------------------------------

    private static Iso9660 openDisc(File rom, String lower) throws IOException {
        File image = rom;
        int sectorSize = 0;
        int dataOffset = 0;
        if (lower.endsWith(".cue")) {
            CueSheet cue = CueSheet.parse(rom);
            if (cue == null) return null;
            image = cue.bin;
            sectorSize = cue.sectorSize;
            dataOffset = cue.dataOffset;
        } else if (!(lower.endsWith(".iso") || lower.endsWith(".bin") || lower.endsWith(".img")
                || lower.endsWith(".mdf"))) {
            return null;
        }
        if (image == null || !image.isFile()) return null;
        RandomAccessFile file = new RandomAccessFile(image, "r");
        int[][] layouts = sectorSize > 0 ? new int[][] {{sectorSize, dataOffset}}
                : new int[][] {{2048, 0}, {2352, 24}, {2352, 16}, {2336, 8}};
        for (int[] layout : layouts) {
            Iso9660 iso = new Iso9660(file, layout[0], layout[1]);
            if (iso.valid()) return iso;
        }
        file.close();
        return null;
    }

    /** A minimal ISO9660 reader over an image with an arbitrary raw sector layout. */
    static final class Iso9660 {
        private final RandomAccessFile file;
        private final int sectorSize;
        private final int dataOffset;
        private long rootExtent;
        private long rootLength;

        Iso9660(RandomAccessFile file, int sectorSize, int dataOffset) {
            this.file = file;
            this.sectorSize = sectorSize;
            this.dataOffset = dataOffset;
        }

        boolean valid() {
            try {
                byte[] pvd = sector(16);
                if (pvd == null || pvd[0] != 1 || !"CD001".equals(ascii(pvd, 1, 5))) return false;
                rootExtent = u32le(pvd, 156 + 2);
                rootLength = u32le(pvd, 156 + 10);
                return rootLength > 0 && rootLength <= MAX_ISO_FILE_BYTES;
            } catch (IOException | RuntimeException failed) {
                return false;
            }
        }

        byte[] sector(long index) throws IOException {
            long at = index * (long) sectorSize + dataOffset;
            if (at < 0 || at + 2048 > file.length()) return null;
            file.seek(at);
            byte[] data = new byte[2048];
            file.readFully(data);
            return data;
        }

        /** Reads a file by path such as {@code PSP_GAME/PARAM.SFO}; null when absent. */
        byte[] readFile(String path, long cap) throws IOException {
            String[] parts = path.replace("\\", "/").split("/");
            long extent = rootExtent;
            long length = rootLength;
            for (int i = 0; i < parts.length; i++) {
                String want = parts[i].trim();
                if (want.isEmpty()) continue;
                boolean last = i == parts.length - 1;
                long[] found = find(extent, length, want, !last);
                if (found == null) return null;
                extent = found[0];
                length = found[1];
            }
            if (length > cap) return null;
            return read(extent, length);
        }

        private long[] find(long dirExtent, long dirLength, String name, boolean directory) throws IOException {
            if (dirLength > MAX_ISO_FILE_BYTES) return null;
            String wanted = name.toUpperCase(Locale.US);
            int wantedNoVersion = wanted.indexOf(';');
            if (wantedNoVersion > 0) wanted = wanted.substring(0, wantedNoVersion);
            long sectors = (dirLength + 2047) / 2048;
            for (long s = 0; s < sectors; s++) {
                byte[] data = sector(dirExtent + s);
                if (data == null) return null;
                int at = 0;
                while (at < 2048) {
                    int recordLength = data[at] & 0xff;
                    if (recordLength == 0) break;
                    if (at + recordLength > 2048 || recordLength < 33) break;
                    int nameLength = data[at + 32] & 0xff;
                    String entryName = ascii(data, at + 33, Math.min(nameLength, 2048 - at - 33))
                            .toUpperCase(Locale.US);
                    int version = entryName.indexOf(';');
                    if (version > 0) entryName = entryName.substring(0, version);
                    boolean isDirectory = (data[at + 25] & 2) != 0;
                    if (entryName.equals(wanted) && isDirectory == directory)
                        return new long[] {u32le(data, at + 2), u32le(data, at + 10)};
                    at += recordLength;
                }
            }
            return null;
        }

        private byte[] read(long extent, long length) throws IOException {
            if (length < 0 || length > MAX_ELF_BYTES) return null;
            byte[] out = new byte[(int) length];
            long remaining = length;
            int written = 0;
            long index = extent;
            while (remaining > 0) {
                byte[] data = sector(index++);
                if (data == null) return null;
                int chunk = (int) Math.min(2048, remaining);
                System.arraycopy(data, 0, out, written, chunk);
                written += chunk;
                remaining -= chunk;
            }
            return out;
        }

        void close() {
            try { file.close(); } catch (IOException ignored) { }
        }
    }

    /** The first FILE/TRACK pair of a cue sheet decides the raw sector layout. */
    static final class CueSheet {
        final File bin;
        final int sectorSize;
        final int dataOffset;

        private CueSheet(File bin, int sectorSize, int dataOffset) {
            this.bin = bin; this.sectorSize = sectorSize; this.dataOffset = dataOffset;
        }

        static CueSheet parse(File cue) throws IOException {
            if (cue == null || !cue.isFile() || cue.length() > 1024 * 1024) return null;
            String text = new String(head(cue, (int) cue.length()), StandardCharsets.ISO_8859_1);
            File bin = null;
            for (String raw : CodeText.lines(text)) {
                String line = raw.trim();
                if (line.regionMatches(true, 0, "FILE ", 0, 5) && bin == null) {
                    String name = line.substring(5).trim();
                    int quote = name.lastIndexOf('"');
                    if (name.startsWith("\"") && quote > 0) name = name.substring(1, quote);
                    else name = name.replaceAll("\\s+\\S+$", "");
                    bin = new File(cue.getParentFile(), new File(name).getName());
                } else if (line.regionMatches(true, 0, "TRACK ", 0, 6) && bin != null) {
                    String mode = line.substring(6).trim().toUpperCase(Locale.US);
                    if (mode.contains("MODE1/2048")) return new CueSheet(bin, 2048, 0);
                    if (mode.contains("MODE1/2352")) return new CueSheet(bin, 2352, 16);
                    if (mode.contains("MODE2/2352")) return new CueSheet(bin, 2352, 24);
                    if (mode.contains("MODE2/2336")) return new CueSheet(bin, 2336, 8);
                    if (mode.contains("AUDIO")) { bin = null; continue; }
                    return new CueSheet(bin, 2352, 24);
                }
            }
            return bin == null ? null : new CueSheet(bin, 2352, 24);
        }
    }

    // ---- helpers ---------------------------------------------------------

    public static String switchTitleId(String text) {
        if (text == null) return "";
        Matcher match = SWITCH_TITLE_ID.matcher(text);
        return match.find() ? match.group(1).toUpperCase(Locale.US) : "";
    }

    public static String serialInName(String text) {
        if (text == null) return "";
        Matcher match = SERIAL_IN_NAME.matcher(text);
        return match.find() ? (match.group(1) + "-" + match.group(2)).toUpperCase(Locale.US) : "";
    }

    public static String stem(String name) {
        if (name == null) return "";
        String base = name;
        int slash = Math.max(base.lastIndexOf('/'), base.lastIndexOf('\\'));
        if (slash >= 0) base = base.substring(slash + 1);
        int dot = base.lastIndexOf('.');
        if (dot > 0 && base.length() - dot <= 5) base = base.substring(0, dot);
        return base.trim();
    }

    /** True when both names normalise to the same catalogue key. */
    public static boolean sameTitle(String a, String b) {
        String left = CheatDatabase.normalise(a);
        return !left.isEmpty() && left.equals(CheatDatabase.normalise(b));
    }

    /** A comma-separated identity value, e.g. build ids. */
    public static List<String> split(String value) {
        List<String> result = new ArrayList<>();
        if (value == null) return result;
        for (String piece : value.split(",")) {
            String clean = piece.trim();
            if (!clean.isEmpty()) result.add(clean);
        }
        return result;
    }

    static byte[] head(File file, int count) throws IOException {
        if (file == null || !file.isFile()) return new byte[0];
        int size = (int) Math.min(count, Math.min(file.length(), 16L * 1024L * 1024L));
        byte[] data = new byte[size];
        try (InputStream input = new FileInputStream(file)) {
            int at = 0;
            while (at < size) {
                int read = input.read(data, at, size - at);
                if (read < 0) break;
                at += read;
            }
            if (at < size) {
                byte[] shorter = new byte[at];
                System.arraycopy(data, 0, shorter, 0, at);
                return shorter;
            }
        }
        return data;
    }

    static String ascii(byte[] data, int offset, int length) {
        if (data == null || offset < 0 || offset >= data.length) return "";
        int end = Math.min(data.length, offset + length);
        StringBuilder out = new StringBuilder();
        for (int i = offset; i < end; i++) {
            int ch = data[i] & 0xff;
            if (ch == 0) break;
            out.append(ch >= 0x20 && ch < 0x7f ? (char) ch : ' ');
        }
        return out.toString();
    }

    private static String cstring(byte[] data, int offset, int max) {
        int end = Math.min(data.length, offset + max);
        int stop = offset;
        while (stop < end && data[stop] != 0) stop++;
        return new String(data, offset, stop - offset, StandardCharsets.UTF_8).trim();
    }

    static long u32le(byte[] d, int at) {
        if (at < 0 || at + 4 > d.length) return 0;
        return (d[at] & 0xffL) | ((d[at + 1] & 0xffL) << 8) | ((d[at + 2] & 0xffL) << 16)
                | ((d[at + 3] & 0xffL) << 24);
    }

    static long u32be(byte[] d, int at) {
        if (at < 0 || at + 4 > d.length) return 0;
        return ((d[at] & 0xffL) << 24) | ((d[at + 1] & 0xffL) << 16) | ((d[at + 2] & 0xffL) << 8)
                | (d[at + 3] & 0xffL);
    }

    static int u16le(byte[] d, int at) {
        if (at < 0 || at + 2 > d.length) return 0;
        return (d[at] & 0xff) | ((d[at + 1] & 0xff) << 8);
    }

    static String hex64le(byte[] d, int at) {
        long value = 0;
        for (int i = 7; i >= 0; i--) value = (value << 8) | (d[at + i] & 0xffL);
        return String.format(Locale.US, "%016X", value);
    }

    static String hex64be(byte[] d, int at) {
        long value = 0;
        for (int i = 0; i < 8; i++) value = (value << 8) | (d[at + i] & 0xffL);
        return String.format(Locale.US, "%016X", value);
    }

    private static long align64(long value) { return (value + 0x3F) & ~0x3FL; }
}
