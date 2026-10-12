package com.thorium.emufusion.state;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/** Pure retention planner: newest states, then one older anchor per UTC hour. */
public final class RetentionPolicy {
    public static final RetentionPolicy DEFAULT = new RetentionPolicy(12, 72, 512L * 1024L * 1024L);
    private static final long HOUR_MILLIS = 60L * 60L * 1000L;
    public final int newestToKeep;
    public final int maximumCount;
    public final long maximumBytes;

    public RetentionPolicy(int newestToKeep, int maximumCount, long maximumBytes) {
        if (newestToKeep < 1 || maximumCount < newestToKeep || maximumBytes < 1)
            throw new IllegalArgumentException("Invalid retention limits");
        this.newestToKeep = newestToKeep;
        this.maximumCount = maximumCount;
        this.maximumBytes = maximumBytes;
    }

    public Set<String> selectForDeletion(List<Candidate> supplied, String protectedSnapshotId) {
        Set<String> protectedIds = protectedSnapshotId == null
                ? Collections.<String>emptySet()
                : Collections.singleton(protectedSnapshotId);
        return selectForDeletion(supplied, protectedIds);
    }

    /** As above, but every supplied id is mandatory-protected from deletion. */
    public Set<String> selectForDeletion(List<Candidate> supplied,
            Set<String> protectedSnapshotIds) {
        List<Candidate> candidates = new ArrayList<>(supplied);
        Collections.sort(candidates, new Comparator<Candidate>() {
            @Override public int compare(Candidate a, Candidate b) {
                int byTime = Long.compare(b.createdAtMillis, a.createdAtMillis);
                return byTime != 0 ? byTime : b.snapshotId.compareTo(a.snapshotId);
            }
        });

        LinkedHashSet<String> keep = new LinkedHashSet<>();
        if (protectedSnapshotIds != null) for (String id : protectedSnapshotIds)
            if (id != null) keep.add(id);
        LinkedHashSet<String> mandatory = new LinkedHashSet<>(keep);
        int newestHistory = 0;
        for (Candidate candidate : candidates) {
            if (!candidate.history) continue;
            if (newestHistory++ < newestToKeep) {
                keep.add(candidate.snapshotId);
                mandatory.add(candidate.snapshotId);
            }
        }

        Set<Long> hours = new HashSet<>();
        for (Candidate candidate : candidates) {
            if (!candidate.history || mandatory.contains(candidate.snapshotId)) continue;
            long hour = candidate.createdAtMillis / HOUR_MILLIS;
            if (hours.add(hour)) keep.add(candidate.snapshotId);
        }

        long keptBytes = 0;
        int keptCount = 0;
        for (Candidate candidate : candidates) if (keep.contains(candidate.snapshotId)) {
            keptBytes = saturatedAdd(keptBytes, Math.max(0, candidate.bytes));
            keptCount++;
        }
        // Remove the oldest non-protected anchors until both ceilings are met.
        for (int i = candidates.size() - 1;
                i >= 0 && (keptCount > maximumCount || keptBytes > maximumBytes); i--) {
            Candidate candidate = candidates.get(i);
            if (mandatory.contains(candidate.snapshotId)) continue;
            if (keep.remove(candidate.snapshotId)) {
                keptCount--;
                keptBytes -= Math.max(0, candidate.bytes);
            }
        }

        Set<String> delete = new LinkedHashSet<>();
        for (Candidate candidate : candidates)
            if (!keep.contains(candidate.snapshotId)) delete.add(candidate.snapshotId);
        return delete;
    }

    private static long saturatedAdd(long left, long right) {
        return right > Long.MAX_VALUE - left ? Long.MAX_VALUE : left + right;
    }

    public static final class Candidate {
        public final String snapshotId;
        public final long createdAtMillis;
        public final long bytes;
        public final boolean history;

        public Candidate(String snapshotId, long createdAtMillis, long bytes) {
            this(snapshotId, createdAtMillis, bytes, true);
        }

        public Candidate(String snapshotId, long createdAtMillis, long bytes, boolean history) {
            this.snapshotId = snapshotId;
            this.createdAtMillis = createdAtMillis;
            this.bytes = bytes;
            this.history = history;
        }
    }
}
