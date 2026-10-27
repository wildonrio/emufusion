package com.thorium.preview.game;

import android.util.Log;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;
import java.util.zip.CRC32;

/**
 * Bounded logcat records; a missing part never becomes a partial timing pass.
 *
 * <p>The checksum, the split and the log writes run on a background thread:
 * a snapshot is about ten log records, written once a second from the
 * presenter thread, and the presenter must not wait on logd.</p>
 */
final class CadenceSnapshotLog {
    private static final AtomicLong SEQUENCE = new AtomicLong();
    private static final int CHARS_PER_PART = 700;
    private static final ExecutorService WRITER = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(() -> {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_BACKGROUND);
            runnable.run();
        }, "emufusion-cadence-log");
        thread.setDaemon(true);
        return thread;
    });

    static void write(String tag, long generator, String snapshot) {
        String identity = android.os.Process.myPid() + ":" + generator + ":" +
                SEQUENCE.incrementAndGet();
        try {
            WRITER.execute(() -> {
                for (String part : parts(identity, snapshot)) Log.i(tag, part);
            });
        } catch (RuntimeException rejected) {
            for (String part : parts(identity, snapshot)) Log.i(tag, part);
        }
    }

    /** Waits until the snapshots written so far are in the log (tests). */
    static void drain(long timeoutMs) throws InterruptedException {
        java.util.concurrent.CountDownLatch done = new java.util.concurrent.CountDownLatch(1);
        WRITER.execute(done::countDown);
        done.await(timeoutMs, java.util.concurrent.TimeUnit.MILLISECONDS);
    }

    static String[] parts(String identity, String snapshot) {
        CRC32 crc = new CRC32();
        crc.update(snapshot.getBytes(StandardCharsets.UTF_8));
        ArrayList<String> chunks = new ArrayList<>();
        for (int start = 0; start < snapshot.length();) {
            int end = Math.min(snapshot.length(), start + CHARS_PER_PART);
            if (end < snapshot.length() && Character.isHighSurrogate(snapshot.charAt(end - 1)))
                --end;
            chunks.add(snapshot.substring(start, end));
            start = end;
        }
        int count = chunks.size();
        String[] result = new String[count];
        for (int i = 0; i < count; ++i) {
            result[i] = "CadenceSnapshot id=" + identity + " part=" + (i + 1) +
                    "/" + count + " crc=" + crc.getValue() + " data=" +
                    chunks.get(i);
        }
        return result;
    }
}
