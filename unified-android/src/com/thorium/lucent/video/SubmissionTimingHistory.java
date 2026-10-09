package com.thorium.lucent.video;

/** Render-thread-owned bounded diagnostic. Never changes admission or timing. */
public final class SubmissionTimingHistory {
    private static final int CAPACITY = 64;
    private final long[][] rows = new long[CAPACITY][8];

    public void record(long epoch, long frameId, long targetNs, long deadlineNs,
                       long swapEnteredNs, long swapReturnedNs, boolean generated) {
        if (epoch <= 0 || frameId <= 0 || swapEnteredNs <= 0 || swapReturnedNs < swapEnteredNs)
            return;
        long[] row = rows[(int)(frameId % CAPACITY)];
        row[0]=epoch; row[1]=frameId; row[2]=targetNs; row[3]=deadlineNs;
        row[4]=swapEnteredNs; row[5]=swapReturnedNs; row[6]=generated?1:0; row[7]=1;
    }

    /** Allocation occurs only for a bounded anomaly log, never each frame. */
    public String describe(long epoch, long firstFrameId, long lastFrameId) {
        if (epoch <= 0 || firstFrameId <= 0 || lastFrameId < firstFrameId) return "invalid-range";
        StringBuilder text = new StringBuilder();
        int count = (int)Math.min(6L, lastFrameId-firstFrameId+1L);
        for (int i=0;i<count;i++) {
            long id=firstFrameId+i; long[] r=rows[(int)(id%CAPACITY)];
            if(i>0)text.append(';');
            text.append("frame:").append(id);
            if(r[7]==0 || r[0]!=epoch || r[1]!=id) {text.append(",history:unavailable");continue;}
            text.append(",target:").append(r[2]).append(",deadline:").append(r[3])
                .append(",swapIn:").append(r[4]).append(",swapOut:").append(r[5])
                .append(",generated:").append(r[6]);
        }
        if(lastFrameId-firstFrameId>=6)text.append(";truncated");
        return text.toString();
    }
}
