package com.thorium.emufusion.state;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

final class AtomicFiles {
    interface OutputWriter { void write(OutputStream output) throws IOException; }

    private AtomicFiles() {}

    static void writeSynced(File file, OutputWriter writer) throws IOException {
        File parent = file.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs())
            throw new IOException("Cannot create " + parent);
        FileOutputStream raw = new FileOutputStream(file);
        boolean complete = false;
        try {
            BufferedOutputStream buffered = new BufferedOutputStream(raw, 32 * 1024);
            writer.write(buffered);
            buffered.flush();
            raw.getFD().sync();
            complete = true;
        } finally {
            try { raw.close(); } finally { if (!complete) file.delete(); }
        }
    }

    static void replace(File temporary, File target) throws IOException {
        if (!temporary.isFile()) throw new IOException("Missing temporary file " + temporary);
        // Android/Linux rename replaces a file atomically. Some host JVMs refuse
        // replacement, so retain and restore a backup for that fallback path.
        if (temporary.renameTo(target)) {
            syncDirectory(target.getParentFile());
            return;
        }
        File backup = new File(target.getParentFile(), target.getName() + ".previous");
        if (backup.exists() && !backup.delete()) throw new IOException("Cannot clear " + backup);
        if (target.exists() && !target.renameTo(backup))
            throw new IOException("Cannot stage existing " + target);
        if (!temporary.renameTo(target)) {
            if (backup.exists()) backup.renameTo(target);
            syncDirectory(target.getParentFile());
            throw new IOException("Cannot publish " + target);
        }
        if (backup.exists()) backup.delete();
        syncDirectory(target.getParentFile());
    }

    static void publishDirectory(File temporary, File target) throws IOException {
        if (!temporary.isDirectory() || target.exists() || !temporary.renameTo(target))
            throw new IOException("Cannot publish snapshot " + target);
        syncDirectory(target.getParentFile());
    }

    /** Recovers the fallback replace sequence if the process died after staging the old file. */
    static void recoverPrevious(File target) throws IOException {
        if (target == null) throw new IOException("Missing atomic target");
        File parent = target.getParentFile();
        File backup = new File(parent, target.getName() + ".previous");
        if (target.isFile()) {
            if (backup.exists() && !backup.delete())
                throw new IOException("Cannot clear stale backup " + backup);
            return;
        }
        if (backup.isFile() && !backup.renameTo(target))
            throw new IOException("Cannot recover previous file " + backup);
        if (target.isFile()) syncDirectory(parent);
    }

    static long size(File file) {
        if (file == null || !file.exists()) return 0L;
        if (file.isFile()) return file.length();
        long total = 0L;
        File[] children = file.listFiles();
        if (children != null) for (File child : children) total += size(child);
        return total;
    }

    static boolean deleteTree(File file) {
        if (file == null || !file.exists()) return true;
        File[] children = file.listFiles();
        if (children != null) for (File child : children)
            if (!deleteTree(child)) return false;
        return file.delete();
    }

    /** Best-effort directory fsync on Android API 21+; harmless on host JVMs. */
    static void syncDirectory(File directory) {
        if (directory == null || !directory.isDirectory()) return;
        Object descriptor = null;
        Class<?> os = null;
        try {
            os = Class.forName("android.system.Os");
            Class<?> constants = Class.forName("android.system.OsConstants");
            Field readOnly = constants.getField("O_RDONLY");
            int flags = readOnly.getInt(null);
            try { flags |= constants.getField("O_DIRECTORY").getInt(null); }
            catch (ReflectiveOperationException ignored) {}
            Method open = os.getMethod("open", String.class, int.class, int.class);
            descriptor = open.invoke(null, directory.getAbsolutePath(), flags, 0);
            os.getMethod("fsync", java.io.FileDescriptor.class).invoke(null, descriptor);
        } catch (Throwable ignored) {
            // Directory fsync is unavailable on ordinary host JVMs and some OEM builds.
        } finally {
            if (descriptor != null && os != null) try {
                os.getMethod("close", java.io.FileDescriptor.class).invoke(null, descriptor);
            } catch (Throwable ignored) {}
        }
    }
}
