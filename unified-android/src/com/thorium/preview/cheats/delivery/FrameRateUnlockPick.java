package com.thorium.preview.cheats.delivery;

import com.thorium.emufusion.cheats.CheatSelection;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/** Pure choice behind {@link FrameRateUnlockOverlay}, provable on the host. */
final class FrameRateUnlockPick {
    private FrameRateUnlockPick() {}

    static List<DeliveryCheat> candidates(List<DeliveryCheat> rows) {
        List<DeliveryCheat> candidates = new ArrayList<>();
        if (rows != null)
            for (DeliveryCheat row : rows)
                if (row != null && row.isFrameRateUnlock() && !row.isUnsupported())
                    candidates.add(row);
        // Explicit "60 FPS" first, then named unlocks, then tag-only; stable
        // within a rank so catalogue order still breaks ties.
        candidates.sort((a, b) -> Integer.compare(a.frameRateUnlockRank(), b.frameRateUnlockRank()));
        return candidates;
    }

    /** Previously auto-chosen, else one already on, else catalogue order. */
    static String choose(List<DeliveryCheat> candidates, Set<String> previouslyAuto,
                         CheatSelection selection) {
        return WidescreenCheatPick.choose(candidates, previouslyAuto, selection);
    }
}
