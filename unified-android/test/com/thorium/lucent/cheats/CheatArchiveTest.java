package com.thorium.lucent.cheats;

import com.thorium.preview.cheats.CheatArchive;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Host proof for the downloaded, compressed Libretro cheat catalogue. */
public final class CheatArchiveTest {
    private static final String NES =
            "Nintendo - Nintendo Entertainment System/";
    private static final String PSP =
            "Sony - PlayStation Portable/";
    private static final String SG1000 = "Sega - SG-1000/";
    private static final String MSX = "Microsoft - MSX - MSX2 - MSX2P - MSX Turbo R/";

    public static void main(String[] args) throws Exception {
        if (args.length == 1) {
            File official = new File(args[0]);
            CheatArchive.verify(official);
            List<Cheat> metroid = CheatArchive.forGame(official, "gba",
                    "Metroid Fusion", "Metroid - Fusion (World).gba");
            check(!metroid.isEmpty(), "official archive yielded no Metroid Fusion codes");
            System.out.println("Official cheat archive probe passed: " +
                    metroid.size() + " deduplicated Metroid Fusion codes");
            return;
        }
        File directory = Files.createTempDirectory("emufusion-cheat-archive").toFile();
        File archive = new File(directory, "cheats.zip");
        try (ZipOutputStream output = new ZipOutputStream(Files.newOutputStream(archive.toPath()))) {
            for (int index = 0; index < 998; index++)
                write(output, NES + "Fixture " + index + ".cht",
                        "cheats = 1\ncheat0_desc = \"Fixture\"\ncheat0_code = \"1234:56\"\n");
            write(output, PSP + "God of War - Chains of Olympus (USA).cht",
                    "cheats = 4\n"
                    + "cheat0_desc = \"Infinite Health\"\n"
                    + "cheat0_code = \"1111:22\"\n"
                    + "cheat1_desc = \"Duplicate spelling\"\n"
                    + "cheat1_code = \"  1111:22  \"\n"
                    + "cheat2_desc = \"Needs a value\"\n"
                    + "cheat2_code = \"2222:XX\"\n"
                    + "cheat3_desc = \"\"\n"
                    + "cheat3_code = \"3333:44\"\n");
            write(output, PSP + "God of War - Chains of Olympus (Europe).cht",
                    "cheats = 2\n"
                    + "cheat0_desc = \"Same code in Europe\"\n"
                    + "cheat0_code = \"1111:22\"\n"
                    + "cheat1_desc = \"European code\"\n"
                    + "cheat1_code = \"5555:66\"\n");
            write(output, PSP + "God of War - Chains of Olympus (Demo) (USA).cht",
                    "cheat0_desc = \"Demo-only address\"\n"
                    + "cheat0_code = \"7777:88\"\n");
            write(output, PSP + "Serial Game [US] [ULUS-12345].cht",
                    "cheat0_desc = \"US address\"\ncheat0_code = \"AAAA:01\"\n");
            write(output, PSP + "Serial Game [EU] [ULES-54321].cht",
                    "cheat0_desc = \"EU address\"\ncheat0_code = \"BBBB:02\"\n");
            write(output, SG1000 + "Zaxxon (World).cht",
                    "cheat0_desc = \"Infinite Lives\"\ncheat0_code = \"1122:33\"\n");
            write(output, MSX + "Metal Gear (Japan).cht",
                    "cheat0_desc = \"Infinite Ammo\"\ncheat0_code = \"4455:66\"\n");
        }

        CheatArchive.verify(archive);
        List<Cheat> cheats = CheatArchive.forGame(archive, "psp",
                "God of War: Chains of Olympus", "God of War - Chains of Olympus (USA).iso");
        check(cheats.size() == 2, "exact region was not preferred: " + cheats.size());
        check("Infinite Health".equals(cheats.get(0).name), "stable source order changed");
        check(cheats.get(0).description.contains("USA"), "variant provenance is missing");
        check("Cheat 4".equals(cheats.get(1).name), "blank descriptions need a usable label");
        for (Cheat cheat : cheats)
            check(!cheat.code.contains("XX"), "unresolved parameter escaped filtering");
        check(cheats.stream().noneMatch(cheat -> cheat.code.equals("7777:88")),
                "retail lookup incorrectly included the demo executable");

        List<Cheat> aggregate = CheatArchive.forGame(archive, "psp",
                "God of War: Chains of Olympus", "God of War - Chains of Olympus.iso");
        check(aggregate.size() == 3, "unknown region did not aggregate variants");
        check(aggregate.get(2).description.contains("Europe"),
                "aggregated variant provenance is missing");

        List<Cheat> serial = CheatArchive.forGame(archive, "psp", "Serial Game",
                "Serial Game [ULUS-12345].iso");
        check(serial.size() == 1 && "AAAA:01".equals(serial.get(0).code),
                "exact PSP serial did not outrank title aggregation");

        // Coverage expansion (2026-09-06): sg1000 was already declared a
        // covered system by CheatSourceRegistry's LIBRETRO row but had no
        // SYSTEM_FOLDERS entry, so it silently matched nothing; msx is a
        // verified-real addition (the libretro cht folder exists).
        List<Cheat> sg1000 = CheatArchive.forGame(archive, "sg1000", "Zaxxon", "Zaxxon (World).sg");
        check(sg1000.size() == 1 && "1122:33".equals(sg1000.get(0).code),
                "sg1000 folder mapping resolves: " + sg1000);
        List<Cheat> msx = CheatArchive.forGame(archive, "msx", "Metal Gear", "Metal Gear (Japan).rom");
        check(msx.size() == 1 && "4455:66".equals(msx.get(0).code),
                "msx folder mapping resolves: " + msx);

        File unsafe = new File(directory, "unsafe.zip");
        try (ZipOutputStream output = new ZipOutputStream(Files.newOutputStream(unsafe.toPath()))) {
            write(output, "../escape.cht", "cheat0_code = \"1234:56\"\n");
        }
        boolean rejected = false;
        try { CheatArchive.verify(unsafe); }
        catch (IOException expected) { rejected = true; }
        check(rejected, "path-traversing archive was accepted");

        delete(directory);
        System.out.println("Cheat archive probe passed");
    }

    private static void write(ZipOutputStream output, String name, String body)
            throws IOException {
        output.putNextEntry(new ZipEntry(name));
        output.write(body.getBytes(StandardCharsets.UTF_8));
        output.closeEntry();
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void delete(File file) {
        if (file == null || !file.exists()) return;
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children != null) for (File child : children) delete(child);
        }
        if (!file.delete()) file.deleteOnExit();
    }
}
