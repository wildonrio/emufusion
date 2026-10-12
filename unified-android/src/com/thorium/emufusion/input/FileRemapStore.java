package com.thorium.emufusion.input;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.EnumMap;
import java.util.Map;
import java.util.Properties;
import java.util.UUID;

/** Atomic properties-backed remaps suitable for app-private Android storage. */
public final class FileRemapStore implements RemapStore {
    private final File file;

    public FileRemapStore(File file) {
        if (file == null) throw new IllegalArgumentException("file is required");
        this.file = file;
    }

    @Override public synchronized Map<CanonicalControl, InputSignal> load(
            MappingScope scope, String deviceKey) throws IOException {
        Properties values = read();
        EnumMap<CanonicalControl, InputSignal> mapping = new EnumMap<>(CanonicalControl.class);
        String prefix = prefix(scope, deviceKey);
        for (CanonicalControl control : CanonicalControl.values()) {
            String encoded = values.getProperty(prefix + control.name());
            if (encoded != null) try { mapping.put(control, InputSignal.decode(encoded)); }
            catch (IllegalArgumentException ignored) { /* Ignore one damaged override. */ }
        }
        return mapping;
    }

    @Override public synchronized void save(MappingScope scope, String deviceKey,
            Map<CanonicalControl, InputSignal> mapping) throws IOException {
        Properties values = read();
        String prefix = prefix(scope, deviceKey);
        clearPrefix(values, prefix);
        for (Map.Entry<CanonicalControl, InputSignal> entry : mapping.entrySet())
            values.setProperty(prefix + entry.getKey().name(), entry.getValue().encode());
        write(values);
    }

    @Override public synchronized void clear(MappingScope scope, String deviceKey) throws IOException {
        Properties values = read();
        clearPrefix(values, prefix(scope, deviceKey));
        write(values);
    }

    private Properties read() throws IOException {
        Properties values = new Properties();
        if (!file.isFile()) return values;
        FileInputStream input = new FileInputStream(file);
        try { values.load(input); }
        finally { input.close(); }
        return values;
    }

    private void write(Properties values) throws IOException {
        File parent = file.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs())
            throw new IOException("Cannot create " + parent);
        File temporary = new File(parent, file.getName() + ".pending-" + UUID.randomUUID());
        FileOutputStream raw = new FileOutputStream(temporary);
        try {
            BufferedOutputStream buffered = new BufferedOutputStream(raw);
            values.store(buffered, "EmuFusion controller remaps");
            buffered.flush();
            raw.getFD().sync();
        } finally { raw.close(); }
        if (!temporary.renameTo(file)) {
            File backup = new File(parent, file.getName() + ".previous");
            if (backup.exists()) backup.delete();
            if (file.exists() && !file.renameTo(backup)) {
                temporary.delete();
                throw new IOException("Cannot stage existing remaps");
            }
            if (!temporary.renameTo(file)) {
                if (backup.exists()) backup.renameTo(file);
                throw new IOException("Cannot publish remaps");
            }
            if (backup.exists()) backup.delete();
        }
    }

    private static void clearPrefix(Properties values, String prefix) {
        for (String key : values.stringPropertyNames().toArray(new String[0]))
            if (key.startsWith(prefix)) values.remove(key);
    }

    private static String prefix(MappingScope scope, String deviceKey) {
        return encode(scope.systemId) + "." + encode(scope.gameId) + "." + encode(deviceKey) + ".";
    }

    private static String encode(String value) {
        byte[] bytes = (value == null ? "" : value).getBytes(StandardCharsets.UTF_8);
        final char[] alphabet =
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".toCharArray();
        StringBuilder result = new StringBuilder((bytes.length * 4 + 2) / 3);
        for (int index = 0; index < bytes.length; index += 3) {
            int first = bytes[index] & 0xff;
            int second = index + 1 < bytes.length ? bytes[index + 1] & 0xff : 0;
            int third = index + 2 < bytes.length ? bytes[index + 2] & 0xff : 0;
            result.append(alphabet[first >>> 2]);
            result.append(alphabet[((first & 3) << 4) | (second >>> 4)]);
            if (index + 1 < bytes.length)
                result.append(alphabet[((second & 15) << 2) | (third >>> 6)]);
            if (index + 2 < bytes.length) result.append(alphabet[third & 63]);
        }
        return result.toString();
    }
}
