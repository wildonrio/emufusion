package com.thorium.emufusion.video;

import java.util.HashSet;
import java.util.Set;

public final class BurnInShiftTest {
    private static final int AMPLITUDE = 8;

    public static void main(String[] args) {
        staysWithinTheBox();
        movesAPixelAtATime();
        coversTheWholeBox();
        noAmplitudeNoShift();
        System.out.println("BurnInShiftTest passed");
    }

    private static void staysWithinTheBox() {
        for (long t = 0; t < 2 * BurnInShift.PERIOD_Y_MS; t += 250L) {
            int x = BurnInShift.x(t, AMPLITUDE), y = BurnInShift.y(t, AMPLITUDE);
            check(Math.abs(x) <= AMPLITUDE && Math.abs(y) <= AMPLITUDE, "within the box at " + t);
        }
        check(BurnInShift.x(0L, AMPLITUDE) == -AMPLITUDE, "starts at one edge");
        check(BurnInShift.x(BurnInShift.PERIOD_X_MS / 2, AMPLITUDE) == AMPLITUDE, "reaches the other");
    }

    /** One-second updates (the counter's own rate) never jump more than a pixel. */
    private static void movesAPixelAtATime() {
        int px = BurnInShift.x(0L, AMPLITUDE), py = BurnInShift.y(0L, AMPLITUDE);
        for (long t = 1000L; t < 3 * BurnInShift.PERIOD_X_MS; t += 1000L) {
            int x = BurnInShift.x(t, AMPLITUDE), y = BurnInShift.y(t, AMPLITUDE);
            check(Math.abs(x - px) <= 1 && Math.abs(y - py) <= 1, "one pixel at " + t);
            px = x;
            py = y;
        }
    }

    /** Over both periods every offset in the box is visited, not just a diagonal. */
    private static void coversTheWholeBox() {
        Set<Integer> seen = new HashSet<>();
        for (long t = 0; t < BurnInShift.PERIOD_X_MS * BurnInShift.PERIOD_Y_MS / 1000L; t += 500L)
            seen.add((BurnInShift.x(t, AMPLITUDE) + AMPLITUDE) * 100 + BurnInShift.y(t, AMPLITUDE) + AMPLITUDE);
        int cells = (2 * AMPLITUDE + 1) * (2 * AMPLITUDE + 1);
        check(seen.size() == cells, "covered " + seen.size() + " of " + cells);
    }

    private static void noAmplitudeNoShift() {
        check(BurnInShift.x(12_345L, 0) == 0 && BurnInShift.y(12_345L, 0) == 0, "no amplitude");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
