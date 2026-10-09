package com.thorium.lucent.video;

public final class PresentationClockDiagnosticsTest {
    public static void main(String[] args) {
        PresentationClockDiagnostics ring = new PresentationClockDiagnostics();
        check(ring.size() == 0, "no invented bootstrap rows");
        for (long id = 1; id <= 10000; ++id) {
            ring.record(id, 1, id / 3, 1000000000L + id, 2000000000L + id,
                    3000000000L + id, 4000000000L + id, 5000000000L + id,
                    8333333L, 6000000000L + id);
            check(ring.size() == Math.min(id, PresentationClockDiagnostics.CAPACITY),
                    "retention must remain bounded across epochs");
        }
        check(ring.describe(0).equals("presentId=9993 sessionEpoch=1 presentationEpoch=3331" +
                " reportedActualNs=1000009993 targetNs=2000009993 tokenId=3000009993" +
                " expectedNs=4000009993 deadlineNs=5000009993 refreshNs=8333333" +
                " observedNs=6000009993"), "exact oldest surviving request join");
        check(ring.describe(7).startsWith("presentId=10000 "), "chronological newest row");
        String snapshot = ring.describe(0);
        ring.record(0, -1, -2, -3, Long.MAX_VALUE, 0, -4, -5, -6, -7);
        check(snapshot.startsWith("presentId=9993 "), "formatted snapshot cannot mutate");
        check(ring.describe(7).contains("reportedActualNs=-3 targetNs=" + Long.MAX_VALUE),
                "diagnostics cannot normalize or silently discard inconvenient values");
        try { ring.describe(-1); throw new AssertionError("negative index accepted"); }
        catch (IndexOutOfBoundsException expected) { }
        try { ring.describe(8); throw new AssertionError("past end accepted"); }
        catch (IndexOutOfBoundsException expected) { }
        check(ring.size() == 8, "reads/errors cannot consume or reset observations");
        System.out.println("PresentationClockDiagnosticsTest passed (observations only)");
    }
    private static void check(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }
}
