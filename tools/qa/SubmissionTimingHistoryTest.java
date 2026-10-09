import com.thorium.lucent.video.SubmissionTimingHistory;

public final class SubmissionTimingHistoryTest {
    public static void main(String[] args) {
        SubmissionTimingHistory h=new SubmissionTimingHistory();
        h.record(1,5547,100,90,80,85,false);
        h.record(1,5548,110,100,91,96,true);
        h.record(1,5549,120,110,101,106,false);
        String gap=h.describe(1,5547,5549);
        if(!gap.contains("frame:5548,target:110,deadline:100,swapIn:91,swapOut:96,generated:1"))throw new AssertionError(gap);
        if(!h.describe(2,5548,5548).contains("history:unavailable"))throw new AssertionError("old epoch reused");
        h.record(1,5612,200,190,180,185,true);
        if(!h.describe(1,5548,5548).contains("history:unavailable"))throw new AssertionError("overwritten identity reused");
        if(!h.describe(1,1,1000000).endsWith("truncated"))throw new AssertionError("unbounded log");
        if(!h.describe(1,2,1).equals("invalid-range"))throw new AssertionError("bad range");
        h.record(3,1,20,10,8,7,true);
        if(!h.describe(3,1,1).contains("history:unavailable"))throw new AssertionError("invalid swap accepted");
    }
}
