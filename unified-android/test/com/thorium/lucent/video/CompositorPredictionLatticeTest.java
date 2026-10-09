package com.thorium.lucent.video;

public final class CompositorPredictionLatticeTest {
    public static void main(String[] args) {
        recorded5573Failure();
        sustainedDivisorPhase();
        rejectDiscontinuities();
        System.out.println("CompositorPredictionLatticeTest passed (prediction only; no physical qualification)");
    }

    private static void recorded5573Failure() {
        // Exact first miss from 5573, 2026-09-05 03:46:10.441, PID 8960.
        long callback = 326120061590666L;
        long now = 326120062194654L;
        long previous = 326120077504814L;
        long physicalPeriod = 8334986L;
        long[] ids = {372645197,372645198,372645199,372645200,
                372645201,372645202,372645203};
        long[] expected = {326120077257332L,326120085590665L,
                326120093923998L,326120102257331L,326120110590664L,
                326120118923997L,326120127257330L};
        long[] deadlines = {326120066923999L,326120075257332L,
                326120083590665L,326120091923998L,326120100257331L,
                326120108590664L,326120116923997L};
        PhysicalPresentationDeadline old = PhysicalPresentationDeadline.nextAlignedOutput(
                callback,326118777246998L,physicalPeriod,1,now,previous);
        eq(326120094174786L,old.contentPresentationTimeNs(),"exact old target replay");
        check(CompositorFrameTimeline.selectRefreshSafeTarget(
                old.contentPresentationTimeNs(),physicalPeriod,now,
                ids,expected,deadlines,7) == null,"old request still rejected");
        eq(-250788L,CompositorFrameTimeline.probe(old.contentPresentationTimeNs(),
                now,ids,expected,deadlines,7).signedTargetErrorNs(),"exact recorded error");

        CompositorPredictionLattice clock = new CompositorPredictionLattice();
        check(clock.observe(callback,expected,7),"accept recorded live grid");
        PhysicalPresentationDeadline plan = PhysicalPresentationDeadline.nextAlignedOutput(
                callback,clock.anchorNs(1),clock.periodNs(),1,now,previous);
        eq(326120093923998L,plan.contentPresentationTimeNs(),"new current-grid target");
        CompositorFrameTimeline.Selection selected =
                CompositorFrameTimeline.selectRefreshSafeTarget(
                        plan.contentPresentationTimeNs(),physicalPeriod,now,
                        ids,expected,deadlines,7);
        check(selected != null,"same strict selector accepts new target");
        eq(372645199L,selected.vsyncId(),"exact live token");
        eq(0L,selected.signedTargetErrorNs(),"no tolerance widening");
        check(plan.contentPresentationTimeNs() > previous + physicalPeriod/2,
                "not a duplicate of the previous immutable request");
    }

    private static void sustainedDivisorPhase() {
        // Android revises prediction phase 1.5 us per callback. A stale origin
        // accumulates milliseconds of error; this clock retains scan parity.
        for (int divisor : new int[]{1,2,3,4,5,6}) {
            CompositorPredictionLattice clock = new CompositorPredictionLattice();
            long period = 8333333L;
            long last = 0L;
            long lastOrdinal = -1L;
            for (int callbackIndex = 0; callbackIndex < 10000; ++callbackIndex) {
                long callback = 1000000000L + callbackIndex*(period+1500L);
                long head = callback+2*period;
                long[] expected = grid(head,period);
                check(clock.observe(callback,expected,7),"continuous revised grid");
                eq(callbackIndex,clock.headOrdinal(),"integer ordinal survives drift");
                PhysicalPresentationDeadline plan = PhysicalPresentationDeadline.nextAlignedOutput(
                        callback,clock.anchorNs(divisor),clock.periodNs(),divisor,
                        callback+500000L,last);
                check(plan.valid(),"future plan");
                long offset = plan.contentPresentationTimeNs()-head;
                eq(0L,offset%period,"on current prediction grid");
                long ordinal = callbackIndex+offset/period;
                eq(0L,ordinal%divisor,"stable divisor phase");
                check(ordinal > lastOrdinal,"never reuses a retimed scan identity");
                check(plan.contentPresentationTimeNs() > last,"monotonic request");
                last = plan.contentPresentationTimeNs();
                lastOrdinal = ordinal;
            }
        }
    }

    private static void rejectDiscontinuities() {
        CompositorPredictionLattice clock = new CompositorPredictionLattice();
        long period = 8333333L;
        long callback = 1000000000L;
        long head = callback+2*period;
        check(clock.observe(callback,grid(head,period),7),"initial");
        check(clock.observe(callback,grid(head,period),7),"same snapshot is idempotent");
        check(!clock.observe(callback-1,grid(head+period,period),7),"reversed callback");
        check(!clock.observe(callback,grid(head+period,period),7),"same callback changed identity");
        check(!clock.observe(callback+period,grid(head+period+250001L,period),7),"ambiguous phase");
        check(!clock.observe(callback+period,grid(head+period,16666667L),7),"mode change");
        check(!clock.observe(callback+300000000L,grid(head+300000000L,period),7),"long gap");
        check(!clock.observe(callback+period,new long[]{head+period,head},2),"reversed grid");
        check(!clock.observe(callback,null,7),"null");
        check(!clock.observe(callback,grid(head,period),8),"bad count");
        eq(head,clock.anchorNs(1),"rejections never mutate phase");
        eq(0L,clock.anchorNs(0),"invalid divisor");
        clock.reset();
        check(!clock.available(),"explicit reset");
        check(clock.observe(callback+300000000L,grid(head+300000000L,period),7),
                "fresh epoch after an explicit discontinuity");
    }

    private static long[] grid(long first,long period) {
        long[] values = new long[7];
        for(int i=0;i<values.length;++i) values[i]=first+i*period;
        return values;
    }
    private static void check(boolean value,String message) {
        if(!value) throw new AssertionError(message);
    }
    private static void eq(long expected,long actual,String message) {
        if(expected!=actual) throw new AssertionError(message+": expected="+expected+" actual="+actual);
    }
}
