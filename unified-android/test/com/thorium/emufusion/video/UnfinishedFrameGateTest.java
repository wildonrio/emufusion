package com.thorium.emufusion.video;

public final class UnfinishedFrameGateTest {
    private static final long PERIOD = 8_333_333L;
    private static final long SECOND = 1_000_000_000L;

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        fastFollowsTheLastShownFrame();
        unknownTimesLeaveTheState();
        rareLateFramesAreAllWithheld();
        lateFramesEveryTimeBackOff();
        spacingRecoversAfterAQuietStretch();
        pipelinedStateDrainsAfterAWhile();
    }

    private static void pipelinedStateDrainsAfterAWhile() {
        UnfinishedFrameGate gate = new UnfinishedFrameGate();
        long now = 10L * SECOND;
        check(!gate.drain(now), "nothing known yet");
        gate.observe(now, now + 1_800_000L, PERIOD);
        check(!gate.drain(now + 5L * SECOND), "the fast state needs no drain");
        now += 5L * SECOND;
        gate.observe(now, now + 10_100_000L, PERIOD);
        check(!gate.drain(now + SECOND), "not right away");
        check(gate.drain(now + 3L * SECOND), "after it has lasted");
        check(!gate.drain(now + 4L * SECOND), "one per spacing");
        gate.observe(now + 5L * SECOND, now + 5L * SECOND + 10_100_000L, PERIOD);
        check(!gate.drain(now + 10L * SECOND), "still within the spacing");
        check(gate.drain(now + 20L * SECOND), "again after the spacing");
        check(gate.drains() == 2L, "counted");
    }

    private static void fastFollowsTheLastShownFrame() {
        UnfinishedFrameGate gate = new UnfinishedFrameGate();
        check(!gate.fast(), "unknown until a frame has been shown");
        gate.observe(100_000_000L, 101_800_000L, PERIOD);
        check(gate.fast(), "shown 1.8 ms after its latch");
        gate.observe(110_000_000L, 120_100_000L, PERIOD);
        check(!gate.fast(), "shown 10.1 ms after its latch");
    }

    private static void unknownTimesLeaveTheState() {
        UnfinishedFrameGate gate = new UnfinishedFrameGate();
        gate.observe(100_000_000L, 101_800_000L, PERIOD);
        gate.observe(0L, 120_000_000L, PERIOD);
        gate.observe(100_000_000L, 0L, PERIOD);
        check(gate.fast(), "a frame without times says nothing");
    }

    private static void rareLateFramesAreAllWithheld() {
        UnfinishedFrameGate gate = new UnfinishedFrameGate();
        for (int i = 0; i < 6; ++i)
            check(gate.withhold(i * 8L * SECOND), "one every 8 s is always withheld");
        check(gate.withheld() == 6L && gate.refused() == 0L, "all counted as withheld");
        check(gate.spacingNs() == UnfinishedFrameGate.MIN_SPACING_NS, "spacing stays at its minimum");
    }

    private static void lateFramesEveryTimeBackOff() {
        UnfinishedFrameGate gate = new UnfinishedFrameGate();
        int withheld = 0;
        long frames = 120L * 60L;  // a minute of frames, every one late
        for (long i = 0; i < frames; ++i)
            if (gate.withhold(i * SECOND / 120L)) ++withheld;
        check(withheld <= 8, "a persistent case costs few frames: " + withheld);
        check(gate.spacingNs() == UnfinishedFrameGate.MAX_SPACING_NS, "spacing reaches its maximum");
        check(gate.refused() == frames - withheld, "the rest are queued as before");
    }

    private static void spacingRecoversAfterAQuietStretch() {
        UnfinishedFrameGate gate = new UnfinishedFrameGate();
        long now = 0L;
        check(gate.withhold(now), "first");
        now += 3L * SECOND;
        check(gate.withhold(now), "second");
        check(gate.spacingNs() == 2L * UnfinishedFrameGate.MIN_SPACING_NS, "grew");
        now += 40L * SECOND;
        check(gate.withhold(now), "after a quiet stretch");
        check(gate.spacingNs() == UnfinishedFrameGate.MIN_SPACING_NS, "shrank again");
    }
}
