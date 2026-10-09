package com.thorium.lucent.state;

import com.thorium.lucent.TestSupport;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

public final class StateVaultTest {
    public static void main(String[] ignored) throws Exception {
        schedulerCountsOnlySuppliedActiveTime();
        schedulerUsesTenMinuteDefaultAndRejectsOverflow();
        retentionKeepsNewestAndHourlyAnchors();
        retentionByteAccountingCannotOverflow();
        vaultRoundTripAndValidation();
        largeStatePolicySkipsRecoveryCopyAndRefusesUnsafeExit();
        largeQuickResumeCommitIsAtomicAndSurvivesProcessDeath();
        quickResumeReferenceRecoversAfterInterruptedReplace();
        vaultPrunesWithoutDeletingQuickResume();
        unreadableQuickReferenceProtectsSnapshotsFromPrune();
        sharedVaultReturnsOneInstancePerRoot();
        separateInstancesOverOneRootShareOneMonitor();
        publishVerificationRejectsChecksumMismatch();
        previousQuickResumeSurvivesForOneGeneration();
        quickResumeDoesNotDisplaceAutomaticHistory();
        identitiesUseSeparateStorage();
        exactCoreArtifactIdentityIsolatesState();
        qualificationSessionIdentityRestoresOnlyWithinSameRun();
        durableBlobRecoversAndCapsReads();
        workerCopiesStateBeforeBackgroundCompression();
        workerDrainsQueuedSnapshotsDuringConcurrentClose();
        System.out.println("StateVaultTest passed");
    }

    private static void largeStatePolicySkipsRecoveryCopyAndRefusesUnsafeExit() {
        TestSupport.truth(!QuickResumePolicy.allowsRuntimeRestore("armsx2"),
                "ARMSX2 silent black-frame restores are quarantined");
        TestSupport.truth(QuickResumePolicy.allowsRuntimeRestore("dolphin"),
                "Dolphin's EGL reset is now handled by restoreQuickResume's"
                + " recreateSurface recovery, so it is no longer quarantined"
                + " (2026-09-06)");
        TestSupport.truth(QuickResumePolicy.shouldCopyPreviousToRecovery(64 * 1024 * 1024),
                "64 MiB state retains recovery-copy convenience");
        TestSupport.truth(!QuickResumePolicy.shouldCopyPreviousToRecovery(
                        64 * 1024 * 1024 + 1),
                "state above 64 MiB avoids duplicating prior state in heap");
        TestSupport.truth(!QuickResumePolicy.mayCompleteStop(true, false),
                "Exit to Lucent refuses to complete after an actual commit failure");
        TestSupport.truth(QuickResumePolicy.mayCompleteStop(true, true),
                "Exit to Lucent completes after a verified commit");
        TestSupport.truth(QuickResumePolicy.mayCompleteStop(false, false),
                "non-user teardown remains best effort");
    }

    private static void largeQuickResumeCommitIsAtomicAndSurvivesProcessDeath()
            throws Exception {
        File root = TestSupport.temporaryDirectory("large-quick-resume");
        try {
            StateIdentity identity = identity("large-engine");
            StateVault vault = new StateVault(root);
            byte[] oldState = new byte[64 * 1024 * 1024 + 1];
            Arrays.fill(oldState, (byte) 3);
            StateSnapshot old = vault.saveQuickResume(identity, oldState, null, 10L);
            File game = old.directory.getParentFile().getParentFile();
            File snapshots = old.directory.getParentFile();
            File held = new File(game, "snapshots-held");
            TestSupport.truth(snapshots.renameTo(held),
                    "stage snapshots directory to force the next publication to fail");
            TestSupport.truth(snapshots.createNewFile(),
                    "blocking file makes snapshot publication fail deterministically");
            boolean failed = false;
            try {
                vault.saveQuickResume(identity, new byte[] { 9 }, null, 11L);
            } catch (Exception expected) { failed = true; }
            TestSupport.truth(failed, "new Quick Resume commit failure is observable");
            TestSupport.truth(snapshots.delete() && held.renameTo(snapshots),
                    "restore old on-disk snapshots after induced failure");
            StateLoadResult oldAfterFailure = new StateVault(root).loadQuickResume(identity);
            TestSupport.equal(StateLoadResult.Status.OK, oldAfterFailure.status,
                    "old Quick Resume remains valid when new commit fails");
            TestSupport.equal(3, (int) oldAfterFailure.state[oldAfterFailure.state.length - 1],
                    "failed commit did not replace old large state");

            byte[] replacement = new byte[64 * 1024 * 1024 + 1];
            Arrays.fill(replacement, (byte) 7);
            vault.saveQuickResume(identity, replacement, null, 12L);
            StateLoadResult afterProcessDeath = new StateVault(root).loadQuickResume(identity);
            TestSupport.equal(StateLoadResult.Status.OK, afterProcessDeath.status,
                    "successful large commit survives a new vault/process instance");
            TestSupport.equal(replacement.length, afterProcessDeath.state.length,
                    "large committed state retains exact size");
            TestSupport.equal(7, (int) afterProcessDeath.state[0],
                    "new process restores the replacement state");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void schedulerUsesTenMinuteDefaultAndRejectsOverflow() {
        CheckpointScheduler scheduler = new CheckpointScheduler();
        TestSupport.equal(CheckpointScheduler.DEFAULT_INTERVAL_MILLIS,
                scheduler.millisUntilNextCheckpoint(), "default interval is ten active minutes");
        TestSupport.equal(0, scheduler.advanceActivePlay(599_999L),
                "ten-minute checkpoint is not early");
        TestSupport.equal(1, scheduler.advanceActivePlay(1L),
                "ten-minute checkpoint fires at the exact boundary");
        CheckpointScheduler nearLimit = new CheckpointScheduler(10L, Long.MAX_VALUE - 1L);
        boolean overflowRejected = false;
        try { nearLimit.advanceActivePlay(2L); }
        catch (ArithmeticException expected) { overflowRejected = true; }
        TestSupport.truth(overflowRejected, "active-time overflow is explicit");
    }

    private static void schedulerCountsOnlySuppliedActiveTime() {
        CheckpointScheduler scheduler = new CheckpointScheduler(1_000L, 0L);
        TestSupport.equal(0, scheduler.advanceActivePlay(999L), "checkpoint must not be early");
        TestSupport.equal(1L, scheduler.millisUntilNextCheckpoint(), "one active ms remains");
        // Paused/background time is deliberately not sent to the scheduler.
        TestSupport.equal(1, scheduler.advanceActivePlay(1L), "checkpoint is due at interval");
        TestSupport.equal(1_000L, scheduler.totalActiveMillis(), "active play accumulated");
        TestSupport.equal(2, scheduler.advanceActivePlay(2_500L), "large tick reports all due states");
        TestSupport.equal(500L, scheduler.millisUntilNextCheckpoint(), "remainder retained");
    }

    private static void retentionKeepsNewestAndHourlyAnchors() {
        RetentionPolicy policy = new RetentionPolicy(3, 5, 10_000L);
        List<RetentionPolicy.Candidate> states = new ArrayList<>();
        for (int i = 0; i < 9; i++) states.add(new RetentionPolicy.Candidate(
                "s" + i, i * 60L * 60L * 1000L, 100L));
        Set<String> deleted = policy.selectForDeletion(states, "s0");
        TestSupport.truth(!deleted.contains("s8") && !deleted.contains("s7") &&
                !deleted.contains("s6"), "newest states survive");
        TestSupport.truth(!deleted.contains("s0"), "protected Quick Resume survives");
        TestSupport.equal(5, 9 - deleted.size(), "policy fills remaining capacity with hourly anchors");
    }

    private static void retentionByteAccountingCannotOverflow() {
        RetentionPolicy policy = new RetentionPolicy(1, 3, 100L);
        List<RetentionPolicy.Candidate> states = new ArrayList<>();
        states.add(new RetentionPolicy.Candidate("protected", 1L, Long.MAX_VALUE, false));
        states.add(new RetentionPolicy.Candidate("newest", 3L, Long.MAX_VALUE, true));
        states.add(new RetentionPolicy.Candidate("optional", 2L, 1L, true));
        Set<String> deleted = policy.selectForDeletion(states, "protected");
        TestSupport.truth(deleted.contains("optional"),
                "overflow cannot make an optional state appear under the byte ceiling");
        TestSupport.truth(!deleted.contains("protected") && !deleted.contains("newest"),
                "mandatory states remain protected even when they exceed the ceiling");
    }

    private static void vaultRoundTripAndValidation() throws Exception {
        File root = TestSupport.temporaryDirectory("state-vault");
        try {
            MutableClock clock = new MutableClock(1_000L);
            StateVault vault = new StateVault(root, clock, new RetentionPolicy(2, 4, 1_000_000L));
            StateIdentity identity = identity("engine-1");
            byte[] bytes = "serialized emulator memory".getBytes(StandardCharsets.UTF_8);
            StateSnapshot saved = vault.saveQuickResume(identity, bytes, new byte[] { 1, 2, 3 }, 600_000L);
            TestSupport.truth(saved.directory.isDirectory(), "snapshot is published");
            TestSupport.truth(saved.screenshotFile().isFile(), "preview is retained");

            StateLoadResult loaded = vault.loadQuickResume(identity);
            TestSupport.equal(StateLoadResult.Status.OK, loaded.status, "valid state loads");
            TestSupport.equal(new String(bytes, StandardCharsets.UTF_8),
                    new String(loaded.state, StandardCharsets.UTF_8), "state round trips");
            TestSupport.equal(StateLoadResult.Status.NOT_FOUND,
                    vault.loadQuickResume(identity("engine-2")).status,
                    "different engine version uses isolated storage");
            TestSupport.equal(StateLoadResult.Status.IDENTITY_MISMATCH,
                    vault.loadSnapshot(identity("engine-2"), saved).status,
                    "an explicitly selected snapshot rejects a different engine version");

            FileOutputStream corrupt = new FileOutputStream(new File(saved.directory, "state.bin.gz"));
            corrupt.write(new byte[] { 0, 1, 2, 3 });
            corrupt.close();
            TestSupport.equal(StateLoadResult.Status.CORRUPT,
                    vault.loadQuickResume(identity).status, "corruption is explicit");
            TestSupport.truth(saved.directory.exists(), "corrupt state is retained for recovery");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void vaultPrunesWithoutDeletingQuickResume() throws Exception {
        File root = TestSupport.temporaryDirectory("state-prune");
        try {
            MutableClock clock = new MutableClock(0L);
            StateVault vault = new StateVault(root, clock, new RetentionPolicy(2, 3, 1_000_000L));
            StateIdentity identity = identity("engine-1");
            vault.saveQuickResume(identity, new byte[] { 9 }, null, 0L);
            for (int i = 1; i <= 6; i++) {
                clock.now = i * 60L * 60L * 1000L;
                vault.saveAutomatic(identity, new byte[] { (byte) i }, null, i * 100L);
            }
            TestSupport.truth(vault.list(identity).size() <= 3, "retention ceiling applied");
            TestSupport.equal(StateLoadResult.Status.OK, vault.loadQuickResume(identity).status,
                    "Quick Resume is protected even when oldest");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void unreadableQuickReferenceProtectsSnapshotsFromPrune() throws Exception {
        File root = TestSupport.temporaryDirectory("state-prune-corrupt-ref");
        try {
            MutableClock clock = new MutableClock(0L);
            StateVault vault = new StateVault(root, clock, new RetentionPolicy(2, 3, 1_000_000L));
            StateIdentity identity = identity("engine-1");
            StateSnapshot quick = vault.saveQuickResume(identity, new byte[] { 9 }, null, 0L);
            File game = quick.directory.getParentFile().getParentFile();
            FileOutputStream corrupt = new FileOutputStream(new File(game, "quick-resume.ref"));
            corrupt.write("../not a snapshot id".getBytes(StandardCharsets.UTF_8));
            corrupt.close();
            for (int i = 1; i <= 6; i++) {
                clock.now = i * 60L * 60L * 1000L;
                vault.saveAutomatic(identity, new byte[] { (byte) i }, null, i * 100L);
            }
            // With the reference unreadable the retention policy cannot know
            // which Quick Resume snapshot is live; pruning must fail closed
            // and leave every snapshot on disk rather than delete the state
            // the reference pointed at.
            TestSupport.truth(quick.directory.isDirectory(),
                    "corrupt reference protects the live Quick Resume from prune");
            TestSupport.equal(7, vault.list(identity).size(),
                    "fail-closed prune leaves every snapshot on disk");
        } finally { TestSupport.deleteTree(root); }

        File unreadableRoot = TestSupport.temporaryDirectory("state-prune-unreadable-ref");
        try {
            MutableClock clock = new MutableClock(0L);
            StateVault vault = new StateVault(unreadableRoot, clock,
                    new RetentionPolicy(2, 3, 1_000_000L));
            StateIdentity identity = identity("engine-1");
            StateSnapshot quick = vault.saveQuickResume(identity, new byte[] { 9 }, null, 0L);
            File game = quick.directory.getParentFile().getParentFile();
            File reference = new File(game, "quick-resume.ref");
            TestSupport.truth(reference.delete() && reference.mkdir(),
                    "replace the reference with an unreadable entry");
            for (int i = 1; i <= 6; i++) {
                clock.now = i * 60L * 60L * 1000L;
                vault.saveAutomatic(identity, new byte[] { (byte) i }, null, i * 100L);
            }
            TestSupport.truth(quick.directory.isDirectory(),
                    "unreadable reference protects the live Quick Resume from prune");
            TestSupport.equal(7, vault.list(identity).size(),
                    "unreadable reference fails prune closed for every snapshot");
        } finally { TestSupport.deleteTree(unreadableRoot); }
    }

    private static void separateInstancesOverOneRootShareOneMonitor() throws Exception {
        File root = TestSupport.temporaryDirectory("state-root-monitor");
        try {
            // Sessions construct separate StateVault instances over one root
            // during a game switch; mutual exclusion is therefore keyed on
            // the canonical root path, not on the instance.
            StateVault first = new StateVault(root);
            StateVault second = new StateVault(new File(root, "."));
            TestSupport.truth(first.rootMonitor() == second.rootMonitor(),
                    "instances over one canonical root share one lock monitor");
            TestSupport.truth(first.rootMonitor() !=
                            new StateVault(new File(root, "other")).rootMonitor(),
                    "different roots keep separate lock monitors");

            // Functional interleaving: a retiring instance's saves and a new
            // instance's save/prune passes over one game directory must leave
            // a loadable Quick Resume behind.
            StateIdentity identity = identity("engine-1");
            first.saveQuickResume(identity, new byte[] { 1 }, null, 1L);
            second.saveAutomatic(identity, new byte[] { 2 }, null, 2L);
            first.saveAutomatic(identity, new byte[] { 3 }, null, 3L);
            second.saveQuickResume(identity, new byte[] { 4 }, null, 4L);
            StateLoadResult loaded = first.loadQuickResume(identity);
            TestSupport.equal(StateLoadResult.Status.OK, loaded.status,
                    "interleaved two-instance save and prune keep Quick Resume loadable");
            TestSupport.equal(4, (int) loaded.state[0],
                    "the newest Quick Resume wins across instances");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void publishVerificationRejectsChecksumMismatch() throws Exception {
        File root = TestSupport.temporaryDirectory("state-publish-verify");
        try {
            StateVault vault = new StateVault(root);
            StateIdentity identity = identity("engine-1");
            StateSnapshot good = vault.saveQuickResume(identity, new byte[] { 1, 2, 3 }, null, 1L);
            TestSupport.truth(good.directory.isDirectory(),
                    "a verifiable snapshot publishes normally");

            // Simulate a snapshot whose durable payload does not match its
            // manifest digests: same manifest, same payload length, different
            // bytes. The publish-verify path must reject it, which is what
            // keeps saveQuickResume from ever swapping quick-resume.ref to an
            // unloadable snapshot.
            File fake = new File(root, "corrupt-published");
            TestSupport.truth(fake.mkdir(), "crafted snapshot directory is created");
            byte[] manifest = readFully(new File(good.directory, "manifest.properties"));
            FileOutputStream copied = new FileOutputStream(new File(fake, "manifest.properties"));
            copied.write(manifest);
            copied.close();
            FileOutputStream corrupt = new FileOutputStream(new File(fake, "state.bin.gz"));
            java.util.zip.GZIPOutputStream gzip = new java.util.zip.GZIPOutputStream(corrupt);
            gzip.write(new byte[] { 9, 9, 9 });
            gzip.close();
            boolean rejected = false;
            try { StateVault.verifyPublishedState(fake); }
            catch (java.io.IOException expected) { rejected = true; }
            TestSupport.truth(rejected,
                    "publish verification rejects a state whose checksum mismatches");

            StateLoadResult loaded = vault.loadQuickResume(identity);
            TestSupport.equal(StateLoadResult.Status.OK, loaded.status,
                    "the reference still targets the verified snapshot");
            TestSupport.equal(1, (int) loaded.state[0],
                    "rejected snapshot never replaced the loadable Quick Resume");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void previousQuickResumeSurvivesForOneGeneration() throws Exception {
        File root = TestSupport.temporaryDirectory("state-previous-generation");
        try {
            MutableClock clock = new MutableClock(1_000L);
            StateVault vault = new StateVault(root, clock, new RetentionPolicy(2, 3, 1_000_000L));
            StateIdentity identity = identity("engine-1");
            StateSnapshot first = vault.saveQuickResume(identity, new byte[] { 1 }, null, 1L);
            clock.now = 2_000L;
            StateSnapshot second = vault.saveQuickResume(identity, new byte[] { 2 }, null, 2L);
            // The prune following the second publish protected the previous
            // generation: if the new state proves unreadable later, the prior
            // Quick Resume still exists on disk.
            TestSupport.truth(first.directory.isDirectory(),
                    "previous Quick Resume survives the prune after its replacement");
            TestSupport.truth(second.directory.isDirectory(), "new Quick Resume is published");
            clock.now = 3_000L;
            StateSnapshot third = vault.saveQuickResume(identity, new byte[] { 3 }, null, 3L);
            TestSupport.truth(!first.directory.exists(),
                    "protection lasts exactly one generation");
            TestSupport.truth(second.directory.isDirectory() && third.directory.isDirectory(),
                    "current and previous generations remain");
            StateLoadResult loaded = vault.loadQuickResume(identity);
            TestSupport.equal(StateLoadResult.Status.OK, loaded.status,
                    "newest Quick Resume loads after generational pruning");
            TestSupport.equal(3, (int) loaded.state[0], "newest generation is the live one");
        } finally { TestSupport.deleteTree(root); }
    }

    private static byte[] readFully(File file) throws Exception {
        java.io.FileInputStream input = new java.io.FileInputStream(file);
        try {
            java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) >= 0)
                if (count > 0) output.write(buffer, 0, count);
            return output.toByteArray();
        } finally { input.close(); }
    }

    private static void sharedVaultReturnsOneInstancePerRoot() throws Exception {
        File root = TestSupport.temporaryDirectory("state-shared-root");
        try {
            // Vault operations synchronize on the instance; a retiring session
            // and its relaunch must therefore resolve to the same instance or
            // their save and prune passes can interleave over one directory.
            TestSupport.truth(StateVault.shared(root) == StateVault.shared(root),
                    "one root resolves to one shared vault instance");
            TestSupport.truth(StateVault.shared(root) !=
                            StateVault.shared(new File(root, "other")),
                    "different roots keep separate vault instances");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void quickResumeReferenceRecoversAfterInterruptedReplace() throws Exception {
        File root = TestSupport.temporaryDirectory("quick-ref-recovery");
        try {
            StateVault vault = new StateVault(root);
            StateIdentity identity = identity("engine-1");
            StateSnapshot saved = vault.saveQuickResume(identity, new byte[] { 42 }, null, 1L);
            File game = saved.directory.getParentFile().getParentFile();
            File reference = new File(game, "quick-resume.ref");
            File backup = new File(game, "quick-resume.ref.previous");
            TestSupport.truth(reference.renameTo(backup),
                    "simulate death after staging the old Quick Resume reference");
            StateLoadResult recovered = vault.loadQuickResume(identity);
            TestSupport.equal(StateLoadResult.Status.OK, recovered.status,
                    "Quick Resume reference recovers from fallback backup");
            TestSupport.equal(42, (int) recovered.state[0],
                    "recovered reference still points to the verified snapshot");
            TestSupport.truth(reference.isFile() && !backup.exists(),
                    "recovery republishes the reference and clears the backup");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void workerCopiesStateBeforeBackgroundCompression() throws Exception {
        File root = TestSupport.temporaryDirectory("state-worker");
        try {
            StateIdentity identity = identity("engine-1");
            StateVault vault = new StateVault(root);
            StateVaultWorker worker = new StateVaultWorker(vault);
            byte[] state = new byte[] { 4, 5, 6 };
            Future<StateSnapshot> future = worker.saveQuickResume(identity, state, null, 10L);
            state[0] = 99;
            future.get();
            worker.close();
            TestSupport.equal(4, (int) vault.loadQuickResume(identity).state[0],
                    "queued state is insulated from engine buffer reuse");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void workerDrainsQueuedSnapshotsDuringConcurrentClose() throws Exception {
        File root = TestSupport.temporaryDirectory("state-worker-close");
        try {
            StateIdentity identity = identity("engine-1");
            StateVault vault = new StateVault(root, Clock.SYSTEM,
                    new RetentionPolicy(20, 32, 16L * 1024L * 1024L));
            StateVaultWorker worker = new StateVaultWorker(vault);
            List<Future<StateSnapshot>> writes = new ArrayList<>();
            for (int i = 0; i < 20; i++)
                writes.add(worker.saveAutomatic(identity, new byte[] { (byte) i }, null, i));
            worker.close();
            for (Future<StateSnapshot> write : writes)
                TestSupport.truth(write.get(10L, TimeUnit.SECONDS).directory.isDirectory(),
                        "queued snapshot commits during orderly close");
            TestSupport.truth(worker.awaitTermination(10L, TimeUnit.SECONDS),
                    "state worker terminates after draining its queue");
            TestSupport.equal(20, vault.list(identity).size(),
                    "concurrent close loses no queued checkpoint");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void quickResumeDoesNotDisplaceAutomaticHistory() throws Exception {
        File root = TestSupport.temporaryDirectory("state-history-kind");
        try {
            MutableClock clock = new MutableClock(0L);
            StateVault vault = new StateVault(root, clock, new RetentionPolicy(3, 8, 1_000_000L));
            StateIdentity identity = identity("engine-1");
            for (int i = 1; i <= 3; i++) {
                clock.now = i * 10L;
                vault.saveAutomatic(identity, new byte[] { (byte) i }, null, i);
            }
            for (int i = 4; i <= 12; i++) {
                clock.now = i * 10L;
                vault.saveQuickResume(identity, new byte[] { (byte) i }, null, i);
            }
            int automatic = 0;
            int quick = 0;
            for (StateSnapshot snapshot : vault.list(identity)) {
                if (snapshot.metadata.kind == SnapshotKind.AUTOMATIC) automatic++;
                if (snapshot.metadata.kind == SnapshotKind.QUICK_RESUME) quick++;
            }
            TestSupport.equal(3, automatic, "Quick Resume cannot displace automatic history");
            TestSupport.equal(2, quick,
                    "the referenced Quick Resume plus one prior generation are retained");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void identitiesUseSeparateStorage() throws Exception {
        File root = TestSupport.temporaryDirectory("state-identity");
        try {
            StateVault vault = new StateVault(root);
            StateIdentity first = identity("engine-1");
            StateIdentity second = identity("engine-2");
            vault.saveAutomatic(first, new byte[] { 1 }, null, 1L);
            vault.saveAutomatic(second, new byte[] { 2 }, null, 2L);
            TestSupport.equal(1, vault.list(first).size(), "first identity is isolated");
            TestSupport.equal(1, vault.list(second).size(), "second identity is isolated");
            TestSupport.truth(!first.storageKey().equals(second.storageKey()),
                    "full identity participates in the storage key");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void exactCoreArtifactIdentityIsolatesState() throws Exception {
        File root = TestSupport.temporaryDirectory("state-core-artifact-identity");
        try {
            StateVault vault = new StateVault(root);
            String commit = "upstream-commit";
            StateIdentity firstArtifact = identity(commit + ":sha256:" + repeat("1a", 32));
            StateIdentity rebuiltArtifact = identity(commit + ":sha256:" + repeat("2b", 32));
            StateSnapshot saved = vault.saveQuickResume(
                    firstArtifact, new byte[] { 7, 8, 9 }, null, 1L);
            TestSupport.equal(StateLoadResult.Status.NOT_FOUND,
                    vault.loadQuickResume(rebuiltArtifact).status,
                    "a different exact core artifact cannot discover stale Quick Resume state");
            TestSupport.equal(StateLoadResult.Status.IDENTITY_MISMATCH,
                    vault.loadSnapshot(rebuiltArtifact, saved).status,
                    "an explicitly selected stale state rejects a different core artifact");
            TestSupport.truth(!firstArtifact.storageKey().equals(rebuiltArtifact.storageKey()),
                    "the exact core artifact SHA participates in state storage identity");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void qualificationSessionIdentityRestoresOnlyWithinSameRun()
            throws Exception {
        File root = TestSupport.temporaryDirectory("state-qualification-session");
        try {
            StateVault vault = new StateVault(root);
            String artifact = "commit:sha256:" + repeat("3c", 32);
            StateIdentity firstLaunch = identity(artifact + ":qa:qa-" + repeat("1", 32));
            StateIdentity sameRunRestart = identity(artifact + ":qa:qa-" + repeat("1", 32));
            StateIdentity differentRun = identity(artifact + ":qa:qa-" + repeat("2", 32));
            vault.saveQuickResume(firstLaunch, new byte[] { 4, 2 }, null, 1L);
            TestSupport.equal(StateLoadResult.Status.OK,
                    vault.loadQuickResume(sameRunRestart).status,
                    "the same qualification namespace restores after process death");
            TestSupport.equal(StateLoadResult.Status.NOT_FOUND,
                    vault.loadQuickResume(differentRun).status,
                    "a different qualification run cannot discover prior QA state");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void durableBlobRecoversAndCapsReads() throws Exception {
        File root = TestSupport.temporaryDirectory("durable-blob");
        try {
            File target = new File(root, "save.bin");
            DurableBlobStore.write(target, new byte[] { 1, 2, 3 }, 8);
            TestSupport.equal(3, DurableBlobStore.read(target, 8).length,
                    "bounded blob round trips");
            File backup = new File(root, "save.bin.previous");
            TestSupport.truth(target.renameTo(backup), "simulate interrupted fallback replacement");
            TestSupport.equal(1, (int) DurableBlobStore.read(target, 8)[0],
                    "previous save is recovered");
            boolean rejected = false;
            try { DurableBlobStore.read(target, 2); }
            catch (java.io.IOException expected) { rejected = true; }
            TestSupport.truth(rejected, "oversized save is rejected before allocation");
        } finally { TestSupport.deleteTree(root); }
    }

    private static StateIdentity identity(String engineVersion) {
        return new StateIdentity("game:example", repeat("ab", 32), "mesen", engineVersion,
                "serialize-v1", "firmware:none");
    }

    private static String repeat(String value, int times) {
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < times; i++) result.append(value);
        return result.toString();
    }

    private static final class MutableClock implements Clock {
        long now;
        MutableClock(long now) { this.now = now; }
        @Override public long wallTimeMillis() { return now; }
    }
}
