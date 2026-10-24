"""Run RomCatalogName (checksum -> No-Intro name -> libretro thumbnail) on fixtures.

On the Thor, 233 of 455 games recorded as having no box art in any source had
it in libretro's catalog under their No-Intro name, which only the ROM's
checksum reveals (owner, 2026-10-24: find the artwork; stop only when it
really cannot be found). This compiles the production class unchanged.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.tests.test_first_install_startup import JAVA, ROOT

SOURCE = ROOT / 'android-companion/src/com/thorium/preview/RomCatalogName.java'
IMPORTER = ROOT / 'android-companion/src/com/thorium/preview/ImportManager.java'

PROBE = r'''
package com.thorium.preview;

import java.io.File;
import java.nio.file.Files;
import java.util.Map;
import java.util.zip.CRC32;

public class RomCatalogNameProbe {
  static void check(boolean condition, String message) {
    if (!condition) throw new AssertionError(message);
  }
  static String crc(byte[] data) {
    CRC32 crc = new CRC32(); crc.update(data, 0, data.length);
    return String.format("%08X", crc.getValue());
  }
  static byte[] payload(int length) {
    byte[] data = new byte[length];
    for (int i = 0; i < length; i++) data[i] = (byte) (i * 31 + (i >> 9));
    return data;
  }
  static File write(File dir, String name, byte[] head, byte[] body) throws Exception {
    File file = new File(dir, name);
    byte[] all = new byte[head.length + body.length];
    System.arraycopy(head, 0, all, 0, head.length);
    System.arraycopy(body, 0, all, head.length, body.length);
    Files.write(file.toPath(), all);
    return file;
  }
  public static void main(String[] args) throws Exception {
    File dir = new File(args[0]);
    // Larger than one read buffer, and not a multiple of it.
    byte[] rom = payload(600 * 1024 + 4);

    File gba = write(dir, "plain.gba", new byte[0], rom);
    check(crc(rom).equals(RomCatalogName.crc32(gba, "gba")), "A headerless dump hashes whole");

    byte[] ines = new byte[16]; ines[0] = 'N'; ines[1] = 'E'; ines[2] = 'S'; ines[3] = 0x1A; ines[4] = 2;
    File nes = write(dir, "game.nes", ines, rom);
    check(crc(rom).equals(RomCatalogName.crc32(nes, "nes")), "The iNES header is not part of the dump");

    byte[] snesBody = payload(512 * 1024);
    File snes = write(dir, "copier.smc", new byte[512], snesBody);
    check(crc(snesBody).equals(RomCatalogName.crc32(snes, "snes")), "A 512-byte copier header is skipped");
    File snesClean = write(dir, "clean.sfc", new byte[0], snesBody);
    check(crc(snesBody).equals(RomCatalogName.crc32(snesClean, "snes")), "A clean SNES dump is untouched");

    byte[] z64 = payload(256 * 1024 + 8);
    z64[0] = (byte) 0x80; z64[1] = 0x37; z64[2] = 0x12; z64[3] = 0x40;
    byte[] v64 = new byte[z64.length], n64 = new byte[z64.length];
    for (int i = 0; i < z64.length; i += 4) {
      v64[i] = z64[i + 1]; v64[i + 1] = z64[i]; v64[i + 2] = z64[i + 3]; v64[i + 3] = z64[i + 2];
      n64[i] = z64[i + 3]; n64[i + 1] = z64[i + 2]; n64[i + 2] = z64[i + 1]; n64[i + 3] = z64[i];
    }
    String expected = crc(z64);
    check(expected.equals(RomCatalogName.crc32(write(dir, "a.z64", new byte[0], z64), "n64")), "z64");
    check(expected.equals(RomCatalogName.crc32(write(dir, "a.v64", new byte[0], v64), "n64")),
          "A byte-swapped .v64 hashes as the big-endian dump");
    check(expected.equals(RomCatalogName.crc32(write(dir, "a.n64", new byte[0], n64), "n64")),
          "A little-endian .n64 hashes as the big-endian dump");

    check(RomCatalogName.crc32(new File(dir, "missing.gba"), "gba").isEmpty(), "Unreadable is empty");

    // libretro-database publishes clrmamepro text, not Logiqx XML.
    String clrmamepro = "clrmamepro (\n\tname \"Nintendo - Game Boy Advance\"\n)\n\n" +
        "game (\n\tname \"2 Games in One! - Dr. Mario + Puzzle League (USA)\"\n\tregion \"USA\"\n" +
        "\trom ( name \"2 Games in One! - Dr. Mario + Puzzle League (USA).gba\" size 8388608 crc 1A2B3C4D md5 00 sha1 00 )\n)\n\n" +
        "game (\n\tname \"DragonHeart (USA, Europe)\"\n" +
        "\trom ( name \"DragonHeart (USA, Europe).gb\" size 131072 crc deadbeef )\n)\n";
    Map<String, String> names = RomCatalogName.parseDat(clrmamepro);
    check("2 Games in One! - Dr. Mario + Puzzle League (USA)".equals(names.get("1A2B3C4D")),
          "clrmamepro game names are read, not the rom file name: " + names);
    check("DragonHeart (USA, Europe)".equals(names.get("DEADBEEF")), "CRCs are upper case");
    check(names.size() == 2, "The header block is not a game: " + names);

    String xml = "<datafile><game name=\"Tom &amp; Jerry (USA)\">\n" +
        "<rom name=\"Tom &amp; Jerry (USA).gb\" size=\"1\" crc=\"0badf00d\"/>\n</game></datafile>";
    check("Tom & Jerry (USA)".equals(RomCatalogName.parseDat(xml).get("0BADF00D")), "Logiqx XML too");

    check("2 Games in One! - Dr. Mario + Puzzle League (USA).png".equals(
          RomCatalogName.thumbnailName("2 Games in One! - Dr. Mario + Puzzle League (USA)")),
          "'+' and '!' are kept in thumbnail names");
    check("Tom _ Jerry_ Frantic (USA).png".equals(RomCatalogName.thumbnailName("Tom & Jerry: Frantic (USA)")),
          "libretro replaces &*/:`<>?\\|\" with _");
    check("Super Puzzle Fighter II".equals(
          RomCatalogName.baseTitle("Super Puzzle Fighter II (USA) (Rev 1)")), "Tags are dropped");
    check(RomCatalogName.datUrl("Nintendo - Game Boy Advance").endsWith(
          "/metadat/no-intro/Nintendo%20-%20Game%20Boy%20Advance.dat"), "DAT named like the catalog");
    check(RomCatalogName.supported("gba") && RomCatalogName.supported("nes") &&
          !RomCatalogName.supported("psx") && !RomCatalogName.supported("switch"),
          "Only whole-file cartridge systems");
    System.out.println("PASS");
  }
}
'''


class RomCatalogNameTest(unittest.TestCase):
    def test_checksums_dats_and_thumbnail_names(self):
        with tempfile.TemporaryDirectory(prefix='emufusion-rom-catalog-') as temp:
            folder = Path(temp)
            package = folder / 'src/com/thorium/preview'
            package.mkdir(parents=True)
            (package / 'RomCatalogName.java').write_text(SOURCE.read_text())
            (package / 'RomCatalogNameProbe.java').write_text(PROBE)
            classes = folder / 'classes'
            subprocess.run([str(JAVA / 'javac'), '-d', str(classes),
                            str(package / 'RomCatalogName.java'),
                            str(package / 'RomCatalogNameProbe.java')],
                           check=True, capture_output=True, text=True)
            data = folder / 'data'
            data.mkdir()
            result = subprocess.run([str(JAVA / 'java'), '-cp', str(classes),
                                     'com.thorium.preview.RomCatalogNameProbe', str(data)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS', result.stdout)

    def test_importer_asks_by_checksum_before_title(self):
        source = IMPORTER.read_text()
        box = source[source.index('private void enrichBoxArt('):][:1600]
        self.assertLess(box.index('noIntroMatch(game, cacheRoot, "Named_Boxarts")'),
                        box.index('boxArtMatch(game.system, game.title, cacheRoot)'))
        self.assertIn('for (String title : lookupTitles(game))', box)
        background = source[source.index('private void resolveBackground('):]
        self.assertIn('noIntroMatch(game, cacheRoot, "Named_Snaps")', background)
        # An unreachable DAT is unanswered, and title matching still runs.
        lookup = source[source.index('private CatalogMatch noIntroMatch('):][:2200]
        self.assertIn('noteUnanswered(unavailable);', lookup)
        self.assertIn('return null;', lookup)
        # Box art and wallpaper misses from before the lookup are asked again.
        self.assertIn('"2026-10-24:no-intro,', source)
        # A catalog href's '+' is literal (Dr. Mario + Puzzle League).
        self.assertIn('URLDecoder.decode(value.replace("+", "%2B"), "UTF-8")', source)


if __name__ == '__main__':
    unittest.main()
