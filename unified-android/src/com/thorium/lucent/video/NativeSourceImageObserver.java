package com.thorium.lucent.video;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/**
 * Single-render-thread, one-shot queued-image metadata observation. NOT authority.
 *
 * <p>Construct only for an enabled observation path, never Off. All storage is
 * allocated here; observe/retain/classify/release allocate nothing. diagnostic()
 * deliberately formats lifetime counters only at the caller's periodic boundary.
 * No clock, GPU/image ownership, waiting, retries, policy decisions or native
 * close calls belong here. Provider calls are bounded by the provider contract.
 * A provider RuntimeException means missing evidence, never a playback failure.</p>
 *
 * <p>The caller owns candidate indices and calls retainCandidate only when it has
 * established the corresponding new image owner. Reusing an occupied index is
 * counted as metadata loss, not a successful transfer. classifyCandidate copies
 * its immutable observation; it does NOT retire that candidate. There is no
 * nearest timestamp, guessed guest ID, or retry after a missing observation.</p>
 */
public final class NativeSourceImageObserver {
    private enum Reason {
        QUERY, BINDING, MISSING_PTS, NO_PROVIDER, PROVIDER_EXCEPTION, EMPTY_SOURCE,
        LEDGER_FAILURE, CLOSED
    }

    private final int candidateCount, classifiedIndex;
    private final NativeSourceImageLedger ledger;
    private final Reason[] reasons;
    private final ByteBuffer bindingBytes = ByteBuffer.allocateDirect(NativeSourceImage.BINDING_BYTES)
            .order(ByteOrder.LITTLE_ENDIAN);
    private final ByteBuffer imageBytes = ByteBuffer.allocateDirect(NativeSourceImage.IMAGE_BYTES)
            .order(ByteOrder.LITTLE_ENDIAN);
    private final NativeSourceImage.Binding binding = new NativeSourceImage.Binding();
    private final NativeSourceImage.Slot previous = new NativeSourceImage.Slot();
    private final NativeSourceImage.Slot current = new NativeSourceImage.Slot();
    private final long[] bindingStatuses = new long[NativeSourceImage.Decode.values().length];
    private final long[] queryStatuses = new long[NativeSourceImage.Decode.values().length];
    private final long[] classifiedStatuses = new long[NativeSourceImage.Decode.values().length];
    private final long[] pairStatuses = new long[NativeSourceImage.Pair.values().length];
    private final long[] missingReasons = new long[Reason.values().length];
    private NativeSourceImageProvider provider;
    private long generation = 1L, previousGeneration;
    private boolean closed, generationExhausted;
    private long observations, bindingCalls, queryCalls, providerChanges, providerExceptions;
    private long candidateRetained, candidateLosses, candidateReleased, candidatesCleared;
    private long classifiedCopies, classifiedReplaced, classifiedReady, classifiedNotReady;
    private long classifiedMissing, classifiedMismatch, pixelUnique, pixelHeld, pixelUnknown;
    private long classifiedAccepted, invalidOperations, ledgerFailures, callsAfterClose, imageResets;
    private long lastClassifiedPts, lastQueueFrame, lastSessionEpoch, lastSurfaceEpoch, lastSwapchainEpoch;
    private Reason lastReason;
    private NativeSourceImage.Decode lastStatus;
    private NativeSourceImage.Pair lastPair;

    public NativeSourceImageObserver(int candidateCount) {
        if (candidateCount < 0 || candidateCount > NativeSourceImageLedger.MAX_CAPACITY - 2)
            throw new IllegalArgumentException("bounded metadata candidate count required");
        this.candidateCount = candidateCount;
        classifiedIndex = candidateCount + 1;
        ledger = new NativeSourceImageLedger(candidateCount + 2);
        reasons = new Reason[ledger.capacity()];
    }

    /** Reference identity, not equals(); replacement invalidates metadata only. */
    public void setProvider(NativeSourceImageProvider next) {
        if (closed) { ++callsAfterClose; return; }
        if (provider == next) return;
        ++providerChanges;
        invalidateMetadata();
        provider = next;
        if (generation == Long.MAX_VALUE) generationExhausted = true;
        else ++generation;
    }

    /** Observe exactly the raw timestamp returned by the consumed image, once. */
    public void observeLatest(long rawTimestampNs) {
        if (closed) { ++callsAfterClose; return; }
        ++observations;
        release(0);
        binding.release();
        if (rawTimestampNs <= 0L) {
            missing(rawTimestampNs, 0L, 0L, 0L, NativeSourceImage.Decode.BAD_ARGUMENT, Reason.MISSING_PTS);
            return;
        }
        if (generationExhausted) {
            missing(rawTimestampNs, 0L, 0L, 0L, NativeSourceImage.Decode.CLOSED, Reason.CLOSED);
            return;
        }
        NativeSourceImageProvider exactProvider = provider;
        if (exactProvider == null) {
            missing(rawTimestampNs, 0L, 0L, 0L, NativeSourceImage.Decode.NOT_FOUND, Reason.NO_PROVIDER);
            return;
        }
        NativeSourceImage.Decode bindingStatus;
        try {
            zero(bindingBytes);
            ++bindingCalls;
            int result = exactProvider.sourceImageBinding(bindingBytes);
            bindingStatus = NativeSourceImage.decodeBinding(result, bindingBytes, binding);
        } catch (RuntimeException failure) {
            ++providerExceptions;
            missing(rawTimestampNs, 0L, 0L, 0L, NativeSourceImage.Decode.NOT_FOUND, Reason.PROVIDER_EXCEPTION);
            return;
        }
        ++bindingStatuses[bindingStatus.ordinal()];
        if (bindingStatus != NativeSourceImage.Decode.ACCEPTED) {
            missing(rawTimestampNs, 0L, 0L, 0L, bindingStatus, Reason.BINDING);
            return;
        }
        long session = binding.sessionEpoch(), surface = binding.surfaceEpoch();
        long swapchain = binding.swapchainEpoch();
        try {
            zero(imageBytes);
            ++queryCalls;
            int result = exactProvider.querySourceImage(session, surface, rawTimestampNs, imageBytes);
            NativeSourceImageLedger.Result retained = ledger.observeBound(0, generation,
                    rawTimestampNs, session, surface, swapchain, result, imageBytes);
            if (retained != NativeSourceImageLedger.Result.SUCCESS) {
                ++ledgerFailures;
                reasons[0] = Reason.LEDGER_FAILURE;
                return;
            }
        } catch (RuntimeException failure) {
            ++providerExceptions;
            release(0); // A failed call can never leave a partially accepted observation.
            missing(rawTimestampNs, session, surface, swapchain,
                    NativeSourceImage.Decode.NOT_FOUND, Reason.PROVIDER_EXCEPTION);
            return;
        }
        reasons[0] = Reason.QUERY;
        ++queryStatuses[ledger.observation(0, ledger.lease(0)).ordinal()];
    }

    public void classifyLatest() { classify(0); }

    public void retainCandidate(int slot) {
        if (closed) { ++callsAfterClose; return; }
        if (!validCandidate(slot)) return;
        int index = slot + 1;
        if (ledger.lease(index) != 0L) { ++candidateLosses; release(index); }
        if (copy(0, index)) ++candidateRetained;
    }

    public void classifyCandidate(int slot) {
        if (closed) { ++callsAfterClose; return; }
        if (!validCandidate(slot)) { clearClassified(); return; }
        classify(slot + 1);
    }

    public void releaseCandidate(int slot) {
        if (closed) { ++callsAfterClose; return; }
        if (!validCandidate(slot)) return;
        if (ledger.lease(slot + 1) != 0L) { ++candidateReleased; release(slot + 1); }
    }

    public void clearCandidates() {
        for (int index = 1; index <= candidateCount; ++index) {
            if (ledger.lease(index) != 0L) { ++candidatesCleared; release(index); }
        }
    }

    public void clearClassified() { release(classifiedIndex); }

    /** Geometry/history reset: invalidate metadata, preserving the provider and lifetime counters. */
    public void resetImages() {
        if (closed) { ++callsAfterClose; return; }
        ++imageResets;
        invalidateMetadata();
    }

    /**
     * Copy the exact classified image's observation before finishClassified retires it.
     * Destination storage is preallocated and empty. Missing raw PTS stays missing,
     * even if the presentation path used an arrival-time fallback. A mismatched
     * positive key records a separate MISMATCH join without rewriting the
     * original query status/payload or independent pixel classification.
     */
    public NativeSourceImageLedger.Result copyClassifiedTo(
            NativeSourceImageLedger destination, int index, long classifiedPts,
            boolean unique, boolean pixelVerdictKnown) {
        if (closed || destination == null) return NativeSourceImageLedger.Result.BAD_ARGUMENT;
        long lease = ledger.lease(classifiedIndex);
        if (lease == 0L) return NativeSourceImageLedger.Result.STALE_LEASE;
        NativeSourceImageLedger.Result copied = ledger.copyTo(classifiedIndex, lease, destination, index);
        if (copied == NativeSourceImageLedger.Result.SUCCESS) {
            destination.recordClassifiedTimestamp(index, destination.lease(index), classifiedPts);
            destination.classifyPixels(index, destination.lease(index), !pixelVerdictKnown ?
                    NativeSourceImageLedger.PixelVerdict.UNKNOWN : unique ?
                    NativeSourceImageLedger.PixelVerdict.UNIQUE : NativeSourceImageLedger.PixelVerdict.HELD);
        }
        return copied;
    }

    /**
     * Pixel classification is a separate diagnostic, not native queue identity.
     * Blind/fallback "unique" is counted unknown unless pixelVerdictKnown is true.
     * Exact positive PTS is required even to count a ready classification.
     */
    public void finishClassified(boolean ready, long classifiedPts, boolean unique,
                                 boolean pixelVerdictKnown) {
        if (closed) { ++callsAfterClose; return; }
        long lease = ledger.lease(classifiedIndex);
        lastPair = null;
        lastReason = reasons[classifiedIndex];
        lastStatus = ledger.observation(classifiedIndex, lease);
        lastClassifiedPts = ledger.rawTimestampNs(classifiedIndex, lease);
        lastQueueFrame = lastSessionEpoch = lastSurfaceEpoch = lastSwapchainEpoch = 0L;
        if (!ready) {
            ++classifiedNotReady;
            previous.clear();
        } else if (lease == 0L || lastClassifiedPts <= 0L || classifiedPts <= 0L) {
            ++classifiedMissing;
            previous.clear();
        } else if (classifiedPts != lastClassifiedPts) {
            ++classifiedMismatch;
            previous.clear();
        } else {
            ++classifiedReady;
            if (!pixelVerdictKnown) ++pixelUnknown;
            else if (unique) ++pixelUnique;
            else ++pixelHeld;
            ++classifiedStatuses[lastStatus.ordinal()];
            if (lastStatus == NativeSourceImage.Decode.ACCEPTED) {
                ++classifiedAccepted;
                current.clear();
                ledger.copySnapshot(classifiedIndex, lease, current);
                long thisGeneration = ledger.providerGeneration(classifiedIndex, lease);
                lastQueueFrame = current.queueFrameNumber(0);
                lastSessionEpoch = current.sessionEpoch();
                lastSurfaceEpoch = current.surfaceEpoch();
                lastSwapchainEpoch = current.swapchainEpoch();
                if (previous.isSealed()) {
                    lastPair = previousGeneration == thisGeneration ?
                            NativeSourceImage.compare(previous, current) : NativeSourceImage.Pair.PROVIDER_CHANGED;
                    ++pairStatuses[lastPair.ordinal()];
                }
                previous.clear();
                previous.copyFrom(current);
                previousGeneration = thisGeneration;
                current.clear();
            } else previous.clear();
        }
        clearClassified(); // A second finish cannot count the same retained observation again.
    }

    /** Metadata retirement only; never closes the provider, native host or image owners. */
    public void close() {
        if (closed) return;
        invalidateMetadata();
        provider = null;
        closed = true;
    }

    /** Periodic boundary only. All counters are lifetime totals, unaffected by epoch/reset. */
    public String diagnostic() {
        StringBuilder out = new StringBuilder(1400);
        out.append("nativeSourceObserver authority=false closed=").append(closed)
                .append(" generation=").append(generation).append(" generationExhausted=").append(generationExhausted)
                .append(" observations=").append(observations).append(" bindingCalls=").append(bindingCalls)
                .append(" queryCalls=").append(queryCalls).append(" providerChanges=").append(providerChanges)
                .append(" providerExceptions=").append(providerExceptions).append(" candidateRetained=").append(candidateRetained)
                .append(" candidateLosses=").append(candidateLosses).append(" candidateReleased=").append(candidateReleased)
                .append(" candidatesCleared=").append(candidatesCleared).append(" classifiedCopies=").append(classifiedCopies)
                .append(" classifiedReplaced=").append(classifiedReplaced).append(" classifiedReady=").append(classifiedReady)
                .append(" classifiedNotReady=").append(classifiedNotReady).append(" classifiedMissing=").append(classifiedMissing)
                .append(" classifiedMismatch=").append(classifiedMismatch).append(" classifiedAccepted=").append(classifiedAccepted)
                .append(" pixelUnique=").append(pixelUnique).append(" pixelHeld=").append(pixelHeld)
                .append(" pixelUnknown=").append(pixelUnknown).append(" invalidOperations=").append(invalidOperations)
                .append(" ledgerFailures=").append(ledgerFailures).append(" callsAfterClose=").append(callsAfterClose)
                .append(" imageResets=").append(imageResets)
                .append(" lastRawPts=").append(lastClassifiedPts).append(" lastQueueFrame=").append(lastQueueFrame)
                .append(" lastSessionEpoch=").append(lastSessionEpoch).append(" lastSurfaceEpoch=").append(lastSurfaceEpoch)
                .append(" lastSwapchainEpoch=").append(lastSwapchainEpoch).append(" lastReason=").append(lastReason)
                .append(" lastStatus=").append(lastStatus).append(" lastPair=").append(lastPair);
        statuses(out, " binding", NativeSourceImage.Decode.values(), bindingStatuses);
        statuses(out, " query", NativeSourceImage.Decode.values(), queryStatuses);
        statuses(out, " classified", NativeSourceImage.Decode.values(), classifiedStatuses);
        statuses(out, " pair", NativeSourceImage.Pair.values(), pairStatuses);
        statuses(out, " missing", Reason.values(), missingReasons);
        return out.toString();
    }

    private void missing(long pts, long session, long surface, long swapchain,
                          NativeSourceImage.Decode status, Reason reason) {
        ++missingReasons[reason.ordinal()];
        if (ledger.observeMissing(0, generation, pts, session, surface, swapchain, status) !=
                NativeSourceImageLedger.Result.SUCCESS) ++ledgerFailures;
        reasons[0] = reason;
    }

    private void classify(int source) {
        if (closed) { ++callsAfterClose; return; }
        if (ledger.lease(classifiedIndex) != 0L) ++classifiedReplaced;
        clearClassified();
        if (copy(source, classifiedIndex)) ++classifiedCopies;
    }

    private boolean copy(int source, int destination) {
        long sourceLease = ledger.lease(source);
        if (sourceLease == 0L) {
            reasons[destination] = Reason.EMPTY_SOURCE;
            return false;
        }
        if (ledger.copy(source, sourceLease, destination) != NativeSourceImageLedger.Result.SUCCESS) {
            ++ledgerFailures;
            reasons[destination] = Reason.LEDGER_FAILURE;
            return false;
        }
        reasons[destination] = reasons[source];
        return true;
    }

    private boolean validCandidate(int slot) {
        if (slot >= 0 && slot < candidateCount) return true;
        ++invalidOperations;
        return false;
    }

    private void invalidateMetadata() {
        release(0);
        clearCandidates();
        clearClassified();
        previous.clear();
        current.clear();
        binding.release();
        previousGeneration = 0L;
        lastClassifiedPts = lastQueueFrame = lastSessionEpoch = lastSurfaceEpoch = lastSwapchainEpoch = 0L;
        lastReason = null;
        lastStatus = null;
        lastPair = null;
    }

    private void release(int index) {
        long lease = ledger.lease(index);
        if (lease != 0L && ledger.release(index, lease) != NativeSourceImageLedger.Result.SUCCESS)
            ++ledgerFailures;
        reasons[index] = null;
    }

    private static void zero(ByteBuffer bytes) {
        bytes.clear();
        for (int index = 0; index < bytes.capacity(); ++index) bytes.put(index, (byte) 0);
    }

    private static void statuses(StringBuilder out, String prefix, Enum<?>[] names, long[] counts) {
        for (int index = 0; index < counts.length; ++index)
            if (counts[index] != 0L) out.append(prefix).append(names[index].name()).append('=').append(counts[index]);
    }
}
