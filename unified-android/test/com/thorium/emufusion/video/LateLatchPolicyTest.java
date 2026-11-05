package com.thorium.emufusion.video;

public final class LateLatchPolicyTest {
    private static final long PERIOD = 8_333_333L;

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        LateLatchPolicy policy = new LateLatchPolicy();
        long callback = 1_000_000_000L, latch = callback + 5_500_000L;
        long work = LateLatchPolicy.INITIAL_WORK_NS, margin = LateLatchPolicy.MARGIN_NS;
        check(policy.targetWaitNs() == work + margin, "target: the work and a margin");

        long arrived = latch - work - margin;
        check(policy.present(arrived + 1_000_000L, arrived, callback, latch, PERIOD),
                "an image at its target wait goes to the latch");
        check(!policy.present(latch - 500_000L, latch - 1_000_000L, callback, latch, PERIOD),
                "an image with too little time goes through its callback");
        check(!policy.present(latch + 1_000L, arrived, callback, latch, PERIOD), "past the latch");
        long later = callback + PERIOD + 5_500_000L;
        check(!policy.present(callback + 7_000_000L, callback + 6_000_000L, callback, later, PERIOD),
                "the latch after the next callback belongs to that callback");
        check(!policy.present(arrived, arrived, 0L, latch, PERIOD), "no callback yet");

        for (int i = 0; i < 1000; ++i) policy.observeWork(1_000_000L);
        check(policy.workNs() < 1_100_000L, "falls to what the work takes: " + policy.workNs());
        check(policy.targetWaitNs() < 1_800_000L, "the target follows");
        policy.observeWork(2_500_000L);
        check(policy.workNs() == 2_500_000L, "one peak counts at once");
        policy.observeWork(0L);
        check(policy.workNs() == 2_500_000L, "no sample, no change");
        policy.presented();
        policy.missed();
        check(policy.presents() == 1L && policy.misses() == 1L, "counted");
    }
}
