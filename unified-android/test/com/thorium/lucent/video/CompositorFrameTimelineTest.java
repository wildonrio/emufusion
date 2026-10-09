package com.thorium.lucent.video;

public final class CompositorFrameTimelineTest {
    public static void main(String[] args) {
        selectsExactFutureTimeline();
        selectsClosestBoundedTimeline();
        rejectsExpiredWrongAmbiguousAndMalformedTimelines();
        rejectsTimelineWithoutSubmissionReserve();
        selectsEarliestLiveTimelineOnlyForBootstrap();
        selectsPredecessorBracketForExactTarget();
        selectsEarliestPredecessorBracketForBootstrap();
        rejectsIncompleteAmbiguousAndExpiredBrackets();
        selectsRefreshSafeExactTarget();
        selectsEarliestRefreshSafeExactTargetForBootstrap();
        probesClosestLiveTimelineWithoutAuthorizingIt();
        System.out.println("CompositorFrameTimelineTest passed");
    }

    private static void selectsRefreshSafeExactTarget() {
        CompositorFrameTimeline.Selection value =
                CompositorFrameTimeline.selectRefreshSafeTarget(
                        7_033_333_332L, 8_333_333L, 7_000_000_000L,
                        new long[]{401L, 402L, 403L},
                        new long[]{7_024_999_999L, 7_033_333_332L,
                                7_041_666_665L},
                        new long[]{7_014_000_000L, 7_022_000_000L,
                                7_030_000_000L}, 3);
        check(value != null && value.vsyncId() == 402L &&
                value.tokenExpectedPresentationTimeNs() == 7_033_333_332L &&
                value.expectedPresentationTimeNs() == 7_033_333_332L &&
                value.deadlineNs() == 7_022_000_000L,
                "refresh-safe selection must bind the exact visible target");
        check(CompositorFrameTimeline.selectRefreshSafeTarget(
                7_033_333_332L, 8_333_333L, 7_012_000_001L,
                new long[]{402L}, new long[]{7_033_333_332L},
                new long[]{7_022_000_000L}, 1) == null,
                "target lacking one refresh plus handoff reserve must reject");
    }

    private static void selectsEarliestRefreshSafeExactTargetForBootstrap() {
        CompositorFrameTimeline.Selection value =
                CompositorFrameTimeline.selectEarliestRefreshSafeTarget(
                        8_333_333L, 8_000_000_000L,
                        new long[]{501L, 502L, 503L},
                        new long[]{8_008_333_333L, 8_016_666_666L,
                                8_024_999_999L},
                        new long[]{7_999_000_000L, 8_006_000_000L,
                                8_014_000_000L}, 3);
        check(value != null && value.vsyncId() == 503L &&
                value.expectedPresentationTimeNs() == 8_024_999_999L &&
                value.tokenExpectedPresentationTimeNs() == 8_024_999_999L &&
                value.deadlineNs() == 8_014_000_000L,
                "bootstrap must skip exact targets lacking refresh reserve");
    }

    private static void selectsPredecessorBracketForExactTarget() {
        CompositorFrameTimeline.Selection value =
                CompositorFrameTimeline.selectPreceding(
                        1_025_000_000L, 8_333_334L, 1_000_000_000L,
                        new long[]{31L, 32L, 33L},
                        new long[]{1_016_666_666L, 1_025_000_000L,
                                1_033_333_333L},
                        new long[]{1_010_000_000L, 1_018_000_000L,
                                1_026_000_000L}, 3);
        check(value != null && value.vsyncId() == 31L &&
                value.tokenExpectedPresentationTimeNs() == 1_016_666_666L &&
                value.expectedPresentationTimeNs() == 1_025_000_000L &&
                value.deadlineNs() == 1_010_000_000L &&
                value.targetDeadlineNs() == 1_018_000_000L,
                "preceding token and exact visible target must stay distinct");
    }

    private static void selectsEarliestPredecessorBracketForBootstrap() {
        CompositorFrameTimeline.Selection value =
                CompositorFrameTimeline.selectEarliestPreceding(
                        8_333_333L, 4_000_000_000L,
                        new long[]{91L, 92L, 93L, 94L},
                        new long[]{4_008_333_333L, 4_016_666_666L,
                                4_024_999_999L, 4_033_333_332L},
                        new long[]{3_999_000_000L, 4_006_000_000L,
                                4_014_000_000L, 4_022_000_000L}, 4);
        check(value != null && value.vsyncId() == 93L &&
                value.tokenExpectedPresentationTimeNs() == 4_024_999_999L &&
                value.expectedPresentationTimeNs() == 4_033_333_332L &&
                value.targetDeadlineNs() == 4_022_000_000L,
                "bootstrap must skip a live pair lacking one refresh reserve");
        check(CompositorFrameTimeline.selectEarliestPreceding(
                8_333_333L, 4_000_000_000L,
                new long[]{91L, 92L, 93L},
                new long[]{4_008_333_333L, 4_016_666_666L,
                        4_024_999_999L},
                new long[]{3_999_000_000L, 4_006_000_000L,
                        4_008_000_000L}, 3) == null,
                "bootstrap fails closed when no predecessor retains a refresh");
    }

    private static void rejectsIncompleteAmbiguousAndExpiredBrackets() {
        long target = 6_025_000_000L;
        check(CompositorFrameTimeline.selectPreceding(
                target, 8_333_333L, 6_000_000_000L,
                new long[]{1L}, new long[]{target},
                new long[]{6_018_000_000L}, 1) == null,
                "a target without a predecessor must reject");
        check(CompositorFrameTimeline.selectPreceding(
                target, 8_333_333L, 6_000_000_000L,
                new long[]{1L, 2L, 3L},
                new long[]{6_016_566_667L, 6_016_766_667L, target},
                new long[]{6_010_000_000L, 6_010_000_000L,
                        6_018_000_000L}, 3) == null,
                "equidistant predecessor identities must reject");
        check(CompositorFrameTimeline.selectPreceding(
                target, 8_333_333L, 6_000_000_000L,
                new long[]{1L, 2L},
                new long[]{6_016_666_667L, target},
                new long[]{6_001_999_999L, 6_018_000_000L}, 2) == null,
                "predecessor below the reserve must reject");
        check(CompositorFrameTimeline.selectPreceding(
                target, 8_333_333L, 6_000_000_000L,
                new long[]{1L, 2L},
                new long[]{6_015_000_000L, target},
                new long[]{6_010_000_000L, 6_018_000_000L}, 2) == null,
                "non-adjacent bracket period must reject");
    }

    private static void selectsEarliestLiveTimelineOnlyForBootstrap() {
        CompositorFrameTimeline.Selection value =
                CompositorFrameTimeline.selectEarliestLive(
                        4_000_000_000L,
                        new long[]{91L, 92L, 93L},
                        new long[]{4_008_333_333L, 4_016_666_666L,
                                4_025_000_000L},
                        new long[]{3_999_000_000L, 4_006_000_000L,
                                4_014_000_000L}, 3);
        check(value != null && value.vsyncId() == 92L &&
                value.expectedPresentationTimeNs() == 4_016_666_666L &&
                value.deadlineNs() == 4_006_000_000L &&
                value.signedTargetErrorNs() == 0L,
                "bootstrap must choose the earliest still-meetable timeline");
        check(CompositorFrameTimeline.selectEarliestLive(
                4_000_000_000L,
                new long[]{101L, 102L},
                new long[]{4_016_666_666L, 4_016_666_666L},
                new long[]{4_006_000_000L, 4_006_000_000L}, 2) == null,
                "ambiguous earliest bootstrap identity must reject");
    }

    private static void selectsExactFutureTimeline() {
        CompositorFrameTimeline.Selection value =
                CompositorFrameTimeline.select(
                        1_025_000_000L, 1_000_000_000L,
                        new long[]{31L, 32L, 33L},
                        new long[]{1_016_666_666L, 1_025_000_000L,
                                1_033_333_333L},
                        new long[]{1_010_000_000L, 1_018_000_000L,
                                1_026_000_000L}, 3);
        check(value != null && value.vsyncId() == 32L &&
                value.expectedPresentationTimeNs() == 1_025_000_000L &&
                value.deadlineNs() == 1_018_000_000L &&
                value.signedTargetErrorNs() == 0L,
                "exact future compositor timeline must be selected");
    }

    private static void selectsClosestBoundedTimeline() {
        CompositorFrameTimeline.Selection value =
                CompositorFrameTimeline.select(
                        2_000_000_000L, 1_980_000_000L,
                        new long[]{41L, 42L},
                        new long[]{1_999_800_000L, 2_000_249_999L},
                        new long[]{1_990_000_000L, 1_991_000_000L}, 2);
        check(value != null && value.vsyncId() == 41L &&
                value.signedTargetErrorNs() == -200_000L,
                "closest bounded compositor timeline must win");
    }

    private static void rejectsExpiredWrongAmbiguousAndMalformedTimelines() {
        check(CompositorFrameTimeline.select(
                3_000_000_000L, 2_990_000_000L,
                new long[]{1L}, new long[]{3_000_000_000L},
                new long[]{2_989_999_999L}, 1) == null,
                "expired timeline must reject");
        check(CompositorFrameTimeline.select(
                3_000_000_000L, 2_990_000_000L,
                new long[]{1L}, new long[]{3_000_250_001L},
                new long[]{2_995_000_000L}, 1) == null,
                "out-of-tolerance timeline must reject");
        check(CompositorFrameTimeline.select(
                3_000_000_000L, 2_990_000_000L,
                new long[]{1L, 2L},
                new long[]{2_999_900_000L, 3_000_100_000L},
                new long[]{2_995_000_000L, 2_995_000_000L}, 2) == null,
                "equidistant timeline identity must reject");
        check(CompositorFrameTimeline.select(
                3_000_000_000L, 2_990_000_000L,
                new long[]{1L}, new long[]{3_000_000_000L},
                new long[]{2_995_000_000L}, 2) == null,
                "malformed timeline count must reject");
    }

    private static void rejectsTimelineWithoutSubmissionReserve() {
        long now = 5_000_000_000L;
        check(CompositorFrameTimeline.select(
                5_010_000_000L, now,
                new long[]{111L}, new long[]{5_010_000_000L},
                new long[]{5_001_999_999L}, 1) == null,
                "timeline below the physical submission reserve must reject");
        CompositorFrameTimeline.Selection exactReserve =
                CompositorFrameTimeline.select(
                        5_010_000_000L, now,
                        new long[]{112L}, new long[]{5_010_000_000L},
                        new long[]{5_002_000_000L}, 1);
        check(exactReserve != null && exactReserve.vsyncId() == 112L,
                "the exact physical submission reserve must remain selectable");
        check(CompositorFrameTimeline.selectEarliestLive(
                now, new long[]{113L}, new long[]{5_010_000_000L},
                new long[]{5_001_999_999L}, 1) == null,
                "bootstrap must enforce the same submission reserve");
    }

    private static void probesClosestLiveTimelineWithoutAuthorizingIt() {
        long target = 4_000_000_000L;
        CompositorFrameTimeline.Probe probe =
                CompositorFrameTimeline.probe(
                        target, 3_970_000_000L,
                        new long[]{71L, 72L, 73L},
                        new long[]{3_991_666_667L, 4_008_333_333L,
                                4_025_000_000L},
                        new long[]{3_969_999_999L, 3_999_000_000L,
                                4_016_000_000L}, 3);
        check(probe.suppliedCount() == 3 && probe.liveCount() == 2 &&
                probe.hasLiveTimeline() && probe.vsyncId() == 72L &&
                probe.expectedPresentationTimeNs() == 4_008_333_333L &&
                probe.deadlineNs() == 3_999_000_000L &&
                probe.signedTargetErrorNs() == 8_333_333L,
                "probe must expose the closest live out-of-tolerance slot");
        check(CompositorFrameTimeline.select(
                target, 3_970_000_000L,
                new long[]{71L, 72L, 73L},
                new long[]{3_991_666_667L, 4_008_333_333L,
                        4_025_000_000L},
                new long[]{3_969_999_999L, 3_999_000_000L,
                        4_016_000_000L}, 3) == null,
                "diagnostic probe must not relax selection tolerance");

        CompositorFrameTimeline.Probe noLive =
                CompositorFrameTimeline.probe(
                        target, 4_100_000_000L,
                        new long[]{81L}, new long[]{4_008_333_333L},
                        new long[]{3_999_000_000L}, 1);
        check(noLive.suppliedCount() == 1 && noLive.liveCount() == 0 &&
                !noLive.hasLiveTimeline() && noLive.vsyncId() == 0L,
                "probe must distinguish supplied but expired timelines");
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}
