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
        pipelined(drain, 106L * SECOND);
        check(drain.spacingNs() == 2L * CompositorStateDrain.MIN_SPACING_NS, "doubled");
        check(!drain.drain(115L * SECOND), "not at the old spacing");
        check(drain.drain(122L * SECOND), "at the new spacing");
    }

    private static void spacingHalvesAgainOnceItLasts() {
        CompositorStateDrain drain = new CompositorStateDrain();
        pipelined(drain, 100L * SECOND);
        check(drain.drain(102L * SECOND), "first");
        fast(drain, 102L * SECOND);
        pipelined(drain, 104L * SECOND);
        check(drain.spacingNs() == 20L * SECOND, "doubled");
        check(drain.drain(122L * SECOND), "second");
        fast(drain, 122L * SECOND);
        pipelined(drain, 150L * SECOND);
        check(drain.spacingNs() == 10L * SECOND, "halved");
    }

    private static void aDrainThatChangesNothingDoublesTheSpacing() {
        CompositorStateDrain drain = new CompositorStateDrain();
        pipelined(drain, 100L * SECOND);
        check(drain.drain(102L * SECOND), "left out");
        pipelined(drain, 103L * SECOND);
        check(!drain.drain(112L * SECOND), "no fast state came of it");
        check(drain.spacingNs() == 20L * SECOND, "doubled");
        check(drain.drain(122L * SECOND), "tries again later");
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
