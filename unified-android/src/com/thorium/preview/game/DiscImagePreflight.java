package com.thorium.preview.game;

import java.io.File;
import java.io.BufferedInputStream;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Locale;

/** Fail-closed validation for disc containers before an in-process core sees them. */
public final class DiscImagePreflight {
    private static final int HEADER_1_SIZE = 0x48;
    private static final int HEADER_1_HASH_OFFSET = 0x34;
    private static final int HEADER_2_HASH_OFFSET = 0x10;
    private static final int HEADER_2_SIZE_OFFSET = 0x0c;
    private static final int CONTAINER_SIZE_OFFSET = 0x2c;
    private static final int HEADER_2_MIN_SIZE = 0xd5;

    private DiscImagePreflight() {}

    /** A diagnosed container problem whose explanation can be shown at launch. */
    public static final class InvalidImageException extends IOException {
        private InvalidImageException(String message) { super(message); }
    }

    public static void validate(String systemId, File file) throws Exception {
        if (file == null || !file.isFile())
            throw new IllegalArgumentException("Game image is missing");
        String lower = file.getName().toLowerCase(Locale.US);
        if (lower.endsWith(".chd")) validateChd(file);
        if (("gamecube".equals(systemId) || "wii".equals(systemId)) &&
                (lower.endsWith(".rvz") || lower.endsWith(".wia")))
            validateWiaRvz(file, lower.endsWith(".rvz"));
        if ("wiiu".equals(systemId) && lower.endsWith(".wux"))
            validateWux(file);
    }

    private static void validateChd(File file) throws IOException {
        // The bundled libchdr reads these v5 offsets before decoding hunks.
        // A missing map is a truncated transfer, not a renderer/BIOS failure.
        // Older CHD formats remain the core's responsibility.
        try (RandomAccessFile input = new RandomAccessFile(file, "r")) {
            long length = input.length();
            if (length < 16) throw invalid(file, "container header is incomplete");
            byte[] header = new byte[124];
            input.readFully(header, 0, 16);
            if (!Arrays.equals(Arrays.copyOf(header, 8),
                    new byte[]{'M','C','o','m','p','r','H','D'}))
                throw invalid(file, "container signature does not match its extension");
            if (readUnsignedIntBigEndian(header, 12) != 5) return;
            if (readUnsignedIntBigEndian(header, 8) != 124 || length < 124)
                throw invalid(file, "v5 container header is incomplete or invalid");
            input.readFully(header, 16, 108);
            long map = readUnsignedLongBigEndian(header, 40);
            long metadata = readUnsignedLongBigEndian(header, 48);
            boolean compressed = readUnsignedIntBigEndian(header, 16) != 0;
            int mapHeader = compressed ? 16 : 4;
            if (map < 124 || map > length - mapHeader ||
                    (metadata != 0 && (metadata < 124 || metadata > length - 16)))
                throw invalid(file, "game data is incomplete (map or metadata is beyond " +
                        length + " bytes). Re-copy the complete game image.");
            if (compressed) {
                input.seek(map);
                long mapBytes = input.readInt() & 0xffffffffL;
                if (mapBytes > length - map - 16)
                    throw invalid(file, "compressed map is incomplete. Re-copy the complete game image.");
            }
        }
    }

    private static void validateWux(File file) throws IOException {
        // Cemu's WUD reader uses a 32-byte little-endian WUX header, then one
        // uint32 physical-sector index per logical sector. Check only that
        // table (about 3 MB for a normal Wii U disc), never hash/read the disc.
        long length = file.length();
        if (length < 32) throw invalid(file, "container header is incomplete");
        try (InputStream input = new BufferedInputStream(new FileInputStream(file))) {
            byte[] header = new byte[32];
            readFully(input, header);
            if (readUnsignedIntLittleEndian(header, 0) != 0x30585557L ||
                    readUnsignedIntLittleEndian(header, 4) != 0x1099d02eL)
                throw invalid(file, "container signature does not match its extension");
            long sector = readUnsignedIntLittleEndian(header, 8);
            if (sector < 0x100L || sector >= 0x10000000L)
                throw invalid(file, "sector size is invalid");
            if ((header[23] & 0x80) != 0)
                throw invalid(file, "logical disc size is invalid");
            long logical = readUnsignedIntLittleEndian(header, 16) |
                    (readUnsignedIntLittleEndian(header, 20) << 32);
            if (logical <= 0) throw invalid(file, "logical disc size is invalid");
            long entries = 1 + (logical - 1) / sector;
            if (entries > 0xffffffffL)
                throw invalid(file, "sector table length is invalid");
            long tableEnd = 32 + entries * 4;
            if (tableEnd > length)
                throw invalid(file, "sector table is incomplete. Re-copy the complete game image.");
            long dataOffset = ((tableEnd + sector - 1) / sector) * sector;
            long required = dataOffset;
            byte[] chunk = new byte[16384];
            for (long done = 0; done < entries;) {
                int count = (int) Math.min(chunk.length / 4, entries - done);
                readFully(input, chunk, count * 4);
                for (int index = 0; index < count; index++, done++) {
                    long physical = readUnsignedIntLittleEndian(chunk, index * 4);
                    // The final logical sector need not use every byte.
                    long used = done == entries - 1 ? logical - done * sector : sector;
                    required = Math.max(required, dataOffset + physical * sector + used);
                }
            }
            if (required > length)
                throw invalid(file, "game data is incomplete (needs at least " + required +
                        " bytes, found " + length + "). Re-copy the complete game image.");
        }
    }

    private static void validateWiaRvz(File file, boolean rvz) throws Exception {
        byte[] header1 = new byte[HEADER_1_SIZE];
        try (InputStream input = new FileInputStream(file)) {
            readFully(input, header1);
            byte[] expectedMagic = rvz ?
                    new byte[]{'R', 'V', 'Z', 1} : new byte[]{'W', 'I', 'A', 1};
            if (!Arrays.equals(expectedMagic, Arrays.copyOf(header1, 4)))
                throw invalid(file, "container signature does not match its extension");

            long declaredSize = readUnsignedLongBigEndian(header1, CONTAINER_SIZE_OFFSET);
            if (declaredSize < HEADER_1_SIZE || declaredSize != file.length())
                throw invalid(file, "container is truncated (declared " + declaredSize +
                        " bytes, found " + file.length() + ")");

            byte[] expectedHeader1Hash = Arrays.copyOfRange(
                    header1, HEADER_1_HASH_OFFSET, HEADER_1_SIZE);
            if (!Arrays.equals(sha1(header1, 0, HEADER_1_HASH_OFFSET), expectedHeader1Hash))
                throw invalid(file, "container header checksum is invalid");

            long header2SizeLong = readUnsignedIntBigEndian(header1, HEADER_2_SIZE_OFFSET);
            if (header2SizeLong < HEADER_2_MIN_SIZE ||
                    header2SizeLong > file.length() - HEADER_1_SIZE ||
                    header2SizeLong > Integer.MAX_VALUE)
                throw invalid(file, "secondary header length is invalid");
            byte[] header2 = new byte[(int) header2SizeLong];
            readFully(input, header2);
            byte[] expectedHeader2Hash = Arrays.copyOfRange(
                    header1, HEADER_2_HASH_OFFSET, HEADER_2_HASH_OFFSET + 20);
            if (!Arrays.equals(sha1(header2, 0, header2.length), expectedHeader2Hash))
                throw invalid(file, "secondary header checksum is invalid");
        }
    }

    private static InvalidImageException invalid(File file, String detail) {
        return new InvalidImageException("Invalid " + extension(file) + " image: " + detail);
    }

    private static String extension(File file) {
        String name = file.getName();
        int dot = name.lastIndexOf('.');
        return dot >= 0 ? name.substring(dot + 1).toUpperCase(Locale.US) : "disc";
    }

    private static void readFully(InputStream input, byte[] output) throws IOException {
        readFully(input, output, output.length);
    }

    private static void readFully(InputStream input, byte[] output, int length) throws IOException {
        int offset = 0;
        while (offset < length) {
            int count = input.read(output, offset, length - offset);
            if (count < 0) throw new IOException("Unexpected end of disc image header");
            offset += count;
        }
    }

    private static long readUnsignedIntLittleEndian(byte[] data, int offset) {
        return (data[offset] & 0xffL) | ((data[offset + 1] & 0xffL) << 8) |
                ((data[offset + 2] & 0xffL) << 16) | ((data[offset + 3] & 0xffL) << 24);
    }

    private static long readUnsignedIntBigEndian(byte[] data, int offset) {
        return ((long) (data[offset] & 0xff) << 24) |
                ((long) (data[offset + 1] & 0xff) << 16) |
                ((long) (data[offset + 2] & 0xff) << 8) |
                (long) (data[offset + 3] & 0xff);
    }

    private static long readUnsignedLongBigEndian(byte[] data, int offset) throws IOException {
        if ((data[offset] & 0x80) != 0)
            throw new IOException("Disc image declares an unsupported size");
        long value = 0;
        for (int index = 0; index < 8; index++)
            value = (value << 8) | (data[offset + index] & 0xffL);
        return value;
    }

    private static byte[] sha1(byte[] data, int offset, int count) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-1");
        digest.update(data, offset, count);
        return digest.digest();
    }
}
