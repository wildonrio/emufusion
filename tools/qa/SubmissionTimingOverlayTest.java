package com.thorium.preview.game;

public final class SubmissionTimingOverlayTest {
    public static final class Owner {private long previousDenseJoinFrameId=5547;}
    public static final class Result {public long frameId=5549,presentationEpoch=1;}
    public static void main(String[] args) {
        Owner owner=new Owner();Result result=new Result();
        for(long id=5547;id<=5549;id++) {
            SubmissionTimingOverlay.before(owner,id,id==5548);
            SubmissionTimingOverlay.after(owner);
            SubmissionTimingOverlay.committed(1,id,0,0,id*100,id*100-20);
        }
        SubmissionTimingOverlay.gap(owner,result);
        String text=android.util.Log.last;
        if(!text.contains("frame:5548,target:554800,deadline:554780,swapIn:"))throw new AssertionError(text);
        if(!text.contains(",generated:1"))throw new AssertionError(text);
        SubmissionTimingOverlay.before(owner,5550,true);
        SubmissionTimingOverlay.after(owner);
        owner.previousDenseJoinFrameId=5550;result.frameId=5550;
        SubmissionTimingOverlay.gap(owner,result);
        if(!android.util.Log.last.contains("frame:5550,history:unavailable"))throw new AssertionError("uncommitted credited");
    }
}
