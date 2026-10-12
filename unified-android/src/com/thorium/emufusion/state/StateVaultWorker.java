package com.thorium.emufusion.state;

import java.io.Closeable;
import java.util.Arrays;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

/** Serial background queue so compression and fsync never run on the render thread. */
public final class StateVaultWorker implements Closeable {
    private final StateVault vault;
    private final ExecutorService executor;

    public StateVaultWorker(StateVault vault) {
        if (vault == null) throw new IllegalArgumentException("vault is required");
        this.vault = vault;
        this.executor = Executors.newSingleThreadExecutor(runnable -> {
            Thread thread = new Thread(runnable, "emufusion-state-vault");
            thread.setDaemon(true);
            return thread;
        });
    }

    public Future<StateSnapshot> saveQuickResume(final StateIdentity identity, byte[] state,
            byte[] screenshot, final long activePlayMillis) {
        final byte[] protectedState = copy(state);
        final byte[] protectedScreenshot = copy(screenshot);
        return executor.submit(() -> vault.saveQuickResume(identity, protectedState,
                protectedScreenshot, activePlayMillis));
    }

    public Future<StateSnapshot> saveAutomatic(final StateIdentity identity, byte[] state,
            byte[] screenshot, final long activePlayMillis) {
        final byte[] protectedState = copy(state);
        final byte[] protectedScreenshot = copy(screenshot);
        return executor.submit(() -> vault.saveAutomatic(identity, protectedState,
                protectedScreenshot, activePlayMillis));
    }

    public Future<StateSnapshot> saveRecovery(final StateIdentity identity, byte[] state,
            byte[] screenshot, final long activePlayMillis) {
        final byte[] protectedState = copy(state);
        final byte[] protectedScreenshot = copy(screenshot);
        return executor.submit(() -> vault.saveRecovery(identity, protectedState,
                protectedScreenshot, activePlayMillis));
    }

    public Future<StateSnapshot> saveBeforeEngineUpdate(final StateIdentity identity, byte[] state,
            byte[] screenshot, final long activePlayMillis) {
        final byte[] protectedState = copy(state);
        final byte[] protectedScreenshot = copy(screenshot);
        return executor.submit(() -> vault.saveBeforeEngineUpdate(identity, protectedState,
                protectedScreenshot, activePlayMillis));
    }

    /** Begins an orderly shutdown; already queued snapshots are still committed. */
    @Override public void close() {
        executor.shutdown();
    }

    /** Allows an engine teardown to retain every already-queued atomic write. */
    public boolean awaitTermination(long timeout, TimeUnit unit) throws InterruptedException {
        return executor.awaitTermination(timeout, unit);
    }

    private static byte[] copy(byte[] value) {
        return value == null ? null : Arrays.copyOf(value, value.length);
    }
}
