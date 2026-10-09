package com.thorium.lucent.video;

/** Owner-thread, value-only observation ring. Never used to select/qualify output. */
public final class PresentationClockDiagnostics {
    public static final int CAPACITY = 8;
    private final long[][] rows = new long[CAPACITY][10];
    private int head, count;

    /** No allocation, normalization, deduplication, image lease or clock authority. */
    public void record(long presentId, long sessionEpoch, long presentationEpoch,
            long reportedActualNs, long targetNs, long tokenId, long expectedNs,
            long deadlineNs, long refreshNs, long observedNs) {
        int slot = (head + count) % CAPACITY;
        if (count == CAPACITY) head = (head + 1) % CAPACITY;
        else ++count;
        long[] row = rows[slot];
        row[0] = presentId; row[1] = sessionEpoch; row[2] = presentationEpoch;
        row[3] = reportedActualNs; row[4] = targetNs; row[5] = tokenId;
        row[6] = expectedNs; row[7] = deadlineNs; row[8] = refreshNs;
        row[9] = observedNs;
    }

    public int size() { return count; }

    /** Format only inside a separately capped diagnostic dump, oldest first. */
    public String describe(int index) {
        if (index < 0 || index >= count) throw new IndexOutOfBoundsException();
        long[] r = rows[(head + index) % CAPACITY];
        return "presentId=" + r[0] + " sessionEpoch=" + r[1] +
                " presentationEpoch=" + r[2] + " reportedActualNs=" + r[3] +
                " targetNs=" + r[4] + " tokenId=" + r[5] +
                " expectedNs=" + r[6] + " deadlineNs=" + r[7] +
                " refreshNs=" + r[8] + " observedNs=" + r[9];
    }
}
