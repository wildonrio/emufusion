package com.thorium.lucent.video;

import java.nio.ByteBuffer;

/**
 * Single-owner, fixed-slot metadata retention; no images, queries, retries or authority.
 *
 * <p>Slot indices correspond to the caller's candidate/FIFO/history image owners.
 * Allocate once at setup. Every occupancy gets a unique positive lease: delayed
 * work must pass that lease, never act on an index alone. The caller establishes
 * destination texture ownership while retaining the source, commits the matching
 * metadata copy/move, then retires the source image ONLY if move succeeded.
 * Explicit release follows image retirement. This helper cannot enforce GPU
 * lifetime. It never selects a neighboring timestamp or manufactures a guest ID.</p>
 *
 * <p>Observations are one-shot. PENDING/BUSY/error states retain their exact key
 * but no accepted snapshot and cannot be completed in place. There is no retry
 * scheduler here; bounded two-candidate/age-limited retry remains future work.</p>
 */
public final class NativeSourceImageLedger {
    public static final int MAX_CAPACITY = 256;
    public enum Result { SUCCESS, BAD_ARGUMENT, OCCUPIED, STALE_LEASE, LEASE_EXHAUSTED }
    /** Pixel evidence is independent of a queued native image identity. */
    public enum PixelVerdict { UNKNOWN, UNIQUE, HELD }
    public enum TimestampJoin { UNOBSERVED, EXACT, MISSING_PTS, MISMATCH }

    private static final class Entry {
        final NativeSourceImage.Slot image = new NativeSourceImage.Slot();
        long lease, providerGeneration, rawTimestampNs, sessionEpoch, surfaceEpoch, swapchainEpoch;
        NativeSourceImage.Decode observation;
        PixelVerdict pixelVerdict = PixelVerdict.UNKNOWN;
        long classifiedTimestampNs, exportedTimestampNs;
        TimestampJoin classifiedJoin = TimestampJoin.UNOBSERVED, exportedJoin = TimestampJoin.UNOBSERVED;
    }

    private final Entry[] entries;
    private long lastLease;

    public NativeSourceImageLedger(int capacity) {
        if (capacity < 1 || capacity > MAX_CAPACITY)
            throw new IllegalArgumentException("bounded positive metadata capacity required");
        entries = new Entry[capacity];
        for (int index = 0; index < capacity; ++index) entries[index] = new Entry();
    }

    public int capacity() { return entries.length; }
    /** Zero denotes empty/invalid. Tokens never wrap or reset during this ledger's lifetime. */
    public long lease(int index) { return valid(index) ? entries[index].lease : 0L; }

    /**
     * Retain the result of ONE query for an already-retained exact image.
     * A nonpositive raw PTS is recorded as missing (BAD_ARGUMENT), never replaced
     * with arrival time; no native bytes are consulted on that path.
     */
    public Result observe(int index, long providerGeneration, long rawTimestampNs,
                          long sessionEpoch, long surfaceEpoch,
                          int nativeResult, ByteBuffer nativeBytes) {
        return observeInternal(index, providerGeneration, rawTimestampNs, sessionEpoch,
                surfaceEpoch, 0L, nativeResult, nativeBytes);
    }

    /** Exact binding/query join, including a swapchain changed during the one-shot query. */
    public Result observeBound(int index, long providerGeneration, long rawTimestampNs,
                               long sessionEpoch, long surfaceEpoch, long swapchainEpoch,
                               int nativeResult, ByteBuffer nativeBytes) {
        if (swapchainEpoch <= 0L) return Result.BAD_ARGUMENT;
        return observeInternal(index, providerGeneration, rawTimestampNs, sessionEpoch,
                surfaceEpoch, swapchainEpoch, nativeResult, nativeBytes);
    }

    private Result observeInternal(int index, long providerGeneration, long rawTimestampNs,
                                   long sessionEpoch, long surfaceEpoch, long swapchainEpoch,
                                   int nativeResult, ByteBuffer nativeBytes) {
        if (!valid(index) || providerGeneration <= 0L ||
                sessionEpoch <= 0L || surfaceEpoch <= 0L) return Result.BAD_ARGUMENT;
        Entry target = entries[index];
        if (target.lease != 0L) return Result.OCCUPIED;
        if (lastLease == Long.MAX_VALUE) return Result.LEASE_EXHAUSTED;
        target.observation = rawTimestampNs <= 0L ? NativeSourceImage.Decode.BAD_ARGUMENT :
                NativeSourceImage.decode(nativeResult, nativeBytes, sessionEpoch,
                        surfaceEpoch, rawTimestampNs, target.image);
        // These states have a fully validated exact-key payload, even when it is
        // not sealed. Preserve a known binding race as stale, not merely pending.
        boolean validatedPayload = target.observation == NativeSourceImage.Decode.ACCEPTED ||
                target.observation == NativeSourceImage.Decode.PENDING ||
                target.observation == NativeSourceImage.Decode.AMBIGUOUS ||
                target.observation == NativeSourceImage.Decode.REJECTED;
        if (validatedPayload && swapchainEpoch > 0L &&
                littleEndianLong(nativeBytes, 56) != swapchainEpoch) {
            target.image.clear();
            target.observation = NativeSourceImage.Decode.STALE_EPOCH;
        }
        target.providerGeneration = providerGeneration;
        target.rawTimestampNs = rawTimestampNs;
        target.sessionEpoch = sessionEpoch;
        target.surfaceEpoch = surfaceEpoch;
        target.swapchainEpoch = swapchainEpoch;
        target.lease = ++lastLease; // Publish occupancy after the complete observation.
        return Result.SUCCESS;
    }

    /**
     * Retain a missing/error observation without inventing a binding or decoding old bytes.
     * Zero epochs explicitly mean unavailable. This method can never seal a snapshot.
     */
    public Result observeMissing(int index, long providerGeneration, long rawTimestampNs,
                                 long sessionEpoch, long surfaceEpoch, long swapchainEpoch,
                                 NativeSourceImage.Decode observation) {
        if (!valid(index) || providerGeneration <= 0L || sessionEpoch < 0L ||
                surfaceEpoch < 0L || swapchainEpoch < 0L || observation == null ||
                observation == NativeSourceImage.Decode.ACCEPTED ||
                observation == NativeSourceImage.Decode.SLOT_IN_USE) return Result.BAD_ARGUMENT;
        Entry target = entries[index];
        if (target.lease != 0L) return Result.OCCUPIED;
        if (lastLease == Long.MAX_VALUE) return Result.LEASE_EXHAUSTED;
        target.observation = observation;
        target.providerGeneration = providerGeneration;
        target.rawTimestampNs = rawTimestampNs;
        target.sessionEpoch = sessionEpoch;
        target.surfaceEpoch = surfaceEpoch;
        target.swapchainEpoch = swapchainEpoch;
        target.lease = ++lastLease;
        return Result.SUCCESS;
    }

    /** The destination must be empty. Both accepted and missing/error observations are copied. */
    public Result copy(int source, long sourceLease, int destination) {
        return copyTo(source, sourceLease, this, destination);
    }

    /** Value-owned cross-owner transfer; never shares a mutable Slot or reuses a lease. */
    public Result copyTo(int source, long sourceLease,
                         NativeSourceImageLedger destinationLedger, int destination) {
        if (!valid(source) || destinationLedger == null || !destinationLedger.valid(destination) ||
                (this == destinationLedger && source == destination))
            return Result.BAD_ARGUMENT;
        if (!matches(source, sourceLease)) return Result.STALE_LEASE;
        Entry from = entries[source], to = destinationLedger.entries[destination];
        if (to.lease != 0L) return Result.OCCUPIED;
        if (destinationLedger.lastLease == Long.MAX_VALUE) return Result.LEASE_EXHAUSTED;
        if (from.image.isSealed()) {
            NativeSourceImage.Transfer copied = to.image.copyFrom(from.image);
            if (copied != NativeSourceImage.Transfer.COPIED)
                throw new IllegalStateException("empty ledger slot has occupied metadata");
        }
        to.providerGeneration = from.providerGeneration;
        to.rawTimestampNs = from.rawTimestampNs;
        to.sessionEpoch = from.sessionEpoch;
        to.surfaceEpoch = from.surfaceEpoch;
        to.swapchainEpoch = from.swapchainEpoch;
        to.observation = from.observation;
        to.pixelVerdict = from.pixelVerdict;
        to.classifiedTimestampNs = from.classifiedTimestampNs;
        to.exportedTimestampNs = from.exportedTimestampNs;
        to.classifiedJoin = from.classifiedJoin;
        to.exportedJoin = from.exportedJoin;
        to.lease = ++destinationLedger.lastLease;
        return Result.SUCCESS;
    }

    /** Classification annotation only; neither this nor ACCEPTED grants clock authority. */
    public Result classifyPixels(int index, long expectedLease, PixelVerdict verdict) {
        if (verdict == null) return Result.BAD_ARGUMENT;
        if (!matches(index, expectedLease)) return Result.STALE_LEASE;
        entries[index].pixelVerdict = verdict;
        return Result.SUCCESS;
    }

    public PixelVerdict pixelVerdict(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].pixelVerdict : PixelVerdict.UNKNOWN;
    }

    /** Preserve original query facts even when the consumer association is wrong. */
    public Result recordClassifiedTimestamp(int index, long expectedLease, long timestampNs) {
        if (!matches(index, expectedLease)) return Result.STALE_LEASE;
        Entry entry = entries[index];
        entry.classifiedTimestampNs = timestampNs;
        entry.classifiedJoin = timestampJoin(entry.rawTimestampNs, timestampNs);
        return Result.SUCCESS;
    }

    public Result recordExportedTimestamp(int index, long expectedLease, long timestampNs) {
        if (!matches(index, expectedLease)) return Result.STALE_LEASE;
        Entry entry = entries[index];
        entry.exportedTimestampNs = timestampNs;
        entry.exportedJoin = timestampJoin(entry.rawTimestampNs, timestampNs);
        return Result.SUCCESS;
    }

    public TimestampJoin classifiedJoin(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].classifiedJoin : TimestampJoin.UNOBSERVED;
    }
    public TimestampJoin exportedJoin(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].exportedJoin : TimestampJoin.UNOBSERVED;
    }
    public long classifiedTimestampNs(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].classifiedTimestampNs : 0L;
    }
    public long exportedTimestampNs(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].exportedTimestampNs : 0L;
    }

    private static TimestampJoin timestampJoin(long rawTimestampNs, long timestampNs) {
        return rawTimestampNs <= 0L ? TimestampJoin.MISSING_PTS :
                rawTimestampNs == timestampNs ? TimestampJoin.EXACT : TimestampJoin.MISMATCH;
    }

    /** Failed destination admission never releases or changes the source. */
    public Result move(int source, long sourceLease, int destination) {
        Result copied = copy(source, sourceLease, destination);
        if (copied != Result.SUCCESS) return copied;
        clear(entries[source]);
        return Result.SUCCESS;
    }

    /** Call after the matching retained image is retired; stale callbacks cannot clear a reuse. */
    public Result release(int index, long expectedLease) {
        if (!valid(index)) return Result.BAD_ARGUMENT;
        if (!matches(index, expectedLease)) return Result.STALE_LEASE;
        clear(entries[index]);
        return Result.SUCCESS;
    }

    public NativeSourceImage.Decode observation(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].observation : null;
    }
    public long providerGeneration(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].providerGeneration : 0L;
    }
    public long rawTimestampNs(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].rawTimestampNs : 0L;
    }
    public long sessionEpoch(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].sessionEpoch : 0L;
    }
    public long surfaceEpoch(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].surfaceEpoch : 0L;
    }
    public long swapchainEpoch(int index, long expectedLease) {
        return matches(index, expectedLease) ? entries[index].swapchainEpoch : 0L;
    }
    public boolean missingPts(int index, long expectedLease) {
        return matches(index, expectedLease) && entries[index].rawTimestampNs <= 0L;
    }
    public long queueFrameNumber(int index, long expectedLease, int layer) {
        return matches(index, expectedLease) ?
                entries[index].image.queueFrameNumber(layer) : 0L;
    }
    /** Optional value export; never exposes the ledger's mutable internal Slot. */
    public NativeSourceImage.Transfer copySnapshot(int index, long expectedLease,
                                                  NativeSourceImage.Slot emptyDestination) {
        if (!matches(index, expectedLease) || emptyDestination == null)
            return NativeSourceImage.Transfer.BAD_ARGUMENT;
        return emptyDestination.copyFrom(entries[index].image);
    }

    /** Compatibility only: ADJACENT_QUEUED_IMAGES still grants no interpolation authority. */
    public NativeSourceImage.Pair compare(int left, long leftLease, int right, long rightLease) {
        if (!matches(left, leftLease) || !matches(right, rightLease))
            return NativeSourceImage.Pair.STALE_RETENTION;
        Entry a = entries[left], b = entries[right];
        if (a.rawTimestampNs <= 0L || b.rawTimestampNs <= 0L)
            return NativeSourceImage.Pair.MISSING_PTS;
        if (a.providerGeneration != b.providerGeneration)
            return NativeSourceImage.Pair.PROVIDER_CHANGED;
        if (a.classifiedJoin == TimestampJoin.MISMATCH || b.classifiedJoin == TimestampJoin.MISMATCH)
            return NativeSourceImage.Pair.CLASSIFIED_TIMESTAMP_MISMATCH;
        if (a.exportedJoin == TimestampJoin.MISMATCH || b.exportedJoin == TimestampJoin.MISMATCH)
            return NativeSourceImage.Pair.EXPORTED_TIMESTAMP_MISMATCH;
        return NativeSourceImage.compare(a.image, b.image);
    }

    private boolean valid(int index) { return index >= 0 && index < entries.length; }
    private static long littleEndianLong(ByteBuffer bytes, int offset) {
        long value = 0L;
        for (int index = 0; index < 8; ++index)
            value |= ((long) bytes.get(offset + index) & 255L) << (index * 8);
        return value;
    }
    private boolean matches(int index, long expectedLease) {
        return valid(index) && expectedLease > 0L && entries[index].lease == expectedLease;
    }
    private static void clear(Entry entry) {
        entry.image.clear();
        entry.observation = null;
        entry.pixelVerdict = PixelVerdict.UNKNOWN;
        entry.classifiedTimestampNs = entry.exportedTimestampNs = 0L;
        entry.classifiedJoin = entry.exportedJoin = TimestampJoin.UNOBSERVED;
        entry.providerGeneration = 0L;
        entry.rawTimestampNs = 0L;
        entry.sessionEpoch = 0L;
        entry.surfaceEpoch = 0L;
        entry.swapchainEpoch = 0L;
        entry.lease = 0L; // Invalidate occupancy only after the snapshot is cleared.
    }
}
