package com.thorium.emufusion.video;

public final class ArrivalQueuePolicyTest {
    private static final long PERIOD = 8_333_333L;

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        ArrivalQueuePolicy policy = new ArrivalQueuePolicy();
        long callback = 1_000_000_000L, latch = callback + 5_500_000L;
        check(policy.present(latch - 1_500_000L, callback, latch, PERIOD),
                "an image in time goes to the latch");
        check(policy.present(latch - ArrivalQueuePolicy.MIN_TO_LATCH_NS, callback, latch, PERIOD),
                "exactly enough time");
        check(!policy.present(latch - 500_000L, callback, latch, PERIOD),
                "an image with too little time goes through its callback");
        check(!policy.present(latch + 1_000L, callback, latch, PERIOD), "past the latch");
        long later = callback + PERIOD + 5_500_000L;
        check(!policy.present(callback + 7_000_000L, callback, later, PERIOD),
                "the latch after the next callback belongs to that callback");
        check(!policy.present(latch - 2_000_000L, 0L, latch, PERIOD), "no callback yet");

        policy.observeWork(6_500_000L);
        check(policy.present(latch - 1_500_000L, callback, latch, PERIOD),
                "one slow frame does not lock it out");
        check(ArrivalQueuePolicy.TARGET_WAIT_NS == 3_500_000L, "the target stays fixed");
        policy.observeWork(0L);
        policy.presented();
        policy.missed();
        check(policy.presents() == 1L && policy.misses() == 1L, "counted");
        System.out.println("Arrival queue policy tests passed");
    }
}
