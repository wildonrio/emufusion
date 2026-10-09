package com.thorium.lucent.video;

import java.lang.management.ManagementFactory;
import java.lang.reflect.Field;
import java.nio.ByteBuffer;

/** Deterministic synthetic ABI fixtures; tests metadata only, never runtime/frame-quality proof. */
public final class NativeSourceImageObserverTest {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static long count(NativeSourceImageObserver observer, String name) {
        String text = observer.diagnostic();
        String key = " " + name + "=";
        int start = text.indexOf(key);
        if (start < 0) return 0L;
        start += key.length();
        int end = text.indexOf(' ', start);
        return Long.parseLong(text.substring(start, end < 0 ? text.length() : end));
    }
    private static void has(NativeSourceImageObserver observer, String text) {
        check(observer.diagnostic().contains(text), text + " in " + observer.diagnostic());
    }
    private static NativeSourceImageLedger ledger(NativeSourceImageObserver observer) throws Exception {
        Field field = NativeSourceImageObserver.class.getDeclaredField("ledger");
        field.setAccessible(true);
        return (NativeSourceImageLedger) field.get(observer);
    }

    private static final class FixtureProvider implements NativeSourceImageProvider {
        int bindingResult = 1, queryResult = 1;
        long bindingSession = 11, bindingSurface = 22, bindingSwapchain = 33;
        long querySession = 11, querySurface = 22, querySwapchain = 33, ptsDelta;
        long frame = 1, submission = 1, composition = 1;
        long bindingCalls, queryCalls, lastSession, lastSurface, lastPts;
        boolean bindingThrows, queryThrows, omitBinding, omitQuery, held;
        boolean sawBuffers;
        ByteBuffer bindingIdentity, queryIdentity;
        final RuntimeException failure = new IllegalStateException("synthetic provider failure");
        @Override public int sourceImageBinding(ByteBuffer b) {
            ++bindingCalls;
            check(b.isDirect() && b.capacity() == 64, "fixed direct binding bytes");
            if (bindingIdentity == null) bindingIdentity = b;
            else check(bindingIdentity == b, "no binding buffer churn");
            if (bindingThrows) throw failure;
            if (!omitBinding) {
                b.putInt(0, 1); b.putInt(4, 64);
                b.putLong(8, bindingSession); b.putLong(16, bindingSurface);
                b.putLong(24, bindingSwapchain);
            }
            return bindingResult;
        }
        @Override public int querySourceImage(long session, long surface, long pts, ByteBuffer b) {
            ++queryCalls;
            lastSession = session; lastSurface = surface; lastPts = pts;
            check(b.isDirect() && b.capacity() == 808, "fixed direct image bytes");
            if (queryIdentity == null) queryIdentity = b;
            else check(queryIdentity == b, "no image buffer churn");
            sawBuffers = true;
            if (queryThrows) throw failure;
            if (!omitQuery) {
                b.putInt(0, 1); b.putInt(4, 808); b.putInt(8, queryResult);
                b.putInt(12, queryResult == 6 ? -4 : 0);
                b.putLong(16, submission); b.putLong(24, pts + ptsDelta);
                b.putLong(40, querySession); b.putLong(48, querySurface); b.putLong(56, querySwapchain);
                b.putLong(72, composition); b.putLong(80, pts - 100);
                b.putInt(88, 1); b.putInt(92, 1); b.putInt(96, 1);
                b.putLong(104, 44); b.putLong(112, frame); b.putLong(120, -700 + frame);
                b.putInt(128, 7); b.putInt(132, (int) (frame % 3));
                b.putInt(136, 2); b.putInt(140, 2); b.putInt(144, held ? 2 : 1);
                b.putInt(148, 1280); b.putInt(152, 720); b.putInt(156, 1280);
                b.putInt(160, 1); b.putInt(184, 1280); b.putInt(188, 720);
            }
            return queryResult;
        }
        void next() { ++frame; ++submission; ++composition; held = false; }
    }

    private static NativeSourceImageObserver observer(FixtureProvider provider, int candidates) {
        NativeSourceImageObserver observer = new NativeSourceImageObserver(candidates);
        observer.setProvider(provider);
        return observer;
    }
    private static void finishLatest(NativeSourceImageObserver observer, long pts,
                                      boolean unique, boolean known) {
        observer.classifyLatest();
        observer.finishClassified(true, pts, unique, known);
    }

    private static void asyncExactRetention() throws Exception {
        FixtureProvider provider = new FixtureProvider();
        NativeSourceImageObserver observer = observer(provider, 2);
        NativeSourceImageLedger ledger = ledger(observer);
        observer.observeLatest(1100);
        observer.retainCandidate(0);
        long retained = ledger.lease(1);
        provider.next(); observer.observeLatest(2100);
        observer.classifyCandidate(0);
        observer.finishClassified(true, 1100, true, true);
        has(observer, "lastQueueFrame=1"); has(observer, "lastRawPts=1100");
        check(ledger.lease(1) == retained && ledger.rawTimestampNs(1, retained) == 1100,
                "classify does not release or overwrite async image metadata");
        observer.releaseCandidate(0);
        check(ledger.lease(1) == 0, "explicit release");
        finishLatest(observer, 2100, true, true);
        has(observer, "lastPair=ADJACENT_QUEUED_IMAGES");
        check(count(observer, "classifiedAccepted") == 2 && provider.queryCalls == 2,
                "delayed result uses immutable candidate, never requeries");

        observer.observeLatest(3100); observer.retainCandidate(1);
        observer.clearCandidates(); // Sync fallback still owns latest.
        finishLatest(observer, 3100, false, true);
        check(count(observer, "classifiedAccepted") == 3 && count(observer, "pixelHeld") == 1,
                "clearCandidates preserves latest for fallback");
    }

    private static void exactTimestampAndEmptyCases() throws Exception {
        for (long delta : new long[] {-1, 1}) {
            FixtureProvider provider = new FixtureProvider(); provider.ptsDelta = delta;
            NativeSourceImageObserver observer = observer(provider, 1);
            observer.observeLatest(1100); finishLatest(observer, 1100, true, true);
            check(count(observer, "queryWRONG_IMAGE") == 1 && count(observer, "classifiedAccepted") == 0,
                    "positive one-ns query mismatch never nearest matched");
        }
        for (long delta : new long[] {-1, 1}) {
            FixtureProvider provider = new FixtureProvider();
            NativeSourceImageObserver observer = observer(provider, 1);
            observer.observeLatest(1100); finishLatest(observer, 1100 + delta, true, true);
            check(count(observer, "classifiedMismatch") == 1 && count(observer, "classifiedReady") == 0 &&
                    count(observer, "pixelUnique") == 0, "classified PTS one-ns mismatch never counted");
        }
        FixtureProvider provider = new FixtureProvider();
        NativeSourceImageObserver observer = observer(provider, 1);
        for (long raw : new long[] {0, -1, Long.MIN_VALUE}) {
            observer.observeLatest(raw); observer.retainCandidate(0);
            observer.classifyCandidate(0); observer.finishClassified(true, 1100, true, true);
            observer.releaseCandidate(0);
        }
        check(provider.bindingCalls == 0 && provider.queryCalls == 0 &&
                count(observer, "classifiedMissing") == 3 && count(observer, "pixelUnique") == 0,
                "missing raw PTS never queries or counts fallback clock");
        observer.classifyCandidate(0); observer.finishClassified(true, 1100, true, true);
        has(observer, "lastReason=EMPTY_SOURCE");
        observer.observeLatest(1100); observer.classifyLatest();
        observer.finishClassified(false, 1100, true, true);
        check(count(observer, "classifiedNotReady") == 1 && count(observer, "classifiedAccepted") == 0,
                "not ready does not count");
        finishLatest(observer, 0, true, true);
        check(count(observer, "classifiedMissing") == 5, "zero classified PTS missing");
        NativeSourceImageLedger ledger = ledger(observer);
        check(ledger.lease(2) == 0, "finish retires only classified metadata");
    }

    private static void statusesAndEpochs() throws Exception {
        NativeSourceImage.Decode[] names = {null, NativeSourceImage.Decode.ACCEPTED,
                NativeSourceImage.Decode.PENDING, NativeSourceImage.Decode.BUSY,
                NativeSourceImage.Decode.NOT_FOUND, NativeSourceImage.Decode.AMBIGUOUS,
                NativeSourceImage.Decode.REJECTED, NativeSourceImage.Decode.UNSUPPORTED,
                NativeSourceImage.Decode.CLOSED, NativeSourceImage.Decode.BAD_ARGUMENT,
                NativeSourceImage.Decode.STALE_EPOCH};
        for (int result = 2; result <= 10; ++result) {
            FixtureProvider provider = new FixtureProvider(); provider.bindingResult = result;
            NativeSourceImageObserver observer = observer(provider, 1);
            observer.observeLatest(1100); observer.retainCandidate(0);
            observer.classifyCandidate(0); observer.finishClassified(true, 1100, false, true);
            check(provider.queryCalls == 0 && count(observer, "binding" + names[result]) == 1 &&
                    count(observer, "classifiedAccepted") == 0, "binding status retained without query " + result);
            has(observer, "lastReason=BINDING"); has(observer, "lastStatus=" + names[result]);

            provider = new FixtureProvider(); provider.queryResult = result;
            observer = observer(provider, 1); observer.observeLatest(1100); observer.retainCandidate(0);
            NativeSourceImageLedger ledger = ledger(observer); long lease = ledger.lease(1);
            check(ledger.sessionEpoch(1, lease) == 11 && ledger.surfaceEpoch(1, lease) == 22 &&
                    ledger.swapchainEpoch(1, lease) == 33 && ledger.rawTimestampNs(1, lease) == 1100,
                    "missing query exact key and binding remain retained");
            observer.classifyCandidate(0); observer.finishClassified(true, 1100, true, false);
            check(provider.queryCalls == 1 && count(observer, "query" + names[result]) == 1 &&
                    count(observer, "classifiedAccepted") == 0, "one-shot query status " + result);
        }
        FixtureProvider provider = new FixtureProvider(); provider.bindingSwapchain = 0;
        NativeSourceImageObserver observer = observer(provider, 0); observer.observeLatest(1100);
        finishLatest(observer, 1100, true, false);
        check(provider.queryCalls == 0 && count(observer, "bindingBINDING_NOT_READY") == 1,
                "no query before valid swapchain binding");
        for (int epoch = 0; epoch < 3; ++epoch) {
            provider = new FixtureProvider();
            if (epoch == 0) ++provider.querySession;
            if (epoch == 1) ++provider.querySurface;
            if (epoch == 2) ++provider.querySwapchain;
            observer = observer(provider, 0); observer.observeLatest(1100); finishLatest(observer, 1100, true, true);
            check(count(observer, "classifiedAccepted") == 0, "epoch mismatch cannot seal " + epoch);
            has(observer, "lastStatus=" + (epoch == 2 ? "STALE_EPOCH" : "WRONG_IMAGE"));
        }
        for (int state : new int[] {2, 5, 6}) {
            provider = new FixtureProvider(); provider.queryResult = state; ++provider.querySwapchain;
            observer = observer(provider, 0); observer.observeLatest(1100);
            finishLatest(observer, 1100, true, true);
            check(count(observer, "querySTALE_EPOCH") == 1 && count(observer, "classifiedAccepted") == 0,
                    "validated missing payload still pins binding swapchain " + state);
        }
    }

    private static void failuresNeverReuseBytes() throws Exception {
        FixtureProvider provider = new FixtureProvider();
        NativeSourceImageObserver observer = observer(provider, 1);
        observer.observeLatest(1100); finishLatest(observer, 1100, true, true);
        provider.omitQuery = true;
        observer.observeLatest(1100); finishLatest(observer, 1100, true, true);
        has(observer, "lastStatus=MALFORMED");
        provider.omitQuery = false; provider.omitBinding = true;
        observer.observeLatest(1100); finishLatest(observer, 1100, true, true);
        has(observer, "lastStatus=MALFORMED");
        check(count(observer, "classifiedAccepted") == 1, "provider claiming success without bytes cannot reuse old evidence");
        provider.omitBinding = false; provider.bindingThrows = true;
        observer.observeLatest(1100); finishLatest(observer, 1100, true, true);
        has(observer, "lastReason=PROVIDER_EXCEPTION");
        provider.bindingThrows = false; provider.queryThrows = true;
        observer.observeLatest(2100); observer.retainCandidate(0);
        NativeSourceImageLedger ledger = ledger(observer); long lease = ledger.lease(1);
        check(ledger.sessionEpoch(1, lease) == 11 && ledger.surfaceEpoch(1, lease) == 22 &&
                ledger.swapchainEpoch(1, lease) == 33 && ledger.queueFrameNumber(1, lease, 0) == 0,
                "query exception retains exact binding/key but no accepted image");
        observer.classifyCandidate(0); observer.finishClassified(true, 2100, true, false);
        check(count(observer, "providerExceptions") == 2 && count(observer, "classifiedAccepted") == 1,
                "exceptions missing evidence only");
    }

    private static void replacementResetAndClose() throws Exception {
        FixtureProvider first = new FixtureProvider(), second = new FixtureProvider();
        NativeSourceImageObserver observer = observer(first, 1);
        observer.observeLatest(1100); observer.retainCandidate(0); observer.classifyCandidate(0);
        long generation = count(observer, "generation");
        observer.setProvider(first);
        observer.finishClassified(true, 1100, true, true);
        check(count(observer, "generation") == generation && count(observer, "classifiedAccepted") == 1,
                "same provider reference preserves retained metadata");
        observer.classifyCandidate(0); observer.setProvider(second);
        check(count(observer, "generation") == generation + 1, "provider identity increments local generation");
        has(observer, "lastStatus=null"); has(observer, "lastQueueFrame=0");
        observer.finishClassified(true, 1100, true, true);
        observer.classifyCandidate(0); observer.finishClassified(true, 1100, true, true);
        check(count(observer, "classifiedAccepted") == 1 && count(observer, "classifiedMissing") == 2,
                "replacement invalidates latest/candidate/classified, not relabeled new provider");
        observer.observeLatest(2100); finishLatest(observer, 2100, true, false);
        has(observer, "lastPair=null");
        observer.observeLatest(3100); observer.retainCandidate(0); observer.classifyCandidate(0);
        generation = count(observer, "generation");
        observer.resetImages();
        observer.finishClassified(true, 3100, true, true);
        check(count(observer, "generation") == generation && count(observer, "imageResets") == 1,
                "geometry reset preserves provider and counters, invalidates metadata");
        second.next(); observer.observeLatest(4100); finishLatest(observer, 4100, true, true);
        has(observer, "lastPair=null");
        observer.setProvider(null); observer.observeLatest(5100); finishLatest(observer, 5100, true, true);
        has(observer, "lastReason=NO_PROVIDER");
        observer.setProvider(second); observer.observeLatest(6100); observer.retainCandidate(0);
        long queries = second.queryCalls;
        observer.close(); observer.close(); observer.setProvider(first); observer.observeLatest(7100);
        has(observer, "lastStatus=null"); has(observer, "lastRawPts=0");
        observer.classifyLatest(); observer.finishClassified(true, 7100, true, true);
        check(second.queryCalls == queries && ledger(observer).lease(0) == 0 && ledger(observer).lease(1) == 0,
                "closed cannot query/reopen or retain images");
        has(observer, "closed=true"); has(observer, "authority=false");
    }

    private static void pixelClassificationAndQueuePairs() {
        FixtureProvider provider = new FixtureProvider();
        NativeSourceImageObserver observer = observer(provider, 0);
        observer.observeLatest(1100); finishLatest(observer, 1100, true, false);
        ++provider.submission; ++provider.composition; provider.held = true;
        observer.observeLatest(2100); finishLatest(observer, 2100, false, true);
        has(observer, "lastPair=HELD_QUEUED_IMAGE");
        provider.frame += 2; ++provider.submission; ++provider.composition; provider.held = false;
        observer.observeLatest(3100); finishLatest(observer, 3100, true, true);
        has(observer, "lastPair=QUEUE_FRAME_GAP");
        check(count(observer, "pixelUnique") == 1 && count(observer, "pixelHeld") == 1 &&
                count(observer, "pixelUnknown") == 1, "blind unique remains unknown, held and gap remain separate native facts");
        observer.finishClassified(true, 3100, true, true);
        check(count(observer, "classifiedAccepted") == 3 && count(observer, "classifiedMissing") == 1,
                "repeated finish cannot count same classified occupancy twice");
        provider.next(); observer.observeLatest(4100); observer.classifyLatest();
        provider.next(); observer.observeLatest(5100); observer.classifyLatest();
        observer.finishClassified(true, 5100, true, false);
        check(count(observer, "classifiedReplaced") == 1 && count(observer, "classifiedAccepted") == 4,
                "fresh classified replacement counts loss without preserving old identity");
    }

    private static void ringPressureAndBounds() throws Exception {
        FixtureProvider provider = new FixtureProvider();
        NativeSourceImageObserver observer = observer(provider, 2);
        observer.observeLatest(1100); observer.retainCandidate(0);
        provider.next(); observer.observeLatest(2100); observer.retainCandidate(1);
        provider.next(); observer.observeLatest(3100); observer.retainCandidate(0);
        check(count(observer, "candidateLosses") == 1, "occupied metadata overwritten only with counted loss");
        observer.classifyCandidate(0); observer.finishClassified(true, 1100, true, true);
        check(count(observer, "classifiedMismatch") == 1 && count(observer, "classifiedAccepted") == 0,
                "late old callback cannot use reused candidate's different PTS");
        observer.classifyCandidate(1); observer.finishClassified(true, 2100, true, true);
        has(observer, "lastQueueFrame=2");
        observer.classifyCandidate(0); observer.finishClassified(true, 3100, true, true);
        has(observer, "lastQueueFrame=3");
        observer.retainCandidate(-1); observer.retainCandidate(2);
        observer.classifyCandidate(2); observer.releaseCandidate(99);
        check(count(observer, "invalidOperations") == 4 && ledger(observer).capacity() == 4,
                "bounded slots fail observation without changing playback or allocating spillover");
        observer.clearCandidates();
        check(count(observer, "candidateLosses") == 1 && count(observer, "candidatesCleared") == 2,
                "lifetime loss counter survives clearing");
        for (int bad : new int[] {-1, NativeSourceImageLedger.MAX_CAPACITY - 1}) {
            boolean rejected = false;
            try { new NativeSourceImageObserver(bad); } catch (IllegalArgumentException expected) { rejected = true; }
            check(rejected, "constructor bounds");
        }
        Field generation = NativeSourceImageObserver.class.getDeclaredField("generation");
        generation.setAccessible(true); generation.setLong(observer, Long.MAX_VALUE);
        long queries = provider.queryCalls;
        observer.setProvider(new FixtureProvider()); observer.observeLatest(6100);
        finishLatest(observer, 6100, true, false);
        has(observer, "generationExhausted=true"); has(observer, "lastStatus=CLOSED");
        check(provider.queryCalls == queries && count(observer, "classifiedAccepted") == 2,
                "provider generation cannot wrap into old identity");
    }

    private static void missingLedgerAndExhaustion() throws Exception {
        NativeSourceImageLedger ledger = new NativeSourceImageLedger(2);
        check(ledger.observeMissing(0, 1, 1100, 0, 0, 0, NativeSourceImage.Decode.BUSY) ==
                NativeSourceImageLedger.Result.SUCCESS, "missing binding does not invent epochs");
        long lease = ledger.lease(0);
        check(ledger.sessionEpoch(0, lease) == 0 && ledger.surfaceEpoch(0, lease) == 0 &&
                ledger.swapchainEpoch(0, lease) == 0 && ledger.queueFrameNumber(0, lease, 0) == 0,
                "missing binding has no sealed identity");
        check(ledger.copy(0, lease, 1) == NativeSourceImageLedger.Result.SUCCESS &&
                ledger.observation(1, ledger.lease(1)) == NativeSourceImage.Decode.BUSY,
                "missing status copied, not converted into accepted");
        ledger.release(1, ledger.lease(1));
        check(ledger.observeMissing(1, 1, 1100, 0, 0, 0, NativeSourceImage.Decode.ACCEPTED) ==
                NativeSourceImageLedger.Result.BAD_ARGUMENT && ledger.lease(1) == 0,
                "missing API cannot manufacture accepted snapshot");
        FixtureProvider provider = new FixtureProvider();
        NativeSourceImageObserver observer = observer(provider, 1);
        Field counter = NativeSourceImageLedger.class.getDeclaredField("lastLease");
        counter.setAccessible(true); counter.setLong(ledger(observer), Long.MAX_VALUE);
        observer.observeLatest(1100); observer.classifyLatest();
        observer.finishClassified(true, 1100, true, true);
        check(count(observer, "ledgerFailures") == 1 && count(observer, "classifiedAccepted") == 0,
                "ledger exhaustion is missing evidence, not an exception or recycled identity");
    }

    private static void exercise(NativeSourceImageObserver observer, FixtureProvider provider, int loops) {
        for (int index = 0; index < loops; ++index) {
            provider.queryResult = 1;
            provider.next(); observer.observeLatest(1100 + provider.submission * 1000);
            observer.retainCandidate(0); observer.classifyCandidate(0);
            observer.finishClassified(true, 1100 + provider.submission * 1000, true, true);
            observer.releaseCandidate(0);
            observer.observeLatest(0); observer.classifyLatest(); observer.finishClassified(true, 0, true, false);
            provider.queryResult = 3;
            observer.observeLatest(2100 + provider.submission * 1000);
            observer.classifyLatest(); observer.finishClassified(true, 2100 + provider.submission * 1000, false, true);
        }
    }
    private static void allocations() {
        com.sun.management.ThreadMXBean bean = (com.sun.management.ThreadMXBean) ManagementFactory.getThreadMXBean();
        check(bean.isThreadAllocatedMemorySupported(), "allocation measurement required");
        bean.setThreadAllocatedMemoryEnabled(true);
        FixtureProvider provider = new FixtureProvider();
        NativeSourceImageObserver observer = observer(provider, 2);
        exercise(observer, provider, 50000);
        long thread = Thread.currentThread().getId();
        long before = bean.getThreadAllocatedBytes(thread);
        exercise(observer, provider, 10000);
        long allocated = bean.getThreadAllocatedBytes(thread) - before;
        check(allocated == 0L, "hot observer allocated " + allocated);
        check(provider.sawBuffers && count(observer, "observations") == 180000 &&
                count(observer, "classifiedAccepted") == 60000, "allocation fixture exercised real production paths");
    }

    public static void main(String[] args) throws Exception {
        asyncExactRetention(); exactTimestampAndEmptyCases(); statusesAndEpochs(); failuresNeverReuseBytes();
        replacementResetAndClose(); pixelClassificationAndQueuePairs(); ringPressureAndBounds();
        missingLedgerAndExhaustion(); allocations();
        System.out.println("NativeSourceImageObserverTest PASS: exact metadata observation; no source authority; zero hot allocations");
    }
}
