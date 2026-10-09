package com.thorium.preview.cheats.delivery;

import com.thorium.lucent.cheats.Cheat;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicReference;

/** Host proof of the registry the EngineSession defaults consult. */
public final class CheatSessionRegistryTest {
    private static final Executor DIRECT = new Executor() {
        @Override public void execute(Runnable task) { task.run(); }
    };

    public static void main(String[] args) {
        nothingRegistered();
        decoration();
        toggling();
        failures();
        registryLifecycle();
        System.out.println("Cheat session registry tests passed");
    }

    private static List<DeliveryCheat> rows() {
        List<DeliveryCheat> rows = new ArrayList<>();
        rows.add(new DeliveryCheat(new Cheat("live1", "Live", "from libretro", "AAAA:11"), "libretro", "live", null, ""));
        rows.add(new DeliveryCheat(new Cheat("boot1", "Boot", "pcsx2", "patch=1,EE,1,word,1"), "pcsx2", "boot",
                Arrays.asList("widescreen"), "pnach"));
        rows.add(new DeliveryCheat(new Cheat("unsup", "Unsupported", "", "x"), "mame", "unsupported", null, ""));
        return rows;
    }

    private static void nothingRegistered() {
        Object session = new Object();
        check(CheatSessionRegistry.forSession(session) == null, "no binding");
        check(CheatSessionRegistry.availableCheats(session).isEmpty(), "empty list fail-closed");
        check(CheatSessionRegistry.enabledCheatIds(session).isEmpty(), "empty set fail-closed");
        check(!CheatSessionRegistry.setCheatEnabled(session, "live1", true), "toggle refused with nothing registered");
        check(CheatSessionRegistry.availableCheats(null).isEmpty(), "null session tolerated");
    }

    private static void decoration() {
        CheatSessionRegistry.Binding binding = new CheatSessionRegistry.Binding("ps2 game", rows(),
                new HashSet<>(Arrays.asList("boot1", "ghost")), null, null, DIRECT, null);
        List<Cheat> shown = binding.availableCheats();
        check(shown.size() == 3, "every row listed");
        check(shown.get(0).description.equals("from libretro"), "live row untouched");
        check(shown.get(1).description.equals("pcsx2 • applies on next launch"), "boot row says when");
        check(shown.get(2).description.equals("not applied by the packaged engine yet"), "unsupported row says why");
        check(shown.get(1).id.equals("boot1") && shown.get(1).code.equals("patch=1,EE,1,word,1"), "id and code kept");
        check(binding.enabledCheatIds().equals(new HashSet<>(Arrays.asList("boot1"))), "stale id dropped on restore");
        check(binding.gameKey().equals("ps2 game"), "game key");
    }

    private static void toggling() {
        final AtomicReference<Set<String>> persisted = new AtomicReference<>();
        final AtomicReference<Set<String>> rewritten = new AtomicReference<>();
        final AtomicReference<String> persistedKey = new AtomicReference<>();
        CheatSessionRegistry.Binding binding = new CheatSessionRegistry.Binding("ps2 game", rows(),
                new HashSet<String>(),
                (gameKey, ids) -> { persistedKey.set(gameKey); persisted.set(ids); },
                ids -> rewritten.set(ids), DIRECT, null);
        check(binding.setEnabled("boot1", true), "boot row toggles");
        check(persisted.get().equals(new HashSet<>(Arrays.asList("boot1"))), "selection persisted");
        check(persistedKey.get().equals("ps2 game"), "persisted under the game key");
        check(rewritten.get().equals(new HashSet<>(Arrays.asList("boot1"))), "boot writer re-run");
        check(binding.isEnabled("boot1"), "state reflects the toggle");
        check(binding.setEnabled("live1", true), "live row registered here toggles too");
        check(binding.setEnabled("boot1", false), "toggle off");
        check(persisted.get().equals(new HashSet<>(Arrays.asList("live1"))), "off persisted");
        check(!binding.setEnabled("unsup", true), "unsupported row fails closed");
        check(!binding.isEnabled("unsup"), "unsupported row stays off");
        check(!binding.setEnabled("missing", true), "unknown id refused");
        check(!binding.setEnabled(null, true) && !binding.setEnabled("", true), "empty id refused");
    }

    private static void failures() {
        final List<String> stages = new ArrayList<>();
        CheatSessionRegistry.FailureListener listener = (stage, failure) -> stages.add(stage);
        // A rewriter that throws is reported; the selection and persistence stand.
        final AtomicReference<Set<String>> persisted = new AtomicReference<>();
        CheatSessionRegistry.Binding binding = new CheatSessionRegistry.Binding("k", rows(), null,
                (gameKey, ids) -> persisted.set(ids),
                ids -> { throw new java.io.IOException("disk full"); }, DIRECT, listener);
        check(binding.setEnabled("boot1", true), "toggle accepted");
        check(stages.equals(Arrays.asList("boot-writer")), "boot writer failure reported: " + stages);
        check(persisted.get().contains("boot1") && binding.isEnabled("boot1"), "selection kept");
        // A queue that rejects rolls the selection back and answers false.
        Executor rejecting = new Executor() {
            @Override public void execute(Runnable task) { throw new RejectedExecutionException("closed"); }
        };
        CheatSessionRegistry.Binding closed = new CheatSessionRegistry.Binding("k", rows(), null,
                null, null, rejecting, listener);
        check(!closed.setEnabled("boot1", true), "rejected queue fails closed");
        check(!closed.isEnabled("boot1"), "rolled back");
        check(stages.contains("queue"), "queue failure reported");
    }

    private static void registryLifecycle() {
        Object session = new Object();
        CheatSessionRegistry.Binding binding = new CheatSessionRegistry.Binding("k", rows(),
                new HashSet<>(Arrays.asList("boot1")), null, null, DIRECT, null);
        CheatSessionRegistry.register(session, binding);
        check(CheatSessionRegistry.forSession(session) == binding, "registered");
        check(CheatSessionRegistry.availableCheats(session).size() == 3, "defaults read the binding");
        check(CheatSessionRegistry.enabledCheatIds(session).contains("boot1"), "enabled through the registry");
        check(CheatSessionRegistry.setCheatEnabled(session, "boot1", false), "toggle through the registry");
        check(!CheatSessionRegistry.enabledCheatIds(session).contains("boot1"), "registry sees the change");
        Object other = new Object();
        check(CheatSessionRegistry.availableCheats(other).isEmpty(), "another session is separate");
        CheatSessionRegistry.unregister(session);
        check(CheatSessionRegistry.forSession(session) == null, "unregistered");
        check(!CheatSessionRegistry.setCheatEnabled(session, "boot1", true), "fail-closed after unregister");
        CheatSessionRegistry.register(null, binding);
        CheatSessionRegistry.register(session, null);
        check(CheatSessionRegistry.forSession(session) == null, "null registrations ignored");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
