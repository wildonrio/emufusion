package com.thorium.lucent.state;

import com.thorium.lucent.TestSupport;

import java.io.File;
import java.io.IOException;

/**
 * Opt-in, red-first recovery contract for the 2026-09-06 DS crash investigation.
 * This is deliberately not added to test.sh before the product proposal is
 * approved. It uses the real vault; the one-byte states are opaque identities,
 * not a simulation of melonDS SRAM serialization.
 */
public final class StateVaultAutomaticRecoveryTest {
    public static void main(String[] ignored) throws Exception {
        int failures = 0;
        try { committedAutomaticBecomesRestartPoint(false); }
        catch (AssertionError failure) {
            failures++;
            System.err.println("FAIL automatic restart: " + failure.getMessage());
        }
        try { committedAutomaticBecomesRestartPoint(true); }
        catch (AssertionError failure) {
            failures++;
            System.err.println("FAIL clock rollback: " + failure.getMessage());
        }
        failedAutomaticKeepsPreviousRestartPoint();
        System.out.println("PASS failed automatic preserves previous restart point");
        if (failures != 0)
            throw new AssertionError(failures + " automatic recovery contract(s) failed");
        System.out.println("StateVaultAutomaticRecoveryTest passed");
    }

    private static void committedAutomaticBecomesRestartPoint(boolean rollClockBack)
            throws Exception {
        File root = TestSupport.temporaryDirectory("automatic-restart");
        try {
            MutableClock clock = new MutableClock(2_000L);
            StateIdentity identity = identity();
            StateVault vault = new StateVault(root, clock, RetentionPolicy.DEFAULT);
            StateSnapshot old = vault.saveQuickResume(identity, new byte[] { 1 }, null, 1L);
            clock.now = rollClockBack ? 1_000L : 3_000L;
            StateSnapshot automatic = vault.saveAutomatic(
                    identity, new byte[] { 2 }, null, 600_000L);

            TestSupport.equal(SnapshotKind.AUTOMATIC, automatic.metadata.kind,
                    "resumability must not relabel automatic history as a manual exit");
            TestSupport.truth(old.directory.isDirectory(),
                    "previous restart point remains recoverable after publication");
            StateLoadResult restarted = new StateVault(root).loadQuickResume(identity);
            TestSupport.equal(StateLoadResult.Status.OK, restarted.status,
                    "a new process can load the committed restart point");
            TestSupport.equal(automatic.metadata.snapshotId,
                    restarted.snapshot.metadata.snapshotId,
                    "last successful automatic commit must replace stale Quick Resume"
                            + (rollClockBack ? " despite wall-clock rollback" : ""));
            TestSupport.equal(2, (int) restarted.state[0],
                    "restart must return the newly committed state bytes");
        } finally {
            TestSupport.deleteTree(root);
        }
    }

    private static void failedAutomaticKeepsPreviousRestartPoint() throws Exception {
        File root = TestSupport.temporaryDirectory("automatic-restart-failure");
        try {
            StateIdentity identity = identity();
            StateVault vault = new StateVault(root);
            StateSnapshot old = vault.saveQuickResume(identity, new byte[] { 1 }, null, 1L);
            File snapshots = old.directory.getParentFile();
            File held = new File(snapshots.getParentFile(), "snapshots-held");
            TestSupport.truth(snapshots.renameTo(held), "stage existing snapshots");
            TestSupport.truth(snapshots.createNewFile(), "block new snapshot publication");
            boolean rejected = false;
            try {
                vault.saveAutomatic(identity, new byte[] { 2 }, null, 600_000L);
            } catch (IOException expected) {
                rejected = true;
            }
            TestSupport.truth(rejected, "failed automatic commit must be observable");
            TestSupport.truth(snapshots.delete() && held.renameTo(snapshots),
                    "restore the pre-existing test snapshots");
            StateLoadResult restarted = new StateVault(root).loadQuickResume(identity);
            TestSupport.equal(StateLoadResult.Status.OK, restarted.status,
                    "publication failure must retain a readable previous reference");
            TestSupport.equal(old.metadata.snapshotId, restarted.snapshot.metadata.snapshotId,
                    "failed publication must not advance the restart reference");
        } finally {
            TestSupport.deleteTree(root);
        }
    }

    private static StateIdentity identity() {
        return new StateIdentity("ds-recovery-fixture",
                "abababababababababababababababababababababababababababababababab",
                "melonds-ds", "fixture-core-sha256", "serialize-v1", "firmware:none");
    }

    private static final class MutableClock implements Clock {
        long now;
        MutableClock(long now) { this.now = now; }
        @Override public long wallTimeMillis() { return now; }
    }
}
