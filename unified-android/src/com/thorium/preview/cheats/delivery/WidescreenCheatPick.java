package com.thorium.preview.cheats.delivery;

import com.thorium.lucent.cheats.CheatSelection;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * Pure decision logic behind {@link WidescreenCheatOverlay}: which single
 * widescreen row to turn on for a game whose catalogue offers more than one.
 *
 * <p>A merged catalogue routinely carries several widescreen variants of the
 * same fix for one game (e.g. Dolphin's bundled catalogue lists "Normal
 * HUD" / "Centered HUD" / "Stretched HUD" cuts of the same 16:9 patch, or two
 * unrelated sources each contribute their own). They are mutually exclusive:
 * turning all of them on at once makes conflicting codes write the same
 * addresses every frame. Exactly one is chosen; the rest are left exactly as
 * they were (a variant the player enabled by hand is never touched).
 *
 * <p>Kept apart from {@link WidescreenCheatOverlay} (which needs org.json and
 * the Android {@code CheatStore}) so the choice itself stays provable on the
 * host with nothing but {@link DeliveryCheat} and {@link CheatSelection}.
 */
final class WidescreenCheatPick {

    private WidescreenCheatPick() {}

    /** The rows this overlay is allowed to consider turning on. */
    static List<DeliveryCheat> candidates(List<DeliveryCheat> rows) {
        List<DeliveryCheat> candidates = new ArrayList<>();
        if (rows != null)
            for (DeliveryCheat row : rows)
                if (row != null && row.isWidescreen() && !row.isUnsupported()) candidates.add(row);
        return candidates;
    }

    /**
     * The one id to enable, or {@code null} when the catalogue has no
     * widescreen row at all.
     *
     * <p>Preference order keeps the choice stable across launches rather
     * than picking whichever the catalogue lists first each time:
     * <ol>
     * <li>the variant this overlay itself chose and enabled last time
     *     ({@code previouslyAuto}), if the catalogue still offers it;</li>
     * <li>a variant already switched on -- by the player, or by an older
     *     build of this overlay that predates single-pick and left more
     *     than one on;</li>
     * <li>otherwise the first candidate in catalogue order.</li>
     * </ol>
     */
    static String choose(List<DeliveryCheat> candidates, Set<String> previouslyAuto,
                         CheatSelection selection) {
        if (candidates.isEmpty()) return null;
        for (DeliveryCheat row : candidates)
            if (previouslyAuto.contains(row.cheat.id)) return row.cheat.id;
        for (DeliveryCheat row : candidates)
            if (selection.isEnabled(row.cheat.id)) return row.cheat.id;
        return candidates.get(0).cheat.id;
    }

    /**
     * Whether any widescreen row is enabled -- what
     * {@code WidescreenHackPolicy.prepareLaunch}'s
     * {@code perGameWidescreenCodeSelected} parameter needs, so the core's
     * own generic projection hack is left off for a title whose own 16:9
     * code is already doing the job (design section 7's "else" clause).
     */
    static boolean anyEnabled(List<DeliveryCheat> rows, Set<String> enabledIds) {
        if (rows == null || enabledIds == null || enabledIds.isEmpty()) return false;
        for (DeliveryCheat row : rows)
            if (row != null && row.isWidescreen() && enabledIds.contains(row.cheat.id)) return true;
        return false;
    }
}
