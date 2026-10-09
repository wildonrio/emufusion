package com.thorium.preview.cheats.sources;

import com.thorium.lucent.cheats.Cheat;
import com.thorium.lucent.cheats.CheatDatabase;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** The per-game file round-trips, survives corruption, and keeps ids stable; plus the source switches. */
public final class DownloadedCheatFileTest {
    public static void main(String[] args) throws Exception {
        File dir = Files.createTempDirectory("lucent-downloaded").toFile();
        codec(dir);
        ids();
        pathDerivation(dir);
        registry(dir);
        fetcherPolicy();
        System.out.println("DownloadedCheatFileTest passed");
    }

    private static void codec(File dir) throws Exception {
        DownloadedCheatDocument document = new DownloadedCheatDocument("ps2", "Shadow of the Colossus");
        document.identity.put("serial", "SCUS-97472");
        document.identity.put("crc", "7D6F5B0E");
        String id = CheatIdFactory.id("pcsx2-patches", "ps2", "patch=1,EE,2034C7A0,extended,3F400000");
        document.add(new DownloadedCheat(new Cheat(id, "Widescreen 16:9", "PCSX2 patches • SCUS-97472_7D6F5B0E.pnach",
                "patch=1,EE,2034C7A0,extended,3F400000"), "pcsx2-patches", "boot", Arrays.asList("Widescreen", " widescreen-16:9 "), "pnach"));
        check(!document.add(new DownloadedCheat(new Cheat(id, "dup", "", "x"), "pcsx2-patches", "boot", null, "pnach")),
                "duplicate id rejected");
        document.add(new DownloadedCheat(new Cheat("libretro-abc", "Live row", "Libretro Database • x", "8000 0001"),
                "libretro-database", "live", null, "retroarch-cht"));
        document.add(new DownloadedCheat(new Cheat("fbneo-cheats-1", "Arcade row", "", "1 \"Enabled\", 0, 0x1, 0x2"),
                "fbneo-cheats", "weird", null, "fbneo-ini"));
        File file = DownloadedCheatCodec.pathFor(dir, "ps2", "Shadow of the Colossus (USA).iso");
        DownloadedCheatCodec.write(file, document);
        check(file.isFile() && !new File(file.getAbsolutePath() + ".part").exists(), "atomic write left no .part");

        List<DownloadedCheat> detailed = DownloadedCheatCodec.readDetailed(file);
        check(detailed.size() == 3, "three rows read back: " + detailed.size());
        check(detailed.get(0).tags.equals(Arrays.asList("widescreen", "widescreen-16:9")), "tags normalised: " + detailed.get(0).tags);
        check("boot".equals(detailed.get(0).delivery) && "pnach".equals(detailed.get(0).engineFormat), "delivery/format");
        check("unsupported".equals(detailed.get(2).delivery), "unknown delivery reads as unsupported");

        List<Cheat> plain = DownloadedCheatCodec.read(file);
        check(plain.get(0).description.contains(DownloadedCheatCodec.BOOT_NOTE), "boot rows say so: " + plain.get(0).description);
        check(!plain.get(1).description.contains(DownloadedCheatCodec.BOOT_NOTE), "live rows unchanged");
        check(plain.get(2).description.contains(DownloadedCheatCodec.UNSUPPORTED_NOTE), "unsupported rows say so");
        check(plain.get(0).id.equals(id), "id preserved");

        Map<String, String> identity = DownloadedCheatCodec.readIdentity(file);
        check("SCUS-97472".equals(identity.get("serial")) && "7D6F5B0E".equals(identity.get("crc")), "identity: " + identity);

        String json = new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
        check(json.contains("\"schemaVersion\":2") && json.contains("\"games\":[{\"system\":\"ps2\""), "CheatCatalog-compatible shape: " + json);

        try (FileOutputStream out = new FileOutputStream(file)) { out.write("{not json".getBytes(StandardCharsets.UTF_8)); }
        check(DownloadedCheatCodec.read(file).isEmpty() && DownloadedCheatCodec.readIdentity(file).isEmpty(), "corruption reads as empty");
        check(DownloadedCheatCodec.read(new File(dir, "missing.json")).isEmpty(), "absence reads as empty");
        check(DownloadedCheatCodec.fromJson("{\"games\":[{\"cheats\":[{\"id\":\"\",\"code\":\"x\"},{\"id\":\"ok\",\"code\":\"y\"}]}]}").size() == 1,
                "one bad row does not cost the others");
    }

    private static void ids() {
        String a = CheatIdFactory.id("libretro", "nes", "AATOZE");
        String b = CheatIdFactory.id("libretro", "nes", "  aatoze ");
        check(a.equals(b) && a.startsWith("libretro-") && a.length() == "libretro-".length() + 24, "id stable across whitespace/case: " + a);
        check(!a.equals(CheatIdFactory.id("libretro", "snes", "AATOZE")), "id depends on the system");
        check(!a.equals(CheatIdFactory.id("duckstation-chtdb", "nes", "AATOZE")), "id depends on the source");
    }

    private static void pathDerivation(File dir) {
        File a = DownloadedCheatCodec.pathFor(dir, "gc", "Zelda (USA).iso");
        File b = DownloadedCheatCodec.pathFor(dir, "gamecube", "zelda");
        check(a.equals(b), "alias system and tagged stem resolve to one file: " + a + " vs " + b);
        check(a.getParentFile().getName().equals("gamecube"), "canonical system directory");
        check(a.getName().equals(CheatDatabase.normalise("Zelda (USA).iso") + ".json"), "normalised stem file name");
        check(DownloadedCheatCodec.pathFor(dir, "", "").getName().equals("untitled.json"), "empty stem fallback");
        File hostile = DownloadedCheatCodec.pathFor(dir, "psx", "../../etc/passwd");
        check(hostile.getName().equals("passwd.json") && hostile.getParentFile().getName().equals("psx")
                && hostile.getParentFile().getParentFile().equals(dir), "no traversal: " + hostile);
    }

    private static void registry(File dir) throws Exception {
        check(CheatSourceRegistry.all().size() >= 17, "table has every design source");
        for (CheatSource source : CheatSourceRegistry.all()) {
            check(!source.bundled && !source.redistribution, source.id + " must not be bundled/redistributed");
            check(source.url.startsWith("https://"), source.id + " https only");
            check(source.auxiliaryUrl.isEmpty() || source.auxiliaryUrl.startsWith("https://"), source.id + " aux https only");
            check(!source.license.isEmpty() && !source.systems.isEmpty(), source.id + " license and systems");
            check(source.maxBytes > 0, source.id + " has a size cap");
        }
        List<CheatSource> n64 = CheatSourceRegistry.forSystem("n64");
        check(n64.size() == 3 && n64.get(0).id.equals(CheatSourceRegistry.LIBRETRO), "n64: libretro first, then mupen and pj64: " + n64);
        check(CheatSourceRegistry.forSystem("ps2").size() == 2, "ps2 two sources");
        check(CheatSourceRegistry.forSystem("switch").size() == 2, "switch two sources");
        check(CheatSourceRegistry.forSystem("xbox").isEmpty(), "unknown system has no sources");
        check(CheatSourceRegistry.byId(CheatSourceRegistry.RC24_GECKO).perGame, "rc24 is per-game");
        check(CheatSourceRegistry.byId(CheatSourceRegistry.LIBRETRO).installedLocally, "libretro is installed, not fetched");

        File prefs = CheatSourceRegistry.preferencesFile(dir);
        check(CheatSourceRegistry.enabled(prefs, CheatSourceRegistry.byId(CheatSourceRegistry.CWCHEAT)), "on by default");
        CheatSourceRegistry.setEnabled(prefs, CheatSourceRegistry.CWCHEAT, false);
        check(!CheatSourceRegistry.enabled(prefs, CheatSourceRegistry.byId(CheatSourceRegistry.CWCHEAT)), "switched off");
        check(CheatSourceRegistry.enabledForSystem(prefs, "psp").size() == 1, "psp keeps libretro only");
        CheatSourceRegistry.setEnabled(prefs, CheatSourceRegistry.CWCHEAT, true);
        check(CheatSourceRegistry.enabledForSystem(prefs, "psp").size() == 2, "switched back on");
        try (FileOutputStream out = new FileOutputStream(prefs)) { out.write("garbage".getBytes(StandardCharsets.UTF_8)); }
        check(CheatSourceRegistry.enabledForSystem(prefs, "psp").size() == 2, "corrupt preference file means no overrides");
        try (FileOutputStream out = new FileOutputStream(prefs)) {
            out.write("{\"disabled\":[\"mame-cheats-spludlow\"]}".getBytes(StandardCharsets.UTF_8));
        }
        check(CheatSourceRegistry.enabledForSystem(prefs, "arcade").size() == 2, "disabled list honoured: "
                + CheatSourceRegistry.enabledForSystem(prefs, "arcade"));
        check(CheatSourceRegistry.describe(prefs).contains("\"enabled\":false"), "describe reports the switch");
    }

    private static void fetcherPolicy() {
        long now = 1_700_000_000_000L;
        check(CheatSourceFetcher.isFresh(now - 1000, now), "just fetched is fresh");
        check(!CheatSourceFetcher.isFresh(now - CheatSourceFetcher.REFRESH_MS - 1, now), "eight days old is stale");
        check(!CheatSourceFetcher.isFresh(0, now), "never fetched is stale");
        check(CheatSourceFetcher.isMissFresh(now - 1000, now), "recent miss memoised");
        CheatSourceFetcher fetcher = new CheatSourceFetcher(new File("/nonexistent/cache"), now);
        check(fetcher.fetch(CheatSourceRegistry.byId(CheatSourceRegistry.CWCHEAT), "http://insecure.example/x") == null, "http refused");
        check(fetcher.fetch(null, "https://example.com/x") == null, "null source refused");

        check("codes.rc24.xyz".equals(CheatSourceFetcher.hostOf("https://codes.rc24.xyz/txt.php?txt=RMCE01")),
                "hostOf: parses the host");
        check(CheatSourceFetcher.hostOf("not a url").isEmpty(), "hostOf: malformed url yields empty");
        check(!CheatSourceFetcher.hostCircuitOpen("codes.rc24.xyz"), "hostCircuitOpen: closed with no recorded failures");
        check(!CheatSourceFetcher.hostCircuitOpen(""), "hostCircuitOpen: empty host never opens");

        // A captive portal answers 200 OK with an HTML login page for any URL;
        // that must never be accepted as the real archive/feed.
        check(!CheatSourceFetcher.isPlausiblePayload("https://example.com/patches.zip",
                "<!DOCTYPE html><html><body>Sign in</body></html>".getBytes(StandardCharsets.UTF_8)),
                "isPlausiblePayload: html doctype rejected");
        check(!CheatSourceFetcher.isPlausiblePayload("https://example.com/data.json",
                "<html><head></head></html>".getBytes(StandardCharsets.UTF_8)),
                "isPlausiblePayload: bare html tag rejected");
        // A URL naming a container must start with that container's magic.
        check(!CheatSourceFetcher.isPlausiblePayload("https://example.com/patches.zip",
                "not a zip".getBytes(StandardCharsets.UTF_8)), "isPlausiblePayload: zip url without zip magic rejected");
        check(CheatSourceFetcher.isPlausiblePayload("https://example.com/patches.zip",
                new byte[] {0x50, 0x4B, 0x03, 0x04}), "isPlausiblePayload: real zip magic accepted");
        check(!CheatSourceFetcher.isPlausiblePayload("https://api.github.com/repos/x/y/contents/3ds.json",
                "oops".getBytes(StandardCharsets.UTF_8)), "isPlausiblePayload: json url without brace/bracket rejected");
        check(CheatSourceFetcher.isPlausiblePayload("https://example.com/3ds.json",
                "  {\"a\":1}".getBytes(StandardCharsets.UTF_8)), "isPlausiblePayload: leading whitespace before json ok");
        // Plain-text/db sources (rc24 txt, cwcheat.db, pnach, yaml, ...) have no
        // fixed magic; only the html sniff applies to them.
        check(CheatSourceFetcher.isPlausiblePayload("https://codes.rc24.xyz/txt.php?txt=RMCE01",
                "RMCE01\nMario Kart Wii\n".getBytes(StandardCharsets.UTF_8)),
                "isPlausiblePayload: unconstrained container accepted");
        check(!CheatSourceFetcher.isPlausiblePayload("https://example.com/x", new byte[0]),
                "isPlausiblePayload: empty body rejected");
    }

    static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
