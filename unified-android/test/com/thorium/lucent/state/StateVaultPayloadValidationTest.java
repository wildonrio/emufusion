package com.thorium.lucent.state;

import com.thorium.lucent.TestSupport;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.zip.GZIPOutputStream;

/** Streaming verification must retain all of the on-disk round-trip checks. */
public final class StateVaultPayloadValidationTest {
    public static void main(String[] args) throws Exception {
        File root = TestSupport.temporaryDirectory("state-payload-validation");
        try {
            StateIdentity identity = new StateIdentity("payload-fixture",
                    Digests.sha256(new byte[] { 1 }), "dolphin", "fixture-v1", "v1", "none");
            StateVault vault = new StateVault(root);
            byte[] bytes = { 1, 2, 3 };
            StateSnapshot snapshot = vault.saveQuickResume(identity, bytes, null, 1L);
            File payload = new File(snapshot.directory, "state.bin.gz");
            write(payload, new byte[] { 1, 2 });
            reject(vault, identity, snapshot, "short expansion");
            write(payload, new byte[] { 1, 2, 3, 4 });
            reject(vault, identity, snapshot, "oversized expansion");
            write(payload, new byte[] { 3, 2, 1 });
            reject(vault, identity, snapshot, "same-sized wrong payload");

            write(payload, bytes);
            try (RandomAccessFile file = new RandomAccessFile(payload, "rw")) {
                file.setLength(file.length() - 1);
            }
            reject(vault, identity, snapshot, "truncated gzip trailer");
            write(payload, bytes);
            try (RandomAccessFile file = new RandomAccessFile(payload, "rw")) {
                file.seek(file.length() - 8);
                int crcByte = file.read();
                file.seek(file.length() - 8);
                file.write(crcByte ^ 1);
            }
            reject(vault, identity, snapshot, "bad gzip CRC trailer");

            write(payload, bytes);
            SnapshotMetadata good = snapshot.metadata;
            manifest(snapshot, good.uncompressedBytes, Digests.sha256(new byte[] { 9 }), good.stateCrc32);
            reject(vault, identity, snapshot, "SHA mismatch with correct CRC");
            manifest(snapshot, good.uncompressedBytes, good.stateSha256, good.stateCrc32 ^ 1);
            reject(vault, identity, snapshot, "CRC mismatch with correct SHA");
            manifest(snapshot, 0, good.stateSha256, good.stateCrc32);
            reject(vault, identity, snapshot, "zero manifest length");
            manifest(snapshot, 512L * 1024 * 1024 + 1, good.stateSha256, good.stateCrc32);
            reject(vault, identity, snapshot, "over-limit manifest length");
            manifest(snapshot, good.uncompressedBytes, good.stateSha256, good.stateCrc32);
            StateVault.verifyPublishedState(snapshot.directory);
            TestSupport.equal(StateLoadResult.Status.OK, vault.loadQuickResume(identity).status,
                    "valid original payload still loads with the original reference");
            System.out.println("StateVaultPayloadValidationTest passed: 9 corrupt cases and valid control");
        } finally { TestSupport.deleteTree(root); }
    }

    private static void write(File file, byte[] bytes) throws IOException {
        try (GZIPOutputStream gzip = new GZIPOutputStream(new FileOutputStream(file))) {
            gzip.write(bytes);
        }
    }

    private static void manifest(StateSnapshot snapshot, long bytes, String sha, long crc)
            throws IOException {
        SnapshotMetadata m = snapshot.metadata;
        try (FileOutputStream output = new FileOutputStream(
                new File(snapshot.directory, "manifest.properties"))) {
            new SnapshotMetadata(m.snapshotId, m.kind, m.identity, m.createdAtMillis,
                    m.activePlayMillis, bytes, sha, crc, m.hasScreenshot).write(output);
        }
    }

    private static void reject(StateVault vault, StateIdentity identity,
            StateSnapshot snapshot, String label) throws IOException {
        boolean rejected = false;
        try { StateVault.verifyPublishedState(snapshot.directory); }
        catch (IOException expected) { rejected = true; }
        TestSupport.truth(rejected, label + " rejected at publication");
        TestSupport.equal(StateLoadResult.Status.CORRUPT, vault.loadQuickResume(identity).status,
                label + " rejected at load");
    }
}
