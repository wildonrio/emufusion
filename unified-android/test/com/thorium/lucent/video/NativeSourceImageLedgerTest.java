package com.thorium.lucent.video;

import java.lang.management.ManagementFactory;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Executes production parser/transfer/ledger methods; no Android or image-quality proof. */
public final class NativeSourceImageLedgerTest {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static ByteBuffer image(long frame, long pts) {
        ByteBuffer b = ByteBuffer.allocateDirect(NativeSourceImage.IMAGE_BYTES)
                .order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(0, 1); b.putInt(4, NativeSourceImage.IMAGE_BYTES); b.putInt(8, 1);
        b.putLong(16, frame); b.putLong(24, pts);
        b.putLong(40, 11); b.putLong(48, 22); b.putLong(56, 33);
        b.putLong(72, frame); b.putLong(80, pts - 100);
        b.putInt(88, 1); b.putInt(92, 1); b.putInt(96, 1);
        b.putLong(104, 44); b.putLong(112, frame); b.putLong(120, -700 + frame);
        b.putInt(128, 7); b.putInt(132, (int) frame % 3);
        b.putInt(136, 2); b.putInt(140, 2); b.putInt(144, 1);
        b.putInt(148, 1280); b.putInt(152, 720); b.putInt(156, 1280);
        b.putInt(160, 1); b.putInt(184, 1280); b.putInt(188, 720);
        return b;
    }
    private static NativeSourceImage.Slot snapshot(ByteBuffer b, long pts) {
        NativeSourceImage.Slot slot = new NativeSourceImage.Slot();
        check(NativeSourceImage.decode(1, b, 11, 22, pts, slot) ==
                NativeSourceImage.Decode.ACCEPTED, "fixture accepted");
        return slot;
    }
    private static long observe(NativeSourceImageLedger ledger, int index,
                                long provider, long pts, ByteBuffer bytes) {
        check(ledger.observe(index, provider, pts, 11, 22, 1, bytes) ==
                NativeSourceImageLedger.Result.SUCCESS, "observe");
        return ledger.lease(index);
    }
    private static NativeSourceImage.Pair pair(ByteBuffer b) {
        NativeSourceImageLedger ledger = new NativeSourceImageLedger(2);
        long a = observe(ledger, 0, 1, 1100, image(1, 1100));
        long c = observe(ledger, 1, 1, 2100, b);
        return ledger.compare(0, a, 1, c);
    }

    private static void snapshots() {
        NativeSourceImage.Slot source = snapshot(image(1, 1100), 1100);
        NativeSourceImage.Slot copy = new NativeSourceImage.Slot();
        check(copy.copyFrom(source) == NativeSourceImage.Transfer.COPIED, "sealed copy");
        check(source.isSealed() && copy.queueFrameNumber(0) == 1, "copy preserves source");
        check(copy.guestRequestedTimestampNs(0) == -699, "original guest value preserved");
        NativeSourceImage.Slot other = snapshot(image(2, 2100), 2100);
        check(copy.moveFrom(other) == NativeSourceImage.Transfer.DESTINATION_OCCUPIED,
                "occupied destination rejects move");
        check(other.isSealed() && copy.queueFrameNumber(0) == 1, "failed move releases neither");
        check(source.moveFrom(source) == NativeSourceImage.Transfer.BAD_ARGUMENT &&
                source.isSealed(), "self move never clears");
        check(copy.copyFrom(null) == NativeSourceImage.Transfer.BAD_ARGUMENT, "null");
        copy.clear();
        check(!copy.isSealed() && copy.queueFrameNumber(0) == 0 &&
                copy.bufferTimestampNs() == 0, "cleared bytes not readable");
        check(copy.moveFrom(other) == NativeSourceImage.Transfer.MOVED, "move");
        check(copy.queueFrameNumber(0) == 2 && !other.isSealed(), "destination sealed before source clear");
        source.release();
        check(source.copyFrom(other) == NativeSourceImage.Transfer.SOURCE_EMPTY, "empty source");
    }

    private static void retention() throws Exception {
        NativeSourceImageLedger ledger = new NativeSourceImageLedger(4);
        check(ledger.capacity() == 4 && ledger.lease(-1) == 0, "bounds");
        long original = observe(ledger, 0, 8, 1100, image(1, 1100));
        check(ledger.observe(0, 9, 2100, 11, 22, 1, image(2, 2100)) ==
                NativeSourceImageLedger.Result.OCCUPIED, "no overwrite");
        check(ledger.rawTimestampNs(0, original) == 1100 &&
                ledger.providerGeneration(0, original) == 8, "exact tuple unchanged");
        check(ledger.copy(0, original, 1) == NativeSourceImageLedger.Result.SUCCESS, "copy candidate");
        long copied = ledger.lease(1);
        check(copied != original && ledger.lease(0) == original, "independent occupancy");
        check(ledger.move(1, copied, 0) == NativeSourceImageLedger.Result.OCCUPIED &&
                ledger.lease(1) == copied, "failed destination preserves source");
        check(ledger.move(1, copied, 2) == NativeSourceImageLedger.Result.SUCCESS, "FIFO/history transfer");
        long moved = ledger.lease(2);
        check(ledger.lease(1) == 0 && ledger.queueFrameNumber(2, moved, 0) == 1,
                "original queue identity never renumbered");
        check(ledger.release(2, copied) == NativeSourceImageLedger.Result.STALE_LEASE,
                "source lease cannot clear destination");
        check(ledger.move(2, moved, 2) == NativeSourceImageLedger.Result.BAD_ARGUMENT &&
                ledger.lease(2) == moved, "ledger self move");
        check(ledger.release(0, original) == NativeSourceImageLedger.Result.SUCCESS, "retired source");
        long reused = observe(ledger, 0, 8, 1100, image(1, 1100));
        check(reused != original && ledger.release(0, original) ==
                NativeSourceImageLedger.Result.STALE_LEASE, "ABA same PTS rejected");
        check(ledger.compare(0, original, 2, moved) == NativeSourceImage.Pair.STALE_RETENTION,
                "stale comparison rejected");
        NativeSourceImage.Slot out = new NativeSourceImage.Slot();
        check(ledger.copySnapshot(2, moved, out) == NativeSourceImage.Transfer.COPIED, "sealed export");
        out.clear();
        check(ledger.queueFrameNumber(2, moved, 0) == 1, "export cannot mutate internal record");

        Field counter = NativeSourceImageLedger.class.getDeclaredField("lastLease");
        counter.setAccessible(true); counter.setLong(ledger, Long.MAX_VALUE);
        check(ledger.move(2, moved, 3) == NativeSourceImageLedger.Result.LEASE_EXHAUSTED &&
                ledger.lease(2) == moved && ledger.lease(3) == 0, "overflow preserves ownership");
        check(ledger.observe(3, 8, 1100, 11, 22, 1, image(1, 1100)) ==
                NativeSourceImageLedger.Result.LEASE_EXHAUSTED, "observe never wraps");
    }

    private static void evidence() {
        NativeSourceImageLedger ledger = new NativeSourceImageLedger(4);
        long a = observe(ledger, 0, 1, 1100, image(1, 1100));
        long b = observe(ledger, 1, 1, 2100, image(2, 2100));
        check(ledger.compare(0, a, 1, b) == NativeSourceImage.Pair.ADJACENT_QUEUED_IMAGES, "adjacent");
        long missing = observe(ledger, 2, 1, 0, image(2, 2100));
        check(ledger.missingPts(2, missing) &&
                ledger.observation(2, missing) == NativeSourceImage.Decode.BAD_ARGUMENT &&
                ledger.compare(0, a, 2, missing) == NativeSourceImage.Pair.MISSING_PTS,
                "missing raw PTS never substituted");
        long different = observe(ledger, 3, 2, 2100, image(2, 2100));
        check(ledger.compare(0, a, 3, different) == NativeSourceImage.Pair.PROVIDER_CHANGED,
                "provider switch invalidates pair");
        ByteBuffer held = image(2, 2100);
        held.putLong(112, 1); held.putLong(120, -699); held.putInt(132, 1); held.putInt(144, 2);
        check(pair(held) == NativeSourceImage.Pair.HELD_QUEUED_IMAGE, "held not adjacent");
        ByteBuffer gap = image(3, 2100);
        check(pair(gap) == NativeSourceImage.Pair.QUEUE_FRAME_GAP, "original gap not host-renumbered");
        ByteBuffer epoch = image(2, 2100); epoch.putLong(56, 34);
        check(pair(epoch) == NativeSourceImage.Pair.EPOCH_CHANGED, "swapchain epoch");
        ByteBuffer geometry = image(2, 2100); geometry.putInt(168, 1);
        check(pair(geometry) == NativeSourceImage.Pair.GEOMETRY_CHANGED, "transform");
        geometry = image(2, 2100); geometry.putInt(176, 1);
        check(pair(geometry) == NativeSourceImage.Pair.GEOMETRY_CHANGED, "crop");
        ByteBuffer wrong = image(2, 2101);
        NativeSourceImageLedger absent = new NativeSourceImageLedger(3);
        long wrongLease = observe(absent, 0, 1, 2100, wrong);
        check(absent.observation(0, wrongLease) == NativeSourceImage.Decode.WRONG_IMAGE,
                "one ns mismatch never nearest matched");
        ByteBuffer pending = image(2, 2100); pending.putInt(8, 2);
        check(absent.observe(1, 1, 2100, 11, 22, 2, pending) ==
                NativeSourceImageLedger.Result.SUCCESS, "retain pending");
        long p = absent.lease(1);
        check(absent.observation(1, p) == NativeSourceImage.Decode.PENDING &&
                absent.queueFrameNumber(1, p, 0) == 0, "pending has no sealed authority");
        check(absent.copy(1, p, 2) == NativeSourceImageLedger.Result.SUCCESS &&
                absent.observation(2, absent.lease(2)) == NativeSourceImage.Decode.PENDING,
                "pending follows exact retained slot, not relabeled accepted");
        check(absent.sessionEpoch(2, absent.lease(2)) == 11 &&
                absent.surfaceEpoch(2, absent.lease(2)) == 22 &&
                absent.rawTimestampNs(2, absent.lease(2)) == 2100, "complete pending key preserved");
        check(absent.observe(1, 1, 2100, 11, 22, 1, image(2, 2100)) ==
                NativeSourceImageLedger.Result.OCCUPIED, "no in-place retry completion");
        check(absent.compare(1, p, 2, absent.lease(2)) == NativeSourceImage.Pair.MISSING_IMAGE,
                "pending pair unqualified");
        check(absent.release(2, absent.lease(2)) == NativeSourceImageLedger.Result.SUCCESS, "release pending");
        check(absent.observe(2, 1, 2100, 11, 22, 3, null) == NativeSourceImageLedger.Result.SUCCESS &&
                absent.observation(2, absent.lease(2)) == NativeSourceImage.Decode.BUSY, "busy without bytes");
    }

    private static long exercise(NativeSourceImageLedger ledger, ByteBuffer bytes, int count) {
        long sum = 0;
        for (int index = 0; index < count; ++index) {
            ledger.observe(0, 1, 1100, 11, 22, 1, bytes);
            long first = ledger.lease(0);
            ledger.copy(0, first, 1);
            ledger.move(1, ledger.lease(1), 2);
            sum += ledger.queueFrameNumber(2, ledger.lease(2), 0);
            ledger.release(0, first);
            ledger.release(2, ledger.lease(2));
        }
        return sum;
    }
    private static void allocations() {
        com.sun.management.ThreadMXBean bean =
                (com.sun.management.ThreadMXBean) ManagementFactory.getThreadMXBean();
        check(bean.isThreadAllocatedMemorySupported(), "allocation measurement required");
        bean.setThreadAllocatedMemoryEnabled(true);
        NativeSourceImageLedger ledger = new NativeSourceImageLedger(3);
        ByteBuffer bytes = image(1, 1100);
        exercise(ledger, bytes, 50000);
        long thread = Thread.currentThread().getId(), before = bean.getThreadAllocatedBytes(thread);
        long sum = exercise(ledger, bytes, 10000);
        long allocated = bean.getThreadAllocatedBytes(thread) - before;
        check(sum == 10000 && allocated == 0, "hot observe/copy/move/release allocated " + allocated);
    }

    public static void main(String[] args) throws Exception {
        snapshots(); retention(); evidence(); allocations();
        System.out.println("NativeSourceImageLedgerTest PASS: retention foundation only; no source authority");
    }
}
