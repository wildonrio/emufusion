package com.thorium.preview.cheats.delivery;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatSelection;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.WeakHashMap;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadFactory;

/**
 * The cheats attached to each running session, for engines that have no
 * live cheat bridge of their own.
 *
 * <p>{@code EngineSession}'s default {@code availableCheats /
 * enabledCheatIds / setCheatEnabled} consult this registry, so the pause
 * menu and the lower-display panel light up for every engine. A session
 * that overrides those methods (the live libretro sessions) never reaches
 * the registry, which is exactly right: their own selection is the truth.
 *
 * <p>Keyed by session identity through a weak map, so a session that is
 * released without an explicit {@link #unregister} does not pin its
 * catalogue in memory. Thread-safe: bindings are read from the UI thread and
 * written from the delivery thread.
 */
public final class CheatSessionRegistry {

    /** Records a selection change; on Android this is the CheatStore. */
    public interface Persister {
        void save(String gameKey, Set<String> enabledIds);
    }

    /** Re-runs the engine's boot writer after a toggle. */
    public interface BootRewriter {
        void rewrite(Set<String> enabledIds) throws Exception;
    }

    /** Where failures go; on Android this is Log.w. */
    public interface FailureListener {
        void onFailure(String stage, Throwable failure);
    }

    /** One session's cheats: the rows, the selection, and how a change is kept. */
    public static final class Binding {
        private final String gameKey;
        private final List<DeliveryCheat> rows;
        private final List<Cheat> display;
        private final CheatSelection selection;
        private final Persister persister;
        private final BootRewriter rewriter;
        private final Executor executor;
        private final FailureListener failures;

        public Binding(String gameKey, List<DeliveryCheat> rows, Set<String> enabledIds,
                       Persister persister, BootRewriter rewriter, Executor executor,
                       FailureListener failures) {
            this.gameKey = gameKey == null ? "" : gameKey;
            this.rows = Collections.unmodifiableList(
                    rows == null ? new ArrayList<DeliveryCheat>() : new ArrayList<>(rows));
            List<Cheat> plain = new ArrayList<>();
            List<Cheat> decorated = new ArrayList<>();
            for (DeliveryCheat row : this.rows) {
                plain.add(row.cheat);
                decorated.add(row.displayCheat());
            }
            this.display = Collections.unmodifiableList(decorated);
            this.selection = new CheatSelection(plain);
            this.selection.restore(enabledIds);
            this.persister = persister;
            this.rewriter = rewriter;
            this.executor = executor == null ? sharedExecutor() : executor;
            this.failures = failures;
        }

        public String gameKey() { return gameKey; }

        public List<DeliveryCheat> rows() { return rows; }

        /** The catalogue as the panel lists it; boot rows carry their note. */
        public List<Cheat> availableCheats() { return display; }

        public Set<String> enabledCheatIds() {
            synchronized (this) { return selection.enabledIds(); }
        }

        public boolean isEnabled(String cheatId) {
            synchronized (this) { return selection.isEnabled(cheatId); }
        }

        /**
         * Flips one row and keeps the choice: the selection file first, the
         * engine's boot file second, both off the calling thread.
         *
         * <p>Fails closed on a row the engine cannot consume, so the switch
         * never moves for a cheat that would do nothing.
         */
        public boolean setEnabled(String cheatId, boolean enabled) {
            DeliveryCheat row = rowFor(cheatId);
            if (row == null || row.isUnsupported()) return false;
            final Set<String> ids;
            synchronized (this) {
                selection.setEnabled(cheatId, enabled);
                ids = selection.enabledIds();
            }
            try {
                executor.execute(() -> keep(ids));
            } catch (RejectedExecutionException rejected) {
                synchronized (this) { selection.setEnabled(cheatId, !enabled); }
                report("queue", rejected);
                return false;
            }
            return true;
        }

        private void keep(Set<String> ids) {
            if (persister != null) {
                try { persister.save(gameKey, ids); }
                catch (Throwable failure) { report("persist", failure); }
            }
            if (rewriter != null) {
                try { rewriter.rewrite(ids); }
                catch (Throwable failure) { report("boot-writer", failure); }
            }
        }

        private DeliveryCheat rowFor(String cheatId) {
            if (cheatId == null || cheatId.isEmpty()) return null;
            for (DeliveryCheat row : rows) if (row.cheat.id.equals(cheatId)) return row;
            return null;
        }

        private void report(String stage, Throwable failure) {
            if (failures != null) failures.onFailure(stage, failure);
        }
    }

    private static final Map<Object, Binding> BINDINGS =
            Collections.synchronizedMap(new WeakHashMap<Object, Binding>());
    private static volatile Executor shared;

    private CheatSessionRegistry() {}

    private static Executor sharedExecutor() {
        Executor current = shared;
        if (current == null) {
            synchronized (CheatSessionRegistry.class) {
                if (shared == null) {
                    shared = Executors.newSingleThreadExecutor(new ThreadFactory() {
                        @Override public Thread newThread(Runnable task) {
                            Thread thread = new Thread(task, "lucent-cheat-delivery");
                            thread.setDaemon(true);
                            return thread;
                        }
                    });
                }
                current = shared;
            }
        }
        return current;
    }

    /** Attaches a binding to a session; a later registration replaces an earlier one. */
    public static void register(Object session, Binding binding) {
        if (session == null || binding == null) return;
        BINDINGS.put(session, binding);
    }

    public static void unregister(Object session) {
        if (session != null) BINDINGS.remove(session);
    }

    /** The binding for a session, or null when nothing was registered for it. */
    public static Binding forSession(Object session) {
        return session == null ? null : BINDINGS.get(session);
    }

    /** {@code EngineSession.availableCheats} default: empty until a binding exists. */
    public static List<Cheat> availableCheats(Object session) {
        Binding binding = forSession(session);
        return binding == null ? Collections.<Cheat>emptyList() : binding.availableCheats();
    }

    /** {@code EngineSession.enabledCheatIds} default. */
    public static Set<String> enabledCheatIds(Object session) {
        Binding binding = forSession(session);
        return binding == null ? Collections.<String>emptySet() : binding.enabledCheatIds();
    }

    /** {@code EngineSession.setCheatEnabled} default: false with nothing registered. */
    public static boolean setCheatEnabled(Object session, String cheatId, boolean enabled) {
        Binding binding = forSession(session);
        return binding != null && binding.setEnabled(cheatId, enabled);
    }

    /** Registered session count; for tests and diagnostics. */
    public static int size() { return BINDINGS.size(); }
}
