package com.thorium.preview.game;

import android.util.Log;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.concurrent.atomic.AtomicLong;
import java.util.zip.CRC32;

/** Bounded logcat records; a missing part never becomes a partial timing pass. */
final class CadenceSnapshotLog {
    private static final AtomicLong SEQUENCE = new AtomicLong();
    private static final int CHARS_PER_PART = 700;

    static void write(String tag, long generator, String snapshot) {
        String identity = android.os.Process.myPid() + ":" + generator + ":" +
                SEQUENCE.incrementAndGet();
        for (String part : parts(identity, snapshot)) Log.i(tag, part);
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
