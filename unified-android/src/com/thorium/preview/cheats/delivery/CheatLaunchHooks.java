package com.thorium.preview.cheats.delivery;

import android.content.Context;
import android.util.Log;

import com.thorium.lucent.metadata.EngineSystemIdResolver;
import com.thorium.preview.cheats.CheatControl;
import com.thorium.preview.game.EngineSession;
import com.thorium.preview.game.GameLaunchRequest;
import com.thorium.preview.game.WidescreenHackPolicy;

import java.io.File;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The one hook between a session factory and the cheat delivery layer.
 *
 * <p>{@code InternalEngineBootstrap} wraps every session it creates in
 * {@link #prepare}. The factory runs on the UI thread and is documented as
 * "a map lookup plus a constructor", so {@link #prepare} keeps only the
 * cheap, bounded work on that thread -- resolving the merged catalogue
 * (JSON reads plus, for a couple of systems, one indexed zip-entry lookup),
 * deciding and applying the widescreen-by-cheat pick, writing the
 * core-option override file, and registering the session's rows so the
 * pause menu and lower-display panel light up immediately. That ordering is
 * what design section 7's "else" clause and the pause-menu's one-time
 * {@code availableCheats()} check both need: the override file must not be
 * written before the per-game 16:9 code decision is known, and the registry
 * binding must exist before the session is handed back.
 *
 * <p>Only the parts that can take real time -- waiting for the content hash
 * a per-game save directory is keyed by (up to
 * {@link #CONTENT_HASH_WAIT_MILLIS}), and the boot writer's own file I/O --
 * run on a detached daemon thread, and re-register the binding with a
 * working boot rewriter once that finishes.
 *
 * <p>Nothing here can fail a launch: every stage is caught and logged with
 * a {@code marker=cheat-delivery-*} line.
 */
public final class CheatLaunchHooks {
    private static final String TAG = "EmuFusionCheats";
    /** How long to wait for the session's own content hash before giving up on per-game files. */
    static final long CONTENT_HASH_WAIT_MILLIS = 180_000L;

    private CheatLaunchHooks() {}

    /**
     * Resolves the game's cheats, applies the widescreen-by-cheat policy,
     * registers the session so the pause menu can list and toggle, writes
     * the core-option overrides, and hands the (slower) boot write off to a
     * daemon thread.
     *
     * @return {@code session}, always the same instance
     */
    public static EngineSession prepare(final Context context, final GameLaunchRequest request,
                                        String engineId, final EngineSession session) {
        if (session == null || context == null || request == null) return session;
        final Context app = context.getApplicationContext();
        final String engine = engineId == null || engineId.trim().isEmpty()
                ? request.engineId : engineId.trim();
        final String canonical = EngineSystemIdResolver.canonical(request.systemId);

        CheatControl.GameCheats resolved = null;
        boolean perGameWidescreenCodeSelected = false;
        try {
            resolved = CheatControl.gameCheatsFor(app, request.systemId, request.gameTitle,
                    contentNameOf(request), discIdentityOf(request), engine);
            if (CheatDelivery.widescreenByCheat(canonical)) {
                boolean hackOn = WidescreenHackPolicy.isHackEnabledFor(app, request.systemId);
                Set<String> before = resolved.selection.enabledIds();
                Set<String> after = WidescreenCheatOverlay.apply(CheatControl.directory(app),
                        CheatControl.store(app), resolved.gameKey, resolved.rows,
                        resolved.selection, hackOn);
                perGameWidescreenCodeSelected = WidescreenCheatPick.anyEnabled(resolved.rows, after);
                if (!before.equals(after))
                    Log.i(TAG, "Widescreen cheats " + (hackOn ? "enabled" : "disabled") +
                            " engine=" + engine + " system=" + request.systemId +
                            " before=" + before.size() + " after=" + after.size() +
                            " marker=cheat-delivery-widescreen");
            }
        } catch (Throwable failure) {
            resolved = null;
            Log.w(TAG, "Cheat catalog not resolved engine=" + engine + " system=" +
                    request.systemId + " marker=cheat-delivery-catalog-failure", failure);
        }

        // Written after the widescreen pick above (never before it), so a
        // per-game 16:9 code the pick just enabled is reflected in the same
        // decision as the generic projection-hack override, not raced by it.
        try {
            WidescreenHackPolicy.prepareLaunch(app, request, engine, perGameWidescreenCodeSelected);
        } catch (Throwable failure) {
            Log.w(TAG, "Widescreen overrides not written engine=" + engine +
                    " system=" + request.systemId + " marker=cheat-delivery-overrides-failure", failure);
        }

        if (resolved != null) {
            registerBinding(app, session, engine, resolved, resolved.selection.enabledIds(), null);
            Log.i(TAG, "Cheats registered engine=" + engine + " system=" + request.systemId +
                    " rows=" + resolved.rows.size() + " enabled=" +
                    resolved.selection.enabledIds().size() + " marker=cheat-delivery-registered");
        }

        final CheatControl.GameCheats forWorker = resolved;
        Thread worker = new Thread(() -> {
            try {
                deliverBoot(app, request, engine, canonical, session, forWorker);
            } catch (Throwable failure) {
                Log.w(TAG, "Cheat delivery failed engine=" + engine + " system=" +
                        request.systemId + " marker=cheat-delivery-failure", failure);
            }
        }, "lucent-cheat-prepare");
        worker.setDaemon(true);
        worker.start();
        return session;
    }

    private static String contentNameOf(GameLaunchRequest request) {
        File game = EngineRoots.contentFile(request.contentUri);
        return game == null ? "" : game.getName();
    }

    private static String discIdentityOf(GameLaunchRequest request) {
        File game = EngineRoots.contentFile(request.contentUri);
        return EngineRoots.discIdentity(request.systemId, game);
    }

    /** The boot writer's own (possibly slow) file I/O; the session is already registered. */
    private static void deliverBoot(Context app, GameLaunchRequest request, String engine,
                                    String canonical, EngineSession session,
                                    CheatControl.GameCheats cheats) throws Exception {
        if (cheats == null) return;
        File game = EngineRoots.contentFile(request.contentUri);
        String stem = EngineRoots.contentStem(game);
        String discIdentity = EngineRoots.discIdentity(request.systemId, game);

        final BootCheatWriter writer = BootCheatWriters.forEngine(engine);
        BootCheatRequest bootRequest = null;
        if (writer != null) {
            File engineRoot = EngineRoots.engineRoot(app, engine);
            File saveDirectory = null;
            if (CheatDelivery.needsSaveDirectory(engine)) {
                saveDirectory = EngineRoots.gameSaveDirectory(app, request, engine, game,
                        CONTENT_HASH_WAIT_MILLIS);
                if (saveDirectory == null)
                    Log.w(TAG, "Per-game save directory unknown; boot cheats wait for the next launch engine=" +
                            engine + " system=" + request.systemId + " marker=cheat-delivery-no-save-dir");
            }
            if (!CheatDelivery.needsSaveDirectory(engine) || saveDirectory != null) {
                Map<String, String> identity = new LinkedHashMap<>(cheats.identity);
                if (!discIdentity.isEmpty()) {
                    identity.put("discIdentity", discIdentity);
                    if (!identity.containsKey("gameId")) identity.put("gameId", discIdentity.substring(0, 6));
                }
                bootRequest = new BootCheatRequest(engine, canonical, request.gameTitle, stem,
                        engineRoot, saveDirectory, identity, deliverable(cheats.rows),
                        cheats.selection.enabledIds());
            }
        }
        if (bootRequest == null) return;

        // Re-read the persisted selection rather than reusing cheats.selection's
        // snapshot: the panel could have toggled a cheat against the first,
        // rewriter-less binding while this thread was waiting on the content
        // hash above, and that toggle must not be lost by this re-registration.
        Set<String> current = CheatControl.store(app).enabledFor(cheats.gameKey);
        final BootCheatRequest initial = bootRequest.withEnabledIds(current);
        registerBinding(app, session, engine, cheats, current, ids -> {
            List<File> files = writer.write(initial.withEnabledIds(ids));
            Log.i(TAG, "Boot cheats rewritten engine=" + engine + " files=" + files.size() +
                    " marker=cheat-boot-write");
        });

        List<File> files = writer.write(initial);
        Log.i(TAG, "Boot cheats written engine=" + engine + " system=" + request.systemId +
                " files=" + files.size() + " enabled=" + initial.enabledIds.size() +
                " marker=cheat-boot-write");
    }

    private static void registerBinding(Context app, EngineSession session, String engine,
                                        CheatControl.GameCheats cheats, Set<String> enabledIds,
                                        CheatSessionRegistry.BootRewriter rewriter) {
        CheatSessionRegistry.Binding binding = new CheatSessionRegistry.Binding(cheats.gameKey,
                cheats.rows, enabledIds,
                (gameKey, ids) -> CheatControl.store(app).save(gameKey, ids),
                rewriter, null,
                (stage, failure) -> Log.w(TAG, "Cheat delivery stage failed engine=" + engine +
                        " stage=" + stage + " marker=cheat-delivery-failure", failure));
        CheatSessionRegistry.register(session, binding);
    }

    /** Rows a boot writer may consume: everything the engine can take. */
    private static List<DeliveryCheat> deliverable(List<DeliveryCheat> rows) {
        List<DeliveryCheat> kept = new java.util.ArrayList<>();
        for (DeliveryCheat row : rows) if (!row.isUnsupported()) kept.add(row);
        return kept;
    }
}
