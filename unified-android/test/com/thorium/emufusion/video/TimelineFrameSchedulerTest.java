package com.thorium.emufusion.video;

import java.util.ArrayList;
import java.util.List;

/** Drives {@link TimelineFrameScheduler} with synthetic producers and a 120 Hz panel. */
public final class TimelineFrameSchedulerTest {
    private static final long PANEL = 8_333_333L;          // 120 Hz
    private static final long SOURCE60 = 2 * PANEL;        // paced 60 fps
    private static final long SOURCE30 = 4 * PANEL;

    public static void main(String[] args) {
        doublesSixtyEvenly();
        triplesFortyEvenly();
        bridgesAHeldFrameWithEvenSteps();
        lateProducerHoldsWithoutRestart();
        pauseIsNotInterpolated();
        motionNotReadyHoldsTheRealImage();
        multiScanOutputOnlyPresentsOnItsSlots();
        thirtyInASixtyStreamIsNotLate();
        stallResumesWithoutSkippingAhead();
        queuedLatencyIsTrimmed();
        oneHitchDoesNotInflateTheExpectedSpan();
        driftingSourceKeepsGenerating();
        passesRealImagesNoOutputLandsNear();
        passingKeepsWholeCadencesExact();
        passingNeedsAQueuedSuccessor();
        burstsAreNotTrimmed();
        trimsKeepTheLatencyTheSourceNeeds();
        System.out.println("TimelineFrameSchedulerTest passed");
    }

    /** Minimal renderer model: FIFO of source frames, active pair, rotate on REAL_RIGHT. */
    private static final class Rig {
        final TimelineFrameScheduler scheduler = new TimelineFrameScheduler();
        final List<long[]> fifo = new ArrayList<>();   // {sequence, timestamp}
        long leftSeq, leftTs, rightSeq, rightTs;
        boolean motionReady = true;
        boolean passing;
        int steadyQueued = 100;  // no trimming unless a test sets its steady depth
        final List<String> shown = new ArrayList<>();

        Rig(long outputPeriod, long sourcePeriod) { scheduler.configure(outputPeriod, sourcePeriod); }

        void produce(long sequence, long timestamp) { fifo.add(new long[] {sequence, timestamp}); fill(); }

        void fill() {
            if (leftSeq == 0 && !fifo.isEmpty()) {
                long[] f = fifo.remove(0); leftSeq = f[0]; leftTs = f[1];
            }
            if (leftSeq != 0 && rightSeq == 0 && !fifo.isEmpty() &&
                    scheduler.pairSpanAllowed(leftTs, fifo.get(0)[1])) {
                long[] f = fifo.remove(0); rightSeq = f[0]; rightTs = f[1];
            }
        }

        void vsync(long displayNs) {
            int kind = passing ?
                    scheduler.select(displayNs, leftSeq, leftTs, rightSeq, rightTs, motionReady,
                            fifo.size() - steadyQueued, rightSeq != 0 && !fifo.isEmpty()) :
                    scheduler.select(displayNs, leftSeq, leftTs, rightSeq, rightTs, motionReady,
                            fifo.size() - steadyQueued);
            if (kind == TimelineFrameScheduler.NONE) { shown.add("-"); return; }
            if (kind == TimelineFrameScheduler.GENERATED)
                shown.add(String.format(java.util.Locale.ROOT, "g%.2f", scheduler.pendingPhase()));
            else shown.add(kind == TimelineFrameScheduler.REAL_RIGHT ? "R" + rightSeq : "L" + leftSeq);
            int advance = scheduler.pendingAdvance();
            scheduler.commit(true);
            if (advance == 1) {
                leftSeq = rightSeq; leftTs = rightTs; rightSeq = 0; rightTs = 0; fill();
            }
        }
    }

    /** 50 fps on a 120 Hz lattice: outputs land 2.4 per pair, drifting across it. */
    private static List<String> drift(boolean passing) {
        long source50 = 20_000_000L;
        Rig rig = new Rig(PANEL, source50);
        rig.passing = passing;
        long t0 = 1_000_000_000L;
        int produced = 0;
        for (; produced < 6; ++produced) rig.produce(produced + 1, t0 + produced * source50);
        for (int v = 0; v < 120; ++v) {
            long now = t0 + 30_000_000L + v * PANEL;
            // Images arrive when they are made, a pair or so ahead of the
            // timeline (which anchors 30 ms after the first image).
            while (t0 + produced * source50 <= now) {
                rig.produce(produced + 1, t0 + produced * source50);
                ++produced;
            }
            rig.vsync(now);
        }
        return rig.shown;
    }

    private static void passesRealImagesNoOutputLandsNear() {
        List<String> before = drift(false);
        List<String> after = drift(true);
        long realBefore = before.stream().filter(s -> s.startsWith("R")).count();
        long realAfter = after.stream().filter(s -> s.startsWith("R")).count();
        check(!after.contains("-") && !before.contains("-"), "no repeated outputs " + after);
        // Every real image used to be shown, some up to half an output off its
        // time; now only those an output lands within a quarter period of.
        check(realBefore >= 48 && realAfter < realBefore * 3 / 4 && realAfter > 10,
                "real images shown " + realBefore + " -> " + realAfter);
    }

    private static void passingKeepsWholeCadencesExact() {
        Rig rig = new Rig(PANEL, SOURCE60);
        rig.passing = true;
        long t0 = 1_000_000_000L;
        for (int i = 0; i < 4; ++i) rig.produce(i + 1, t0 + i * SOURCE60);
        for (int v = 0; v < 12; ++v) {
            rig.vsync(t0 + 30_000_000L + v * PANEL);
            if (v % 2 == 0) rig.produce(5 + v / 2, t0 + (4 + v / 2) * SOURCE60);
        }
        String expect = "[L1, g0.50, R2, g0.50, R3, g0.50, R4, g0.50, R5, g0.50, R6, g0.50]";
        check(rig.shown.toString().equals(expect), "x2 cadence with passing " + rig.shown);
    }

    private static void passingNeedsAQueuedSuccessor() {
        // Without a queued successor the pair cannot advance past its right
        // image, so it is still shown (never a repeat or a skipped image).
        long source50 = 20_000_000L;
        Rig rig = new Rig(PANEL, source50);
        rig.passing = true;
        long t0 = 1_000_000_000L;
        rig.produce(1, t0);
        rig.produce(2, t0 + source50);
        for (int v = 0; v < 6; ++v) rig.vsync(t0 + 30_000_000L + v * PANEL);
        check(rig.shown.contains("R2"), "right image shown without a successor " + rig.shown);
    }

    private static void burstsAreNotTrimmed() {
        // 60 fps delivered two images at a time every 33 ms (a producer that
        // presents in bursts): the extra queued image is momentary, so the
        // timeline keeps its latency instead of trimming toward the newest
        // image and then waiting on a late successor.
        Rig rig = new Rig(PANEL, SOURCE60);
        rig.steadyQueued = 0;  // every image beyond the pair counts as excess
        long t0 = 1_000_000_000L;
        int produced = 0;
        for (; produced < 2; ++produced) rig.produce(produced + 1, t0 + produced * SOURCE60);
        int momentaryExcess = 0;
        for (int v = 0; v < 240; ++v) {
            long now = t0 + 40_000_000L + v * PANEL;
            if (v % 4 == 0) {
                rig.produce(produced + 1, t0 + produced * SOURCE60);
                rig.produce(produced + 2, t0 + (produced + 1) * SOURCE60);
                produced += 2;
            }
            if (rig.fifo.size() >= TimelineFrameScheduler.TRIM_EXCESS_QUEUED) ++momentaryExcess;
            rig.vsync(now);
        }
        String diagnostics = rig.scheduler.diagnostics();
        check(momentaryExcess > 20, "the bursts do queue extra images " + momentaryExcess);
        check(diagnostics.contains("timelineTrims=0 "), "bursts are not trimmed: " + diagnostics);
        check(!rig.shown.subList(1, rig.shown.size()).contains("-"), "no repeated output " + rig.shown);
    }

    private static String backlogDiagnostics(long requiredLatencyNs) {
        // A 60-fps source with a standing backlog: four images queued beyond
        // the pair for two seconds, so the latency is trimmed unless the
        // source has shown it needs that latency.
        Rig rig = new Rig(PANEL, SOURCE60);
        rig.steadyQueued = 0;
        rig.scheduler.setRequiredLatencyNs(requiredLatencyNs);
        long t0 = 1_000_000_000L;
        int produced = 0;
        for (; produced < 6; ++produced) rig.produce(produced + 1, t0 + produced * SOURCE60);
        for (int v = 0; v < 240; ++v) {
            long now = t0 + 40_000_000L + v * PANEL;
            while (rig.fifo.size() < 4) {
                rig.produce(produced + 1, t0 + produced * SOURCE60);
                ++produced;
            }
            rig.vsync(now);
        }
        return rig.scheduler.diagnostics();
    }

    private static void trimsKeepTheLatencyTheSourceNeeds() {
        String unknown = backlogDiagnostics(Long.MIN_VALUE);
        check(!unknown.contains("timelineTrims=0 "), "a standing backlog is trimmed: " + unknown);
        check(unknown.contains("timelineTrimsHeld=0 "), "nothing holds it: " + unknown);
        // Images have been arriving a second after their stamps: no trim.
        String needed = backlogDiagnostics(1_000_000_000L);
        check(needed.contains("timelineTrims=0 "), "latency the source needs is kept: " + needed);
        check(!needed.contains("timelineTrimsHeld=0 "), "the held trims are counted: " + needed);
        // A small requirement still lets the excess latency go.
        String small = backlogDiagnostics(-1_000_000_000L);
        check(!small.contains("timelineTrims=0 "), "latency beyond the need is trimmed: " + small);
    }

    private static void doublesSixtyEvenly() {
        Rig rig = new Rig(PANEL, SOURCE60);
        long t0 = 1_000_000_000L;
        for (int i = 0; i < 4; ++i) rig.produce(i + 1, t0 + i * SOURCE60);
        for (int v = 0; v < 12; ++v) {
            rig.vsync(t0 + 30_000_000L + v * PANEL);
            if (v % 2 == 0) rig.produce(5 + v / 2, t0 + (4 + v / 2) * SOURCE60);
        }
        // Prime on L1, then every vsync alternates generated midpoint / real.
        String expect = "[L1, g0.50, R2, g0.50, R3, g0.50, R4, g0.50, R5, g0.50, R6, g0.50]";
        check(rig.shown.toString().equals(expect), "x2 cadence " + rig.shown);
    }

    private static void triplesFortyEvenly() {
        long source40 = 3 * PANEL;
        Rig rig = new Rig(PANEL, source40);
        long t0 = 1_000_000_000L;
        for (int i = 0; i < 6; ++i) rig.produce(i + 1, t0 + i * source40);
        for (int v = 0; v < 10; ++v) rig.vsync(t0 + 30_000_000L + v * PANEL);
        String expect = "[L1, g0.33, g0.67, R2, g0.33, g0.67, R3, g0.33, g0.67, R4]";
        check(rig.shown.toString().equals(expect), "x3 cadence " + rig.shown);
    }

    private static void bridgesAHeldFrameWithEvenSteps() {
        Rig rig = new Rig(PANEL, SOURCE60);
        long t0 = 1_000_000_000L;
        // Frame 3 is held: the next unique image arrives two periods later.
        long[] stamps = {0, SOURCE60, 3 * SOURCE60, 4 * SOURCE60, 5 * SOURCE60, 6 * SOURCE60};
        for (int i = 0; i < stamps.length; ++i) rig.produce(i + 1, t0 + stamps[i]);
        for (int v = 0; v < 12; ++v) rig.vsync(t0 + 30_000_000L + v * PANEL);
        String expect = "[L1, g0.50, R2, g0.25, g0.50, g0.75, R3, g0.50, R4, g0.50, R5, g0.50]";
        check(rig.shown.toString().equals(expect), "held frame bridged evenly " + rig.shown);
        check(!rig.shown.contains("-"), "no empty output slot across the hold");
    }

    private static void lateProducerHoldsWithoutRestart() {
        Rig rig = new Rig(PANEL, SOURCE60);
        long t0 = 1_000_000_000L;
        rig.produce(1, t0);
        rig.produce(2, t0 + SOURCE60);
        for (int v = 0; v < 6; ++v) rig.vsync(t0 + 30_000_000L + v * PANEL);
        // Producer stalls; then resumes.
        rig.produce(3, t0 + 2 * SOURCE60);
        rig.produce(4, t0 + 3 * SOURCE60);
        for (int v = 6; v < 10; ++v) rig.vsync(t0 + 30_000_000L + v * PANEL);
        check(rig.scheduler.primed(), "the timeline survives a late producer");
        check(rig.shown.get(0).equals("L1") && rig.shown.contains("R3"),
                "playback resumes from the held image " + rig.shown);
    }

    private static void pauseIsNotInterpolated() {
        Rig rig = new Rig(PANEL, SOURCE60);
        long t0 = 1_000_000_000L;
        rig.produce(1, t0);
        rig.produce(2, t0 + SOURCE60);
        rig.produce(3, t0 + 40 * SOURCE60);  // a loading pause
        for (int v = 0; v < 8; ++v) rig.vsync(t0 + 30_000_000L + v * PANEL);
        for (String s : rig.shown)
            check(!s.startsWith("g") || rig.shown.indexOf(s) < 2, "no morph across a pause " + rig.shown);
        check(!rig.scheduler.pairSpanAllowed(t0, t0 + 40 * SOURCE60), "pause is not a pair");
    }

    private static void motionNotReadyHoldsTheRealImage() {
        Rig rig = new Rig(PANEL, SOURCE60);
        rig.motionReady = false;
        long t0 = 1_000_000_000L;
        for (int i = 0; i < 4; ++i) rig.produce(i + 1, t0 + i * SOURCE60);
        for (int v = 0; v < 6; ++v) rig.vsync(t0 + 30_000_000L + v * PANEL);
        for (String s : rig.shown) check(!s.startsWith("g"), "never shows unready motion " + rig.shown);
        check(rig.shown.contains("R2") && rig.shown.contains("R3"), "real images keep flowing " + rig.shown);
    }

    private static void multiScanOutputOnlyPresentsOnItsSlots() {
        // 30 -> 60 on a 120 Hz panel: one output every two scans.
        Rig rig = new Rig(2 * PANEL, SOURCE30);
        long t0 = 1_000_000_000L;
        for (int i = 0; i < 5; ++i) rig.produce(i + 1, t0 + i * SOURCE30);
        for (int v = 0; v < 12; ++v) rig.vsync(t0 + 30_000_000L + v * PANEL);
        String expect = "[L1, -, g0.50, -, R2, -, g0.50, -, R3, -, g0.50, -]";
        check(rig.shown.toString().equals(expect), "30->60 on 120 Hz " + rig.shown);
    }

    private static void thirtyInASixtyStreamIsNotLate() {
        // The tier is not known yet: the scheduler is told 60, frames come at 30.
        Rig rig = new Rig(PANEL, SOURCE60);
        rig.motionReady = false;
        long t0 = 1_000_000_000L;
        int produced = 0;
        rig.produce(++produced, t0);
        rig.produce(++produced, t0 + SOURCE30);
        for (int v = 0; v < 64; ++v) {
            long now = t0 + 40_000_000L + v * PANEL;
            while (t0 + produced * SOURCE30 <= now - 6_000_000L) rig.produce(++produced, t0 + produced * SOURCE30);
            rig.vsync(now);
        }
        // After the first pair the span is learned: every real image is held
        // exactly four scans (30 fps), none early or late.
        List<Integer> gaps = new ArrayList<>();
        int last = -1;
        for (int i = 0; i < rig.shown.size(); ++i)
            if (rig.shown.get(i).startsWith("R")) { if (last >= 0) gaps.add(i - last); last = i; }
        check(gaps.size() >= 10, "real images keep flowing " + rig.shown);
        for (int g : gaps.subList(3, gaps.size())) check(g == 4, "even 30 fps holds " + gaps);
    }

    private static void stallResumesWithoutSkippingAhead() {
        Rig rig = new Rig(PANEL, SOURCE60);
        long t0 = 1_000_000_000L;
        for (int i = 0; i < 3; ++i) rig.produce(i + 1, t0 + i * SOURCE60);
        for (int v = 0; v < 4; ++v) rig.vsync(t0 + 40_000_000L + v * PANEL);
        // A 100 ms stall, then frames resume with their normal timestamps.
        for (int v = 4; v < 16; ++v) rig.vsync(t0 + 40_000_000L + v * PANEL);
        for (int i = 3; i < 8; ++i) rig.produce(i + 1, t0 + i * SOURCE60);
        for (int v = 16; v < 24; ++v) rig.vsync(t0 + 40_000_000L + v * PANEL);
        List<String> after = rig.shown.subList(16, 24);
        check(after.get(0).equals("R4") || after.get(0).equals("R3"),
                "the overdue image shows at once " + rig.shown);
        for (int i = 1; i < after.size(); ++i)
            check(!after.get(i).equals("-"), "playback continues every slot " + rig.shown);
    }

    private static void queuedLatencyIsTrimmed() {
        Rig rig = new Rig(PANEL, SOURCE60);
        rig.steadyQueued = 1;
        long t0 = 1_000_000_000L;
        for (int i = 0; i < 6; ++i) rig.produce(i + 1, t0 + i * SOURCE60);  // backlog of 3 extra
        int produced = 6;
        for (int v = 0; v < 240; ++v) {
            long now = t0 + 40_000_000L + v * PANEL;
            if (v % 2 == 0) rig.produce(++produced, t0 + (produced - 1) * SOURCE60);
            rig.vsync(now);
        }
        check(rig.fifo.size() <= 2, "the backlog drains to the steady depth " + rig.fifo.size());
        check(!rig.shown.subList(1, rig.shown.size()).contains("-"), "no slot is skipped while trimming");
    }

    private static void oneHitchDoesNotInflateTheExpectedSpan() {
        Rig rig = new Rig(2 * PANEL, SOURCE30);
        long t0 = 1_000_000_000L;
        long[] stamps = new long[24];
        for (int i = 0; i < stamps.length; ++i) stamps[i] = i * SOURCE30 + (i >= 12 ? 2 * SOURCE30 : 0);
        for (int i = 0; i < stamps.length; ++i) rig.produce(i + 1, t0 + stamps[i]);
        long peak = 0;
        for (int v = 0; v < 70; ++v) {
            rig.vsync(t0 + 70_000_000L + v * PANEL);
            peak = Math.max(peak, rig.scheduler.expectedSpanNs());
        }
        check(peak < SOURCE30 + SOURCE30 / 4,
                "a single 100 ms span leaves the estimate near 33 ms: peak " + peak);
    }

    private static void driftingSourceKeepsGenerating() {
        // 30 -> 60 on 120 Hz; frames are stamped every 33.3 ms but arrive
        // 0.5 ms later each time (an emulator running slower than its clock).
        Rig rig = new Rig(2 * PANEL, SOURCE30);
        rig.motionReady = true;
        long t0 = 1_000_000_000L;
        int produced = 0;
        rig.produce(++produced, t0);
        rig.produce(++produced, t0 + SOURCE30);
        rig.produce(++produced, t0 + 2 * SOURCE30);
        int generated = 0;
        for (int v = 0; v < 960; ++v) {
            long now = t0 + 70_000_000L + v * PANEL;
            while (t0 + produced * (SOURCE30 + 500_000L) + 2 * SOURCE30 <= now)
                rig.produce(++produced, t0 + produced * SOURCE30);
            rig.vsync(now);
            if (v >= 480 && rig.shown.get(rig.shown.size() - 1).startsWith("g")) ++generated;
        }
        // 480 vsyncs = 4 s = ~118 real frames; nearly every pair keeps its midpoint.
        check(generated >= 100, "generation survives a drifting source: " + generated);
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
