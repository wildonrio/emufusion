package com.thorium.preview.game;

import android.util.Log;
import com.thorium.lucent.video.SubmissionTimingHistory;

/** Diagnostic adapter for the audited installed renderer; no pacing decisions. */
public final class SubmissionTimingOverlay {
    private static final ThreadLocal<State> STATE = new ThreadLocal<State>();
    private static final class State {
        Object owner;
        long frameId,entered,returned;
        boolean generated;
        final SubmissionTimingHistory history=new SubmissionTimingHistory();
    }
    public static void before(Object owner,long frameId,boolean generated) {
        if(frameId<=0)return;
        State s=STATE.get();
        if(s==null||s.owner!=owner){s=new State();s.owner=owner;STATE.set(s);}
        s.frameId=frameId;s.generated=generated;s.returned=0;s.entered=System.nanoTime();
    }
    public static void after(Object owner) {
        long now=System.nanoTime();State s=STATE.get();
        if(s!=null&&s.owner==owner)s.returned=now;
    }
    public static void committed(long epoch,long frameId,long pair,long warp,long target,long deadline) {
        State s=STATE.get();
        if(s!=null&&s.frameId==frameId)
            s.history.record(epoch,frameId,target,deadline,s.entered,s.returned,s.generated);
    }
    public static void gap(Object owner,Object result) {
        State s=STATE.get();if(s==null||s.owner!=owner)return;
        try {
            java.lang.reflect.Field previous=owner.getClass().getDeclaredField("previousDenseJoinFrameId");
            previous.setAccessible(true);
            long first=previous.getLong(owner);
            long last=result.getClass().getField("frameId").getLong(result);
            long epoch=result.getClass().getField("presentationEpoch").getLong(result);
            Log.w("EmuFusionFrameGen","Built-in submission history "+s.history.describe(epoch,first,last));
        } catch(ReflectiveOperationException failure) {
            Log.w("EmuFusionFrameGen","Submission history unavailable: "+failure.getClass().getSimpleName());
        }
    }
}
