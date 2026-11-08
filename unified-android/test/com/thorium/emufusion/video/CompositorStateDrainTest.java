package com.thorium.emufusion.video;

public final class CompositorStateDrainTest {
    private static final long PERIOD = 8_333_333L;
    private static final long SECOND = 1_000_000_000L;

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void fast(CompositorStateDrain drain, long nowNs) {
        drain.observe(nowNs - 1_800_000L, nowNs, PERIOD);
    }

    private static void pipelined(CompositorStateDrain drain, long nowNs) {
        drain.observe(nowNs - 10_100_000L, nowNs, PERIOD);
    }

    public static void main(String[] args) {
        unknownAndFastStatesKeepEveryFrame();
        waitsBeforeLeavingOneOut();
        aLastingFastStateKeepsTheMinimumSpacing();
        aShortFastStateDoublesTheSpacing();
        spacingHalvesAgainOnceItLasts();
        aDrainThatChangesNothingDoublesTheSpacing();
        aMiddlingStayKeepsTheSpacing();
        spacingIsBounded();
        System.out.println("Compositor state drain tests passed");
    }

    private static void unknownAndFastStatesKeepEveryFrame() {
        CompositorStateDrain drain = new CompositorStateDrain();
        check(!drain.drain(100L * SECOND), "state unknown");
        fast(drain, 100L * SECOND);
        check(drain.fast() && !drain.drain(200L * SECOND), "fast state");
        check(drain.drains() == 0L, "nothing left out");
    }

    private static void waitsBeforeLeavingOneOut() {
        CompositorStateDrain drain = new CompositorStateDrain();
        pipelined(drain, 100L * SECOND);
        check(!drain.drain(101L * SECOND), "too soon");
        check(drain.drain(102L * SECOND), "after two seconds");
        check(!drain.drain(103L * SECOND), "spaced");
        check(drain.drains() == 1L, "one left out");
    }

    private static void aLastingFastStateKeepsTheMinimumSpacing() {
        CompositorStateDrain drain = new CompositorStateDrain();
        pipelined(drain, 100L * SECOND);
        check(drain.drain(102L * SECOND), "left out");
        fast(drain, 102L * SECOND);
        pipelined(drain, 150L * SECOND);
        check(drain.spacingNs() == CompositorStateDrain.MIN_SPACING_NS, "stays at the minimum");
        check(drain.drain(152L * SECOND), "again");
    }

    private static void aShortFastStateDoublesTheSpacing() {
        CompositorStateDrain drain = new CompositorStateDrain();
        pipelined(drain, 100L * SECOND);
        check(drain.drain(102L * SECOND), "left out");
        fast(drain, 102L * SECOND);
        pipelined(drain, 105L * SECOND);
        check(drain.spacingNs() == CompositorStateDrain.MIN_SPACING_NS, "not doubled yet");
        check(!drain.drain(106L * SECOND), "the pipelined state must last first");
        check(drain.drain(107L * SECOND), "once more");
        fast(drain, 107L * SECOND);
        pipelined(drain, 108L * SECOND);
        check(drain.spacingNs() == 2L * CompositorStateDrain.MIN_SPACING_NS, "doubled");
        check(!drain.drain(120L * SECOND), "not at the old spacing");
        check(drain.drain(137L * SECOND), "at the new spacing");
    }

    private static void spacingHalvesAgainOnceItLasts() {
        CompositorStateDrain drain = new CompositorStateDrain();
        pipelined(drain, 100L * SECOND);
        check(drain.drain(102L * SECOND), "first");
        fast(drain, 102L * SECOND);
        pipelined(drain, 104L * SECOND);
        check(drain.drain(106L * SECOND), "once more");
        fast(drain, 106L * SECOND);
        pipelined(drain, 107L * SECOND);
        check(drain.spacingNs() == 30L * SECOND, "doubled");
        check(drain.drain(136L * SECOND), "second");
        fast(drain, 136L * SECOND);
        pipelined(drain, 154L * SECOND);
        check(drain.spacingNs() == 15L * SECOND, "over the short stay: halved");
        check(drain.drain(156L * SECOND), "third");
        fast(drain, 156L * SECOND);
        pipelined(drain, 200L * SECOND);
        check(drain.spacingNs() == 15L * SECOND, "never under the minimum");
    }

    private static void aDrainThatChangesNothingDoublesTheSpacing() {
        CompositorStateDrain drain = new CompositorStateDrain();
        pipelined(drain, 100L * SECOND);
        check(drain.drain(102L * SECOND), "left out");
        pipelined(drain, 103L * SECOND);
        check(!drain.drain(103L * SECOND), "too soon to tell");
        check(drain.drain(104L * SECOND), "no fast state came of it: once more at once");
        check(drain.spacingNs() == 15L * SECOND, "not doubled yet");
        check(!drain.drain(106L * SECOND), "nor of that");
        check(drain.spacingNs() == 30L * SECOND, "doubled");
        check(!drain.drain(120L * SECOND), "spaced");
        check(drain.drain(134L * SECOND), "tries again later");
    }

    private static void aMiddlingStayKeepsTheSpacing() {
        CompositorStateDrain drain = new CompositorStateDrain();
        pipelined(drain, 100L * SECOND);
        check(drain.drain(102L * SECOND), "left out");
        fast(drain, 102L * SECOND);
        pipelined(drain, 109L * SECOND);
        check(drain.spacingNs() == CompositorStateDrain.MIN_SPACING_NS, "7 s of 15: tries again on time");
        check(drain.drain(117L * SECOND), "the next try");
    }

    private static void spacingIsBounded() {
        CompositorStateDrain drain = new CompositorStateDrain();
        long now = 100L * SECOND;
        pipelined(drain, now);
        for (int i = 0; i < 12; ++i) {
            now += 2L * CompositorStateDrain.MAX_SPACING_NS;
            drain.drain(now);
            fast(drain, now);
            pipelined(drain, now + SECOND);
            now += SECOND;
        }
        check(drain.spacingNs() == CompositorStateDrain.MAX_SPACING_NS, "bounded");
    }
}
