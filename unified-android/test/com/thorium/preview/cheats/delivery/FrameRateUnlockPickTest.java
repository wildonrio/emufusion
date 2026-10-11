package com.thorium.preview.cheats.delivery;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatSelection;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** Host proof of the frame-rate unlock classification and single pick. */
public final class FrameRateUnlockPickTest {
    public static void main(String[] args) {
        names();
        picksOneSupportedUnlock();
        System.out.println("Frame-rate unlock pick tests passed");
    }

    private static DeliveryCheat row(String id, String name, String delivery, String... tags) {
        return new DeliveryCheat(new Cheat(id, name, "", "0"), "test", delivery, Arrays.asList(tags), "");
    }

    private static void names() {
        for (String yes : new String[] {"60 FPS", "60fps (NTSC-U)", "Force 60 FPS", "FPS++",
                "Unlock Framerate", "Unlocked FPS", "Frame rate unlock", "60 Frames Per Second"})
            check(row("x", yes, "live").isFrameRateUnlock(), "should unlock: " + yes);
        for (String no : new String[] {"30 FPS Lock", "Infinite Health", "160 Rings",
                "Widescreen 16:9", "Max 600 coins", "Unlock all levels"})
            check(!row("x", no, "live").isFrameRateUnlock(), "should not unlock: " + no);
        check(row("x", "Camera", "live", "60fps").isFrameRateUnlock(), "tagged 60fps");
        // Sources tag every frame-rate code "60fps" (CWCheat DB, God of War
        // Chains of Olympus): a lower rate or a revert code never qualifies.
        for (String no : new String[] {"30 FPS [Fixed]", "Unlimited FPS [Default]", "20fps lock",
                "FPS Restore", "Normal Frame Rate", "25 FPS (PAL)"})
            check(!row("x", no, "live", "60fps").isFrameRateUnlock(), "tagged but not an unlock: " + no);
        check(row("x", "60 FPS [Fixed]", "live", "60fps").isFrameRateUnlock(), "60 FPS [Fixed]");
        check(row("x", "60 FPS (30 FPS cutscenes)", "live").isFrameRateUnlock(), "60 FPS with a note");
    }

    private static void picksOneSupportedUnlock() {
        List<DeliveryCheat> rows = Arrays.asList(
                row("hp", "Infinite Health", "live"),
                row("u1", "60 FPS (unsupported engine)", "unsupported"),
                row("u2", "60 FPS", "boot"),
                row("u3", "60 FPS (alt)", "boot"));
        List<DeliveryCheat> candidates = FrameRateUnlockPick.candidates(rows);
        check(candidates.size() == 2, "unsupported/non-unlock rows excluded: " + candidates.size());
        List<Cheat> plain = new java.util.ArrayList<>();
        for (DeliveryCheat row : candidates) plain.add(row.cheat);
        CheatSelection selection = new CheatSelection(plain);
        check("u2".equals(FrameRateUnlockPick.choose(candidates,
                Collections.<String>emptySet(), selection)), "first supported unlock");
        check("u3".equals(FrameRateUnlockPick.choose(candidates,
                Collections.singleton("u3"), selection)), "stable across launches");

        // God of War Chains of Olympus: 30 FPS [Fixed] was picked by 3.2.24
        // candidates; the explicit 60 FPS code wins, ahead of tag-only rows,
        // and a remembered 30 FPS pick is no longer a candidate.
        List<DeliveryCheat> gow = Arrays.asList(
                row("fix", "Dark Overlay HackFix", "boot"),
                row("limit", "Frame Limiter Off", "boot", "60fps"),
                row("f30", "30 FPS [Fixed]", "boot", "60fps"),
                row("f60", "60 FPS [Fixed]", "boot", "60fps"),
                row("unl", "Unlimited FPS [Default]", "boot", "60fps"));
        List<DeliveryCheat> gowCandidates = FrameRateUnlockPick.candidates(gow);
        check(gowCandidates.size() == 2 && "f60".equals(gowCandidates.get(0).cheat.id),
                "60 FPS first, 30/default excluded: " + gowCandidates.size());
        List<Cheat> gowPlain = new java.util.ArrayList<>();
        for (DeliveryCheat row : gow) gowPlain.add(row.cheat);
        check("f60".equals(FrameRateUnlockPick.choose(gowCandidates,
                Collections.singleton("f30"), new CheatSelection(gowPlain))), "remembered 30 FPS replaced");
    }

    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
}
