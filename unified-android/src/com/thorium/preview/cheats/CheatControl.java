package com.thorium.preview.cheats;

import android.content.Context;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatDatabase;
import com.thorium.lucent.cheats.CheatSelection;
import com.thorium.lucent.metadata.EngineSystemIdResolver;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import com.thorium.preview.cheats.delivery.CheatDelivery;
import com.thorium.preview.cheats.delivery.DeliveryCheat;
import com.thorium.preview.cheats.sources.DownloadedCheat;
import com.thorium.preview.cheats.sources.DownloadedCheatFile;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The one place that knows where cheat state lives, and how the library reads
 * and writes it for a game that is not running.
 *
 * <p>The paths are here rather than at each call site because the running
 * engine and the library's control plane address the same selection file. Two
 * copies of the literal would drift the moment one of them moved, and the only
 * symptom would be a toggle that silently stops surviving relaunch.
 */
public final class CheatControl {

    private static final String DIRECTORY = "cheats";
    private static final String SELECTION_FILE = "selection.json";

    private CheatControl() {}

    /** Holds the user's database override and the saved selection. */
    public static File directory(Context context) {
        return new File(context.getApplicationContext().getFilesDir(), DIRECTORY);
    }

    public static File downloadedArchive(Context context) {
        return CheatArchive.file(directory(context));
    }

    public static CheatStore store(Context context) {
        return new CheatStore(new File(directory(context), SELECTION_FILE));
    }

    /**
     * A game's cheats and their current on/off state.
     *
     * <p>{@code system} is accepted in the frontend's own vocabulary and
     * canonicalised here: the library knows a game by its folder
     * ("megadrive"), while the selection is keyed by the engine-facing id.
     *
     * @return {@code {"ok":true,"cheats":[..]}}; an empty array for a game the
     *         catalogue does not carry, which is what makes the caller able to
     *         hide the entry rather than open an empty list
     */
    public static String listJson(Context context, String system, String title) {
        String canonicalSystem = EngineSystemIdResolver.canonical(system);
        CheatStore store = store(context);
        CheatSelection selection = selectionFor(context, store, canonicalSystem, title, null);
        Map<String, DownloadedCheat> downloaded = downloadedById(context, canonicalSystem, title, null);
        String systemDelivery = CheatDelivery.defaultForSystem(canonicalSystem);
        try {
            JSONArray entries = new JSONArray();
            for (Cheat cheat : selection.available()) {
                JSONObject item = new JSONObject();
                item.put("id", cheat.id);
                item.put("name", cheat.name);
                item.put("description", cheat.description);
                item.put("enabled", selection.isEnabled(cheat.id));
                // Additive (2026-09-06): where the row came from and how the
                // system's internal route delivers it. The engine is not
                // chosen yet at this point, so the delivery is the system's
                // default; the running session reports the exact one.
                DownloadedCheat row = downloaded.get(cheat.id);
                item.put("source", row != null && row.source != null && !row.source.isEmpty()
                        ? row.source : sourceFromId(cheat.id));
                String claimed = row == null ? "" : row.delivery;
                item.put("delivery", claimed == null || claimed.isEmpty() ? systemDelivery
                        : DeliveryCheat.BOOT.equals(claimed) && DeliveryCheat.LIVE.equals(systemDelivery)
                        ? DeliveryCheat.BOOT : claimed);
                entries.put(item);
            }
            JSONObject response = new JSONObject();
            response.put("ok", true);
            response.put("system", canonicalSystem);
            response.put("title", title == null ? "" : title);
            response.put("count", entries.length());
            response.put("cheats", entries);
            return response.toString();
        } catch (JSONException unexpected) {
            return "{\"ok\":false,\"error\":\"cheat list could not be encoded\"}";
        }
    }

    /**
     * Switches one cheat on or off for a game that is not running; the running
     * engine owns its own selection and is toggled through the session.
     *
     * <p>Rejects an id this game's catalogue does not offer rather than
     * recording it: a stored id no cheat matches would be invisible in every
     * UI while still occupying the saved selection.
     *
     * @return false when this game has no such cheat, so the caller can answer
     *         404 rather than silently accepting a write it did not perform
     */
    public static boolean setEnabled(Context context, String system, String title,
                                     String cheatId, boolean enabled) {
        String canonicalSystem = EngineSystemIdResolver.canonical(system);
        CheatStore store = store(context);
        CheatSelection selection = selectionFor(context, store, canonicalSystem, title, null);
        if (!offers(selection.available(), cheatId)) return false;
        selection.setEnabled(cheatId, enabled);
        Set<String> enabledIds = selection.enabledIds();
        store.save(CheatDatabase.key(canonicalSystem, title), enabledIds);
        return true;
    }

    private static CheatSelection selectionFor(Context context, CheatStore store,
                                               String canonicalSystem, String title) {
        return selectionFor(context, store, canonicalSystem, title, null);
    }

    /** Selection used by a running game; its content filename retains region tags. */
    public static CheatSelection selectionForGame(Context context, String system,
                                                   String title, String contentName) {
        return selectionForGame(context, system, title, contentName, "");
    }

    public static CheatSelection selectionForGame(Context context, String system,
                                                   String title, String contentName,
                                                   String contentIdentity) {
        String canonicalSystem = EngineSystemIdResolver.canonical(system);
        CheatStore store = store(context);
        List<Cheat> available = CheatCatalog.forGame(context, directory(context),
                canonicalSystem, title, contentName, contentIdentity);
        CheatSelection selection = new CheatSelection(available);
        if (!available.isEmpty()) selection.restore(store.enabledFor(
                CheatDatabase.key(canonicalSystem, title)));
        return selection;
    }

    private static CheatSelection selectionFor(Context context, CheatStore store,
                                               String canonicalSystem, String title,
                                               String contentName) {
        List<Cheat> available = CheatCatalog.forGame(context, directory(context),
                canonicalSystem, title, contentName);
        CheatSelection selection = new CheatSelection(available);
        if (!available.isEmpty())
            selection.restore(store.enabledFor(
                    CheatDatabase.key(canonicalSystem, title)));
        return selection;
    }

    private static boolean offers(List<Cheat> available, String cheatId) {
        if (cheatId == null || cheatId.isEmpty()) return false;
        for (Cheat cheat : available) if (cheat.id.equals(cheatId)) return true;
        return false;
    }

    // ---- Delivery layer (2026-09-06): what CheatLaunchHooks needs per launch.

    /** A launch's cheats: the plain selection plus each row's provenance and delivery. */
    public static final class GameCheats {
        public final String gameKey;
        public final CheatSelection selection;
        /** Parallel to {@code selection.available()}, delivery resolved for the engine. */
        public final List<DeliveryCheat> rows;
        /** Identity the downloader recorded (serial, crc, titleId, buildIds, ...). */
        public final Map<String, String> identity;

        GameCheats(String gameKey, CheatSelection selection, List<DeliveryCheat> rows,
                   Map<String, String> identity) {
            this.gameKey = gameKey;
            this.selection = selection;
            this.rows = Collections.unmodifiableList(rows);
            this.identity = Collections.unmodifiableMap(identity);
        }
    }

    /**
     * The aggregate catalogue for a launch, each row annotated with the
     * downloader's provenance when it has one and with the delivery the
     * given engine really provides (see {@link CheatDelivery#resolve}).
     */
    public static GameCheats gameCheatsFor(Context context, String system, String title,
                                           String contentName, String contentIdentity,
                                           String engineId) {
        String canonicalSystem = EngineSystemIdResolver.canonical(system);
        CheatSelection selection = selectionForGame(context, canonicalSystem, title,
                contentName, contentIdentity);
        Map<String, DownloadedCheat> downloaded =
                downloadedById(context, canonicalSystem, title, contentName);
        List<DeliveryCheat> rows = new ArrayList<>();
        for (Cheat cheat : selection.available()) {
            DownloadedCheat row = downloaded.get(cheat.id);
            String source = row != null && row.source != null && !row.source.isEmpty()
                    ? row.source : sourceFromId(cheat.id);
            String delivery = CheatDelivery.resolve(engineId, row == null ? "" : row.delivery);
            rows.add(new DeliveryCheat(cheat, source, delivery,
                    row == null ? null : row.tags, row == null ? "" : row.engineFormat));
        }
        return new GameCheats(CheatDatabase.key(canonicalSystem, title), selection, rows,
                downloadedIdentityFor(context, canonicalSystem, title, contentName));
    }

    /** The downloaded per-game rows by id; empty when the update never fetched any. */
    public static Map<String, DownloadedCheat> downloadedById(Context context, String system,
                                                              String title, String contentName) {
        Map<String, DownloadedCheat> byId = new HashMap<>();
        for (DownloadedCheat row : downloadedRowsFor(context, system, title, contentName))
            if (row != null && row.cheat != null && !byId.containsKey(row.cheat.id))
                byId.put(row.cheat.id, row);
        return byId;
    }

    /** Detailed downloaded rows, trying the content stem when the title file is absent. */
    public static List<DownloadedCheat> downloadedRowsFor(Context context, String system,
                                                          String title, String contentName) {
        if (context == null) return Collections.emptyList();
        try {
            File file = downloadedFileFor(context, system, title, contentName);
            if (file == null) return Collections.emptyList();
            List<DownloadedCheat> rows = DownloadedCheatFile.readDetailed(file);
            return rows == null ? Collections.<DownloadedCheat>emptyList() : rows;
        } catch (RuntimeException unreadable) {
            return Collections.emptyList();
        }
    }

    public static Map<String, String> downloadedIdentityFor(Context context, String system,
                                                            String title, String contentName) {
        if (context == null) return Collections.emptyMap();
        try {
            File file = downloadedFileFor(context, system, title, contentName);
            if (file == null) return Collections.emptyMap();
            Map<String, String> identity = DownloadedCheatFile.readIdentity(file);
            return identity == null ? Collections.<String, String>emptyMap() : identity;
        } catch (RuntimeException unreadable) {
            return Collections.emptyMap();
        }
    }

    private static File downloadedFileFor(Context context, String system, String title,
                                          String contentName) {
        String canonicalSystem = EngineSystemIdResolver.canonical(system);
        File byTitle = title == null || title.isEmpty() ? null
                : DownloadedCheatFile.pathFor(context, canonicalSystem, title);
        if (byTitle != null && byTitle.isFile()) return byTitle;
        if (contentName != null && !contentName.isEmpty()) {
            File byStem = DownloadedCheatFile.pathFor(context, canonicalSystem, contentName);
            if (byStem.isFile()) return byStem;
        }
        return byTitle;
    }

    /** Provenance for rows that predate the downloader, from their id prefix. */
    static String sourceFromId(String id) {
        if (id == null) return "bundled";
        if (id.startsWith("dolphin-")) return "dolphin-gamesettings";
        if (id.startsWith("libretro-")) return "libretro-database";
        return "bundled";
    }
}
