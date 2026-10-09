package com.thorium.lucent.state;

import com.thorium.lucent.TestSupport;
import java.io.File;
import java.util.Arrays;

/** Run with -Xmx192m: a Wii-sized state must not need duplicate expanded buffers. */
public final class StateVaultHeapTest {
    private static final int BYTES = 129 * 1024 * 1024 + 17;

    public static void main(String[] args) throws Exception {
        File root = TestSupport.temporaryDirectory("state-vault-heap");
        try {
            StateVault vault = new StateVault(root);
            StateIdentity identity = new StateIdentity("heap-fixture",
                    repeat("ab", 32), "dolphin", "fixture-v1", "serialize-v1", "none");
            save(vault, identity);
            // The original producer array is out of scope; loading needs only
            // the one returned array, not a growable buffer plus a final copy.
            StateLoadResult loaded = vault.loadQuickResume(identity);
            TestSupport.equal(StateLoadResult.Status.OK, loaded.status, "large state loads");
            TestSupport.equal(BYTES, loaded.state.length, "exact byte length retained");
            for (int i = 0; i < loaded.state.length; i++) {
                if (loaded.state[i] != (byte) 73)
                    throw new AssertionError("State mismatch at " + i);
            }
            System.out.println("StateVaultHeapTest passed: " + BYTES
                    + " bytes, max heap=" + Runtime.getRuntime().maxMemory());
        } finally { TestSupport.deleteTree(root); }
    }

    private static void save(StateVault vault, StateIdentity identity) throws Exception {
        byte[] state = new byte[BYTES];
        Arrays.fill(state, (byte) 73);
        StateSnapshot saved = vault.saveQuickResume(identity, state, null, 1L);
        StateVault.verifyPublishedState(saved.directory);
        TestSupport.equal(BYTES, (int) saved.metadata.uncompressedBytes,
                "verification retained manifest length");
    }

    private static String repeat(String value, int count) {
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < count; i++) text.append(value);
        return text.toString();
    }
}
