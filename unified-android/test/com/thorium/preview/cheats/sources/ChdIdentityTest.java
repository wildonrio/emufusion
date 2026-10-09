package com.thorium.preview.cheats.sources;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Map;

/**
 * Synthetic CHD headers built exactly to the byte layout documented (and
 * cross-checked against {@code chd_file::parse_v3/v4/v5_header}) in MAME's
 * {@code src/lib/util/chd.h} (BSD-3-Clause): a fixed, version-dependent
 * struct starting with the {@code "MComprHD"} magic. Never a real CHD file --
 * only the header bytes {@link CheatGameIdentity#chdIdentity} actually reads.
 */
public final class ChdIdentityTest {
    public static void main(String[] args) throws Exception {
        v1v2Md5();
        v3Sha1AndLegacyMd5();
        v3ZeroShaFallsBackToNothing();
        v4SplitRawAndCombined();
        v5SplitRawAndCombined();
        unsupportedVersionReportsOnlyVersion();
        truncatedHeaderReportsOnlyVersion();
        badMagicAndShortHeaderRejected();
        wiredIntoIdentifyForChdExtension();
        notWiredForANonDiscSystem();
        System.out.println("ChdIdentityTest passed");
    }

    private static void v1v2Md5() {
        byte[] md5 = md5("raw-data-v1v2");
        for (int version : new int[] {1, 2}) {
            int size = version == 1 ? 76 : 80;
            byte[] header = new byte[size];
            tag(header);
            putBe32(header, 8, size);
            putBe32(header, 12, version);
            System.arraycopy(md5, 0, header, 44, 16);
            Map<String, String> id = CheatGameIdentity.chdIdentity(header);
            check(String.valueOf(version).equals(id.get("chdVersion")), "v" + version + " version: " + id);
            check(hex(md5).equals(id.get("chdMd5")), "v" + version + " md5: " + id);
            check(hex(md5).equals(id.get("chdRawHash")) && "md5".equals(id.get("chdRawHashAlgo")),
                    "v" + version + " raw hash promotion: " + id);
            check(!id.containsKey("chdSha1") && !id.containsKey("chdRawSha1"), "v" + version + " no sha1 fields");
        }
    }

    private static void v3Sha1AndLegacyMd5() {
        byte[] md5 = md5("raw-data-v3-legacy-md5");
        byte[] sha1 = sha1("raw-data-v3-sha1");
        byte[] header = new byte[120];
        tag(header);
        putBe32(header, 8, 120);
        putBe32(header, 12, 3);
        System.arraycopy(md5, 0, header, 44, 16);
        System.arraycopy(sha1, 0, header, 80, 20);
        Map<String, String> id = CheatGameIdentity.chdIdentity(header);
        check("3".equals(id.get("chdVersion")), "v3 version: " + id);
        check(hex(md5).equals(id.get("chdMd5")), "v3 legacy md5 retained: " + id);
        check(hex(sha1).equals(id.get("chdSha1")), "v3 sha1: " + id);
        check(hex(sha1).equals(id.get("chdRawHash")) && "sha1".equals(id.get("chdRawHashAlgo")),
                "v3 sha1 is the raw hash (v3 has no separate metadata split): " + id);
    }

    private static void v3ZeroShaFallsBackToNothing() {
        // A CHD whose SHA1 field was never populated: the legacy MD5 is
        // still reported for transparency, but it is not promoted as
        // "the" raw hash -- v3's raw-data field is specifically SHA1, and
        // silently substituting a differently-scoped hash would risk a
        // false positive match against a Redump DAT.
        byte[] md5 = md5("raw-data-v3-only-md5-known");
        byte[] header = new byte[120];
        tag(header);
        putBe32(header, 8, 120);
        putBe32(header, 12, 3);
        System.arraycopy(md5, 0, header, 44, 16);
        Map<String, String> id = CheatGameIdentity.chdIdentity(header);
        check(hex(md5).equals(id.get("chdMd5")), "v3 md5 present: " + id);
        check(!id.containsKey("chdSha1") && !id.containsKey("chdRawHash"), "v3 zero sha1 not promoted: " + id);
    }

    private static void v4SplitRawAndCombined() {
        byte[] combined = sha1("raw-data-v4-combined");
        byte[] raw = sha1("raw-data-v4-raw");
        byte[] header = new byte[108];
        tag(header);
        putBe32(header, 8, 108);
        putBe32(header, 12, 4);
        System.arraycopy(combined, 0, header, 48, 20);
        System.arraycopy(raw, 0, header, 88, 20);
        Map<String, String> id = CheatGameIdentity.chdIdentity(header);
        check("4".equals(id.get("chdVersion")), "v4 version: " + id);
        check(hex(combined).equals(id.get("chdSha1")), "v4 combined sha1: " + id);
        check(hex(raw).equals(id.get("chdRawSha1")), "v4 raw sha1: " + id);
        check(hex(raw).equals(id.get("chdRawHash")) && "sha1".equals(id.get("chdRawHashAlgo")),
                "v4 raw-only sha1 is the match hash, not the combined one: " + id);
        check(!id.get("chdSha1").equals(id.get("chdRawHash")), "v4 combined and raw actually differ: " + id);
    }

    private static void v5SplitRawAndCombined() {
        byte[] raw = sha1("raw-data-v5-raw");
        byte[] combined = sha1("raw-data-v5-combined");
        byte[] header = new byte[124];
        tag(header);
        putBe32(header, 8, 124);
        putBe32(header, 12, 5);
        System.arraycopy(raw, 0, header, 64, 20);
        System.arraycopy(combined, 0, header, 84, 20);
        Map<String, String> id = CheatGameIdentity.chdIdentity(header);
        check("5".equals(id.get("chdVersion")), "v5 version: " + id);
        check(hex(raw).equals(id.get("chdRawSha1")), "v5 raw sha1: " + id);
        check(hex(combined).equals(id.get("chdSha1")), "v5 combined sha1: " + id);
        check(hex(raw).equals(id.get("chdRawHash")) && "sha1".equals(id.get("chdRawHashAlgo")),
                "v5 raw-only sha1 is the match hash: " + id);
    }

    private static void unsupportedVersionReportsOnlyVersion() {
        byte[] header = new byte[124];
        tag(header);
        putBe32(header, 8, 124);
        putBe32(header, 12, 9);
        for (int i = 16; i < header.length; i++) header[i] = (byte) 0xAA; // never mistaken for a real hash
        Map<String, String> id = CheatGameIdentity.chdIdentity(header);
        check(id.size() == 1 && "9".equals(id.get("chdVersion")), "unknown version reports only chdVersion: " + id);
    }

    private static void truncatedHeaderReportsOnlyVersion() {
        // Claims to be a v5 header but the file was cut short: never decode
        // a hash from bytes that are not there.
        byte[] header = new byte[50];
        tag(header);
        putBe32(header, 8, 124);
        putBe32(header, 12, 5);
        Map<String, String> id = CheatGameIdentity.chdIdentity(header);
        check(id.size() == 1 && "5".equals(id.get("chdVersion")), "truncated header reports only chdVersion: " + id);
    }

    private static void badMagicAndShortHeaderRejected() {
        check(CheatGameIdentity.chdIdentity((byte[]) null).isEmpty(), "null header");
        check(CheatGameIdentity.chdIdentity(new byte[8]).isEmpty(), "too short for even the magic+length+version");
        byte[] wrongMagic = new byte[76];
        System.arraycopy("NotAChd!".getBytes(StandardCharsets.US_ASCII), 0, wrongMagic, 0, 8);
        check(CheatGameIdentity.chdIdentity(wrongMagic).isEmpty(), "wrong magic rejected");
    }

    private static void wiredIntoIdentifyForChdExtension() throws IOException {
        byte[] raw = sha1("psx-disc-raw-data");
        byte[] combined = sha1("psx-disc-combined");
        byte[] header = new byte[124];
        tag(header);
        putBe32(header, 8, 124);
        putBe32(header, 12, 5);
        System.arraycopy(raw, 0, header, 64, 20);
        System.arraycopy(combined, 0, header, 84, 20);
        File dir = Files.createTempDirectory("lucent-chd").toFile();
        File chd = new File(dir, "Some Game (USA).chd");
        write(chd, header);
        for (String system : new String[] {"psx", "ps2", "dreamcast", "segacd", "pcenginecd",
                "saturn", "neogeocd", "3do", "amigacd32"}) {
            Map<String, String> id = CheatGameIdentity.identify(system, chd, "");
            check(hex(raw).equals(id.get("chdRawHash")), system + " chd identity wired in: " + id);
            check("5".equals(id.get("chdVersion")), system + " chd version present: " + id);
        }
    }

    private static void notWiredForANonDiscSystem() throws IOException {
        byte[] header = new byte[76];
        tag(header);
        putBe32(header, 8, 76);
        putBe32(header, 12, 1);
        System.arraycopy(md5("irrelevant"), 0, header, 44, 16);
        File dir = Files.createTempDirectory("lucent-chd-2").toFile();
        File chd = new File(dir, "not-a-disc-system.chd");
        write(chd, header);
        Map<String, String> id = CheatGameIdentity.identify("gba", chd, "");
        check(!id.containsKey("chdRawHash") && !id.containsKey("chdVersion"),
                "a cartridge system's .chd (not a real combination) is never chd-decoded: " + id);
    }

    // ---- fixtures -----------------------------------------------------------

    private static void tag(byte[] header) {
        System.arraycopy("MComprHD".getBytes(StandardCharsets.US_ASCII), 0, header, 0, 8);
    }

    private static void putBe32(byte[] d, int at, long v) {
        d[at] = (byte) (v >> 24); d[at + 1] = (byte) (v >> 16); d[at + 2] = (byte) (v >> 8); d[at + 3] = (byte) v;
    }

    private static byte[] md5(String seed) { return digest("MD5", seed); }

    private static byte[] sha1(String seed) { return digest("SHA-1", seed); }

    private static byte[] digest(String algorithm, String seed) {
        try {
            return MessageDigest.getInstance(algorithm).digest(seed.getBytes(StandardCharsets.UTF_8));
        } catch (Exception impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static String hex(byte[] data) {
        StringBuilder out = new StringBuilder();
        for (byte b : data) out.append(String.format(java.util.Locale.US, "%02X", b & 0xff));
        return out.toString();
    }

    private static void write(File file, byte[] data) throws IOException {
        try (FileOutputStream out = new FileOutputStream(file)) { out.write(data); }
    }

    static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
