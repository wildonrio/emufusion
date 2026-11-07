package com.thorium.emufusion.video;

public final class HeldSwapCadenceTest {
    private static final long MS = 1_000_000L;
    private static final long PANEL = 8 * MS;
    private static final long OUTPUT = 16 * MS;

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        aFrameOnItsSlotKeepsTheExtraScan();
        aFrameAScanLateTriesSooner();
        thePairsRealImageMayFollowItButTheNextPairMayNot();
        aLaterPairMayGoSoonerAgain();
        nothingToCompareWithIsNoReason();
        System.out.println("HeldSwapCadenceTest passed");
    }

    private static void aFrameOnItsSlotKeepsTheExtraScan() {
        HeldSwapCadence c = new HeldSwapCadence();
        check(!c.wantsSooner(100 * MS, 116 * MS, 100 * MS, OUTPUT, PANEL), "exactly on the rhythm");
        check(!c.wantsSooner(100 * MS, 108 * MS, 100 * MS, OUTPUT, PANEL), "ahead of the rhythm");
    }

    private static void aFrameAScanLateTriesSooner() {
        HeldSwapCadence c = new HeldSwapCadence();
        check(c.wantsSooner(100 * MS, 124 * MS, 100 * MS, OUTPUT, PANEL), "a scan past the rhythm");
    }

    private static void thePairsRealImageMayFollowItButTheNextPairMayNot() {
        HeldSwapCadence c = new HeldSwapCadence();
        c.committed(100 * MS, true, OUTPUT);
        check(c.pairs() == 1L, "one pair counted");
        check(c.wantsSooner(116 * MS, 150 * MS, 124 * MS, OUTPUT, PANEL), "the pair's real image");
        c.committed(116 * MS, true, OUTPUT);
        check(c.pairs() == 1L, "the real image is the same pair");
        check(!c.wantsSooner(132 * MS, 160 * MS, 132 * MS, OUTPUT, PANEL), "the next pair goes back");
    }

    private static void aLaterPairMayGoSoonerAgain() {
        HeldSwapCadence c = new HeldSwapCadence();
        c.committed(100 * MS, true, OUTPUT);
        check(c.wantsSooner(100 * MS + 3 * OUTPUT, 200 * MS, 124 * MS, OUTPUT, PANEL), "two outputs on");
        c.committed(100 * MS + 3 * OUTPUT, true, OUTPUT);
        check(c.pairs() == 2L, "a second pair");
    }

    private static void nothingToCompareWithIsNoReason() {
        HeldSwapCadence c = new HeldSwapCadence();
        check(!c.wantsSooner(100 * MS, 200 * MS, 0L, OUTPUT, PANEL), "no earlier frame");
        c.committed(100 * MS, false, OUTPUT);
        check(c.pairs() == 0L, "a frame with the extra scan is no pair");
    }
}
