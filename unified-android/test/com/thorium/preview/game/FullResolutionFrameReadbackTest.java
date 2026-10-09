package com.thorium.preview.game;

import java.nio.ByteBuffer;

public final class FullResolutionFrameReadbackTest {
    static final class Fake implements FullResolutionFrameReadback.Backend {
        int bytes, queued, completed, closes, ready = 3;
        boolean wrongTag, pending;
        long queuedPresent;
        public int configure(int w, int h, int count) { bytes = count; return 15; }
        public int enqueue(long sequence, long present) { ++queued; queuedPresent = present; return 0; }
        public long[] poll(long present, ByteBuffer output) {
            if (pending || completed == queued || completed == ready) return new long[0];
            ++completed;
            for (int i = 0; i < bytes; ++i) output.put((byte) completed);
            long[] row = new long[15];
            row[3] = wrongTag ? 99 : completed;
            row[4] = queuedPresent;
            row[5] = bytes;
            row[6] = 1;
            return row;
        }
        public void close() { ++closes; }
    }
    public static void main(String[] ignored) {
        Fake good = new Fake();
        FullResolutionFrameReadback capture = new FullResolutionFrameReadback(good, 256, 192, 4, 42);
        for (int i = 0; i < 3; ++i) capture.enqueue(100);
        good.pending = true;
        check(capture.poll(101, 4, 42) == null, "pending GPU does not block or yield proof");
        good.pending = false;
        byte[][] result = capture.poll(101, 4, 42);
        check(result != null, "all ready planes drain in one callback");
        check(result.length == 3 && result[0].length == 256 * 192 * 4,
                "native dimensions retained");
        check(result[0][0] == 1 && result[1][0] == 2 && result[2][0] == 3,
                "G/A/B independently preserved");
        check(good.closes == 1 && capture.poll(104, 4, 42) == null, "one-shot cleanup");
        Fake partial = new Fake();
        capture = new FullResolutionFrameReadback(partial, 2, 2, 4, 42);
        for (int i = 0; i < 3; ++i) capture.enqueue(100);
        partial.ready = 1;
        check(capture.poll(101, 4, 42) == null && partial.completed == 1,
                "partial readiness yields without fabricating a triplet");
        partial.ready = 3;
        check(capture.poll(102, 4, 42).length == 3, "remaining ready planes drain together");
        Fake stale = new Fake();
        capture = new FullResolutionFrameReadback(stale, 2, 2, 4, 42);
        capture.enqueue(100);
        check(capture.poll(101, 5, 42) == null && stale.closes == 1,
                "old epoch cannot return images");
        Fake bad = new Fake();
        capture = new FullResolutionFrameReadback(bad, 2, 2, 4, 42);
        capture.enqueue(100);
        bad.wrongTag = true;
        try { capture.poll(101, 4, 42); throw new AssertionError("wrong tag accepted"); }
        catch (IllegalStateException expected) { check(bad.closes == 1, "bad transfer cleaned"); }
        Fake timeout = new Fake();
        capture = new FullResolutionFrameReadback(timeout, 2, 2, 4, 42);
        capture.enqueue(100);
        timeout.pending = true;
        check(capture.poll(109, 4, 42) == null && timeout.closes == 1,
                "GPU that never returns still releases bounded capture");
        Fake mixed = new Fake();
        capture = new FullResolutionFrameReadback(mixed, 2, 2, 4, 42);
        capture.enqueue(100);
        try { capture.enqueue(101); throw new AssertionError("mixed triplet accepted"); }
        catch (IllegalStateException expected) { check(mixed.closes == 1, "mixed capture closed"); }
        System.out.println("FullResolutionFrameReadbackTest passed");
    }
    static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
