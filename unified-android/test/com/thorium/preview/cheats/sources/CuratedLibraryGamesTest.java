package com.thorium.preview.cheats.sources;

import java.io.File;
import java.util.List;

/** Hand-written Pegasus metadata yields every listed game with its system and title. */
public final class CuratedLibraryGamesTest {
    public static void main(String[] args) {
        String text = "collection: Sony PlayStation 2\n"
                + "shortname: playstation2\n"
                + "launch: am start -a com.thorium.preview.LAUNCH_INTERNAL_GAME --es path \"{file.path}\" --es system ps2 --es engine_id armsx2\n"
                + "files:\n"
                + "  /storage/emulated/0/Games/ps2/God of War.iso\n"
                + "  /storage/emulated/0/Games/ps2/Katamari Damacy/Katamari_Damacy.iso\n"
                + "  relative/Sly 2.iso\n"
                + "\n"
                + "game: God of War\n"
                + "sort-by: god of war\n"
                + "file: /storage/emulated/0/Games/ps2/God of War.iso\n"
                + "description: A long\n"
                + "  multi-line text: with colons\n"
                + "\n"
                + "collection: Super Nintendo\n"
                + "shortname: snes\n"
                + "files:\n"
                + "  /storage/emulated/0/Games/snes/Chrono Trigger (USA).sfc\n"
                + "game: Super Metroid\n"
                + "files:\n"
                + "  /storage/emulated/0/Games/snes/Super Metroid (USA).sfc\n"
                + "collection: Web\n"
                + "files:\n"
                + "  https://example.invalid/x.html\n";
        List<CuratedLibraryGames.Game> games = CuratedLibraryGames.parse(text, new File("/meta"));
        check(games.size() == 5, "five local games: " + games.size());
        check(games.get(0).system.equals("ps2"), "system from the launch line beats shortname");
        check(games.get(0).title.equals("God of War"), "game block title: " + games.get(0).title);
        check(games.get(1).title.equals("Katamari_Damacy"), "stem when no game block: " + games.get(1).title);
        check(games.get(2).file.getPath().equals(new File("/meta", "relative/Sly 2.iso").getPath()),
                "relative path resolved against the metadata directory");
        check(games.get(3).system.equals("snes") && games.get(3).title.equals("Chrono Trigger (USA)"),
                "shortname when no launch line: " + games.get(3).system);
        check(games.get(4).title.equals("Super Metroid") && games.get(4).system.equals("snes"),
                "game block with files: list keeps its collection");
        System.out.println("Curated library games tests passed");
    }

    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
}
