package com.thorium.emufusion.state;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.UUID;

/** Crash-safe bounded storage for battery-backed emulator memory. */
public final class DurableBlobStore {
    private DurableBlobStore() {}

    public static void write(File target, final byte[] value, int maximumBytes)
            throws IOException {
        if (target == null || value == null || value.length > maximumBytes || maximumBytes < 1)
            throw new IOException("Invalid durable blob");
        AtomicFiles.recoverPrevious(target);
        File temporary = new File(target.getParentFile(), target.getName() +
                ".pending-" + UUID.randomUUID());
        AtomicFiles.writeSynced(temporary, new AtomicFiles.OutputWriter() {
            @Override public void write(OutputStream output) throws IOException {
                output.write(value);
            }
        });
        AtomicFiles.replace(temporary, target);
    }

    public static byte[] read(File target, int maximumBytes) throws IOException {
        if (target == null || maximumBytes < 1) throw new IOException("Invalid durable blob");
        AtomicFiles.recoverPrevious(target);
        if (!target.isFile()) return null;
        long length = target.length();
        if (length < 0 || length > maximumBytes) throw new IOException("Durable blob is too large");
        InputStream input = new FileInputStream(target);
        try {
            ByteArrayOutputStream output = new ByteArrayOutputStream((int) length);
            byte[] buffer = new byte[32 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                if (count == 0) continue;
                if (output.size() > maximumBytes - count)
                    throw new IOException("Durable blob exceeds its limit");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        } finally { input.close(); }
    }

}
