package com.thorium.lucent.video;

public final class PhysicalPresentMarginTest {
    public static void main(String[] args) {
        check(PhysicalPresentMargin.normalize(564_427L, 8_337_942L) == 564_427L,
                "ordinary positive margin is preserved");
        check(PhysicalPresentMargin.normalize(-564_427L, 8_337_942L) == 0L,
                "r25 bounded wrapped-late margin becomes zero headroom");
        check(PhysicalPresentMargin.normalize(-8_337_942L, 8_337_942L) == 0L,
                "one-refresh wrap is the inclusive bound");
        expectFailure(() -> PhysicalPresentMargin.normalize(
                -8_337_943L, 8_337_942L));
        expectFailure(() -> PhysicalPresentMargin.normalize(Long.MIN_VALUE, 1L));
        expectFailure(() -> PhysicalPresentMargin.normalize(1L, 0L));
        System.out.println("PhysicalPresentMarginTest passed");
    }

    private static void expectFailure(Runnable action) {
        try {
            action.run();
            throw new AssertionError("expected failure");
        } catch (IllegalArgumentException expected) {
            // expected
        }
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
