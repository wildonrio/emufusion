package com.thorium.lucent.video;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.Paths;
import static com.thorium.lucent.video.NativeSourceImage.*;

public final class NativeSourceImageTest {
    public static void main(String[] args) throws Exception {
        validAndImmutable();
        exactKeysAndStructuralFailures();
        nativeStatesFailClosed();
        compositionAndLayerChecks();
        adjacencyAndHeldSemantics();
        epochsGeometryAndClockModes();
        bindingsAndByteOrder();
        if (args.length == 1) nativeFixture(Files.readAllBytes(Paths.get(args[0])));
        System.out.println("NativeSourceImageTest PASS (metadata only; no source authority)");
    }

    private static ByteBuffer fixture(long frame) {
        ByteBuffer b = ByteBuffer.allocate(IMAGE_BYTES).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(0, VERSION); b.putInt(4, IMAGE_BYTES); b.putInt(8, 1);
        b.putLong(16, frame); b.putLong(24, 1000 + frame * 100);
        b.putInt(32, (int) frame); b.putInt(36, 2);
        b.putLong(40, 11); b.putLong(48, 22); b.putLong(56, 33);
        b.putLong(64, 0); b.putLong(72, frame); b.putLong(80, 900 + frame * 100);
        b.putInt(88, 1); b.putInt(92, 1); b.putInt(96, 1);
        layer(b, 0, 44, frame);
        return b;
    }

    private static void layer(ByteBuffer b, int index, long queue, long frame) {
        int at = 104 + index * LAYER_BYTES;
        b.putLong(at, queue); b.putLong(at + 8, frame);
        b.putLong(at + 16, -700); // Unknown guest domain, not Android monotonic.
        b.putInt(at + 24, 7); b.putInt(at + 28, (int) frame % 3);
        b.putInt(at + 32, 2); b.putInt(at + 36, 2);
        b.putInt(at + 40, 1); b.putInt(at + 44, 1280); b.putInt(at + 48, 720);
        b.putInt(at + 52, 1280); b.putInt(at + 56, 1);
        b.putInt(at + 80, 1280); b.putInt(at + 84, 720);
    }

    private static Decode decode(ByteBuffer b, Slot slot) {
        return NativeSourceImage.decode(b.getInt(8), b, 11, 22, b.getLong(24), slot);
    }
    private static Slot accepted(ByteBuffer b) {
        Slot s = new Slot();
        check(decode(b, s) == Decode.ACCEPTED, "valid fixture rejected");
        return s;
    }
    private static Pair pair(ByteBuffer left, ByteBuffer right) {
        return compare(accepted(left), accepted(right));
    }
    private static void check(boolean condition, String why) {
        if (!condition) throw new AssertionError(why);
    }
    private static void rejected(ByteBuffer b, Decode expected) {
        Slot s = new Slot();
        check(decode(b, s) == expected, "unexpected decode status: " + decode(b, s));
        check(!s.isSealed() && s.queueEpoch(0) == 0, "rejection exposed usable record");
    }

    private static void validAndImmutable() {
        ByteBuffer a = fixture(1), b = fixture(2);
        Slot left = accepted(a), right = accepted(b);
        check(compare(left, right) == Pair.ADJACENT_QUEUED_IMAGES, "adjacent queues rejected");
        check(left.guestRequestedTimestampNs(0) == -700, "raw guest domain not preserved");
        check(left.queueFrameNumber(1) == 0 && left.queueFrameNumber(-1) == 0, "invalid layer exposed");
        a.putLong(112, 700);
        check(left.queueFrameNumber(0) == 1, "snapshot aliases caller bytes");
        check(decode(a, left) == Decode.SLOT_IN_USE, "owned snapshot overwritten");
        check(compare(left, right) == Pair.ADJACENT_QUEUED_IMAGES, "refused overwrite mutated snapshot");
        left.release();
        check(compare(left, right) == Pair.MISSING_IMAGE && left.bufferTimestampNs() == 0,
                "released snapshot was usable");
        check(decode(a, left) == Decode.ACCEPTED && left.queueFrameNumber(0) == 700,
                "explicitly released slot could not be reused");
        check(compare(null, right) == Pair.MISSING_IMAGE, "null endpoint accepted");
    }

    private static void exactKeysAndStructuralFailures() {
        ByteBuffer b = fixture(1); Slot s = new Slot();
        check(NativeSourceImage.decode(1, b, 11, 22, 1101, s) == Decode.WRONG_IMAGE, "nearest timestamp accepted");
        check(NativeSourceImage.decode(1, b, 12, 22, 1100, s) == Decode.WRONG_IMAGE, "session mismatch accepted");
        check(NativeSourceImage.decode(1, b, 11, 23, 1100, s) == Decode.WRONG_IMAGE, "surface mismatch accepted");
        check(NativeSourceImage.decode(1, b, 0, 22, 1100, s) == Decode.BAD_ARGUMENT, "zero expected epoch accepted");
        check(NativeSourceImage.decode(1, null, 11, 22, 1100, s) == Decode.BAD_ARGUMENT, "null bytes accepted");
        check(NativeSourceImage.decode(1, b, 11, 22, 1100, null) == Decode.BAD_ARGUMENT, "null slot accepted");
        b.limit(IMAGE_BYTES - 1); check(decode(b, s) == Decode.BAD_ARGUMENT, "truncated bytes accepted");
        for (int offset : new int[]{0, 4, 100}) {
            b = fixture(1); b.putInt(offset, b.getInt(offset) + 1); rejected(b, Decode.MALFORMED);
        }
        for (int offset : new int[]{16, 56, 72, 80, 104, 112}) {
            b = fixture(1); b.putLong(offset, 0); rejected(b, Decode.MALFORMED);
            b.putLong(offset, Long.MIN_VALUE); rejected(b, Decode.MALFORMED);
        }
        b = fixture(1); b.putLong(80, 1101); rejected(b, Decode.MALFORMED);
        b = fixture(1); b.putInt(12, -4); rejected(b, Decode.MALFORMED);
        b = fixture(1); b.putInt(12, 1000001003); accepted(b);
        b = fixture(1); b.putInt(8, 2);
        check(NativeSourceImage.decode(1, b, 11, 22, 1100, s) == Decode.MALFORMED, "return/row state mismatch accepted");
    }

    private static void nativeStatesFailClosed() {
        Decode[] states = {Decode.ACCEPTED, Decode.PENDING, Decode.BUSY, Decode.NOT_FOUND,
                Decode.AMBIGUOUS, Decode.REJECTED, Decode.UNSUPPORTED, Decode.CLOSED,
                Decode.BAD_ARGUMENT, Decode.STALE_EPOCH};
        for (int result = 2; result <= 10; ++result) {
            ByteBuffer b = fixture(1); b.putInt(8, result);
            if (result == 6) b.putInt(12, -1000001004);
            rejected(b, states[result - 1]);
        }
        ByteBuffer pending = fixture(1); pending.putInt(8, 2);
        Slot s = new Slot(); check(decode(pending, s) == Decode.PENDING, "pending lost");
        pending.putInt(8, 1); check(decode(pending, s) == Decode.ACCEPTED, "same-image finalized retry rejected");
        ByteBuffer b = fixture(1); b.putInt(8, 6); rejected(b, Decode.MALFORMED);
        b = fixture(1); b.putInt(8, 2); b.putInt(12, -4); rejected(b, Decode.MALFORMED);
        b = fixture(1); b.putInt(8, 99); rejected(b, Decode.MALFORMED);
        check(NativeSourceImage.decode(3, null, 11, 22, 1100, new Slot()) == Decode.BUSY,
                "busy depended on stale output bytes");
    }

    private static void compositionAndLayerChecks() {
        for (int flags : new int[]{0, 2, 3, 4, 5, 6, 7}) {
            ByteBuffer b = fixture(1); b.putInt(92, flags); rejected(b, Decode.INCOMPLETE_COMPOSITION);
        }
        ByteBuffer b = fixture(1); b.putInt(92, 8); rejected(b, Decode.MALFORMED);
        b = fixture(1); b.putInt(88, 9); b.putInt(96, 8); rejected(b, Decode.INCOMPLETE_COMPOSITION);
        b = fixture(1); b.putInt(96, 9); rejected(b, Decode.MALFORMED);
        b = fixture(1); b.putInt(96, 0); rejected(b, Decode.INCOMPLETE_COMPOSITION);
        for (int flags : new int[]{0, 3, 16, 17}) {
            b = fixture(1); b.putInt(144, flags); rejected(b, Decode.MALFORMED);
        }
        for (int offset : new int[]{148, 152, 156}) {
            b = fixture(1); b.putInt(offset, 0); rejected(b, Decode.MALFORMED);
        }
        b = fixture(1); b.putInt(140, 3); rejected(b, Decode.MALFORMED);
        b = fixture(1); b.putInt(88, 8); b.putInt(96, 8);
        for (int n = 1; n < 8; ++n) layer(b, n, 44 + n, 1);
        check(pair(b, fixture(2)) == Pair.UNSUPPORTED_LAYERS, "multi-layer composition granted subset compatibility");
        b.putLong(104 + LAYER_BYTES, 44); rejected(b, Decode.MALFORMED);
        b = fixture(2); b.putInt(144, 5);
        check(pair(fixture(1), b) == Pair.OVERLAY_LAYER, "overlay selected as gameplay");
    }

    private static void adjacencyAndHeldSemantics() {
        ByteBuffer a = fixture(1), b = fixture(2);
        b.putLong(112, 1); b.putInt(132, a.getInt(132)); b.putInt(144, 2);
        check(pair(a, b) == Pair.HELD_QUEUED_IMAGE, "held image renumbered");
        b.putInt(144, 1); b.putLong(72, 1); b.putLong(80, 1000);
        check(pair(a, b) == Pair.HELD_QUEUED_IMAGE, "same Frame retry became new image");
        b.putLong(120, -701);
        check(pair(a, b) == Pair.INCONSISTENT_SAME_IMAGE, "same identity changed guest metadata");
        b.putLong(120, -700); b.putInt(132, 2);
        check(pair(a, b) == Pair.INCONSISTENT_SAME_IMAGE, "same identity changed storage slot");
        b = fixture(2); b.putInt(144, 2);
        check(pair(a, b) == Pair.RIGHT_IMAGE_NOT_NEW, "held observation treated as fresh acquisition");
        a.putInt(144, 2); b.putInt(144, 1);
        check(pair(a, b) == Pair.ADJACENT_QUEUED_IMAGES, "held left blocks later real adjacency");
        b.putLong(112, 3);
        check(pair(a, b) == Pair.QUEUE_FRAME_GAP, "skipped source renumbered adjacent");
        a.putLong(112, 3); b.putLong(112, 2);
        check(pair(a, b) == Pair.QUEUE_FRAME_REVERSED, "reversed source accepted");
        a.putLong(112, Long.MAX_VALUE - 1); b.putLong(112, Long.MAX_VALUE);
        check(pair(a, b) == Pair.ADJACENT_QUEUED_IMAGES, "safe signed boundary rejected");
        for (int offset : new int[]{16, 24, 72, 80}) {
            a = fixture(1); b = fixture(2); b.putLong(offset, a.getLong(offset));
            check(pair(a, b) == Pair.NONMONOTONIC_OBSERVATION, "nonadvancing observation accepted");
        }
    }

    private static void epochsGeometryAndClockModes() {
        for (int offset : new int[]{56, 64}) {
            ByteBuffer b = fixture(2); b.putLong(offset, b.getLong(offset) + 1);
            check(pair(fixture(1), b) == Pair.EPOCH_CHANGED, "epoch/display crossed");
        }
        for (int offset : new int[]{40, 48}) {
            ByteBuffer b = fixture(2); b.putLong(offset, b.getLong(offset) + 1);
            Slot left = accepted(fixture(1)), right = new Slot();
            check(NativeSourceImage.decode(1, b, b.getLong(40), b.getLong(48), 1200, right) == Decode.ACCEPTED,
                    "new binding record rejected");
            check(compare(left, right) == Pair.EPOCH_CHANGED, "binding epoch crossed");
        }
        ByteBuffer b = fixture(2); b.putLong(104, 45);
        check(pair(fixture(1), b) == Pair.QUEUE_CHANGED, "queue epoch crossed");
        b = fixture(2); b.putInt(128, 8);
        check(pair(fixture(1), b) == Pair.QUEUE_CHANGED, "consumer changed silently");
        for (int offset = 148; offset < 192; offset += 4) {
            b = fixture(2); b.putInt(offset, b.getInt(offset) - (offset == 148 ? 1 : -1));
            check(pair(fixture(1), b) == Pair.GEOMETRY_CHANGED, "geometry tuple field ignored: " + offset);
        }
        b = fixture(2); b.putInt(136, 3); b.putInt(140, 3);
        check(pair(fixture(1), b) == Pair.SWAP_INTERVAL_CHANGED, "swap interval crossed");
        for (int raw : new int[]{-1, 0, 5, 120}) {
            ByteBuffer a = fixture(1); b = fixture(2);
            a.putInt(136, raw); a.putInt(140, 1); b.putInt(136, raw); b.putInt(140, 1);
            check(pair(a, b) == Pair.UNSUPPORTED_SWAP_MODE, "extended speed mode qualified");
        }
    }

    private static void bindingsAndByteOrder() {
        ByteBuffer b = ByteBuffer.allocate(BINDING_BYTES).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(0, 1); b.putInt(4, BINDING_BYTES); b.putLong(8, 11); b.putLong(16, 22);
        Binding binding = new Binding();
        check(decodeBinding(1, b, binding) == Decode.BINDING_NOT_READY, "missing swapchain bound");
        b.putLong(24, 33);
        check(decodeBinding(1, b, binding) == Decode.ACCEPTED, "binding rejected");
        b.putLong(8, 99);
        check(binding.sessionEpoch() == 11 && binding.surfaceEpoch() == 22 && binding.swapchainEpoch() == 33,
                "binding not immutable");
        check(decodeBinding(1, b, binding) == Decode.SLOT_IN_USE, "binding overwritten");
        binding.release(); b.putInt(4, BINDING_BYTES + 1);
        check(decodeBinding(1, b, binding) == Decode.MALFORMED, "binding size mismatch accepted");
        check(decodeBinding(7, null, binding) == Decode.UNSUPPORTED, "unsupported hook lost");
        ByteBuffer image = fixture(1); image.position(100); image.order(ByteOrder.BIG_ENDIAN);
        Slot out = new Slot();
        check(NativeSourceImage.decode(1, image.asReadOnlyBuffer(), 11, 22, 1100, out) == Decode.ACCEPTED,
                "caller order/position changed the native wire interpretation");
        check(image.position() == 100 && image.order() == ByteOrder.BIG_ENDIAN, "parser mutated caller buffer");
    }

    private static void nativeFixture(byte[] bytes) {
        check(bytes.length == IMAGE_BYTES + BINDING_BYTES, "compiled C ABI size drift");
        ByteBuffer wire = ByteBuffer.wrap(bytes);
        Slot record = new Slot();
        check(NativeSourceImage.decode(1, wire, 11, 22, 1100, record) == Decode.ACCEPTED,
                "real C ABI fixture did not parse");
        check(record.queueEpoch(0) == 44 && record.queueFrameNumber(0) == 1 &&
                record.guestRequestedTimestampNs(0) == -700, "C fields shifted or unsigned guest timestamp coerced");
        wire.position(IMAGE_BYTES);
        Binding binding = new Binding();
        check(decodeBinding(1, wire.slice(), binding) == Decode.ACCEPTED && binding.swapchainEpoch() == 33,
                "real C binding ABI mismatch");
    }
}
