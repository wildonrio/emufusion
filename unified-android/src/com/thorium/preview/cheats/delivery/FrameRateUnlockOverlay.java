package com.thorium.preview.cheats.delivery;

import com.thorium.lucent.cheats.CheatSelection;
import com.thorium.preview.cheats.CheatStore;

import java.io.File;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Turns on one community frame-rate unlock ("60 FPS", Cemu "FPS++", "Unlock
 * framerate") for the game at launch (owner, 2026-10-10: "unlock the frame
 * rate if possible -- always that's the first thing you should do"; frame
 * generation is only for games that stay locked).
 *
 * <p>Same contract as {@link WidescreenCheatOverlay}: exactly one variant is
 * chosen (they write the same addresses), the choice is remembered so it is
 * stable across launches, a code the player enabled by hand is never touched,
 * and turning the feature off retires only what this overlay enabled.
 */
final class FrameRateUnlockOverlay {
    static final String FILE_NAME = "fps-unlock-auto.json";

    private FrameRateUnlockOverlay() {}

    /** @return the enabled ids after the change */
    static Set<String> apply(File cheatDirectory, CheatStore store, String gameKey,
                             List<DeliveryCheat> rows, CheatSelection selection, boolean on) {
        File record = new File(cheatDirectory, FILE_NAME);
        Set<String> previouslyAuto = WidescreenCheatOverlay.readRecord(record, gameKey);
        Set<String> auto = new LinkedHashSet<>();
        boolean changed = false;
        String chosen = on ? FrameRateUnlockPick.choose(
                FrameRateUnlockPick.candidates(rows), previouslyAuto, selection) : null;
        if (chosen != null) {
            if (!selection.isEnabled(chosen)) {
                selection.setEnabled(chosen, true);
                changed = true;
            }
            auto.add(chosen);
        }
        for (String id : previouslyAuto) {
            if (id.equals(chosen)) continue;
            if (selection.isEnabled(id)) {
                selection.setEnabled(id, false);
                changed = true;
            }
        }
        if (changed) store.save(gameKey, selection.enabledIds());
        if (!auto.equals(previouslyAuto)) WidescreenCheatOverlay.writeRecord(record, gameKey, auto);
        return selection.enabledIds();
    }
}
