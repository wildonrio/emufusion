package com.thorium.preview.cheats.delivery;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatSelection;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Host proof of {@link WidescreenCheatPick}: which single widescreen row a
 * catalogue with several mutually-exclusive variants should turn on.
 */
public final class WidescreenCheatPickTest {

    public static void main(String[] args) {
        candidatesFilter();
        firstInOrderByDefault();
        stableAcrossRelaunch();
        respectsAlreadyEnabled();
        noWidescreenRowAtAll();
        anyEnabled();
        System.out.println("Widescreen cheat pick tests passed");
    }

    private static DeliveryCheat row(String id, String name, String delivery, String... tags) {
        return new DeliveryCheat(new Cheat(id, name, "", "0"), "test", delivery, Arrays.asList(tags), "");
    }

    private static void candidatesFilter() {
        List<DeliveryCheat> rows = Arrays.asList(
                row("a", "16:9 Normal HUD", "live"),
                row("b", "Health", "live"),
                row("c", "Widescreen (2)", "unsupported"),
                row("d", "Camera", "live", "widescreen"));
        List<DeliveryCheat> candidates = WidescreenCheatPick.candidates(rows);
        check(candidates.size() == 2, "unsupported and non-widescreen rows excluded: " + candidates.size());
        check(candidates.get(0).cheat.id.equals("a") && candidates.get(1).cheat.id.equals("d"),
                "candidates keep catalogue order");
    }

    // Metroid Prime 2-style catalogue: several mutually exclusive HUD variants.
    private static List<DeliveryCheat> variants() {
        List<DeliveryCheat> rows = new ArrayList<>();
        rows.add(row("normal", "16:9 Aspect Ratio Fix - Normal HUD", "live"));
        rows.add(row("centered", "16:9 Aspect Ratio Fix - Centered HUD", "live"));
        rows.add(row("stretched", "16:9 Aspect Ratio Fix - Stretched HUD", "live"));
        return rows;
    }

    private static void firstInOrderByDefault() {
        List<DeliveryCheat> candidates = WidescreenCheatPick.candidates(variants());
        CheatSelection selection = new CheatSelection(plain(candidates));
        String chosen = WidescreenCheatPick.choose(candidates, Collections.<String>emptySet(), selection);
        check("normal".equals(chosen), "first candidate chosen with no history: " + chosen);
    }

    private static void stableAcrossRelaunch() {
        List<DeliveryCheat> candidates = WidescreenCheatPick.candidates(variants());
        CheatSelection selection = new CheatSelection(plain(candidates));
        // A previous launch picked "centered" and enabled it.
        selection.setEnabled("centered", true);
        Set<String> previouslyAuto = new LinkedHashSet<>(Arrays.asList("centered"));
        String chosen = WidescreenCheatPick.choose(candidates, previouslyAuto, selection);
        check("centered".equals(chosen), "the overlay's own earlier pick sticks: " + chosen);
    }

    private static void respectsAlreadyEnabled() {
        List<DeliveryCheat> candidates = WidescreenCheatPick.candidates(variants());
        CheatSelection selection = new CheatSelection(plain(candidates));
        // No record of this overlay having picked anything, but the player
        // (or an older build predating single-pick) already has one on.
        selection.setEnabled("stretched", true);
        String chosen = WidescreenCheatPick.choose(candidates, Collections.<String>emptySet(), selection);
        check("stretched".equals(chosen), "a variant already on beats catalogue order: " + chosen);
    }

    private static void noWidescreenRowAtAll() {
        List<DeliveryCheat> rows = Arrays.asList(row("a", "Infinite Health", "live"));
        List<DeliveryCheat> candidates = WidescreenCheatPick.candidates(rows);
        CheatSelection selection = new CheatSelection(plain(candidates));
        check(WidescreenCheatPick.choose(candidates, Collections.<String>emptySet(), selection) == null,
                "nothing to choose when the catalogue has no widescreen row");
    }

    private static void anyEnabled() {
        List<DeliveryCheat> rows = variants();
        check(!WidescreenCheatPick.anyEnabled(rows, Collections.<String>emptySet()), "nothing enabled");
        check(WidescreenCheatPick.anyEnabled(rows, new LinkedHashSet<>(Arrays.asList("centered"))),
                "one widescreen row enabled");
        check(!WidescreenCheatPick.anyEnabled(rows, new LinkedHashSet<>(Arrays.asList("no-such-id"))),
                "an id that is not a widescreen row does not count");
    }

    private static List<Cheat> plain(List<DeliveryCheat> rows) {
        List<Cheat> plain = new ArrayList<>();
        for (DeliveryCheat row : rows) plain.add(row.cheat);
        return plain;
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
