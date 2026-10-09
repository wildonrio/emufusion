package com.thorium.lucent.state;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.zip.CRC32;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

/**
 * Crash-resilient immutable emulator state storage.
 *
 * A snapshot directory is fully written and synced before it becomes visible.
 * Quick Resume is only a tiny atomically replaced reference to one immutable
 * snapshot, so a process death cannot expose half of a new state.
 */
public final class StateVault {
    private static final String SNAPSHOTS = "snapshots";
    private static final String MANIFEST = "manifest.properties";
    private static final String STATE = "state.bin.gz";
    private static final String PREVIEW = "preview.webp";
    private static final String QUICK_REF = "quick-resume.ref";
    private static final long MAX_UNCOMPRESSED_STATE = 512L * 1024L * 1024L;

    private final File root;
    private final Clock clock;
    private final RetentionPolicy retention;
    /**
     * Mutual exclusion is keyed on the canonical vault root, not the instance.
     * Multiple sessions construct separate StateVault instances over one root
     * (a retiring game plus its relaunch), and a per-instance lock would let
     * the retiring session's save interleave with the new session's prune
     * over the same game directory.
     */
    private final Object monitor;

    public StateVault(File root) {
        this(root, Clock.SYSTEM, RetentionPolicy.DEFAULT);
    }

    public StateVault(File root, Clock clock, RetentionPolicy retention) {
        if (root == null || clock == null || retention == null)
            throw new IllegalArgumentException("StateVault dependencies cannot be null");
        this.root = root;
        this.clock = clock;
        this.retention = retention;
        this.monitor = monitorFor(root);
    }

    /**
     * Production callers share one instance per root through this factory;
     * direct construction remains for tests. Even directly constructed
     * instances over one root serialize their operations through the shared
     * root monitor.
     */
    public static StateVault shared(File root) {
        if (root == null)
            throw new IllegalArgumentException("StateVault dependencies cannot be null");
        String key = canonicalKey(root);
        StateVault current = SHARED.get(key);
        if (current != null) return current;
        StateVault created = new StateVault(root);
        StateVault existing = SHARED.putIfAbsent(key, created);
        return existing != null ? existing : created;
    }

    private static final java.util.concurrent.ConcurrentHashMap<String, StateVault> SHARED =
            new java.util.concurrent.ConcurrentHashMap<String, StateVault>();

    private static final java.util.concurrent.ConcurrentHashMap<String, Object> MONITORS =
            new java.util.concurrent.ConcurrentHashMap<String, Object>();

    private static String canonicalKey(File root) {
        try { return root.getCanonicalPath(); }
        catch (IOException unresolvable) { return root.getAbsolutePath(); }
    }

    private static Object monitorFor(File root) {
        String key = canonicalKey(root);
        Object current = MONITORS.get(key);
        if (current != null) return current;
        Object created = new Object();
        Object existing = MONITORS.putIfAbsent(key, created);
        return existing != null ? existing : created;
    }

    /** Visible for tests: instances over one canonical root share this lock. */
    Object rootMonitor() {
        return monitor;
    }

    public StateSnapshot saveQuickResume(StateIdentity identity, byte[] state,
            byte[] webpScreenshot, long activePlayMillis) throws IOException {
        synchronized (monitor) {
            StateSnapshot snapshot = save(identity, SnapshotKind.QUICK_RESUME, state,
                    webpScreenshot, activePlayMillis);
            File game = gameDirectory(identity);
            // The outgoing Quick Resume stays protected for one more prune
            // generation; deleting it in the same pass that publishes its
            // replacement would leave zero fallbacks if the new state proves
            // unreadable in ways the publish verification cannot see.
            String previousQuickId = readQuickId(game);
            final byte[] reference = (snapshot.metadata.snapshotId + "\n")
                    .getBytes(StandardCharsets.UTF_8);
            File temporary = new File(game, QUICK_REF + ".pending-" + UUID.randomUUID());
            AtomicFiles.writeSynced(temporary, new AtomicFiles.OutputWriter() {
                @Override public void write(OutputStream output) throws IOException {
                    output.write(reference);
                }
            });
            AtomicFiles.replace(temporary, new File(game, QUICK_REF));
            prune(identity, previousQuickId);
            return snapshot;
        }
    }

    public StateSnapshot saveAutomatic(StateIdentity identity, byte[] state,
            byte[] webpScreenshot, long activePlayMillis) throws IOException {
        synchronized (monitor) {
            StateSnapshot result = save(identity, SnapshotKind.AUTOMATIC, state,
                    webpScreenshot, activePlayMillis);
            prune(identity, null);
            return result;
        }
    }

    public StateSnapshot saveRecovery(StateIdentity identity, byte[] state,
            byte[] webpScreenshot, long activePlayMillis) throws IOException {
        synchronized (monitor) {
            StateSnapshot result = save(identity, SnapshotKind.RECOVERY, state,
                    webpScreenshot, activePlayMillis);
            prune(identity, null);
            return result;
        }
    }

    public StateSnapshot saveBeforeEngineUpdate(StateIdentity identity, byte[] state,
            byte[] webpScreenshot, long activePlayMillis) throws IOException {
        synchronized (monitor) {
            StateSnapshot result = save(identity, SnapshotKind.PRE_UPDATE, state,
                    webpScreenshot, activePlayMillis);
            prune(identity, null);
            return result;
        }
    }

    /**
     * Drops the Quick Resume reference (and its recovery backup) so the next
     * launch cold-boots. Used when a restored state proves defective at
     * runtime — a resumed melonDS session whose gameplay screen stayed black
     * and ignored input relaunched into the same zombie forever
     * (2026-08-19, Thor). The snapshot files themselves stay for manual
     * recovery; only the automatic-resume pointer is removed.
     */
    public void discardQuickResume(StateIdentity identity) {
        synchronized (monitor) {
            File game = gameDirectory(identity);
            File reference = new File(game, QUICK_REF);
            File backup = new File(game, QUICK_REF + ".previous");
            if (reference.isFile()) reference.delete();
            if (backup.isFile()) backup.delete();
        }
    }

    public StateLoadResult loadQuickResume(StateIdentity expected) {
        synchronized (monitor) {
            File game = gameDirectory(expected);
            File reference = new File(game, QUICK_REF);
            try { AtomicFiles.recoverPrevious(reference); }
            catch (IOException failure) {
                return StateLoadResult.failure(StateLoadResult.Status.IO_ERROR, null,
                        failure.getMessage());
            }
            if (!reference.isFile())
                return StateLoadResult.failure(StateLoadResult.Status.NOT_FOUND, null,
                        "No Quick Resume");
            try {
                String snapshotId = readUtf8(reference).trim();
                if (!safeSnapshotId(snapshotId))
                    return StateLoadResult.failure(StateLoadResult.Status.CORRUPT, null,
                            "Invalid Quick Resume reference");
                return loadSnapshot(expected, new File(new File(game, SNAPSHOTS), snapshotId));
            } catch (IOException failure) {
                return StateLoadResult.failure(StateLoadResult.Status.IO_ERROR, null,
                        failure.getMessage());
            }
        }
    }

    public StateLoadResult loadSnapshot(StateIdentity expected, StateSnapshot snapshot) {
        synchronized (monitor) {
            return snapshot == null
                    ? StateLoadResult.failure(StateLoadResult.Status.NOT_FOUND, null,
                            "Snapshot missing")
                    : loadSnapshot(expected, snapshot.directory);
        }
    }

    public List<StateSnapshot> list(StateIdentity identity) {
        synchronized (monitor) {
            List<StateSnapshot> result = new ArrayList<>();
            File snapshots = new File(gameDirectory(identity), SNAPSHOTS);
            File[] directories = snapshots.listFiles();
            if (directories != null) for (File directory : directories) {
                if (!directory.isDirectory() || directory.getName().startsWith(".pending-"))
                    continue;
                try {
                    SnapshotMetadata metadata = readMetadata(directory);
                    if (metadata.identity.matches(identity))
                        result.add(new StateSnapshot(metadata, directory));
                } catch (IOException ignored) {
                    // Corrupt entries are retained for recovery and omitted from the UI.
                }
            }
            Collections.sort(result, new Comparator<StateSnapshot>() {
                @Override public int compare(StateSnapshot a, StateSnapshot b) {
                    return Long.compare(b.metadata.createdAtMillis, a.metadata.createdAtMillis);
                }
            });
            return result;
        }
    }

    private StateSnapshot save(final StateIdentity identity, final SnapshotKind kind,
            final byte[] state, final byte[] screenshot, final long activePlayMillis)
            throws IOException {
        if (identity == null || kind == null || state == null || state.length == 0)
            throw new IllegalArgumentException("Identity, kind and non-empty state are required");
        if (state.length > MAX_UNCOMPRESSED_STATE)
            throw new IOException("State exceeds the 512 MiB safety limit");
        if (activePlayMillis < 0) throw new IllegalArgumentException("activePlayMillis is negative");

        File game = gameDirectory(identity);
        File snapshots = new File(game, SNAPSHOTS);
        ensureDirectory(snapshots);
        final long now = clock.wallTimeMillis();
        final String id = now + "-" + UUID.randomUUID().toString();
        final String sha256 = Digests.sha256(state);
        final SnapshotMetadata metadata = new SnapshotMetadata(id, kind, identity, now,
                activePlayMillis, state.length, sha256, Digests.crc32(state),
                screenshot != null && screenshot.length > 0);
        File pending = new File(snapshots, ".pending-" + id);
        File published = new File(snapshots, id);
        if (!pending.mkdir()) throw new IOException("Cannot create " + pending);
        boolean complete = false;
        try {
            AtomicFiles.writeSynced(new File(pending, STATE), new AtomicFiles.OutputWriter() {
                @Override public void write(OutputStream output) throws IOException {
                    GZIPOutputStream gzip = new GZIPOutputStream(output);
                    gzip.write(state);
                    gzip.finish();
                }
            });
            if (metadata.hasScreenshot) {
                AtomicFiles.writeSynced(new File(pending, PREVIEW), new AtomicFiles.OutputWriter() {
                    @Override public void write(OutputStream output) throws IOException {
                        output.write(screenshot);
                    }
                });
            }
            AtomicFiles.writeSynced(new File(pending, MANIFEST), new AtomicFiles.OutputWriter() {
                @Override public void write(OutputStream output) throws IOException {
                    metadata.write(output);
                }
            });
            // Read it back before publication; a visible directory is always complete.
            SnapshotMetadata verified = readMetadata(pending);
            if (!id.equals(verified.snapshotId)) throw new IOException("Manifest verification failed");
            AtomicFiles.publishDirectory(pending, published);
            complete = true;
        } finally {
            if (!complete) AtomicFiles.deleteTree(pending);
        }
        // End-to-end verification of the durable payload before the caller may
        // reference this snapshot (Quick Resume swaps its ref only after this
        // returns). The manifest digests cover the uncompressed state, so the
        // published state.bin.gz is decompressed and re-hashed exactly as a
        // future load would. A snapshot that cannot be loaded must never
        // replace one that can.
        try {
            verifyPublishedState(published);
        } catch (IOException corrupt) {
            AtomicFiles.deleteTree(published);
            AtomicFiles.syncDirectory(snapshots);
            throw new IOException("Published snapshot failed verification and was discarded: "
                    + corrupt.getMessage(), corrupt);
        }
        return new StateSnapshot(metadata, published);
    }

    /**
     * Proves a published snapshot's state payload round-trips: decompresses
     * state.bin.gz from disk and checks it against the manifest digests, the
     * same validation {@link #loadSnapshot(StateIdentity, File)} applies.
     */
    static void verifyPublishedState(File directory) throws IOException {
        SnapshotMetadata metadata = readMetadata(directory);
        if (metadata.uncompressedBytes <= 0 || metadata.uncompressedBytes > MAX_UNCOMPRESSED_STATE)
            throw new IOException("Invalid state size");
        // The caller still owns the original serialized state. A second full
        // expansion here made Wii checkpoints exceed Android's Java heap.
        // Verify every durable byte (including the gzip trailer) without
        // retaining another state-sized array.
        MessageDigest sha256 = Digests.newDigest();
        CRC32 crc32 = new CRC32();
        long total = 0;
        try (InputStream file = new FileInputStream(new File(directory, STATE));
                InputStream input = new GZIPInputStream(file, 32 * 1024)) {
            byte[] buffer = new byte[32 * 1024];
            int count;
            while ((count = input.read(buffer)) != -1) {
                if (count == 0) continue;
                total += count;
                if (total > metadata.uncompressedBytes)
                    throw new IOException("Expanded state exceeds manifest size");
                sha256.update(buffer, 0, count);
                crc32.update(buffer, 0, count);
            }
        }
        if (total != metadata.uncompressedBytes ||
                !metadata.stateSha256.equals(Digests.hex(sha256.digest())) ||
                metadata.stateCrc32 != crc32.getValue())
            throw new IOException("State checksum mismatch");
    }

    private StateLoadResult loadSnapshot(StateIdentity expected, File directory) {
        if (directory == null || !directory.isDirectory())
            return StateLoadResult.failure(StateLoadResult.Status.NOT_FOUND, null, "Snapshot missing");
        StateSnapshot snapshot = null;
        try {
            SnapshotMetadata metadata = readMetadata(directory);
            snapshot = new StateSnapshot(metadata, directory);
            if (!expected.matches(metadata.identity))
                return StateLoadResult.failure(StateLoadResult.Status.IDENTITY_MISMATCH, snapshot,
                        "ROM, engine, state format, or firmware changed");
            if (metadata.uncompressedBytes <= 0 || metadata.uncompressedBytes > MAX_UNCOMPRESSED_STATE)
                return StateLoadResult.failure(StateLoadResult.Status.CORRUPT, snapshot,
                        "Invalid state size");
            byte[] state = gunzip(new File(directory, STATE), metadata.uncompressedBytes);
            if (state.length != metadata.uncompressedBytes ||
                    !metadata.stateSha256.equals(Digests.sha256(state)) ||
                    metadata.stateCrc32 != Digests.crc32(state))
                return StateLoadResult.failure(StateLoadResult.Status.CORRUPT, snapshot,
                        "State checksum mismatch");
            return StateLoadResult.ok(snapshot, state);
        } catch (IOException failure) {
            return StateLoadResult.failure(StateLoadResult.Status.CORRUPT, snapshot,
                    failure.getMessage());
        }
    }

    private void prune(StateIdentity identity, String previousQuickId) {
        List<StateSnapshot> snapshots = list(identity);
        File game = gameDirectory(identity);
        String protectedId = readQuickId(game);
        boolean referencePresent = new File(game, QUICK_REF).exists() ||
                new File(game, QUICK_REF + ".previous").exists();
        if (referencePresent && (protectedId == null || !safeSnapshotId(protectedId))) {
            // Fail closed: with no readable reference the retention policy
            // cannot tell which Quick Resume snapshot is live and would
            // select every one of them for deletion. An unreadable reference
            // must protect the newest state, never expose it. Retry on the
            // next save.
            System.err.println("StateVault: PRUNE_SKIPPED_UNREADABLE_QUICK_REF "
                    + "quick-resume.ref exists but is unreadable or invalid for "
                    + game.getName() + "; skipping prune to protect the live Quick Resume");
            return;
        }
        Set<String> protectedIds = new LinkedHashSet<>();
        if (protectedId != null && safeSnapshotId(protectedId)) protectedIds.add(protectedId);
        // The prune that follows a successful Quick Resume publish also keeps
        // the immediately-preceding Quick Resume for one generation.
        if (previousQuickId != null && safeSnapshotId(previousQuickId))
            protectedIds.add(previousQuickId);
        List<RetentionPolicy.Candidate> candidates = new ArrayList<>();
        for (StateSnapshot snapshot : snapshots)
            candidates.add(new RetentionPolicy.Candidate(snapshot.metadata.snapshotId,
                    snapshot.metadata.createdAtMillis, AtomicFiles.size(snapshot.directory),
                    snapshot.metadata.kind != SnapshotKind.QUICK_RESUME));
        Set<String> deletions = retention.selectForDeletion(candidates, protectedIds);
        for (StateSnapshot snapshot : snapshots)
            if (deletions.contains(snapshot.metadata.snapshotId))
                AtomicFiles.deleteTree(snapshot.directory);
        AtomicFiles.syncDirectory(new File(gameDirectory(identity), SNAPSHOTS));
    }

    private File gameDirectory(StateIdentity identity) {
        return new File(root, identity.storageKey());
    }

    private static SnapshotMetadata readMetadata(File directory) throws IOException {
        InputStream input = new FileInputStream(new File(directory, MANIFEST));
        try { return SnapshotMetadata.read(input); }
        finally { input.close(); }
    }

    private static byte[] gunzip(File file, long expectedBytes) throws IOException {
        if (expectedBytes <= 0 || expectedBytes > MAX_UNCOMPRESSED_STATE)
            throw new IOException("Invalid state size");
        try (InputStream source = new FileInputStream(file);
                InputStream input = new GZIPInputStream(source, 32 * 1024)) {
            // Loading needs one contiguous array for the native unserializer,
            // but no geometric growth or toByteArray copy of that array.
            byte[] state = new byte[(int) expectedBytes];
            int total = 0;
            while (total < state.length) {
                int count = input.read(state, total, Math.min(32 * 1024, state.length - total));
                if (count == -1) throw new IOException("Expanded state is shorter than manifest size");
                if (count == 0) continue;
                total += count;
            }
            // Read through EOF so oversized data and a damaged/truncated gzip
            // trailer cannot pass just because the expected prefix matched.
            if (input.read() != -1)
                throw new IOException("Expanded state exceeds manifest size");
            return state;
        }
    }

    private static String readQuickId(File game) {
        try {
            File reference = new File(game, QUICK_REF);
            AtomicFiles.recoverPrevious(reference);
            return readUtf8(reference).trim();
        }
        catch (IOException ignored) { return null; }
    }

    private static String readUtf8(File file) throws IOException {
        InputStream input = new FileInputStream(file);
        try {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[256];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                if (count > 0) output.write(buffer, 0, count);
                if (output.size() > 1024) throw new IOException("Reference is too large");
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        } finally { input.close(); }
    }

    private static boolean safeSnapshotId(String id) {
        return id != null && id.matches("[0-9]+-[0-9a-fA-F-]{36}");
    }

    private static void ensureDirectory(File directory) throws IOException {
        if (!directory.isDirectory() && !directory.mkdirs())
            throw new IOException("Cannot create " + directory);
    }
}
